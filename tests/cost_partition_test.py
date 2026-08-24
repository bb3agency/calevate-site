"""Two ways "what this month cost us" stopped being one number (D-370, D-371).

`tests/margin_cost_definition_test.py` pins that the margin panel and the tier panel read
ONE expression. This file pins the two things that expression, and its presentation, each
got wrong about the same rupees — both reachable on ordinary traffic, both invisible on a
fixture whose amounts happen to be whole paise:

* **D-370 — a zero-`qty` row is a whole-leg row.** `unit_cost_paid` is a price PER UNIT OF
  `qty`, and a completed call the engine reports as zero-length has a real leg cost and
  genuinely zero seconds. `pipeline._unit_price` keeps the leg whole on the row in that
  case; every reader multiplied it by zero.
* **D-371 — the three rung costs are a PARTITION of `cost_inr`, not three roundings of
  it.** The admin margin route says so in its own docstring. `to_paise` per bucket does
  not deliver it.

The fixtures below are deliberately the awkward ones. A month of round rupees satisfies
both properties under the broken code as well as the fixed code, which is precisely why
neither defect was caught by the assertions that already existed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from apps.api.admin import service as admin_service
from apps.api.billing import service as billing
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text


async def _tenant_with_rows(
    rows: tuple[tuple[str, str, str, str | None], ...],
    *,
    one_call: bool = False,
) -> uuid.UUID:
    """A tenant whose billing month is exactly `rows` — (unit_type, qty, unit_cost, tier).

    `one_call` hangs them all off ONE call, which is what a single metered call looks
    like and what `ux_usage_events_tenant_call_unit` permits so long as the unit types
    differ. Otherwise each row gets its own call, the shape `margin_cost_definition_test`
    settled on after D-112.
    """
    created = await admin_service.create_organization(
        name="Cost Clinic",
        slug=f"cost-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    agent_id = created["agent_id"]
    shared = uuid7()
    call_ids = [shared] * len(rows) if one_call else [uuid7() for _ in rows]
    async with tenant_session(tenant_id) as session:
        for index, call_id in enumerate(dict.fromkeys(call_ids)):
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                    "'outbound', '+919876500002', 'completed', now(), now())"
                ),
                {
                    "i": call_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"exec_{uuid.uuid4().hex[:12]}_{index}",
                },
            )
        for call_id, (unit_type, qty, cost, tier) in zip(call_ids, rows, strict=True):
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, :u, "
                    ":qty, :cost, now(), CAST(:meta AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "u": unit_type,
                    "qty": Decimal(qty),
                    "cost": Decimal(cost),
                    "meta": None if tier is None else '{"tts_tier": "' + tier + '"}',
                },
            )
    return tenant_id


async def test_a_zero_duration_call_does_not_lose_its_leg_costs() -> None:
    """D-370. `qty` can legitimately be ZERO, and the row still holds real money.

    The three rows below are exactly what `pipeline._meter` writes for a zero-duration
    call the engine charged ₹1.0000 for — ₹0.20 network, ₹0.50 platform, ₹0.30
    synthesizer. `_unit_price` cannot divide the first two by a zero duration, so it keeps
    the leg cost whole on the row; `SUM(qty * unit_cost_paid)` then valued both at ₹0.00
    and the margin panel reported our cost for the call as ₹0.30. Seventy paise of a real
    supplier charge invisible on the one screen whose whole job is "is this client making
    us money", while `spend_state.spend_used` — which takes `cost.total_inr` straight from
    the adapter and never touches these rows — recorded the whole rupee. Two accounts of
    one call, which is the one thing two readers of the same money may never be.

    The CLIENT's own closed-month `spend_used` is deliberately NOT asserted here: since
    P1.3 it is `calling_revenue_inr`, priced off MINUTES at the client's rate rather than
    off `unit_cost_paid`, so it never read this number. The blast radius is
    `margin_for_tenant` and `tier_usage` — both checked below.
    """
    tenant_id = await _tenant_with_rows(
        (
            ("telephony_s", "0", "0.2000", "value"),
            ("platform_min", "0", "0.5000", "value"),
            ("tts_chars", "1", "0.3000", "value"),
        ),
        one_call=True,
    )
    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
        tiers = await billing.tier_usage(session, tenant_id=tenant_id)

    assert margin["cost_inr"] == Decimal("1.00"), (
        "a zero-duration call's duration-priced legs are being multiplied to nothing — "
        "the whole leg cost is on the row and the reader has to treat it as one"
    )
    assert tiers["cost_value_inr"] == Decimal("1.00"), "and on the rung it ran on"
    assert margin["minutes_used"] == Decimal("0.00"), (
        "and it must NOT gain a minute in the process — writing qty=1 on the WRITE side "
        "would bill the client a second that never happened, which is the worse error"
    )


async def test_the_three_rung_costs_are_a_partition_and_not_three_roundings() -> None:
    """D-371. The admin margin route nests these three under `cost_inr` and its docstring
    promises they "add up to `cost_inr` exactly — they are a partition of it, not a
    parallel estimate".

    `to_paise` on each bucket independently does not deliver that. `unit_cost_paid` is
    NUMERIC(12,4) and `qty` NUMERIC(14,4), so a bucket's sum of products carries four
    decimals as a matter of course: 601 s and 401 s at ₹0.0125/s are ₹7.5125 and ₹5.0125,
    published as ₹7.51 and ₹5.01 — adding to ₹12.52 beside a `cost_inr` of ₹12.53.
    `allocate_paise` (largest remainder) is the function this module already uses for
    exactly this, on the MINUTES sitting on the same card.
    """
    tenant_id = await _tenant_with_rows(
        (
            ("telephony_s", "601", "0.0125", "premium"),
            ("telephony_s", "401", "0.0125", "value"),
        )
    )
    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
        tiers = await billing.tier_usage(session, tenant_id=tenant_id)

    buckets = tiers["cost_premium_inr"] + tiers["cost_value_inr"] + tiers["cost_unattributed_inr"]
    assert margin["cost_inr"] == Decimal("12.53"), "the fixture's own arithmetic moved"
    assert buckets == margin["cost_inr"], (
        f"the three rungs add to {buckets} beside a cost of {margin['cost_inr']} — the "
        "admin route documents them as a partition, so they have to be ALLOCATED, not "
        "rounded one at a time"
    )
    # No bucket may drift more than a paisa from its own exact value either, which is
    # what largest-remainder buys over "put the whole remainder on the first one".
    assert tiers["cost_premium_inr"] in (Decimal("7.51"), Decimal("7.52"))
    assert tiers["cost_value_inr"] in (Decimal("5.01"), Decimal("5.02"))

