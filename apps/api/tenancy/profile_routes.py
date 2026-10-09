"""The business profile, as the client reads and edits it (D-695).

    GET   /v1/business-profile         the profile, setup progress and what blocks going live
    PATCH /v1/business-profile         replace the sections sent; every agent is updated
    POST  /v1/business-profile/setup   start, skip a step, dismiss or reopen the setup

    GET   /v1/admin/tenants/{tenant_id}/business-profile   the same, for the operator console

Reading is `org:read`, so staff see what the agents say. Writing is `org:manage`, which a
view-as session may exercise (`rbac.VIEW_AS_MUTATIONS`), so an operator can fix a profile
while on the phone with the client; every write is audited with section names and counts,
never the answers (hard rule 6).

The legal business name is shown beside the trading name and is NOT editable here: the
verification record is the legal identity (`compliance/kyc.py`), and this screen only
reads it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.languages import Language
from apps.api.compliance.audit import write_audit
from apps.api.compliance.kyc import read_kyc
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.tenancy import business_profile as bp
from apps.api.tenancy.models import PROFILE_STEPS
from apps.api.tenancy.profile_service import ProfilePatch, SetupAction, record_setup, save_profile

router = APIRouter(prefix="/v1/business-profile", tags=["business-profile"])
admin_router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/business-profile", tags=["admin"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Writer = Annotated[Principal, Depends(requires("org:manage"))]
AdminReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileSetupStepOut(_Out):
    id: bp.StepId
    state: Literal["done", "skipped", "todo"]


class ProfileSetupOut(_Out):
    steps: list[ProfileSetupStepOut]
    started: bool
    dismissed: bool
    #: Every step answered or skipped.
    complete: bool


class ProfileBlockerOut(_Out):
    """Something an agent needs before it can go live, and the setup step that fixes it."""

    code: str
    step: bp.StepId
    message: str


class BusinessProfileOut(_Out):
    business_name: str
    #: The name on the business's verification, when one is on file. Read-only here.
    legal_name: str | None
    #: The business type, for examples that fit this trade.
    vertical_template: str | None
    #: The answered days only, Monday first. A day absent here is not answered yet; a
    #: day with `closed` true is closed.
    hours: list[bp.DayHours]
    branches: list[bp.Branch]
    services: list[bp.ServiceItem]
    faqs: list[bp.Faq]
    staff: list[bp.StaffMember]
    booking_rules: str | None
    contacts: list[bp.BusinessContactOut]
    languages: list[Language]
    setup: ProfileSetupOut
    blockers: list[ProfileBlockerOut]
    updated_at: datetime | None
    #: On a save: how many agents got the change. Null on a read.
    agents_updated: int | None = None


class AdminBusinessProfileOut(BusinessProfileOut):
    #: Where the move from per-agent answers found two agents disagreeing: the value kept
    #: and the values set aside. Operators only.
    merge_notes: list[dict[str, Any]]


class ProfileSetupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: SetupAction
    #: Required for `skip`, ignored otherwise.
    step: bp.StepId | None = None


def _hours_out(hours: dict[str, dict[str, str] | None]) -> list[bp.DayHours]:
    out: list[bp.DayHours] = []
    for day in bp.DAYS:
        if day not in hours:
            continue
        window = hours[day]
        out.append(
            bp.DayHours(day=day, closed=True)
            if window is None
            else bp.DayHours(day=day, opens=window["opens"], closes=window["closes"])
        )
    return out


async def render(session: AsyncSession, *, tenant_id: UUID) -> dict[str, Any]:
    """The whole read, as the fields both realms' models share."""
    profile = await bp.load_profile(session, tenant_id=tenant_id)
    org = (
        await session.execute(
            text("SELECT name, vertical_template FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if org is None:
        raise ProblemError.not_found("Organization")
    kyc = await read_kyc(session, tenant_id=tenant_id)
    return {
        "business_name": str(org[0]),
        "vertical_template": org[1],
        "legal_name": kyc.legal_business_name,
        "hours": _hours_out(profile.hours),
        "branches": profile.branches,
        "services": profile.services,
        "faqs": profile.faqs,
        "staff": profile.staff,
        "booking_rules": profile.booking_rules,
        "contacts": [
            bp.BusinessContactOut(id=c.id, label=c.label, phone_e164=c.phone_e164, note=c.note)
            for c in profile.contacts
        ],
        "languages": profile.languages,
        "setup": ProfileSetupOut(
            steps=[
                ProfileSetupStepOut(id=step, state=bp.step_state(profile, step))  # type: ignore[arg-type]
                for step in PROFILE_STEPS
            ],
            started=profile.setup_started_at is not None,
            dismissed=profile.setup_dismissed_at is not None,
            complete=bp.setup_complete(profile),
        ),
        "blockers": [
            ProfileBlockerOut(code=code, step=bp.BLOCKER_STEPS[code], message=bp.BLOCKER_COPY[code])
            for code in bp.go_live_blockers(profile)
        ],
        "updated_at": profile.updated_at,
        "merge_notes": profile.merge_notes,
    }


def _client_out(fields: dict[str, Any], *, agents_updated: int | None = None) -> BusinessProfileOut:
    fields = {k: v for k, v in fields.items() if k != "merge_notes"}
    return BusinessProfileOut(**fields, agents_updated=agents_updated)


@router.get(
    "",
    response_model=BusinessProfileOut,
    summary="The business profile every agent reads, with setup progress",
    openapi_extra=permission_meta("org:read"),
)
async def get_business_profile(session: Session, principal: Reader) -> BusinessProfileOut:
    assert principal.tenant_id is not None
    return _client_out(await render(session, tenant_id=principal.tenant_id))


@router.patch(
    "",
    response_model=BusinessProfileOut,
    summary="Replace the sections sent; every agent of the business is updated",
    openapi_extra=permission_meta("org:manage"),
)
async def patch_business_profile(
    payload: ProfilePatch,
    session: Session,
    principal: Writer,
    request: Request,
) -> BusinessProfileOut:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    steps, updated = await save_profile(
        session, tenant_id=tenant_id, patch=payload, user_id=principal.client_user_id
    )
    await write_audit(
        session,
        actor=principal,
        action="business_profile.updated",
        tenant_id=tenant_id,
        object_type="organization",
        object_id=str(tenant_id),
        ip=client_request_ip(request),
        summary={"sections": sorted(steps), "agents_updated": updated},
    )
    return _client_out(await render(session, tenant_id=tenant_id), agents_updated=updated)


@router.post(
    "/setup",
    response_model=BusinessProfileOut,
    summary="Move the setup wizard: start it, skip a step, dismiss or reopen the checklist",
    openapi_extra=permission_meta("org:manage"),
)
async def post_setup(
    payload: ProfileSetupIn,
    session: Session,
    principal: Writer,
    request: Request,
) -> BusinessProfileOut:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    await record_setup(session, tenant_id=tenant_id, action=payload.action, step=payload.step)
    await write_audit(
        session,
        actor=principal,
        action="business_profile.setup",
        tenant_id=tenant_id,
        object_type="organization",
        object_id=str(tenant_id),
        ip=client_request_ip(request),
        summary={"action": payload.action, "step": payload.step},
    )
    return _client_out(await render(session, tenant_id=tenant_id))


@admin_router.get(
    "",
    response_model=AdminBusinessProfileOut,
    summary="A client's business profile, for the operator console",
    openapi_extra=permission_meta("org:read"),
)
async def admin_get_business_profile(
    tenant_id: UUID,
    request: Request,
    principal: AdminReader,
) -> AdminBusinessProfileOut:
    """Read-only. An operator edits the profile through view-as, where the same writes
    and the same audit apply. Audited as an admin read: it holds staff names and mobiles."""
    async with tenant_session(tenant_id) as scoped:
        fields = await render(scoped, tenant_id=tenant_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return AdminBusinessProfileOut(**fields)


__all__ = ["admin_router", "router"]
