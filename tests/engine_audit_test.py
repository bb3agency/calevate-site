"""Engine-boundary + webhook-receiver audit (hard rules 2 and 3).

Two questions, one file:

1. **Is the conformance suite strict enough to be worth running?** A suite that every
   adapter passes tells you nothing unless a WRONG adapter fails it. So the first
   section builds deliberately broken adapters — each one wrong in a way that would
   cost real money or break a real guarantee — and asserts the suite catches each. A
   saboteur that slips through is a hole in the contract, not a clever adapter.

2. **Is the receiver's every response a deliberate one?** Bolna signs nothing (D-31),
   so anyone who learns the URL can POST anything at it: 30MB of JSON, 10,000 nested
   arrays, a body that is not JSON at all, an engine name we never deployed. None of
   those may 500, and every one of them must be answerable from `X-Ack-Ms`.

Scoped for a shared database: every execution id and status here is uuid-unique, so
these assertions stay true while other suites write to the same tables.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import engine_intake
import httpx
import pytest
import webhook_routes
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import get_engine as get_db_engine
from apps.api.db.session import untenanted_session
from apps.api.engine import vendor_http
from apps.api.engine.bolna import BolnaEngine
from apps.api.engine.fake import (
    DEFAULT_FAKE_CAPABILITIES,
    EXTERNAL_DEPLOYMENT_CAPABILITIES,
    FakeEngine,
)
from apps.api.reliability import service as reliability
from apps.api.reliability.service import body_hash
from calevate_shared.config import (
    DEFAULT_BOLNA_SOURCE_IPS,
    Settings,
    parse_source_ip_allowlist,
)
from calevate_shared.engine import (
    AgentConfig,
    AgentSnapshot,
    CallContext,
    CostBreakdown,
    ExecutionListing,
    ExecutionSnapshot,
    NumberSpec,
    ProvisionedNumber,
    VoiceEngine,
    WebhookVerdict,
)
from calevate_shared.events import CallEvent, TranscriptTurn
from httpx import ASGITransport, AsyncClient
from main import app as voice_app
from sqlalchemy import event, text

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE_DIR = REPO_ROOT / "packages" / "shared" / "tests" / "engine_conformance"

# RFC 5737 documentation addresses: unroutable, so copying one into a real config is
# inert rather than dangerous.
ENGINE_EGRESS_IP = "198.51.100.7"
ATTACKER_IP = "203.0.113.9"
EDGE_PROXY_IP = "127.0.0.1"

HOOK = "/hooks/v1/engine/bolna"


# =============================================================================
# Section 1 — is the conformance suite strict enough?
# =============================================================================


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _suite() -> ModuleType:
    return _load(CONFORMANCE_DIR / "contract_test.py", "audit_conformance_contract")


def _suite_fixtures() -> ModuleType:
    return _load(CONFORMANCE_DIR / "conftest.py", "audit_conformance_conftest")


async def _conformance_failures(engine: VoiceEngine) -> list[str]:
    """Run every clause of the conformance suite against one adapter.

    Returns the names of the clauses that rejected it. An empty list means the suite
    considers this adapter conformant.
    """
    suite = _suite()
    fixtures = _suite_fixtures()
    failures: list[str] = []
    for name, fn in vars(suite).items():
        if not name.startswith("test_") or not inspect.iscoroutinefunction(fn):
            continue
        # A clause may ask for the adapter in a particular STATE — `saturated_engine` is
        # one whose listing has been driven to a full page. The parameter name is how the
        # suite says so to pytest, so it is how this harness reads it too; a clause whose
        # setup this loop cannot perform is a clause no saboteur below can ever fail.
        wants = next(iter(inspect.signature(fn).parameters), "engine")
        if wants == LADDER_PARAM:
            # NOT SKIPPED QUIETLY — see `test_the_transport_clauses_reject_a_drifted_
            # ladder`, which is this function's counterpart for exactly these clauses.
            # Their subject is not an adapter but a BUILDER that puts an HTTP-speaking
            # adapter over a transport the clause writes; every saboteur in this file is
            # a `FakeEngine`, which has no transport to point anywhere, so handing one in
            # would fail these clauses with a `TypeError` for a reason that has nothing
            # to do with the saboteur. That would make every saboteur below look better
            # covered than it is.
            continue
        subject = fixtures.saturated(engine) if wants == "saturated_engine" else engine
        try:
            await fn(subject)
        except AssertionError:
            failures.append(name)
        except Exception as exc:  # a crash is a caught divergence too
            failures.append(f"{name}[{type(exc).__name__}]")
    return failures


class _AcceptsAnySource(FakeEngine):
    """Claims a real verification method, then waves everyone through.

    This is THE adapter bug that matters at an unsigned endpoint: `method="source_ip"`
    is what tells the receiver it holds evidence, and here the evidence is fiction.
    """

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        return WebhookVerdict(ok=True, method="source_ip")


class _DropsAgentRef(FakeEngine):
    """Snapshots with no `engine_agent_ref`.

    `ExecutionSnapshot.engine_agent_ref` is the ONLY bridge from the vendor's world to
    a tenant, and the reconciliation poller — the guarantee of record under D-31 — has
    no webhook payload to read it from. An adapter that drops it makes every repaired
    call unmappable, and the failure is invisible until a call goes missing.
    """

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        return (await super().get_execution(call_id)).model_copy(update={"engine_agent_ref": None})

    async def list_executions(self, *, since: Any) -> ExecutionListing:
        listing = await super().list_executions(since=since)
        return listing.model_copy(
            update={
                "snapshots": [
                    snapshot.model_copy(update={"engine_agent_ref": None})
                    for snapshot in listing.snapshots
                ]
            }
        )


class _UnstampedCost(FakeEngine):
    """A cost with no fx rate and no source amount.

    Hard rule 7 and `CostBreakdown`'s own docstring: the adapter converts at capture
    and STAMPS the rate it used, so a ledger row can always be re-derived. Strip the
    stamp and every usage_event becomes an unauditable number.
    """

    def _cost_for(self, duration_s: int) -> CostBreakdown:
        cost = super()._cost_for(duration_s)
        return cost.model_copy(update={"fx_rate": None, "source_amount": None})


class _DirectionLiar(FakeEngine):
    """Calls every call outbound, including inbound ones.

    Direction decides which compliance obligations attach (DNC, calling hours,
    140/160 series). Getting it wrong in this direction over-regulates; the contract
    still has to pin it, because the same hole passes an adapter that gets it wrong
    the other way.
    """

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        return super().parse_webhook(payload).model_copy(update={"direction": "outbound"})


class _ForeignTranscript(FakeEngine):
    """Turns tagged with somebody else's call id — a cross-call transcript leak."""

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        snapshot = await super().get_execution(call_id)
        return snapshot.model_copy(
            update={
                "transcript": [
                    TranscriptTurn(
                        call_id="some_other_call",
                        idx=turn.idx,
                        speaker=turn.speaker,
                        text=turn.text,
                    )
                    for turn in snapshot.transcript
                ]
            }
        )


class _ForgetsRawStatus(FakeEngine):
    """Normalizes the status and throws the vendor's own word away.

    `raw_status` is what the forensic `webhook_deliveries` row records and what the
    ingest job is keyed on. Without it, 'why was this call marked failed' has no
    answer that does not involve reading the vendor's dashboard.
    """

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        return super().parse_webhook(payload).model_copy(update={"raw_status": None})


class _EchoesTheLastWrite(FakeEngine):
    """A read-back that returns whatever was written LAST, for any agent asked about.

    The defect that makes `get_agent` worthless while looking like it works: it agrees
    with the caller by construction, so gate 2 would score every prompt update APPLIED —
    including one the vendor silently dropped — and would score it APPLIED for agents
    that were never touched. This is the reason the conformance clause reads TWO agents
    back instead of one; against a single agent, an echo and a real read-back are
    indistinguishable.
    """

    def __init__(self, **kwargs: Any) -> None:
        # The audit harness re-constructs a saboteur to reach the saturated-listing
        # clause (`conftest.saturated`), so the base engine's kwargs must pass through.
        super().__init__(**kwargs)
        self._last_write: AgentConfig | None = None

    async def create_agent(self, cfg: AgentConfig) -> str:
        self._last_write = cfg
        return await super().create_agent(cfg)

    async def update_agent(self, ref: str, cfg: AgentConfig) -> None:
        self._last_write = cfg
        await super().update_agent(ref, cfg)

    async def get_agent(self, ref: str) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        if self._last_write is None:
            return snapshot
        sent = self._last_write
        return snapshot.model_copy(
            update={"system_prompt": f"{sent.disclosure_line}\n\n{sent.system_prompt}"}
        )


class _ArchivesNothing(FakeEngine):
    """Carries no raw document out of `get_execution` — the shipped state D-126 lived in.

    `storage.archive_payload`, `calls.engine_payload_ref` and
    `retention._erase_engine_payloads` all exist; with no document to archive they guard a
    store nothing writes to, and TRD §5's escape valve for hard rule 2 (raw vendor payloads
    in object storage, never in typed columns) describes an empty bucket. Nothing 500s,
    nothing logs, every other clause passes — which is why it needs a clause of its own.
    """

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        return (await super().get_execution(call_id)).model_copy(update={"raw_document": None})


class _ArchivesOneDocumentForEveryCall(FakeEngine):
    """Answers every execution with the same bytes.

    Subtler than carrying none and worse in one way: the archive EXISTS, under each call's
    own erasure prefix, and describes none of them. An operator reconciling a disputed
    call would read a document belonging to no call and have no way to tell.
    """

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        snapshot = await super().get_execution(call_id)
        return snapshot.model_copy(update={"raw_document": b'{"execution_id":"the-same-one"}'})


class _ClaimsToReadKbRefsAndReadsNone(FakeEngine):
    """Reports `knowledge_base_refs_readable=True` with an empty list.

    D-41's failure mode in one line: "the agent references nothing" is a claim, and an
    adapter that makes it without looking closes the dangling-`rag_id` question in the
    direction that adds no work to our code. Declining (`readable=False`) is conformant;
    a confident empty answer is not.
    """

    async def get_agent(self, ref: str) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        return snapshot.model_copy(update={"knowledge_base_refs": []})


# --- saboteurs that lie in the CAPABILITY DESCRIPTOR (D-93) -------------------
#
# Every saboteur above breaks a BEHAVIOUR. These break a DECLARATION, which is the more
# dangerous half: a wrong behaviour surfaces as a failed call, while a wrong declaration
# surfaces as a screen confidently offering a control that cannot work. The descriptor is
# only worth having if the suite can catch an adapter lying in it — otherwise it converts
# a runtime failure into a confident wrong answer, which is strictly worse than nothing.


def _with_capabilities(**changes: object) -> Callable[[], VoiceEngine]:
    """A `fake` adapter whose DESCRIPTOR is altered and whose behaviour is not.

    That combination is the whole point: each of these adapters does exactly what the
    shipped `fake` adapter does, and only its claims about itself are wrong. A saboteur
    that also changed behaviour could be caught by a behavioural clause and tell us
    nothing about whether the declaration is checked.
    """

    def build() -> VoiceEngine:
        return FakeEngine(
            capabilities=DEFAULT_FAKE_CAPABILITIES.model_copy(update=changes),
            # Sabotaged descriptors keep the shipped name so `WEBHOOK_AUTH_BY_ENGINE`
            # still has an entry to be contradicted — a saboteur under an unknown name
            # would fail the table clause for the wrong reason and prove nothing.
            name="fake",
        )

    return build


class _AcceptsAVoiceItSaysItCannotSpeak(FakeEngine):
    """Declares that the ENGINE dictates TTS, then accepts our voice anyway.

    THE headline failure this slice exists to remove, staged. Nothing errors: the
    operator picks Bulbul v3, the row saves, the publish returns 200, and the caller
    hears the engine's own voice forever. Every screen goes on reporting the voice that
    was chosen, because from our side nothing ever said otherwise.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault(
            "capabilities", DEFAULT_FAKE_CAPABILITIES.model_copy(update={"tts": "engine"})
        )
        super().__init__(**kwargs)

    def _assert_speech_is_ours(self, cfg: AgentConfig) -> None:
        return  # the silent drop


class _SubstitutesItsOwnVoice(FakeEngine):
    """Claims BYOK TTS and reports a DIFFERENT voice than the one configured.

    The vendor accepted the write and is running something else — accepted, not applied,
    for the one setting a client can hear. Distinct from the saboteur above because this
    adapter refuses nothing and hides nothing at write time; the divergence is only ever
    visible in the read-back, which is why `AgentSnapshot.models` had to exist.
    """

    async def get_agent(self, ref: str) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        assert snapshot.models is not None
        return snapshot.model_copy(
            update={"models": snapshot.models.model_copy(update={"tts_voice": "sonic-3.5"})}
        )


class _ProvisionsANumberItDenies(FakeEngine):
    """Declares it provisions no number class and hands one back regardless.

    Not hypothetical — this was the SHIPPED behaviour of the `fake` adapter while the
    Bolna adapter raised, so the two adapters disagreed about whether the platform can
    buy a number and nothing could see it. A number returned here is recorded as dialable
    and matched against a campaign's 140/160 classification by the launch gate.
    """

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        return ProvisionedNumber(
            e164="+911140000000", provider="nobody", engine_number_ref="n_1", series=spec.series
        )


class _AnswersKbQuestionsItHasNoKbFor(FakeEngine):
    """Declares no knowledge base and answers `list_kb` with a cheerful empty list.

    The quietest one here and the worst. `[]` is a POSITIVE claim that the agent holds no
    documents, and `kb/service._reconcile_engine_state` reads exactly that claim to decide
    whether the engine is serving text our rows cannot account for — so this adapter tells
    the publish path "everything is accounted for" every single time, about a question it
    was never able to answer.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault(
            "capabilities",
            DEFAULT_FAKE_CAPABILITIES.model_copy(update={"knowledge_base": False}),
        )
        super().__init__(**kwargs)

    async def list_kb(self, ref: str) -> list[str]:
        return []


class _ClaimsATransferItCannotPerform(FakeEngine):
    """Advertises engine-side transfer and does nothing at all.

    The hardest declaration to check and the one that found a hole in the clause meant to
    check it. `transfer` returns None and the Protocol has no read-back, so "transferred"
    and "did nothing" are the same observation from above — this saboteur passed a first
    version of the transfer clause that only asserted no exception was raised. What
    catches it is the one thing an adapter that can really transfer must still be able to
    do: FAIL a transfer for a call the engine does not hold.

    The stake: the escalation path is what a caller reaches when the agent cannot help
    them, so a transfer that silently does nothing leaves a real person in silence while
    the console reports an escalation that never happened.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault(
            "capabilities", DEFAULT_FAKE_CAPABILITIES.model_copy(update={"transfer": True})
        )
        super().__init__(**kwargs)

    async def transfer(self, call_id: str, to: str, warm: bool) -> None:
        return


class _HostsAgentsItSaysItDoesNot(FakeEngine):
    """Declares that its agents are deployed elsewhere, then creates and serves one anyway.

    THE DESCRIPTOR LIE THIS SLICE EXISTS TO REMOVE, staged the way it would actually
    arrive: somebody sets `agent_hosting="external_deployment"` on an adapter to silence a
    publish failure, and leaves the write path doing what it always did. Nothing errors —
    the publish still refuses at `publish_agent` because the SEAM reads the descriptor, so
    the only thing that changes is that the descriptor and the adapter now disagree, and
    the next reader believes whichever they looked at first.

    It matters more than a mislabel: the same declaration decides where hard rule 5 lives.
    An adapter claiming this shape is claiming the truthful-answer rule rides its calls,
    and this one carries no prompt on a dial at all.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault(
            "capabilities",
            DEFAULT_FAKE_CAPABILITIES.model_copy(update={"agent_hosting": "external_deployment"}),
        )
        super().__init__(**kwargs)

    def _assert_this_engine_hosts_agents(self) -> None:
        return  # the silent acceptance


class _DialsWithoutTheTruthfulAnswerRule(FakeEngine):
    """Declares agents deployed elsewhere AND drops the compliance floor on every dial.

    The quietest failure in this file and the only one with a legal consequence. On this
    shape there is no agent record holding the truthful-answer directive and no read-back
    to score, so `CallContext.system_prompt` is the only vehicle — and an adapter that
    places the call regardless has produced an agent that can be scripted into claiming it
    is human, with nothing anywhere able to detect it afterwards. `start_outbound_call`
    returns a handle and no read-back, so from every screen we own this looks identical to
    a working dial.

    It differs from the saboteur above by keeping the agent methods honest: only the DIAL
    is wrong, which is exactly the residue a fix aimed at the publish path would leave.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("capabilities", EXTERNAL_DEPLOYMENT_CAPABILITIES)
        kwargs.setdefault("name", "fake")
        super().__init__(**kwargs)

    async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
        # No `require_call_compliance_floor`, and the prompt is thrown away rather than
        # carried — the two halves of the drop, together, because an adapter that checked
        # and then dropped would be caught by the guard alone.
        handle = self._stable_id("fakecall", ref, to, ctx.lead_id or "", str(len(self._calls)))
        self._calls[handle] = {
            "agent_ref": ref,
            "direction": "outbound",
            "status": "completed",
            "started_at": datetime.now(UTC) - timedelta(seconds=95),
            "ended_at": datetime.now(UTC),
            "duration_s": 95,
            "from_e164": "+911140000000",
            "to_e164": to,
            "context": ctx.model_dump(),
            "system_prompt": None,
        }
        return handle


SABOTEURS: dict[str, Callable[[], VoiceEngine]] = {
    "agent-read-back-echoes-the-last-write": _EchoesTheLastWrite,
    "archives-nothing": _ArchivesNothing,
    "archives-one-document-for-every-call": _ArchivesOneDocumentForEveryCall,
    "claims-to-read-kb-refs-and-reads-none": _ClaimsToReadKbRefsAndReadsNone,
    "accepts-any-source-ip": _AcceptsAnySource,
    "drops-engine-agent-ref": _DropsAgentRef,
    "cost-without-fx-stamp": _UnstampedCost,
    "lies-about-direction": _DirectionLiar,
    "transcript-of-another-call": _ForeignTranscript,
    "forgets-raw-status": _ForgetsRawStatus,
    # Descriptor lies. See the block comment above.
    "accepts-a-voice-it-says-it-cannot-speak": _AcceptsAVoiceItSaysItCannotSpeak,
    "substitutes-its-own-voice": _SubstitutesItsOwnVoice,
    "provisions-a-number-it-denies": _ProvisionsANumberItDenies,
    "answers-kb-questions-it-has-no-kb-for": _AnswersKbQuestionsItHasNoKbFor,
    # Declares a webhook method it does not use. The receiver reads the DECLARATION
    # (through `WEBHOOK_AUTH_BY_ENGINE`) while the worker reads the adapter's verdict, so
    # a mismatch means the two services authenticate the same delivery differently.
    "declares-a-webhook-method-it-does-not-use": _with_capabilities(webhook_auth="source_ip"),
    # Claims an engine-side capability the Protocol has no method for, and which our
    # dispatch does not use. Unfalsifiable by construction, which is why the suite
    # refuses the claim outright rather than pretending to test it.
    "claims-engine-side-campaigns": _with_capabilities(campaigns=True),
    "claims-a-transfer-it-cannot-perform": _ClaimsATransferItCannotPerform,
    # Agent hosting (D-280). The first is the descriptor lie; the second keeps the
    # descriptor honest and drops hard rule 5's only vehicle on that shape.
    "hosts-agents-it-says-it-does-not": _HostsAgentsItSaysItDoesNot,
    "dials-without-the-truthful-answer-rule": _DialsWithoutTheTruthfulAnswerRule,
}


@pytest.mark.parametrize("saboteur", sorted(SABOTEURS))
async def test_the_conformance_suite_rejects_a_deliberately_broken_adapter(
    saboteur: str,
) -> None:
    """The suite's whole value is that a wrong adapter cannot pass it.

    Each saboteur below is the `fake` adapter with exactly ONE behaviour replaced by
    something that would break a documented guarantee. If the suite lets one through,
    then the clause it was supposed to encode is not actually tested, and the promise
    that "a second engine changes one package" is untested folklore.
    """
    failures = await _conformance_failures(SABOTEURS[saboteur]())
    assert failures, (
        f"the conformance suite accepted the '{saboteur}' adapter — "
        "that behaviour is not covered by any clause"
    )


#: The parameter name the transport-ladder clauses use for their subject. One spelling,
#: shared by the skip above and the runner below, so the two cannot disagree about which
#: clauses this file covers by the other route.
LADDER_PARAM = "ladder"


class _DriftedLadder(BolnaEngine):
    """A real HTTP adapter whose transport ladder has drifted back to where it was.

    This is not an invention: it is `cartesia._request` as it stood before D-240 —
    no 429 handling at all, and a 2xx whose body will not parse collapsed into `{}`. It
    is kept as a saboteur rather than deleted with the bug because the transport clauses
    are the only thing standing between a future adapter and the same two answers, and a
    clause nothing can fail is not a clause.
    """

    async def _request(
        self, method: str, path: str, *, absent_is_success: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        try:
            response = await self._http().request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProblemError(
                kind="dependency",
                code="engine_unreachable",
                title="Voice engine unreachable",
                detail="The voice platform did not respond.",
            ) from exc
        if absent_is_success and response.status_code == 404:
            return {}
        if response.status_code >= 400:
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform refused the request.",
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return payload if isinstance(payload, dict) else {"data": payload}


def _drifted_ladder(handler: Callable[[httpx.Request], httpx.Response]) -> BolnaEngine:
    return _DriftedLadder(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai", transport=httpx.MockTransport(handler)
        ),
    )


async def _transport_clause_failures(
    build: Callable[[Callable[[httpx.Request], httpx.Response]], Any],
) -> list[str]:
    """Run every TRANSPORT-ladder clause against one adapter builder."""
    suite = _suite()
    failures: list[str] = []
    for name, fn in vars(suite).items():
        if not name.startswith("test_") or not inspect.iscoroutinefunction(fn):
            continue
        if next(iter(inspect.signature(fn).parameters), "engine") != LADDER_PARAM:
            continue
        try:
            await fn(build)
        except AssertionError:
            failures.append(name)
        except Exception as exc:  # a crash is a caught divergence too
            failures.append(f"{name}[{type(exc).__name__}]")
    return failures


async def test_the_transport_clauses_reject_a_drifted_ladder() -> None:
    """The counterpart to the saboteur run above, for the clauses it cannot reach.

    `_conformance_failures` skips the transport clauses because its saboteurs are all
    `FakeEngine`s with no transport. Without this, those clauses would be the only ones
    in the suite that nothing has ever been proven to fail — which is the state the
    transport ladder was already in before D-240, and the reason two adapters could
    disagree about a 429 for as long as they did.
    """
    failures = await _transport_clause_failures(_drifted_ladder)
    assert failures, (
        "the transport-ladder clauses accepted an adapter that swallows a 200 it cannot "
        "parse and reports a 429 as a flat rejection — they are not covering anything"
    )


async def test_the_transport_clauses_pass_every_shipped_adapter() -> None:
    """And the other half: the clauses were not tightened by inventing a rule the real
    adapters break."""
    fixtures = _suite_fixtures()
    for engine_id, build in fixtures.TRANSPORT_RECIPES.items():
        assert await _transport_clause_failures(build) == [], (
            f"{engine_id} fails a transport-ladder clause"
        )


async def test_the_shipped_adapters_still_pass_the_suite() -> None:
    """The other half: tightening the contract must not have been done by inventing a
    rule the real adapters break. Both shipped adapters pass every clause, unchanged."""
    fixtures = _suite_fixtures()
    for engine_id in fixtures.ENGINE_IDS:
        engine = fixtures.make_engine(engine_id)
        assert await _conformance_failures(engine) == [], f"{engine_id} adapter regressed"


# =============================================================================
# Section 2 — the receiver
# =============================================================================


@pytest.fixture(autouse=True)
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    """Point the allowlist at a documentation IP, exactly as the security suite does —
    these tests must never encode a vendor's current egress address."""
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client(peer_ip: str = EDGE_PROXY_IP) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444)),
        base_url="http://runtime",
    )


def _engine_headers() -> dict[str, str]:
    return {"CF-Connecting-IP": ENGINE_EGRESS_IP}


def _event(status: str | None = None) -> tuple[str, str, dict[str, Any]]:
    token = uuid.uuid4().hex[:12]
    execution_id = f"exec_{token}"
    event_status = f"{status or 'completed'}-{token}"
    return execution_id, event_status, {"execution_id": execution_id, "status": event_status}


async def _inbox_row(execution_id: str, raw_status: str) -> tuple[str, int] | None:
    """The inbox key is `{execution_id}:{raw_status}` — the unit of work is the
    TRANSITION, not the execution (D-40). Keying on the execution alone meant the first
    status change claimed the row and `completed`, the only one carrying cost, recording
    and transcript, was answered `duplicate` and never reached the queue."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, duplicate_count FROM webhook_inbox_events "
                    "WHERE provider = 'bolna' AND event_key = :k"
                ),
                {"k": f"{execution_id}:{raw_status}"},
            )
        ).first()
    return (str(row[0]), int(row[1])) if row else None


# --- 2a. every response path reports the ack budget ---------------------------


async def test_x_ack_ms_is_reported_on_every_response_path() -> None:
    """Hard rule 3 puts a NUMBER on this endpoint, and Bolna does not retry: a receiver
    that drifts past 500ms silently loses calls. `X-Ack-Ms` is the only per-request
    evidence anyone has.

    The paths that return early are exactly the ones a flood would take — a duplicate
    storm, a stream of unkeyable payloads, a scanner hammering the URL from off the
    allowlist. Those are the requests whose latency you most want to see, so reporting
    the header only on the happy path measures the endpoint at its least stressed.
    """
    execution_id, status, body = _event()

    async with _client() as http:
        accepted = await http.post(HOOK, json=body, headers=_engine_headers())
        duplicate = await http.post(HOOK, json=body, headers=_engine_headers())
        ignored = await http.post(HOOK, json={"status": "completed"}, headers=_engine_headers())
        rejected = await http.post(HOOK, json=body)  # peer is trusted, forwarded IP absent

    assert accepted.json()["status"] == "accepted"
    assert duplicate.json()["status"] == "duplicate"
    assert ignored.json()["status"] == "ignored"
    assert rejected.status_code == 401

    for label, response in (
        ("accepted", accepted),
        ("duplicate", duplicate),
        ("ignored", ignored),
        ("rejected", rejected),
    ):
        assert "X-Ack-Ms" in response.headers, f"the {label} path reports no ack time"
        assert float(response.headers["X-Ack-Ms"]) >= 0, f"the {label} path reports a non-number"

    assert await _inbox_row(execution_id, status) is not None


async def _inbox_payload_hash(execution_id: str, raw_status: str) -> str | None:
    """The hash the inbox actually stored for one transition.

    Read from the row rather than reasoned about: whether the receiver hands the inbox a
    hash of the DELIVERY or of the UNIT OF WORK decides whether every ordinary status
    transition raises `webhook_payload_mismatch`, and that is a fact about a column.
    """
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT payload_hash FROM webhook_inbox_events "
                    "WHERE provider = 'bolna' AND event_key = :k"
                ),
                {"k": f"{execution_id}:{raw_status}"},
            )
        ).scalar()


# --- 2b. hostile input is answered, never 500'd -------------------------------


async def test_a_deeply_nested_payload_is_answered_not_crashed() -> None:
    """`json.loads` raises RecursionError — NOT JSONDecodeError — on a deeply nested
    document, so a handler that catches only the decode error turns 20KB of `[[[[`
    into a 500.

    A 500 here is not merely ugly. Bolna delivers at most once and swallows errors, so
    the receiver crashing on one hostile POST is indistinguishable from the receiver
    crashing on the real call that arrives in the same second.
    """
    depth = 20_000
    hostile = ("[" * depth) + ("]" * depth)

    async with _client() as http:
        response = await http.post(
            HOOK,
            content=hostile.encode(),
            headers={**_engine_headers(), "Content-Type": "application/json"},
        )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "ignored"
    assert "X-Ack-Ms" in response.headers


@pytest.mark.parametrize(
    ("label", "content"),
    [
        ("not-json", b"this is not json at all"),
        ("bare-null", b"null"),
        ("top-level-list", b"[1, 2, 3]"),
        ("empty-body", b""),
        ("invalid-utf8", b"\xff\xfe\x00garbage"),
        ("id-is-an-object", b'{"execution_id": {"$ne": null}, "status": "completed"}'),
        ("id-is-a-number", b'{"execution_id": 12345, "status": "completed"}'),
    ],
)
async def test_a_malformed_payload_is_answered_not_crashed(label: str, content: bytes) -> None:
    """Every one of these is something a scanner sends on a Tuesday. Each must produce
    a deliberate answer — never a stack trace, never a 500."""
    async with _client() as http:
        response = await http.post(
            HOOK, content=content, headers={**_engine_headers(), "Content-Type": "application/json"}
        )

    assert response.status_code < 500, f"{label} produced {response.status_code}: {response.text}"
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert "X-Ack-Ms" in response.headers


async def test_an_oversized_body_is_refused_before_it_is_buffered() -> None:
    """`await request.body()` buffers whatever the caller sends. On an endpoint with no
    signature, no auth token and a public URL, that is an unbounded allocation driven
    by a stranger — on the one service in the estate that must not stall.

    Refusing is safe precisely because the payload is only a hint (D-31): the poller
    still picks the execution up. Buffering 200MB to be polite is not.
    """
    execution_id, status, _body = _event()
    huge = json.dumps(
        {"execution_id": execution_id, "status": status, "padding": "x" * (8 * 1024 * 1024)}
    ).encode()

    async with _client() as http:
        response = await http.post(
            HOOK, content=huge, headers={**_engine_headers(), "Content-Type": "application/json"}
        )

    assert response.status_code == 413, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "X-Ack-Ms" in response.headers
    assert await _inbox_row(execution_id, status) is None, "an oversized body must not claim a key"


# --- 2c. the fake engine is a dev affordance, not a public door ---------------


async def test_the_fake_engine_hook_is_closed_when_the_deployment_runs_a_real_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`verify_source` accepts the `fake` engine from ANY source IP — correct for local
    work, catastrophic in production. The route is mounted in every environment, so on
    a prod box running ENGINE=bolna a stranger can still POST `/hooks/v1/engine/fake`
    and get an inbox claim, a forensic row and an ARQ job for free.

    An unauthenticated queue-write is exactly the thing hard rule 3's verification step
    exists to prevent, and 'the payload is only a hint' is no comfort when the hint
    costs a worker fetch.
    """
    real_settings = engine_intake.get_settings()
    monkeypatch.setattr(
        engine_intake,
        "get_settings",
        lambda: real_settings.model_copy(update={"engine": "bolna"}),
    )

    execution_id, _status, body = _event()
    async with _client(ATTACKER_IP) as http:
        response = await http.post("/hooks/v1/engine/fake", json=body)

    assert response.status_code == 401, response.text
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_inbox_events "
                    "WHERE provider = 'fake' AND event_key = :k"
                ),
                {"k": execution_id},
            )
        ).scalar()
    assert rows == 0


async def test_the_fake_engine_hook_still_works_where_the_fake_engine_is_the_engine() -> None:
    """The mirror: `ENGINE=fake` is how the whole pipeline runs offline (DEV-SETUP §3),
    so closing the door in production must not close it locally."""
    assert engine_intake.get_settings().engine == "fake", "this suite runs on ENGINE=fake"
    _execution_id, _status, body = _event()
    async with _client(ATTACKER_IP) as http:
        response = await http.post("/hooks/v1/engine/fake", json=body)
    assert response.status_code == 202, response.text


# --- 2d. a status transition is not an attack --------------------------------


async def test_a_later_status_transition_is_not_reported_as_a_doctored_payload() -> None:
    """Bolna fires a webhook on every status transition (TRD §5): queued → in-progress
    → completed, all carrying the SAME execution id and DIFFERENT bodies.

    The receiver hands the inbox a hash of the whole delivery, and the inbox treats
    'same key, different hash' as evidence of a replayed doctored payload — a 409 plus
    a `webhook_payload_mismatch` alert. So on a healthy platform every single call
    raises a spoofing alarm, and the alarm that fires on every call is the alarm nobody
    reads when a real one arrives.

    The hash is therefore taken over the UNIT OF WORK rather than the delivery. D-40
    then settled what that unit is: the TRANSITION, `{execution_id}:{raw_status}` — so a
    later transition is new work and is accepted, while a REPEAT of one transition (a
    retry, whose body may legitimately have grown) is a counted duplicate. Both halves
    are asserted below, because the failure this test exists to prevent is a 409 plus a
    `webhook_payload_mismatch` alert on healthy traffic, and either half regressing
    brings it back.

    **WHAT "NOT REPORTED AS A DOCTORED PAYLOAD" ACTUALLY MEANS HERE, asserted rather than
    inferred (D-147).** This test used to reach its conclusion through `duplicate_count >=
    1`, which proved only that a second delivery had touched Postgres — and that is not the
    same claim. `duplicate_count` counts arrivals; it moves identically for a byte-identical
    replay and for a rewritten one, so it can neither report a doctored payload nor refute
    one. The three assertions below say the real thing instead:

    * no `webhook_payload_mismatch` alert fires, which is the alarm the title is about;
    * the `payload_hash` the inbox stores is a pure function of the KEY, recomputed here
      from both bodies and shown equal — so the inbox's "same key, different hash" branch
      is a tautology at this endpoint and cannot fire on a body change at all. That is the
      design (`_claim_and_enqueue` argues it) and it predates the fast-path key move;
    * the divergence is nevertheless COUNTED. Since nothing compares bodies at the durable
      layer, the fast path does it: its key is the transition and its VALUE is the digest of
      the delivery that settled it, so a replay with different bytes increments
      `webhook_replay_divergence` without costing a Postgres transaction. Before D-147 that
      replay cost three statements and produced no signal whatsoever.

    The fast-path key is deleted once, mid-test, so the durable claim is exercised too —
    otherwise every assertion here would be satisfied by Redis and the inbox would be
    untested.
    """
    token = uuid.uuid4().hex[:12]
    execution_id = f"exec_{token}"
    in_progress = f"in-progress-{token}"
    completed = f"completed-{token}"
    first = {"execution_id": execution_id, "status": in_progress}
    later = {"execution_id": execution_id, "status": completed, "total_cost": 8.5}
    # The same transition again, with MORE in the body — a retry that raced the vendor
    # finishing its own bookkeeping. Same work, different bytes.
    retry = {"execution_id": execution_id, "status": completed, "total_cost": 8.5, "extra": "x"}

    alerts: list[str] = []
    divergences: list[str] = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(reliability, "alert", lambda _stage, code, **_f: alerts.append(code))
        patch.setattr(webhook_routes, "alert", lambda _stage, code, **_f: alerts.append(code))
        patch.setattr(
            webhook_routes,
            "record_webhook_replay_divergence",
            lambda *, provider: divergences.append(provider),
        )
        async with _client() as http:
            opened = await http.post(HOOK, json=first, headers=_engine_headers())
            transitioned = await http.post(HOOK, json=later, headers=_engine_headers())
            # FIRST through the warm cache, which is the path production takes: the key
            # holds the digest of `later`, this body is `retry`, so the bytes diverge.
            cached = await http.post(HOOK, json=retry, headers=_engine_headers())
            # THEN with the key removed, so the inbox — where the tautology above lives —
            # is exercised rather than assumed.
            settled = f"calevate:wh:bolna:{execution_id}:{completed}"
            assert await get_redis().delete(settled) == 1, "the accepted transition was not cached"
            repeated = await http.post(HOOK, json=retry, headers=_engine_headers())

    assert opened.status_code == 202, opened.text
    assert opened.json()["status"] == "accepted"

    assert transitioned.status_code == 202, (
        "a legitimate status transition was answered "
        f"{transitioned.status_code}: {transitioned.text}"
    )
    assert transitioned.json()["status"] == "accepted", (
        "`completed` is the transition that carries cost, recording and transcript — "
        "absorbing it as a duplicate is how the pipeline stopped running from webhooks"
    )

    assert repeated.status_code == 202, (
        f"a retry of one transition was answered {repeated.status_code}: {repeated.text}"
    )
    assert repeated.json()["status"] == "duplicate", (
        "a bigger body for the same transition is a retry, not a doctored replay"
    )
    assert cached.json()["status"] == "duplicate", (
        "a fuller body must not defeat the cache; that was a free Postgres transaction "
        "per replay at an endpoint anyone past the source check can post to"
    )

    assert "webhook_payload_mismatch" not in alerts, (
        f"a fuller retry raised the spoofing alarm this test exists to keep quiet: {alerts}"
    )

    # The inbox is handed a hash of the UNIT OF WORK. Recomputed from the receiver's own
    # helper for both bodies: identical, therefore no body can ever produce a mismatch.
    unit = {"engine": "bolna", "execution_id": execution_id, "raw_status": completed}
    assert body_hash(unit) == body_hash(dict(unit)), "the hash must not depend on identity"
    assert body_hash(later) != body_hash(retry), "the premise: the two BODIES do differ"
    row = await _inbox_row(execution_id, completed)
    assert row is not None
    assert row[1] >= 1, "the retry reached the durable claim and was counted"
    stored = await _inbox_payload_hash(execution_id, completed)
    assert stored == body_hash(unit), (
        "the inbox stores a hash of {engine, execution_id, raw_status}; if it ever stores "
        "a hash of the delivery again, every status transition becomes a spoofing alarm"
    )

    # And the divergence nobody could see before: two replays with rewritten bytes, one
    # through the cache. Only the cached one can report it — the durable layer has no body
    # to compare — which is exactly why the signal lives where it does.
    assert divergences == ["bolna"], (
        "a replay with different bytes must be counted at the fast path; without it an "
        f"unsigned endpoint has no replay signal at all: {divergences}"
    )


# --- 2e. the allowlist is operable ------------------------------------------


async def test_the_source_ip_allowlist_comes_from_configuration() -> None:
    """The vendor's egress IP is a value THEY change, on their schedule, with no notice
    to us — and while it is wrong, every webhook 401s and every call falls back to the
    10-minute poller.

    Recovering from that must not require editing Python, opening a PR and shipping a
    deploy of the one service whose deploys are deliberately rare (main.py: 'never
    redeployed casually'). It must be a config value.

    Note what this does NOT do: it does not widen trust. The default is the same single
    documented address, entries must parse as IP addresses, and an empty or unusable
    setting falls back to the built-in default rather than to 'allow everything'.
    """
    parse = parse_source_ip_allowlist
    assert parse("198.51.100.7") == frozenset({"198.51.100.7"})
    assert parse(" 198.51.100.7 , 203.0.113.9 ") == frozenset({"198.51.100.7", "203.0.113.9"})
    # Fail SAFE, not open: nonsense must not empty the allowlist, and a CIDR is not an
    # entry format this check understands — it must not silently become a wildcard.
    assert parse("") == DEFAULT_BOLNA_SOURCE_IPS
    assert parse("0.0.0.0/0") == DEFAULT_BOLNA_SOURCE_IPS
    assert parse("*") == DEFAULT_BOLNA_SOURCE_IPS
    assert parse("not-an-ip, 198.51.100.7") == frozenset({"198.51.100.7"})
    # The default and the field default are the same statement, not two.
    assert (
        parse(Settings.model_fields["bolna_webhook_source_ips"].default) == DEFAULT_BOLNA_SOURCE_IPS
    )


def _bolna_adapter() -> BolnaEngine:
    """An adapter instance with no HTTP identity — `verify_webhook` needs none."""
    return BolnaEngine(api_key=None, fx_rate=Decimal("88.00"))


def test_the_adapter_and_the_receiver_read_one_allowlist(
    source_ip_allowlist: Callable[..., None],
) -> None:
    """THE BUG THIS SECTION EXISTS FOR. `BolnaEngine.verify_webhook` used to match a
    module constant while the receiver matched `BOLNA_WEBHOOK_SOURCE_IPS`. They agreed
    while the setting held its default and diverged the moment anyone used the recovery
    path the setting exists for — a vendor renumber, rotate the variable, restart — so
    the adapter's `WebhookVerdict` would keep blessing an address the door rejects, or
    reject one the door admits. Neither direction announces itself.

    So this asserts the two agree under a WIDENED allowlist and under a NARROWED one,
    not merely under the shipped default: a test of the default is exactly the test that
    could never fail while the bug was present.
    """
    adapter = _bolna_adapter()
    rotated = "203.0.113.77"  # RFC 5737 TEST-NET-3: the "vendor renumbered" address

    # 1. WIDENED — an operator adds the new egress beside the old one.
    source_ip_allowlist(ENGINE_EGRESS_IP, rotated)
    assert adapter.verify_webhook({}, b"{}", rotated).ok, (
        "the adapter still refuses an address the operator allowlisted — it is reading "
        "a second allowlist"
    )
    assert engine_intake.verify_source("bolna", rotated).ok
    assert adapter.verify_webhook({}, b"{}", ENGINE_EGRESS_IP).ok
    assert engine_intake.verify_source("bolna", ENGINE_EGRESS_IP).ok

    # 2. NARROWED — the old address is retired. Divergence in THIS direction is the
    #    dangerous one: the adapter would keep calling a retired address authentic.
    source_ip_allowlist(rotated)
    assert not adapter.verify_webhook({}, b"{}", ENGINE_EGRESS_IP).ok, (
        "the adapter still accepts an address the operator removed — a retired egress "
        "stays trusted for as long as nobody redeploys"
    )
    assert not engine_intake.verify_source("bolna", ENGINE_EGRESS_IP).ok
    assert adapter.verify_webhook({}, b"{}", rotated).ok
    assert engine_intake.verify_source("bolna", rotated).ok

    # 3. The verdict still says what it is: an IP check, never dressed up as a signature.
    assert adapter.verify_webhook({}, b"{}", rotated).method == "source_ip"
    assert adapter.verify_webhook({}, b"{}", ENGINE_EGRESS_IP).method == "source_ip"


def test_a_second_source_ip_engine_is_not_authenticated_against_bolnas_addresses(
    monkeypatch: pytest.MonkeyPatch,
    source_ip_allowlist: Callable[..., None],
) -> None:
    """P2.6. The METHOD was looked up per engine; the ADDRESSES never were.

    `verify_source` read `bolna_source_ips` for ANY engine declaring `source_ip`, so
    adopting a second unsigned engine would have authenticated its deliveries against
    Bolna's egress — which is verbatim the thing the `hmac` branch two lines down refuses
    in a paragraph of its own ("an allowlist is evidence about a DIFFERENT engine's
    egress"). It was inert because `bolna` is the only engine declaring the method, and
    that is precisely why nothing caught it.

    Simulated by DECLARING a second such engine rather than by adding one: this is a
    property of the lookup, and waiting for a real second vendor to prove it is waiting
    for the outage. The allowlist table gets no entry for it, so the only safe answer is
    a refusal — and a fallback to the single entry that exists is the defect.
    """
    monkeypatch.setitem(engine_intake.WEBHOOK_AUTH_BY_ENGINE, "notbolna", "source_ip")
    # And NO entry in the allowlist table, which is the condition under test.
    source_ip_allowlist(ENGINE_EGRESS_IP)

    verdict = engine_intake.verify_source("notbolna", ENGINE_EGRESS_IP)
    assert not verdict.ok, (
        "a second source-ip engine was accepted from BOLNA's egress address — the "
        "receiver authenticated one vendor's delivery with another vendor's evidence"
    )
    assert verdict.reason == "no source ip allowlist for this engine", verdict.reason
    # And the engine that DOES have an entry is unaffected: the refusal is a missing
    # entry, not a disabled branch.
    assert engine_intake.verify_source("bolna", ENGINE_EGRESS_IP).ok


def test_no_second_source_ip_allowlist_has_grown_back(
    source_ip_allowlist: Callable[..., None],
) -> None:
    """A guard against the shape of the defect, not just this instance of it.

    The vendor's documented egress may be WRITTEN in several places — docs, `.env.example`,
    `scripts/pilot/gates_api.py` (deliberately, so the gate is not tautological) — but no
    runtime path may DECIDE with a copy of it. The check: with the setting pointed at
    documentation addresses only, nothing that answers the authenticity question may
    still accept the shipped default.
    """
    documented = next(iter(DEFAULT_BOLNA_SOURCE_IPS))
    source_ip_allowlist(ENGINE_EGRESS_IP)

    assert not engine_intake.verify_source("bolna", documented).ok, (
        "the receiver accepts the built-in default while the setting names another "
        "address — something is still deciding from a hardcoded copy"
    )
    assert not _bolna_adapter().verify_webhook({}, b"{}", documented).ok, (
        "the adapter accepts the built-in default while the setting names another "
        "address — the module constant is back"
    )

    # And no runtime module carries the literal as CODE. Comments and docstrings may
    # name it — `client_ip`'s docstring uses it in its worked example of a spoofed
    # forwarded header, and a rule that forbade explaining the value would be a rule
    # against writing down why it matters. Parsed rather than grepped for exactly that
    # reason: the question is "does anything compare against a copy", and only a string
    # the interpreter evaluates can.
    for path in (Path("apps/api/engine/bolna.py"), Path("apps/voice-runtime/engine_intake.py")):
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        offending = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and documented in node.value
            and id(node) not in docstrings
        ]
        assert not offending, (
            f"{path} carries the vendor's egress address as a code literal at line(s) "
            f"{offending}. It belongs to `calevate_shared.config.DEFAULT_BOLNA_SOURCE_IPS` "
            "and to the `BOLNA_WEBHOOK_SOURCE_IPS` setting, nowhere else."
        )


async def test_a_rejected_caller_is_named_in_the_alert(caplog: pytest.LogCaptureFixture) -> None:
    """The incident this alert exists for is "the vendor renumbered": every webhook
    401s, every call silently falls back to the 10-minute poller, and the fix is one
    value in one config line.

    An alert that says `source ip not allowlisted` without saying WHICH source ip makes
    an operator run tcpdump on a production voice box to learn it. The address is a
    machine caller's, not a subscriber's — nothing hard rule 6 protects — and it stays
    out of the response body, where it would leak the allowlist to a prober.
    """
    _execution_id, _status, body = _event()
    with caplog.at_level("ERROR", logger="calevate.alert"):
        async with _client(ATTACKER_IP) as http:
            response = await http.post(HOOK, json=body)

    assert response.status_code == 401
    assert ATTACKER_IP not in response.text, "the response must not confirm anything to a prober"

    rejections = [
        record
        for record in caplog.records
        if getattr(record, "code", None) == "webhook_source_rejected"
    ]
    assert rejections, "a rejected webhook did not alert at all"
    assert getattr(rejections[-1], "source_ip", None) == ATTACKER_IP, (
        "the alert does not name the caller it rejected"
    )


# --- 2f. the ack path stays cheap -------------------------------------------

#: Every module under `apps.api.engine`, GLOBBED off the tree rather than typed out.
#:
#: The list this replaces named `bolna` and `fake` and had never learned about
#: `cartesia` (P2.6) — a hand-written enumeration of a set that grows, which is the drift
#: class D-103 exists for and which is invisible precisely because the missing entry is
#: the one nobody thought about. A third adapter could have leaked into the ack path and
#: this assertion would have stayed green.
#:
#: The whole PACKAGE, not just the adapters: `apps.api.engine.__init__` builds them, so
#: importing any submodule pulls httpx and the vendor clients into a process that must
#: ack in 500ms (hard rule 3). The receiver reads `calevate_shared.engine` instead, which
#: imports nothing.
_ENGINE_MODULES = (
    "apps.api.engine",
    *sorted(
        f"apps.api.engine.{path.stem}"
        for path in (REPO_ROOT / "apps" / "api" / "engine").glob("*.py")
        if path.stem != "__init__"
    ),
)

_FORBIDDEN_AT_IMPORT = (
    *_ENGINE_MODULES,
    # The worker package: importing it here would drag the whole post-call pipeline,
    # its model clients and its storage layer into a latency-critical process.
    "apps.workers",
    # An HTTP client at module scope means somebody added an outbound call to the ack
    # path — the exact thing hard rule 3 forbids.
    "httpx",
    "aiohttp",
    # Model SDKs and numeric stacks: seconds of import time, no business here.
    "openai",
    "google.generativeai",
    "anthropic",
    "numpy",
    "pandas",
    "torch",
    "transformers",
)


def test_the_receiver_imports_nothing_heavy_at_module_scope() -> None:
    """The import-surface assertion `main.py` claims exists — and did not.

    An eyeball on the import block is not evidence: the leak is always transitive, one
    `from apps.workers.x import y` three modules deep. So this boots the real ASGI app
    in a clean interpreter and reads `sys.modules`, which cannot be argued with.

    Why it matters more here than anywhere else: this process must ack in under 500ms
    and must be deployable without touching `api`. Every module it pulls in is both a
    cold-start cost and a reason someone will one day couple the two deploys.
    """
    search_path = [str(REPO_ROOT), str(REPO_ROOT / "apps" / "voice-runtime")]
    probe = (
        f"import sys; sys.path[:0] = {search_path!r}; import main; "
        "print('\\n'.join(sorted(sys.modules)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    loaded = {line.strip() for line in result.stdout.splitlines() if line.strip()}

    leaked = sorted(m for m in _FORBIDDEN_AT_IMPORT if m in loaded)
    assert not leaked, f"voice-runtime imports these at module scope: {leaked}"
    assert "main" in loaded and "webhook_routes" in loaded, "the probe did not import the app"


async def test_the_ack_path_writes_only_the_minimal_event_rows() -> None:
    """Hard rule 3 allows the receiver exactly two writes — the inbox claim and the
    forensic delivery row — and nothing else.

    The committed security suite proves the ABSENCE of domain rows. This counts the
    statements instead, which is the property that actually stays true when someone
    adds a 'quick lookup' later: a SELECT that joins three tables leaves no row behind
    but still spends the budget on a path that has 500ms for everything.
    """
    statements: list[str] = []

    def _record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(" ".join(statement.split())[:120])

    sync_engine = get_db_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", _record)
    try:
        _execution_id, _status, body = _event()
        async with _client() as http:
            response = await http.post(HOOK, json=body, headers=_engine_headers())
    finally:
        event.remove(sync_engine, "before_cursor_execute", _record)

    assert response.status_code == 202, response.text

    writes = [s for s in statements if s.upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    inserts = [s for s in writes if s.upper().startswith("INSERT")]
    assert len(inserts) == 2, f"expected the inbox claim + the forensic row, got: {inserts}"
    assert any("webhook_inbox_events" in s for s in inserts)
    assert any("webhook_deliveries" in s for s in inserts)
    # The single UPDATE is `mark_inbox_enqueued`; anything more is pipeline work.
    assert len(writes) <= 3, f"the ack path is writing more than the minimal event rows: {writes}"

    for statement in statements:
        for table in ("calls", "leads", "usage_events", "transcripts", "agents"):
            assert f" {table} " not in f" {statement.lower()} ", (
                f"the ack path touched `{table}`: {statement}"
            )


# =============================================================================
# Section 3 — adapter resilience against the vendor's rate limit (SURFACES §3.3)
# =============================================================================


def _throttling_engine(
    responses: list[httpx.Response],
) -> tuple[BolnaEngine, list[httpx.Request]]:
    """A Bolna adapter whose transport returns a scripted sequence of responses."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[min(len(seen) - 1, len(responses) - 1)]

    engine = BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai", transport=httpx.MockTransport(handler)
        ),
    )
    return engine, seen


def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, float | None]]:
    """Keep the retry mechanics, drop the wall-clock wait.

    The real `throttle_delay_s` still decides IF and with what arguments (that is what
    the returned list records); it just returns zero so the suite does not sleep.
    """
    computed: list[tuple[int, float | None]] = []
    real = vendor_http.throttle_delay_s

    def _spy(attempt: int, retry_after: float | None, **kwargs: Any) -> float:
        computed.append((attempt, retry_after))
        assert real(attempt, retry_after) > 0, "the real backoff would not have waited"
        return 0.0

    monkeypatch.setattr(vendor_http, "throttle_delay_s", _spy)
    return computed


async def test_a_rate_limited_request_is_retried_rather_than_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 says "I did not do this, slow down". Treating it as a generic failure
    throws away a request the vendor never processed — and on the campaign path that
    consumes a contact's attempt for a reason that has nothing to do with the contact.
    """
    waits = _instant_backoff(monkeypatch)

    engine, seen = _throttling_engine(
        [
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json={"execution_id": "exec_after_throttle"}),
        ]
    )
    handle = await engine.start_outbound_call(
        "agent_xyz", "+919876543210", CallContext(lead_name="Ravi")
    )

    assert handle == "exec_after_throttle"
    assert len(seen) == 2, "the throttled request was not retried"
    assert waits == [(0, None)], "a retry with no backoff is a faster way to be throttled"


async def test_an_exhausted_throttle_is_reported_as_transient_not_as_a_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error ladder does real work here: `transient` (503, retryable=True) tells a
    caller an identical retry can succeed, where `engine_rejected` says the request
    itself was bad. Collapsing a rate limit into the second is how a throttled campaign
    contact gets marked as a failed call."""
    _instant_backoff(monkeypatch)

    engine, seen = _throttling_engine([httpx.Response(429, json={"error": "slow down"})])
    with pytest.raises(ProblemError) as raised:
        await engine.get_execution("exec_abc123")

    assert raised.value.kind == "transient"
    assert raised.value.code == "engine_rate_limited"
    assert raised.value.status == 503
    assert raised.value.as_problem()["retryable"] is True
    assert len(seen) == vendor_http.THROTTLE_MAX_ATTEMPTS, "it gave up at the wrong attempt count"


async def test_a_non_throttle_failure_is_never_retried() -> None:
    """The other half, and the more dangerous one. `POST /call` DIALS A HUMAN. A 502 or
    a 504 does not tell us whether the platform already placed that call, so repeating
    it can ring a lead twice — a TRAI complaint generator, not a resilience feature.

    Only 429 is safe to repeat, because only 429 states the request was refused.
    """
    for status in (500, 502, 503, 504, 400, 404):
        engine, seen = _throttling_engine([httpx.Response(status, json={"error": "nope"})])
        with pytest.raises(ProblemError) as raised:
            await engine.start_outbound_call("agent_xyz", "+919876543210", CallContext())
        assert len(seen) == 1, f"a {status} caused a second POST /call — that dials twice"
        assert raised.value.code == "engine_rejected"


async def test_backoff_is_jittered_and_never_undercuts_retry_after() -> None:
    """Every worker throttled in the same second retries in the same second unless the
    delay carries variance — that is how a rate limit turns into an outage. And when
    the vendor names a time, it is a floor: retrying before it is worse than useless.
    """
    delays = {vendor_http.throttle_delay_s(0, None) for _ in range(50)}
    assert len(delays) > 1, "the backoff is deterministic — every worker retries in lockstep"
    assert all(d >= 0 for d in delays)

    # Full jitter over an exponentially growing ceiling: bounded, but never a constant.
    assert all(d <= vendor_http.THROTTLE_BASE_S for d in delays)
    assert all(
        vendor_http.throttle_delay_s(3, None, rand=lambda: 1.0) <= vendor_http.THROTTLE_MAX_SLEEP_S
        for _ in range(5)
    )

    honoured = vendor_http.throttle_delay_s(0, 2.0, rand=lambda: 0.0)
    assert honoured >= 2.0, "we retried before the vendor said we could"


async def test_a_long_retry_after_fails_fast_instead_of_holding_the_request_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter calls run inside request handlers as well as workers. Sleeping through a
    two-minute `Retry-After` would hold a user's HTTP request open for two minutes and
    hold a worker slot with it. Report `transient` and let the caller reschedule."""
    waits = _instant_backoff(monkeypatch)

    engine, seen = _throttling_engine(
        [httpx.Response(429, headers={"Retry-After": "120"}, json={"error": "slow down"})]
    )
    with pytest.raises(ProblemError) as raised:
        await engine.get_execution("exec_abc123")

    assert raised.value.code == "engine_rate_limited"
    assert waits == [], "the adapter would have slept through a two-minute Retry-After"
    assert len(seen) == 1


# =============================================================================
# Section 4 — hard rule 2 measured as DATA FLOW, not as imports
#
# The import-linter contract in `pyproject.toml` is a claim about IMPORTS. A vendor shape
# does not need one: `payload["telephony_data"]` is a Bolna field name learned by a module
# that imports nothing from `apps/api/engine/`, and it arrives with no import for a
# reviewer to notice. So the boundary is measured here by reading every module's dict-key
# accesses out of its AST and comparing them against the vocabulary the adapters speak.
#
# THE CLASSIFICATION BELOW IS THE WHOLE MECHANISM, and it is split in two on purpose.
# A single "banned words" list rots the moment an adapter learns a new field — the list is
# edited by whoever remembers, which is the failure mode CLAUDE.md's hard rule 4 note and
# D-103/D-105 are all about. So every key an ADAPTER reads must appear in exactly one of
# the two sets below (`test_every_payload_key_an_adapter_reads_is_classified`), which makes
# triaging a new vendor field a build failure rather than an act of vigilance.
# =============================================================================

#: Keys that exist ONLY in a vendor's vocabulary. Reading one outside `apps/api/engine/`
#: is a vendor shape escaping the adapter — hard rule 2 — even though no import moved.
#:
#: The test for membership is not "does an adapter read it" (that is both sets) but "would
#: this word be a surprise in our own vocabulary". `telephony_data` and `outbound_calls`
#: are a vendor's nouns; `status` and `duration` are everybody's.
_VENDOR_ONLY_KEYS = frozenset(
    {
        # Bolna, read in their own pinned OpenAPI document (D-350,
        # `docs/vendor/bolna/hosted-oas.md`) rather than hand-maintained from prose.
        "agent_config",
        "agent_name",
        "agent_prompts",
        "agent_type",
        # The greeting field — Bolna's own noun for it. Read since P3.3, because the
        # disclosure verdict has to be scored against the field that SPEAKS.
        "agent_welcome_message",
        # THE DIRECTION OF A CALL, IN THE VENDOR'S SPELLING (D-359). Bolna puts it on
        # `telephony_data.call_type` as `"inbound"`/`"outbound"`; OUR word for the same
        # thing is `direction`, on `CallEvent` and `ExecutionSnapshot`. That is exactly
        # what makes this a vendor-only noun rather than a shared one: the concept is
        # ours, the spelling is theirs, and `direction` appearing outside the adapter is
        # normal while `call_type` appearing there would be a vendor shape that escaped.
        "call_type",
        "conversation_duration",
        "cost_breakdown",
        "cost_currency",
        "executions",
        "extracted_data",
        # `knowledgebases` left with `list_kb`'s account-wide listing (D-354): the vendor's
        # knowledge base carries no agent, so that listing could never answer the question
        # this port asks, and the capability is now declared absent.
        #
        # `has_more` IS LISTED ONCE FOR BOTH VENDORS, and it is the only entry that has to
        # be. Bolna's `AgentExecutionV2List.has_more` (VERIFIED-OAS, D-353) and Cartesia's
        # pagination flag are the same word, so a second entry down in the Cartesia block
        # was a duplicate a frozenset silently absorbed — ruff's B033 caught it. It stays
        # HERE rather than there because this is the first block: the set is a ban list,
        # not a per-vendor inventory, and a word only has to be banned once.
        "has_more",
        "llm_config",
        "rag_id",
        "recipient_phone_number",
        "synthesizer",
        "task_1",
        "tasks",
        "telephony_data",
        "tools_config",
        "total_cost",
        "transcriber",
        "user_data",
        # Cartesia Line (TRD §10.5; the adapter marks which shapes are sourced, and
        # `docs/vendor/cartesia/` carries the citations since D-270).
        "agent_call_id",
        "duration_seconds",
        "from_number_id",
        # (`has_more` is Cartesia's too — listed once, up in the Bolna block.)
        # Their pagination cursor parameter, read at source in their generated client.
        # Nothing of ours is called this. (`summaries`, the envelope `GET /agents` answers
        # with, is NOT here — see `_SHARED_PAYLOAD_KEYS`.)
        "starting_after",
        # `telephony_params` is Cartesia's noun for the same thing Bolna calls
        # `telephony_data`, which is already banned two lines up — the pair is the
        # clearest example in this list of why the ban is per vendor noun rather than per
        # concept.
        "telephony_params",
        # `introduction` AND `document_ids` USED TO BE HERE and were removed by D-281,
        # which is the third way an entry can go stale and the one the clause below could
        # not have guessed: the vendor did not rename either field and neither entry was
        # fictional — the OPERATIONS that read them stopped existing. Cartesia's agent
        # record carries no prompt, no greeting and no document list, so `create_agent`,
        # `update_agent` and `get_agent` refuse on `agent_hosting` rather than reading a
        # response with those keys in it. A word no adapter reads cannot escape from one,
        # which is the whole premise of this list; if a Cartesia agent read ever comes back
        # (gate 19(a)), both entries come back with it.
        "outbound_calls",
        # `start_time`/`end_time` are Cartesia's names for the two instants everything
        # else in this repo calls `started_at`/`ended_at` — `ExecutionSnapshot`,
        # `CallEvent` and the `calls` columns all use the `_at` spelling, so the bare form
        # appearing in shipped code outside the adapter is a vendor shape that escaped.
        # Ordinary-looking English words, banned for `introduction`'s reason.
        "start_time",
        "end_time",
        # THE LLM ENDPOINT, IN THE VENDOR'S SPELLING (D-400/D-404, re-aimed by D-410), and
        # it is `call_type`'s case exactly: the concept is ours and the spelling is theirs.
        # OUR word is `llm_base_url` — on `ModelConfig`, built by `azure_openai_base_url()`
        # and validated there against the one endpoint shape that builder emits — while
        # bare `base_url` is the key inside Bolna's `SimpleLlmAgent`. That distinction is
        # load-bearing rather than tidy: this field carries the RESIDENCY guarantee, so a
        # shipped module outside the adapter reading a raw `base_url` off a payload is
        # reading an unvalidated endpoint, which is the one shape `ModelConfig`'s validator
        # exists to make impossible.
        #
        # IT MATTERS MORE UNDER AZURE, NOT LESS, and that is worth the extra line. A Vertex
        # URL wore its region in the host and the path, so an unvalidated one could at
        # least be EYEBALLED; `<resource>.openai.azure.com` names no region at all, so the
        # only thing standing between a stray `base_url` and an out-of-region resource is
        # the validator this ban keeps callers funnelled through.
        "base_url",
        # Bolna's credential store (D-404, no longer rotating since D-410). `provider_id`
        # is how `set_llm_credential` tells a superseded entry from the one it just wrote —
        # the store MASKS `provider_value`, so identity is the only thing it will answer
        # honestly about. Both are their nouns and neither has a Calevate counterpart: our
        # vocabulary for this has no id at all, because the credential lives in the secrets
        # manager and in the vendor's store, and nowhere of ours.
        "provider_id",
        "provider_name",
    }
)
# `next_page` was here and is gone with the Cartesia listing rewrite (D-270): their page
# model carries no `has_more`/`next_page` at all, it cursors on the last row's id. It was
# removed rather than kept "just in case", because
# `test_every_banned_key_is_still_a_word_some_adapter_speaks` is what stops this list
# accumulating words that describe nothing.

#: Keys an adapter reads that are ALSO ours. Being here is not permission to read a vendor
#: payload — it is an admission that this word carries no evidence either way, so the
#: repo-wide scan cannot use it. The places where a shared word still matters are covered
#: by a POSITIVE allowlist instead: `_RECEIVER_PAYLOAD_KEYS` below.
#:
#: Four of these were in the ban list before this section existed — `transcript`,
#: `recording_url`, `from_number`, `to_number` — and they worked there only because that
#: check was scoped to two files. Repo-wide they name `ExecutionSnapshot.recording_url`,
#: the golden-fixture `case["transcript"]` in `scripts/eval.py` and the columns
#: `calls.from_e164`/`to_e164` are read beside. A guard that cries wolf on our own
#: vocabulary is a guard somebody switches off.
_SHARED_PAYLOAD_KEYS = frozenset(
    {
        "agent",
        "agent_id",
        "agent_ref",
        "calls",
        "completed_at",
        "content",
        "context_note",
        "created_at",
        "currency",
        "data",
        "direction",
        "documents",
        "duration",
        "duration_s",
        "ended_at",
        "event",
        "execution_id",
        "from_e164",
        "from_number",
        "id",
        "lead_id",
        "lead_name",
        "llm",
        "model",
        "name",
        "network",
        "next",
        "platform",
        "prior_call_summary",
        "recording_url",
        "retry-after",
        "role",
        "speaker",
        "started_at",
        "status",
        # Cartesia's `GET /agents` envelope key — and also OURS: `apps/workers/retention.py`
        # counts the call `summaries` it sweeps under exactly this name. Which is the
        # whole point of this set: the word carries no evidence either way, so the
        # repo-wide scan may not use it. Banning it turned a real retention counter into
        # a hard-rule-2 violation, which is how a guard that cries wolf gets switched off.
        "summaries",
        "stt",
        "system_prompt",
        "text",
        "to_e164",
        "to_number",
        "transcript",
        "transfer_warm",
        "transferred_to",
        "tts",
        "updated_at",
        "webhook_url",
    }
)

#: EVERY key the voice-runtime receiver may pull out of a mapping — an allowlist, not a
#: denylist, because this is the one module where a shared word is as dangerous as a
#: vendor one. Hard rule 3 gives it three payload fields: the execution id under any of
#: its spellings (the dedupe key), the status (the other half of that key, D-40) and the
#: agent ref (a routing hint the worker re-derives anyway). Reading a fourth is not a
#: leak of Bolna's shape in particular — it is the receiver starting to interpret a
#: payload that is only ever a HINT (D-31).
#:
#: The two header names are here because an AST cannot tell `headers["content-length"]`
#: from `payload["content-length"]`. That is the cost of the stronger check, and it is
#: cheap: the set is short, and every addition is a line somebody has to write here.
_RECEIVER_PAYLOAD_KEYS = frozenset(
    {"execution_id", "id", "call_id", "status", "agent_id", "X-Ack-Ms", "content-length"}
)

#: The modules the repo-wide scan holds to hard rule 2. Shipped code only: the conformance
#: stub and the pilot fixtures BUILD vendor payloads on purpose (a stub of a vendor has to
#: speak the vendor's shape, and `conftest._bolna_handler` says so at length), so scanning
#: them would only teach the next person to add an exemption.
_SHIPPED_ROOTS = ("apps", "packages/shared/src", "scripts")

#: The one package allowed to hold a vendor payload shape at all (hard rule 2).
_ADAPTER_PACKAGE = "apps/api/engine"

_ADAPTER_SOURCES = (
    "apps/api/engine/bolna.py",
    "apps/api/engine/cartesia.py",
    "apps/api/engine/fake.py",
)


def _dict_keys_read(source: str) -> set[str]:
    """Every literal key this module pulls out of a mapping: `x["k"]`, `x.get("k")`,
    `x.pop("k")`, `x.setdefault("k")`. Parsed rather than grepped, so a key named in a
    docstring or a comment — where explaining the vendor is the whole point — is not
    mistaken for one being read."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                found.add(node.slice.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop", "setdefault")
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.add(node.args[0].value)
    return found


def _string_constants(source: str) -> set[str]:
    """Every string literal in a module, docstrings included. Used only to ask whether a
    banned word is still SPOKEN by an adapter — a ban list naming a field no vendor has is
    a rule that cannot fail, which is the same defect as no rule."""
    return {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _shipped_modules() -> list[Path]:
    """Every shipped `.py` outside the adapter package. Tests are not shipped and are
    excluded by root, never by an exemption list."""
    found: list[Path] = []
    for root in _SHIPPED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            relative = path.relative_to(REPO_ROOT).as_posix()
            if "__pycache__" in relative or relative.startswith(_ADAPTER_PACKAGE):
                continue
            found.append(path)
    return found


def test_no_shipped_module_outside_the_adapters_reads_a_vendor_payload_key() -> None:
    """HARD RULE 2, MEASURED OVER THE WHOLE TREE RATHER THAN ASSERTED ABOUT IMPORTS.

    This is the check the import-linter contract cannot be: that contract forbids naming
    `apps.api.engine.bolna` in an import, and a vendor field name needs no import to
    travel — it rides inside a `dict[str, Any]`, arrives in a worker, and gets read. The
    scan below is what turns "only the adapter sees vendor payload shapes" from a claim
    into a measurement, and it covers `apps/`, `packages/shared/src` and `scripts/`
    rather than the two receiver files the previous version of this check looked at.

    A failure here has exactly two honest fixes: map the field inside the adapter and add
    it to `ExecutionSnapshot`/`CallEvent`, or carry it as OPAQUE BYTES like
    `ExecutionSnapshot.raw_document` does for D-126's archive. Adding the key to
    `_SHARED_PAYLOAD_KEYS` is not one of them.

    `apps/voice-runtime/` IS SCANNED, which is stricter than hard rule 2 reads — the rule
    permits "the voice-runtime twin" to see a vendor shape. The twin's own discipline is
    what closes that gap: hard rule 3 gives it authenticity and a dedupe key and forbids
    interpretation, so there is no vendor field it is entitled to read and
    `_RECEIVER_PAYLOAD_KEYS` says which five words it may touch at all.
    """
    leaks: dict[str, list[str]] = {}
    for path in _shipped_modules():
        found = sorted(_dict_keys_read(path.read_text(encoding="utf-8")) & _VENDOR_ONLY_KEYS)
        if found:
            leaks[path.relative_to(REPO_ROOT).as_posix()] = found
    assert not leaks, (
        f"vendor payload keys are read outside {_ADAPTER_PACKAGE}/: {leaks}. A vendor "
        "shape crossed the boundary inside a dict, which no import contract can see "
        "(hard rule 2)."
    )


def test_every_payload_key_an_adapter_reads_is_classified() -> None:
    """The clause that stops the ban list above from rotting.

    A denylist is only as good as the day it was written: the moment an adapter learns a
    new vendor field, the list is one word short and nothing says so. So every key an
    adapter reads out of a mapping must be classified as vendor-only or as shared
    vocabulary, and a new one fails this test until somebody decides which it is. That
    decision takes a second and is exactly the second at which it is cheapest.

    The two sets must also stay DISJOINT — a key in both would be banned and permitted at
    once, and the repo-wide scan would silently take the permissive reading.
    """
    overlap = sorted(_VENDOR_ONLY_KEYS & _SHARED_PAYLOAD_KEYS)
    assert not overlap, f"these keys are classified twice: {overlap}"

    unclassified: dict[str, list[str]] = {}
    for source in _ADAPTER_SOURCES:
        keys = _dict_keys_read((REPO_ROOT / source).read_text(encoding="utf-8"))
        missing = sorted(keys - _VENDOR_ONLY_KEYS - _SHARED_PAYLOAD_KEYS)
        if missing:
            unclassified[source] = missing
    assert not unclassified, (
        f"these payload keys are read by an adapter and classified nowhere: {unclassified}. "
        "Put each in `_VENDOR_ONLY_KEYS` (a vendor's own noun, banned everywhere else) or "
        "in `_SHARED_PAYLOAD_KEYS` (a word we use too, so it proves nothing)."
    )


def test_every_banned_key_is_still_a_word_some_adapter_speaks() -> None:
    """The other direction, and the reason it is worth a clause of its own.

    A ban list that outlives its subject is a rule that cannot fail. If Bolna's
    `telephony_data` is renamed and the adapter follows, the entry here goes on passing
    forever while protecting nothing — and the NEW field name is unguarded, because
    nobody re-derived the list. Checked against every string constant in the adapters
    (not just keys they read) so a field an adapter only WRITES — `recipient_phone_number`,
    `user_data`, `from_number_id` — still counts as spoken.
    """
    spoken: set[str] = set()
    for source in _ADAPTER_SOURCES:
        spoken |= _string_constants((REPO_ROOT / source).read_text(encoding="utf-8"))
    stale = sorted(key for key in _VENDOR_ONLY_KEYS if key not in spoken)
    assert not stale, (
        f"`_VENDOR_ONLY_KEYS` bans words no adapter uses any more: {stale}. Either the "
        "vendor renamed the field (in which case the NEW name is what needs banning) or "
        "the entry was never real."
    )


def test_the_receiver_reads_only_the_keys_hard_rule_3_gives_it() -> None:
    """The receiver, held to an ALLOWLIST rather than to a list of forbidden words.

    Denying vendor nouns is the right check for the tree and the wrong one here. This
    module acks in under 500ms for an unsigned, at-most-once vendor (D-31), and the
    payload is a HINT — so the danger is not specifically that it learns `telephony_data`,
    it is that it starts interpreting the payload at all. `duration_s` would be just as
    wrong and appears in no denylist, because it is our own word.

    So: three payload fields, named in `_RECEIVER_PAYLOAD_KEYS`, and anything else is a
    failure whether or not a vendor invented it.
    """
    for module in (engine_intake, webhook_routes):
        path = Path(inspect.getsourcefile(module) or "")
        extra = sorted(_dict_keys_read(path.read_text(encoding="utf-8")) - _RECEIVER_PAYLOAD_KEYS)
        assert not extra, (
            f"{module.__name__} reads {extra} out of a mapping. The receiver's whole job "
            "is authenticity and a dedupe key; interpreting a payload it is told to treat "
            "as a hint belongs in apps/api/engine/, in a worker, later (hard rules 2 and 3)."
        )


# =============================================================================
# Section 5 — hard rule 6 on the adapter surface, measured rather than reviewed
#
# "Never log phone numbers, transcript text, or extraction payloads. Log ids." The
# adapters are the one layer that HOLDS all three: they parse the vendor's execution
# document, which carries the caller's number and every word both parties said. Every log
# call in `apps/api/engine/` was written to pass ids and counts, and reading them and
# agreeing is not evidence — the leak that matters is the one that arrives by accident,
# through an exception message, a route string or a field somebody added to an `extra`.
#
# So the adapters are DRIVEN, across the paths that log, against a payload whose number
# and transcript are unique strings, and every record the run emits is searched for them.
# =============================================================================

#: A number and two utterances that appear nowhere else in this repository, so a hit is a
#: leak and never a coincidence. The number is in the RFC 5737-equivalent space for Indian
#: E.164 that this suite already uses for fixtures: unroutable in practice, and prefixed
#: `+915` like every other synthetic caller here.
_PII_NUMBER = "+915000700071"
_PII_TRANSCRIPT_TURN = "zzq-caller-said-this-out-loud"
_PII_EXTRACTED_VALUE = "zzq-extracted-field-value"


def _pii_execution(execution_id: str) -> dict[str, Any]:
    """A completed execution in Bolna's documented shape, carrying the three things hard
    rule 6 names: a caller's number, transcript text and an extraction payload."""
    return {
        "id": execution_id,
        "agent_id": "agent_pii",
        "status": "completed",
        "direction": "inbound",
        "created_at": "2026-08-10T09:15:00Z",
        "ended_at": "2026-08-10T09:16:35Z",
        "conversation_duration": 95,
        "total_cost": 8.5,
        # An unconvertible currency, so `engine_cost_currency_unsupported` fires on a
        # payload that also holds the number and the transcript.
        "currency": "XAU",
        "telephony_data": {
            "from_number": _PII_NUMBER,
            "to_number": "+911140000000",
            "recording_url": f"https://s3.example.invalid/{execution_id}.wav?token=zzq-secret",
        },
        # The FIRST line carries no speaker prefix, so `parse_transcript` can place it
        # nowhere and counts it as lost — the branch whose whole promise is that what
        # cannot become a `TranscriptTurn` is COUNTED and discarded, never kept for
        # inspection. It holds the caller's number so the discard is measured with real
        # material rather than with filler.
        "transcript": f"{_PII_NUMBER} {_PII_TRANSCRIPT_TURN}\nuser: {_PII_TRANSCRIPT_TURN}",
        "extracted_data": {"lead_name": _PII_EXTRACTED_VALUE},
    }


async def test_no_adapter_logs_a_phone_number_a_transcript_or_an_extraction(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HARD RULE 6, DRIVEN THROUGH THE PATHS THAT ACTUALLY LOG.

    A quiet adapter proves nothing: every log site in `apps/api/engine/` sits on a failure
    branch, so a run that never fails never reaches one. This drives the branches on
    purpose — an unconvertible currency, an off-origin continuation link, an exhausted
    throttle, a vendor rejection, an unparseable transcript line — with a payload that
    carries a caller's number, a spoken line and an extracted value.

    The captured record is searched WHOLE, attributes included, not just its message:
    `log.warning("x", extra={"payload": ...})` puts the leak in a field, which is exactly
    how one arrives. The presigned recording URL is in the fixture for the same reason —
    it is a credential in a query string (`scripts/pilot/record.py` says so), and it rides
    on the same object.

    READ AT THE RECORD, NOT AT THE FORMATTED LINE, and that is the one place this differs
    from `tests/pii_logging_sweep_test.py` — deliberately, because the two are asking
    different questions rather than the same one twice. That file reads formatted output
    because redaction lives in `JsonFormatter.format`, and what it proves is that nothing
    reaches the log STREAM. This asks whether the adapter HANDED the logger a caller's
    number in the first place, which the redactor would then have to catch — so it must
    look before the redactor runs, and it is strictly the stricter of the two on this
    surface. A leak the formatter happens to scrub is still an adapter bug: it is one
    redaction-pattern change away from being a live one.
    """
    listings = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal listings
        path = request.url.path
        if path == "/v2/agent/all":
            listings += 1
            if listings > 1:
                # The second `list_executions` call: throttled forever from its very first
                # request, so the ladder logs `engine_throttled` and then
                # `engine_throttle_exhausted` — both with a vendor body full of PII.
                return httpx.Response(429, json={"error": f"slow down, {_PII_NUMBER}"})
            return httpx.Response(200, json=[{"id": "agent_pii_listed"}])
        if path.endswith("/executions") and path.startswith("/v2/agent/"):
            # `has_more: true` on a page that re-serves what we already hold, so the walk
            # stops with `next_link_no_progress` and `engine_listing_incomplete` is logged
            # for a window whose every row carries a number and a transcript.
            return httpx.Response(
                200,
                json={
                    "has_more": True,
                    "data": [_pii_execution(f"exec_pii_{i}") for i in range(10)],
                },
            )
        if path.startswith("/executions/"):
            return httpx.Response(200, json=_pii_execution("exec_pii_one"))
        # Every other route refuses, so `engine_error` fires with a body that carries PII.
        return httpx.Response(
            400, json={"error": f"bad request for {_PII_NUMBER}: {_PII_TRANSCRIPT_TURN}"}
        )

    engine = BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai", transport=httpx.MockTransport(handler)
        ),
    )
    monkeypatch.setattr(vendor_http, "throttle_delay_s", lambda *a, **k: 0.0)

    with caplog.at_level("DEBUG"):
        snapshot = await engine.get_execution("exec_pii_one")
        listing = await engine.list_executions(since=datetime(2026, 8, 10, tzinfo=UTC))
        with pytest.raises(ProblemError):
            await engine.list_executions(since=datetime(2026, 8, 10, tzinfo=UTC))
        with pytest.raises(ProblemError):
            await engine.get_agent("agent_pii")
        engine.parse_webhook(_pii_execution("exec_pii_hook"))
        engine.verify_webhook({}, b"{}", ATTACKER_IP)

    # The run really did reach the material: without this the test could pass on an
    # adapter that logged nothing because it parsed nothing.
    assert snapshot.from_e164 == _PII_NUMBER, "the fixture did not carry a caller's number"
    assert any(_PII_TRANSCRIPT_TURN in turn.text for turn in snapshot.transcript)
    assert snapshot.transcript_lines_unparsed == 1, "the unparseable-line branch was not reached"
    assert snapshot.cost is None, "the unsupported-currency branch was not reached"
    assert not listing.complete, "the listing branches were not reached"

    emitted = "\n".join(
        f"{record.getMessage()} {sorted(vars(record).items(), key=str)}"
        for record in caplog.records
    )
    assert emitted.strip(), "nothing was logged at all, so this test measured nothing"
    for secret, what in (
        (_PII_NUMBER, "a caller's phone number"),
        (_PII_TRANSCRIPT_TURN, "transcript text"),
        (_PII_EXTRACTED_VALUE, "an extracted field value"),
        ("zzq-secret", "a presigned recording credential"),
    ):
        assert secret not in emitted, f"an adapter logged {what} (hard rule 6)"
