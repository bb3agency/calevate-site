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
    supplier charge invisible on the panel and missing from the closed month's
    `spend_used`, while `spend_state.spend_used` — which takes `cost.total_inr` straight
    from the adapter — recorded the whole rupee. Two accounts of one call, which is the
    one thing two readers of the same money may never be.
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


async def test_a_correction_does_not_reach_rows_of_other_calls_or_of_no_call() -> None:
    """D-372's blast radius, which the window function decides and a comment cannot.

    `_CORRECTED_TIER_SQL` re-attributes a call's rows with `PARTITION BY call_id`, and
    two things about that partitioning are load-bearing rather than incidental:

    * **A `number_rental` row carries NO `call_id`.** Postgres groups every NULL into ONE
      partition, so if a correction row could ever land in it, one mis-tiered call would
      drag every un-called row in the tenant's month onto its rung. It cannot — a
      correction always names its call — but "cannot" is exactly the kind of claim that
      stops being true when somebody adds a second correction path, so it is asserted
      here rather than reasoned about in a comment.
    * **A correction is scoped to its own call.** An uncorrected premium call sitting
      beside a corrected one must keep its own rung.

    The fixture: one premium call corrected onto `value`, one premium call left alone,
    and one `number_rental` row attributed `premium`. Only the first may move.
    """
    tenant_id = await _tenant_with_rows(
        (
            ("telephony_s", "60", "0.0100", "premium"),
            ("telephony_s", "120", "0.0100", "premium"),
        )
    )
    async with tenant_session(tenant_id) as session:
        corrected_call = (
            await session.execute(
                text(
                    "SELECT call_id FROM usage_events WHERE tenant_id = :t AND qty = 60 "
                    "AND unit_type = 'telephony_s'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
        # A rental row: real money, no call, deliberately stamped `premium` so a leak
        # out of the NULL partition would be visible as money moving rungs.
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, NULL, "
                "'number_rental', 1, 5.0000, now(), CAST(:m AS jsonb), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "m": '{"tts_tier": "premium"}'},
        )
        await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=corrected_call,
            chars=10_000,
            billed_tier="premium",
            actual_tier="value",
            ref="ops-blast",
        )
        tiers = await billing.tier_usage(session, tenant_id=tenant_id)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)

    # 60 s moved to the value rung; 120 s stayed premium. Minutes, not money, because
    # the money also carries the correction's own -₹15.00 row.
    assert tiers["minutes_value"] == Decimal("1.00"), "the corrected call's minute moved"
    assert tiers["minutes_premium"] == Decimal("2.00"), (
        "the UNCORRECTED call kept its own rung — a correction is scoped to its call"
    )
    assert tiers["minutes_unattributed"] == Decimal("0.00")
    # The rental row is not a telephony row, so it contributes no minutes at all; what
    # would show a NULL-partition leak is its ₹5.00 appearing on the value rung.
    assert tiers["cost_premium_inr"] == Decimal("6.20"), (
        "₹5.00 rental + ₹1.20 for the uncorrected 120 s call — the rental row has no "
        "call_id, so no correction may reach it"
    )
    # And the partition still holds after all that (D-371).
    buckets = tiers["cost_premium_inr"] + tiers["cost_value_inr"] + tiers["cost_unattributed_inr"]
    assert buckets == margin["cost_inr"]


async def test_the_latest_correction_on_a_call_is_the_one_that_prices_it() -> None:
    """D-372, second correction. An operator who corrects a call to `value` and then
    finds a better vendor export saying `premium` must end on `premium`.

    `max(ARRAY[id::text, tier])` is what decides this, and it decides it by ID rather
    than by tier: uuid7's canonical text sorts in creation order, and every correction
    carries the CALL's `occurred_at` rather than its own, so the timestamp cannot order
    them. Spelled as a test because "the lexicographic maximum of the tier strings" is
    the reading a reviewer is most likely to have, and on this pair it gives `value` —
    the wrong answer, and the one that looks right.
    """
    tenant_id = await _tenant_with_rows((("telephony_s", "60", "0.0100", "premium"),))
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT call_id FROM usage_events WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
        await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            chars=10_000,
            billed_tier="premium",
            actual_tier="value",
            ref="ops-first",
        )
        await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            chars=10_000,
            billed_tier="value",
            actual_tier="premium",
            ref="ops-second",
        )
        tiers = await billing.tier_usage(session, tenant_id=tenant_id)

    assert tiers["minutes_premium"] == Decimal("1.00"), (
        "the SECOND correction is the one in force; picking the lexicographic maximum "
        "of ('premium', 'value') would leave this minute on the value rung"
    )
    assert tiers["minutes_value"] == Decimal("0.00")
