"""The ThinnestAI adapter brought in step with the 8 Oct 2026 docs (D-690).

Every vendor shape here is from the hash-pinned snapshot
`thinnest-findings/mirror/snapshots/2026-10-08/pages/` (VERIFIED-VENDOR-DOCS): the error
envelope (`api-reference/errors.md:9-177`), the built-in tools (`api-reference/tools/
update-built-in-tools.md:553-637`), the agent's voice object (`api-reference/agents/
update-agent.md:940-1016`), live transfer (`channels/voice.md:483-492`), a call's
`costMicro` (`api-reference/calls/get-call.md:498-523`) and the webhook events
(`api-reference/webhooks.md:70-99`).
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS, ReconcilesAgentSettings
from apps.api.agents.service import CREDIT_STOP_MESSAGE
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest, vendor_http
from apps.api.engine.thinnest import (
    PAUSED_LINE_MESSAGE,
    ThinnestEngine,
    language_fields,
)
from apps.api.engine.vendor_http import (
    LINES_BUSY_CODE,
    NUMBER_DAILY_LIMIT_CODE,
    RECIPIENT_OPTED_OUT_CODE,
    EngineRateLimitedError,
    EngineRejectedError,
)
from apps.workers import engine_charges
from calevate_shared.engine import CallContext, HandoffSpec
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant
from tests.thinnest_engine_test import _agent_write, _cfg, _engine, _recorder, tools_state

_DIAL_TO = "+919876543210"


def _greeting() -> httpx.Response:
    return httpx.Response(200, json={"id": "ag_1", "greeting": "Idi AI assistant."})


def _handoff() -> HandoffSpec:
    return HandoffSpec(
        destination_e164="+919811122233",
        trigger="The caller asks for a person.",
        spoken_line="Connecting you to our front desk now.",
    )


async def _dial(status: int, envelope: dict[str, Any], **headers: str) -> BaseException:
    handler, _ = _recorder(
        {
            ("GET", "/agents/ag_1"): _greeting(),
            ("POST", "/calls"): httpx.Response(status, json=envelope, headers=headers),
        }
    )
    with pytest.raises(ProblemError) as raised:
        await _engine(handler).start_outbound_call("ag_1", _DIAL_TO, CallContext())
    return raised.value


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        thinnest, "alert", lambda _s, code, **kw: raised.append((code, kw.get("detail", "")))
    )
    return raised


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_s: float) -> None:
        return None

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _instant)


# --- (12) the error envelope ---------------------------------------------------------


async def test_the_envelope_code_and_reason_reach_the_refusal(
    alarms: list[tuple[str, str]],
) -> None:
    refused = await _dial(
        402,
        {"error": "Top up.", "code": "insufficient_balance", "reason": "trial spent"},
    )
    assert isinstance(refused, EngineRejectedError)
    assert (refused.vendor_code, refused.vendor_reason) == ("insufficient_balance", "trial spent")
    assert refused.request_refused
    assert alarms[0][0] == "engine_balance_exhausted" and "(trial spent)" in alarms[0][1]


async def test_an_undocumented_reason_and_a_malformed_code_are_dropped() -> None:
    refused = await _dial(402, {"error": "x", "code": "Not A Code", "reason": "+919876543210"})
    assert isinstance(refused, EngineRejectedError)
    assert refused.vendor_code is None and refused.vendor_reason is None


async def test_a_setup_refusal_alarms_and_is_known_not_to_have_rung(
    alarms: list[tuple[str, str]],
) -> None:
    refused = await _dial(409, {"error": "x", "code": "calling_not_set_up"})
    assert isinstance(refused, EngineRejectedError) and refused.request_refused
    assert [code for code, _ in alarms] == ["engine_dial_setup_refused"]


async def test_a_carrier_503_with_its_code_is_a_refusal_not_a_maybe(
    alarms: list[tuple[str, str]],
) -> None:
    """A 5xx is "the phone may be ringing" unless the vendor's code says it was not placed
    (errors.md:122)."""
    refused = await _dial(503, {"error": "x", "code": "carrier_unavailable"})
    assert isinstance(refused, EngineRejectedError)
    assert refused.vendor_status == 503 and refused.request_refused
    assert alarms == []  # 503 is worth retrying; only the 502 names our number.
    bare = await _dial(503, {"error": "x"})
    assert isinstance(bare, EngineRejectedError) and not bare.request_refused


async def test_the_idempotency_conflict_is_not_called_not_placed() -> None:
    refused = await _dial(409, {"error": "x", "code": "idempotency_in_progress"})
    # 409 is in the dial's own refused set; the code adds nothing either way.
    assert isinstance(refused, EngineRejectedError) and refused.vendor_code == (
        "idempotency_in_progress"
    )


async def test_concurrent_calls_is_lines_busy_without_a_retry() -> None:
    refused = await _dial(
        429,
        {"error": "x", "code": "concurrent_calls", "limit": {"name": "concurrent_calls", "max": 5}},
        **{"Retry-After": "1"},
    )
    assert refused.code == LINES_BUSY_CODE


async def test_a_numbers_daily_limit_is_its_own_refusal_and_rings_nobody() -> None:
    from apps.api.agents.service import dial_was_not_placed

    refused = await _dial(
        429,
        {"error": "x", "code": "number_daily_limit", "limit": {"name": "number_daily", "max": 200}},
    )
    assert refused.code == NUMBER_DAILY_LIMIT_CODE
    assert dial_was_not_placed(refused) is True


async def test_a_per_minute_limit_is_retried_on_retry_after_then_reported(
    no_sleep: None, caplog: pytest.LogCaptureFixture
) -> None:
    refused = await _dial(
        429,
        {
            "error": "Over 60 calls a minute.",
            "code": "rate_limit_calls",
            "limit": {"name": "calls", "perMinute": 60},
        },
        **{"Retry-After": "2"},
    )
    assert isinstance(refused, EngineRateLimitedError) and refused.retry_after_s == 2.0
    exhausted = [r for r in caplog.records if r.getMessage() == "engine_throttle_exhausted"]
    assert exhausted and exhausted[0].limit == "calls" and exhausted[0].limit_per_minute == 60


async def test_the_sentence_is_logged_from_error_and_never_carried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _dial(409, {"error": "Outside hours for +919876543210", "code": "outside_calling_hours"})
    logged = next(r for r in caplog.records if r.getMessage() == "engine_error")
    assert logged.vendor_code == "outside_calling_hours"
    assert "Outside hours for" in str(logged.vendor_message)
    assert "9876543210" not in str(logged.vendor_message)


def test_the_key_probe_is_gone() -> None:
    assert not hasattr(ThinnestEngine, "_key_places_calls_probe")


# --- (2), (17) built-in tools and live transfer ------------------------------------------


def test_every_switchable_tool_is_stated_off_without_a_handover() -> None:
    body = ThinnestEngine.built_in_tools_body(_cfg())
    assert body["tools"] == {
        "call_them_now": False,
        "send_sms": False,
        "send_whatsapp": False,
        "reply_by_email": False,
        "capture_lead": False,
        "schedule_callback": False,
        "escalate_to_human": False,
    }
    assert body["handOver"] == {"mode": "chat", "phone": None, "line": None}


def test_an_on_duty_destination_is_a_live_transfer() -> None:
    cfg = _cfg(handoff=_handoff())
    body = ThinnestEngine.built_in_tools_body(cfg)
    assert body["tools"]["escalate_to_human"] is True
    assert body["handOver"] == {
        "mode": "call",
        "phone": "+919811122233",
        "line": "Connecting you to our front desk now.",
    }
    agent = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    assert agent["escalation"] == {"onNoAnswer": False, "onRequest": True}
    assert ThinnestEngine.capabilities.in_call_handoff is True


async def test_a_handover_line_too_long_is_refused_before_any_write() -> None:
    handler, seen = _recorder({})
    long_line = _handoff().model_copy(update={"spoken_line": "x" * 301})
    with pytest.raises(ProblemError) as raised:
        await _engine(handler).create_agent(_cfg(handoff=long_line, engine_workspace="org_c"))
    assert raised.value.code == "engine_handover_line_too_long" and seen == []


async def test_a_partial_apply_of_the_tools_refuses_the_publish() -> None:
    """Changes apply in order and stop at the first refusal, keeping what came before."""
    refused, _ = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1"}),
            ("PATCH", "/agents/ag_1/tools"): httpx.Response(
                400, json={"error": "Add the number.", "code": "validation_failed"}
            ),
        }
    )
    with pytest.raises(ProblemError) as raised:
        await _engine(refused).update_agent("ag_1", _cfg())
    assert raised.value.code == "engine_tools_not_pinned"
    kept_on = tools_state({"tools": {"call_them_now": True}})
    half, _ = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1"}),
            ("PATCH", "/agents/ag_1/tools"): httpx.Response(200, json=kept_on),
        }
    )
    with pytest.raises(ProblemError) as raised:
        await _engine(half).update_agent("ag_1", _cfg())
    assert raised.value.code == "engine_tools_not_pinned"


async def test_the_read_back_names_the_live_transfer_destination() -> None:
    held = tools_state(
        {
            "tools": {"escalate_to_human": True},
            "handOver": {"mode": "call", "phone": "+919811122233", "line": "x"},
        }
    )
    handler, _ = _recorder(
        {
            ("GET", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1", "instructions": ""}),
            ("GET", "/agents/ag_1/knowledge"): httpx.Response(
                200, json={"items": [], "nextCursor": None}
            ),
            ("GET", "/agents/ag_1/tools"): httpx.Response(200, json=held),
        }
    )
    snapshot = await _engine(handler).get_agent("ag_1")
    assert snapshot.handoff_destinations == ("+919811122233",)
    assert snapshot.handoff_destinations_readable
    chat, _ = _recorder(
        {
            ("GET", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1", "instructions": ""}),
            ("GET", "/agents/ag_1/knowledge"): httpx.Response(
                200, json={"items": [], "nextCursor": None}
            ),
            ("GET", "/agents/ag_1/tools"): httpx.Response(200, json={"tools": "?"}),
        }
    )
    unread = await _engine(chat).get_agent("ag_1")
    assert unread.handoff_destinations == () and not unread.handoff_destinations_readable


def test_the_handover_screen_states_where_transfer_works() -> None:
    from apps.api.agents.transfer_providers import transfer_platform_note

    note = transfer_platform_note(ThinnestEngine(api_key=None))
    assert note and "rented through Calevate" in note
    assert "Plivo" not in note and "Thinnest" not in note


# --- (13) language, (14) the pause, (16) null resets, caller memory --------------------------


@pytest.mark.parametrize(
    ("primary", "extra", "expected"),
    [
        ("te-IN", [], ("Telugu", "Telugu")),
        ("te-IN", ["en-IN"], ("auto", None)),
        ("te-IN", ["te"], ("Telugu", "Telugu")),
        ("kn-IN", [], ("Kannada", "Kannada")),
        ("xx-YY", [], ("auto", None)),
    ],
)
def test_one_language_is_fixed_and_two_follow_the_caller(
    primary: str, extra: list[str], expected: tuple[str, str | None]
) -> None:
    assert language_fields(_cfg(language_primary=primary, languages_extra=extra)) == expected


def test_the_paused_line_speaks_the_credit_stop_sentence() -> None:
    assert PAUSED_LINE_MESSAGE == CREDIT_STOP_MESSAGE


def test_caller_memory_is_recap_never_quiet() -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    on = engine._agent_body(_cfg(caller_memory_enabled=True))
    off = engine._agent_body(_cfg())
    assert on["voice"]["pastConversations"] == "recap"
    assert off["voice"]["pastConversations"] == "fresh"


async def test_a_cleared_voice_and_model_are_sent_as_null() -> None:
    handler, seen = _recorder({("PATCH", "/agents/ag_1"): httpx.Response(200, json={})})
    await _engine(handler).update_agent("ag_1", _cfg(engine_own_voice_key=False))
    body = json.loads(_agent_write(seen).content)
    assert body["model"] is None and body["voice"]["voice"] is None
    assert body["byok"] == "off"
    chosen = ThinnestEngine(api_key="x")._agent_body(
        _cfg(engine_own_voice_key=False, engine_voice_id="priya", engine_model_id="gpt-4.1")
    )
    assert (chosen["voice"]["voice"], chosen["model"]) == ("priya", "gpt-4.1")


def test_the_reset_refusal_is_retired() -> None:
    from apps.api.agents import lifecycle

    assert not hasattr(lifecycle, "ENGINE_CHOICE_RESET_UNSUPPORTED")


def test_our_distillation_does_not_run_on_this_engine() -> None:
    from apps.workers.caller_memory_distil import ENGINES_THAT_REMEMBER

    assert "thinnest" in ENGINES_THAT_REMEMBER and "pipecat" not in ENGINES_THAT_REMEMBER


async def test_the_distillation_tick_stops_on_an_engine_that_remembers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.settings import get_settings
    from apps.workers import caller_memory_distil

    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    assert await caller_memory_distil.distil_caller_memories({}) == "engine_remembers"


# --- (11) settings read back and repaired --------------------------------------------------


def _held_agent(body: dict[str, Any], **changes: Any) -> dict[str, Any]:
    held = json.loads(json.dumps(body))
    for key, value in changes.items():
        if key.startswith("voice__"):
            held["voice"][key.removeprefix("voice__")] = value
        else:
            held[key] = value
    return held


async def test_settings_in_step_report_nothing() -> None:
    engine = ThinnestEngine(api_key="x")
    cfg = _cfg(engine_own_voice_key=False, engine_voice_id="priya")
    held = _held_agent(engine._agent_body(cfg), voice__language="te-IN")
    handler, _ = _recorder({("GET", "/agents/ag_1"): httpx.Response(200, json=held)})
    assert await _engine(handler).settings_drift("ag_1", cfg) == []
    assert isinstance(_engine(handler), ReconcilesAgentSettings)


async def test_drifted_settings_are_named_and_only_they_are_rewritten() -> None:
    engine = ThinnestEngine(api_key="x")
    cfg = _cfg(engine_own_voice_key=False, engine_voice_id="priya")
    held = _held_agent(
        engine._agent_body(cfg),
        voice__recordCalls=False,
        voice__pastConversations="quiet",
        voice__voice="kavya",
        scheduleCallbacks=True,
        escalation={"onNoAnswer": True, "onRequest": False},
        collectFields=[{"name": "budget"}],
        voice__answersCalls=False,
    )
    tools = tools_state({"tools": {"call_them_now": True}})
    handler, seen = _recorder(
        {
            ("GET", "/agents/ag_1"): httpx.Response(200, json=held),
            ("PATCH", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1"}),
            ("GET", "/agents/ag_1/tools"): httpx.Response(200, json=tools),
        }
    )
    adapter = _engine(handler)
    drifted = await adapter.settings_drift("ag_1", cfg)
    assert set(drifted) == {
        "record_calls",
        "caller_memory",
        "voice",
        "scheduled_callbacks",
        "escalation",
        "collected_fields",
        "built_in_tools",
    }
    assert set(drifted) <= AGENT_SETTING_LABELS
    await adapter.repair_settings("ag_1", cfg, drifted)
    patch = json.loads(_agent_write(seen).content)
    # The script, the greeting and the line state (a pause) are never part of a repair.
    assert not {"instructions", "greeting", "name"} & set(patch)
    assert "answersCalls" not in patch["voice"]
    assert patch["voice"] == {"recordCalls": True, "pastConversations": "fresh", "voice": "priya"}
    assert patch["scheduleCallbacks"] is False and patch["collectFields"] == []
    assert seen[-1].url.path.endswith("/agents/ag_1/tools")


async def test_a_default_voice_and_model_are_not_reported_as_drift() -> None:
    engine = ThinnestEngine(api_key="x")
    cfg = _cfg(engine_own_voice_key=False)
    held = _held_agent(engine._agent_body(cfg), voice__voice="kavya", model="prana-voice")
    handler, _ = _recorder({("GET", "/agents/ag_1"): httpx.Response(200, json=held)})
    assert await _engine(handler).settings_drift("ag_1", cfg) == []


async def test_the_sweep_repairs_and_alarms_naming_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from apps.api.agents.engine_settings import SettingsCheck
    from apps.api.agents.reconciliation import DriftCandidate
    from apps.workers import engine_reconciliation as sweep

    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        sweep, "alert", lambda _s, code, **kw: raised.append((code, kw.get("detail", "")))
    )
    candidate = DriftCandidate(
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        engine_agent_ref="ag_x",
        drift_checked_at=None,
    )
    for check, code in (
        (SettingsCheck(drifted=("record_calls", "built_in_tools"), repaired=True), "repaired"),
        (SettingsCheck(drifted=("hand_over",), repaired=False), "drifted"),
        (SettingsCheck(drifted=(), repaired=False), None),
        (None, None),
    ):
        raised.clear()

        async def _check(_c: Any = check, **_kw: Any) -> Any:
            return _c

        monkeypatch.setattr(sweep, "check_agent_settings", _check)
        await sweep._reconcile_settings("thinnest", candidate)
        if code is None:
            assert raised == []
        else:
            assert raised[0][0] == f"engine_agent_settings_{code}"
            assert all(name in raised[0][1] for name in check.drifted)  # type: ignore[union-attr]


async def test_the_settings_check_is_skipped_on_an_engine_without_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.agents import engine_settings

    monkeypatch.setattr(engine_settings, "get_engine", lambda: object())
    assert (
        await engine_settings.check_agent_settings(
            tenant_id=uuid.uuid4(), agent_id=uuid.uuid4(), engine_agent_ref="ag_x"
        )
        is None
    )


# --- (9) the charge per call ------------------------------------------------------------


def test_cost_micro_is_rupees_without_a_float() -> None:
    engine = ThinnestEngine(api_key="x")
    snap = engine.snapshot_from_delivery(
        {"data": {"id": "out_1", "status": "completed", "costMicro": 6370001, "currency": "INR"}}
    )
    assert snap.engine_charged_inr == Decimal("6.370001")
    for call in (
        {"costMicro": None, "currency": "INR"},
        {"costMicro": 100, "currency": "USD"},
        {"costMicro": True, "currency": "INR"},
        {"costMicro": -5, "currency": "INR"},
    ):
        held = engine.snapshot_from_delivery({"data": {"id": "out_2", **call}})
        assert held.engine_charged_inr is None


@pytest.mark.parametrize(("band", "fee"), [("studio", "0.09"), ("premium", "0.10")])
def test_the_top_up_fee_follows_the_plan_the_band_needs(band: str, fee: str) -> None:
    assert engine_charges.thinnest_topup_fee(band) == Decimal(fee)
    assert engine_charges.cost_with_fee(Decimal("3.00"), fee=Decimal(fee)) == (
        Decimal("3.00") * (1 + Decimal(fee))
    ).quantize(Decimal("0.0001"))


def test_the_variance_is_named_in_rupees_and_percent() -> None:
    sentence = engine_charges.variance_sentence(Decimal("3.0000"), Decimal("3.3000"))
    assert "-INR 0.3000" in sentence and "(-9.1%)" in sentence


async def _call_with_usage(
    *, rate_key: str, minute_cost: Decimal | None, tts: bool
) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _seed_tenant(f"sync_{uuid.uuid4().hex[:10]}")
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                "'completed', now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"out_{call_id}"},
        )
        rows: list[tuple[str, Decimal, Decimal | None]] = [
            ("platform_min", Decimal(1), minute_cost)
        ]
        if tts:
            rows.append(("tts_kchars", Decimal("0.5"), Decimal("4.0000")))
        for unit, qty, cost in rows:
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, :u, "
                    ":q, :p, now(), CAST(:m AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "u": unit,
                    "q": qty,
                    "p": cost,
                    "m": json.dumps({"engine_rate_key": rate_key}),
                },
            )
    return tenant_id, call_id


@pytest.fixture
def charge_alarms(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "thinnest_clear_voice_band", "studio")
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        engine_charges, "alert", lambda _s, code, **kw: raised.append((code, kw.get("detail", "")))
    )
    return raised


@pytest.mark.rls
async def test_a_charge_is_kept_once_and_matched_with_its_fee(
    charge_alarms: list[tuple[str, str]],
) -> None:
    tenant_id, call_id = await _call_with_usage(
        rate_key="studio", minute_cost=Decimal("3.2700"), tts=False
    )
    outcome = await engine_charges.reconcile_call_charge(tenant_id, call_id, Decimal("3.000000"))
    assert outcome == "matched" and charge_alarms == []
    again = await engine_charges.reconcile_call_charge(tenant_id, call_id, Decimal("9.999999"))
    assert again == "already_recorded"
    async with tenant_session(tenant_id) as session:
        held = (
            await session.execute(
                text("SELECT engine_charged_inr FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar_one()
    assert held == Decimal("3.000000")


@pytest.mark.rls
async def test_a_rate_attested_without_the_fee_is_a_named_variance(
    charge_alarms: list[tuple[str, str]],
) -> None:
    tenant_id, call_id = await _call_with_usage(
        rate_key="studio", minute_cost=Decimal("3.0000"), tts=False
    )
    outcome = await engine_charges.reconcile_call_charge(tenant_id, call_id, Decimal("3.000000"))
    assert outcome == "variance"
    code, detail = charge_alarms[0]
    assert code == "engine_call_cost_variance"
    assert "metered INR 3.0000 vs charged-with-fee INR 3.2700" in detail and "%" in detail


@pytest.mark.rls
async def test_a_studio_call_needs_its_cartesia_row(charge_alarms: list[tuple[str, str]]) -> None:
    tenant_id, call_id = await _call_with_usage(
        rate_key="byok_voice", minute_cost=Decimal("1.6350"), tts=False
    )
    outcome = await engine_charges.reconcile_call_charge(tenant_id, call_id, Decimal("1.500000"))
    assert outcome == "synthesis_cost_missing"
    assert [code for code, _ in charge_alarms] == ["engine_studio_synthesis_cost_missing"]
    with_tts, tts_call = await _call_with_usage(
        rate_key="byok_voice", minute_cost=Decimal("1.0000"), tts=True
    )
    charge_alarms.clear()
    assert (
        await engine_charges.reconcile_call_charge(with_tts, tts_call, Decimal("1.500000"))
        == "variance"
    )
    assert "Cartesia synthesis is metered separately at INR 2.0000" in charge_alarms[0][1]


@pytest.mark.rls
async def test_an_unmetered_or_unpriced_call_is_kept_and_not_compared(
    charge_alarms: list[tuple[str, str]],
) -> None:
    tenant_id, call_id = await _call_with_usage(rate_key="studio", minute_cost=None, tts=False)
    assert (
        await engine_charges.reconcile_call_charge(tenant_id, call_id, Decimal("3.000000"))
        == "unpriced"
    )
    bare_tenant, _agent = await _seed_tenant(f"sync_{uuid.uuid4().hex[:10]}")
    bare_call = uuid7()
    async with tenant_session(bare_tenant) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                "'completed', now(), now())"
            ),
            {"id": bare_call, "tid": bare_tenant, "aid": _agent, "ecid": f"out_{bare_call}"},
        )
    assert (
        await engine_charges.reconcile_call_charge(bare_tenant, bare_call, Decimal("1"))
        == "not_metered"
    )
    assert charge_alarms == []


# --- (19) the two extra events -----------------------------------------------------------


def test_lead_and_escalation_events_are_our_notices() -> None:
    engine = ThinnestEngine(api_key="x")
    lead = engine.parse_notice(
        {
            "id": "evt_1",
            "event": "lead.captured",
            "sentAt": "2026-10-08T09:12:03.551Z",
            "data": {"agent": {"id": "ag_1"}, "callId": "out_1", "phone": "+919876543210"},
        }
    )
    assert lead is not None and lead.kind == "lead_captured"
    assert (lead.notice_id, lead.engine_agent_ref, lead.engine_call_id) == (
        "evt_1",
        "ag_1",
        "out_1",
    )
    assert "9876543210" not in lead.model_dump_json()
    escalated = engine.parse_notice(
        {"id": "evt_2", "event": "conversation.escalated", "data": {"agentId": "ag_2"}}
    )
    assert escalated is not None and escalated.kind == "conversation_escalated"
    assert escalated.engine_agent_ref == "ag_2" and escalated.engine_call_id is None
    assert engine.parse_notice({"id": "evt_3", "event": "call.analysed", "data": {}}) is None
    assert engine.parse_notice({"event": "lead.captured", "data": {}}) is None
    assert thinnest.NOTICE_EVENTS == ("lead.captured", "conversation.escalated")


def test_the_new_alarms_are_registered() -> None:
    from apps.api.core.alarm_severity import ALARM_SEVERITY

    for code in (
        "engine_dial_setup_refused",
        "engine_number_daily_limit",
        "engine_agent_settings_repaired",
        "engine_agent_settings_drifted",
        "engine_call_cost_variance",
        "engine_studio_synthesis_cost_missing",
    ):
        assert code in ALARM_SEVERITY
    assert RECIPIENT_OPTED_OUT_CODE == "engine_recipient_opted_out"
