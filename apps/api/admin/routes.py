"""Admin-realm endpoints (FLOWS §1, §2; D-22).

Every route here is `realm="admin"`, so a client token cannot reach any of them even
if it somehow carried the permission — the realms are separate Clerk applications and
`verify_token` will not accept one realm's token for the other.

Impersonation (D-22) is READ-ONLY and both its start and every page view are audited.
The start endpoint exists so the audit trail records the *intent* ("operator X began
viewing tenant Y at T"), which is what makes a later "why did you look at this account"
question answerable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import IMPERSONATE_HEADER, Principal
from apps.api.core.deps import admin_db, db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/admin", tags=["admin"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
# Reads the tenant DIRECTORY (organizations) cross-tenant; nothing else.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
TenantSession = Annotated[AsyncSession, Depends(db)]

Vertical = Literal["clinic", "real_estate", "insurance", "education", "custom"]


class TenantSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    slug: str
    status: str
    vertical_template: str | None
    live_agents: int
    calls_7d: int
    leads: int
    last_call_at: datetime | None
    capped: bool


class CreateOrgIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    # Optional: derived from the name when absent. IMMUTABLE once set (DB trigger),
    # because it lives in every client URL.
    slug: str | None = Field(default=None, max_length=40)
    vertical_template: Vertical = "clinic"
    billing_email: EmailStr | None = None
    language: Literal["te-IN", "hi-IN", "en-IN"] = "te-IN"


class CreateOrgOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    slug: str
    agent_id: UUID
    extraction_schema_id: UUID
    status: str


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: Literal["owner", "staff"] = "owner"


class InviteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Returned EXACTLY once — only the hash is stored, so it cannot be re-read later.
    token: str
    expires_in_hours: int


@router.get(
    "/tenants",
    response_model=list[TenantSummary],
    openapi_extra=permission_meta("admin:tenants"),
    summary="Client health overview (cross-tenant by design, audited surface)",
)
async def list_tenants(
    session: AdminSession, _: Principal = Depends(requires("admin:tenants", realm="admin"))
) -> list[TenantSummary]:
    return [TenantSummary.model_validate(row) for row in await service.tenant_overview(session)]


@router.post(
    "/tenants",
    response_model=CreateOrgOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="New-client wizard step 1 — org, retention defaults, agent draft, schema",
)
async def create_tenant(
    payload: CreateOrgIn,
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> CreateOrgOut:
    slug = payload.slug or service.slugify(payload.name)
    created = await service.create_organization(
        name=payload.name,
        slug=slug,
        vertical_template=payload.vertical_template,
        billing_email=str(payload.billing_email) if payload.billing_email else None,
        language=payload.language,
        created_by=principal.user_id,
    )
    await write_audit(
        session,
        action="admin.tenant_created",
        actor=principal,
        tenant_id=UUID(str(created["id"])),
        object_type="organization",
        object_id=str(created["id"]),
        ip=request.client.host if request.client else None,
        summary={"slug": slug, "vertical": payload.vertical_template},
    )
    return CreateOrgOut.model_validate(created)


@router.post(
    "/tenants/{tenant_id}/invitations",
    response_model=InviteOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Wizard step 8 — single-use 72h invite (token hashed at rest)",
)
async def invite_member(
    tenant_id: UUID,
    payload: InviteIn,
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> InviteOut:
    # `global_db` has no tenant GUC, and `invitations` is RLS'd — so scope explicitly
    # to the tenant being invited into rather than reusing the admin's own context.
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as scoped:
        token = await service.create_invitation(
            scoped,
            tenant_id=tenant_id,
            email=str(payload.email),
            role=payload.role,
            created_by=principal.user_id,
        )
    await write_audit(
        session,
        action="admin.invitation_created",
        actor=principal,
        tenant_id=tenant_id,
        object_type="invitation",
        ip=request.client.host if request.client else None,
        # The email is redacted by the audit summary sanitizer; the ROLE is what a
        # later review actually needs.
        summary={"role": payload.role},
    )
    return InviteOut(token=token, expires_in_hours=int(service.INVITE_TTL.total_seconds() // 3600))


@router.post(
    "/tenants/{tenant_id}/impersonate",
    openapi_extra=permission_meta("admin:impersonate"),
    summary="Begin a READ-ONLY view-as session (D-22) — audited, never acting-as",
)
async def start_impersonation(
    tenant_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:impersonate", realm="admin")),
) -> dict[str, str]:
    await write_audit(
        session,
        action="admin.impersonation_started",
        actor=principal,
        tenant_id=tenant_id,
        object_type="organization",
        object_id=str(tenant_id),
        ip=request.client.host if request.client else None,
    )
    # The header carries the SLUG, matching how the auth layer resolves it (and how
    # client URLs are addressed, D-10) — returning a raw uuid here would look right and
    # fail at the first request.
    from sqlalchemy import text as sql

    slug = (
        await session.execute(
            sql("SELECT slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    if slug is None:
        raise ProblemError.not_found("Organization")

    # No credential is minted: the admin keeps their own token and adds the
    # X-Impersonate-Org header, which the auth layer turns into a read-only principal.
    # Issuing a client credential would make the audit trail ambiguous about who acted.
    return {
        "mode": "read_only",
        "header": IMPERSONATE_HEADER,
        "value": str(slug),
        "note": "Mutations are refused while impersonating.",
    }


__all__ = ["router"]
