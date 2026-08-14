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

from .charges import one_time_charge_lines
from .plans import month_pricing_instant
from .service import to_paise, usage_summary

# 18% GST on SaaS/telecom services. Whether that lands as IGST or a CGST+SGST split is
# an invoicing detail the accountant owns — the ledger's job is the base amount and the
# rate applied. A constant (greppable by name) until pricing config ships.
GST_RATE_PCT = Decimal("18")


def _reconcile_overage(rungs: list[dict[str, Any]], overage_cost: Decimal) -> None:
    """Make the per-rung overage lines sum to the total the client was already shown.

    `usage_summary` prices the whole overage in ONE quantization — `to_paise(premium *
    rate + value * value_rate)` — while the invoice has to show each rung on its own
    line, which is two quantizations. Those can differ by a paisa. The panel's number is
    the one the client has seen and the one `margin_for_tenant` uses, so it wins, and the
    LAST line absorbs the difference: a rounding remainder has to land somewhere, and
    putting it on the final line is what a hand-checker expects.

    Mutates in place because the caller is building the list; it is private to this
    module for exactly that reason.
    """
    if not rungs:
        return
    drift = overage_cost - sum((item["amount_inr"] for item in rungs), start=Decimal("0"))
    if drift != 0:
        rungs[-1]["amount_inr"] = to_paise(rungs[-1]["amount_inr"] + drift)


async def build_invoice(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """Build one tenant's invoice statement for an IST billing month.

    The invoice number is **deterministic on purpose**:
    ``CAL-{month-without-dash}-{first 8 hex of tenant_id}``. Rebuilding the same month
    for the same tenant yields the same number, so a regenerated invoice can never
    silently duplicate — the accountant sees ONE number per tenant-month, however many
    times the JSON was produced.

    Line items: the plan fee whenever the tenant has a plan (with a fee), the tenant's
    one-time charges for this month (the onboarding setup fee — `billing/charges.py`),
    plus an overage line only when overage actually cost something. A ₹0.00 line on an
    invoice invites a dispute about nothing, so zero-amount overage (under the included
    minutes, or a zero/absent rate) and a zero or absent setup fee simply do not appear.

    **This function APPENDS the setup charge to `one_time_charges` the first time the
    onboarding month's statement is built, and that is deliberate** — there is no
    `invoices` table for a signup-time side effect to hang off, so the statement is
    where the fee is billed. The write is idempotent under a unique index and can only
    ever ADD the row that says what was already owed; every later build, including a
    concurrent one, reads it back rather than writing a second.

    GST: ``GST_RATE_PCT`` (18%) on the subtotal, quantized to paise. The IGST vs
    CGST+SGST split is the accountant's concern, not this function's (see the module
    constant).

    Must run under a tenant-scoped session — `usage_summary` reads RLS'd tables.
    """
    usage = await usage_summary(session, tenant_id=tenant_id, month=month)
    period = str(usage["month"])

    org = (
        await session.execute(
            # `created_at` is read for the same reason the name is: it is on the
            # statement's face. It decides the tenant's ONBOARDING month, which is the
            # one month the setup fee may land on (`billing/charges.py`).
            text("SELECT id, name, billing_email, created_at FROM organizations WHERE id = :tid"),
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

    # ONE-TIME CHARGES — today the onboarding setup fee, and only on the tenant's
    # onboarding month. Read from `one_time_charges` rather than computed here: the
    # ledger is what makes "billed once" survive regeneration, a plan change and two
    # concurrent generations (see `billing/charges.py` for the whole argument). A tenant
    # with no such charge gets NO line, which is the same rule the overage follows.
    line_items.extend(
        await one_time_charge_lines(
            session,
            tenant_id=tenant_id,
            month=period,
            onboarded_at=org.created_at,
            # The same instant `usage_summary` priced this month at, recomputed from the
            # same pure function rather than passed through a dict — one definition of
            # "which plan prices this month", used twice.
            priced_at=month_pricing_instant(period),
        )
    )

    overage_minutes: Decimal = usage["overage_minutes"]
    overage_cost: Decimal = usage["overage_cost_inr"]
    if overage_minutes > 0 and overage_cost > 0:
        # The rates come from `usage_summary`, which is the computation that PRICED the
        # overage. Re-reading `plans` here was a second query with its own
        # `ORDER BY created_at DESC LIMIT 1` — two plan rows sharing a created_at and
        # the invoice could quote a rate it did not bill at. One source, one rate.
        rate: Decimal = usage["overage_rate_inr"]
        value_rate: Decimal | None = usage["overage_rate_value_inr"]
        if value_rate is None:
            # ONE rate, ONE line — the shape every invoice had before plans could quote
            # a value rate, and the shape every plan that does not quote one still has.
            line_items.append(
                {
                    "description": f"Extra calling minutes ({overage_minutes} min at ₹{rate}/min)",
                    "qty": overage_minutes,
                    "unit_inr": rate,
                    "amount_inr": overage_cost,
                }
            )
        else:
            # TWO rungs, TWO lines. A single line quoting one rate could not multiply
            # out — `qty * unit_inr` would miss the total by the difference between the
            # rates — and "every line multiplies out" is the arithmetic promise a client
            # actually checks. A rung with no minutes gets no line, for the same reason a
            # ₹0.00 overage gets none: a zero line invites a dispute about nothing.
            #
            # The two amounts are computed here and the LAST one absorbs the rounding,
            # so the lines still sum to exactly the `overage_cost_inr` the usage panel
            # already showed the client. Rounding each independently could leave the
            # invoice a paisa away from the panel, and that paisa is a support ticket.
            rungs: list[dict[str, Any]] = [
                {
                    "description": f"Extra calling minutes, {label} ({qty} min at ₹{unit}/min)",
                    "qty": qty,
                    "unit_inr": unit,
                    "amount_inr": to_paise(qty * unit),
                }
                for label, qty, unit in (
                    ("premium voice", usage["overage_minutes_premium"], rate),
                    ("value voice", usage["overage_minutes_value"], value_rate),
                )
                if qty > 0
            ]
            _reconcile_overage(rungs, overage_cost)
            line_items.extend(rungs)

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
