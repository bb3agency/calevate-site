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
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service
from apps.api.agents import service as agents_service
from apps.api.billing import service as billing
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import IMPERSONATE_HEADER, Principal
from apps.api.core.deps import admin_db, db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service

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


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantSummary,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client's health — the detail screen should not fetch the whole list",
)
async def get_tenant(
    tenant_id: UUID,
    session: AdminSession,
    _: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> TenantSummary:
    rows = await service.tenant_overview(session, tenant_id=tenant_id)
    if not rows:
        raise ProblemError.not_found("Client")
    return TenantSummary.model_validate(rows[0])


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


# --- Knowledge base: the MUTATING half (FLOWS §7) ------------------------------
# These live on the admin router, not the client one, because of D-22: an admin
# reaching a tenant does so by impersonation, and impersonation is read-only. The
# tenant is therefore named in the path rather than inferred from a session, which
# also makes every approval self-documenting in the audit log.


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class PublishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    version: int
    status: str


@router.post(
    "/tenants/{tenant_id}/kb/{source_id}/approve",
    openapi_extra=permission_meta("agents:write"),
    summary="Approval gate (D-28: stays ours whichever RAG provider wins)",
)
async def approve_kb(
    tenant_id: UUID,
    source_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> dict[str, str]:
    async with tenant_session(tenant_id) as scoped:
        await kb_service.approve_source(scoped, source_id=source_id, approved_by=principal.user_id)
    await write_audit(
        session,
        action="kb.approved",
        actor=principal,
        tenant_id=tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=request.client.host if request.client else None,
    )
    return {"status": "approved"}


@router.post(
    "/tenants/{tenant_id}/kb/{source_id}/reject",
    openapi_extra=permission_meta("agents:write"),
)
async def reject_kb(
    tenant_id: UUID,
    source_id: UUID,
    payload: RejectIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> dict[str, str]:
    async with tenant_session(tenant_id) as scoped:
        await kb_service.reject_source(scoped, source_id=source_id, reason=payload.reason)
    await write_audit(
        session,
        action="kb.rejected",
        actor=principal,
        tenant_id=tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=request.client.host if request.client else None,
        summary={"reason": payload.reason},
    )
    return {"status": "rejected"}


@router.post(
    "/tenants/{tenant_id}/kb/{source_id}/publish",
    response_model=PublishOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Push to the engine KB and make this the active version",
    description="Rollback is republishing an earlier version (FLOWS §7).",
)
async def publish_kb(
    tenant_id: UUID,
    source_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> PublishOut:
    async with tenant_session(tenant_id) as scoped:
        version = await kb_service.publish_source(scoped, tenant_id=tenant_id, source_id=source_id)
    await write_audit(
        session,
        action="kb.published",
        actor=principal,
        tenant_id=tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=request.client.host if request.client else None,
        summary={"version": version},
    )
    return PublishOut(source_id=source_id, version=version, status="live")


class MarginOut(BaseModel):
    """Per-client margin (D-12).

    Every money field is a STRING: the values are `Decimal` (hard rule 7) and the route
    stringifies them at the boundary, because a JSON float cannot hold a rupee amount
    exactly. They must stay strings all the way to the screen.
    """

    model_config = ConfigDict(extra="forbid")

    month: str
    minutes_used: str
    calls: int
    revenue_inr: str
    cost_inr: str
    margin_inr: str
    # None rather than "0.0" when nothing has been billed: "0% margin" and "nothing
    # billed yet" are different facts, and an operator acts differently on each.
    margin_pct: str | None


@router.get(
    "/tenants/{tenant_id}/margin",
    response_model=MarginOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Revenue vs OUR cost for one client (D-12) — the number G2 gates on",
)
async def tenant_margin(
    tenant_id: UUID,
    session: AdminSession,
    month: str | None = None,
    _: Principal = Depends(requires("billing:read", realm="admin")),
) -> MarginOut:
    """Admin realm only. `unit_cost_paid` is our supplier pricing — it is the reason
    this lives here and not beside the client's usage panel.

    Runs under a tenant-scoped session because `usage_events` is RLS'd and stays that
    way: `app.admin` opens the client DIRECTORY, never their data (migration
    b57e2f9c4a13). An operator reads one client's numbers by entering that client's
    scope deliberately, exactly like impersonation does for pages.
    """
    async with tenant_session(tenant_id) as scoped:
        margin = await billing.margin_for_tenant(scoped, tenant_id=tenant_id, month=month)
    del session
    return MarginOut.model_validate(
        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in margin.items()}
    )


# --------------------------------------------------------- campaign prerequisites
#
# Numbers and DLT templates are what the campaign launch gate checks (SEC-COMP §3),
# and both are OUR operational work: we buy the number, we file the template with the
# registrar under the client's PE. The client realm can read them (to pick one) but
# never write them — a client who could mark their own template "approved" would be
# launching under a registration that does not exist.


class ProvisionNumberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    e164: str = Field(min_length=8, max_length=20, pattern=r"^\+[1-9]\d{7,18}$")
    # The series decides what the number may lawfully dial (DATA-MODEL §6).
    series: Literal["140", "160", "standard"]
    agent_id: UUID | None = None
    provider: str | None = Field(default=None, max_length=60)
    purpose: str | None = Field(default=None, max_length=120)


class NumberCreatedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    e164: str
    series: str
    dlt_status: str


class DltStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dlt_status: Literal["pending", "registered", "blocked"]


class RegisterTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Literal["promotional", "transactional", "service"]
    body: str = Field(min_length=10, max_length=2000)
    dlt_ref: str | None = Field(default=None, max_length=120)


class TemplateStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["draft", "submitted", "approved", "rejected"]
    dlt_ref: str | None = Field(default=None, max_length=120)


class DltRegistrationIn(BaseModel):
    """What the registrar says about THIS CLIENT's Principal Entity (SEC-COMP §3).

    Two statuses rather than one `ready` flag, because they fail separately and the
    next action differs: an unregistered entity is a ₹5,900 registration we execute for
    them, a missing TM link is an authorisation only they can grant. The launch gate
    names them separately for the same reason.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_started", "submitted", "active", "suspended", "rejected"]
    tm_link_status: Literal["not_linked", "pending", "active", "revoked"]
    # The registrar's PE id. Required for `active` by a DB CHECK — an active
    # registration that cannot say which registration it is, is a claim, not a fact.
    pe_id: str | None = Field(default=None, max_length=120)
    entity_name: str | None = Field(default=None, max_length=200)
    registered_at: datetime | None = None


class DltRegistrationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    status: str
    tm_link_status: str
    pe_id: str | None


@router.post(
    "/tenants/{tenant_id}/numbers",
    response_model=NumberCreatedOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Provision a calling number — the series is the compliance-bearing field",
)
async def provision_number(
    tenant_id: UUID,
    payload: ProvisionNumberIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> NumberCreatedOut:
    async with tenant_session(tenant_id) as scoped:
        number_id = await agents_service.provision_number(
            scoped,
            tenant_id=tenant_id,
            e164=payload.e164,
            series=payload.series,
            agent_id=payload.agent_id,
            provider=payload.provider,
            purpose=payload.purpose,
        )
    await write_audit(
        session,
        action="number.provisioned",
        actor=principal,
        tenant_id=tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=request.client.host if request.client else None,
        # The series, never the number itself (hard rule 6).
        summary={"series": payload.series},
    )
    return NumberCreatedOut(
        id=number_id, e164=payload.e164, series=payload.series, dlt_status="pending"
    )


@router.post(
    "/tenants/{tenant_id}/numbers/{number_id}/dlt-status",
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record what the DLT registrar decided about this number",
)
async def set_number_dlt_status(
    tenant_id: UUID,
    number_id: UUID,
    payload: DltStatusIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> dict[str, str]:
    async with tenant_session(tenant_id) as scoped:
        await agents_service.set_number_dlt_status(
            scoped, number_id=number_id, dlt_status=payload.dlt_status
        )
    await write_audit(
        session,
        action="number.dlt_status_set",
        actor=principal,
        tenant_id=tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=request.client.host if request.client else None,
        summary={"dlt_status": payload.dlt_status},
    )
    return {"dlt_status": payload.dlt_status}


@router.post(
    "/tenants/{tenant_id}/dlt-templates",
    openapi_extra=permission_meta("admin:tenants"),
    status_code=201,
    summary="Register a voice template — created `submitted`, never `approved`",
)
async def register_template(
    tenant_id: UUID,
    payload: RegisterTemplateIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> dict[str, str]:
    async with tenant_session(tenant_id) as scoped:
        template_id = await campaigns_service.register_dlt_template(
            scoped,
            tenant_id=tenant_id,
            classification=payload.classification,
            body=payload.body,
            dlt_ref=payload.dlt_ref,
        )
    await write_audit(
        session,
        action="dlt_template.registered",
        actor=principal,
        tenant_id=tenant_id,
        object_type="dlt_template",
        object_id=str(template_id),
        ip=request.client.host if request.client else None,
        summary={"classification": payload.classification},
    )
    return {"id": str(template_id), "status": "submitted"}


@router.post(
    "/tenants/{tenant_id}/dlt-templates/{template_id}/status",
    openapi_extra=permission_meta("admin:tenants"),
    summary="Approve or reject per the registrar — `approved` unlocks the launch gate",
)
async def set_template_status(
    tenant_id: UUID,
    template_id: UUID,
    payload: TemplateStatusIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> dict[str, str]:
    async with tenant_session(tenant_id) as scoped:
        await campaigns_service.set_template_status(
            scoped, template_id=template_id, status=payload.status, dlt_ref=payload.dlt_ref
        )
    await write_audit(
        session,
        action="dlt_template.status_set",
        actor=principal,
        tenant_id=tenant_id,
        object_type="dlt_template",
        object_id=str(template_id),
        ip=request.client.host if request.client else None,
        summary={"status": payload.status},
    )
    return {"status": payload.status}


@router.post(
    "/tenants/{tenant_id}/dlt-registration",
    response_model=DltRegistrationOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record the client's DLT Principal Entity registration and its Calevate TM link",
    description=(
        "The third registration in the same family as the number header and the voice "
        "template, and the one the campaign launch gate reads as `pe_registration_*` / "
        "`tm_link_not_active`. Upserts: re-recording is what happens every time we "
        "re-verify with the registrar."
    ),
)
async def record_dlt_registration(
    tenant_id: UUID,
    payload: DltRegistrationIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> DltRegistrationOut:
    """The operator surface `campaigns.service.record_dlt_registration` was written for.

    It shipped with no route at all — deliberately none for CLIENTS, since a client who
    could mark their own PE registration `active` would be marking the launch gate green
    on a registration that does not exist — but with nothing for OPS either, which left
    the fact settable only by hand-written SQL against production. Same family, same
    permission and same shape as `set_number_dlt_status` and `set_template_status`
    above: `admin:tenants`, tenant named in the PATH, work done inside
    `tenant_session(tenant_id)` so RLS is what isolates it.

    The tenant-in-path form is not a style choice. An admin-realm mutation that infers
    its tenant from the session is un-callable by construction (D-22 refuses every
    mutating permission while impersonating, and without the header an admin principal
    has no tenant at all) — the failure this repo has already hit twice, now pinned by
    `tests/route_shape_test.py::test_no_admin_realm_mutation_infers_its_tenant_from_the_session`.
    """
    if payload.status == "active" and not (payload.pe_id or "").strip():
        # `ck_dlt_registrations_active_registration_names_its_pe` would refuse this in
        # the database; caught here so the operator gets a problem+json naming the
        # missing field instead of a 500 out of an IntegrityError.
        raise ProblemError(
            kind="validation",
            code="pe_registration_id_required",
            title="A registration number is required",
            detail="Recording a PE registration as active needs the registrar's PE id.",
            remediation="Send pe_id with the registration number the registrar issued.",
        )
    async with tenant_session(tenant_id) as scoped:
        await campaigns_service.record_dlt_registration(
            scoped,
            tenant_id=tenant_id,
            pe_id=payload.pe_id,
            entity_name=payload.entity_name,
            status=payload.status,
            tm_link_status=payload.tm_link_status,
            registered_at=payload.registered_at,
        )
    await write_audit(
        session,
        action="dlt_registration.recorded",
        actor=principal,
        tenant_id=tenant_id,
        object_type="dlt_registration",
        object_id=str(tenant_id),
        ip=request.client.host if request.client else None,
        # The registrar's identifiers are the client's own business identity, not PII
        # under hard rule 6 — and the PE id is the whole point of the audit row: it is
        # what a regulator asks us to evidence.
        summary={
            "status": payload.status,
            "tm_link_status": payload.tm_link_status,
            "pe_id": payload.pe_id,
        },
    )
    return DltRegistrationOut(
        tenant_id=tenant_id,
        status=payload.status,
        tm_link_status=payload.tm_link_status,
        pe_id=payload.pe_id,
    )


__all__ = ["router"]
