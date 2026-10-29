"""Follow-up runs (D-940): starting, every step kind, every stop, the triggers, and the
call step through the call-back tick's own gate and dial."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.compliance.service import add_to_dnc
from apps.api.crm import service as crm
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.follow_ups import runner, service
from apps.api.whatsapp.webhooks import extract_events
from apps.workers import follow_ups as worker
from apps.workers.callbacks import dispatch_due_callbacks
from apps.workers.retention import ANONYMIZED_PHONE, _erase_follow_up_runs, sweep_tenant
from sqlalchemy import text
from tests.callback_dispatch_test import _dialable_tenant
from tests.follow_ups_support import publish

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so the gate's calling hours are never what a test here measures."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)
    reset_engine_cache()


def _phone() -> str:
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


async def _lead(
    tenant_id: UUID, agent_id: UUID, *, phone: str | None = None, data: dict[str, Any] | None = None
) -> tuple[UUID, str]:
    lead_id, number = uuid7(), phone or _phone()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Asha', 'webhook', 'new', "
                "CAST(:d AS jsonb), now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": number, "d": json.dumps(data or {})},
        )
    return lead_id, number


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    lead_id: UUID | None,
    phone: str,
    status: str = "completed",
    direction: str = "inbound",
    outcome: str | None = None,
    business: str | None = None,
    trial: bool = False,
) -> UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, direction, "
                "from_e164, to_e164, status, outcome_tag, business_outcome, "
                "business_outcome_label, trial_call, created_at, updated_at) VALUES (:id, :t, "
                ":a, :l, :e, :d, :f, :to, :s, :o, :b, :bl, :trial, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "l": lead_id,
                "e": f"fu_{uuid.uuid4().hex}",
                "d": direction,
                "f": phone if direction == "inbound" else "+914000000000",
                "to": "+914000000000" if direction == "inbound" else phone,
                "s": status,
                "o": outcome,
                "b": business,
                "bl": business.title() if business else None,
                "trial": trial,
            },
        )
    return call_id


async def _run(tenant_id: UUID, follow_up_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id, status, step_id, end_reason, goal_reached, wake_at, attempt, "
                        "waiting_call_id, last_call_id FROM follow_up_runs WHERE follow_up_id = :f "
                        "ORDER BY started_at DESC LIMIT 1"
                    ),
                    {"f": follow_up_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def _events(tenant_id: UUID, run_id: UUID) -> list[tuple[str, str, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT step_id, kind, result FROM follow_up_run_events WHERE run_id = :r "
                    "ORDER BY at, id"
                ),
                {"r": run_id},
            )
        ).all()
    return [(str(a), str(b), str(c)) for a, b, c in rows]


async def _start(tenant_id: UUID, follow_up_id: UUID, lead_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        outcome = await service.start_leads(
            session, follow_up_id, tenant_id=tenant_id, lead_ids=[lead_id]
        )
    assert outcome.started == 1
    return UUID(str((await _run(tenant_id, follow_up_id))["id"]))


async def _due_now(tenant_id: UUID, run_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE follow_up_runs SET wake_at = now() - interval '1 second' WHERE id = :r"),
            {"r": run_id},
        )


async def _owner(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        found = (await session.execute(text("SELECT user_id FROM memberships LIMIT 1"))).scalar()
        if found is None:
            user_id = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO users (id, email, created_at, updated_at) VALUES "
                    "(:id, :e, now(), now())"
                ),
                {"id": user_id, "e": f"{user_id}@example.com"},
            )
            await session.execute(
                text(
                    "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, "
                    "updated_at) VALUES (:id, :t, :u, 'owner', now(), now())"
                ),
                {"id": uuid.uuid4(), "t": tenant_id, "u": user_id},
            )
            return user_id
    return UUID(str(found))


# --- steps without a call -------------------------------------------------------------


async def test_a_run_waits_then_marks_assigns_and_reaches_its_goal() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    owner = await _owner(tenant_id)
    follow_up_id = await publish(
        tenant_id,
        steps=[
            {"id": "s1", "kind": "wait", "minutes": 5, "next": "s2"},
            {"id": "s2", "kind": "set_status", "status": "hot", "next": "s3"},
            {"id": "s3", "kind": "assign", "user_id": str(owner), "next": "s4"},
            {"id": "s4", "kind": "end", "goal": True},
        ],
    )
    lead_id, _ = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)

    assert await runner.drive(tenant_id, run_id) == 1
    waiting = await _run(tenant_id, follow_up_id)
    assert (waiting["status"], waiting["step_id"]) == ("waiting", "s1")
    assert waiting["wake_at"] > datetime.now(UTC) + timedelta(minutes=4)
    assert await runner.drive(tenant_id, run_id) == 0, "not due yet: nothing is claimed"

    await _due_now(tenant_id, run_id)
    assert await runner.drive(tenant_id, run_id) == 4
    done = await _run(tenant_id, follow_up_id)
    assert (done["status"], done["end_reason"], done["goal_reached"]) == ("done", "goal", True)
    async with tenant_session(tenant_id) as session:
        lead = (
            await session.execute(
                text("SELECT status, assigned_to FROM leads WHERE id = :l"), {"l": lead_id}
            )
        ).one()
    assert (lead[0], lead[1]) == ("hot", owner)
    assert await _events(tenant_id, run_id) == [
        ("s1", "start", "manual"),
        ("s1", "waiting", "waiting"),
        ("s1", "wait", "waited"),
        ("s2", "set_status", "status:hot"),
        ("s3", "assign", "assigned"),
        ("s4", "end", "end"),
    ]
    assert await runner.drive(tenant_id, run_id) == 0, "a finished run is never claimed again"


async def test_assign_and_status_steps_skip_what_they_cannot_do() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(
        tenant_id,
        steps=[
            {"id": "s1", "kind": "set_status", "status": "contacted", "next": "s2"},
            {"id": "s2", "kind": "assign", "user_id": str(await _owner(tenant_id)), "next": "s3"},
            {"id": "s3", "kind": "wait", "until_field": "visit_date", "next": "s4"},
            {"id": "s4", "kind": "end"},
        ],
    )
    lead_id, _p = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET deleted_at = now() WHERE id = :l"), {"l": lead_id}
        )
    await runner.drive(tenant_id, run_id)
    results = [e[2] for e in await _events(tenant_id, run_id)]
    assert "skipped:not_found" in results
    assert results[-2:] == ["no_date", "end"]
    assert (await _run(tenant_id, follow_up_id))["end_reason"] == "finished"


async def test_a_wait_until_a_lead_date_sleeps_until_that_morning() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(
        tenant_id,
        steps=[
            {
                "id": "s1",
                "kind": "wait",
                "until_field": "visit_date",
                "offset_days": -1,
                "at": "09:30",
                "next": None,
            },
        ],
    )
    visit = (datetime.now(UTC) + timedelta(days=5)).date()
    lead_id, _p = await _lead(tenant_id, agent_id, data={"visit_date": visit.isoformat()})
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    await runner.drive(tenant_id, run_id)
    assert (await _run(tenant_id, follow_up_id))["wake_at"] == runner.at_ist(
        visit - timedelta(days=1), "09:30"
    )
    # A date already past moves straight on.
    past_lead, _q = await _lead(tenant_id, agent_id, data={"visit_date": "2020-01-01"})
    past_run = await _start(tenant_id, follow_up_id, past_lead)
    await runner.drive(tenant_id, past_run)
    assert [e[2] for e in await _events(tenant_id, past_run)][-1] == "date_passed"


async def test_decide_branches_on_the_business_outcome_then_the_call_outcome() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    await publish(
        tenant_id,
        trigger={"kind": "call_ended", "calls": "inbound"},
        steps=[
            {
                "id": "s1",
                "kind": "decide",
                "on": {"interested": "s2", "missed": "s3"},
                "other": None,
            },
            {"id": "s2", "kind": "end", "goal": False},
            {"id": "s3", "kind": "end"},
        ],
        settings={"goal": "interested"},
    )
    seen: dict[str, Any] = {}
    for business, outcome in (("interested", "answered"), (None, "missed"), (None, "answered")):
        lead_id, phone = await _lead(tenant_id, agent_id)
        call_id = await _call(
            tenant_id, agent_id, lead_id=lead_id, phone=phone, outcome=outcome, business=business
        )
        async with tenant_session(tenant_id) as session:
            [run_id] = await runner.start_for_call(session, tenant_id=tenant_id, call_id=call_id)
        await runner.drive(tenant_id, run_id)
        events = await _events(tenant_id, run_id)
        seen[f"{business}/{outcome}"] = (events[1][2], (await _run_by_id(tenant_id, run_id)))
    assert seen["interested/answered"][0] == "branch:interested"
    assert seen["interested/answered"][1]["goal_reached"] is True
    assert seen["None/missed"][0] == "branch:missed"
    assert seen["None/answered"][0] == "branch:other"
    assert seen["None/answered"][1]["goal_reached"] is False


async def _run_by_id(tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, end_reason, goal_reached FROM follow_up_runs WHERE id = :r"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def test_tell_team_queues_one_alert_about_the_runs_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _dialable_tenant()
    async with tenant_session(tenant_id) as session:
        contact_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO team_alert_contacts (id, tenant_id, channel, address, is_default, "
                "verified_at, created_at, updated_at) VALUES (:id, :t, 'email', 'team@ex.com', "
                "true, now(), now(), now())"
            ),
            {"id": contact_id, "t": tenant_id},
        )
    follow_up_id = await publish(
        tenant_id,
        trigger={"kind": "call_ended"},
        steps=[{"id": "s1", "kind": "tell_team", "why": "Wants a visit"}],
    )
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _call(tenant_id, agent_id, lead_id=lead_id, phone=phone)
    async with tenant_session(tenant_id) as session:
        [run_id] = await runner.start_for_call(session, tenant_id=tenant_id, call_id=call_id)
    await runner.drive(tenant_id, run_id)
    async with tenant_session(tenant_id) as session:
        alerts = (
            await session.execute(
                text("SELECT trigger, reasons FROM team_alerts WHERE call_id = :c"),
                {"c": call_id},
            )
        ).all()
    assert [(a[0], a[1][0]["why"]) for a in alerts] == [("follow_up", "Wants a visit")]
    assert (await _events(tenant_id, run_id))[-1][2] == "sent"
    del follow_up_id


async def test_whatsapp_and_action_steps_go_out_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.actions.execution import ExecutionResult
    from apps.api.crm import lead_message, swipe

    sent: list[dict[str, Any]] = []

    async def _send(session: Any, **kwargs: Any) -> swipe.WhatsAppSendOut:
        sent.append(kwargs)
        return swipe.WhatsAppSendOut(status="sent")

    ran: list[UUID] = []

    async def _execute(session: Any, *, tool: Any, **kwargs: Any) -> ExecutionResult:
        ran.append(tool.id)
        return ExecutionResult(ok=True, payload={}, status="ok")

    class _Tool:
        id = uuid.uuid4()
        enabled = True

    async def _get_tool(session: Any, *, tool_id: UUID) -> Any:
        return _Tool()

    monkeypatch.setattr(lead_message, "send_lead_whatsapp", _send)
    monkeypatch.setattr("apps.api.actions.execution.execute_action", _execute)
    monkeypatch.setattr("apps.api.actions.service.get_tool", _get_tool)
    tenant_id, agent_id = await _dialable_tenant()
    template_id = uuid.uuid4()
    follow_up_id = await _published_raw(
        tenant_id,
        [
            {
                "id": "s1",
                "kind": "whatsapp",
                "template_id": str(template_id),
                "values": [
                    {"source": "lead_name"},
                    {"source": "business_name"},
                    {"source": "agent_name"},
                    {"source": "lead_field", "key": "city"},
                    {"source": "text", "text": "Hi"},
                ],
                "next": {"sent": "s2", "not_sent": None},
            },
            {
                "id": "s2",
                "kind": "action",
                "action_id": str(uuid.uuid4()),
                "next": {"done": None, "failed": None},
            },
        ],
    )
    lead_id, _p = await _lead(tenant_id, agent_id, data={"city": "Guntur"})
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    assert await runner.drive(tenant_id, run_id) == 2
    assert len(sent) == 1 and sent[0]["idempotency_key"] == f"follow-up:{run_id}:s1"
    assert sent[0]["payload"].values[0] == "Asha" and sent[0]["payload"].values[3] == "Guntur"
    assert len(ran) == 1
    results = [e[2] for e in await _events(tenant_id, run_id)]
    assert results[-3:] == ["sent", "started", "done"]


async def _published_raw(tenant_id: UUID, steps: list[dict[str, Any]]) -> UUID:
    """A live version written directly: for steps whose references (a template, an action)
    this test fakes rather than creates."""
    follow_up_id, version_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO follow_ups (id, tenant_id, name, status, trigger, settings) VALUES "
                "(:f, :t, 'Raw', 'draft', '{\"kind\": \"manual\"}'::jsonb, '{}'::jsonb)"
            ),
            {"f": follow_up_id, "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO follow_up_versions (id, tenant_id, follow_up_id, number, steps, "
                "trigger, settings) VALUES (:v, :t, :f, 1, CAST(:s AS jsonb), "
                "'{\"kind\": \"manual\"}'::jsonb, '{}'::jsonb)"
            ),
            {"v": version_id, "t": tenant_id, "f": follow_up_id, "s": json.dumps(steps)},
        )
        await session.execute(
            text("UPDATE follow_ups SET status = 'live', live_version_id = :v WHERE id = :f"),
            {"v": version_id, "f": follow_up_id},
        )
    return follow_up_id


async def test_an_action_started_before_a_crash_is_never_run_twice() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _published_raw(
        tenant_id, [{"id": "s1", "kind": "action", "action_id": str(uuid.uuid4())}]
    )
    lead_id, _p = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    async with tenant_session(tenant_id) as session:
        run = await runner.load_run(session, run_id)
        assert run is not None
        await runner.record(session, run, step_id="s1", kind="started", result="started")
    await runner.drive(tenant_id, run_id)
    assert [e[2] for e in await _events(tenant_id, run_id)][-1] == "failed:unconfirmed"


# --- starting --------------------------------------------------------------------------


async def test_only_if_again_and_the_hourly_cap_decide_who_starts() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(
        tenant_id,
        steps=[{"id": "s1", "kind": "end"}],
        trigger={
            "kind": "manual",
            "only_if": {"lead_status": ["new"], "field": {"key": "city", "equals": "Guntur"}},
        },
        settings={"again": "never", "starts_per_hour": 1},
    )
    yes, _a = await _lead(tenant_id, agent_id, data={"city": "guntur"})
    no, _b = await _lead(tenant_id, agent_id, data={"city": "Vizag"})
    also, _c = await _lead(tenant_id, agent_id, data={"city": "Guntur"})
    async with tenant_session(tenant_id) as session:
        first = await service.start_leads(
            session, follow_up_id, tenant_id=tenant_id, lead_ids=[yes, no]
        )
        assert (first.started, first.skipped) == (1, 1)
        live = await runner.version(
            session, (await service.get(session, follow_up_id)).live_version_id
        )  # type: ignore[arg-type]
        capped = await runner.start_run(
            session,
            tenant_id=tenant_id,
            follow_up=live,
            lead_id=also,
            phone_e164=_c,
            trigger_ref="manual:x",
        )
        assert capped.run is not None
        wake = (
            await session.execute(
                text("SELECT wake_at FROM follow_up_runs WHERE id = :r"), {"r": capped.run.id}
            )
        ).scalar_one()
        assert wake > datetime.now(UTC) + timedelta(minutes=50), "the rest wait their turn"
    await runner.drive(tenant_id, UUID(str((await _run_for(tenant_id, yes))["id"])))
    async with tenant_session(tenant_id) as session:
        again = await runner.start_run(
            session,
            tenant_id=tenant_id,
            follow_up=live,
            lead_id=yes,
            phone_e164=_a,
            trigger_ref="manual:y",
        )
    assert again.outcome == "not_again"


async def _run_for(tenant_id: UUID, lead_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            (
                await session.execute(
                    text("SELECT id, status FROM follow_up_runs WHERE lead_id = :l"), {"l": lead_id}
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def test_a_lead_is_never_in_one_follow_up_twice_at_once() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(
        tenant_id,
        steps=[{"id": "s1", "kind": "wait", "days": 1}],
        settings={"again": "after_30_days"},
    )
    lead_id, _p = await _lead(tenant_id, agent_id)
    await _start(tenant_id, follow_up_id, lead_id)
    async with tenant_session(tenant_id) as session:
        second = await service.start_leads(
            session, follow_up_id, tenant_id=tenant_id, lead_ids=[lead_id]
        )
    assert (second.started, second.skipped) == (0, 1)


async def test_the_call_ended_trigger_matches_and_never_feeds_itself() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(
        tenant_id,
        trigger={
            "kind": "call_ended",
            "calls": "inbound",
            "outcomes": ["missed"],
            "agent_ids": [str(agent_id)],
        },
        steps=[{"id": "s1", "kind": "wait", "minutes": 5}],
    )
    lead_id, phone = await _lead(tenant_id, agent_id)
    missed = await _call(
        tenant_id, agent_id, lead_id=lead_id, phone=phone, outcome="missed", status="no_answer"
    )
    answered = await _call(tenant_id, agent_id, lead_id=lead_id, phone=phone, outcome="answered")
    outbound = await _call(
        tenant_id, agent_id, lead_id=lead_id, phone=phone, outcome="missed", direction="outbound"
    )
    trial = await _call(
        tenant_id, agent_id, lead_id=lead_id, phone=phone, outcome="missed", trial=True
    )
    async with tenant_session(tenant_id) as session:
        for call_id in (answered, outbound, trial):
            assert await runner.start_for_call(session, tenant_id=tenant_id, call_id=call_id) == []
        started = await runner.start_for_call(session, tenant_id=tenant_id, call_id=missed)
        assert len(started) == 1
        assert await runner.start_for_call(session, tenant_id=tenant_id, call_id=missed) == [], (
            "the run's own call never starts another"
        )
    assert (await _run(tenant_id, follow_up_id))["last_call_id"] == missed


async def test_a_lead_date_starts_each_lead_once_per_date() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(
        tenant_id,
        trigger={"kind": "lead_date", "field": "visit_date", "offset_days": -1, "at": "00:00"},
        steps=[{"id": "s1", "kind": "end"}],
    )
    now = datetime.now(UTC)
    tomorrow = (now.replace(tzinfo=None) + timedelta(hours=5, minutes=30)).date() + timedelta(
        days=1
    )
    await _lead(tenant_id, agent_id, data={"visit_date": tomorrow.isoformat()})
    await _lead(tenant_id, agent_id, data={"visit_date": "2031-01-01"})
    async with tenant_session(tenant_id) as session:
        assert await runner.start_for_dates(session, tenant_id=tenant_id, now=now) == 1
        assert await runner.start_for_dates(session, tenant_id=tenant_id, now=now) == 0
    run = await _run(tenant_id, follow_up_id)
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT trigger_ref FROM follow_up_runs WHERE id = :r"), {"r": run["id"]}
            )
        ).scalar_one()
    assert ref == f"visit_date:{tomorrow.isoformat()}"


# --- the call step ----------------------------------------------------------------------


async def _call_follow_up(tenant_id: UUID, agent_id: UUID, **call: Any) -> UUID:
    step = {
        "id": "s1",
        "kind": "call",
        "agent_id": str(agent_id),
        "next": {"answered": "s2", "not_reached": None},
        **call,
    }
    return await publish(tenant_id, steps=[step, {"id": "s2", "kind": "end", "goal": True}])


async def _tick(tenant_id: UUID) -> dict[str, int]:
    """The call-back tick, with every booked Follow-up call due now: the account's hours
    move a booking to its next opening by the real clock, which this file does not pin."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE scheduled_callbacks SET requested_at = now() - interval '1 minute' "
                "WHERE status = 'scheduled' AND source_execution_id LIKE 'follow-up:%' "
                "AND split_part(source_execution_id, ':', 4) = '0'"
            )
        )
    return await dispatch_due_callbacks(tenant_id, slots=5)


async def _callbacks_of(tenant_id: UUID, run_id: UUID) -> list[tuple[str, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT source_execution_id, status FROM scheduled_callbacks WHERE "
                    "source_execution_id LIKE :k ORDER BY created_at"
                ),
                {"k": f"follow-up:{run_id}:%"},
            )
        ).all()
    return [(str(a), str(b)) for a, b in rows]


async def test_a_call_step_is_dialled_by_the_tick_and_retried_when_not_answered() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _call_follow_up(tenant_id, agent_id, retries=1, retry_minutes=30)
    lead_id, phone = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)

    await runner.drive(tenant_id, run_id)
    assert await _callbacks_of(tenant_id, run_id) == [
        (runner.callback_key(run_id, "s1", 0), "scheduled")
    ]
    outcome = await _tick(tenant_id)
    assert outcome["dialled"] == 1, outcome
    run = await _run(tenant_id, follow_up_id)
    assert run["waiting_call_id"] is not None and run["wake_at"] is None
    assert (runner.callback_key(run_id, "s1", 1), "scheduled") in await _callbacks_of(
        tenant_id, run_id
    ), "the next try is booked when this one is dialled"

    first_call = run["waiting_call_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = 'no_answer' WHERE id = :c"), {"c": first_call}
        )
        assert await runner.on_call_ended(session, call_id=first_call) == []
    run = await _run(tenant_id, follow_up_id)
    assert (run["attempt"], run["waiting_call_id"]) == (1, None)

    # The second (last) try is not answered either: the step is left `not_reached`.
    async with tenant_session(tenant_id) as session:
        second = await _call(
            tenant_id,
            agent_id,
            lead_id=lead_id,
            phone=phone,
            status="no_answer",
            direction="outbound",
        )
        await runner.wait_on_call(session, run_id, call_id=second, attempt=1)
        await session.execute(
            text(
                "UPDATE scheduled_callbacks SET status = 'completed', settled_at = now() "
                "WHERE source_execution_id = :k"
            ),
            {"k": runner.callback_key(run_id, "s1", 1)},
        )
    async with tenant_session(tenant_id) as session:
        assert await runner.on_call_ended(session, call_id=second) == [run_id]
    done = await _run(tenant_id, follow_up_id)
    assert (done["status"], done["end_reason"]) == ("done", "finished")


async def test_an_answered_call_takes_the_answered_exit_and_calls_off_the_retry() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _call_follow_up(tenant_id, agent_id, retries=2)
    lead_id, _ = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    await runner.drive(tenant_id, run_id)
    await _tick(tenant_id)
    call_id = (await _run(tenant_id, follow_up_id))["waiting_call_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = 'completed' WHERE id = :c"), {"c": call_id}
        )
        moved = await runner.on_call_ended(session, call_id=call_id)
        assert moved == [run_id]
        assert await runner.on_call_ended(session, call_id=call_id) == [], "once per call"
    await runner.drive(tenant_id, run_id)
    done = await _run(tenant_id, follow_up_id)
    assert (done["status"], done["end_reason"], done["goal_reached"]) == ("done", "goal", True)
    assert (runner.callback_key(run_id, "s1", 1), "cancelled") in await _callbacks_of(
        tenant_id, run_id
    )


async def test_a_retry_after_they_answered_elsewhere_is_answered() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _call_follow_up(tenant_id, agent_id, retries=1)
    lead_id, phone = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    async with tenant_session(tenant_id) as session:
        await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=runner.callback_key(run_id, "s1", 1),
            lead_id=lead_id,
            phone_e164=phone,
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            booked_at=datetime.now(UTC) - timedelta(minutes=10),
            note=None,
            language=None,
        )
        await session.execute(
            text("UPDATE follow_up_runs SET wake_at = NULL, attempt = 1 WHERE id = :r"),
            {"r": run_id},
        )
    await _call(tenant_id, agent_id, lead_id=lead_id, phone=phone, status="completed")
    await _tick(tenant_id)
    run = await _run(tenant_id, follow_up_id)
    assert run["step_id"] == "s2", "they answered: the step is answered"


async def test_a_refusal_for_good_ends_the_run_and_a_stale_call_back_is_called_off() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _call_follow_up(tenant_id, agent_id)
    lead_id, phone = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    await runner.drive(tenant_id, run_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            # Straight into the list, past `cancel_for_phones`: the gate at the dial is what
            # this test measures.
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:i, :t, :p, 'tenant', 'manual', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "p": phone},
        )
    await _tick(tenant_id)
    run = await _run(tenant_id, follow_up_id)
    assert (run["status"], run["end_reason"]) == ("stopped", "do_not_call")

    other_lead, _p = await _lead(tenant_id, agent_id)
    other_run = await _start(tenant_id, follow_up_id, other_lead)
    await runner.drive(tenant_id, other_run)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE follow_up_runs SET status = 'stopped', ended_at = now(), "
                "end_reason = 'stopped_by_client' WHERE id = :r"
            ),
            {"r": other_run},
        )
    await _tick(tenant_id)
    assert await _callbacks_of(tenant_id, other_run) == [
        (runner.callback_key(other_run, "s1", 0), "cancelled")
    ]


async def test_a_trial_or_platform_refusal_ends_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.compliance.service import DispatchDecision
    from apps.api.compliance.trial_access import TRIAL_DIAL_REFUSALS
    from apps.api.engine.vendor_http import recipient_opted_out_error
    from apps.workers import callbacks as callback_worker

    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _call_follow_up(tenant_id, agent_id)
    trial_rule = sorted(TRIAL_DIAL_REFUSALS)[0]
    original_gate = callback_worker.check_dispatch

    async def _trial(*_a: Any, **_k: Any) -> DispatchDecision:
        return DispatchDecision(allowed=False, rule=trial_rule, reason="trial")

    monkeypatch.setattr(callback_worker, "check_dispatch", _trial)
    lead_a, _pa = await _lead(tenant_id, agent_id)
    run_a = await _start(tenant_id, follow_up_id, lead_a)
    await runner.drive(tenant_id, run_a)
    await _tick(tenant_id)
    assert (await _run_by_id(tenant_id, run_a))["end_reason"] == f"refused:{trial_rule}"

    monkeypatch.setattr(callback_worker, "check_dispatch", original_gate)

    async def _opted_out(*_a: Any, **_k: Any) -> str:
        raise recipient_opted_out_error()

    monkeypatch.setattr(callback_worker, "dispatch_call", _opted_out)
    lead_b, _pb = await _lead(tenant_id, agent_id)
    run_b = await _start(tenant_id, follow_up_id, lead_b)
    await runner.drive(tenant_id, run_b)
    await _tick(tenant_id)
    assert (await _run_by_id(tenant_id, run_b))["end_reason"] == "do_not_call"


async def test_a_call_step_with_no_agent_that_can_call_ends_the_run() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _call_follow_up(tenant_id, agent_id)
    lead_id, _p = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )
    await runner.drive(tenant_id, run_id)
    run = await _run(tenant_id, follow_up_id)
    assert (run["status"], run["end_reason"]) == ("stopped", "refused:agent_not_published")


async def test_pause_calls_off_the_booked_call_and_resume_books_it_again() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _call_follow_up(tenant_id, agent_id)
    lead_id, _p = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    await runner.drive(tenant_id, run_id)
    async with tenant_session(tenant_id) as session:
        await service.pause(session, follow_up_id)
    assert await _callbacks_of(tenant_id, run_id) == [
        (runner.callback_key(run_id, "s1", 0), "cancelled")
    ]
    assert await runner.drive(tenant_id, run_id) == 0, "a paused run waits where it is"
    async with tenant_session(tenant_id) as session:
        await service.resume(session, follow_up_id, tenant_id=tenant_id)
    await runner.drive(tenant_id, run_id)
    booked = await _callbacks_of(tenant_id, run_id)
    assert len(booked) == 2 and booked[1][1] == "scheduled"
    assert booked[1][0].startswith(runner.callback_key(run_id, "s1", 0) + ":")


# --- stopping ---------------------------------------------------------------------------


async def test_do_not_call_a_reply_and_won_lost_stop_runs() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(tenant_id, steps=[{"id": "s1", "kind": "wait", "days": 3}])
    quiet_id = await publish(
        tenant_id,
        steps=[{"id": "s1", "kind": "wait", "days": 3}],
        settings={"stop_on_reply": False, "stop_on_won_lost": False},
        name="Quiet",
    )
    lead_a, phone_a = await _lead(tenant_id, agent_id)
    lead_b, phone_b = await _lead(tenant_id, agent_id)
    lead_c, _pc = await _lead(tenant_id, agent_id)
    for lead in (lead_a, lead_b, lead_c):
        await _start(tenant_id, follow_up_id, lead)
        await _start(tenant_id, quiet_id, lead)

    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone_a, source="manual")
        assert await runner.stop_for_reply(session, phone_e164=phone_b) == 1
        await crm.set_lead_status(session, lead_c, status="won", actor="test")
        ends = dict(
            (
                await session.execute(
                    text(
                        "SELECT lead_id::text || ':' || follow_up_id::text, "
                        "coalesce(end_reason, status) FROM follow_up_runs"
                    )
                )
            ).all()
        )
    assert ends[f"{lead_a}:{follow_up_id}"] == "do_not_call"
    assert ends[f"{lead_a}:{quiet_id}"] == "do_not_call", "do-not-call is never optional"
    assert ends[f"{lead_b}:{follow_up_id}"] == "replied"
    assert ends[f"{lead_b}:{quiet_id}"] == "waiting"
    assert ends[f"{lead_c}:{follow_up_id}"] == "lead_won"
    assert ends[f"{lead_c}:{quiet_id}"] == "waiting"


async def test_a_run_that_marks_its_own_lead_won_goes_on() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(
        tenant_id,
        steps=[
            {"id": "s1", "kind": "set_status", "status": "won", "next": "s2"},
            {"id": "s2", "kind": "end", "goal": True},
        ],
    )
    other = await publish(tenant_id, steps=[{"id": "s1", "kind": "wait", "days": 1}], name="B")
    lead_id, _p = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    await _start(tenant_id, other, lead_id)
    await runner.drive(tenant_id, run_id)
    assert (await _run(tenant_id, follow_up_id))["end_reason"] == "goal"
    assert (await _run(tenant_id, other))["end_reason"] == "lead_won"


async def test_stopping_by_the_client_off_max_days_and_erasure() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(
        tenant_id, steps=[{"id": "s1", "kind": "wait", "days": 3}], settings={"max_days": 2}
    )
    leads = [await _lead(tenant_id, agent_id) for _ in range(4)]
    runs = [await _start(tenant_id, follow_up_id, lead) for lead, _p in leads]
    async with tenant_session(tenant_id) as session:
        await service.stop_run(session, follow_up_id, runs[0])
        with pytest.raises(Exception, match="follow_up_run_not_running"):
            await service.stop_run(session, follow_up_id, runs[0])
        with pytest.raises(Exception, match="not_found"):
            await service.stop_run(session, uuid.uuid4(), runs[1])
        await session.execute(
            text("UPDATE follow_up_runs SET started_at = now() - interval '3 days' WHERE id = :r"),
            {"r": runs[1]},
        )
        assert await runner.end_overdue(session) == 1
        assert await _erase_follow_up_runs(session, phone=leads[2][1]) == 1
    async with tenant_session(tenant_id) as session:
        await service.turn_off(session, follow_up_id)
        rows = dict(
            (
                await session.execute(
                    text("SELECT id, end_reason FROM follow_up_runs WHERE follow_up_id = :f"),
                    {"f": follow_up_id},
                )
            ).all()
        )
        erased = (
            await session.execute(
                text("SELECT phone_e164 FROM follow_up_runs WHERE id = :r"), {"r": runs[2]}
            )
        ).scalar_one()
    assert [rows[r] for r in runs] == [
        "stopped_by_client",
        "max_days",
        "lead_erased",
        "follow_up_off",
    ]
    assert erased.startswith("+91000000") and erased != leads[2][1]


async def test_a_run_whose_call_can_no_longer_come_leaves_the_step() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await _call_follow_up(tenant_id, agent_id)
    lead_id, _p = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    await runner.drive(tenant_id, run_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE scheduled_callbacks SET status = 'missed', settled_at = now() "
                "WHERE source_execution_id LIKE :k"
            ),
            {"k": f"follow-up:{run_id}:%"},
        )
        await session.execute(
            text("UPDATE follow_up_runs SET updated_at = now() - interval '2 hours' WHERE id = :r"),
            {"r": run_id},
        )
        assert await runner.settle_orphans(session, limit=10) == [run_id]
    done = await _run(tenant_id, follow_up_id)
    assert (done["status"], done["end_reason"]) == ("done", "finished")


async def test_a_whatsapp_reply_becomes_an_event_that_carries_no_text() -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {"from": "919812345678", "id": "wamid.1", "text": {"body": "STOP"}}
                            ],
                        },
                    }
                ],
            }
        ],
    }
    [event] = extract_events(payload)
    assert (event.kind, event.detail) == (
        "reply",
        {"from_e164": "+919812345678", "message_id": "wamid.1"},
    )
    assert "STOP" not in json.dumps(event.payload())


# --- the workers ----------------------------------------------------------------------


async def test_the_tick_queues_due_runs_and_the_call_ended_job_moves_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[tuple[str, dict[str, Any], str | None]] = []

    async def _enqueue(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        queued.append((job, payload, job_id))
        return job_id or job

    monkeypatch.setattr(worker, "enqueue", _enqueue)
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(tenant_id, steps=[{"id": "s1", "kind": "end"}])
    lead_id, _p = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)

    await worker.follow_up_tick({})
    mine = [q for q in queued if q[1].get("run_id") == str(run_id)]
    assert mine and mine[0][0] == worker.DRIVE_JOB
    assert await worker.drive_follow_up_run({"job_try": 1}, mine[0][1]) == "steps=1"
    assert (await _run(tenant_id, follow_up_id))["status"] == "done"

    call_follow_up = await _call_follow_up(tenant_id, agent_id)
    lead_b, phone_b = await _lead(tenant_id, agent_id)
    run_b = await _start(tenant_id, call_follow_up, lead_b)
    await runner.drive(tenant_id, run_b)
    await _tick(tenant_id)
    call_id = (await _run(tenant_id, call_follow_up))["waiting_call_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = 'completed' WHERE id = :c"), {"c": call_id}
        )
    result = await worker.follow_up_call_ended(
        {}, {"tenant_id": str(tenant_id), "call_id": str(call_id)}
    )
    assert result.startswith("moved=1")
    assert any(q[1].get("run_id") == str(run_b) for q in queued)
    del phone_b


async def test_the_lead_clock_forgets_a_settled_runs_number_and_leaves_an_open_one() -> None:
    """A run copies the number it calls; once its lead period has passed the copy goes,
    as the lead's own and the uploaded contact's do. The run's outcome stays."""
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(tenant_id, steps=[{"id": "s1", "kind": "end"}])
    settled = await _start(tenant_id, follow_up_id, (await _lead(tenant_id, agent_id))[0])
    still_open = await _start(tenant_id, follow_up_id, (await _lead(tenant_id, agent_id))[0])
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE follow_up_runs SET started_at = now() - interval '1200 days', "
                "status = CASE WHEN id = :s THEN 'done' ELSE status END, "
                "ended_at = CASE WHEN id = :s THEN now() ELSE ended_at END, "
                "end_reason = CASE WHEN id = :s THEN 'finished' ELSE end_reason END "
                "WHERE id IN (:s, :o)"
            ),
            {"s": settled, "o": still_open},
        )

    counts = await sweep_tenant(tenant_id)

    async with tenant_session(tenant_id) as session:
        rows = {
            r[0]: (r[1], r[2], r[3])
            for r in (
                await session.execute(
                    text(
                        "SELECT id, left(phone_e164, 9) = :anon, status, end_reason "
                        "FROM follow_up_runs WHERE id IN (:s, :o)"
                    ),
                    {"s": settled, "o": still_open, "anon": ANONYMIZED_PHONE[:9]},
                )
            ).all()
        }
    assert rows[settled] == (True, "done", "finished")
    assert rows[still_open][0] is False
    assert counts["follow_up_runs"] == 1


async def test_a_step_that_keeps_failing_ends_the_run_and_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arq import Retry

    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(tenant_id, steps=[{"id": "s1", "kind": "end"}])
    lead_id, _p = await _lead(tenant_id, agent_id)
    run_id = await _start(tenant_id, follow_up_id, lead_id)
    alarms: list[str] = []

    async def _broken(*_a: Any, **_k: Any) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker.runner, "drive", _broken)
    monkeypatch.setattr(worker, "alert", lambda _stage, code, **_k: alarms.append(code))
    payload = {"tenant_id": str(tenant_id), "run_id": str(run_id)}
    with pytest.raises(Retry):
        await worker.drive_follow_up_run({"job_try": 1}, payload)
    assert await worker.drive_follow_up_run({"job_try": 99}, payload) == "failed"
    assert alarms == ["follow_up_step_failed"]
    assert (await _run(tenant_id, follow_up_id))["end_reason"] == "step_failed"
