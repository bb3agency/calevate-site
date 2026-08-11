"""`to_paise` does not return paise, and something has to say so out loud.

It quantizes a rupee amount to two decimal places and returns RUPEES:
`to_paise(Decimal("7.125"))` is `Decimal("7.13")`, not `713`. Every money field in
every billing response goes through it, which is exactly why the name matters — the
top-up guard compares its result against `MIN_TOPUP_INR = 100.00` and
`MAX_TOPUP_INR = 100000.00`, and that comparison is correct only because the function
does not do what its name says.

A well-meaning rename or "fix" that made it return an integer count of paise would
turn a ₹100 minimum into a ₹1 minimum and a ₹100,000 maximum into ₹1,000 — silently,
with every test that only checks rounding still passing. These tests are the tripwire.

They also pin the two properties the money path actually depends on (hard rule 7):
the result is a Decimal, never a float, and rounding is half-up rather than the
process-global default, because an Indian tax invoice is checked for ₹18.05 where
banker's rounding gives ₹18.04.
"""

from __future__ import annotations

import decimal
from decimal import Decimal

from apps.api.billing.payment_routes import MAX_TOPUP_INR, MIN_TOPUP_INR
from apps.api.billing.service import to_paise


def test_to_paise_returns_rupees_not_paise() -> None:
    """The name is a lie and the behaviour is the contract."""
    assert to_paise(Decimal("7.125")) == Decimal("7.13")
    assert to_paise(Decimal("100.00")) == Decimal("100.00")
    assert to_paise(Decimal("1")) == Decimal("1.00")
    # The failure this file exists to prevent: if this ever equals 10000, the top-up
    # bounds below have silently become a hundred times wrong.
    assert to_paise(Decimal("100.00")) != Decimal("10000")


def test_the_topup_bounds_are_compared_against_the_same_scale() -> None:
    """`create_topup_intent` guards with `to_paise(amount) < MIN_TOPUP_INR`. That is
    only right while both sides are rupees."""
    assert to_paise(MIN_TOPUP_INR) == MIN_TOPUP_INR
    assert to_paise(MAX_TOPUP_INR) == MAX_TOPUP_INR

    # A ₹99 top-up is below the floor and ₹100 is not — asserted through the same
    # function the route uses, so the scales cannot drift apart unnoticed.
    assert to_paise(Decimal("99.99")) < MIN_TOPUP_INR
    assert to_paise(Decimal("100.00")) >= MIN_TOPUP_INR
    assert to_paise(Decimal("100000.01")) > MAX_TOPUP_INR


def test_rounding_is_half_up_and_does_not_read_the_ambient_context() -> None:
    """GST on a ₹100.25 subtotal is exactly ₹18.045. Half-up gives the ₹18.05 an
    Indian tax invoice is checked for; the process-global default (half-even) gives
    ₹18.04, and any library in the image can change that default."""
    assert to_paise(Decimal("18.045")) == Decimal("18.05")

    with decimal.localcontext() as ctx:
        ctx.rounding = decimal.ROUND_DOWN
        assert to_paise(Decimal("18.045")) == Decimal("18.05"), (
            "rounding must be passed explicitly, not inherited from the process"
        )


def test_no_rupee_amount_becomes_a_float() -> None:
    """Hard rule 7 at the one function every money field passes through."""
    result = to_paise(Decimal("2500.10"))
    assert isinstance(result, Decimal)
    assert not isinstance(result, float)
    assert str(result) == "2500.10"
