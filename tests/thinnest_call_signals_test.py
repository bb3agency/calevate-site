"""What ThinnestAI reports about a call beside its result (docs.thinnest.ai
api-reference/webhooks, read 11 Oct 2026): `call.problem` while it is live, the `quality`
block once it ends, the notices that now name their call, the `callRef` of an inbound
`call.completed`, the platform's own status read, and the empty agent hand-off list.

SHARED DATABASE DISCIPLINE: every row is minted here and every assertion is scoped to it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import signed_intake
from apps.api.core.errors import ProblemError
from apps.api.crm import service as crm_service
from apps.api.db.session import tenant_session
from apps.api.engine.health import PlatformStatus
from apps.api.engine.thinnest import (
    PROBLEM_DETAIL_MAX_CHARS,
    HandoffTarget,
    ThinnestEngine,
    _tools_drift,
    handoff_agents_body,
    parse_quality,
    problem_detail,
)
from apps.api.engine.thinnest_webhooks import SUBSCRIBED_EVENTS
from apps.api.healer import health
from apps.api.reliability.engine_intake_keys import seal_delivery
from apps.workers import engine_signals, healer
from apps.workers.settings import WorkerSettings
from calevate_shared.engine import AgentConfig
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

ENGINE = "thinnest"
QUALITY = {
    "turns": 14,
    "responseMs": {"median": 1180, "p90": 1920, "max": 3410},
    "firstTokenMs": {"median": 610, "p90": 940, "max": None},
    "longSilences": 1,
    "longSilenceSeconds": 10,
    "longestSilenceSeconds": 12.4,
    "interruptions": 2,
    "modelErrors": None,
    "rescues": 1,
}


# --- the adapter --------------------------------------------------------------------------


def test_quality_is_read_in_our_names_and_a_missing_figure_stays_missing() -> None:
    q = parse_quality(QUALITY)
    assert q is not None
    assert (q.turns, q.reply_ms_median, q.reply_ms_p90, q.reply_ms_max) == (14, 1180, 1920, 3410)
    assert q.first_token_ms_max is None and q.model_errors is None
    assert q.longest_silence_s == 12.4 and q.backup_answers == 1
    assert parse_quality(None) is None
    assert parse_quality({"turns": "many", "interruptions": -1}).turns is None  # type: ignore[union-attr]


def test_a_call_object_carries_its_quality_and_an_inbound_completion_its_callref() -> None:
    engine = ThinnestEngine(api_key="ta_x")
    snap = engine.snapshot_from_delivery(
        {
            "event": "call.analysed",
            "data": {"id": "out_1", "status": "completed", "quality": QUALITY},
        }
    )
    assert snap.quality is not None and snap.quality.turns == 14
    inbound = engine.parse_webhook(
        {"event": "call.completed", "data": {"callRef": "CA77", "outcome": "completed"}}
    )
    assert inbound.call_id == "CA77"


@pytest.mark.parametrize(
    ("kind", "ours"),
    [
        ("byok_failed", "own_key_failed"),
        ("voice_failed", "voice_failed"),
        ("slow_reply", "slow_reply"),
        ("no_answer_from_model", "no_answer_from_model"),
    ],
)
def test_a_problem_carries_the_vendors_sentence_only_for_a_key_failure(
    kind: str, ours: str
) -> None:
    problem = ThinnestEngine(api_key="ta_x").parse_problem(
        {
            "id": "evt_1",
            "event": "call.problem",
            "data": {
                "callId": "out_9",
                "agentId": "ag_5",
                "kind": kind,
                "detail": "A reply took 6.2 seconds to start.",
                "at": "2026-10-06T04:31:02.702Z",
            },
        }
    )
    assert problem is not None and problem.kind == ours
    assert problem.engine_call_id == "out_9" and problem.engine_agent_ref == "ag_5"
    assert problem.operator_detail == (
        "A reply took 6.2 seconds to start." if ours == "own_key_failed" else None
    )


def test_an_unknown_problem_kind_is_not_read() -> None:
    engine = ThinnestEngine(api_key="ta_x")
    body = {"id": "e", "event": "call.problem", "data": {"callId": "c", "kind": "new_kind"}}
    assert engine.parse_problem(body) is None


def test_a_notice_names_its_call_and_its_agent() -> None:
    notice = ThinnestEngine(api_key="ta_x").parse_notice(
        {
            "id": "evt_2",
            "event": "lead.captured",
            "data": {"conversationId": "conv_1", "agentId": "ag_7", "callId": "out_3"},
        }
    )
    assert notice is not None
    assert (notice.engine_agent_ref, notice.engine_call_id) == ("ag_7", "out_3")


def test_every_endpoint_subscribes_to_call_problem() -> None:
    assert "call.problem" in SUBSCRIBED_EVENTS


async def _status(answer: httpx.Response | Exception) -> PlatformStatus:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/status"
        assert "Authorization" not in request.headers
        if isinstance(answer, Exception):
            raise answer
        return answer

    engine = ThinnestEngine(api_key="ta_x", status_transport=httpx.MockTransport(handler))
    return await engine.platform_status()


async def test_the_platform_status_is_read_without_our_key() -> None:
    ok = await _status(
        httpx.Response(
            200, json={"checkedAt": "x", "database": "operational", "voiceEngine": "operational"}
        )
    )
    assert ok == PlatformStatus(
        reachable=True,
        calls_operational=True,
        data_operational=True,
        reported="voice operational, data operational",
    )
    down = await _status(
        httpx.Response(200, json={"database": "operational", "voiceEngine": "major_outage"})
    )
    assert down.calls_operational is False and down.data_operational is True
    odd = await _status(httpx.Response(200, json={"voiceEngine": "<script>"}))
    assert odd.reported == "voice other, data other"
    assert (await _status(httpx.Response(503))).reachable is False
    assert (await _status(httpx.ConnectError("x"))).reachable is False
    assert (await ThinnestEngine(api_key=None).platform_status()).reachable is False


# --- item 6: agent-to-agent hand-off ----------------------------------------------------


def test_a_hand_off_list_is_always_sent_empty_and_one_typed_in_the_console_is_drift() -> None:
    cfg = AgentConfig.model_construct(handoff=None, engine_own_voice_key=True)
    body = ThinnestEngine.built_in_tools_body(cfg)
    assert body["handOver"]["agents"] == []
    held = {
        "tools": [{"id": t, "enabled": on} for t, on in body["tools"].items()],
        "handOver": {"mode": "chat", "agents": [{"agent": "ag_x", "when": "orders"}]},
        "knowledgeOnCalls": body["knowledgeOnCalls"],
        "recall": body["recall"],
        "verifyByCode": body["verifyByCode"],
    }
    assert _tools_drift(body, held) == ["handOver.agents"]


def test_a_hand_off_across_clear_and_studio_is_refused_in_plain_words() -> None:
    studio = HandoffTarget(engine_agent_ref="ag_s@org_1", own_voice_key=True, when="billing")
    clear = HandoffTarget(engine_agent_ref="ag_c@org_1", own_voice_key=False, when="billing")
    assert handoff_agents_body(True, [studio]) == [{"agent": "ag_s", "when": "billing"}]
    with pytest.raises(ProblemError) as refused:
        handoff_agents_body(True, [clear])
    assert refused.value.code == "handoff_across_voice_tiers"
    with pytest.raises(ProblemError):
        handoff_agents_body(False, [studio])


# --- the intake ---------------------------------------------------------------------------


def _intake() -> signed_intake.SignedIntake:
    return signed_intake.SIGNED_INTAKES[ENGINE]


def test_an_inbound_completion_is_keyed_on_its_callref_in_the_agents_workspace() -> None:
    keyed = signed_intake.keyed_event(
        _intake(),
        {"id": "evt_a", "event": "call.completed", "data": {"callRef": "CA9", "outcome": "missed"}},
        engine_agent_ref="ag_1@org_7",
    )
    assert isinstance(keyed, signed_intake.SignedEvent)
    assert keyed.execution_id == "CA9@org_7" and keyed.job == signed_intake.INGEST_JOB


def test_a_problem_is_keyed_on_its_call_and_routed_to_its_own_job() -> None:
    keyed = signed_intake.keyed_event(
        _intake(),
        {"id": "evt_b", "event": "call.problem", "data": {"callId": "out_4", "agentId": "ag_1"}},
        engine_agent_ref="ag_1",
    )
    assert isinstance(keyed, signed_intake.SignedEvent)
    assert keyed.execution_id == "out_4" and keyed.job == signed_intake.ENGINE_PROBLEM_JOB
    other = signed_intake.keyed_event(
        _intake(),
        {"id": "evt_c", "event": "call.problem", "data": {"callId": "out_4", "agentId": "ag_2"}},
        engine_agent_ref="ag_1",
    )
    assert other == "agent mismatch"


def test_a_notice_stays_keyed_on_its_event_id_so_dedupe_is_unchanged() -> None:
    keyed = signed_intake.keyed_event(
        _intake(),
        {"id": "evt_d", "event": "lead.captured", "data": {"callId": "out_5", "agentId": "ag_1"}},
        engine_agent_ref="ag_1",
    )
    assert isinstance(keyed, signed_intake.SignedEvent)
    assert keyed.execution_id == "evt_d" and keyed.event_name == "lead.captured:evt_d"


def test_the_problem_job_is_named_as_voice_runtime_enqueues_it_and_is_registered() -> None:
    import webhook_routes

    assert engine_signals.ENGINE_PROBLEM_JOB == signed_intake.ENGINE_PROBLEM_JOB
    assert webhook_routes.ENGINE_PROBLEM_JOB == signed_intake.ENGINE_PROBLEM_JOB
    registered = {getattr(fn, "__qualname__", "") for fn in WorkerSettings.functions}
    assert engine_signals.ENGINE_PROBLEM_JOB in registered


# --- the worker ---------------------------------------------------------------------------


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    raised: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        engine_signals, "alert", lambda _stage, code, **kw: raised.append((code, kw))
    )
    monkeypatch.setattr(engine_signals, "get_engine", lambda: ThinnestEngine(api_key="ta_x"))
    return raised


async def _route(*, rate_key: str | None = None) -> tuple[uuid.UUID, uuid.UUID, str]:
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, engine_rate_key, created_at, updated_at) VALUES ('thinnest', :ref, "
                ":tid, :aid, true, :rk, now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id, "rk": rate_key},
        )
    return tenant_id, agent_id, ref


def _problem(ref: str, call: str, kind: str, detail: str = "x") -> dict[str, Any]:
    event_id = f"evt_{uuid.uuid4().hex[:10]}"
    body = json.dumps(
        {
            "id": event_id,
            "event": "call.problem",
            "sentAt": "2026-10-11T09:00:00Z",
            "data": {
                "callId": call,
                "agentId": ref,
                "kind": kind,
                "detail": detail,
                "at": "2026-10-11T09:00:00Z",
            },
        }
    )
    return {
        "engine": ENGINE,
        "execution_id": call,
        "raw_status": "call.problem",
        "engine_agent_ref": ref,
        "delivery": seal_delivery(
            body, engine=ENGINE, execution_id=call, event_name=f"call.problem:{event_id}"
        ),
    }


async def _signals(tenant_id: uuid.UUID, call: str) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text("SELECT kind FROM call_engine_signals WHERE engine_call_id = :c ORDER BY kind"),
            {"c": call},
        )
        return [str(r[0]) for r in rows]


async def test_a_studio_voice_failure_is_filed_once_and_alarms_the_key(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    tenant_id, _agent_id, ref = await _route(rate_key="byok_voice")
    call = f"in_{uuid.uuid4()}"
    assert await engine_signals.ingest_engine_problem({}, _problem(ref, call, "voice_failed")) == (
        "voice_failed"
    )
    # A re-send of the same kind on the same call files and alarms nothing more.
    await engine_signals.ingest_engine_problem({}, _problem(ref, call, "voice_failed"))
    assert await _signals(tenant_id, call) == ["voice_failed"]
    assert [code for code, _ in alerts] == ["studio_call_voice_failed"]
    assert "Cartesia key" in str(alerts[0][1]["detail"])


async def test_an_own_key_failure_names_the_key_and_no_backup_model(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    _tenant_id, _agent_id, ref = await _route(rate_key="byok_voice")
    await engine_signals.ingest_engine_problem(
        {}, _problem(ref, f"in_{uuid.uuid4()}", "byok_failed")
    )
    [(code, fields)] = alerts
    assert code == "engine_call_own_key_failed"
    detail = str(fields["detail"])
    assert "no backup on our own keys" in detail
    assert "apology" in detail and "quota" in detail
    assert "backup model" not in detail


async def test_a_clear_agents_problems_alarm_by_kind_and_a_slow_reply_alarms_nothing(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    tenant_id, _agent_id, ref = await _route(rate_key="studio")
    call = f"out_{uuid.uuid4()}"
    for kind in ("slow_reply", "voice_failed", "byok_failed"):
        await engine_signals.ingest_engine_problem({}, _problem(ref, call, kind))
    assert await _signals(tenant_id, call) == ["own_key_failed", "slow_reply", "voice_failed"]
    assert [code for code, _ in alerts] == [
        "engine_call_voice_failed",
        "engine_call_own_key_failed",
    ]


async def test_another_tenant_cannot_see_a_calls_signals(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    tenant_id, _agent_id, ref = await _route()
    call = f"out_{uuid.uuid4()}"
    await engine_signals.ingest_engine_problem({}, _problem(ref, call, "slow_reply"))
    other, _other_agent = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    assert await _signals(tenant_id, call) == ["slow_reply"]
    assert await _signals(other, call) == []


async def test_a_notice_is_attached_to_the_call_it_names(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    tenant_id, _agent_id, ref = await _route()
    call = f"out_{uuid.uuid4()}"
    event_id = f"evt_{uuid.uuid4().hex[:10]}"
    body = json.dumps(
        {
            "id": event_id,
            "event": "conversation.escalated",
            "sentAt": "2026-10-11T09:00:00Z",
            "data": {"agentId": ref, "callId": call, "conversationId": "conv_1"},
        }
    )
    payload = {
        "engine": ENGINE,
        "execution_id": event_id,
        "raw_status": "conversation.escalated",
        "engine_agent_ref": ref,
        "delivery": seal_delivery(
            body,
            engine=ENGINE,
            execution_id=event_id,
            event_name=f"conversation.escalated:{event_id}",
        ),
    }
    assert await engine_signals.ingest_engine_notice({}, payload) == "conversation_escalated"
    assert await _signals(tenant_id, call) == ["conversation_escalated"]


async def test_the_call_screen_reads_the_quality_and_the_signals(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    tenant_id, agent_id, ref = await _route()
    call_id, engine_call = uuid.uuid4(), f"out_{uuid.uuid4()}"
    quality = parse_quality(QUALITY)
    assert quality is not None
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "engine_quality, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'outbound', 'completed', CAST(:q AS jsonb), now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": engine_call,
                "q": quality.model_dump_json(),
            },
        )
    await engine_signals.ingest_engine_problem({}, _problem(ref, engine_call, "slow_reply"))
    async with tenant_session(tenant_id) as session:
        detail = await crm_service.get_call(session, call_id, raw=False)
    assert detail.quality is not None and detail.quality.reply_ms_p90 == 1920
    assert [s.kind for s in detail.signals] == ["slow_reply"]


async def test_quality_that_is_not_numbers_is_refused_by_the_database() -> None:
    tenant_id, agent_id, _ref = await _route()
    with pytest.raises(Exception, match="engine_quality"):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, engine_quality, created_at, updated_at) VALUES (:id, :tid, :aid, "
                    ":ecid, 'outbound', 'completed', CAST(:q AS jsonb), now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ecid": f"out_{uuid.uuid4()}",
                    "q": json.dumps({"turns": "the caller said hello"}),
                },
            )


# --- the healer ---------------------------------------------------------------------------


async def test_the_healer_counts_a_slow_reply_as_slow_and_silence_as_a_failure(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    tenant_id, agent_id, ref = await _route()
    start = health.window_start(datetime.now(UTC)) - timedelta(minutes=30)
    calls = [f"out_{uuid.uuid4()}" for _ in range(3)]
    async with tenant_session(tenant_id) as session:
        for ecid in calls:
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, duration_s, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                    "'outbound', 'completed', 120, :at, :at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ecid": ecid,
                    "at": start + timedelta(minutes=1),
                },
            )
    await engine_signals.ingest_engine_problem({}, _problem(ref, calls[0], "slow_reply"))
    await engine_signals.ingest_engine_problem({}, _problem(ref, calls[1], "voice_failed"))
    async with tenant_session(tenant_id) as session:
        counts = {c.agent_id: c for c in await health.count_window(session, start=start)}
    mine = counts[agent_id]
    assert (mine.calls, mine.slow_starts, mine.failed_calls) == (3, 1, 1)


async def test_the_outage_check_says_whose_fault_it_looks_like(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Down:
        async def platform_status(self) -> PlatformStatus:
            return PlatformStatus(
                reachable=True, calls_operational=False, data_operational=True, reported="v"
            )

    monkeypatch.setattr(healer, "get_engine", lambda: Down())
    status = await healer.platform_status()
    assert status is not None and status.calls_operational is False
    assert "reports a fault" in healer._status_words(status)
    up = PlatformStatus(reachable=True, calls_operational=True, data_operational=True, reported="v")
    assert "look at our side first" in healer._status_words(up)
    assert "did not answer" in healer._status_words(PlatformStatus(reachable=False))


def test_the_key_failure_sentence_is_one_short_line_with_long_numbers_masked() -> None:
    long = "Your Google key was refused  for project 9876543210 (quota).\n" + "x" * 400
    detail = problem_detail(long)
    assert detail is not None and "\n" not in detail
    assert "9876543210" not in detail and "[number]" in detail and "(quota)" in detail
    assert len(detail) == PROBLEM_DETAIL_MAX_CHARS and detail.endswith("…")
    assert problem_detail("Key 12345 failed.") == "Key 12345 failed."
    assert problem_detail(None) is None and problem_detail("   ") is None


async def test_an_own_key_failure_alarm_carries_the_platforms_sentence(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    _tenant_id, _agent_id, ref = await _route(rate_key="byok_llm_voice")
    await engine_signals.ingest_engine_problem(
        {},
        _problem(
            ref,
            f"in_{uuid.uuid4()}",
            "byok_failed",
            detail="Your Gemini key returned 429: quota exceeded.",
        ),
    )
    [(code, fields)] = alerts
    assert code == "engine_call_own_key_failed"
    assert 'The voice platform said: "Your Gemini key returned 429: quota exceeded."' in str(
        fields["detail"]
    )
