"""A new lead and its Follow-up (D-940): the inline first call keeps every hardening of the
old plan, and the run it creates is what the rest of the journey hangs on."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.api.ingest import service as ingest_service
from apps.api.ingest.routes import SECRET_HEADER
from sqlalchemy import text
from tests.follow_ups_support import publish, set_new_lead_call
from tests.lead_ingest_test import SECRET, _client, _tenant_with_ingest


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime, timedelta

    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _post(webhook_id: Any, phone: str, name: str = "Kiran") -> dict[str, Any]:
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": phone, "full_name": name},
            headers={SECRET_HEADER: SECRET},
        )
    assert response.status_code == 202, response.text
    return dict(response.json())


async def _runs(tenant_id: UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT r.status, r.step_id, r.end_reason, r.waiting_call_id, r.wake_at, "
                        "f.starter FROM follow_up_runs r "
                        "JOIN follow_ups f ON f.id = r.follow_up_id "
                        "ORDER BY r.started_at"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


async def test_a_new_lead_is_called_at_once_and_its_run_waits_on_that_call() -> None:
    tenant_id, _agent, webhook_id = await _tenant_with_ingest()
    body = await _post(webhook_id, "9876508801")
    assert body["dispatched"] is True
    [run] = await _runs(UUID(str(tenant_id)))
    assert (run["status"], run["starter"], run["wake_at"]) == ("waiting", "call_new_leads", None)
    assert run["waiting_call_id"] is not None, "the run waits on the call it placed"


async def test_retries_from_call_new_leads_are_booked_with_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent, webhook_id = await _tenant_with_ingest()
    tid = UUID(str(tenant_id))
    await set_new_lead_call(tid, retries=2, retry_minutes=45)
    await _post(webhook_id, "9876508802")
    async with tenant_session(tid) as session:
        keys = (
            (
                await session.execute(
                    text(
                        "SELECT source_execution_id FROM scheduled_callbacks "
                        "WHERE status = 'scheduled'"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(keys) == 1 and keys[0].startswith("follow-up:") and keys[0].endswith(":s1:1")


async def test_with_call_new_leads_off_a_lead_is_kept_and_not_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent, webhook_id = await _tenant_with_ingest()
    tid = UUID(str(tenant_id))
    follow_up_id = await set_new_lead_call(tid)
    from apps.api.follow_ups import service

    async with tenant_session(tid) as session:
        await service.turn_off(session, follow_up_id)
    dialled: list[Any] = []

    async def _dial(*args: Any, **kwargs: Any) -> str:
        dialled.append(kwargs)
        return "x"

    monkeypatch.setattr(ingest_service, "dispatch_call", _dial)
    body = await _post(webhook_id, "9876508803")
    assert (body["dispatched"], body["blocked"]) == (False, ingest_service.NO_FOLLOW_UP_RULE)
    assert dialled == []
    async with tenant_session(tid) as session:
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar_one()
    assert leads == 1, "the lead is stored"


async def test_an_enquiry_sent_twice_is_called_once() -> None:
    tenant_id, _agent, webhook_id = await _tenant_with_ingest()
    first = await _post(webhook_id, "9876508804")
    second = await _post(webhook_id, "9876508804", name="Kiran again")
    assert first["dispatched"] is True
    assert (second["dispatched"], second["blocked"]) == (False, "follow_up_already_in")
    assert len(await _runs(UUID(str(tenant_id)))) == 1


async def test_a_follow_up_that_does_not_start_with_a_call_is_left_to_a_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent, webhook_id = await _tenant_with_ingest()
    tid = UUID(str(tenant_id))
    call_new_leads = await set_new_lead_call(tid)
    from apps.api.follow_ups import service

    async with tenant_session(tid) as session:
        await service.turn_off(session, call_new_leads)
    await publish(
        tid,
        trigger={"kind": "new_lead", "source_ids": [str(webhook_id)]},
        steps=[{"id": "s1", "kind": "wait", "minutes": 10}],
    )

    async def _never(*_a: Any, **_k: Any) -> str:
        raise AssertionError("no inline call")

    monkeypatch.setattr(ingest_service, "dispatch_call", _never)
    body = await _post(webhook_id, "9876508805")
    assert (body["dispatched"], body["blocked"]) == (False, None)
    [run] = await _runs(tid)
    assert run["status"] == "waiting" and run["wake_at"] is not None


async def test_a_person_refused_by_the_gate_ends_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.compliance.platform_dnc import platform_dnc_block_error

    tenant_id, _agent, webhook_id = await _tenant_with_ingest()
    tid = UUID(str(tenant_id))

    async def _refuse(*_a: Any, **_k: Any) -> str:
        raise platform_dnc_block_error()

    monkeypatch.setattr(ingest_service, "dispatch_call", _refuse)
    await _post(webhook_id, "9876508806")
    from apps.api.compliance.service import add_to_dnc

    async with tenant_session(tid) as session:
        await add_to_dnc(session, tenant_id=tid, phone_e164="+919876508807", source="manual")
    await _post(webhook_id, "9876508807")
    assert [(r["status"], r["end_reason"]) for r in await _runs(tid)] == [
        ("stopped", "do_not_call"),
        ("stopped", "do_not_call"),
    ]


async def test_a_released_held_lead_is_called_on_its_run_and_a_dropped_one_ends_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import time

    from apps.api.ingest import lead_policy
    from apps.api.ingest.lead_policy import LeadCallPlan
    from tests.ingest_deferred_window_test import _pin_gate_clock, _utc_at_ist

    _pin_gate_clock(monkeypatch, _utc_at_ist(2026, 10, 13, 19, 30))
    tenant_id, _agent, webhook_id = await _tenant_with_ingest()
    tid = UUID(str(tenant_id))
    async with tenant_session(tid) as session:
        await lead_policy.save_plan(
            session,
            tenant_id=tid,
            plan=LeadCallPlan(hours_start=time(10), hours_end=time(18), after_hours="hold"),
            user_id=None,
        )
    await _post(webhook_id, "9876508808")
    await _post(webhook_id, "9876508809")
    async with tenant_session(tid) as session:
        holds = (
            (await session.execute(text("SELECT id FROM lead_call_holds ORDER BY held_at")))
            .scalars()
            .all()
        )
        await lead_policy.release_held(session, tenant_id=tid, hold_id=holds[0], user_id=None)
        await lead_policy.drop_held(session, hold_id=holds[1], user_id=None)
        keys = (
            (await session.execute(text("SELECT source_execution_id FROM scheduled_callbacks")))
            .scalars()
            .all()
        )
    assert len(keys) == 1 and keys[0].startswith("follow-up:") and keys[0].endswith(":s1:0")
    runs = await _runs(tid)
    assert [(r["status"], r["end_reason"]) for r in runs] == [
        ("waiting", None),
        ("stopped", "stopped_by_client"),
    ]
