"""Conformance fixtures: every adapter runs the SAME suite.

The suite lives in `packages/shared` on purpose — it tests the CONTRACT, not an
implementation, so it belongs next to the Protocol rather than inside `apps/api`.
Cartesia is exercised against a transport stub (`httpx.MockTransport`) fed payload
shapes from its generated client; Pipecat runs over an in-memory double of its database
and worker; the fake engine runs as itself. None touches the network —
`make conformance` must be runnable on a plane.

Adding an engine = adding one entry to `ENGINE_IDS` and a factory below. If the new
adapter cannot pass unchanged, the contract is wrong or the adapter is leaking.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from apps.api.agents.config_versions import Attestation, model_config_digest, prompt_digest
from apps.api.engine import cartesia as cartesia_module
from apps.api.engine.cartesia import CartesiaEngine
from apps.api.engine.fake import (
    DICTATED_SPEECH_CAPABILITIES,
    EXTERNAL_DEPLOYMENT_CAPABILITIES,
    OWNED_RUNTIME_CAPABILITIES,
    FakeEngine,
)
from apps.api.engine.pipecat import (
    PipecatEngine,
    RuntimeAgent,
)
from calevate_shared.engine import (
    AccountKBObject,
    AgentConfig,
    EngineAgentRef,
    EngineKBRef,
    EngineVoice,
    ExecutionSnapshot,
    VoiceEngine,
    compose_engine_prompt,
)
from calevate_shared.events import TranscriptTurn

#: SIX SUBJECTS, TWO OF THEM REAL ADAPTERS (D-93, D-639).
#:
#: `cartesia` is a real vendor that DISAGREES with us: it dictates its own STT and TTS, signs its
#: webhooks, and provisions no Indian number class. It is what makes "the contract is
#: vendor-neutral" a measurement rather than a hope. Its stub below is fed the same shapes the
#: adapter documents, at the same evidence standing, so the suite proves OUR mapping and our
#: contract; it proves nothing about Cartesia, and `apps/api/engine/cartesia.py` says so at every
#: line.
#:
#: `fake-restricted` is retained as the FAST TEST DOUBLE for the same capability profile:
#: the `FakeEngine` class running an engine-dictates-speech, no-knowledge-base,
#: signed-webhook descriptor, with no transport stub to maintain. It drives those paths
#: in unit tests cheaply, and it keeps the `hmac` branch executable with a verifier that
#: actually verifies (the Cartesia adapter's fails closed, by design, because its scheme
#: is unsourced).
#: `fake-deployed` is the FIFTH subject and the only one that satisfies the ALTERNATIVE
#: half of hard rule 5 (D-280/D-282): an engine whose agents are deployed elsewhere, whose
#: `create_agent`/`get_agent` refuse by name, and which carries our prompt onto every call
#: through `CallContext.system_prompt`. `cartesia` is the same SHAPE and cannot do the
#: second half — its outbound body has no prompt field, so it refuses every dial — so
#: without this fixture the branch where an externally-deployed engine actually dials
#: would be contract nothing executes. Same argument as `fake-restricted`, about a bigger
#: difference: a capability profile needs no vendor account and no imagined vendor JSON.
#:
#: `fake-owned-runtime` is the SIXTH and the only subject declaring the third
#: `AgentHosting` member (D-592, `docs/PIPECAT-MIGRATION.md` §1.1): we hold the agent
#: record AND run the program. Without it, `hosts_agents()` True would be exercised on one
#: shape only and `test_every_agent_hosting_shape_is_exercised_by_the_roster` would say so.
#: It stands in for the CAPABILITY half and not the witness half — a real `owned_runtime`
#: adapter answers `get_agent` from `agent_config_attestations`, written by a separate
#: process, and a fixture with no database and no second process cannot reproduce that.
#: Its clauses land with `apps/api/engine/pipecat.py`; see `fake.OWNED_RUNTIME_CAPABILITIES`.
#: `pipecat` is the SEVENTH and is the first REAL adapter on the owned-runtime shape
#: (D-592). It is here rather than left to `fake-owned-runtime` because that fixture says
#: in its own comment what it cannot do: it stands in for the CAPABILITY half and not for
#: the witness, because `FakeEngine` has no database and no second process, and the
#: attestation contract — `get_agent` answering from what a WORKER recomputed, and
#: reporting "nobody has confirmed this" when none has — is the whole of §1.1. Its double
#: below supplies the store AND the worker; see `_InMemoryControlPlane`.
#:
#: BOTH SUBJECTS STAY. The fixture keeps the hosting branches executable with no store at
#: all — it is what every OTHER clause in this file runs against on that shape, at fixture
#: speed — and deleting it would make the roster's hosting coverage depend on one adapter
#: that also has to be constructed with a double. They differ on `knowledge_base`,
#: `caller_id`, `inbound_binding`, `in_call_handoff` and `number_series`, so between them
#: the owned-runtime shape is exercised in BOTH directions of five capability clauses
#: rather than one; a single subject could only ever exercise its own answers.
ENGINE_IDS = [
    "fake",
    "fake-restricted",
    "fake-deployed",
    "fake-owned-runtime",
    "cartesia",
    "pipecat",
]


# A completed Line call in the shape Cartesia's OWN GENERATED CLIENT declares (D-270).
# Every key below is read at source in `cartesia-python/src/cartesia/types/agents/
# agent_call.py` and `.../agent_transcript.py`, so unlike the rest of this file's Cartesia
# fixtures it is not our inference reflected back at us — it is a machine translation of
# their OpenAPI spec. `docs/vendor/cartesia/calls-and-transcripts.md` carries the citation.
#
# What is ABSENT is as load-bearing as what is present, and each absence is a fact:
#   * no cost/currency of any kind — usage is an account-level daily credit meter, so the
#     adapter reports no cost and that is the answer rather than a deferral;
#   * no duration field — the adapter derives it from the two instants;
#   * no recording URL — audio is an authenticated download at `/agents/calls/{id}/audio`;
#   * no `direction` — there is nothing to read, so the adapter's default stands.
#
# `start_time` is minted RELATIVE TO NOW because the vendor offers no server-side time
# filter, so `list_executions` must apply `since` itself; a fixture frozen in the past
# would put every row outside every window and make the listing clauses pass vacuously.
def _cartesia_completed(call_id: str = "cart_call_1") -> dict[str, Any]:
    started = datetime.now(UTC) - timedelta(minutes=5)
    return {
        "id": call_id,
        "agent_id": "agent_xyz",
        "status": "completed",
        "start_time": started.isoformat().replace("+00:00", "Z"),
        "end_time": (started + timedelta(seconds=95)).isoformat().replace("+00:00", "Z"),
        "summary": "Caller asked for an appointment.",
        "telephony_params": {"from": "+919876543210", "to": "+911140000000"},
        "transcript": [
            {
                "role": "assistant",
                "text": "Namaskaram, idi Sunrise Clinic AI assistant.",
                "start_timestamp": 0.0,
                "end_timestamp": 3.2,
            },
            {
                "role": "user",
                "text": "Naaku appointment kavali.",
                "start_timestamp": 3.9,
                "end_timestamp": 5.4,
            },
            # A `system` row is a LOG entry, not speech — their own field documentation
            # says so. It is here because without it nothing proves the adapter refuses to
            # file instrumentation into a client's transcript as a caller utterance.
            {
                "role": "system",
                "start_timestamp": 5.5,
                "end_timestamp": 5.5,
                "log_event": {"event": "kb_lookup", "metadata": {}, "timestamp": 5.5},
            },
        ],
    }


# How many calls the FAKE engine is seeded with to saturate its listing. It is also that
# engine's configured page size, so one more call than this is a truncated window.
FULL_LISTING_PAGE = 10

CARTESIA_FULL_PAGE = cartesia_module._LISTING_PAGE_SIZE


def _cartesia_handler(*, listing_rows: int = 1) -> Callable[[httpx.Request], httpx.Response]:
    """A stub of Cartesia Line's control plane, at the adapter's own evidence standing.

    **THIS STUB PROVES NOTHING ABOUT CARTESIA.** It is built from the same sources the
    adapter cites — the OSS SDK for the host, version and document endpoint; a search
    summary for the outbound-call shape; RESTful inference for the rest — so it can only
    ever confirm that our mapping is self-consistent, which is the whole reason
    `OPERATIONS §2` keeps vendor behaviour as pilot GATES rather than tests.
    What it DOES prove is worth having: that a vendor with a different capability profile
    can satisfy this contract without any clause bending to accommodate it.

    STATEFUL agent and document stores: a stub that echoed the last write would let an echoing
    `get_agent` pass the read-back clause, and one that answered every DELETE with 200 would let a
    `detach_kb` that removes nothing sail through.
    """
    #: SEEDED WITH ONE AGENT.
    #: `GET /agents/calls` requires an `agent_id`, so `list_executions` fans out over
    #: `GET /agents` — and on this platform an account HAS agents whether or not our API
    #: client made them (they are deployed from git repositories). An empty account would
    #: make every listing clause pass vacuously with zero rows, which is the shape of stub
    #: this suite refuses everywhere else.
    agents: dict[str, dict[str, Any]] = {"agent_deployed": {"name": "deployed-from-repo"}}
    documents: dict[str, dict[str, dict[str, Any]]] = {}
    placed: list[str] = []
    #: Every call this stub placed, so `GET` and `/end` can answer 404 for one it did not:
    #: a stub that echoes any id makes the read-back and `end_call` clauses unfailable.
    calls_placed: set[str] = set()

    def agent_id_for(body: dict[str, Any]) -> str:
        # Derived from the NAME: stable across a re-create (the ref-stability clause needs
        # that) and distinct per agent (the read-back clause needs that).
        return "agent_" + hashlib.sha256(str(body.get("name") or "").encode()).hexdigest()[:8]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        body = json.loads(request.content or b"{}") if request.content else {}

        # The version pin is not decoration: assert it is sent on EVERY request, so a
        # future edit that drops the header fails here rather than on a vendor's next
        # breaking release. The auth header is asserted in the form their generated
        # clients actually send (`Authorization: Bearer …`), not merely as "present".
        assert request.headers.get("Cartesia-Version") == cartesia_module.API_VERSION
        assert (request.headers.get("Authorization") or "").startswith(
            f"{cartesia_module.AUTH_SCHEME} "
        )

        # THE CALL ROUTES COME FIRST. `/agents/calls` has the same shape as
        # `/agents/{id}`, so a generic agent match placed above would swallow it and
        # answer 404 for every listing — which is exactly what it did.
        if path == "/agents/calls" and method == "POST":
            assert body["outbound_calls"][0]["to_number"].startswith("+"), "E.164 only"
            assert body.get("from_number_id"), "a caller id must be named"
            # One id per dial: a stub that cannot tell two calls apart makes every clause about two
            # calls unfailable.
            placed.append(body["outbound_calls"][0]["to_number"])
            call_id = f"cart_call_{len(placed)}"
            calls_placed.add(call_id)
            return httpx.Response(200, json={"outbound_calls": [{"agent_call_id": call_id}]})
        if path == "/agents/calls" and method == "GET":
            # THE PUBLISHED LISTING CONTRACT, asserted rather than tolerated (D-270).
            # `agent_id` is `Required[str]` in their params type, so a listing without one
            # is a 4xx at the vendor and must be a failure here — the previous stub
            # answered a global, unfiltered listing that the real API cannot serve, which
            # is how the adapter came to send an invented `start_time` for months.
            query = request.url.params
            agent_id = query.get("agent_id")
            assert agent_id, "`agent_id` is required on GET /agents/calls"
            assert query.get("expand") == "transcript", (
                "without `expand=transcript` the vendor returns no transcript, and the "
                "poller is the path with no webhook behind it to supply one"
            )
            limit = int(query.get("limit") or 0)
            assert 1 <= limit <= 100, "`limit` ranges between 1 and 100"
            # Cursor by call id, their `starting_after`. Ids carry an ordinal so the stub
            # can continue a walk; a stub that ignored the cursor and re-served page one
            # would make the no-progress branch unreachable.
            after = query.get("starting_after")
            first = int(after.rsplit("_", 1)[-1]) + 1 if after else 0
            rows = [
                _cartesia_completed(f"{agent_id}_c_{i}") for i in range(first, first + listing_rows)
            ]
            calls_placed.update(str(row["id"]) for row in rows)
            # `{"data": [...]}` and NO `has_more`: their page model derives the next cursor
            # from the last row's id, so shortness is the only end-of-window signal.
            return httpx.Response(200, json={"data": rows})
        if path == "/agents" and method == "GET":
            # `{"summaries": [...]}` — read at source in `types/agent_list_response.py`.
            # This is what makes the per-agent listing reachable at all.
            return httpx.Response(
                200,
                json={"summaries": [{**stored, "id": ref} for ref, stored in agents.items()]},
            )
        if path.startswith("/agents/calls/") and path.endswith("/end"):
            # STATEFUL, and a marked assumption (D-187): nothing sourced says what Line answers for
            # a call it is not running, and the `end_call` clause is unfailable while the stub says
            # 200 to every id.
            call_id = path.rsplit("/", 2)[-2]
            if call_id not in calls_placed:
                return httpx.Response(404, json={"error": "unknown call"})
            return httpx.Response(200, json={"status": "ended"})
        if path.startswith("/agents/calls/") and method == "GET":
            # Echo the id asked about, and STATEFUL — see `calls_placed`.
            call_id = path.rsplit("/", 1)[-1]
            if call_id not in calls_placed:
                return httpx.Response(404, json={"error": "unknown call"})
            return httpx.Response(200, json=_cartesia_completed(call_id))
        if path == "/agents" and method == "POST":
            agent_id = agent_id_for(body)
            agents[agent_id] = body
            documents.setdefault(agent_id, {})
            return httpx.Response(200, json={"id": agent_id})
        if path.startswith("/agents/") and path.count("/") == 2 and method == "PATCH":
            agent_id = path.rsplit("/", 1)[-1]
            if agent_id not in agents:
                return httpx.Response(404, json={"error": "unknown agent"})
            agents[agent_id].update(body)
            return httpx.Response(200, json={"id": agent_id})
        if path.startswith("/agents/") and path.count("/") == 2 and method == "GET":
            agent_id = path.rsplit("/", 1)[-1]
            stored = agents.get(agent_id)
            if stored is None:
                return httpx.Response(404, json={"error": "unknown agent"})
            return httpx.Response(200, json={"agent": {**stored, "id": agent_id}})
        if path.startswith("/agents/") and path.count("/") == 2 and method == "DELETE":
            # Stateful, and the documents store goes with the agent: an agent object that
            # survived only as a bag of documents would let `get_agent` keep answering.
            agent_id = path.rsplit("/", 1)[-1]
            if agents.pop(agent_id, None) is None:
                return httpx.Response(404, json={"error": "unknown agent"})
            documents.pop(agent_id, None)
            return httpx.Response(200, json={"status": "deleted"})
        if path.endswith("/documents") and method == "POST":
            agent_id = path.split("/")[2]
            store = documents.setdefault(agent_id, {})
            doc_id = f"doc_{len(store) + 1}"
            store[doc_id] = {"id": doc_id, "title": body.get("title")}
            return httpx.Response(200, json={"id": doc_id})
        if path.endswith("/documents") and method == "GET":
            agent_id = path.split("/")[2]
            return httpx.Response(
                200, json={"documents": list(documents.get(agent_id, {}).values())}
            )
        if "/documents/" in path and method == "DELETE":
            agent_id, doc_id = path.split("/")[2], path.rsplit("/", 1)[-1]
            if documents.get(agent_id, {}).pop(doc_id, None) is None:
                # Their delete must 404 an id we never issued, or `detach_kb` can never be
                # proven to have removed anything (the clause that makes it mean something).
                return httpx.Response(404, json={"error": "unknown document"})
            return httpx.Response(200, json={"status": "deleted"})
        return httpx.Response(404, json={"error": "not found"})

    return handler


#: A stub of ONE vendor route, written by the clause that needs it rather than by this
#: file. The stubs above model a vendor BEHAVING; these model one misbehaving.
VendorHandler = Callable[[httpx.Request], httpx.Response]

#: How to point ONE HTTP-speaking adapter at a transport of the clause's choosing.
#:
#: Everything else in this file hands out adapters wired to a WELL-BEHAVED stub, so every
#: clause in the suite measured a happy path plus the handful of 404s the stubs are
#: stateful enough to produce. The failure paths an adapter meets in production — a
#: throttle, a gateway error, a socket that never answers, a 200 carrying a WAF challenge
#: — had no fixture at all, and that is how two real adapters came to disagree about all
#: of them (D-240): one retried a 429 and reported it `transient` while `cartesia` reported
#: it as a flat rejection with no backoff, and `cartesia` turned an unparseable 2xx into
#: `{}` and built an `ExecutionSnapshot` out of nothing.
#:
#: A RECIPE PER ADAPTER rather than one generic builder, because the credential, the base
#: URL and the version pin are exactly the per-vendor half `engine/vendor_http.py`
#: deliberately does not hold. Each call builds a FRESH adapter, so a transport wired to
#: answer 429 forever cannot leak into the next clause's subject.
TRANSPORT_RECIPES: dict[str, Callable[[VendorHandler], VoiceEngine]] = {
    "cartesia": lambda handler: CartesiaEngine(
        api_key="test-key",
        from_number_id="num_test",
        client=httpx.AsyncClient(
            base_url=cartesia_module.BASE_URL,
            headers={
                # `AUTH_HEADER`, not the old `API_KEY_HEADER`: D-271 moved the adapter
                # to `Authorization: Bearer` after reading both generated clients.
                cartesia_module.AUTH_HEADER: (f"{cartesia_module.AUTH_SCHEME} test-key"),
                cartesia_module.VERSION_HEADER: cartesia_module.API_VERSION,
            },
            transport=httpx.MockTransport(handler),
        ),
    ),
}


@pytest.fixture(params=sorted(TRANSPORT_RECIPES))
def ladder(request: pytest.FixtureRequest) -> Callable[[VendorHandler], VoiceEngine]:
    """One HTTP-speaking adapter, over whatever transport the clause hands it."""
    return TRANSPORT_RECIPES[str(request.param)]


@pytest.fixture
def transport_recipe_ids() -> frozenset[str]:
    """Which adapters the transport-ladder clauses actually ran against."""
    return frozenset(TRANSPORT_RECIPES)


@pytest.fixture
def http_speaking_engine_ids() -> frozenset[str]:
    """Which adapters in the roster reach their vendor over HTTP.

    Every real adapter does, by definition. `FakeEngine` is the one subject that does not,
    because it IS the vendor — so it is identified by its TYPE rather than by its name,
    and a third vendor added to `ENGINE_IDS` lands in this set automatically. That is what
    makes the roster clause in `contract_test.py` bite rather than pass vacuously.
    """
    return frozenset(
        eid for eid in ENGINE_IDS if not isinstance(make_engine(eid), _IN_PROCESS_ADAPTERS)
    )


#: THE VOICES THE `pipecat` DOUBLE'S DEPLOYMENT HAS ATTESTED.
#:
#: Two rows, one per speech vendor, because `TtsModel` has two members and a fixture with
#: one would let an adapter that filtered on a single provider pass. They are the shape an
#: OPERATOR typed and attested (`platform_voice_catalog`, `origin = 'operator'`, D-590),
#: which is what `SqlControlPlane.voices` reads and is the only honest source on an engine
#: whose speech vendors are not reachable from here.
#:
#: NEITHER IS A CLONE, and that is a real state rather than a gap: nothing in this tree has
#: read a cloned voice on this engine, and the clone clause explicitly does not fail an
#: adapter whose account holds none. The Cartesia speaker is a FIXTURE STRING and not a
#: voice id, `_VOICE_TIERS`' rule — nobody here has read one, and inventing one that looked
#: real would be laundering dressed as a fixture.
PIPECAT_FIXTURE_VOICES: tuple[EngineVoice, ...] = (
    EngineVoice(
        voice_id="anushka",
        label="Anushka",
        tts_model="sonic-3.5",
        languages=("te-IN", "hi-IN", "en-IN"),
    ),
    EngineVoice(
        voice_id="conformance-placeholder-not-a-real-voice-id",
        label="Conformance Sonic",
        tts_model="sonic-3.5",
        languages=("en-IN",),
    ),
)


class _InMemoryControlPlane:
    """The database AND the worker, in memory — the `pipecat` adapter's far side.

    **IT IS THE SAME KIND OF OBJECT AS `httpx.MockTransport`, NOT A SECOND ADAPTER.** Every
    other subject in this roster gets its offline property from a stub of the VENDOR;
    `PipecatEngine` has no vendor, and what it talks to is a database and a separate
    process, so this stands in for both. The adapter under test is the real one.

    **THE WORKER HALF IS THE PART THAT MATTERS, AND IT IS DELIBERATELY NOT AN ECHO.**
    `publish` records the version's content and then plays a worker that LOADED that
    content and recomputed the prompt digest from it — `prompt_digest` over the composed
    prompt, exactly as `apps/voice-worker/attest.py` will (§1.1). So the attestation is
    derived from what was STORED, never from what `get_agent` is about to be asked, and an
    adapter that minted one prompt while publishing another would be caught here rather
    than agreeing with itself. `attest(...)` lets a clause make that worker disagree, which
    is the only way the mismatch branch is reachable at all.
    """

    def __init__(self) -> None:
        self._agents: dict[EngineAgentRef, RuntimeAgent] = {}
        self._attested: dict[UUID, Attestation] = {}
        #: handle -> (kb_id, agent ref or None). The ref goes None on `forget`, never the
        #: row — an account object that outlives its agent is the residue
        #: `list_account_kb` exists to report, and a double that tidied it away would make
        #: that clause unfalsifiable.
        self._kb: dict[EngineKBRef, tuple[str, EngineAgentRef | None]] = {}
        self._executions: dict[str, ExecutionSnapshot] = {}

    async def publish(self, cfg: AgentConfig, *, ref: EngineAgentRef) -> UUID:
        version_id = uuid4()
        agent_id = UUID(cfg.agent_id)
        self._agents[ref] = RuntimeAgent(
            engine_agent_ref=ref,
            tenant_id=UUID(cfg.tenant_id),
            agent_id=agent_id,
            name=cfg.name,
            agent_config_version_id=version_id,
            published_at=datetime.now(UTC),
            config=cfg,
        )
        composed = compose_engine_prompt(cfg)
        # THE WORKER, and it starts a session immediately. A real one attests when it picks
        # the agent up; this one does it at publish because a conformance clause cannot
        # wait for a process. What it recomputes is the digest of the STORED prompt, which
        # is the property being modelled.
        self.attest(
            agent_id,
            version_id=version_id,
            worker_prompt_sha256=prompt_digest(cfg),
            composed_prompt=composed,
            opening_line=cfg.opening_line,
            models=cfg.models,
            expected_prompt_sha256=prompt_digest(cfg),
        )
        assert model_config_digest(cfg)  # the model digest is minted too; nothing reads it
        return version_id

    def attest(
        self,
        agent_id: UUID,
        *,
        version_id: UUID,
        worker_prompt_sha256: str,
        composed_prompt: str,
        opening_line: str,
        models: Any,
        expected_prompt_sha256: str,
    ) -> None:
        """Make a worker say what it loaded. Public so a clause can make it DISAGREE."""
        self._attested[agent_id] = Attestation(
            id=uuid4(),
            agent_id=agent_id,
            agent_config_version_id=version_id,
            prompt_sha256=worker_prompt_sha256,
            observed_at=datetime.now(UTC),
            expected_prompt_sha256=expected_prompt_sha256,
            composed_prompt=composed_prompt,
            opening_line=opening_line,
            models=models,
        )

    def forget_attestation(self, agent_id: UUID) -> None:
        """Put an agent back into the state every freshly-published agent is really in:
        published, never dialled, no worker has confirmed anything."""
        self._attested.pop(agent_id, None)

    async def runtime_agent(self, ref: EngineAgentRef) -> RuntimeAgent | None:
        return self._agents.get(ref)

    async def forget(self, ref: EngineAgentRef) -> None:
        self._agents.pop(ref, None)
        for handle, (kb_id, held_by) in list(self._kb.items()):
            if held_by == ref:
                self._kb[handle] = (kb_id, None)

    async def attested(self, agent: RuntimeAgent) -> Attestation | None:
        return self._attested.get(agent.agent_id)

    async def attach(self, agent: RuntimeAgent, *, handle: EngineKBRef, kb_id: str) -> None:
        self._kb[handle] = (kb_id, agent.engine_agent_ref)

    async def detach(self, agent: RuntimeAgent, *, handle: EngineKBRef) -> bool:
        held = self._kb.get(handle)
        if held is None or held[1] != agent.engine_agent_ref:
            return False
        del self._kb[handle]
        return True

    async def agent_kb(self, agent: RuntimeAgent) -> tuple[EngineKBRef, ...]:
        return tuple(
            sorted(h for h, (_, held_by) in self._kb.items() if held_by == agent.engine_agent_ref)
        )

    async def account_kb(self) -> tuple[AccountKBObject, ...]:
        return tuple(AccountKBObject(handle=handle, state="ready") for handle in sorted(self._kb))

    async def voices(self) -> tuple[EngineVoice, ...]:
        return PIPECAT_FIXTURE_VOICES

    async def execution(self, call_id: str) -> ExecutionSnapshot | None:
        return self._executions.get(call_id)

    async def executions(self, *, since: datetime) -> tuple[ExecutionSnapshot, ...]:
        return tuple(
            snapshot
            for snapshot in self._executions.values()
            if (snapshot.started_at or datetime.now(UTC)) >= since
        )

    def seed_execution(self, call_id: str) -> None:
        """Stage one session the runtime recorded — what `saturated()` needs.

        It is a SESSION and not a carrier record, which is the point of the clause it
        serves: `list_executions` reports a window carrying sessions as INCOMPLETE because
        the CDR that witnesses the billable half cannot be read (§1.2), and a double that
        seeded a reconciled call could never reach that branch.
        """
        now = datetime.now(UTC)
        self._executions[call_id] = ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref="pipecat:seed",
            direction="inbound",
            status="completed",
            raw_status="completed",
            terminal=True,
            # FALSE, and it is the honest value rather than a fixture convenience: the
            # billable quantity is witnessed by the party that bills the minute, and no
            # CDR has been read. §9.2 names `billable_ready` as a clause that keeps passing
            # while measuring nothing; here it measures exactly that.
            billable_ready=False,
            started_at=now - timedelta(seconds=95),
            ended_at=now,
            duration_s=95,
            transcript=[
                TranscriptTurn(call_id=call_id, idx=0, speaker="agent", text="Namaskaram.")
            ],
            engine="pipecat",
        )


#: THE ADAPTERS THAT REACH NO VENDOR OVER HTTP, so the transport ladder has nothing to
#: measure on them.
#:
#: It was `FakeEngine` alone and the comment said why — *"it IS the vendor"*. `PipecatEngine`
#: is the second, for the same structural reason rather than because it is a fixture: its
#: far side is our own database, and the ladder's clauses are all about what an adapter does
#: with a vendor's 429, 3xx, error body and dead socket. A tuple rather than a name check,
#: so `test_every_adapter_that_speaks_http_is_held_to_the_transport_clauses` still refuses
#: an HTTP-speaking adapter that simply forgot to add a recipe.
_IN_PROCESS_ADAPTERS: tuple[type, ...] = (FakeEngine, PipecatEngine)


def make_engine(engine_id: str, *, listing_rows: int = 1) -> VoiceEngine:
    if engine_id == "fake":
        return FakeEngine(listing_page_size=FULL_LISTING_PAGE)
    if engine_id == "fake-restricted":
        return FakeEngine(
            listing_page_size=FULL_LISTING_PAGE,
            capabilities=DICTATED_SPEECH_CAPABILITIES,
            # Its own name, not "fake": `WEBHOOK_AUTH_BY_ENGINE` is keyed by name and
            # this instance authenticates differently, so sharing a name would make that
            # table ambiguous — and the table is what the voice-runtime receiver reads.
            name="fake-restricted",
        )
    if engine_id == "fake-deployed":
        return FakeEngine(
            listing_page_size=FULL_LISTING_PAGE,
            capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES,
            # Its own name for `fake-restricted`'s reason: `WEBHOOK_AUTH_BY_ENGINE` is
            # keyed by name, and two instances answering to one name while declaring
            # different capabilities make that table ambiguous.
            name="fake-deployed",
        )
    if engine_id == "fake-owned-runtime":
        return FakeEngine(
            listing_page_size=FULL_LISTING_PAGE,
            capabilities=OWNED_RUNTIME_CAPABILITIES,
            # Its own name for `fake-restricted`'s reason: `WEBHOOK_AUTH_BY_ENGINE` is
            # keyed by name, and two instances answering to one name while declaring
            # different capabilities make that table ambiguous.
            name="fake-owned-runtime",
        )
    if engine_id == "pipecat":
        # The REAL adapter over a double of its database and its worker — see
        # `_InMemoryControlPlane` for why that is a vendor stub and not a second adapter.
        return PipecatEngine(store=_InMemoryControlPlane())
    if engine_id == "cartesia":
        return CartesiaEngine(
            api_key="test-key",
            # A caller id must be NAMED for an outbound call to be placeable at all —
            # the adapter refuses without one rather than dialling from whatever the
            # account happens to hold first. The stub asserts it arrives.
            from_number_id="num_test",
            client=httpx.AsyncClient(
                base_url=cartesia_module.BASE_URL,
                headers={
                    cartesia_module.AUTH_HEADER: f"{cartesia_module.AUTH_SCHEME} test-key",
                    cartesia_module.VERSION_HEADER: cartesia_module.API_VERSION,
                },
                transport=httpx.MockTransport(_cartesia_handler(listing_rows=listing_rows)),
            ),
        )
    raise AssertionError(f"no engine in the roster is called {engine_id!r}")


@pytest.fixture(params=ENGINE_IDS)
def engine(request: pytest.FixtureRequest) -> VoiceEngine:
    return make_engine(request.param)


def saturated(engine: VoiceEngine) -> VoiceEngine:
    """Drive an adapter's `list_executions` to a FULL page — the truncation case.

    Every adapter reaches it differently and none of them may EXPOSE how (hard rule 2):
    the Cartesia stub answers with exactly a page's worth of rows, the fake engine is
    given more calls than its page size, and the Pipecat double holds sessions it cannot
    reconcile. What the contract test asserts afterwards is identical for all of them —
    the caller is TOLD the answer may be short.

    A function rather than only a fixture because the adapter audit
    (`tests/engine_audit_test.py`) runs these clauses against saboteur adapters outside
    pytest's fixture machinery, and a clause it cannot set up is a clause no saboteur can
    ever fail.
    """
    if isinstance(engine, FakeEngine):
        # A FRESH instance of the same adapter class, never the one passed in: seeding
        # eleven calls into a shared engine would change what every other clause sees,
        # and a suite whose clauses interfere is one that fails in definition order.
        #
        # It carries the ORIGINAL's capabilities and name. Rebuilding with the defaults
        # would silently hand the truncation clause a fully-capable engine while the
        # parameter id still said `fake-restricted` — a saboteur could then hide in the
        # one clause whose subject is constructed rather than passed in.
        saturated_fake = type(engine)(
            listing_page_size=FULL_LISTING_PAGE,
            capabilities=engine.capabilities,
            name=engine.name,
        )
        for i in range(FULL_LISTING_PAGE + 1):
            saturated_fake.seed_inbound_call(
                call_id=f"exec_seed_{i}",
                agent_ref="fakeagent_seed",
                from_e164="+915000000001",
                to_e164="+911140000000",
            )
        return saturated_fake
    if isinstance(engine, PipecatEngine):
        # A FRESH adapter over a FRESH double, for the fake's reason: seeding sessions into
        # the subject other clauses share would change what every one of them sees. The
        # saturation here is not a page — there are no pages over our own store — it is the
        # condition §1.2 makes the listing's real verdict: sessions we hold and cannot
        # reconcile against the carrier's CDR.
        saturated_store = _InMemoryControlPlane()
        for i in range(FULL_LISTING_PAGE + 1):
            saturated_store.seed_execution(f"pipecat_seed_{i}")
        return PipecatEngine(store=saturated_store)
    assert isinstance(engine, CartesiaEngine), f"no saturation recipe for {type(engine).__name__}"
    return make_engine("cartesia", listing_rows=CARTESIA_FULL_PAGE)


@pytest.fixture(params=ENGINE_IDS)
def saturated_engine(request: pytest.FixtureRequest) -> VoiceEngine:
    return saturated(make_engine(str(request.param)))


@pytest.fixture
def declared_agent_hostings() -> frozenset[str]:
    """Every `agent_hosting` value the roster actually declares.

    Built here rather than in the clause because `ENGINE_IDS` and `make_engine` live here:
    the clause asks which shapes are exercised, and this answers it from the same roster
    every other fixture is parametrised over, so the two cannot describe different suites.
    """
    return frozenset(make_engine(eid).capabilities.agent_hosting for eid in ENGINE_IDS)


@pytest.fixture
def engine_id(request: pytest.FixtureRequest) -> str:
    return str(request.node.callspec.params["engine"])
