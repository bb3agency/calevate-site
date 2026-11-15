"""The company training page: the owner's overview, materials, the training every agent is
given and Pip's pending draft of it. `agents/company_training.py` holds the rules."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import company_training as training_rules
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.kb import uploads as kb_uploads
from apps.api.kb.curation import goes_live_without_review, requires_kb_curation
from apps.api.teach.routes import read_bounded_upload

router = APIRouter(prefix="/v1/company-training", tags=["company-training"])
Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("agents:read"))]
#: The same permission as editing an agent's script: the training reaches every agent's calls.
Writer = Annotated[Principal, Depends(requires("org:manage"))]
KbWriter = Annotated[Principal, Depends(requires_kb_curation())]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrainingMaterialOut(_Out):
    id: UUID
    kind: Literal["file", "link", "note"]
    title: str
    url: str | None
    note: str | None
    kb_upload_id: UUID | None
    created_at: datetime


class TrainingProposalOut(_Out):
    id: UUID
    status: Literal["drafting", "ready", "failed"]
    requested_at: datetime
    #: The training it was written from (null for the first one).
    base_training: str | None
    training: str | None
    note: str | None
    #: Who wrote it when it was not the account's own model (D-127 G-6), shown beside it.
    disclosure: str | None
    #: Failed: why (a refusal code, `crashed` or `stale`), so the screen can say what to do.
    reason: str | None


class CompanyTrainingOut(_Out):
    overview: str
    #: What every agent is given, ahead of its own script.
    training: str
    #: Moves on every save of the training; 0 before the first.
    version: int
    #: When the training was last saved; null before the first save.
    updated_at: datetime | None
    proposal: TrainingProposalOut | None
    materials: list[TrainingMaterialOut]
    overview_max: int
    training_max: int


def _material(m: training_rules.Material) -> TrainingMaterialOut:
    return TrainingMaterialOut(
        id=m.id,
        kind=m.kind,  # type: ignore[arg-type]
        title=m.title,
        url=m.url,
        note=m.note,
        kb_upload_id=m.kb_upload_id,
        created_at=m.created_at,
    )


def _proposal(p: training_rules.TrainingProposal | None) -> TrainingProposalOut | None:
    if p is None:
        return None
    return TrainingProposalOut(
        id=p.id,
        status=p.status,
        requested_at=p.requested_at,
        base_training=p.base_training,
        training=p.training,
        note=p.note,
        disclosure=p.disclosure,
        reason=p.reason,
    )


async def _out(session: AsyncSession, tenant_id: UUID) -> CompanyTrainingOut:
    t = await training_rules.read_training(session, tenant_id)
    return CompanyTrainingOut(
        overview=t.overview,
        training=t.training,
        version=t.version,
        updated_at=t.updated_at,
        proposal=_proposal(t.proposal),
        materials=[_material(m) for m in t.materials],
        overview_max=training_rules.OVERVIEW_MAX,
        training_max=training_rules.TRAINING_MAX,
    )


def _tenant(principal: Principal) -> UUID:
    assert principal.tenant_id is not None
    return principal.tenant_id


@router.get(
    "",
    response_model=CompanyTrainingOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The company training every agent is given, its materials and Pip's draft",
)
async def read_company_training(session: Session, principal: Reader) -> CompanyTrainingOut:
    return await _out(session, _tenant(principal))


class OverviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overview: str = Field(max_length=training_rules.OVERVIEW_MAX)


@router.put(
    "/overview",
    response_model=CompanyTrainingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Save the owner's description of the business, which Pip writes the training from",
)
async def save_overview(
    payload: OverviewIn, session: Session, principal: Writer
) -> CompanyTrainingOut:
    tenant_id = _tenant(principal)
    await training_rules.save_overview(session, tenant_id, payload.overview)
    return await _out(session, tenant_id)


class TrainingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    training: str = Field(max_length=training_rules.TRAINING_MAX)
    #: The draft this save keeps, cleared in the same transaction.
    proposal_id: UUID | None = None


@router.put(
    "/training",
    response_model=CompanyTrainingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Save the training; every agent is brought onto it",
)
async def save_training(
    payload: TrainingIn, session: Session, request: Request, principal: Writer
) -> CompanyTrainingOut:
    tenant_id = _tenant(principal)
    version = await training_rules.save_training(
        session, tenant_id, payload.training, saved_by=principal.user_id
    )
    if payload.proposal_id is not None:
        await training_rules.clear_proposal(session, tenant_id, payload.proposal_id)
    await write_audit(
        session,
        action="company_training.saved",
        actor=principal,
        tenant_id=tenant_id,
        object_type="company_training",
        object_id=str(tenant_id),
        ip=client_request_ip(request),
        summary={"version": version, "from_draft": payload.proposal_id is not None},
    )
    return await _out(session, tenant_id)


class TrainingMaterialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["file", "link", "note"]
    title: str = Field(min_length=1, max_length=training_rules.TITLE_MAX)
    url: str | None = Field(default=None, max_length=2_000)
    note: str | None = Field(default=None, max_length=training_rules.NOTE_MAX)
    #: The upload (`POST /v1/kb/uploads` or `/v1/kb/links`) a file or link is held in.
    kb_upload_id: UUID | None = None


@router.post(
    "/materials",
    response_model=TrainingMaterialOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Add a document, link or note for the training to be written from",
)
async def add_material(
    payload: TrainingMaterialIn, session: Session, principal: Writer
) -> TrainingMaterialOut:
    material = await training_rules.add_material(
        session,
        tenant_id=_tenant(principal),
        kind=payload.kind,
        title=payload.title,
        url=payload.url,
        note=payload.note,
        kb_upload_id=payload.kb_upload_id,
        created_by=principal.user_id,
    )
    return _material(material)


@router.post(
    "/materials/upload",
    response_model=TrainingMaterialOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Upload a file for the training; a file already in the knowledge is reused",
)
async def upload_material(
    session: Session,
    request: Request,
    file: Annotated[UploadFile, File()],
    principal: KbWriter,
    title: Annotated[str | None, Form(max_length=training_rules.TITLE_MAX)] = None,
) -> TrainingMaterialOut:
    """The file goes into the client's knowledge exactly as `POST /v1/kb/uploads` puts it,
    unless these exact bytes are already live there: then that upload is attached instead of
    being refused as a duplicate, as a campaign's materials are (D-992)."""
    tenant_id = _tenant(principal)
    data = await read_bounded_upload(file, kb_uploads.MAX_UPLOAD_BYTES)
    upload_id = await kb_uploads.live_duplicate_of(session, tenant_id=tenant_id, data=data)
    if upload_id is None:
        made = await kb_uploads.create_upload(
            session,
            tenant_id=tenant_id,
            name=None,
            filename=file.filename or "document",
            content_type=file.content_type,
            data=data,
            submitted_by=principal.user_id,
            auto_approve=goes_live_without_review(
                realm=principal.realm, impersonating=principal.impersonating
            ),
        )
        upload_id = UUID(str(made["id"]))
        await write_audit(
            session,
            action="kb.uploaded",
            actor=principal,
            tenant_id=tenant_id,
            object_type="kb_source",
            object_id=str(made["source_id"]),
            ip=client_request_ip(request),
            summary={"upload_id": str(upload_id), "via": "company_training_material"},
        )
    material = await training_rules.add_material(
        session,
        tenant_id=tenant_id,
        kind="file",
        title=(title or "").strip() or (file.filename or "Document"),
        url=None,
        note=None,
        kb_upload_id=upload_id,
        created_by=principal.user_id,
    )
    return _material(material)


@router.post(
    "/materials/{training_material_id}/archive",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Remove a material from the training (archived, not deleted)",
)
async def archive_material(training_material_id: UUID, session: Session, _: Writer) -> None:
    await training_rules.archive_material(session, training_material_id)


@router.post(
    "/proposal",
    response_model=TrainingProposalOut,
    status_code=202,
    openapi_extra=permission_meta("org:manage"),
    summary="Ask Pip to write the training from the overview and materials",
)
async def request_proposal(
    session: Session, request: Request, principal: Writer
) -> TrainingProposalOut:
    tenant_id = _tenant(principal)
    # Writing the training spends the account's dashboard AI allowance, as a campaign's
    # script does: refused at the ceiling or under view-as, before anything is queued.
    assert_view_as_may(principal, "billing.ai_assist")
    await require_ai_assist(session, tenant_id=tenant_id)
    proposal = await training_rules.request_proposal(
        session, tenant_id=tenant_id, requested_by=principal.user_id
    )
    await write_audit(
        session,
        action="company_training.requested",
        actor=principal,
        tenant_id=tenant_id,
        object_type="company_training",
        object_id=str(tenant_id),
        ip=client_request_ip(request),
        summary={"proposal_id": str(proposal.id)},
    )
    out = _proposal(proposal)
    assert out is not None
    return out


@router.delete(
    "/proposal/{training_proposal_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Stop Pip's draft while it is written, or discard it",
)
async def clear_proposal(training_proposal_id: UUID, session: Session, principal: Writer) -> None:
    await training_rules.clear_proposal(session, _tenant(principal), training_proposal_id)
