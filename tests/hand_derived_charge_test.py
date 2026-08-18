"""One month's charge, derived BY HAND and asserted at every intermediate.

`docs/evidence/deepdive-money2.md` §1 carries the same derivation in prose. This file is
the executable half: it drives the REAL meter over four calls, then checks each hop —
seconds, per-rung minutes, the paise allocation, the allowance split, each rung's price,
the counter, the invoice's lines, the subtotal, GST and the total — against numbers
worked out on paper rather than against whatever the code happens to produce.

That distinction is the whole point. Every other suite here asserts an INVARIANT (the
parts sum to the total, the panel agrees with the invoice), which stays green under a
uniformly wrong rule. This one asserts VALUES, so a change that keeps the system
self-consistent and moves what a client owes has somewhere to fail.

THE FIXTURE, and why each number is awkward:

    plan     monthly_fee ₹4,999.00 · included 100 min
             overage ₹8.50/min premium · ₹3.25/min value · setup fee ₹15,000.00
    calls    3847 s premium · 2913 s value · 611 s premium · 137 s with no voice

None of the durations divides by 60, the two rates differ, and the allowance is larger
than the premium rung — so the dearer-rung-first rule has to do real work, one rung
prices at zero minutes, and the unattributed call has to fold into value
(SURFACES §2b: a call we cannot prove got the premium voice is never charged the premium
rate).

Run: uv run pytest -q tests/hand_derived_charge_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from apps.api.billing.charges import issue_setup_fee
from apps.api.billing.gst import PlaceOfSupply, split_tax
from apps.api.billing.invoice import GST_RATE_PCT, build_invoice
from apps.api.billing.service import current_billing_month, tier_usage, usage_summary
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.spend_caps_test import _call_row, _snapshot, _spend_state, _tenant

_MONTHLY_FEE = Decimal("4999.0000")
_SETUP_FEE = Decimal("15000.0000")
_INCLUDED_MIN = 100
_PREMIUM_RATE = Decimal("8.5000")
_VALUE_RATE = Decimal("3.2500")

#: (configured voice tier or None, seconds, what the engine charged US).
_CALLS: tuple[tuple[str | None, int, str], ...] = (
    ("premium", 3847, "77.1900"),
    ("value", 2913, "58.2600"),
    ("premium", 611, "12.2200"),
    (None, 137, "2.7400"),
)

#: `spend_state.billed_inr` after each call, worked out by hand below.
_RUNNING_BILLED = (Decimal("0.00"), Decimal("41.18"), Decimal("74.26"), Decimal("81.67"))


async def _plan(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "overage_rate_value, setup_fee, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, :fee, :inc, :prem, :val, :setup, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "fee": _MONTHLY_FEE,
                "inc": _INCLUDED_MIN,
                "prem": _PREMIUM_RATE,
                "val": _VALUE_RATE,
                "setup": _SETUP_FEE,
            },
        )


async def _voice(tenant_id: UUID, agent_id: UUID, tier: str | None) -> None:
    from apps.api.agents.voices import CATALOG

    voice = None if tier is None else next(v.id for v in CATALOG if v.tier == tier)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v WHERE id = :i"),
            {"v": voice, "i": agent_id},
        )


async def _billed_month(label: str) -> tuple[UUID, UUID]:
    """Meter the four calls and issue the setup fee, asserting the counter after each."""
    tenant_id, agent_id, _ref = await _tenant(label)
    await _plan(tenant_id)
    now = datetime.now(UTC)
    for (tier, seconds, spend), expected in zip(_CALLS, _RUNNING_BILLED, strict=True):
        await _voice(tenant_id, agent_id, tier)
        call_id = await _call_row(tenant_id, agent_id)
        await _meter(tenant_id, call_id, _snapshot(seconds=seconds, spend=spend, ended=now))
        _m, _min, _sp, _cap, billed = await _spend_state(tenant_id)
        assert billed == expected, (
            f"after a {seconds}s {tier} call the month's bill should be ₹{expected}, not ₹{billed}"
        )
    async with tenant_session(tenant_id) as session:
        assert await issue_setup_fee(session, tenant_id=tenant_id, onboarded_at=now)
    return tenant_id, agent_id


async def test_the_minutes_and_the_rungs_are_the_hand_derived_ones() -> None:
    """Hop 1-3: raw seconds -> per-rung seconds -> per-rung minutes, allocated to paise.

    premium 3847 + 611 = 4458 s -> 74.300000 min
    value   2913 s              -> 48.550000 min
    unproven 137 s, metered AS value (`billable_tier` bills what it cannot prove
                                      at the cheaper rate)  -> 2.283333 min
    total   7508 s -> 125.133333 min, published as 125.13

    `allocate_paise` floors to 74.30 / 50.83 (= 48.55 + 2.283333 floored) and owes
    125.13 - 125.13 = 0 paise, so nothing is redistributed and the parts add exactly.
    """
    tenant_id, _agent_id = await _billed_month(f"hd{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        tiers = await tier_usage(session, tenant_id=tenant_id)
        summary = await usage_summary(session, tenant_id=tenant_id)

    assert tiers["minutes_premium"] == Decimal("74.30")
    assert tiers["minutes_value"] == Decimal("50.83")
    assert tiers["minutes_unattributed"] == Decimal("0.00"), (
        "the meter attributes every call it writes; the third bucket is for legacy rows"
    )
    assert summary["minutes_used"] == Decimal("125.13")
    assert (
        tiers["minutes_premium"] + tiers["minutes_value"] + tiers["minutes_unattributed"]
        == summary["minutes_used"]
    )
    assert summary["calls"] == 4


async def test_the_allowance_split_and_the_rung_prices_are_the_hand_derived_ones() -> None:
    """Hop 4-5: the 100-minute allowance, then each rung's money.

    overage = 125.13 - 100 = 25.13 min.
    The DEARER rung is premium (₹8.50 > ₹3.25) and it holds 74.30 min, all of which the
    allowance covers — so the premium overage is 0.00 and the remaining 25.70 min of
    allowance is spent on value, leaving 50.83 - 25.70 = 25.13 min of value overage.

        premium   0.00 min x ₹8.5000 = ₹0.0000     -> ₹0.00
        value    25.13 min x ₹3.2500 = ₹81.6725    -> ₹81.67   (ROUND_HALF_UP)
        total                                          ₹81.67
    """
    tenant_id, _agent_id = await _billed_month(f"ha{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)

    assert summary["included_minutes"] == _INCLUDED_MIN
    assert summary["overage_minutes"] == Decimal("25.13")
    assert summary["overage_minutes_premium"] == Decimal("0.00")
    assert summary["overage_minutes_value"] == Decimal("25.13")
    assert summary["overage_rate_inr"] == Decimal("8.50")
    assert summary["overage_rate_value_inr"] == Decimal("3.25")
    assert summary["overage_cost_inr"] == Decimal("81.67")
    # And the live counter the cap is judged against agrees with it to the paisa.
    assert summary["spend_used_inr"] == Decimal("81.67")


async def test_the_counter_is_the_sum_of_the_calls_own_increments() -> None:
    """Hop 6: the increments telescope.

    Each call is charged the difference it makes to the month's overage bill:

        after call 1   64.12 min           -> under the allowance -> ₹0.00   (+₹0.00)
        after call 2  112.67 min, 12.67 over -> 12.67 x ₹3.25 = ₹41.1775 -> ₹41.18 (+₹41.18)
        after call 3  122.85 min, 22.85 over -> 22.85 x ₹3.25 = ₹74.2625 -> ₹74.26 (+₹33.08)
        after call 4  125.13 min, 25.13 over -> 25.13 x ₹3.25 = ₹81.6725 -> ₹81.67 (+₹7.41)

    The running total is asserted after every call inside `_billed_month`; this pins the
    end state and that the MINUTE counter is the published figure and not a per-call
    quotient (D-253).
    """
    tenant_id, _agent_id = await _billed_month(f"hc{uuid.uuid4().hex[:6]}")
    month, minutes, spend, capped, billed = await _spend_state(tenant_id)

    assert billed == Decimal("81.67")
    assert minutes == Decimal("125.13"), "the counter is the ledger's own minute total"
    assert not capped, "this plan quotes no ceiling"
    # OUR supplier cost, which is a different fact and stays the engine's own number:
    # 77.19 + 58.26 + 12.22 + 2.74.
    assert spend == Decimal("150.4100")
    assert month == current_billing_month(), "the counter is stamped with the IST month"


async def test_the_invoice_is_the_hand_derived_document() -> None:
    """Hop 7-9: the lines, the subtotal, the tax and the total.

        Monthly plan fee                          1 x ₹4,999.00 = ₹4,999.00
        One-time onboarding & setup               1 x ₹15,000.00 = ₹15,000.00
        Extra calling minutes, value voice   25.13 x ₹3.25      = ₹81.67
        (no premium line: a rung with no minutes prints nothing)
        subtotal                                                 ₹20,080.67
        GST 18%  20,080.67 x 0.18 = 3,614.5206                -> ₹3,614.52
        total                                                    ₹23,695.19

    And the CGST/SGST halves of that tax, for an intra-State supply:
        CGST 20,080.67 x 0.09 = 1,807.2603 -> ₹1,807.26
        SGST 3,614.52 - 1,807.26           =  ₹1,807.26   (the second absorbs the
                                                           remainder, so the heads sum
                                                           to the printed total exactly)
    """
    tenant_id, _agent_id = await _billed_month(f"hi{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    priced = {item["description"]: item for item in invoice["line_items"]}
    assert priced["Monthly plan fee"]["amount_inr"] == Decimal("4999.00")
    assert priced["One-time onboarding & setup"]["amount_inr"] == Decimal("15000.00")
    overage_line = next(
        item for item in invoice["line_items"] if item["description"].startswith("Extra")
    )
    assert overage_line["description"] == (
        "Extra calling minutes, value voice (25.13 min at ₹3.25/min)"
    )
    assert overage_line["qty"] == Decimal("25.13")
    assert overage_line["unit_inr"] == Decimal("3.25")
    assert overage_line["amount_inr"] == Decimal("81.67")
    assert len(invoice["line_items"]) == 3, "a rung with no minutes must not print a ₹0.00 line"

    assert invoice["subtotal_inr"] == Decimal("20080.67")
    assert invoice["gst_inr"] == Decimal("3614.52")
    assert invoice["total_inr"] == Decimal("23695.19")

    # The heads, derived from the same subtotal for an intra-State supply. Asserted here
    # rather than read off the document because no deployment has a supplier GSTIN, so
    # `build_invoice` publishes one unclassified `GST` component (and says `proforma`).
    intrastate = PlaceOfSupply(
        state_code="36", state_name="Telangana", supply_type="intrastate", basis="fixture"
    )
    heads = split_tax(subtotal_inr=invoice["subtotal_inr"], rate_pct=GST_RATE_PCT, place=intrastate)
    assert [(head.label, head.amount_inr) for head in heads] == [
        ("CGST", Decimal("1807.26")),
        ("SGST", Decimal("1807.26")),
    ]
    assert sum((head.amount_inr for head in heads), Decimal("0.00")) == invoice["gst_inr"]
    assert invoice["document_type"] == "proforma", (
        "no deployment has a GST registration, and the document must say so"
    )
