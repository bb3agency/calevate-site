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


@router.get(
    "",
    openapi_extra=permission_meta("billing:read"),
    summary="One tenant's invoice statement for an IST billing month (deterministic number)",
)
async def tenant_invoice(
    tenant_id: UUID,
    month: str | None = None,
    _: Principal = Depends(requires("billing:read", realm="admin")),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as scoped:
        invoice = await build_invoice(scoped, tenant_id=tenant_id, month=month)
    return {k: _stringify(v) for k, v in invoice.items()}


__all__ = ["router"]
