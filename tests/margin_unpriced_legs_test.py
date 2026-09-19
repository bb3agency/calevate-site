"""A margin that cannot see the legs it could not price reads better than it is.

`margin_for_tenant` sums `unit_cost_paid` over the `usage_events` rows that EXIST. On the
owned runtime a call's cost is five independently metered legs, and a leg nobody can
honestly price writes a `call_metering_refusals` row INSTEAD of a usage row — deliberately,
because a fabricated ₹0 on an append-only ledger is worse than a visible gap.

Nothing read that table. So a month with refused legs produced a `cost_inr` and a
`margin_pct` that were arithmetically correct over the rows present and MISSING MONEY, in
the flattering direction, on the number D-12 says G2 gates on. The live instance is the
RUNTIME leg: what a Pipecat Cloud active minute bills is UNKNOWN (OPERATIONS §2 gate 57),
so every Pipecat call refuses it until an operator attests an invoice.

A COUNT, NEVER A RUPEE ESTIMATE. The reason those legs have no row is that nobody can price
them; totalling them would be the fabrication the refusal exists instead of. Non-zero means
`cost_inr` is a floor and `margin_pct` a ceiling.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from apps.api.billing import service as billing
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.spend_attribution_test import _metered_call, _tenant


async def _refuse_a_leg(tenant_id: uuid.UUID, *, leg: str = "runtime") -> None:
    """One refusal against this tenant's most recent call, shaped as `settle_call` writes
    it. Written by hand because the producer lives in the worker API and this test is
    about the READER."""
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 1"),
                {"t": tenant_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO call_metering_refusals (id, tenant_id, call_id, leg, code, "
                "detail, remediation, created_at) VALUES (:i, :t, :c, :leg, "
                "'runtime_price_unknown', 'no attested active-minute price', "
                "'attest it in the ops console (OPERATIONS gate 57)', now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "leg": leg},
        )
        await session.commit()


async def test_a_month_with_no_refusals_reports_none() -> None:
    """The ordinary case, and the one that must not cry wolf: a complete month says so."""
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")

    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id, month=None)

    assert margin["legs_unpriced"] == 0


async def test_a_refused_leg_is_counted_beside_the_cost() -> None:
    """THE DEFECT, as it was: this month's cost was published as complete."""
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")
    await _refuse_a_leg(tenant_id)

    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id, month=None)

    assert margin["legs_unpriced"] == 1, (
        "the margin still reads as though every leg was priced; a founder pricing against "
        "it cannot tell a complete cost from a partial one"
    )
    # The cost itself is UNCHANGED — the count is published beside it, never folded into
    # it. A refusal has no rupee value by construction, and inventing one here would be
    # the fabrication the refusal was written instead of.
    assert Decimal(str(margin["cost_inr"])) > 0


async def test_the_count_is_not_a_rupee_estimate() -> None:
    """Two refusals on one call are two legs, not a doubled cost. Pins the type and the
    meaning together, because the tempting 'improvement' is to price them."""
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")
    async with tenant_session(tenant_id) as session:
        before = await billing.margin_for_tenant(session, tenant_id=tenant_id, month=None)
    await _refuse_a_leg(tenant_id, leg="runtime")
    await _refuse_a_leg(tenant_id, leg="tts")

    async with tenant_session(tenant_id) as session:
        after = await billing.margin_for_tenant(session, tenant_id=tenant_id, month=None)

    assert after["legs_unpriced"] == 2
    assert isinstance(after["legs_unpriced"], int)
    assert after["cost_inr"] == before["cost_inr"], "a refusal must not move the cost total"
