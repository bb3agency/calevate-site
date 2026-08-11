"""Campaign endpoints (FLOWS §5, SURFACES §2).

The route worth reading is `/launch-check`: it exists so the UI can render the launch
button DISABLED WITH REASONS before anyone clicks it. `POST /launch` re-runs the same
check and refuses with the same names — the check endpoint is a preview of the gate,
never a substitute for it.

D-21's boundary applies: campaign creation and launch are OWNER actions in the client
realm (`leads:dispatch` — it places calls, so it carries the dispatch permission, not
a new one).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])

Session = Annotated[AsyncSession, Depends(db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateCampaignIn(Strict):
    agent_id: UUID
    name: str = Field(min_length=2, max_length=120)
    classification: Literal["promotional", "transactional", "service"]
    number_id: UUID | None = None
    dlt_template_id: UUID | None = None
    concurrency: int = Field(default=3, ge=1, le=10)


class CreateCampaignOut(Strict):
    id: UUID
    status: str


class ContactIn(Strict):
    phone: str = Field(min_length=8, max_length=20)
    name: str | None = Field(default=None, max_length=120)
    # Extra per-contact variables rendered into the agent prompt (Bolna user_data).
    custom: dict[str, str] = Field(default_factory=dict)


class AddContactsIn(Strict):
    contacts: list[ContactIn] = Field(min_length=1, max_length=5000)


class AddContactsOut(Strict):
    added: int
    malformed: int
    duplicate: int


class BlockerOut(Strict):
    rule: str
    reason: str


class LaunchCheckOut(Strict):
    ready: bool
    blockers: list[BlockerOut]


class LaunchOut(Strict):
    status: str
    dialable: int
    dnc_scrubbed: int


class ProgressOut(Strict):
    status: str
    launched_at: datetime | None
    concurrency: int
    contacts: dict[str, int]
    total: int


class CampaignSummaryOut(Strict):
    id: UUID
    name: str
    classification: str
    status: str
    contacts: int
    connected: int
    launched_at: datetime | None
    created_at: datetime


class NumberOut(Strict):
    id: UUID
    e164: str
    series: str
    dlt_status: str


class TemplateOut(Strict):
    id: UUID
    classification: str
    status: str
    body: str


@router.get(
    "",
    response_model=list[CampaignSummaryOut],
    openapi_extra=permission_meta("leads:read"),
    summary="Every campaign, newest first — a launched campaign must be findable later",
)
async def list_campaigns(
    session: Session,
    _: Principal = Depends(requires("leads:read")),
) -> list[CampaignSummaryOut]:
    rows = await service.list_campaigns(session)
    return [CampaignSummaryOut.model_validate(row) for row in rows]


# NOTE: these two are declared BEFORE `/{campaign_id}` on purpose — FastAPI matches in
# declaration order, and `/numbers` would otherwise be parsed as a campaign id.
@router.get(
    "/numbers",
    response_model=list[NumberOut],
    openapi_extra=permission_meta("org:read"),
    summary="Numbers this tenant may dial from, with their series (140/160/standard)",
)
async def list_numbers(
    session: Session,
    _: Principal = Depends(requires("org:read")),
) -> list[NumberOut]:
    rows = (
        await session.execute(
            text("SELECT id, e164, series, dlt_status FROM phone_numbers ORDER BY created_at")
        )
    ).all()
    return [NumberOut(id=r[0], e164=r[1], series=r[2], dlt_status=r[3]) for r in rows]


@router.get(
    "/templates",
    response_model=list[TemplateOut],
    openapi_extra=permission_meta("org:read"),
    summary="DLT voice templates, so the launch gate's requirement is selectable",
)
async def list_templates(
    session: Session,
    _: Principal = Depends(requires("org:read")),
) -> list[TemplateOut]:
    rows = (
        await session.execute(
            text(
                "SELECT id, classification, status, body FROM dlt_templates "
                "WHERE kind = 'voice' ORDER BY created_at"
            )
        )
    ).all()
    return [TemplateOut(id=r[0], classification=r[1], status=r[2], body=r[3]) for r in rows]


@router.post(
    "",
    response_model=CreateCampaignOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
)
async def create_campaign(
    payload: CreateCampaignIn,
    session: Session,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> CreateCampaignOut:
    assert principal.tenant_id is not None
    campaign_id = await service.create_campaign(
        session,
        tenant_id=principal.tenant_id,
        agent_id=payload.agent_id,
        name=payload.name,
        classification=payload.classification,
        number_id=payload.number_id,
        dlt_template_id=payload.dlt_template_id,
        concurrency=payload.concurrency,
    )
    return CreateCampaignOut(id=campaign_id, status="draft")


@router.post(
    "/{campaign_id}/contacts",
    response_model=AddContactsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="CSV rows in — deduped, validated, malformed numbers counted not guessed",
)
async def add_contacts(
    campaign_id: UUID,
    payload: AddContactsIn,
    session: Session,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> AddContactsOut:
    assert principal.tenant_id is not None
    result = await service.add_contacts(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        contacts=[{"phone": c.phone, "name": c.name, **c.custom} for c in payload.contacts],
    )
    return AddContactsOut.model_validate(result)


@router.get(
    "/{campaign_id}/launch-check",
    response_model=LaunchCheckOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Why the launch button is disabled, by name (SEC-COMP §3)",
)
async def launch_check(
    campaign_id: UUID,
    session: Session,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> LaunchCheckOut:
    assert principal.tenant_id is not None
    blockers = await service.launch_blockers(
        session, tenant_id=principal.tenant_id, campaign_id=campaign_id
    )
    return LaunchCheckOut(
        ready=not blockers,
        blockers=[BlockerOut(rule=b.rule, reason=b.reason) for b in blockers],
    )


@router.post(
    "/{campaign_id}/launch",
    response_model=LaunchOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="The compliance gate, then the DNC scrub, then running (hard rule 5)",
)
async def launch(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> LaunchOut:
    assert principal.tenant_id is not None
    result = await service.launch_campaign(
        session, tenant_id=principal.tenant_id, campaign_id=campaign_id
    )
    await write_audit(
        session,
        action="campaign.launched",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=request.client.host if request.client else None,
        summary={"dialable": result["dialable"], "dnc_scrubbed": result["dnc_scrubbed"]},
    )
    return LaunchOut.model_validate(result)


@router.post(
    "/{campaign_id}/pause",
    openapi_extra=permission_meta("leads:dispatch"),
)
async def pause(
    campaign_id: UUID,
    session: Session,
    _: Principal = Depends(requires("leads:dispatch")),
) -> dict[str, str]:
    await service.set_campaign_status(
        session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
    )
    return {"status": "paused"}


@router.post(
    "/{campaign_id}/resume",
    openapi_extra=permission_meta("leads:dispatch"),
)
async def resume(
    campaign_id: UUID,
    session: Session,
    _: Principal = Depends(requires("leads:dispatch")),
) -> dict[str, str]:
    await service.set_campaign_status(
        session, campaign_id=campaign_id, to_status="running", from_statuses=("paused",)
    )
    return {"status": "running"}


@router.get(
    "/{campaign_id}",
    response_model=ProgressOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Live progress: dispatched / connected / failed / no-answer (FLOWS §5)",
)
async def progress(
    campaign_id: UUID,
    session: Session,
    _: Principal = Depends(requires("leads:read")),
) -> ProgressOut:
    result: dict[str, Any] = await service.campaign_progress(session, campaign_id)
    return ProgressOut.model_validate(result)


__all__ = ["router"]
