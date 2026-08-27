"""The invoice's tax total is the SUM OF THE HEADS it prints, computed once.

Rule 46(l)-(m), CGST Rules 2017 requires the tax to appear separately as central / State /
integrated / Union territory tax, and a recipient credits those to different ledgers. So
the heads are what the document actually asserts, and `gst_inr` is a convenience total
over them.

THE DEFECT this pins is a "two spellings" one rather than a wrong number.
`build_invoice` computed `gst = to_paise(subtotal * GST_RATE_PCT / 100)` — character for
character the expression `gst.split_tax` opens with — and then called `split_tax` to
produce the heads. The two agreed, and nothing made them: `split_tax`'s own docstring
promises "the two halves summing to the printed GST total is the property a hand-checker
actually tests", and that promise was held by two identical expressions rather than by
one computation. The next rounding decision on this line — a rate that is not a whole
percent, or CGST s.170's round-to-the-nearest-rupee question — would have had to be made
in both places, and a document whose stated tax is not the sum of its own tax lines is
the first thing an accountant rejects.

Run: uv run pytest -q tests/invoice_tax_total_is_the_heads_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.gst import PlaceOfSupply, TaxComponent, split_tax
from apps.api.billing.invoice import build_invoice
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.money_walk_test import _metered_call, _tenant


async def _plan_with_odd_subtotal(tenant_id: UUID) -> None:
    """A monthly fee ending in an ODD number of paise, which is the only place 18% can
    land on a half-paisa and the CGST/SGST halves can fail to add up."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, 1234.5700, 0, 7.1250, 10, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id},
        )


async def test_the_stated_tax_is_exactly_the_heads_that_are_printed() -> None:
    tenant_id, agent_id = await _tenant()
    await _plan_with_odd_subtotal(tenant_id)
    await _metered_call(tenant_id, agent_id, tier="premium", seconds="300.3000")

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    heads = sum(
        (component["amount_inr"] for component in invoice["tax_components"]),
        start=Decimal("0.00"),
    )
    assert invoice["gst_inr"] == heads
    assert invoice["total_inr"] == invoice["subtotal_inr"] + invoice["gst_inr"]


async def test_the_document_follows_split_tax_rather_than_re_deriving_the_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The structural half, and it needs a substitution to be visible at all: while both
    spellings compute the same expression they agree by coincidence, so the only way to
    ask "which one does the document publish" is to make them differ.

    `split_tax` is wrapped rather than replaced — the real heads, with one paisa moved
    onto the second — so what is being asserted is that `gst_inr` FOLLOWS the heads, not
    that any particular arithmetic produced them.
    """

    def _one_paisa_heavier(
        *, subtotal_inr: Decimal, rate_pct: Decimal, place: PlaceOfSupply
    ) -> list[TaxComponent]:
        real = split_tax(subtotal_inr=subtotal_inr, rate_pct=rate_pct, place=place)
        last = real[-1]
        return [
            *real[:-1],
            TaxComponent(
                label=last.label,
                rate_pct=last.rate_pct,
                amount_inr=last.amount_inr + Decimal("0.01"),
            ),
        ]

    monkeypatch.setattr("apps.api.billing.invoice.split_tax", _one_paisa_heavier)

    tenant_id, agent_id = await _tenant()
    await _plan_with_odd_subtotal(tenant_id)
    await _metered_call(tenant_id, agent_id, tier="premium", seconds="300.3000")

    async with tenant_session(tenant_id) as session:
        invoice: dict[str, Any] = await build_invoice(session, tenant_id=tenant_id)

    heads = sum(
        (component["amount_inr"] for component in invoice["tax_components"]),
        start=Decimal("0.00"),
    )
    assert invoice["gst_inr"] == heads, (
        "the document states a tax total its own tax lines do not add up to"
    )
    assert invoice["total_inr"] == invoice["subtotal_inr"] + heads


async def test_a_client_can_add_the_invoice_up_by_hand() -> None:
    """The arithmetic promise in `billing/invoice.py`'s docstring, end to end: the lines
    sum to the subtotal, the heads sum to the tax, and the total is their sum."""
    tenant_id, agent_id = await _tenant()
    await _plan_with_odd_subtotal(tenant_id)
    await _metered_call(tenant_id, agent_id, tier="premium", seconds="300.3000")
    await _metered_call(tenant_id, agent_id, tier="value", seconds="299.7000")

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    lines = sum((item["amount_inr"] for item in invoice["line_items"]), start=Decimal("0.00"))
    heads = sum(
        (component["amount_inr"] for component in invoice["tax_components"]),
        start=Decimal("0.00"),
    )
    assert lines == invoice["subtotal_inr"]
    assert heads == invoice["gst_inr"]
    assert invoice["subtotal_inr"] + invoice["gst_inr"] == invoice["total_inr"]
    assert str(uuid.UUID(str(invoice["organization"]["id"]))) == str(tenant_id)


@pytest.fixture(autouse=True)
def _gst_registered_supplier(monkeypatch: pytest.MonkeyPatch):
    """Register a specimen GST supplier for this suite.

    These tests assert the TAX-INVOICE arithmetic (18% GST split into heads), which is only
    lawful once Calevate is GST-registered. An UNregistered supplier now issues a bill of
    supply with no tax (CGST s.32, Rule 49; billing/invoice.py), so without a registered
    supplier ``gst_inr`` would be zero and these arithmetic assertions would test nothing.
    The specimen GSTIN is Telangana (36) so an intra-State supply splits into CGST+SGST.
    """
    from apps.api.core.settings import get_settings

    monkeypatch.setenv("GST_SUPPLIER_LEGAL_NAME", "Calevate")
    monkeypatch.setenv("GST_SUPPLIER_ADDRESS", "Plot 42, Madhapur, Hyderabad 500081")
    monkeypatch.setenv("GST_SUPPLIER_GSTIN", "36AABCC1234D1Z5")
    monkeypatch.setenv("GST_SUPPLY_SAC", "998315")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
