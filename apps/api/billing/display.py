"""How a number reads in client-facing text: emails, WhatsApp, notices, problem details a
client reads, and the text Pip's client tools hand the model.

At most ONE digit after the decimal point, and none when the value is whole: ₹4.5000 reads
₹4.5, ₹6.0000 reads ₹6, 12.0% reads 12% (founder, 27 Oct 2026). Rounded half-up, the same
rule as the web's `lib/numberDisplay.ts`, so a screen and an email never disagree.

Display only. Nothing here may feed a stored value, a wire field or a calculation; the money
itself stays NUMERIC and is rounded only by `billing.service.to_paise` (hard rule 7).

NOT for tax documents (`billing/invoice.py`, receipts, credit notes, GST statements), which
reconcile to the paisa, nor for the admin/ops console, whose operators need exact figures.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

ONE_DECIMAL = Decimal("0.1")


def _group_indian(whole: str) -> str:
    """12,34,567 — the last three digits, then pairs."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *pairs, tail])


def display_decimal(value: Decimal | int | str) -> str:
    """`Decimal("1234.56")` → "1,234.6"; `Decimal("12.0")` → "12"; `Decimal("4.95")` → "5"."""
    rounded = Decimal(value).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    whole, _, fraction = f"{abs(rounded):f}".partition(".")
    fraction = fraction.rstrip("0")
    grouped = _group_indian(whole)
    return f"{sign}{grouped}.{fraction}" if fraction else f"{sign}{grouped}"


def display_inr(value: Decimal | int | str) -> str:
    """`Decimal("4.5000")` → "₹4.5"; `Decimal("6")` → "₹6"; `Decimal("-1234.56")` → "-₹1,234.6"."""
    figure = display_decimal(value)
    return f"-₹{figure[1:]}" if figure.startswith("-") else f"₹{figure}"
