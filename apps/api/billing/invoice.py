"""Invoice generation (ROADMAP M2).

An invoice here is a STRUCTURED STATEMENT derived from the usage ledger — the JSON a
future PDF/UI renders, not the PDF itself. It is built on top of `usage_summary`
(never a parallel query set), so the invoice can never disagree with the usage panel
the client already saw: one computation, two presentations.

Money is NUMERIC/Decimal INR end to end (hard rule 7); every money field is rounded by
``service.to_paise`` — one function, one explicit mode (half-up) — because two decimals
is what a rupee amount means to the person reading the invoice, and which way ₹18.045
goes is a decision, not a default.

Two arithmetic promises the client can check by hand:

- every line multiplies out (``qty * unit_inr`` rounds to ``amount_inr``), which is why
  the overage RATE is published at its true precision rather than rounded like a rupee
  amount — see ``service.rate_to_display``;
- ``subtotal`` is the sum of the line amounts and nothing else, GST is applied at
  exactly one place, and ``total = subtotal + gst``. No ₹0.01 appears from anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError

from .service import to_paise, usage_summary

# 18% GST on SaaS/telecom services. Whether that lands as IGST or a CGST+SGST split is
# an invoicing detail the accountant owns — the ledger's job is the base amount and the
# rate applied. A constant (greppable by name) until pricing config ships.
GST_RATE_PCT = Decimal("18")


async def build_invoice(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """Build one tenant's invoice statement for an IST billing month.

    The invoice number is **deterministic on purpose**:
    ``CAL-{month-without-dash}-{first 8 hex of tenant_id}``. Rebuilding the same month
    for the same tenant yields the same number, so a regenerated invoice can never
    silently duplicate — the accountant sees ONE number per tenant-month, however many
    times the JSON was produced.

    Line items: the plan fee whenever the tenant has a plan (with a fee), plus an
    overage line only when overage actually cost something. A ₹0.00 line on an invoice
    invites a dispute about nothing, so zero-amount overage (under the included
    minutes, or a zero/absent rate) simply does not appear.

    GST: ``GST_RATE_PCT`` (18%) on the subtotal, quantized to paise. The IGST vs
    CGST+SGST split is the accountant's concern, not this function's (see the module
    constant).

    Must run under a tenant-scoped session — `usage_summary` reads RLS'd tables.
    """
    usage = await usage_summary(session, tenant_id=tenant_id, month=month)
    period = str(usage["month"])

    org = (
        await session.execute(
            text("SELECT id, name, billing_email FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if org is None:
        raise ProblemError.not_found("Organization")

    line_items: list[dict[str, Any]] = []
    monthly_fee = usage["monthly_fee_inr"]  # already paise-rounded, None without a plan fee
    if monthly_fee is not None:
        line_items.append(
            {
                "description": "Monthly plan fee",
                # Decimal, not int: every quantity on this document sits beside money
                # and is serialized the same way, so a consumer never gets a bare JSON
                # number on one line and a string on the next.
                "qty": Decimal("1"),
                "unit_inr": monthly_fee,
                "amount_inr": monthly_fee,
            }
        )

    overage_minutes: Decimal = usage["overage_minutes"]
    overage_cost: Decimal = usage["overage_cost_inr"]
    if overage_minutes > 0 and overage_cost > 0:
        # The rate comes from `usage_summary`, which is the computation that PRICED the
        # overage. Re-reading `plans` here was a second query with its own
        # `ORDER BY created_at DESC LIMIT 1` — two plan rows sharing a created_at and
        # the invoice could quote a rate it did not bill at. One source, one rate.
        rate: Decimal = usage["overage_rate_inr"]
        line_items.append(
            {
                "description": f"Extra calling minutes ({overage_minutes} min at ₹{rate}/min)",
                "qty": overage_minutes,
                "unit_inr": rate,
                "amount_inr": overage_cost,
            }
        )

    subtotal = to_paise(sum((item["amount_inr"] for item in line_items), start=Decimal("0")))
    gst = to_paise(subtotal * GST_RATE_PCT / Decimal("100"))
    total = to_paise(subtotal + gst)

    return {
        "invoice_number": f"CAL-{period.replace('-', '')}-{tenant_id.hex[:8]}",
        "month": period,
        "generated_at": datetime.now(UTC).isoformat(),
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "billing_email": org.billing_email,
        },
        "line_items": line_items,
        "subtotal_inr": subtotal,
        "gst_rate_pct": GST_RATE_PCT,
        "gst_inr": gst,
        "total_inr": total,
        "usage": {
            "minutes_used": usage["minutes_used"],
            "calls": usage["calls"],
            "included_minutes": usage["included_minutes"],
        },
    }


__all__ = ["GST_RATE_PCT", "build_invoice"]
