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

from apps.api.compliance.kyc import read_kyc
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

from .charges import one_time_charge_lines
from .gst import Gstin, parse_gstin, resolve_place_of_supply, split_tax, supplier_identity
from .service import to_paise, usage_summary

# 18% GST on SaaS/telecom services. A constant (greppable by name) until pricing config
# ships. WHICH HEADS it lands under is no longer "an invoicing detail the accountant
# owns", which is what this comment used to say and what left the document invalid:
# Rule 46(l)-(m) requires the tax to appear separately as central / State / integrated /
# Union territory tax, and a recipient credits those to three different ledgers. The
# split is derived in `billing/gst.py` from the place of supply; only the total rate
# lives here.
GST_RATE_PCT = Decimal("18")

# THE INVOICE NUMBER IS NOT YET RULE 46(b) COMPLIANT, and this note is the honest half of
# a slice that fixed the rest. 46(b) requires "a consecutive serial number, not exceeding
# sixteen characters ... unique for a financial year". `CAL-202608-0192f0aa` is NINETEEN
# characters and is not consecutive — it is deterministic per tenant-month, which is a
# different and deliberately chosen property (D-46: the statement is recomputed from the
# ledgers, never stored, so regeneration cannot duplicate).
#
# The two requirements genuinely conflict: a CONSECUTIVE series needs a counter, which
# needs a stored issued-invoice row, which is exactly what D-46 rejected. Truncating the
# tenant suffix to fit sixteen characters is not a fix either — five hex characters
# collide across a few hundred tenants often enough to put two clients on one invoice
# number, which breaks 46(b)'s uniqueness instead of its length.
#
# So the numbering scheme is left ALONE rather than half-changed: it needs the same
# decision the identity fields need (the entity, its financial-year series, and whether
# an issued-invoice registry is acceptable under D-46), and until that decision exists
# the document does not claim to be a tax invoice anyway. Reported, not invented.
#
# `tests/invoice_gst_test.py` pins the gap so it stays visible: the finding is executable
# rather than a comment that rots.
RULE_46B_MAX_SERIAL_CHARS = 16


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

    **This function WRITES NOTHING.** It used to append the setup charge to
    `one_time_charges` the first time the onboarding month's statement was built, which
    put a side effect behind a GET and left a tenant whose invoice nobody opened
    uncharged. `apps/workers/billing.py::issue_one_time_charges` issues those charges on
    a schedule now and `billing/charges.issue_setup_fee` is the only writer; building a
    statement is a read of the ledgers, start to finish.

    GST: ``GST_RATE_PCT`` (18%) on the subtotal, quantized to paise, then SPLIT across
    the heads the place of supply puts it under (`billing/gst.py`). The total is the
    same number it always was; what is new is that the document says whether it is IGST
    or CGST+SGST, because a recipient credits those to different ledgers and cannot
    claim tax charged under the wrong one (Rule 46(l)-(m), CGST Rules).

    **What the identity being unconfigured does, and what it deliberately does NOT do.**
    With no `GST_SUPPLIER_*` values this returns ``document_type = "proforma"`` and lists
    the missing keys in ``document_blockers``; the heading, not the arithmetic, is what
    changes. Zeroing the tax was considered and rejected: it is the more literal reading
    of CGST s.32 (an unregistered person shall not collect tax), but it would mean a
    deployment that forgot one environment variable silently under-bills every client by
    18% — a missing config key must never move money. The proforma states in words that
    no tax may be collected against it, which is what a proforma is for.

    Must run under a tenant-scoped session — `usage_summary` and `read_kyc` read RLS'd
    tables.
    """
    usage = await usage_summary(session, tenant_id=tenant_id, month=month)
    period = str(usage["month"])

    org = (
        await session.execute(
            # What is on the statement's face, and nothing more. `created_at` used to be
            # read here too — it decides the tenant's ONBOARDING month, and this function
            # used to be what billed the setup fee into it. Issuing that charge is
            # `apps/workers/billing.py`'s job now, so the invoice no longer needs to know
            # when the client was onboarded; it reads what was billed.
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

    # ONE-TIME CHARGES — today the onboarding setup fee, and only on the tenant's
    # onboarding month. Read from `one_time_charges` rather than computed here: the
    # ledger is what makes "billed once" survive regeneration, a plan change and two
    # concurrent generations (see `billing/charges.py` for the whole argument). A tenant
    # with no such charge gets NO line, which is the same rule the overage follows.
    line_items.extend(await one_time_charge_lines(session, tenant_id=tenant_id, month=period))

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

    supplier = supplier_identity(get_settings())
    recipient_gstin = await _recipient_gstin(session, tenant_id=tenant_id)
    place = resolve_place_of_supply(supplier, recipient_gstin)

    # Rule 46(g): every line carries the SAC of the supply. One code for the whole
    # document because every line is the same supply — a plan fee, an onboarding fee and
    # extra minutes are all consideration for the one voice-agent service — so a second
    # config key per line kind would be four ways to state one classification.
    for item in line_items:
        item["sac"] = supplier.sac

    subtotal = to_paise(sum((item["amount_inr"] for item in line_items), start=Decimal("0")))
    gst = to_paise(subtotal * GST_RATE_PCT / Decimal("100"))
    total = to_paise(subtotal + gst)
    components = split_tax(subtotal_inr=subtotal, rate_pct=GST_RATE_PCT, place=place)

    return {
        "invoice_number": f"CAL-{period.replace('-', '')}-{tenant_id.hex[:8]}",
        "month": period,
        "generated_at": datetime.now(UTC).isoformat(),
        # WHAT THIS DOCUMENT IS. `tax_invoice` only when every Rule 46 identity
        # particular is configured; otherwise `proforma`, with the environment variables
        # an operator must set. The console renders the heading from THIS, never from a
        # literal, so the one place that decides is the one place that knows.
        "document_type": "tax_invoice" if supplier.is_registered else "proforma",
        "document_blockers": list(supplier.missing),
        "supplier": {
            "legal_name": supplier.legal_name,
            "address": supplier.address,
            "gstin": supplier.gstin.value if supplier.gstin else None,
            "state_name": supplier.gstin.state_name if supplier.gstin else None,
            "sac": supplier.sac,
        },
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "billing_email": org.billing_email,
            # Rule 46(e)-(f): the recipient's GSTIN when they have one. Null is a real
            # and lawful answer — a client below the registration threshold is a B2C
            # supply and this is still a tax invoice — and it is the answer that tells
            # the reader why no input credit is claimable.
            "gstin": recipient_gstin.value if recipient_gstin else None,
            "state_name": recipient_gstin.state_name if recipient_gstin else None,
        },
        # Rule 46(n) wants the place of supply with the name of the State on an
        # inter-State supply; it is published unconditionally because a reader checking
        # WHY they were charged IGST needs it on the intra-State document too.
        "place_of_supply": {
            "state_code": place.state_code,
            "state_name": place.state_name,
            "supply_type": place.supply_type,
            "basis": place.basis,
        },
        "line_items": line_items,
        "subtotal_inr": subtotal,
        "gst_rate_pct": GST_RATE_PCT,
        "gst_inr": gst,
        # The same total, itemised by head. `gst_inr` stays the authority and the
        # components sum to it exactly (`gst.split_tax` makes the second absorb the
        # remainder), so no screen has to add them up and disagree.
        "tax_components": [
            {
                "label": component.label,
                "rate_pct": component.rate_pct,
                "amount_inr": component.amount_inr,
            }
            for component in components
        ],
        "total_inr": total,
        "usage": {
            "minutes_used": usage["minutes_used"],
            "calls": usage["calls"],
            "included_minutes": usage["included_minutes"],
        },
    }


async def _recipient_gstin(session: AsyncSession, *, tenant_id: UUID) -> Gstin | None:
    """The client's own GSTIN — the VERIFIED one, or none at all.

    There is no `organizations.gstin` column, and adding one was the obvious move and the
    wrong one: nothing in the product would write it (the tenant record's only writer is
    the admin console), so it would ship as a column nobody fills — a defect that looks
    like progress. What DOES exist is `kyc_records`, where ops records the public
    business-registry document they verified this business against (D-47), and
    `document_kind = 'gstin'` means that document WAS the GST registration.

    That is a stronger fact than a typed-in field, and the strength is the argument: a
    recipient GSTIN on an invoice that does not match the recipient's actual registration
    is a mismatch in their return, so "a human checked this against the registry" is
    exactly the standard this field should meet. `is_verified` is required for the same
    reason — an `in_review` record is a claim, not a verification.

    A client verified against a CIN, Udyam or trade licence therefore has no GSTIN here
    even if they hold one, and the document says "not registered" rather than guessing.
    That understatement is safe (a B2C tax invoice is still valid) where a guess is not.
    Closing it is a product decision — a client-supplied, ops-confirmed billing GSTIN —
    not something this function should invent.
    """
    record = await read_kyc(session, tenant_id=tenant_id)
    if not record.is_verified or record.document_kind != "gstin":
        return None
    return parse_gstin(record.document_ref)


__all__ = ["GST_RATE_PCT", "build_invoice"]
