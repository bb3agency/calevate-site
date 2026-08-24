"""The invoice statement, in BOTH realms (ROADMAP M2, SLICE AL).

Two routers, ONE computation. `build_invoice` is the only thing that knows how a bill is
derived, and both handlers below call it and validate through the same `InvoiceOut`, so
the document ops prints and the document the client prints cannot disagree — not by a
paisa, not by a line, not by a heading. A bill that argues with itself is the worst
version of this feature, and the way that happens is a second implementation "for the
client view", so there is deliberately no second implementation to drift.

**Why the client half exists at all.** BRD §51 names the client persona as the one who
pays invoices, and until this slice the only way to see one was the admin console. A
client who wanted their own bill had to ask us for it.

**Why both are GETs and both are pure reads.** Rendering an invoice used to append the
onboarding setup fee the first time anyone opened it (D-64), which put a write behind a
GET and left a tenant whose invoice nobody opened uncharged. `apps/workers/billing.py`
issues those charges on a schedule now; `build_invoice` writes nothing, and the client
path must never reintroduce one — an impersonating operator opening a client's invoice
would otherwise be performing a billing write from a read-only session.

**Realms and permissions.** The admin route keeps `realm="admin"` and the tenant in the
path: it is a cross-tenant ops surface reached with an admin token. The client route
takes the tenant from the PRINCIPAL and requires `billing:read` — the same permission
`GET /v1/usage` requires, which `staff` does not hold (spend is an owner's business,
SEC-COMP §5) and which is NOT in `MUTATING_PERMISSIONS`, so a support person inside a
read-only "view as client" session (D-22) can see exactly the document the client is
looking at. That last property is the whole reason the read permission is the right one:
the recurring bug `tests/impersonation_reads_test.py` exists to stop is a view gated on
the permission to ACT.

Both run under a tenant-scoped session — `usage_events`, `plans` and `kyc_records` are
RLS'd and stay that way; `app.admin` opens the client DIRECTORY, never their data.

These routers are NOT mounted here — the integrator mounts them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.invoice import build_invoice
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/invoice", tags=["admin"])
client_router = APIRouter(prefix="/v1/billing/invoice", tags=["billing"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this IS routes.py — but the client handler reads better with the
# alias and it matches `kyc_routes.py`, so both realms declare their reader the same way.
InvoiceReader = Annotated[Principal, Depends(requires("billing:read"))]


def _stringify(value: Any) -> Any:
    """Decimals become strings exactly as `tenant_margin` does — recursively, because
    the invoice nests money inside `line_items`, `tax_components` and `usage`."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _stringify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify(v) for v in value]
    return value


class Strict(BaseModel):
    """`extra="forbid"` (the crm/schemas.py convention): the response model IS the
    output whitelist, and an undeclared field cannot be serialized."""

    model_config = ConfigDict(extra="forbid")


class InvoiceSupplierOut(Strict):
    """Who issued this document (Rule 46(a)-(b), CGST Rules 2017).

    EVERY FIELD IS NULLABLE and today every one of them is null: the legal entity has not
    been chosen, so there is no GSTIN to print (ROADMAP M0). That is not a gap in this
    schema, it is the state the schema exists to represent honestly — see
    `document_type`.
    """

    legal_name: str | None
    # The registered address of the entity. One free-text block rather than parsed
    # lines: Rule 46 wants the address, not a schema for addresses, and splitting it
    # would invite a screen to reassemble it in a different order than the registration.
    address: str | None
    gstin: str | None
    # Derived from the GSTIN's first two digits — never a second setting, so it cannot
    # disagree with the number printed beside it.
    state_name: str | None
    # Service Accounting Code (Rule 46(g)); repeated on every line, where the rule wants
    # it, and here once for a reader looking for it at the top.
    sac: str | None


class InvoiceOrganizationOut(Strict):
    # Already `str(org.id)` by the time it leaves `build_invoice`.
    id: str
    name: str
    # Nullable: a client can be onboarded before finance supplies a billing address.
    billing_email: str | None
    # The recipient's GSTIN (Rule 46(e)-(f)) — present only when ops verified this
    # business against its GST registration (`billing/invoice.py::_recipient_gstin`
    # argues why that is the source). Null is lawful: a client below the registration
    # threshold is a B2C supply, and the null is what tells them no input credit is
    # claimable.
    gstin: str | None
    state_name: str | None


class InvoiceLineItemOut(Strict):
    description: str
    # A STRING, like every other number on this document. `qty` is a `Decimal` on BOTH
    # line kinds (`Decimal("1")` for the plan fee, decimal minutes for overage) exactly
    # so a consumer never gets a bare JSON number on one line and a string on the next
    # — see the comment in billing/invoice.py.
    qty: str
    unit_inr: str
    amount_inr: str
    # Rule 46(g). Null until `GST_SUPPLY_SAC` is configured, which is one of the reasons
    # the document refuses to call itself a tax invoice.
    sac: str | None


class InvoicePlaceOfSupplyOut(Strict):
    """Rule 46(n) — and the field that decides which taxes were charged.

    `basis` is published rather than kept in the server's head because place of supply is
    the particular most likely to be questioned, and the question is always "why this
    one". IGST Act s.12(2) in one sentence beats a support ticket.
    """

    state_code: str | None
    state_name: str | None
    # "intrastate" | "interstate" | "undetermined". `undetermined` is what a deployment
    # with no GST registration gets — there is no supplier location to compare against,
    # and inventing one would put a client's credit under the wrong head.
    supply_type: str
    basis: str


class InvoiceTaxComponentOut(Strict):
    """One head of tax, itemised as Rule 46(l)-(m) requires.

    The flat "GST @ 18%" this replaces was not merely terse: CGST, SGST/UTGST and IGST
    are three different ledgers on the recipient's side, and tax charged without saying
    which one cannot be claimed. The components always sum to `gst_inr` exactly.
    """

    # "CGST" | "SGST" | "UTGST" | "IGST", or "GST" on a proforma with no classification.
    label: str
    # A RATE (9, 18) — printed as published, never as a rupee amount.
    rate_pct: str
    amount_inr: str


class InvoiceUsageOut(Strict):
    minutes_used: str
    calls: int
    included_minutes: int


class InvoiceOut(Strict):
    """The structured statement a PDF/UI renders (billing/invoice.py).

    Money is a string throughout for the reason hard rule 7 exists: these are exact
    NUMERIC rupee amounts, and a JSON float cannot hold them. `qty * unit_inr` must
    still reproduce `amount_inr` when a client checks it by hand, which is why the
    overage rate is published at its true precision rather than rounded like a rupee.

    ONE model for both realms. The client and the operator receive byte-identical
    documents for the same tenant-month (`generated_at` aside), which is asserted in
    `tests/invoice_gst_test.py` and is the property that makes this feature trustworthy.
    """

    # Deterministic: CAL{YYMM}{tenant suffix} — one number per tenant-month, exactly
    # sixteen characters (Rule 46(b)'s length cap, now satisfied). The CONSECUTIVE-series
    # half of 46(b) is still open and is argued in billing/invoice.py.
    invoice_number: str
    # IST billing month, YYYY-MM.
    month: str
    # An ISO-8601 string already when it leaves `build_invoice`, not a datetime.
    generated_at: str
    # "tax_invoice" | "proforma". THE FIELD THE HEADING IS RENDERED FROM. A document that
    # looks like a tax invoice and is not is worse than one that admits what it is, so
    # the server decides this and the browser never writes the words itself.
    document_type: str
    # The environment variables standing between this document and being a tax invoice,
    # named as an operator types them. Empty on a `tax_invoice`.
    document_blockers: list[str]
    supplier: InvoiceSupplierOut
    organization: InvoiceOrganizationOut
    place_of_supply: InvoicePlaceOfSupplyOut
    # Deliberately empty when nothing was billable — a usage-only statement. A ₹0.00
    # line invites a dispute about nothing, so absence states the absence of a charge.
    line_items: list[InvoiceLineItemOut]
    subtotal_inr: str
    # The rate APPLIED to this document: "18" on a tax invoice, "0" on a bill of supply.
    gst_rate_pct: str
    gst_inr: str
    # `gst_inr` split across the heads the place of supply puts it under; sums to it
    # exactly, so no consumer has to add these up and risk disagreeing. Empty on a bill of
    # supply, which charges no tax.
    tax_components: list[InvoiceTaxComponentOut]
    total_inr: str
    # The words that make an unregistered document a compliant BILL OF SUPPLY — no tax
    # charged, no input tax credit (CGST s.32, Rule 49). Null on a tax invoice.
    tax_note: str | None
    # INTERNAL ESTIMATE, never a collectible amount: what the tax and total WOULD be once
    # Calevate is GST-registered. Present only on a bill of supply so a screen can preview
    # the eventual figure without ever presenting it as due; null on a tax invoice, where
    # `gst_inr`/`total_inr` already carry the real amounts.
    estimated_gst_rate_pct: str | None
    estimated_gst_inr: str | None
    estimated_total_inr: str | None
    usage: InvoiceUsageOut


def _out(invoice: dict[str, Any]) -> InvoiceOut:
    """`extra="forbid"`: a field `build_invoice` grows without the schema growing with it
    fails HERE rather than reaching a browser the generated client cannot type. Shared by
    both realms so neither can quietly publish a field the other does not."""
    return InvoiceOut.model_validate({k: _stringify(v) for k, v in invoice.items()})


@router.get(
    "",
    response_model=InvoiceOut,
    openapi_extra=permission_meta("billing:read"),
    summary="One tenant's invoice statement for an IST billing month (deterministic number)",
)
async def tenant_invoice(
    tenant_id: UUID,
    month: str | None = None,
    _: Principal = Depends(requires("billing:read", realm="admin")),
) -> InvoiceOut:
    async with tenant_session(tenant_id) as scoped:
        invoice = await build_invoice(scoped, tenant_id=tenant_id, month=month)
    return _out(invoice)


@client_router.get(
    "",
    response_model=InvoiceOut,
    openapi_extra=permission_meta("billing:read"),
    summary="This account's own invoice statement for an IST billing month",
    description=(
        "The same statement the Calevate team sees for this account, recomputed from the "
        "usage ledger on every request — there is no stored invoice row to go stale. "
        "Requires `billing:read`, which account owners hold and staff do not. The "
        "document states whether it is a tax invoice or a proforma; it is a proforma "
        "until Calevate's GST registration is recorded, because an unregistered supplier "
        "may not collect tax (CGST s.32)."
    ),
)
async def my_invoice(
    session: Session,
    principal: InvoiceReader,
    month: str | None = None,
) -> InvoiceOut:
    """The tenant comes from the PRINCIPAL, never from the caller.

    There is no `tenant_id` parameter to tamper with, and `session` is `deps.db` — scoped
    by RLS on the principal's own tenant — so another account's month is not merely
    forbidden, it is unaddressable and would return zero rows if it were addressed
    (hard rule 1; `tests/invoice_gst_test.py` proves both halves).
    """
    assert principal.tenant_id is not None
    return _out(await build_invoice(session, tenant_id=principal.tenant_id, month=month))


__all__ = ["client_router", "router"]
