"""Free trial minutes do not spend a client's paid minute ceiling (D-1023): the counter the
outbound gate enforces (`spend_state.minutes_used`) counts the same period as the usage
panel's "minutes left" and the invoice (`service.counting_window`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.service import usage_summary
from apps.api.billing.trials import TRIAL_CONVERTED, end_trial, start_trial
from apps.api.db.session import tenant_session
from apps.workers import trials as trial_sweep
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.spend_caps_test import _call_row, _plan, _snapshot, _spend_state
from tests.spend_caps_test import _tenant as _cap_tenant

pytestmark = [pytest.mark.rls]


async def _panel(tenant_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await usage_summary(session, tenant_id=tenant_id)


async def test_trial_minutes_leave_the_paid_minute_ceiling_whole() -> None:
    """150 trial minutes, a 500-minute ceiling, 200 paid minutes: 300 left on the panel
    and at the gate, before and after the daily sweep records the trial's end."""
    tenant_id, agent_id, _ = await _cap_tenant("trialmincap")
    await _plan(tenant_id, cap_min=500, included_min=1000)
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session, tenant_id=tenant_id, days=1, actor_user_id=None, at=now - timedelta(hours=3)
        )
        # The trial ran to its end date ten minutes ago and the sweep has not run yet.
        await session.execute(
            text("UPDATE tenant_trials SET ends_at = :e WHERE tenant_id = :t"),
            {"e": now - timedelta(minutes=10), "t": tenant_id},
        )
    trial_call = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        trial_call,
        _snapshot(seconds=150 * 60, spend="1.0000", ended=now - timedelta(minutes=25)).model_copy(
            update={"started_at": now - timedelta(minutes=175)}
        ),
    )
    paid_call = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        paid_call,
        _snapshot(seconds=200 * 60, spend="1.0000", ended=now).model_copy(
            update={"started_at": now - timedelta(minutes=5)}
        ),
    )

    _month, minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    usage = await _panel(tenant_id)
    assert usage["minutes_used"] == Decimal("200.00")
    assert usage["minutes_left"] == 300
    assert minutes == usage["minutes_used"], "the gate counts the panel's minutes"
    assert capped is False

    assert await trial_sweep._close_if_expired(tenant_id, now=datetime.now(UTC))
    _month, minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    usage = await _panel(tenant_id)
    assert usage["minutes_left"] == 300
    assert minutes == Decimal("200.00"), "the boundary keeps the paid calls already placed"
    assert capped is False


async def test_a_trial_call_settling_after_the_trial_adds_no_paid_minutes() -> None:
    tenant_id, agent_id, _ = await _cap_tenant("triallatecap")
    await _plan(tenant_id, cap_min=500, included_min=1000)
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session, tenant_id=tenant_id, days=7, actor_user_id=None, at=now - timedelta(hours=1)
        )
        await end_trial(
            session,
            tenant_id=tenant_id,
            outcome=TRIAL_CONVERTED,
            reason="paid",
            at=now - timedelta(minutes=20),
        )
    paid_call = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        paid_call,
        _snapshot(seconds=180, spend="0.5000", ended=now).model_copy(
            update={"started_at": now - timedelta(minutes=3)}
        ),
    )
    # Spoken inside the trial, settled by a retry after it ended.
    late_call = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        late_call,
        _snapshot(seconds=600, spend="0.5000", ended=now - timedelta(minutes=10)).model_copy(
            update={"started_at": now - timedelta(minutes=40)}
        ),
    )

    _month, minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    usage = await _panel(tenant_id)
    assert usage["minutes_used"] == Decimal("3.00")
    assert minutes == usage["minutes_used"]
    assert billed == Decimal("0.00")


async def test_a_trial_call_with_no_engine_times_is_dated_by_its_call_row() -> None:
    """No `started_at` and no `ended_at` on the snapshot: the trial decision asks about the
    call row's own start, never the settlement clock (D-1013)."""
    tenant_id, agent_id, _ = await _cap_tenant("trialnotimes")
    await _plan(tenant_id, cap_min=500, included_min=1000)
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session, tenant_id=tenant_id, days=7, actor_user_id=None, at=now - timedelta(hours=1)
        )
    call_id = await _call_row(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET created_at = :c WHERE id = :i"),
            {"c": now - timedelta(minutes=30), "i": call_id},
        )
        await end_trial(
            session,
            tenant_id=tenant_id,
            outcome=TRIAL_CONVERTED,
            reason="paid",
            at=now - timedelta(minutes=5),
        )
    snapshot = _snapshot(seconds=120, spend="0.5000", ended=now).model_copy(
        update={"ended_at": None, "started_at": None}
    )
    await _meter(tenant_id, call_id, snapshot)

    async with tenant_session(tenant_id) as session:
        covered = (
            await session.execute(
                text(
                    "SELECT bool_and((meta ->> 'trial_covered')::boolean) FROM usage_events "
                    "WHERE call_id = :c AND meta ->> 'trial_covered' IS NOT NULL"
                ),
                {"c": call_id},
            )
        ).scalar()
    assert covered is True, "the call began inside the trial, by its call row"
    _month, minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    assert billed == Decimal("0.00")
    assert minutes == Decimal("0.00")
