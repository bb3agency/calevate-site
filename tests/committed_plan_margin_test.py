"""The committed-volume bundle margin guard (D-469).

A bundle plan sells minutes exactly as a prepaid pack does — `monthly_fee` buys
`included_min` of them, and `overage_rate` prices the rest — so it answers to the same
floor. The difference, and the reason this guard exists at all, is WHERE the two are set:
the pack catalogue is code a reviewer reads and CI scores, while these terms are typed into
an admin console during an onboarding call with neither.

What is pinned here, in the order it would cost:

1. **Below cost is below cost.** `SELF_SERVE_COST_FLOOR_INR_PER_MIN` is the line; a rate
   under it loses money on every minute the client uses, so heavy use makes it worse.
2. **The boundary cases are exact.** A rate AT the floor is not below it, and a margin
   exactly AT `MIN_GROSS_MARGIN` is not under target. Both are `Decimal` comparisons and
   both are the value an operator will eventually type.
3. **Unset is not zero.** A bundle with no `included_min` quotes no committed rate; an
   unset `overage_rate` quotes no overage. Judging either as ₹0.00 would refuse a perfectly
   ordinary retainer-only agreement as a below-cost sale.
"""

from __future__ import annotations

from decimal import Decimal

from apps.api.billing.rates import (
    MIN_GROSS_MARGIN,
    SELF_SERVE_COST_FLOOR_INR_PER_MIN,
    committed_plan_margin,
    gross_margin_ratio,
)

#: The retail rate whose margin is EXACTLY the target: `cost / (1 - target)`. At a ₹3.70
#: floor and a 20% target that is ₹4.625 — derived, never typed, so this file keeps testing
#: the boundary if either founder-approved constant moves.
AT_TARGET = SELF_SERVE_COST_FLOOR_INR_PER_MIN / (Decimal("1") - MIN_GROSS_MARGIN)


def test_gross_margin_is_the_fraction_of_a_retail_rupee_that_is_not_cost() -> None:
    # ₹5.00 sold at a ₹3.70 cost keeps ₹1.30, which is 26% of the rupee taken.
    assert gross_margin_ratio(rate=Decimal("5.00"), cost=Decimal("3.70")) == Decimal("0.26")
    # Exact Decimal, never a float: 0.26 here is the digits, not 0.26000000000000001.
    assert str(gross_margin_ratio(rate=Decimal("5.00"), cost=Decimal("3.70"))) == "0.26"


def test_a_committed_rate_is_the_fee_divided_by_the_minutes_it_buys() -> None:
    m = committed_plan_margin(monthly_fee=Decimal("10000.00"), included_min=2000, overage_rate=None)
    assert m.effective_committed_rate == Decimal("5.00")
    assert m.below_cost() == ()
    assert m.below_target() == ()
    # No overage was set, so there is nothing to judge — not a zero-rupee overage.
    assert m.overage is None


def test_a_bundle_priced_under_the_cost_floor_is_named_as_below_cost() -> None:
    # ₹7,000 for 2,000 minutes is ₹3.50/min — under the ₹3.70 floor, so every minute the
    # client uses loses money. This is the shape the write path refuses outright.
    m = committed_plan_margin(monthly_fee=Decimal("7000.00"), included_min=2000, overage_rate=None)
    assert m.effective_committed_rate == Decimal("3.50")
    assert m.below_cost() == ("committed",)
    # Disjoint: a below-cost rate is not ALSO reported as below-target, or the write path
    # would refuse and warn about the same number.
    assert m.below_target() == ()


def test_an_overage_rate_is_judged_on_its_own() -> None:
    # A healthy committed rate does not launder a below-cost overage: the client pays the
    # overage on exactly the minutes they use hardest.
    m = committed_plan_margin(
        monthly_fee=Decimal("10000.00"), included_min=2000, overage_rate=Decimal("2.0000")
    )
    assert m.below_cost() == ("overage",)


def test_both_rates_can_be_below_cost_and_both_are_named() -> None:
    m = committed_plan_margin(
        monthly_fee=Decimal("1000.00"), included_min=2000, overage_rate=Decimal("1.0000")
    )
    assert set(m.below_cost()) == {"committed", "overage"}


def test_a_rate_at_the_floor_is_not_below_it_but_is_under_target() -> None:
    """The boundary an operator eventually types. At cost exactly: no loss per minute, and
    no margin either — allowed, and said out loud."""
    fee = SELF_SERVE_COST_FLOOR_INR_PER_MIN * 1000
    m = committed_plan_margin(monthly_fee=fee, included_min=1000, overage_rate=None)
    assert m.effective_committed_rate == SELF_SERVE_COST_FLOOR_INR_PER_MIN
    assert m.below_cost() == ()
    assert m.below_target() == ("committed",)
    assert m.committed is not None and m.committed.margin == Decimal("0")


def test_a_margin_exactly_at_the_target_clears_it() -> None:
    """`< target`, not `<= target` — a bundle sold at exactly the founder-approved floor is
    a bundle sold AT the floor, and warning about it would cry wolf on the intended case."""
    m = committed_plan_margin(monthly_fee=AT_TARGET * 1000, included_min=1000, overage_rate=None)
    assert m.committed is not None
    assert m.committed.margin == MIN_GROSS_MARGIN
    assert m.below_cost() == ()
    assert m.below_target() == ()


def test_a_thin_but_profitable_rate_is_warned_not_refused() -> None:
    # ₹4.00/min: above the ₹3.70 cost, but only ~7.5% margin — a deliberate founder call,
    # so it is surfaced rather than blocked.
    m = committed_plan_margin(monthly_fee=Decimal("4000.00"), included_min=1000, overage_rate=None)
    assert m.below_cost() == ()
    assert m.below_target() == ("committed",)


def test_unset_fields_are_judged_by_nothing() -> None:
    """A retainer with no bundled minutes, or terms that state no price at all, must pass
    cleanly — `None` is 'not agreed', and reading it as ₹0.00 would refuse the ordinary
    cap-only row `billing/caps.py` mints for a client's own stop button."""
    empty = committed_plan_margin(monthly_fee=None, included_min=None, overage_rate=None)
    assert empty.effective_committed_rate is None
    assert empty.committed is None and empty.overage is None
    assert empty.below_cost() == () and empty.below_target() == ()

    # A fee with NO included minutes is a retainer, not a ₹∞/min bundle: there are no
    # bundled minutes to divide by, so no committed rate is quoted.
    retainer = committed_plan_margin(
        monthly_fee=Decimal("9999.00"), included_min=0, overage_rate=None
    )
    assert retainer.effective_committed_rate is None
    assert retainer.below_cost() == ()

    # And minutes with no fee cannot be divided into a rate either.
    no_fee = committed_plan_margin(monthly_fee=None, included_min=500, overage_rate=None)
    assert no_fee.effective_committed_rate is None


def test_a_free_minute_is_a_loss_with_no_margin_to_display() -> None:
    """₹0 is SET, unlike `None` — it is a real (and refusable) below-cost sale, but the
    margin ratio is undefined because the fraction has nothing to divide by."""
    m = committed_plan_margin(
        monthly_fee=Decimal("0.00"), included_min=1000, overage_rate=Decimal("0.0000")
    )
    assert set(m.below_cost()) == {"committed", "overage"}
    assert m.committed is not None and m.committed.margin is None
    assert m.overage is not None and m.overage.margin is None


def test_the_cost_basis_and_target_are_arguments_so_a_case_can_be_pinned() -> None:
    """The guard re-scores when the cost model moves, and a test can pin an exact case
    without reaching into module state — the pattern `pack_gross_margin_ratio` set."""
    m = committed_plan_margin(
        monthly_fee=Decimal("4000.00"),
        included_min=1000,
        overage_rate=None,
        cost=Decimal("2.00"),
        target=Decimal("0.10"),
    )
    # ₹4.00 against a ₹2.00 cost is 50% — comfortable under this (hypothetical) basis.
    assert m.below_cost() == () and m.below_target() == ()
