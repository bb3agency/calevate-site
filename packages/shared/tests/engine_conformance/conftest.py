"""Conformance fixtures: every adapter runs the SAME suite.

The suite lives in `packages/shared` on purpose — it tests the CONTRACT, not an
implementation, so it belongs next to the Protocol rather than inside `apps/api`.
Bolna is exercised against a transport stub (`httpx.MockTransport`) fed payload
shapes captured from their docs; the fake engine runs as itself. Neither test touches
the network — `make conformance` must be runnable on a plane.

Adding an engine = adding one entry to `ENGINE_IDS` and a factory below. If the new
adapter cannot pass unchanged, the contract is wrong or the adapter is leaking.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.engine.bolna import BolnaEngine
from apps.api.engine.fake import FakeEngine
from calevate_shared.engine import VoiceEngine

ENGINE_IDS = ["fake", "bolna"]

# A completed execution as Bolna documents it: USD-cent costs with a per-leg
# breakdown, prefix-tagged transcript text, recording on their S3.
BOLNA_COMPLETED: dict[str, Any] = {
    "id": "exec_abc123",
    "agent_id": "agent_xyz",
    "status": "completed",
    "direction": "inbound",
    "created_at": "2026-08-10T09:15:00Z",
    "ended_at": "2026-08-10T09:16:35Z",
    "conversation_duration": 95,
    "total_cost": 8.5,
    "cost_breakdown": {
        "platform": 5.0,
        "network": 1.5,
        "llm": 0.0,
        "synthesizer": 1.4,
        "transcriber": 0.6,
    },
    "telephony_data": {
        "from_number": "+919876543210",
        "to_number": "+911140000000",
        "recording_url": "https://s3.us-east-1.amazonaws.com/bolna/exec_abc123.wav",
    },
    "transcript": (
        "assistant: Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi.\n"
        "user: Naaku appointment kavali.\n"
        "assistant: Tappakunda, ee roju evening 6 gantalaku doctor available unnaru.\n"
        "user: Sare, naa peru Ravi."
    ),
    "extracted_data": {},
}


# How many executions a saturated `GET /executions` hands back in this suite. It is a
# member of `bolna._LISTING_PAGE_SIZES` on purpose: the Bolna stub returns exactly this
# many rows and NO pagination metadata, which is the worst case the adapter has to cope
# with (Bolna publishes no pagination contract), and the fake engine's page size is set
# to the same number so one contract test can saturate either adapter.
FULL_LISTING_PAGE = 10


def _bolna_handler(*, listing_rows: int = 1) -> Callable[[httpx.Request], httpx.Response]:
    """A stub of their API, built fresh per engine so each test gets clean vendor state.

    What the agent store deliberately does NOT contain: any knowledge-base reference
    inside the agent object. Nothing in Bolna's published documentation says the agent
    carries one or what it would be called (`BolnaEngine.get_agent`), so inventing a
    `rag_id` field here would make the suite assert our own guess back at us. The Bolna
    adapter therefore reports `knowledge_base_refs_readable=False` through this stub, and
    the contract clause treats that as the honest "cannot tell" it is — D-41's question
    is settled at pilot gate 8, not in a fixture.

    The knowledge-base routes are STATEFUL on purpose. A stub that answered every
    `POST /knowledgebase` with the same `rag_id` and every `DELETE` with 200 would let
    an adapter that never detaches anything sail through the suite — the exact defect
    the KB clause exists to catch. So this keeps a store: creates mint distinct ids,
    the listing reflects it, and deleting an id the store does not hold 404s, which is
    what their `rag_id`-addressed CRUD API (TRD §5) does.
    """
    knowledge_bases: dict[str, dict[str, Any]] = {}
    # The AGENT store, and it is stateful for the same reason the KB routes are: a stub
    # that answered every `GET /v2/agent/{id}` with the body of the last write would let
    # an adapter that echoes what it was handed pass the read-back clause, which is the
    # one defect that clause exists to catch. So writes are filed under an id derived
    # from the agent's NAME — stable across a re-create (the ref-stability clause needs
    # that) and distinct per agent (the read-back clause needs that) — and the GET
    # returns the stored object in the `{"agent_id": ..., "data": {...}}` envelope their
    # OSS server's `GET /all` is documented to use.
    agents: dict[str, dict[str, Any]] = {}

    def agent_id_for(body: dict[str, Any]) -> str:
        config = body.get("agent_config") or {}
        name = str(config.get("agent_name") or "")
        return "agent_" + hashlib.sha256(name.encode()).hexdigest()[:8]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v2/agent" and request.method == "POST":
            body = json.loads(request.content or b"{}")
            agent_id = agent_id_for(body)
            agents[agent_id] = body
            return httpx.Response(200, json={"agent_id": agent_id})
        if path.startswith("/v2/agent/") and request.method == "PUT":
            agent_id = path.rsplit("/", 1)[-1]
            if agent_id not in agents:
                return httpx.Response(404, json={"error": "unknown agent"})
            agents[agent_id] = json.loads(request.content or b"{}")
            return httpx.Response(200, json={"status": "ok"})
        if path.startswith("/v2/agent/") and request.method == "GET":
            agent_id = path.rsplit("/", 1)[-1]
            stored = agents.get(agent_id)
            if stored is None:
                return httpx.Response(404, json={"error": "unknown agent"})
            return httpx.Response(200, json={"agent_id": agent_id, "data": stored})
        if path == "/call" and request.method == "POST":
            body = json.loads(request.content or b"{}")
            assert body["recipient_phone_number"].startswith("+"), "E.164 only"
            return httpx.Response(200, json={"execution_id": "exec_abc123"})
        if path == "/knowledgebase" and request.method == "POST":
            body = json.loads(request.content or b"{}")
            rag_id = f"kb_{len(knowledge_bases) + 1}"
            knowledge_bases[rag_id] = {
                "rag_id": rag_id,
                "agent_id": body.get("agent_id"),
                "name": body.get("name"),
            }
            return httpx.Response(200, json={"rag_id": rag_id})
        if path == "/knowledgebase/all" and request.method == "GET":
            return httpx.Response(200, json={"data": list(knowledge_bases.values())})
        if path.startswith("/knowledgebase/") and request.method == "DELETE":
            rag_id = path.rsplit("/", 1)[-1]
            if knowledge_bases.pop(rag_id, None) is None:
                return httpx.Response(404, json={"error": "unknown rag_id"})
            return httpx.Response(200, json={"status": "deleted"})
        if path.startswith("/executions/") and path.endswith("/stop"):
            return httpx.Response(200, json={"status": "stopped"})
        if path == "/executions":
            # Distinct ids: a listing whose rows all share one id would let an adapter
            # that de-duplicates too eagerly look like one that read a short page.
            rows = [{**BOLNA_COMPLETED, "id": f"exec_list_{i}"} for i in range(listing_rows)]
            return httpx.Response(200, json={"data": rows})
        if path.startswith("/executions/"):
            return httpx.Response(200, json=BOLNA_COMPLETED)
        return httpx.Response(404, json={"error": "not found"})

    return handler


def make_engine(engine_id: str, *, listing_rows: int = 1) -> VoiceEngine:
    if engine_id == "fake":
        return FakeEngine(listing_page_size=FULL_LISTING_PAGE)
    return BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai",
            transport=httpx.MockTransport(_bolna_handler(listing_rows=listing_rows)),
        ),
    )


@pytest.fixture(params=ENGINE_IDS)
def engine(request: pytest.FixtureRequest) -> VoiceEngine:
    return make_engine(request.param)


def saturated(engine: VoiceEngine) -> VoiceEngine:
    """Drive an adapter's `list_executions` to a FULL page — the truncation case.

    Every adapter reaches it differently and none of them may EXPOSE how (hard rule 2):
    the Bolna stub answers with exactly a page's worth of rows and no metadata at all
    (the worst case, since Bolna publishes no pagination contract), and the fake engine
    is given more calls than its page size. What the contract test asserts afterwards is
    identical for both — the caller is TOLD the answer may be short.

    A function rather than only a fixture because the adapter audit
    (`tests/engine_audit_test.py`) runs these clauses against saboteur adapters outside
    pytest's fixture machinery, and a clause it cannot set up is a clause no saboteur can
    ever fail.
    """
    if isinstance(engine, FakeEngine):
        # A FRESH instance of the same adapter class, never the one passed in: seeding
        # eleven calls into a shared engine would change what every other clause sees,
        # and a suite whose clauses interfere is one that fails in definition order.
        saturated_fake = type(engine)(listing_page_size=FULL_LISTING_PAGE)
        for i in range(FULL_LISTING_PAGE + 1):
            saturated_fake.seed_inbound_call(
                call_id=f"exec_seed_{i}",
                agent_ref="fakeagent_seed",
                from_e164="+915000000001",
                to_e164="+911140000000",
            )
        return saturated_fake
    assert isinstance(engine, BolnaEngine), f"no saturation recipe for {type(engine).__name__}"
    return make_engine("bolna", listing_rows=FULL_LISTING_PAGE)


@pytest.fixture(params=ENGINE_IDS)
def saturated_engine(request: pytest.FixtureRequest) -> VoiceEngine:
    return saturated(make_engine(str(request.param)))


@pytest.fixture
def engine_id(request: pytest.FixtureRequest) -> str:
    return str(request.node.callspec.params["engine"])
