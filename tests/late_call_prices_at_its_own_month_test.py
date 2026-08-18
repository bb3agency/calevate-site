"""A call that settles late is priced by ITS OWN month's terms, not by today's.

`billing/plans.py::month_pricing_instant` is this repository's one answer to "which plan
prices this month": now while the month is open, the month's LAST instant once it is
closed — which is what makes a derived invoice re-renderable rather than re-priced by
whatever a plan change did since. `usage_summary` resolves the plan at that instant and
`billing/charges.py` quotes the setup fee at it.

THE DEFECT. `pipeline._meter` resolved the plan at `now()`. A call whose `ended_at` falls
in a CLOSED month therefore had its `spend_state.billed_inr` contribution priced by
today's terms while every panel and every invoice priced the same call by that month's.
That is not an exotic path — `engine.py` says the vendor may take minutes to price a
call, the reconciliation poller's window straddles midnight IST on the 1st, and the ARQ
retry ladder can cross it — and the disagreement is not a rounding one. Measured on this
tree before the fix, one ten-minute call ending on the last day of a month whose ₹2/min
terms were superseded by ₹20/min on the 1st:

    spend_state.billed_inr   ₹200.00   <- the counter, at today's rate
    usage_summary / invoice   ₹20.00   <- that month's own rate

THE FIX is one bind: `_meter` reads `plan_in_effect_sql` at `month_pricing_instant(month)`
rather than at `NOW_SQL`. The CEILING is deliberately still resolved at `now()` inside the
upsert's `caps` CTE, and the split is not an inconsistency — a RATE is a term of the month
being priced, a CAP is a question about whether this tenant may dial right now.

Run: uv run pytest -q tests/late_call_prices_at_its_own_month_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.api.billing.plans import ist_billing_month, ist_month_end
from apps.api.billing.service import usage_summary
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.spend_caps_test import _bill, _spend_state, _tenant

#: Far apart on purpose: a wrong plan is then an order of magnitude and not a paisa.
_CLOSED_MONTH_RATE = Decimal("2.0000")
_CURRENT_MONTH_RATE = Decimal("20.0000")


def _this_months_first_instant(now: datetime) -> datetime:
    """The instant the CURRENT IST billing month opened, as UTC.

    Derived from the PREVIOUS month's last instant through the one function that knows
    when an IST month ends, rather than by truncating a UTC date: a UTC month boundary is
    05:30 IST, so a truncated date would put the changeover — and with it the successor
    plan — in the wrong billing month for five and a half hours of every month.
    """
    year, month = int(ist_billing_month(now)[:4]), int(ist_billing_month(now)[5:])
    previous = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
    return ist_month_end(previous) + timedelta(microseconds=1)


async def _superseded_terms(tenant_id: UUID, changeover: datetime) -> None:
    """The commercial history this test is about: cheap terms that ENDED when the month
    turned, and dearer terms that started with it. Half-open, so the changeover instant
    belongs to exactly one of them (`billing/plans.py`)."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "concurrency_ceiling, effective_to, created_at, updated_at) "
                "VALUES (:i, :t, 0, 0, :rate, 10, :to, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "rate": _CLOSED_MONTH_RATE, "to": changeover},
        )
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "concurrency_ceiling, effective_from, created_at, updated_at) "
                "VALUES (:i, :t, 0, 0, :rate, 10, :fr, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "rate": _CURRENT_MONTH_RATE, "fr": changeover},
        )


async def test_the_counter_prices_a_late_call_by_the_month_it_belongs_to() -> None:
    tenant_id, agent_id, _ref = await _tenant(f"late{uuid.uuid4().hex[:6]}")
    now = datetime.now(UTC)
    changeover = _this_months_first_instant(now)
    await _superseded_terms(tenant_id, changeover)

    # Ten minutes, ending inside the CLOSED month, metered now.
    ended = changeover - timedelta(hours=6)
    closed_month = ist_billing_month(ended)
    assert closed_month != ist_billing_month(now), "the fixture must straddle the roll"
    await _bill(tenant_id, agent_id, seconds=600, spend="20.0000", ended=ended)

    month, _minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    assert month == closed_month, "the call is counted into the month it ended in"

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id, month=closed_month)

    expected = Decimal("10.00") * _CLOSED_MONTH_RATE
    assert summary["overage_rate_inr"] == _CLOSED_MONTH_RATE, (
        "the panel already priced the closed month by the terms that were in force"
    )
    assert summary["overage_cost_inr"] == expected
    assert billed == expected, (
        f"the counter priced this call at {billed} where the client's own panel and "
        f"their invoice price it at {expected}"
    )


async def test_an_open_months_call_is_still_priced_at_now() -> None:
    """The other half of `month_pricing_instant`, so the fix cannot be a blanket
    'price everything at the month end': terms dated to start LATER this month must not
    price today, which is the defect `billing/plans.py` exists for."""
    tenant_id, agent_id, _ref = await _tenant(f"open{uuid.uuid4().hex[:6]}")
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, 0, 0, :rate, 10, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "rate": _CLOSED_MONTH_RATE},
        )
        # Dearer terms that come into force LATER in this same month.
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "concurrency_ceiling, effective_from, created_at, updated_at) "
                "VALUES (:i, :t, 0, 0, :rate, 10, :fr, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "rate": _CURRENT_MONTH_RATE,
                "fr": ist_month_end(ist_billing_month(now)),
            },
        )

    await _bill(tenant_id, agent_id, seconds=600, spend="20.0000", ended=now)
    _month, _minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    assert billed == Decimal("10.00") * _CLOSED_MONTH_RATE, (
        "a plan dated to start later this month must not price a call made today"
    )
