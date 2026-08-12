"""`plans.effective_from` / `effective_to` are the row's VALID TIME (DATA-MODEL §8).

The defect these tests were written against: both columns were declared, migrated and
read by NOTHING, while every reader resolved a tenant's plan as the newest row
(`ORDER BY created_at DESC LIMIT 1`). An operator who prepared next month's price today
changed today's bill — silently, and in the opposite direction from the one the column
name promises.

The properties pinned here, in the order they matter:

1. a plan dated to start in the FUTURE prices nothing today (the money bug);
2. a CLOSED month is priced by the plan that was in effect during it, not by whatever
   plan exists when the invoice is re-rendered — without which a derived invoice
   changes every time you look at it;
3. a SUPERSEDED plan (`effective_to` in the past) prices nothing;
4. a windowless plan behaves exactly as it did before effective dating existed, which
   is what makes this change re-price nobody on the day it lands;
5. the same instant governs the CAPS, so a future-dated ceiling does not bind today.

Money is NUMERIC INR throughout — no float appears in any assertion (hard rule 7).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import caps as billing_caps
from apps.api.billing import service as billing
from apps.api.billing.invoice import build_invoice
from apps.api.billing.plans import IST, month_pricing_instant, parse_billing_month
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _month_start_ist(month: str) -> datetime:
    """The first instant of an IST billing month, as UTC — the boundary an operator
    would date a price change to."""
    year, mon = parse_billing_month(month)
    return datetime(year, mon, 1, tzinfo=IST).astimezone(UTC)


def _previous_month(month: str) -> str:
    year, mon = parse_billing_month(month)
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


def _next_month(month: str) -> str:
    year, mon = parse_billing_month(month)
    return f"{year + 1}-01" if mon == 12 else f"{year}-{mon + 1:02d}"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Effective Dating Clinic",
        slug=f"eff-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _plan(session: AsyncSession, tenant_id: uuid.UUID, **columns: Any) -> uuid.UUID:
    """One `plans` row, with whatever columns the test cares about.

    Written as raw SQL like every other plan fixture in this suite: `plans` rows are
    created by operators by hand (nothing in the codebase writes one except the
    client-cap mint), so a fixture that went through an ORM helper would be testing a
    path production does not have.

    `clock_timestamp()`, NOT `now()`, and it is load-bearing here: `now()` is
    TRANSACTION-start time, so two rows a test writes in one `tenant_session` share a
    `created_at` to the microsecond and "the newest row" stops being a defined thing.
    The first draft of this file used `now()` and two of these tests passed against the
    UNFIXED code — the resolver was picking a row arbitrarily out of a tie and
    happening to be right. Production writes each plan row in its own transaction, so
    distinct stamps are the honest fixture. (`credit_ledger` takes the same instant for
    the same reason — `billing/service.py::record_entry`.)
    """
    plan_id = uuid7()
    names = ", ".join(columns)
    binds = ", ".join(f":{name}" for name in columns)
    await session.execute(
        text(
            f"INSERT INTO plans (id, tenant_id, {names}, created_at, updated_at) "
            f"VALUES (:id, :tid, {binds}, clock_timestamp(), clock_timestamp())"
        ),
        {"id": plan_id, "tid": tenant_id, **columns},
    )
    return plan_id


async def _usage(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    minutes: int,
    occurred_at: datetime | None = None,
) -> uuid.UUID:
    """One completed call worth `minutes` of telephony, stamped whenever the test says.

    `occurred_at` is what puts the usage in a given IST billing month — the same column
    `billing.service._IST_MONTH` buckets on.
    """
    call_id = uuid7()
    moment = occurred_at or datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
            "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
            "'+919876500001', 'completed', :at, :at)"
        ),
        {
            "i": call_id,
            "t": tenant_id,
            "a": agent_id,
            "e": f"exec_{uuid.uuid4().hex[:12]}",
            "at": moment,
        },
    )
    await session.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid, "
            "occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', :qty, :cost, :at, :at)"
        ),
        {
            "i": uuid7(),
            "t": tenant_id,
            "c": call_id,
            "qty": Decimal(minutes * 60),
            "cost": Decimal("0.5000"),
            "at": moment,
        },
    )
    return call_id


# --- 1. the money bug ---------------------------------------------------------


async def test_a_future_dated_plan_does_not_price_today() -> None:
    """THE defect. An operator prepares next month's price change today; today's bill
    must not move.

    Both rows are legitimate and both are the "newest" by turns — the future row is
    newer by `created_at`, which is exactly why the old rule picked it. The window is
    the only thing that distinguishes them, and it is the one the operator set.
    """
    tenant_id, agent_id = await _tenant()
    next_month_start = _month_start_ist(_next_month(billing.current_billing_month()))
    async with tenant_session(tenant_id) as session:
        await _plan(
            session,
            tenant_id,
            monthly_fee=Decimal("9999.00"),
            included_min=100,
            overage_rate=Decimal("8.0000"),
        )
        # Next month's terms, written in advance — the whole point of the columns.
        await _plan(
            session,
            tenant_id,
            monthly_fee=Decimal("19999.00"),
            included_min=50,
            overage_rate=Decimal("20.0000"),
            effective_from=next_month_start,
        )
        await _usage(session, tenant_id, agent_id, minutes=120)

        summary = await billing.usage_summary(session, tenant_id=tenant_id)

    assert summary["monthly_fee_inr"] == Decimal("9999.00"), (
        "a plan dated to start next month must not charge this month's retainer"
    )
    assert summary["included_minutes"] == 100, "nor move this month's included allowance"
    assert summary["overage_rate_inr"] == Decimal("8.00"), "nor this month's overage rate"
    # 120 used - 100 included = 20 overage minutes at THIS month's ₹8, not next's ₹20.
    assert summary["overage_cost_inr"] == Decimal("160.00")


async def test_the_invoice_agrees_with_the_panel_when_a_future_plan_exists() -> None:
    """The invoice is derived from `usage_summary` and must stay that way: one
    computation, two presentations. A future-dated plan that moved one and not the
    other would put the client's panel and their bill in different worlds."""
    tenant_id, agent_id = await _tenant()
    next_start = _month_start_ist(_next_month(billing.current_billing_month()))
    async with tenant_session(tenant_id) as session:
        await _plan(
            session,
            tenant_id,
            monthly_fee=Decimal("5000.00"),
            included_min=10,
            overage_rate=Decimal("4.0000"),
        )
        await _plan(
            session,
            tenant_id,
            monthly_fee=Decimal("50000.00"),
            included_min=0,
            overage_rate=Decimal("40.0000"),
            effective_from=next_start,
        )
        await _usage(session, tenant_id, agent_id, minutes=20)

        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id)

    lines = invoice["line_items"]
    fee_lines = [line for line in lines if line["description"] == "Monthly plan fee"]
    assert fee_lines[0]["amount_inr"] == Decimal("5000.00")
    overage = [line for line in lines if "Extra calling minutes" in str(line["description"])]
    assert overage[0]["amount_inr"] == summary["overage_cost_inr"] == Decimal("40.00")
    assert invoice["subtotal_inr"] == Decimal("5040.00")


# --- 2. a closed month is priced by the plan that ran in it -------------------


async def test_a_closed_month_is_priced_by_the_plan_that_was_in_effect_then() -> None:
    """An invoice for July prices July.

    This is the half of the defect that bites even with no future dating at all: the
    invoice is a DERIVED statement (`billing/invoice.py` persists nothing), so under
    the newest-row rule a plan change in August silently re-priced every re-render of
    July's bill. A statement that changes when you look at it twice is not a statement.
    """
    tenant_id, agent_id = await _tenant()
    this_month = billing.current_billing_month()
    last_month = _previous_month(this_month)
    boundary = _month_start_ist(this_month)

    async with tenant_session(tenant_id) as session:
        await _plan(
            session,
            tenant_id,
            monthly_fee=Decimal("1000.00"),
            included_min=0,
            overage_rate=Decimal("5.0000"),
            effective_to=boundary,
        )
        # `effective_from` == the old row's `effective_to`: the half-open window makes
        # that the correct gesture, with neither a gap nor an overlap at the boundary.
        await _plan(
            session,
            tenant_id,
            monthly_fee=Decimal("2000.00"),
            included_min=0,
            overage_rate=Decimal("9.0000"),
            effective_from=boundary,
        )
        await _usage(
            session, tenant_id, agent_id, minutes=10, occurred_at=boundary - timedelta(days=2)
        )
        await _usage(session, tenant_id, agent_id, minutes=10)

        july = await billing.usage_summary(session, tenant_id=tenant_id, month=last_month)
        august = await billing.usage_summary(session, tenant_id=tenant_id, month=this_month)

    assert july["overage_rate_inr"] == Decimal("5.00"), "the closed month keeps its own rate"
    assert july["monthly_fee_inr"] == Decimal("1000.00")
    assert july["overage_cost_inr"] == Decimal("50.00")
    assert august["overage_rate_inr"] == Decimal("9.00"), "and the current month uses the new one"
    assert august["monthly_fee_inr"] == Decimal("2000.00")
    assert august["overage_cost_inr"] == Decimal("90.00")


async def test_a_superseded_plan_prices_nothing_and_says_so_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A plan whose window has CLOSED with no successor leaves the tenant unpriced —
    the same state as no plan row, which is what every cap reader already treats as
    "no constraint".

    That is a real cost of effective dating and it is accepted deliberately (see
    `billing/plans.py`): falling back to the expired row would charge terms whose end
    date we were explicitly told. What it must not be is SILENT, so the operator gets a
    log line naming the tenant and the remedy.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _plan(
            session,
            tenant_id,
            monthly_fee=Decimal("7000.00"),
            included_min=0,
            overage_rate=Decimal("6.0000"),
            hard_cap_min=10,
            effective_to=datetime.now(UTC) - timedelta(days=1),
        )
        await _usage(session, tenant_id, agent_id, minutes=30)
        with caplog.at_level("WARNING"):
            summary = await billing.usage_summary(session, tenant_id=tenant_id)
        caps = await billing_caps.read_caps(session, tenant_id=tenant_id)

    assert summary["monthly_fee_inr"] is None, "an ended plan does not keep charging a retainer"
    assert summary["overage_cost_inr"] == Decimal("0.00")
    assert caps.effective_cap_min is None, "nor keep enforcing a ceiling it no longer states"
    assert "plan_window_leaves_tenant_unpriced" in caplog.text


# --- 3. nothing changes for the plans that exist today ------------------------


async def test_windowless_plans_still_resolve_newest_first() -> None:
    """Every `plans` row in the database today has both bounds NULL, and every one of
    them is "in effect" at every instant. The tie-break has to be the rule this repo
    already had — newest `created_at` — or this change re-prices live clients on the
    day it lands."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _plan(session, tenant_id, monthly_fee=Decimal("100.00"), overage_rate=Decimal("1.0"))
        await _plan(session, tenant_id, monthly_fee=Decimal("200.00"), overage_rate=Decimal("2.0"))
        await _usage(session, tenant_id, agent_id, minutes=5)
        summary = await billing.usage_summary(session, tenant_id=tenant_id)

    assert summary["monthly_fee_inr"] == Decimal("200.00"), "newest windowless row still wins"


async def test_a_dated_row_beats_a_windowless_one_once_it_is_in_effect() -> None:
    """The ordinary operator gesture is to leave the old open-ended row alone and
    INSERT the new terms with an `effective_from`. That has to work in ONE statement,
    including when the correction to the old row is written afterwards — so valid-time
    start, not insertion order, decides."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _plan(
            session,
            tenant_id,
            monthly_fee=Decimal("300.00"),
            overage_rate=Decimal("3.0"),
            effective_from=datetime.now(UTC) - timedelta(days=1),
        )
        # Written LATER, so it is the newest row — and it is undated, meaning "since
        # forever", which is strictly older in valid time than yesterday.
        await _plan(session, tenant_id, monthly_fee=Decimal("100.00"), overage_rate=Decimal("1.0"))
        await _usage(session, tenant_id, agent_id, minutes=5)
        summary = await billing.usage_summary(session, tenant_id=tenant_id)

    assert summary["monthly_fee_inr"] == Decimal("300.00")


# --- 4. the caps read the same window ----------------------------------------


async def test_a_future_dated_ceiling_does_not_cap_today() -> None:
    """Caps price the PRESENT, so their instant is now — not the month's end and not
    the newest row. A ceiling an operator has agreed for next month must not stop
    today's dialling, and today's ceiling must still bind."""
    tenant_id, _ = await _tenant()
    next_start = datetime.now(UTC) + timedelta(days=40)
    async with tenant_session(tenant_id) as session:
        await _plan(session, tenant_id, hard_cap_min=500, hard_cap_spend=Decimal("5000.00"))
        await _plan(
            session,
            tenant_id,
            hard_cap_min=1,
            hard_cap_spend=Decimal("1.00"),
            effective_from=next_start,
        )
        caps = await billing_caps.read_caps(session, tenant_id=tenant_id)

    assert caps.admin_cap_min == 500, "next month's ceiling is not this month's ceiling"
    assert caps.effective_cap_spend == Decimal("5000.00")


# --- 5. the instant itself ----------------------------------------------------


def test_the_pricing_instant_is_clamped_into_the_month() -> None:
    """A closed month prices at its last instant, the current month prices at now, and
    a future month prices at its own start. The first is what makes a re-rendered
    invoice deterministic; the second is what stops a mid-month dated row pricing
    today."""
    now = datetime(2026, 8, 12, 6, 0, tzinfo=UTC)  # 11:30 IST on the 12th

    closed = month_pricing_instant("2026-07", now=now)
    assert closed == datetime(2026, 8, 1, tzinfo=IST).astimezone(UTC) - timedelta(microseconds=1)

    assert month_pricing_instant("2026-08", now=now) == now

    future = month_pricing_instant("2026-12", now=now)
    assert future == datetime(2026, 12, 1, tzinfo=IST).astimezone(UTC)


def test_a_month_that_is_not_a_month_is_refused() -> None:
    """`month` is an unvalidated query parameter on three routes. It now selects the
    PLAN that prices the answer, so a value we cannot parse cannot be waved through to
    a ₹0.00 statement."""
    for bad in ("july", "2026-13", "2026-7", "2026", ""):
        with pytest.raises(ProblemError) as raised:
            parse_billing_month(bad)
        assert raised.value.status == 422
        assert raised.value.code == "invalid_billing_month"
