"""How they speak (the company training): the owner's overview, the training every agent is
given, and Pip's background write of it, shown as a tab of What your agents know. Pip writes
it on its own (D-1034); the owner may edit it, and may ask for a rewrite now. Material to write
it from is added to the knowledge itself. `agents/company_training.py` holds the rules."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import company_training as training_rules
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import problem_responses
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/company-training", tags=["company-training"])
Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("agents:read"))]
#: The same permission as editing an agent's script: the training reaches every agent's calls.
Writer = Annotated[Principal, Depends(requires("org:manage"))]

WriteReasonOut = training_rules.WriteReason


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrainingProposalOut(_Out):
    """Pip's pending write: waiting for changes to settle, writing, or failed."""

    id: UUID
    status: Literal["queued", "drafting", "failed"]
    requested_at: datetime
    #: When a queued write starts.
    due_at: datetime | None
    #: What it is written for.
    reasons: list[WriteReasonOut]
    note: str | None
    #: Failed: why (a refusal code, `ungrounded`, `too_long`, `crashed` or `stale`).
    reason: str | None


MissingPartOut = Literal["business", "offer", "customers"]


class LastWriteOut(_Out):
    """Pip's last saved write."""

    at: datetime
    reasons: list[WriteReasonOut]
    #: The owner's own edits it carried.
    owner_edits_kept: int
    #: Owner's facts newer knowledge replaced, as the owner wrote them.
    superseded: list[str]
    shortened: bool
    #: Who wrote it when it was not the account's own model (D-127 G-6), shown beside it.
    disclosure: str | None
    #: What the knowledge did not say well enough to write without guessing; the owner is
    #: asked for a source that says it.
    missing: list[MissingPartOut] = Field(default_factory=list)


class CompanyTrainingOut(_Out):
    overview: str
    #: What every agent is given, ahead of its own script.
    training: str
    #: Moves on every save of the training; 0 before the first.
    version: int
    #: When the training was last saved; null before the first save.
    updated_at: datetime | None
    proposal: TrainingProposalOut | None
    last_write: LastWriteOut | None
    #: The training holds the owner's own edits, which Pip's next rewrite carries.
    owner_edited: bool
    overview_max: int
    training_max: int


def _reasons(values: tuple[str, ...]) -> list[WriteReasonOut]:
    return [cast(WriteReasonOut, r) for r in values if r in training_rules.WRITE_REASONS]


def _proposal(p: training_rules.TrainingProposal | None) -> TrainingProposalOut | None:
    if p is None:
        return None
    return TrainingProposalOut(
        id=p.id,
        status=p.status,
        requested_at=p.requested_at,
        due_at=p.due_at,
        reasons=_reasons(p.reasons),
        note=p.note,
        reason=p.reason,
    )


def _last_write(w: training_rules.LastWrite | None) -> LastWriteOut | None:
    if w is None:
        return None
    return LastWriteOut(
        at=w.at,
        reasons=_reasons(w.reasons),
        owner_edits_kept=w.owner_edits_kept,
        superseded=list(w.superseded),
        shortened=w.shortened,
        disclosure=w.disclosure,
        missing=[
            cast(MissingPartOut, m) for m in w.missing if m in ("business", "offer", "customers")
        ],
    )


async def _out(session: AsyncSession, tenant_id: UUID) -> CompanyTrainingOut:
    t = await training_rules.read_training(session, tenant_id)
    return CompanyTrainingOut(
        overview=t.overview,
        training=t.training,
        version=t.version,
        updated_at=t.updated_at,
        proposal=_proposal(t.proposal),
        last_write=_last_write(t.last_write),
        owner_edited=t.owner_edited,
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
    summary="The company training every agent is given and Pip's write of it",
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
    summary="Save the owner's description of the business; Pip rewrites the training from it",
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
    #: The version the edit began from; a save over a newer one is refused (409).
    version: int | None = Field(default=None, ge=0)


@router.put(
    "/training",
    response_model=CompanyTrainingOut,
    responses=problem_responses(training_rules.CompanyTrainingTooLong),
    openapi_extra=permission_meta("org:manage"),
    summary="Save the owner's edit of the training; every agent is brought onto it",
)
async def save_training(
    payload: TrainingIn, session: Session, request: Request, principal: Writer
) -> CompanyTrainingOut:
    tenant_id = _tenant(principal)
    version = await training_rules.save_training(
        session,
        tenant_id,
        payload.training,
        saved_by=principal.user_id,
        edited_version=payload.version,
    )
    await write_audit(
        session,
        action="company_training.saved",
        actor=principal,
        tenant_id=tenant_id,
        object_type="company_training",
        object_id=str(tenant_id),
        ip=client_request_ip(request),
        summary={"version": version},
    )
    return await _out(session, tenant_id)


@router.post(
    "/proposal",
    response_model=TrainingProposalOut,
    status_code=202,
    openapi_extra=permission_meta("org:manage"),
    summary="Ask Pip to rewrite the training now, from the business and its knowledge",
)
async def request_proposal(
    session: Session, request: Request, principal: Writer
) -> TrainingProposalOut:
    tenant_id = _tenant(principal)
    # Writing the training spends the account's dashboard AI allowance, as a campaign's
    # script does: refused at the ceiling or under view-as, before anything is queued.
    assert_view_as_may(principal, "billing.ai_assist")
    await require_ai_assist(session, tenant_id=tenant_id)
    proposal = await training_rules.request_rewrite(
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
    summary="Dismiss a write that failed, or stop one",
)
async def clear_proposal(training_proposal_id: UUID, session: Session, principal: Writer) -> None:
    await training_rules.clear_proposal(session, _tenant(principal), training_proposal_id)
