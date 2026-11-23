"""Free trial minutes do not spend a client's paid minute ceiling (D-1023): the counter the
outbound gate enforces (`spend_state.minutes_used`) counts the same period as the usage
panel's "minutes left" and the invoice (`service.counting_window`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.invoice import build_invoice
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.service import margin_for_tenant, usage_summary
from apps.api.billing.trials import (
    TRIAL_CONVERTED,
    TRIAL_ORIGIN_SIGNUP,
    TRIAL_STOPPED,
    end_trial,
    start_trial,
)
from apps.api.db.session import tenant_session
from apps.workers import trials as trial_sweep
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.conftest import mark_paid_for_tests
from tests.spend_caps_test import _OVERAGE_RATE, _call_row, _plan, _snapshot, _spend_state
from tests.spend_caps_test import _tenant as _cap_tenant

pytestmark = [pytest.mark.rls]


async def _metered(
    tenant_id: UUID, agent_id: UUID, *, seconds: int, started: datetime, ended: datetime
) -> UUID:
    call_id = await _call_row(tenant_id, agent_id)
    snapshot = _snapshot(seconds=seconds, spend="0.5000", ended=ended).model_copy(
        update={"started_at": started}
    )
    await _meter(tenant_id, call_id, snapshot)
    return call_id


async def test_a_gift_trial_mid_month_leaves_the_paid_calls_on_the_invoice() -> None:
    """A paying account given a trial mid-month (D-697's billing gift): the month's invoice
    and panel bill the paid calls before and after the trial and only those, and the live
    rupee counter agrees with them (D-1023)."""
    tenant_id, agent_id, _ = await _cap_tenant("giftinvoice")
    await _plan(tenant_id, included_min=0)
    await mark_paid_for_tests(tenant_id)
    now = datetime.now(UTC)
    m = timedelta(minutes=1)
    await _metered(tenant_id, agent_id, seconds=120, started=now - 60 * m, ended=now - 58 * m)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=1, actor_user_id=None, at=now - 40 * m)
    await _metered(tenant_id, agent_id, seconds=300, started=now - 35 * m, ended=now - 30 * m)
    async with tenant_session(tenant_id) as session:
        await end_trial(
            session,
            tenant_id=tenant_id,
            outcome=TRIAL_STOPPED,
            reason="Gift over.",
            at=now - 20 * m,
        )
    await _metered(tenant_id, agent_id, seconds=180, started=now - 5 * m, ended=now)

    async with tenant_session(tenant_id) as session:
        usage = await usage_summary(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id, month=ist_billing_month(now))
    assert usage["minutes_used"] == Decimal("5.00"), "two paid calls, the trial call excluded"
    assert usage["calls"] == 2
    assert invoice["usage"]["minutes_used"] == usage["minutes_used"]
    assert invoice["usage"]["calls"] == usage["calls"]
    assert usage["overage_cost_inr"] == Decimal("5.00") * _OVERAGE_RATE
    _month, minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    assert minutes == usage["minutes_used"]
    assert billed == usage["overage_cost_inr"] + usage["llm_surcharge_inr"]


async def test_the_sweep_keeps_paid_calls_after_the_end_date_in_the_rupee_ceiling() -> None:
    """A paid call between a trial's end date and the expiry sweep stays in `billed_inr`
    when the sweep records the end, and a cap flag the counters no longer justify is
    cleared there (D-1023)."""
    tenant_id, agent_id, _ = await _cap_tenant("sweepbilled")
    await _plan(tenant_id, included_min=0, cap_min=100)
    now = datetime.now(UTC)
    m = timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session, tenant_id=tenant_id, days=1, actor_user_id=None, at=now - 180 * m
        )
        await session.execute(
            text("UPDATE tenant_trials SET ends_at = :e WHERE tenant_id = :t"),
            {"e": now - 30 * m, "t": tenant_id},
        )
    await _metered(tenant_id, agent_id, seconds=600, started=now - 120 * m, ended=now - 110 * m)
    await _metered(tenant_id, agent_id, seconds=120, started=now - 10 * m, ended=now)
    # A row left over-counted and capped by trial minutes before the meter read the period.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE spend_state SET minutes_used = 250, capped = true WHERE tenant_id = :t"),
            {"t": tenant_id},
        )

    assert await trial_sweep._close_if_expired(tenant_id, now=datetime.now(UTC))
    _month, minutes, _spend, capped, billed = await _spend_state(tenant_id)
    assert minutes == Decimal("2.00")
    assert billed == Decimal("2.00") * _OVERAGE_RATE, "the paid call after the end date"
    assert capped is False, "2 of 100 minutes does not justify the flag"


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


async def test_a_running_trial_puts_no_extra_minutes_on_the_open_months_statement() -> None:
    """While a trial runs, the open month's statement bills no overage for the trial's free
    minutes: the panel says the period is on us, and the statement for the same month
    must not charge for those minutes."""
    tenant_id, agent_id, _ = await _cap_tenant("trialstatement")
    await _plan(tenant_id, included_min=0)
    now = datetime.now(UTC)
    m = timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=1, actor_user_id=None, at=now - 40 * m)
    await _metered(tenant_id, agent_id, seconds=300, started=now - 35 * m, ended=now - 30 * m)

    async with tenant_session(tenant_id) as session:
        usage = await usage_summary(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id, month=ist_billing_month(now))
    assert usage["trial"]["active"] is True
    assert usage["month_charges_inr"] == Decimal("0.00")
    calling = [
        item
        for item in invoice["line_items"]
        if str(item["description"]).startswith(("Extra calling minutes", "AI model upgrade"))
    ]
    assert calling == [], "trial minutes are not billed"
    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id)
    assert margin["revenue_inr"] == invoice["subtotal_inr"], "revenue is what is billed"


async def test_a_running_trial_charges_nothing_on_the_spend_page() -> None:
    """The spend page's period charge (and the per-call charges spread from it) is the
    statement's calling: nothing for the minutes a running trial absorbs."""
    from apps.api.billing.attribution import period_attribution

    tenant_id, agent_id, _ = await _cap_tenant("trialspend")
    await _plan(tenant_id, included_min=0)
    now = datetime.now(UTC)
    m = timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=1, actor_user_id=None, at=now - 40 * m)
    await _metered(tenant_id, agent_id, seconds=300, started=now - 35 * m, ended=now - 30 * m)

    async with tenant_session(tenant_id) as session:
        usage = await usage_summary(session, tenant_id=tenant_id)
        period = await period_attribution(session, tenant_id=tenant_id)
    assert usage["trial"]["active"] is True and usage["overage_cost_inr"] > 0
    assert period.period_charge_inr == Decimal("0.00")
    assert all(row.charged_inr == Decimal("0.00") for row in period.by_call)


async def test_a_gift_trial_waives_the_plan_fee_of_every_month_it_touches() -> None:
    """Founder, 23 Nov 2026: a gift trial waives the monthly plan fee. A trial that ended
    earlier this month still waives it, while the paid calls after it are billed; the
    statement, the panel and the margin's revenue agree. A month it did not touch keeps it."""
    tenant_id, agent_id, _ = await _cap_tenant("giftfee")
    await _plan(tenant_id, included_min=0, age_days=400)
    await mark_paid_for_tests(tenant_id)
    now = datetime.now(UTC)
    m = timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=1, actor_user_id=None, at=now - 40 * m)
        await end_trial(
            session,
            tenant_id=tenant_id,
            outcome=TRIAL_STOPPED,
            reason="Gift over.",
            at=now - 20 * m,
        )
    await _metered(tenant_id, agent_id, seconds=180, started=now - 5 * m, ended=now)

    month = ist_billing_month(now)
    async with tenant_session(tenant_id) as session:
        usage = await usage_summary(session, tenant_id=tenant_id, month=month)
        invoice = await build_invoice(session, tenant_id=tenant_id, month=month)
        margin = await margin_for_tenant(session, tenant_id=tenant_id, month=month)
    assert usage["monthly_fee_inr"] is None
    descriptions = [str(item["description"]) for item in invoice["line_items"]]
    assert "Monthly plan fee" not in descriptions
    assert usage["month_charges_inr"] == usage["overage_cost_inr"] > 0, "paid calls still billed"
    assert invoice["subtotal_inr"] == usage["month_charges_inr"]
    assert margin["revenue_inr"] == invoice["subtotal_inr"]

    # The account's birth trial is not a gift: a month only it touched keeps the fee.
    other, _agent, _ = await _cap_tenant("signupfee")
    await _plan(other, included_min=0, age_days=400)
    async with tenant_session(other) as session:
        await start_trial(
            session,
            tenant_id=other,
            days=1,
            actor_user_id=None,
            at=now - 40 * m,
            origin=TRIAL_ORIGIN_SIGNUP,
        )
        signup_usage = await usage_summary(session, tenant_id=other, month=month)
    assert signup_usage["monthly_fee_inr"] is not None

    # A month before the trial keeps its fee.
    year, mon = (int(part) for part in month.split("-"))
    earlier = f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"
    async with tenant_session(tenant_id) as session:
        before = await build_invoice(session, tenant_id=tenant_id, month=earlier)
    assert "Monthly plan fee" in [str(item["description"]) for item in before["line_items"]]
