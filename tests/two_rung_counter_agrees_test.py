"""The live spend counter and the invoice price the same month the same way.

`tests/money_walk_test.py::test_the_clients_own_spend_figure_is_their_bill_and_not_our_
supplier_cost` states the promise in as many words — "the figure a client reads as 'used
so far' and the number they are invoiced must now AGREE" — and proves it on a plan with
ONE rate and no included minutes, where the two arithmetics cannot differ. This file
proves it on the plan shape that makes them differ, which is the shape D-36's ladder is
for: an included allowance plus a SECOND, cheaper overage rate.

THE DEFECT. Two functions price the same month and they used different rules.

* `usage_summary` (the invoice's own numbers — `build_invoice` prints
  `overage_rungs`'s output as its lines) spends the included allowance on the DEARER rung
  first. `split_overage` says why: the allocation decides the bill, and consuming the
  expensive minutes first leaves the cheap ones to be charged for, which is the client's
  favour.
* `_billed_for_this_call` (the counter the CAP is enforced against, and the counter
  `usage_summary` republishes as `spend_used_inr` while the month is open) spent the
  allowance in ARRIVAL order and priced each call's marginal minutes at that call's own
  rung.

Those agree whenever there is one rate — `sum of  (over(before+m) - over(before)) x rate` is
`max(0, total - included) x rate` — which is every plan in the database today, because
`plans.overage_rate_value` is an open founder decision and is NULL everywhere. They
disagree the moment one is quoted, and the disagreement is not a paisa: with the value
minutes arriving first the counter charges the premium rate for minutes the invoice
charges the value rate for.

What that costs is two things at once, both on surfaces a client looks at:

* `/c/<slug>/usage` shows "Extra usage total" (month-level) in one card and "Used so
  far … ₹X" (the counter) in the card below it — two rupee figures for one month, on one
  screen;
* the client's own spend cap is compared against the LARGER of the two, so their stop
  button stops their outbound calling before their bill justifies it.

THE FIX is that there is one rule: `priced_overage` is the whole month's pricing, and the
meter charges a call the DIFFERENCE it makes to that — computed from the per-rung SECONDS
the ledger holds, so the increments telescope to exactly the month total whatever order
calls meter in.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from apps.api.billing.service import usage_summary
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.spend_caps_test import _call_row, _snapshot, _spend_state, _tenant

#: A plan with BOTH rungs quoted and a real allowance — the shape the two arithmetics
#: disagree on. The rates are far apart so a wrong rung is a rupee difference and not a
#: rounding one.
_INCLUDED_MIN = 100
_PREMIUM_RATE = Decimal("8.0000")
_VALUE_RATE = Decimal("2.0000")


async def _two_rung_plan(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "overage_rate_value, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, 0.00, :inc, :prem, :val, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "inc": _INCLUDED_MIN,
                "prem": _PREMIUM_RATE,
                "val": _VALUE_RATE,
            },
        )


async def _voice(tenant_id: UUID, agent_id: UUID, voice_id: str | None) -> None:
    """Set the agent's configured voice — which is what `billable_tier` reads to decide
    the rung a call is metered on (`billing/rates.py`: the engine reports no synthesizer,
    so the configured voice IS the tier, stamped with its provenance)."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v WHERE id = :i"),
            {"v": voice_id, "i": agent_id},
        )


async def _clean(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM spend_state WHERE tenant_id = :t"), {"t": tenant_id}
        )


async def _premium_and_value_voices() -> tuple[str, str]:
    """One id from each rung of the live catalog, so this test cannot drift from it."""
    from apps.api.agents.voices import CATALOG

    premium = next(v.id for v in CATALOG if v.tier == "premium")
    value = next(v.id for v in CATALOG if v.tier == "value")
    return premium, value


async def test_the_counter_and_the_invoice_agree_when_the_cheap_minutes_arrive_first() -> None:
    """Value minutes first, then premium — the order that maximises the disagreement.

    60 value minutes then 150 premium, against a 100-minute allowance:

    * the INVOICE spends the allowance on the dearer rung, so 50 premium minutes at ₹8
      and 60 value minutes at ₹2 — ₹520.00;
    * the old counter spent the allowance in arrival order, so the first 60 value and
      the first 40 premium minutes were free and the remaining 110 premium minutes were
      charged at ₹8 — ₹880.00.

    ₹360 apart, on one client's screen, with the cap enforced against the larger.
    """
    tenant_id, agent_id, _ref = await _tenant(f"two_rung_{uuid.uuid4().hex[:6]}")
    await _two_rung_plan(tenant_id)
    premium_voice, value_voice = await _premium_and_value_voices()

    await _voice(tenant_id, agent_id, value_voice)
    for _ in range(2):
        call_id = await _call_row(tenant_id, agent_id)
        await _meter(
            tenant_id,
            call_id,
            _snapshot(seconds=1800, spend="1.0000", ended=datetime.now(UTC)),
        )
    await _voice(tenant_id, agent_id, premium_voice)
    for _ in range(3):
        call_id = await _call_row(tenant_id, agent_id)
        await _meter(
            tenant_id,
            call_id,
            _snapshot(seconds=3000, spend="1.0000", ended=datetime.now(UTC)),
        )

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
    _month, minutes, _spend, _capped, billed = await _spend_state(tenant_id)

    assert Decimal(str(minutes)) == Decimal("210"), "60 value + 150 premium minutes"
    assert summary["overage_cost_inr"] == Decimal("520.00"), (
        "50 premium minutes at ₹8 plus 60 value minutes at ₹2 — the allowance goes on "
        "the dearer rung (`split_overage`)"
    )
    assert Decimal(str(billed)) == summary["overage_cost_inr"], (
        "the counter the cap is enforced against must price the month the way the invoice does"
    )
    assert summary["spend_used_inr"] == summary["overage_cost_inr"], (
        "one month, two rupee figures on one client screen"
    )
    await _clean(tenant_id)


async def test_the_agreement_does_not_depend_on_the_order_calls_meter_in() -> None:
    """The same five calls in the other order reach the same month total.

    The increments telescope because each is the difference this call makes to the
    month's own pricing, so nothing about them is about when they arrived.
    """
    tenant_id, agent_id, _ref = await _tenant(f"two_rung_rev_{uuid.uuid4().hex[:6]}")
    await _two_rung_plan(tenant_id)
    premium_voice, value_voice = await _premium_and_value_voices()

    await _voice(tenant_id, agent_id, premium_voice)
    for _ in range(3):
        call_id = await _call_row(tenant_id, agent_id)
        await _meter(
            tenant_id,
            call_id,
            _snapshot(seconds=3000, spend="1.0000", ended=datetime.now(UTC)),
        )
    await _voice(tenant_id, agent_id, value_voice)
    for _ in range(2):
        call_id = await _call_row(tenant_id, agent_id)
        await _meter(
            tenant_id,
            call_id,
            _snapshot(seconds=1800, spend="1.0000", ended=datetime.now(UTC)),
        )

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
    _month, _minutes, _spend, _capped, billed = await _spend_state(tenant_id)

    assert summary["overage_cost_inr"] == Decimal("520.00")
    assert Decimal(str(billed)) == Decimal("520.00")
    await _clean(tenant_id)
