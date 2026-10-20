"""A margin that cannot see the legs it could not price reads better than it is (D-840).

`margin_for_tenant` sums `unit_cost_paid` over the month's usage rows, and a row the meter
could not price (an unattested rate or fee) carries a NULL cost that the sum counts as ₹0.
`legs_unpriced` counts those rows beside the figure.

A COUNT, NEVER A RUPEE ESTIMATE: non-zero means `cost_inr` is a floor and `margin_pct` a
ceiling.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from apps.api.billing import service as billing
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.spend_attribution_test import _metered_call, _tenant


async def _unpriced_minute(tenant_id: uuid.UUID) -> None:
    """One minute row with no cost against the tenant's newest call, as `pipeline._meter`
    writes a ThinnestAI minute whose rate or fee is unattested."""
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 1"),
                {"t": tenant_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'platform_min', 1, NULL, now(), CAST(:m AS jsonb), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "m": '{"engine_rate_key": "premium"}'},
        )
        await session.commit()


async def test_a_month_with_every_row_priced_reports_none() -> None:
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")

    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id, month=None)

    assert margin["legs_unpriced"] == 0


async def test_an_unpriced_row_is_counted_and_not_priced_at_zero() -> None:
    """THE DEFECT: the count read `call_metering_refusals`, which nothing writes since D-763,
    so an unpriced minute was invisible and the month read as complete."""
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")
    async with tenant_session(tenant_id) as session:
        before = await billing.margin_for_tenant(session, tenant_id=tenant_id, month=None)
    await _unpriced_minute(tenant_id)

    async with tenant_session(tenant_id) as session:
        after = await billing.margin_for_tenant(session, tenant_id=tenant_id, month=None)

    assert after["legs_unpriced"] == 1
    assert isinstance(after["legs_unpriced"], int)
    # Published beside the cost, never folded into it.
    assert after["cost_inr"] == before["cost_inr"]
    assert Decimal(str(after["cost_inr"])) > 0
