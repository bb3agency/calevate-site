"""The ThinnestAI adapter's own decisions, against request and response shapes from the
hash-pinned mirror (`thinnest-findings/mirror/pages/api-reference/`). The conformance suite
holds it to the shared contract; these pin what is particular to this vendor: what is sent,
what is refused before anything is sent, and how their vocabulary maps onto ours."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine import build_engine, engine_catalogue
from apps.api.engine.capabilities import EngineCapabilityAbsentError
from apps.api.engine.thinnest import (
    BASE_URL,
    INSTRUCTIONS_MAX_CHARS,
    ThinnestEngine,
    vendor_agent_name,
)
from apps.api.engine.vendor_http import EngineRejectedError
from calevate_shared.engine import AgentConfig, CallContext, RecallOutcome
from calevate_shared.webhook_signature import (
    sha256_signature,
    sha256_signature_matches,
    timestamped_sha256_signature,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _engine(handler: Handler, **kwargs: Any) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": "Bearer ta_live_test"},
            transport=httpx.MockTransport(handler),
        ),
        **kwargs,
    )


#: The client's own customer workspace every new agent is created in (D-693).
WS = "org_client-test"


def _cfg(**update: Any) -> AgentConfig:
    base = AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic receptionist",
        direction="both",
        language_primary="te-IN",
        system_prompt="You are the receptionist.",
        opening_line="Idi AI assistant. Ee call record avutundi.",
        engine_workspace=WS,
    )
    return base.model_copy(update=update)


def tools_state(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """`GET`/`PATCH /agents/{id}/tools` as the vendor answers it (update-built-in-tools.md:
    705-790): the saved switches, `body`'s applied over every tool off and a chat hand-over."""
    switches = dict.fromkeys(
        (
            "capture_lead",
            "escalate_to_human",
            "schedule_callback",
            "call_them_now",
            "send_whatsapp",
            "send_sms",
            "reply_by_email",
        ),
        False,
    )
    hand_over: dict[str, Any] = {"mode": "chat", "phone": None, "line": None}
    if body:
        switches.update(body.get("tools", {}))
        hand_over.update(body.get("handOver", {}))
    return {
        "agent": "ag_1",
        "tools": [{"id": "search_knowledge", "enabled": True}]
        + [{"id": tool, "enabled": on} for tool, on in switches.items()],
        "webSearch": {"enabled": False, "switchable": False},
        "recall": "two_tier",
        "verifyByCode": False,
        "handOver": hand_over,
        "messages": [],
    }


def _recorder(responses: dict[tuple[str, str], httpx.Response]) -> tuple[Handler, list[Any]]:
    """Answers `responses`, a 404 for anything else, and the built-in tools route the way the
    vendor does unless a test names its own answer for it."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path.removeprefix("/api/v1")
        named = responses.get((request.method, path))
        if named is not None:
            return named
        if path.endswith("/tools") and request.method == "PATCH":
            return httpx.Response(200, json=tools_state(json.loads(request.content)))
        if path.endswith("/tools") and request.method == "GET":
            return httpx.Response(200, json=tools_state())
        return httpx.Response(404, json={"error": "x"})

    return handler, seen


def _agent_write(seen: list[httpx.Request]) -> httpx.Request:
    """The last agent write (`POST /agents` or `PATCH /agents/{id}`), not the tools PATCH."""
    return next(
        r
        for r in reversed(seen)
        if r.method in ("POST", "PATCH") and not r.url.path.endswith(("/tools", "/byok-voice"))
    )


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


# --- agents ------------------------------------------------------------------


async def test_create_sends_the_composed_prompt_and_the_call_settings() -> None:
    handler, seen = _recorder(
        {
            ("GET", "/agents"): httpx.Response(200, json={"items": [], "nextCursor": None}),
            ("POST", "/agents"): httpx.Response(201, json={"id": "ag_1"}),
        }
    )
    assert await _engine(handler).create_agent(_cfg()) == f"ag_1@{WS}"
    body = _body(_agent_write(seen))
    assert "Ee call record avutundi." in body["instructions"]
    assert body["greeting"] == "Idi AI assistant. Ee call record avutundi."
    # One language: fixed on the agent and on calls (snapshots/2026-10-08/pages/channels/
    # voice.md:225-239); `secondLanguage` is retired and not sent.
    assert body["language"] == "Telugu" and "secondLanguage" not in body
    assert body["voice"] == {
        "answersCalls": True,
        "unavailableMessage": None,
        "language": "Telugu",
        "recordCalls": True,
        "maxCallSeconds": 600,
        "detectMachines": False,
        "summariseCalls": False,
        "pastConversations": "fresh",
    }
    assert body["collectFields"] == [] and body["captureLeads"] is False
    # No per-agent switch stated (the workspace on its own keys): voice and model not sent.
    assert "model" not in body and "voice" not in body["voice"]
    # The built-in tools were pinned after the write and read back.
    assert seen[-1].method == "PATCH" and seen[-1].url.path.endswith("/agents/ag_1/tools")


async def test_a_documented_language_is_named() -> None:
    handler, seen = _recorder(
        {
            ("GET", "/agents"): httpx.Response(200, json={"items": [], "nextCursor": None}),
            ("POST", "/agents"): httpx.Response(201, json={"id": "ag_1"}),
        }
    )
    await _engine(handler).create_agent(
        _cfg(language_primary="hi-IN", languages_extra=["en-IN", "te-IN"])
    )
    body = _body(_agent_write(seen))
    # More than one language: "Match the customer", with calls following it.
    assert (body["language"], body["voice"]["language"]) == ("auto", None)


async def test_a_retried_create_adopts_the_agent_it_already_made() -> None:
    """`POST /agents` mints a new agent every time (agents.md:74-82); the name tag is what
    stops a retried publish leaving a second live agent."""
    cfg = _cfg()
    tagged = vendor_agent_name(cfg)
    handler, seen = _recorder(
        {
            ("GET", "/agents"): httpx.Response(
                200,
                json={"items": [{"id": "ag_old", "name": tagged}], "nextCursor": None},
            ),
            ("PATCH", "/agents/ag_old"): httpx.Response(200, json={"id": "ag_old"}),
        }
    )
    assert await _engine(handler).create_agent(cfg) == f"ag_old@{WS}"
    assert [r.method for r in seen] == ["GET", "PATCH", "PATCH"]
    assert len(tagged) <= 60 and tagged.startswith("Sunrise Clinic receptionist #cv-")


async def test_another_tenants_agent_of_the_same_name_is_not_adopted() -> None:
    other = vendor_agent_name(_cfg(tenant_id="0199a0b0-0000-7000-8000-0000000000ff"))
    handler, seen = _recorder(
        {
            ("GET", "/agents"): httpx.Response(
                200, json={"items": [{"id": "ag_theirs", "name": other}], "nextCursor": None}
            ),
            ("POST", "/agents"): httpx.Response(201, json={"id": "ag_new"}),
        }
    )
    assert await _engine(handler).create_agent(_cfg()) == f"ag_new@{WS}"
    assert [r.method for r in seen] == ["GET", "POST", "PATCH"]


@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"system_prompt": "x" * INSTRUCTIONS_MAX_CHARS}, "engine_prompt_too_long"),
        ({"opening_line": "y" * 201}, "engine_greeting_too_long"),
        ({"max_call_duration_s": 1800}, "engine_call_cap_out_of_range"),
    ],
)
async def test_what_the_engine_cannot_hold_is_refused_before_any_request(
    update: dict[str, Any], code: str
) -> None:
    """Never truncated: the truthful-answer rule sits at the tail of the prompt."""
    handler, seen = _recorder({})
    with pytest.raises(ProblemError) as raised:
        await _engine(handler).create_agent(_cfg(**update))
    assert raised.value.code == code
    assert raised.value.remediation
    assert seen == []


async def test_the_read_back_carries_the_prompt_greeting_and_documents() -> None:
    cfg = _cfg()
    handler, _ = _recorder(
        {
            ("GET", "/agents/ag_1"): httpx.Response(
                200,
                json={
                    "id": "ag_1",
                    "name": vendor_agent_name(cfg),
                    "instructions": "held prompt",
                    "greeting": None,
                },
            ),
            ("GET", "/agents/ag_1/knowledge"): httpx.Response(
                200, json={"items": [{"id": "doc_1"}], "nextCursor": None}
            ),
        }
    )
    snapshot = await _engine(handler).get_agent("ag_1")
    assert snapshot.name == cfg.name
    assert snapshot.system_prompt == "held prompt" and snapshot.system_prompt_readable
    assert snapshot.greeting == "" and snapshot.greeting_readable
    assert snapshot.references_kb("doc_1") is True
    assert snapshot.holds_speech("tts") is None


async def test_a_read_back_describing_another_agent_is_refused() -> None:
    handler, _ = _recorder(
        {("GET", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_2", "instructions": ""})}
    )
    with pytest.raises(ProblemError) as raised:
        await _engine(handler).get_agent("ag_1")
    assert raised.value.code == "engine_bad_response"


# --- dialling ----------------------------------------------------------------


def _agent_with_greeting(greeting: str | None) -> httpx.Response:
    return httpx.Response(200, json={"id": "ag_1", "greeting": greeting})


async def test_a_dial_speaks_the_held_greeting_and_leaves_retries_and_hours_to_us() -> None:
    handler, seen = _recorder(
        {
            ("GET", "/agents/ag_1"): _agent_with_greeting("Idi AI assistant."),
            ("POST", "/calls"): httpx.Response(202, json={"id": "out_1", "status": "ringing"}),
        }
    )
    ctx = CallContext(
        call_id="0199a0b0-0000-7000-8000-00000000ca11",
        lead_id="lead-9",
        lead_name="Asha",
        from_e164="+918045678901",
    )
    assert await _engine(handler).start_outbound_call("ag_1", "+919876543210", ctx) == "out_1"
    dial = seen[-1]
    body = _body(dial)
    assert body["purpose"] == "Idi AI assistant."
    assert body["agent"] == "ag_1" and body["from"] == "+918045678901"
    assert body["ifOutsideHours"] == "refuse"
    assert body["reference"] == ctx.call_id
    assert body["variables"] == {"lead_name": "Asha"}
    assert "retry" not in body and "callingHours" not in body and "extract" not in body
    assert dial.headers["Idempotency-Key"] == f"calevate-call-{ctx.call_id}"


@pytest.mark.parametrize("greeting", [None, "", "   "])
async def test_an_agent_with_no_opening_line_is_not_dialled(greeting: str | None) -> None:
    handler, seen = _recorder({("GET", "/agents/ag_1"): _agent_with_greeting(greeting)})
    with pytest.raises(ProblemError) as raised:
        await _engine(handler).start_outbound_call("ag_1", "+919876543210", CallContext())
    assert raised.value.code == "carrier_dial_precondition_failed"
    assert [r.method for r in seen] == ["GET"]


async def test_a_failed_greeting_read_is_reported_as_not_placed() -> None:
    handler, _ = _recorder({})
    with pytest.raises(ProblemError) as raised:
        await _engine(handler).start_outbound_call("ag_1", "+919876543210", CallContext())
    assert raised.value.code == "carrier_dial_precondition_failed"


@pytest.mark.parametrize("status", [402, 409])
async def test_a_refused_dial_is_known_not_to_have_rung(status: int) -> None:
    """402 is a balance the workspace cannot spend and every 409 on `POST /calls` is a call
    that was not placed (snapshots/2026-10-07/pages/api-reference/calls/place-call.md:
    379-453). A 403 is decided by `thinnest_call_lifecycle_test`."""
    handler, _ = _recorder(
        {
            ("GET", "/agents/ag_1"): _agent_with_greeting("Idi AI assistant."),
            ("POST", "/calls"): httpx.Response(status, json={"error": "refused"}),
        }
    )
    with pytest.raises(EngineRejectedError) as raised:
        await _engine(handler).start_outbound_call("ag_1", "+919876543210", CallContext())
    assert raised.value.request_refused


@pytest.mark.parametrize(
    ("status", "report", "outcome"),
    [
        (200, {"status": "cancelled"}, RecallOutcome.PREVENTED),
        (202, {"status": "connected"}, RecallOutcome.ALREADY_RUNNING),
        (202, {"status": "ringing"}, RecallOutcome.ALREADY_RUNNING),
        (200, {}, RecallOutcome.UNKNOWN),
    ],
)
async def test_a_stop_reports_what_it_caught(
    status: int, report: dict[str, Any], outcome: RecallOutcome
) -> None:
    handler, _ = _recorder({("DELETE", "/calls/out_1"): httpx.Response(status, json=report)})
    assert await _engine(handler).end_call("out_1") == outcome


async def test_a_stop_of_a_call_that_already_ended_says_it_ran() -> None:
    handler, _ = _recorder(
        {
            ("DELETE", "/calls/out_1"): httpx.Response(409, json={"error": "ended"}),
            ("GET", "/calls/out_1"): httpx.Response(
                200, json={"id": "out_1", "status": "completed", "agent": {"id": "ag_1"}}
            ),
        }
    )
    assert await _engine(handler).end_call("out_1") == RecallOutcome.ALREADY_RUNNING


async def test_a_connected_call_is_never_reported_as_stopped_nor_hung_up() -> None:
    handler, seen = _recorder(
        {
            ("DELETE", "/calls/out_1"): httpx.Response(409, json={"error": "brought number"}),
            ("GET", "/calls/out_1"): httpx.Response(
                200, json={"id": "out_1", "status": "connected"}
            ),
        }
    )
    assert await _engine(handler).end_call("out_1") == RecallOutcome.ALREADY_RUNNING
    assert [r.method for r in seen] == ["GET"]


# --- reading calls -----------------------------------------------------------


def _call(**update: Any) -> dict[str, Any]:
    return {
        "id": "out_1",
        "status": "completed",
        "direction": "outbound",
        "phone": "919876543210",
        "from": "918045678901",
        "agent": {"id": "ag_1", "name": "x"},
        "startedAt": "2026-09-18T04:30:02Z",
        "endedAt": "2026-09-18T04:33:11Z",
        "seconds": 182,
        "hangup": "answered",
        "transcript": [
            {"speaker": "agent", "text": "Hello", "at": "2026-09-18T04:30:10Z"},
            {"speaker": "team", "text": "Joining", "at": "2026-09-18T04:30:12Z"},
            {"speaker": "customer", "text": "Yes", "at": "2026-09-18T04:30:14Z"},
        ],
        "recording": {"url": "https://rec/1", "ready": True},
        "analysedAt": "2026-09-18T04:33:20Z",
        "fields": {},
    } | update


async def test_a_fetched_call_is_mapped_into_our_vocabulary() -> None:
    handler, _ = _recorder({("GET", "/calls/out_1"): httpx.Response(200, json=_call())})
    snapshot = await _engine(handler).get_execution("out_1")
    assert (snapshot.status, snapshot.terminal, snapshot.billable_ready) == (
        "completed",
        True,
        True,
    )
    assert (snapshot.from_e164, snapshot.to_e164) == ("+918045678901", "+919876543210")
    assert snapshot.duration_s == 182 and snapshot.recording_url == "https://rec/1"
    assert [t.speaker for t in snapshot.transcript] == ["agent", "caller"]
    assert snapshot.transcript_lines_unparsed == 1, "a teammate's words are filed under neither"
    assert snapshot.cost is None and snapshot.raw_document


@pytest.mark.parametrize(
    ("hangup", "status"), [("busy", "busy"), ("voicemail", "voicemail"), ("no_answer", "no_answer")]
)
def test_a_missed_call_is_refined_by_its_hangup(hangup: str, status: str) -> None:
    engine = _engine(_recorder({})[0])
    assert engine._snapshot(_call(status="missed", hangup=hangup), workspace=None).status == status


def test_an_inbound_call_swaps_the_numbers() -> None:
    snapshot = _engine(_recorder({})[0])._snapshot(_call(direction="inbound"), workspace=None)
    assert (snapshot.from_e164, snapshot.to_e164) == ("+919876543210", "+918045678901")


def test_a_call_is_not_billable_until_its_results_are_final() -> None:
    snapshot = _engine(_recorder({})[0])._snapshot(_call(analysedAt=None), workspace=None)
    assert snapshot.terminal and not snapshot.billable_ready


def test_an_inbound_delivery_with_audio_still_arriving_is_settled_with_its_link() -> None:
    """The `call.analysed` delivery is an inbound call's only transcript, so a recording
    marked `ready: false` must not hold the call back; the link is passed on for the copy
    to retry (get-call.md:170-174)."""
    engine = _engine(_recorder({})[0])
    pending = {"url": "https://rec/1", "ready": False}
    delivery = {"event": "call.analysed", "data": _call(direction="inbound", recording=pending)}
    snapshot = engine.snapshot_from_delivery(delivery)
    assert snapshot.billable_ready and snapshot.transcript
    assert snapshot.recording_url == "https://rec/1"
    assert engine.parse_webhook(delivery).recording_url == "https://rec/1"


async def test_the_call_list_keeps_the_newest_try_and_follows_the_cursor() -> None:
    pages = {
        None: {"items": [_call(attempt=2), _call(attempt=1)], "nextCursor": "c2"},
        "c2": {"items": [_call(id="out_2")], "nextCursor": None},
    }
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[request.url.params.get("cursor")])

    from datetime import UTC, datetime

    listing = await _engine(handler).list_executions(since=datetime(2026, 9, 18, tzinfo=UTC))
    assert listing.complete and listing.pages_fetched == 2
    assert [s.engine_call_id for s in listing.snapshots] == ["out_1", "out_2"]
    assert seen[0].url.params["since"] == "2026-09-18T00:00:00Z"


async def test_a_cursor_that_repeats_is_reported_rather_than_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_call()], "nextCursor": "same"})

    from datetime import UTC, datetime

    listing = await _engine(handler).list_executions(since=datetime(2026, 9, 18, tzinfo=UTC))
    assert not listing.complete and listing.incomplete_reason == "next_link_no_progress"


def test_a_verified_delivery_becomes_a_full_snapshot() -> None:
    engine = _engine(_recorder({})[0])
    snapshot = engine.snapshot_from_delivery({"event": "call.analysed", "data": _call(id="inb_1")})
    assert snapshot.engine_call_id == "inb_1" and snapshot.transcript


# --- webhooks ----------------------------------------------------------------


def _delivery(agent: str = "ag_1") -> bytes:
    return json.dumps(
        {"event": "call.analysed", "data": _call() | {"agent": {"id": agent}}}
    ).encode()


def _v2(body: bytes, secret: str, *, minutes_ago: float = 0) -> dict[str, str]:
    """`x-thinnest-signature-v2` over `<delivered-at>.<body>` (snapshots/2026-10-08/pages/
    api-reference/webhooks.md:100-108)."""
    from datetime import UTC, datetime, timedelta

    at = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "X-Thinnest-Signature-V2": timestamped_sha256_signature(body, secret, signed_at=at),
        "X-Thinnest-Delivered-At": at,
    }


def test_a_delivery_signed_with_the_agents_secret_is_accepted() -> None:
    body = _delivery()
    engine = _engine(_recorder({})[0], signing_secret_for={"ag_1": "s3cr3t"}.get)
    assert engine.verify_webhook(_v2(body, "s3cr3t"), body, "203.0.113.9").ok


def test_a_delivery_without_a_signed_time_is_refused() -> None:
    """v1 alone signs no time, so it is not accepted; nor is a delivery with no signature."""
    body = _delivery()
    engine = _engine(_recorder({})[0], signing_secret_for={"ag_1": "s3cr3t"}.get)
    for headers in ({"x-thinnest-signature": sha256_signature(body, "s3cr3t")}, {}):
        verdict = engine.verify_webhook(headers, body, "203.0.113.9")
        assert (verdict.ok, verdict.reason) == (False, "signature_missing")


def test_a_stale_delivery_time_is_refused() -> None:
    body = _delivery()
    engine = _engine(_recorder({})[0], signing_secret_for={"ag_1": "s3cr3t"}.get)
    verdict = engine.verify_webhook(_v2(body, "s3cr3t", minutes_ago=6), body, "203.0.113.9")
    assert (verdict.ok, verdict.reason) == (False, "delivery_stale")


@pytest.mark.parametrize(
    ("secret", "signed_with", "reason"),
    [
        ({"ag_1": "s3cr3t"}, "another", "signature_mismatch"),
        ({}, "s3cr3t", "signing_secret_unavailable"),
    ],
)
def test_a_delivery_that_cannot_be_proved_is_refused(
    secret: dict[str, str], signed_with: str, reason: str
) -> None:
    body = _delivery()
    engine = _engine(_recorder({})[0], signing_secret_for=secret.get)
    verdict = engine.verify_webhook(_v2(body, signed_with), body, "203.0.113.9")
    assert (verdict.ok, verdict.method, verdict.reason) == (False, "hmac", reason)


def test_a_signature_over_reserialised_json_does_not_match() -> None:
    body = _delivery()
    header = sha256_signature(json.dumps(json.loads(body), indent=2).encode(), "s3cr3t")
    assert not sha256_signature_matches(body, header, "s3cr3t")


def test_the_delivery_envelope_is_parsed_into_our_event() -> None:
    event = _engine(_recorder({})[0]).parse_webhook(
        {"event": "call.completed", "data": _call(direction="inbound", status="missed")}
    )
    assert (event.call_id, event.engine_agent_ref, event.direction) == ("out_1", "ag_1", "inbound")
    assert event.status == "no_answer" and event.engine == "thinnest"
    assert event.tenant_id is None


# --- the rest of the surface -------------------------------------------------


async def test_the_byok_slot_refuses_on_the_llm_capability() -> None:
    with pytest.raises(EngineCapabilityAbsentError) as raised:
        await _engine(_recorder({})[0]).set_llm_credential("k", provider="openai")
    assert raised.value.capability == "llm"


async def test_numbers_are_listed_and_never_bought() -> None:
    handler, _ = _recorder(
        {
            ("GET", "/phone-numbers"): httpx.Response(
                200,
                json={
                    "items": [
                        {"number": "918012345678", "source": "rented", "provider": "ThinnestAI"},
                        {"number": "918012345679", "source": "brought", "provider": "vobiz"},
                    ],
                    "nextCursor": None,
                },
            )
        }
    )
    numbers = await _engine(handler).list_engine_numbers()
    assert [(n.e164, n.engine_number_ref, n.engine_owned) for n in numbers] == [
        ("+918012345678", "918012345678", True),
        ("+918012345679", "918012345679", False),
    ]


async def test_failed_knowledge_indexing_is_not_reported_as_attached() -> None:
    from calevate_shared.engine import KBSourceRef

    handler, _ = _recorder(
        {
            ("POST", "/agents/ag_1/knowledge"): httpx.Response(
                201, json={"id": "doc_1", "status": "failed", "error": "x"}
            )
        }
    )
    with pytest.raises(ProblemError) as raised:
        await _engine(handler).attach_kb("ag_1", KBSourceRef(kb_id="k", title="t", text="x"))
    assert raised.value.code == "engine_kb_ingest_failed"


async def test_the_engine_catalogue_reads_the_models() -> None:
    """Models only since D-687: the voices a client may pick are the operator's curated
    list (`agents/hosted_voices.py`), never the live vendor catalogue."""
    handler, _ = _recorder(
        {
            ("GET", "/models"): httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "prana-voice",
                            "name": "Prana",
                            "voice": True,
                            "available": True,
                            "voiceOnlyByok": True,
                        },
                        {"id": "gpt-4.1", "name": "GPT-4.1", "voice": False, "available": False},
                    ]
                },
            ),
        }
    )
    catalogue = await engine_catalogue(_engine(handler))
    assert catalogue.complete
    assert [
        (m.model_id, m.call_capable, m.plan_allows, m.voice_only_byok) for m in catalogue.models
    ] == [
        ("prana-voice", True, True, True),
        ("gpt-4.1", False, False, False),
    ]


async def test_an_engine_without_a_catalogue_refuses_by_name() -> None:
    with pytest.raises(EngineCapabilityAbsentError) as raised:
        await engine_catalogue(build_engine(get_settings().model_copy(update={"engine": "fake"})))
    assert raised.value.capability == "tts"


def test_the_factory_builds_it_from_settings_and_names_its_key() -> None:
    engine = build_engine(
        get_settings().model_copy(update={"engine": "thinnest", "thinnest_api_key": None})
    )
    assert isinstance(engine, ThinnestEngine)
    assert not engine.holds_credentials()
    assert engine.credential_env_keys == ("THINNEST_API_KEY",)
