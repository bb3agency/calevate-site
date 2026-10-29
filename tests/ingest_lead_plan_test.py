"""A new lead under the client's own calling plan (D-716), through the ingest route.

The plan only ever narrows when a lawful call is placed: a "hold for me" plan puts an
after-hours lead in the release queue, a wait books the call for later, and a plan that
opens after the platform window does is where a night lead's call lands. Nothing here
rings at once, and every booked call still meets `check_dispatch` when it falls due.
"""

from __future__ import annotations

import uuid
from datetime import time, timedelta
from typing import Any

import pytest
from apps.api.compliance.service import CALLING_HOURS_RULE
from apps.api.db.session import tenant_session
from apps.api.ingest import lead_policy
from apps.api.ingest.lead_policy import LeadCallPlan
from apps.api.ingest.service import HELD_FOR_RELEASE_RULE
from sqlalchemy import text
from tests.follow_ups_support import set_new_lead_call
from tests.ingest_deferred_window_test import (
    _callbacks,
    _no_dial,
    _pin_gate_clock,
    _post,
    _utc_at_ist,
)
from tests.lead_ingest_test import _tenant_with_ingest


async def _with_plan(plan: LeadCallPlan, **call: Any) -> tuple[uuid.UUID, Any]:
    """The account's hours from `plan`; the wait and retries on "Call new leads" (D-940)."""
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    async with tenant_session(tenant_id) as session:
        await lead_policy.save_plan(session, tenant_id=tenant_id, plan=plan, user_id=None)
    if call:
        await set_new_lead_call(uuid.UUID(str(tenant_id)), **call)
    return uuid.UUID(str(tenant_id)), webhook_id


async def _held(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM lead_call_holds WHERE status = 'held'")
                )
            ).scalar_one()
        )


async def test_an_after_hours_lead_on_a_hold_plan_waits_for_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 19:30 IST on a Tuesday: inside the platform's window, after the client's hours.
    _pin_gate_clock(monkeypatch, _utc_at_ist(2026, 10, 13, 19, 30))
    dialled = _no_dial(monkeypatch)
    tenant_id, webhook_id = await _with_plan(
        LeadCallPlan(hours_start=time(10), hours_end=time(18), after_hours="hold")
    )

    body = await _post(webhook_id, "9876507721")

    assert (body["dispatched"], body["blocked"]) == (False, HELD_FOR_RELEASE_RULE)
    assert dialled == []
    assert await _held(tenant_id) == 1
    assert await _callbacks(tenant_id, "+919876507721") == []


async def test_a_plan_that_waits_books_the_call_for_after_the_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _utc_at_ist(2026, 10, 13, 11)
    _pin_gate_clock(monkeypatch, now)
    dialled = _no_dial(monkeypatch)
    tenant_id, webhook_id = await _with_plan(LeadCallPlan(), wait_minutes=2, wait_seconds=120)

    body = await _post(webhook_id, "9876507722")

    assert body["blocked"] == "plan_wait"
    assert dialled == []
    [row] = await _callbacks(tenant_id, "+919876507722")
    assert row[0] == now + timedelta(seconds=120)
    assert await _held(tenant_id) == 0


async def test_a_night_lead_is_booked_for_the_plans_opening_not_the_platforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The platform would ring at 09:00; this client opens at 11:00, and the later of the
    two is the lawful time they asked for."""
    _pin_gate_clock(monkeypatch, _utc_at_ist(2026, 10, 13, 22))
    dialled = _no_dial(monkeypatch)
    tenant_id, webhook_id = await _with_plan(LeadCallPlan(hours_start=time(11)))

    body = await _post(webhook_id, "9876507723")

    assert body["blocked"] == CALLING_HOURS_RULE
    assert dialled == []
    [row] = await _callbacks(tenant_id, "+919876507723")
    assert row[0] == _utc_at_ist(2026, 10, 14, 11)
