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
from apps.api.engine import cartesia as cartesia_module
from apps.api.engine.bolna import BolnaEngine
from apps.api.engine.cartesia import CartesiaEngine
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from calevate_shared.engine import VoiceEngine

#: FOUR SUBJECTS, THREE OF THEM REAL ADAPTERS (D-93).
#:
#: `cartesia` is the second real vendor and the first that DISAGREES with us: it dictates
#: its own STT and TTS, signs its webhooks, and provisions no Indian number class. It is
#: what makes "the contract is vendor-neutral" a measurement rather than a hope — that
#: claim and "the contract is Bolna-shaped" are indistinguishable while only one vendor
#: exists. Its stub below is fed the same shapes the adapter documents, at the same
#: evidence standing, so the suite proves OUR mapping and our contract; it proves nothing
#: about Cartesia, and `apps/api/engine/cartesia.py` says so at every line.
#:
#: `fake-restricted` is retained as the FAST TEST DOUBLE for the same capability profile:
#: the `FakeEngine` class running an engine-dictates-speech, no-knowledge-base,
#: signed-webhook descriptor, with no transport stub to maintain. It drives those paths
#: in unit tests cheaply, and it keeps the `hmac` branch executable with a verifier that
#: actually verifies (the Cartesia adapter's fails closed, by design, because its scheme
#: is unsourced).
ENGINE_IDS = ["fake", "fake-restricted", "bolna", "cartesia"]

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


# A completed Line call, in the shapes `cartesia.py` documents — role-based transcript
# entries, ISO timestamps, and NO cost object, because the adapter deliberately reports
# no cost for this vendor (nothing sourced says what currency Line quotes, and a stamped
# guess is worse than no number at all).
CARTESIA_COMPLETED: dict[str, Any] = {
    "agent_call_id": "cart_call_1",
    "agent_id": "agent_xyz",
    "status": "completed",
    "direction": "inbound",
    "started_at": "2026-08-10T09:15:00Z",
    "ended_at": "2026-08-10T09:16:35Z",
    "duration_seconds": 95,
    "from_number": "+919876543210",
    "to_number": "+911140000000",
    "recording_url": "https://storage.cartesia.ai/recordings/cart_call_1.wav",
    "transcript": [
        {"role": "assistant", "content": "Namaskaram, idi Sunrise Clinic AI assistant."},
        {"role": "user", "content": "Naaku appointment kavali."},
    ],
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
    #: The numbers this stub has been asked to dial, so each dial gets its own execution
    #: id. See the `POST /call` branch.
    placed: list[str] = []
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
        if path.startswith("/v2/agent/") and request.method == "DELETE":
            # STATEFUL, for the reason the GET above is: a stub that answered every
            # DELETE with 200 would let an adapter that removes nothing pass the delete
            # clause, which is the one defect that clause exists to catch.
            #
            # THE 404 ON A REPEAT IS THIS SUITE'S ASSUMPTION AS MUCH AS THE ADAPTER'S,
            # and `BolnaEngine.delete_agent` says so in the marked-assumption block: the
            # vendor documents 200 and 400 and nothing about a second delete. Encoding
            # 404 here proves our HANDLING of a 404 and proves nothing about Bolna —
            # exactly the standing every shape in this stub has (see `_cartesia_handler`).
            agent_id = path.rsplit("/", 1)[-1]
            if agents.pop(agent_id, None) is None:
                return httpx.Response(404, json={"error": "unknown agent"})
            return httpx.Response(200, json={"message": "success", "state": "deleted"})
        if path == "/call" and request.method == "POST":
            body = json.loads(request.content or b"{}")
            assert body["recipient_phone_number"].startswith("+"), "E.164 only"
            # A DISTINCT id per dial, derived from the number dialled. A stub that answered
            # every `POST /call` with one execution id made two calls indistinguishable, so
            # any clause about telling two executions apart — the archived document is the
            # first — could only ever be failed by the stub. Vendors mint one id per call;
            # a stub that does not is a stub that hides that class of defect.
            placed.append(body["recipient_phone_number"])
            return httpx.Response(200, json={"execution_id": f"exec_abc{len(placed):03d}"})
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
            # The id is ECHOED from the path. Answering with the fixture's own id for any
            # id asked about is the `get_agent` echo defect wearing a different route: it
            # makes one execution's document indistinguishable from another's, which the
            # archive clause exists to refuse.
            return httpx.Response(200, json={**BOLNA_COMPLETED, "id": path.rsplit("/", 1)[-1]})
        return httpx.Response(404, json={"error": "not found"})

    return handler


#: How many calls a saturated Cartesia listing returns. Equal to the adapter's
#: `_LISTING_PAGE_SUSPECT` on purpose: that constant IS the adapter's truncation
#: heuristic, so restating the number here would let the two drift and quietly stop
#: exercising the branch.
CARTESIA_FULL_PAGE = cartesia_module._LISTING_PAGE_SUSPECT


def _cartesia_handler(*, listing_rows: int = 1) -> Callable[[httpx.Request], httpx.Response]:
    """A stub of Cartesia Line's control plane, at the adapter's own evidence standing.

    **THIS STUB PROVES NOTHING ABOUT CARTESIA.** It is built from the same sources the
    adapter cites — the OSS SDK for the host, version and document endpoint; a search
    summary for the outbound-call shape; RESTful inference for the rest — so it can only
    ever confirm that our mapping is self-consistent. That is exactly what the Bolna stub
    does (its `GET /v2/agent` shape is equally hand-maintained), and it is the whole
    reason `OPERATIONS §2` keeps vendor behaviour as pilot GATES rather than tests.
    What it DOES prove is worth having: that a vendor with a different capability profile
    can satisfy this contract without any clause bending to accommodate it.

    STATEFUL agent and document stores, for the reasons the Bolna stub is stateful: a stub
    that echoed the last write would let an echoing `get_agent` pass the read-back clause,
    and one that answered every DELETE with 200 would let a `detach_kb` that removes
    nothing sail through.
    """
    agents: dict[str, dict[str, Any]] = {}
    documents: dict[str, dict[str, dict[str, Any]]] = {}
    placed: list[str] = []

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
        # breaking release.
        assert request.headers.get("Cartesia-Version") == cartesia_module.API_VERSION
        assert request.headers.get("X-API-Key")

        # THE CALL ROUTES COME FIRST. `/agents/calls` has the same shape as
        # `/agents/{id}`, so a generic agent match placed above would swallow it and
        # answer 404 for every listing — which is exactly what it did.
        if path == "/agents/calls" and method == "POST":
            assert body["outbound_calls"][0]["to_number"].startswith("+"), "E.164 only"
            assert body.get("from_number_id"), "a caller id must be named"
            # One id per dial, for the reason the Bolna stub mints one: a stub that cannot
            # tell two calls apart makes every clause about two calls unfailable.
            placed.append(body["outbound_calls"][0]["to_number"])
            return httpx.Response(
                200, json={"outbound_calls": [{"agent_call_id": f"cart_call_{len(placed)}"}]}
            )
        if path == "/agents/calls" and method == "GET":
            rows = [{**CARTESIA_COMPLETED, "agent_call_id": f"c_{i}"} for i in range(listing_rows)]
            return httpx.Response(200, json={"calls": rows})
        if path.startswith("/agents/calls/") and path.endswith("/end"):
            return httpx.Response(200, json={"status": "ended"})
        if path.startswith("/agents/calls/") and method == "GET":
            # Echo the id asked about — see the Bolna stub's `/executions/` branch.
            return httpx.Response(
                200, json={**CARTESIA_COMPLETED, "agent_call_id": path.rsplit("/", 1)[-1]}
            )
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
                    cartesia_module.API_KEY_HEADER: "test-key",
                    cartesia_module.VERSION_HEADER: cartesia_module.API_VERSION,
                },
                transport=httpx.MockTransport(_cartesia_handler(listing_rows=listing_rows)),
            ),
        )
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
    if isinstance(engine, CartesiaEngine):
        return make_engine("cartesia", listing_rows=CARTESIA_FULL_PAGE)
    assert isinstance(engine, BolnaEngine), f"no saturation recipe for {type(engine).__name__}"
    return make_engine("bolna", listing_rows=FULL_LISTING_PAGE)


@pytest.fixture(params=ENGINE_IDS)
def saturated_engine(request: pytest.FixtureRequest) -> VoiceEngine:
    return saturated(make_engine(str(request.param)))


@pytest.fixture
def engine_id(request: pytest.FixtureRequest) -> str:
    return str(request.node.callspec.params["engine"])
