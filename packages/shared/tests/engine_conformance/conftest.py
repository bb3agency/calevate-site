"""Conformance fixtures: every adapter runs the SAME suite.

The suite lives in `packages/shared` on purpose — it tests the CONTRACT, not an
implementation, so it belongs next to the Protocol rather than inside `apps/api`.
ThinnestAI is exercised against a transport stub (`httpx.MockTransport`) fed the payload
shapes its documentation prints; the fake engine runs as itself. None touches the network —
`make conformance` must be runnable on a plane.

Adding an engine = adding one entry to `ENGINE_IDS` and a factory below. If the new
adapter cannot pass unchanged, the contract is wrong or the adapter is leaking.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.engine.fake import (
    DICTATED_SPEECH_CAPABILITIES,
    EXTERNAL_DEPLOYMENT_CAPABILITIES,
    FakeEngine,
)
from apps.api.engine.thinnest import BASE_URL as THINNEST_BASE_URL
from apps.api.engine.thinnest import ThinnestEngine
from calevate_shared.engine import VoiceEngine

#: FOUR SUBJECTS, ONE OF THEM A REAL ADAPTER.
#:
#: `thinnest` is the production adapter, over a stub of its documented REST surface.
#:
#: `fake-restricted` is the `FakeEngine` class running an engine-dictates-speech descriptor
#: with a signed-webhook verifier, so the speech-control refusals and the `hmac` branch stay
#: executable with no transport stub to maintain.
#:
#: `fake-deployed` is the only subject that satisfies the ALTERNATIVE half of hard rule 5
#: (D-280/D-282): an engine whose agents are deployed elsewhere, whose
#: `create_agent`/`get_agent` refuse by name, and which carries our prompt onto every call
#: through `CallContext.system_prompt`. Without it the branch where an externally-deployed
#: engine actually dials would be contract nothing executes.
ENGINE_IDS = [
    "fake",
    "fake-restricted",
    "fake-deployed",
    "thinnest",
]


# How many calls the FAKE engine is seeded with to saturate its listing. It is also that
# engine's configured page size, so one more call than this is a truncated window.
FULL_LISTING_PAGE = 10

THINNEST_FULL_PAGE = 100


def _thinnest_call(call_id: str, *, agent: str, to: str, frm: str | None) -> dict[str, Any]:
    """A finished outbound call in the shape `GET /calls/{id}` prints
    (`thinnest-findings/mirror/pages/api-reference/get-call.md:14-47`): numbers without `+`,
    an `agent` object, a `team` turn the adapter must not file under either party, and a
    recording that is ready. `startedAt` is relative to now so `since` windows include it."""
    started = datetime.now(UTC) - timedelta(minutes=5)
    return {
        "id": call_id,
        "callRef": call_id,
        "reference": None,
        "metadata": {},
        "attempt": 1,
        "status": "completed",
        "direction": "outbound",
        "phone": to.lstrip("+"),
        "from": frm.lstrip("+") if frm else "918045678901",
        "agent": {"id": agent, "name": "Conformance agent"},
        "scheduledFor": None,
        "startedAt": started.isoformat().replace("+00:00", "Z"),
        "answeredAt": (started + timedelta(seconds=7)).isoformat().replace("+00:00", "Z"),
        "endedAt": (started + timedelta(seconds=182)).isoformat().replace("+00:00", "Z"),
        "seconds": 182,
        "hangup": "answered",
        "variables": {},
        "summary": None,
        "fields": {},
        "transcript": [
            {"speaker": "agent", "text": "Namaskaram, idi AI assistant.", "at": "x"},
            {"speaker": "customer", "text": "Naaku appointment kavali.", "at": "x"},
            {"speaker": "team", "text": "Joining from the desk.", "at": "x"},
        ],
        "recording": {
            "url": f"https://app.thinnest.ai/api/v1/recordings/{call_id}?sig=x",
            "expiresAt": "2026-11-05T00:00:00Z",
            "ready": True,
        },
        "analysedAt": (started + timedelta(seconds=190)).isoformat().replace("+00:00", "Z"),
        "retryScheduledFor": None,
        "error": None,
    }


def _thinnest_handler(*, listing_rows: int = 1) -> Callable[[httpx.Request], httpx.Response]:
    """ThinnestAI's REST surface in memory, in the shapes the mirror prints
    (`thinnest-findings/mirror/pages/api-reference/`). Stateful because
    agents, documents and calls the stub never issued answer 404, and `POST
    /agents` mints a NEW id every time, as the real create does, so `create_agent`'s
    find-by-tag is what keeps a re-create stable. A request the docs do not describe is a
    404. `listing_rows` at a full page makes the call list cursor forever, which is the
    truncation case."""
    agents: dict[str, dict[str, Any]] = {}
    documents: dict[str, dict[str, dict[str, Any]]] = {}
    calls: dict[str, dict[str, Any]] = {}
    idempotent: dict[str, str] = {}
    counter = {"agent": 0, "doc": 0, "call": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer test-key"
        path = request.url.path.removeprefix("/api/v1")
        method = request.method
        body = json.loads(request.content) if request.content else {}
        query = request.url.params
        if method == "GET" and path in ("/agents", "/calls", "/phone-numbers", "/voices"):
            assert 1 <= int(query.get("limit") or 0) <= 100, "`limit` is 1-100"
        parts = path.strip("/").split("/")

        if path == "/agents" and method == "GET":
            rows = [{"id": ref, "name": agent["name"]} for ref, agent in agents.items()]
            return httpx.Response(200, json={"items": rows, "nextCursor": None})
        if path == "/agents" and method == "POST":
            assert 2 <= len(body["name"]) <= 60
            assert len(body["instructions"]) <= 20_000 and len(body["greeting"]) <= 200
            counter["agent"] += 1
            ref = f"ag_{counter['agent']:04d}"
            agents[ref] = {"id": ref, **body}
            documents[ref] = {}
            return httpx.Response(201, json=agents[ref])
        if len(parts) == 2 and parts[0] == "agents":
            ref = parts[1]
            if ref not in agents:
                return httpx.Response(404, json={"error": "No such agent in your workspace."})
            if method == "GET":
                return httpx.Response(200, json=agents[ref])
            if method == "PATCH":
                agents[ref].update(body)
                return httpx.Response(200, json=agents[ref])
            if method == "DELETE":
                agents.pop(ref)
                documents.pop(ref, None)
                return httpx.Response(204)
        if len(parts) == 3 and parts[0] == "agents" and parts[2] == "tools":
            # `GET`/`PATCH /agents/{id}/tools` (snapshots/2026-10-08/pages/api-reference/
            # tools/update-built-in-tools.md:553-790): the switches as saved, and the hand-over.
            ref = parts[1]
            if ref not in agents:
                return httpx.Response(404, json={"error": "No such agent in your workspace."})
            held = agents[ref].setdefault(
                "_tools", {"switches": {}, "handOver": {"mode": "chat", "phone": None}}
            )
            if method == "PATCH":
                held["switches"].update(body.get("tools", {}))
                held["handOver"].update(body.get("handOver", {}))
            rows = [{"id": tool, "enabled": on} for tool, on in held["switches"].items()]
            return httpx.Response(200, json={"tools": rows, "handOver": held["handOver"]})
        if len(parts) >= 3 and parts[0] == "agents" and parts[2] == "knowledge":
            ref = parts[1]
            if ref not in agents:
                return httpx.Response(404, json={"error": "No such agent in your workspace."})
            store = documents[ref]
            if len(parts) == 3 and method == "POST":
                assert body.get("text") and "url" not in body
                counter["doc"] += 1
                doc = f"doc_{counter['doc']:04d}"
                store[doc] = {"id": doc, "title": body.get("title"), "status": "ready"}
                return httpx.Response(201, json={**store[doc], "type": "text", "passages": 1})
            if len(parts) == 3 and method == "GET":
                return httpx.Response(200, json={"items": list(store.values()), "nextCursor": None})
            if len(parts) == 4 and method == "DELETE":
                if store.pop(parts[3], None) is None:
                    return httpx.Response(404, json={"error": "No such document."})
                return httpx.Response(204)
        if path == "/calls" and method == "POST":
            for field in ("to", "purpose"):
                assert body.get(field), f"`{field}` is required"
            assert len(body["purpose"]) <= 300
            assert "retry" not in body
            hours = body.get("callingHours")
            if hours is not None:
                # Place Call: `start` and `end` as HH:MM, start earlier than end (else 400
                # validation_failed); docs.thinnest.ai/api-reference/calls/place-call, read
                # 24 Oct 2026. Our dials refuse rather than queue outside them (D-872).
                assert set(hours) <= {"start", "end", "days", "timezone"}
                assert re.fullmatch(r"\d{2}:\d{2}", hours["start"])
                assert re.fullmatch(r"\d{2}:\d{2}", hours["end"])
                assert hours["start"] < hours["end"]
                assert body.get("ifOutsideHours") == "refuse"
            key = request.headers.get("Idempotency-Key")
            if key and key in idempotent:
                return httpx.Response(202, json={"id": idempotent[key], "status": "ringing"})
            counter["call"] += 1
            call_id = f"out_{counter['call']:04d}"
            calls[call_id] = _thinnest_call(
                call_id, agent=body["agent"], to=body["to"], frm=body.get("from")
            )
            if key:
                idempotent[key] = call_id
            return httpx.Response(202, json={"id": call_id, "status": "ringing"})
        if path == "/calls" and method == "GET":
            assert query.get("since"), "the poller always bounds its window"
            page = int(query.get("cursor") or "0")
            rows = [
                {k: v for k, v in call.items() if k not in ("transcript", "recording")}
                for call in calls.values()
            ]
            rows += [
                {
                    k: v
                    for k, v in _thinnest_call(
                        f"inb_{page}_{i}", agent="ag_inbound", to="+919000000001", frm=None
                    ).items()
                    if k not in ("transcript", "recording")
                }
                | {"direction": "inbound"}
                for i in range(listing_rows)
            ]
            cursor = str(page + 1) if listing_rows >= THINNEST_FULL_PAGE else None
            return httpx.Response(200, json={"items": rows, "nextCursor": cursor})
        if len(parts) == 2 and parts[0] == "calls":
            call = calls.get(parts[1])
            if call is None:
                return httpx.Response(404, json={"error": "No such call."})
            if method == "GET":
                return httpx.Response(200, json=call)
            if method == "DELETE":
                return httpx.Response(202, json={**call, "status": "ringing", "hangup": None})
        if path == "/phone-numbers" and method == "GET":
            row = {"number": "918012345678", "label": "Sales", "source": "rented", "agent": None}
            return httpx.Response(200, json={"items": [row], "nextCursor": None})
        return httpx.Response(404, json={"error": "not found"})

    return handler


def _thinnest_engine(handler: Callable[[httpx.Request], httpx.Response]) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="test-key",
        client=httpx.AsyncClient(
            base_url=THINNEST_BASE_URL,
            headers={"Authorization": "Bearer test-key"},
            transport=httpx.MockTransport(handler),
        ),
    )


#: A stub of ONE vendor route, written by the clause that needs it rather than by this
#: file. The stubs above model a vendor BEHAVING; these model one misbehaving.
VendorHandler = Callable[[httpx.Request], httpx.Response]

#: How to point ONE HTTP-speaking adapter at a transport of the clause's choosing.
#:
#: Everything else in this file hands out adapters wired to a WELL-BEHAVED stub. The failure
#: paths an adapter meets in production — a throttle, a gateway error, a socket that never
#: answers, a 200 carrying a WAF challenge — are what these recipes let a clause write
#: (D-240).
#:
#: A RECIPE PER ADAPTER rather than one generic builder, because the credential, the base
#: URL and the version pin are exactly the per-vendor half `engine/vendor_http.py`
#: deliberately does not hold. Each call builds a FRESH adapter, so a transport wired to
#: answer 429 forever cannot leak into the next clause's subject.
TRANSPORT_RECIPES: dict[str, Callable[[VendorHandler], VoiceEngine]] = {
    "thinnest": _thinnest_engine,
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


#: THE ADAPTERS THAT REACH NO VENDOR OVER HTTP, so the transport ladder has nothing to
#: measure on them. `FakeEngine` IS the vendor. A tuple rather than a name check, so
#: `test_every_adapter_that_speaks_http_is_held_to_the_transport_clauses` still refuses an
#: HTTP-speaking adapter that simply forgot to add a recipe.
_IN_PROCESS_ADAPTERS: tuple[type, ...] = (FakeEngine,)


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
    if engine_id == "thinnest":
        return _thinnest_engine(_thinnest_handler(listing_rows=listing_rows))
    raise AssertionError(f"no engine in the roster is called {engine_id!r}")


@pytest.fixture(params=ENGINE_IDS)
def engine(request: pytest.FixtureRequest) -> VoiceEngine:
    return make_engine(request.param)


def saturated(engine: VoiceEngine) -> VoiceEngine:
    """Drive an adapter's `list_executions` to a FULL page — the truncation case.

    Every adapter reaches it differently and none of them may EXPOSE how (hard rule 2):
    the ThinnestAI stub answers with exactly a page's worth of rows and keeps a cursor, and
    the fake engine is given more calls than its page size. What the contract test asserts
    afterwards is identical for all of them — the caller is TOLD the answer may be short.

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
    assert isinstance(engine, ThinnestEngine), f"no saturation recipe for {type(engine).__name__}"
    return make_engine("thinnest", listing_rows=THINNEST_FULL_PAGE)


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
