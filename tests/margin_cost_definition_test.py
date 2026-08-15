"""There is ONE definition of "what this month cost us", and three readers share it.

THE DEFECT. `usage_events.unit_cost_paid` is summed as `SUM(qty * COALESCE(unit_cost_paid,
0))` — and that expression was spelled TWICE: once inside `_tier_totals`, which
`tier_usage` reports and `_spend_used` uses for a CLOSED month, and once inside
`margin_for_tenant`, in its own SQL string with its own predicate. Two spellings of one
money fact, agreeing today, with nothing in the tree able to notice the day one of them
grew a filter the other did not.

That is the D-103 shape aimed at the most expensive number the admin console shows. The
concrete failure it sets up: `_spend_used`'s docstring PROMISES that a closed month's
`spend_used` and the margin panel's `cost_inr` "agree by construction, because both are
the per-call `cost.total_inr` the pipeline metered". They did not agree by construction —
they agreed by coincidence, because two independently-written queries happened to say the
same thing. A client asking "why does my July spend say ₹3,600 and your margin sheet say
₹3,540" is a question nobody could answer from the code.

`margin_for_tenant` now sums `_tier_totals`' buckets. A GROUP BY partitions the rows, so
summing the groups IS the ungrouped total — same arithmetic, one place for a filter to be
added to.

WHAT THIS FILE PINS THAT A VALUE ASSERTION CANNOT. `billing_surfaces_test` already
asserts `margin["cost_inr"] == ₹3,600.00` on a single-row fixture, and that assertion
passes under BOTH spellings and under most divergences between them — one telephony row
carrying no tier is the case where every reading agrees. So the fixture here is
deliberately the awkward one: three rungs at once (premium, value, and the unattributed
rows written before tier attribution existed) plus a `tts_tier_correction` row, which is
`unit_type = 'other'` and is exactly the shape a re-added predicate would drop.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from apps.api.admin import service as admin_service
from apps.api.billing import service as billing
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text

#: One month, one tenant, one call per rung. The costs are chosen so no two buckets
#: share a total — a reader that dropped a bucket, or double-counted one, cannot land on
#: the right answer by luck.
_ROWS: tuple[tuple[str, str, str, str | None], ...] = (
    # (unit_type, qty, unit_cost_paid, meta.tts_tier)
    ("telephony_s", "600", "0.0100", "premium"),  # ₹6.00
    ("telephony_s", "300", "0.0200", "value"),  # ₹6.00 — same total, different rung
    ("telephony_s", "120", "0.0300", None),  # ₹3.60 — written before attribution
    ("stt_s", "600", "0.0083", "premium"),  # ₹4.98 — a non-telephony leg
    # A tier correction: `unit_type='other'`, qty 1, priced at the delta. The row a
    # predicate on `unit_type` would silently drop from one reader and not the other.
    ("other", "1", "-1.5000", "value"),  # minus ₹1.50
)

#: What the five rows above cost, in total. Stated rather than derived from the tuples, so
#: an edit to the fixture that changes the money has to be a deliberate edit to this line.
_TOTAL_COST_INR = Decimal("19.08")


async def _tenant_with_a_mixed_month() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Margin Clinic",
        slug=f"margin-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    agent_id = created["agent_id"]
    # ONE CALL PER ROW, since D-112 (`ux_usage_events_tenant_call_unit`). The fixture used
    # to hang all five rows off a single call, which meant three `telephony_s` rows for one
    # call — a shape `pipeline._meter` cannot produce and the ledger now refuses. The
    # month's arithmetic is what this file is about and it is unchanged; what changes is
    # that the fixture now depicts a month the product could actually generate. The
    # correction row keeps its own call for the same reason: `unit_type='other'` is
    # excluded from the index precisely so a compensating entry can repeat, and pinning it
    # to a call that also carries a metered row would test that exclusion by accident.
    call_ids = [uuid7() for _ in _ROWS]
    async with tenant_session(tenant_id) as session:
        for index, call_id in enumerate(call_ids):
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
        for call_id, (unit_type, qty, cost, tier) in zip(call_ids, _ROWS, strict=True):
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
                    "meta": None if tier is None else f'{{"tts_tier": "{tier}"}}',
                },
            )
    return tenant_id


async def test_the_margin_panel_and_the_tier_panel_cost_the_month_identically() -> None:
    """The equality that makes "one definition" a fact rather than a claim.

    `tier_usage` splits the month into three rungs; `margin_for_tenant` reports one
    figure. They are the same rows, so the three buckets must add to the one figure —
    including the correction row, which is neither telephony nor attributed to the rung
    it was originally billed on.
    """
    tenant_id = await _tenant_with_a_mixed_month()
    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
        tiers = await billing.tier_usage(session, tenant_id=tenant_id)

    buckets = tiers["cost_premium_inr"] + tiers["cost_value_inr"] + tiers["cost_unattributed_inr"]
    assert margin["cost_inr"] == buckets, (
        f"the margin panel says our cost was ₹{margin['cost_inr']} and the tier panel's "
        f"three rungs add to ₹{buckets}. Two readers of one ledger disagreeing about one "
        "month is the defect `margin_for_tenant` was rewritten to make unreachable — it "
        "must sum `_tier_totals`, never a second query of its own."
    )
    assert margin["cost_inr"] == _TOTAL_COST_INR, (
        "the fixture's own arithmetic moved; check the row costs before trusting the "
        "equality above, which two identically-wrong readers would also satisfy"
    )
    assert isinstance(margin["cost_inr"], Decimal), "money is never a float (hard rule 7)"


async def test_a_correction_row_counts_on_both_panels() -> None:
    """The row a re-added `unit_type` predicate drops. `record_tier_correction` writes
    `unit_type='other'` with qty 1 priced at the delta (hard rule 4 — the wrong row stays
    and a new one carries the difference), so a reader filtered to telephony would report
    a month as costing MORE than it did and quietly un-do every correction ever issued."""
    tenant_id = await _tenant_with_a_mixed_month()
    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
        uncorrected = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0) "
                    "FROM usage_events WHERE tenant_id = :t AND unit_type <> 'other'"
                ),
                {"t": tenant_id},
            )
        ).scalar()

    assert margin["cost_inr"] < Decimal(str(uncorrected)), (
        "the -1.50 rupee correction is not reaching the margin panel, so a client corrected on "
        "paper is still costed at the rate they were mis-billed on"
    )


async def test_a_closed_month_spends_what_the_margin_panel_says_it_cost() -> None:
    """`_spend_used`'s promise, asserted rather than trusted.

    For a CLOSED month `usage_summary.spend_used_inr` comes from `_tier_totals` and the
    margin panel's `cost_inr` now comes from the same call. A month with no rows is the
    honest way to reach the closed branch here without inventing a clock: both readers
    must agree it was ₹0.00, and — the part that matters — they must agree by reading one
    expression rather than two.
    """
    tenant_id = await _tenant_with_a_mixed_month()
    closed = "2026-01"
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id, month=closed)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id, month=closed)
    assert summary["spend_used_inr"] == margin["cost_inr"] == Decimal("0.00")
    assert summary["month"] == margin["month"] == closed
