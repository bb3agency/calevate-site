"""The ops work list: which accounts are waiting on a human.

    GET /v1/admin/compliance/holds

The discovery half of two R-11 mitigations that shipped without one. `apps/api/admin/
holds.py` argues the isolation design (nothing widened; the directory, then each
tenant's own RLS session) and states what is deliberately absent from the row.

**`org:read`, not `admin:tenants`.** D-22 forbids gating a GET on a permission
read-only impersonation refuses, and `admin:tenants` is in `MUTATING_PERMISSIONS`.
Reading a work list is not acting on it: every release on it is a separate, audited
POST that keeps `admin:tenants`. The existing `/v1/admin/tenants` GETs carry the
mutating permission and an exemption in `tests/impersonation_reads_test.py`; a new
surface does not need to inherit that, and the repo's own rule is to pick the read
permission when one fits. Both admin roles hold `org:read`.

**`realm="admin"` is what separates the realms**, not the permission — client roles
hold `org:read` too. The dependency resolves against `admin_users`, so a client token
never reaches this route whatever its role.

**No audit row.** The queue discloses no personal data and it is the page an operator
refreshes; an audit chain that grows a row per poll stops being readable (the argument
`kyc_routes.py` makes for the client's own screen). Every ACTION taken from it — the
KYC record, the release, the refusal — writes its own entry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.holds import HeldTenant, held_tenants
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/admin/compliance/holds", tags=["admin"])

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is `holds_routes.py` — same situation and same
# resolution as `kyc_routes.py` and `first_campaign_routes.py`.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
QueueReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]


class HeldTenantOut(BaseModel):
    """One account waiting on a human — and nothing about anyone at that account."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str
    slug: str
    # Both controls are scoped to the self-serve motion, so this is always `self_serve`
    # or `trial` today. It is on the row because the day a third motion appears, an
    # operator reading this list must not have to guess which line it was drawn on.
    plan_tier: str
    signed_up_at: datetime
    # The gates' own rule names — `kyc_missing`, `kyc_not_verified`,
    # `first_campaign_review_pending`, `first_campaign_review_rejected` — the same
    # vocabulary the client's screen and the launch preview use, so an operator and a
    # client on the phone are naming one condition the same way. An account can be held
    # by both gates at once; the list says so rather than picking a winner.
    holds: list[str]


def _out(row: HeldTenant) -> HeldTenantOut:
    return HeldTenantOut(
        tenant_id=row.tenant_id,
        name=row.name,
        slug=row.slug,
        plan_tier=row.plan_tier,
        signed_up_at=row.signed_up_at,
        holds=list(row.rules),
    )


@router.get(
    "",
    response_model=list[HeldTenantOut],
    openapi_extra=permission_meta("org:read"),
    summary="Accounts held for a human decision — KYC and first-campaign review (R-11)",
    description=(
        "Every self-serve account that cannot dial until someone at Calevate acts, "
        "oldest signup first: identity verification not recorded, or the first campaign "
        "not yet released. An account held by both gates appears once with both rules. "
        "Clearing a gate removes the account from this list. Read-only — the decisions "
        "are recorded through the audited routes on each account."
    ),
)
async def list_held_tenants(session: AdminSession, principal: QueueReader) -> list[HeldTenantOut]:
    del principal  # the dependency IS the authorization; the identity is not needed here
    return [_out(row) for row in await held_tenants(session)]


__all__ = ["router"]
