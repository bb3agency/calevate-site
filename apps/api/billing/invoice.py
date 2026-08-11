"""Invoice generation (ROADMAP M2).

An invoice here is a STRUCTURED STATEMENT derived from the usage ledger — the JSON a
future PDF/UI renders, not the PDF itself. It is built on top of `usage_summary`
(never a parallel query set), so the invoice can never disagree with the usage panel
the client already saw: one computation, two presentations.

Money is NUMERIC/Decimal INR end to end (hard rule 7); every money field is quantized
to paise (``Decimal("0.01")``) at this boundary, because two decimals is what a rupee
amount means to the person reading the invoice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError

from .service import usage_summary

# 18% GST on SaaS/telecom services. Whether that lands as IGST or a CGST+SGST split is
# an invoicing detail the accountant owns — the ledger's job is the base amount and the
# rate applied. A constant (greppable by name) until pricing config ships.
GST_RATE_PCT = Decimal("18")

_PAISE = Decimal("0.01")


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
    monthly_fee = usage["monthly_fee_inr"]  # already paise-quantized, None without a plan fee
    if monthly_fee is not None:
        line_items.append(
            {
                "description": "Monthly plan fee",
                "qty": 1,
                "unit_inr": monthly_fee,
                "amount_inr": monthly_fee,
            }
        )

    overage_minutes: Decimal = usage["overage_minutes"]
    overage_cost: Decimal = usage["overage_cost_inr"]
    if overage_minutes > 0 and overage_cost > 0:
        # `usage_summary` exposes the overage COST, not the rate; the line description
        # needs the rate. Read it rather than re-deriving cost ÷ minutes, which would
        # re-round a number the client can check against their plan.
        rate_raw = (
            await session.execute(
                text(
                    "SELECT overage_rate FROM plans WHERE tenant_id = :tid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tid": tenant_id},
            )
        ).scalar()
        rate = Decimal(str(rate_raw or 0)).quantize(_PAISE)
        line_items.append(
            {
                "description": f"Extra calling minutes ({overage_minutes} min at ₹{rate}/min)",
                "qty": overage_minutes,
                "unit_inr": rate,
                "amount_inr": overage_cost,
            }
        )

    subtotal = sum((item["amount_inr"] for item in line_items), start=Decimal("0")).quantize(_PAISE)
    gst = (subtotal * GST_RATE_PCT / Decimal("100")).quantize(_PAISE)
    total = (subtotal + gst).quantize(_PAISE)

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
