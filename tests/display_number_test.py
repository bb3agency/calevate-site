"""The client display rule for numbers in server-rendered text (`billing/display.py`)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing.display import display_decimal, display_inr


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("6.0000"), "₹6"),
        (Decimal("4.5000"), "₹4.5"),
        (Decimal("4.6296"), "₹4.6"),
        (Decimal("4.95"), "₹5"),
        (Decimal("4.05"), "₹4.1"),
        (Decimal("1234.56"), "₹1,234.6"),
        (Decimal("1234567.89"), "₹12,34,567.9"),
        (Decimal("999.96"), "₹1,000"),
        (Decimal("0"), "₹0"),
        (Decimal("-0.04"), "₹0"),
        (Decimal("-1234.56"), "-₹1,234.6"),
        (500, "₹500"),
        ("2500.10", "₹2,500.1"),
    ],
)
def test_display_inr_keeps_at_most_one_decimal(value: Decimal | int | str, expected: str) -> None:
    assert display_inr(value) == expected


def test_display_decimal_rounds_half_up_not_half_even() -> None:
    # HALF_EVEN, Decimal's default, would round 0.25 down to "0.2"; the web rounds it up.
    assert display_decimal(Decimal("0.15")) == "0.2"
    assert display_decimal(Decimal("0.25")) == "0.3"
    assert display_decimal(Decimal("3.25")) == "3.3"
    assert display_decimal(Decimal("12.0")) == "12"
