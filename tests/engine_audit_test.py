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
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import engine_intake
import httpx
import pytest
import webhook_routes
from apps.api.core.errors import ProblemError
from apps.api.db.session import get_engine as get_db_engine
from apps.api.db.session import untenanted_session
from apps.api.engine import bolna
from apps.api.engine.bolna import BolnaEngine
from apps.api.engine.fake import FakeEngine
from calevate_shared.config import (
    DEFAULT_BOLNA_SOURCE_IPS,
    Settings,
    parse_source_ip_allowlist,
)
from calevate_shared.engine import (
    CallContext,
    CostBreakdown,
    ExecutionListing,
    ExecutionSnapshot,
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


SABOTEURS: dict[str, Callable[[], VoiceEngine]] = {
    "accepts-any-source-ip": _AcceptsAnySource,
    "drops-engine-agent-ref": _DropsAgentRef,
    "cost-without-fx-stamp": _UnstampedCost,
    "lies-about-direction": _DirectionLiar,
    "transcript-of-another-call": _ForeignTranscript,
    "forgets-raw-status": _ForgetsRawStatus,
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

    async with _client() as http:
        opened = await http.post(HOOK, json=first, headers=_engine_headers())
        transitioned = await http.post(HOOK, json=later, headers=_engine_headers())
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

    row = await _inbox_row(execution_id, completed)
    assert row is not None
    assert row[1] >= 1, "the retry is counted as a delivery, not rejected"


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

_FORBIDDEN_AT_IMPORT = (
    # Vendor adapters — the only modules that know a vendor payload shape (hard rule 2).
    "apps.api.engine.bolna",
    "apps.api.engine.fake",
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
    real = bolna.throttle_delay_s

    def _spy(attempt: int, retry_after: float | None, **kwargs: Any) -> float:
        computed.append((attempt, retry_after))
        assert real(attempt, retry_after) > 0, "the real backoff would not have waited"
        return 0.0

    monkeypatch.setattr(bolna, "throttle_delay_s", _spy)
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
    assert len(seen) == bolna.THROTTLE_MAX_ATTEMPTS, "it gave up at the wrong attempt count"


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
    delays = {bolna.throttle_delay_s(0, None) for _ in range(50)}
    assert len(delays) > 1, "the backoff is deterministic — every worker retries in lockstep"
    assert all(d >= 0 for d in delays)

    # Full jitter over an exponentially growing ceiling: bounded, but never a constant.
    assert all(d <= bolna.THROTTLE_BASE_S for d in delays)
    assert all(
        bolna.throttle_delay_s(3, None, rand=lambda: 1.0) <= bolna.THROTTLE_MAX_SLEEP_S
        for _ in range(5)
    )

    honoured = bolna.throttle_delay_s(0, 2.0, rand=lambda: 0.0)
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


# Keys that exist only in Bolna's vocabulary. Reading one outside `apps/api/engine/`
# is a vendor shape escaping the adapter — hard rule 2 — even though no import moved.
_VENDOR_ONLY_KEYS = frozenset(
    {
        "telephony_data",
        "cost_breakdown",
        "conversation_duration",
        "extracted_data",
        "total_cost",
        "recipient_phone_number",
        "agent_config",
        "agent_prompts",
        "rag_id",
        "user_data",
        "recording_url",
        "transcript",
        "from_number",
        "to_number",
    }
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


def test_the_receiver_holds_no_vendor_payload_shape() -> None:
    """Hard rule 2 from the side the guardrail cannot see.

    The import-linter contract catches `from apps.api.engine.bolna import ...`. It does
    NOT catch this module learning that a Bolna execution carries `telephony_data` or
    `cost_breakdown` and quietly reading one — a vendor shape travels through a dict
    just as easily as through an import, and arrives with no import to review.

    The receiver is allowed exactly three keys (`execution_id`/`id`, `status`,
    `agent_id`), because those are the dedupe key and the routing hint. Everything
    else about the payload is the adapter's business, in a worker, later.
    """
    for module in (engine_intake, webhook_routes):
        path = Path(inspect.getsourcefile(module) or "")
        leaked = sorted(_dict_keys_read(path.read_text(encoding="utf-8")) & _VENDOR_ONLY_KEYS)
        assert not leaked, (
            f"{module.__name__} reads vendor-only keys {leaked} — that shape belongs in "
            "apps/api/engine/ (hard rule 2)"
        )
