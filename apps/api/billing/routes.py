"""Admin-realm invoice endpoint (ROADMAP M2).

Admin realm because an invoice names what a client owes us; the client-facing render
of the same statement is a later, separate surface. Like `tenant_margin`, the work
runs under a tenant-scoped session — `usage_events` and `plans` are RLS'd and stay
that way; `app.admin` opens the client DIRECTORY, never their data.

This router is NOT mounted here — the integrator mounts it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from apps.api.billing.invoice import build_invoice
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/invoice", tags=["admin"])


def _stringify(value: Any) -> Any:
    """Decimals become strings exactly as `tenant_margin` does — recursively, because
    the invoice nests money inside `line_items` and `usage`."""
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


class InvoiceOrganizationOut(Strict):
    # Already `str(org.id)` by the time it leaves `build_invoice`.
    id: str
    name: str
    # Nullable: a client can be onboarded before finance supplies a billing address.
    billing_email: str | None


class InvoiceLineItemOut(Strict):
    description: str
    # A STRING, like every other number on this document. `qty` is a `Decimal` on BOTH
    # line kinds (`Decimal("1")` for the plan fee, decimal minutes for overage) exactly
    # so a consumer never gets a bare JSON number on one line and a string on the next
    # — see the comment in billing/invoice.py.
    qty: str
    unit_inr: str
    amount_inr: str


class InvoiceUsageOut(Strict):
    minutes_used: str
    calls: int
    included_minutes: int


class InvoiceOut(Strict):
    """The structured statement a future PDF/UI renders (billing/invoice.py).

    Money is a string throughout for the reason hard rule 7 exists: these are exact
    NUMERIC rupee amounts, and a JSON float cannot hold them. `qty * unit_inr` must
    still reproduce `amount_inr` when a client checks it by hand, which is why the
    overage rate is published at its true precision rather than rounded like a rupee.
    """

    # Deterministic: CAL-{YYYYMM}-{tenant prefix} — one number per tenant-month.
    invoice_number: str
    # IST billing month, YYYY-MM.
    month: str
    # An ISO-8601 string already when it leaves `build_invoice`, not a datetime.
    generated_at: str
    organization: InvoiceOrganizationOut
    # Deliberately empty when nothing was billable — a usage-only statement. A ₹0.00
    # line invites a dispute about nothing, so absence states the absence of a charge.
    line_items: list[InvoiceLineItemOut]
    subtotal_inr: str
    gst_rate_pct: str
    gst_inr: str
    total_inr: str
    usage: InvoiceUsageOut


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
    # `extra="forbid"`: a field `build_invoice` grows without the schema growing with it
    # fails here rather than reaching a browser the generated client cannot type.
    return InvoiceOut.model_validate({k: _stringify(v) for k, v in invoice.items()})


__all__ = ["router"]
