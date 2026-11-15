"""The campaign workspace: main task, materials, the campaign's script and Pip's draft of it,
and the questions its calls could not answer (D-992). `campaigns/workspace.py` holds the rules.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.trial_calls import attest_own_number, place_trial_call
from apps.api.campaigns import learning, workspace
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.kb import uploads as kb_uploads
from apps.api.kb.curation import goes_live_without_review, requires_kb_curation
from apps.api.reliability.service import require_idempotency_key
from apps.api.teach.routes import read_bounded_upload
from apps.api.teach.struggles import list_struggles

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])
Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("leads:read"))]
Dispatcher = Annotated[Principal, Depends(requires("leads:dispatch"))]
KbWriter = Annotated[Principal, Depends(requires_kb_curation())]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialOut(_Out):
    id: UUID
    kind: Literal["file", "link", "note"]
    #: `owner`, or `call` for a note learned from the campaign's own calls.
    source: Literal["owner", "call"]
    title: str
    url: str | None
    note: str | None
    kb_upload_id: UUID | None
    created_at: datetime


class CampaignProposalOut(_Out):
    id: UUID
    status: Literal["drafting", "ready", "failed"]
    requested_at: datetime
    #: The script it was written from (null for a campaign's first script).
    base_script: CallScript | None
    script: CallScript | None
    note: str | None


class WorkspaceOut(_Out):
    campaign_id: UUID
    agent_id: UUID
    status: str
    main_task: str
    script: CallScript | None
    #: The agent script version this campaign put live at its last Start.
    script_live_version: int | None
    proposal: CampaignProposalOut | None
    materials: list[MaterialOut]


def _material(m: workspace.Material) -> MaterialOut:
    return MaterialOut(
        id=m.id,
        kind=m.kind,  # type: ignore[arg-type]
        source=m.source,  # type: ignore[arg-type]
        title=m.title,
        url=m.url,
        note=m.note,
        kb_upload_id=m.kb_upload_id,
        created_at=m.created_at,
    )


def _proposal(p: workspace.CampaignProposal | None) -> CampaignProposalOut | None:
    if p is None:
        return None
    return CampaignProposalOut(
        id=p.id,
        status=p.status,
        requested_at=p.requested_at,
        base_script=p.base_script,
        script=p.script,
        note=p.note,
    )


async def _workspace_out(session: AsyncSession, campaign_id: UUID) -> WorkspaceOut:
    w = await workspace.read_workspace(session, campaign_id)
    return WorkspaceOut(
        campaign_id=w.campaign_id,
        agent_id=w.agent_id,
        status=w.status,
        main_task=w.main_task,
        script=w.script,
        script_live_version=w.script_live_version,
        proposal=_proposal(w.proposal),
        materials=[_material(m) for m in w.materials],
    )


@router.get(
    "/{campaign_id}/workspace",
    response_model=WorkspaceOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The campaign's main task, materials, script and Pip's pending draft",
)
async def read_workspace(campaign_id: UUID, session: Session, _: Reader) -> WorkspaceOut:
    return await _workspace_out(session, campaign_id)


class MainTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    main_task: str = Field(max_length=workspace.MAIN_TASK_MAX)


@router.put(
    "/{campaign_id}/main-task",
    response_model=WorkspaceOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Save what the campaign should achieve",
)
async def save_main_task(
    campaign_id: UUID,
    payload: MainTaskIn,
    session: Session,
    _: Dispatcher,
) -> WorkspaceOut:
    await workspace.save_main_task(session, campaign_id, payload.main_task)
    return await _workspace_out(session, campaign_id)


class ScriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script: CallScript


@router.put(
    "/{campaign_id}/script",
    response_model=WorkspaceOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Save the campaign's script (it reaches calls at Start)",
)
async def save_script(
    campaign_id: UUID,
    payload: ScriptIn,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> WorkspaceOut:
    assert principal.tenant_id is not None
    await workspace.save_script(session, campaign_id, payload.script)
    await write_audit(
        session,
        action="campaign.script_saved",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary={},
    )
    return await _workspace_out(session, campaign_id)


class MaterialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["file", "link", "note"]
    title: str = Field(min_length=1, max_length=workspace.TITLE_MAX)
    url: str | None = Field(default=None, max_length=2_000)
    note: str | None = Field(default=None, max_length=workspace.NOTE_MAX)
    #: The upload (`POST /v1/kb/uploads` or `/v1/kb/links`) a file or link is held in.
    kb_upload_id: UUID | None = None


@router.post(
    "/{campaign_id}/materials",
    response_model=MaterialOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Add a document, link or note for the campaign to work from",
)
async def add_material(
    campaign_id: UUID,
    payload: MaterialIn,
    session: Session,
    principal: Dispatcher,
) -> MaterialOut:
    assert principal.tenant_id is not None
    material = await workspace.add_material(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        kind=payload.kind,
        title=payload.title,
        url=payload.url,
        note=payload.note,
        kb_upload_id=payload.kb_upload_id,
        created_by=principal.user_id,
    )
    return _material(material)


@router.post(
    "/{campaign_id}/materials/{material_id}/archive",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Remove a material from the campaign (archived, not deleted)",
)
async def archive_material(
    campaign_id: UUID,
    material_id: UUID,
    session: Session,
    _: Dispatcher,
) -> None:
    await workspace.archive_material(session, campaign_id, material_id)


@router.post(
    "/{campaign_id}/script/proposal",
    response_model=CampaignProposalOut,
    status_code=202,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Ask Pip to write the campaign's script from its main task and materials",
)
async def request_proposal(
    campaign_id: UUID,
    session: Session,
    principal: Dispatcher,
) -> CampaignProposalOut:
    assert principal.tenant_id is not None
    proposal = await workspace.request_proposal(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        requested_by=principal.user_id,
    )
    out = _proposal(proposal)
    assert out is not None
    return out


@router.delete(
    "/{campaign_id}/script/proposal/{proposal_id}",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Stop Pip's draft while it is written, or discard it once reviewed",
)
async def clear_proposal(
    campaign_id: UUID,
    proposal_id: UUID,
    session: Session,
    _: Dispatcher,
) -> None:
    await workspace.clear_proposal(session, campaign_id, proposal_id)


class CampaignQuestionOut(_Out):
    id: UUID
    kind: Literal["didnt_know", "put_off", "unanswered", "needed_you"]
    topic: str
    #: What the caller asked and what the agent said, both redacted (hard rule 6).
    question: str | None
    answer: str | None
    times: int
    calls: int
    last_call_id: UUID | None
    last_seen_at: datetime


@router.get(
    "/{campaign_id}/questions",
    response_model=list[CampaignQuestionOut],
    openapi_extra=permission_meta("leads:read"),
    summary="What the agent could not answer on this campaign's calls",
)
async def campaign_questions(
    campaign_id: UUID, session: Session, _: Reader
) -> list[CampaignQuestionOut]:
    await workspace.read_workspace(session, campaign_id)
    return [
        CampaignQuestionOut(
            id=s.id,
            kind=s.kind,
            topic=s.topic,
            question=s.question,
            answer=s.answer,
            times=s.times,
            calls=s.calls,
            last_call_id=s.last_call_id,
            last_seen_at=s.last_seen_at,
        )
        for s in await list_struggles(session, campaign_id=campaign_id)
    ]


class CampaignAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=workspace.TITLE_MAX)
    answer: str = Field(min_length=1, max_length=workspace.NOTE_MAX)


@router.post(
    "/{campaign_id}/questions/answer",
    response_model=MaterialOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Answer a question the agent could not: kept as a note learned from the calls",
)
async def answer_question(
    campaign_id: UUID,
    payload: CampaignAnswerIn,
    session: Session,
    principal: Dispatcher,
) -> MaterialOut:
    """The answer joins the campaign's materials as a note learned from its calls, so the next
    script Pip writes works it in; the owner updates the script to put it on calls."""
    assert principal.tenant_id is not None
    material = await workspace.add_material(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        kind="note",
        title=payload.topic,
        url=None,
        note=payload.answer,
        kb_upload_id=None,
        created_by=principal.user_id,
        source="call",
    )
    return _material(material)


# --- What a campaign's calls teach it, its opening test and its test call (D-992) ----------

OPENING_B_MAX: Final = 200
_FORMATTING: Final = re.compile(r"[*#`_~|\[\]<>{}]")


class OpeningBIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The second opening line to test, or null to stop the test.
    opening_b: str | None = Field(default=None, max_length=OPENING_B_MAX)


@router.put(
    "/{campaign_id}/opening-b",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Test a second opening line against the script's own, or stop the test",
)
async def save_opening_b(
    campaign_id: UUID, payload: OpeningBIn, session: Session, _: Dispatcher
) -> None:
    """Half the people hear this opening, half the script's own. The agent's notices are
    said beside it whenever it does not say them itself (`agents.service.campaign_first_words`)."""
    await workspace.read_workspace(session, campaign_id)
    line = " ".join((payload.opening_b or "").split())
    if line and _FORMATTING.search(line):
        raise ProblemError(
            kind="validation",
            code="opening_b_formatting",
            title="Check this field",
            detail="Write the opening as plain spoken words, without symbols.",
        )
    await session.execute(
        text("UPDATE campaigns SET opening_b = :o, updated_at = now() WHERE id = :cid"),
        {"o": line or None, "cid": campaign_id},
    )


class HourOut(_Out):
    #: The hour of the day in IST, 0-23.
    hour: int
    calls: int
    answered: int
    rate: float


class OpeningOut(_Out):
    variant: Literal["a", "b"]
    people: int
    answered: int
    goal_reached: int
    goal_rate: float | None


class CampaignInsightsOut(_Out):
    hours: list[HourOut]
    #: The hours people answer most, among those with enough calls to judge.
    best_hours: list[HourOut]
    min_calls_per_hour: int
    opening_b: str | None
    openings: list[OpeningOut]
    opening_verdict: str | None


def _hour(r: learning.HourRate) -> HourOut:
    return HourOut(hour=r.hour, calls=r.calls, answered=r.answered, rate=round(r.rate, 4))


@router.get(
    "/{campaign_id}/insights",
    response_model=CampaignInsightsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="When people answer this campaign's calls, and how its two openings compare",
)
async def campaign_insights(campaign_id: UUID, session: Session, _: Reader) -> CampaignInsightsOut:
    await workspace.read_workspace(session, campaign_id)
    rates = await learning.answer_rate_by_hour(session, campaign_id)
    opening_b = (
        await session.execute(
            text("SELECT opening_b FROM campaigns WHERE id = :c"), {"c": campaign_id}
        )
    ).scalar_one_or_none()
    openings = await learning.opening_results(session, campaign_id) if opening_b else []
    return CampaignInsightsOut(
        hours=[_hour(r) for r in rates],
        best_hours=[_hour(r) for r in learning.best_hours(rates)],
        min_calls_per_hour=learning.MIN_CALLS_PER_HOUR,
        opening_b=opening_b,
        openings=[
            OpeningOut(
                variant=o.variant,  # type: ignore[arg-type]
                people=o.people,
                answered=o.answered,
                goal_reached=o.goal_reached,
                goal_rate=None if o.goal_rate is None else round(o.goal_rate, 4),
            )
            for o in openings
        ],
        opening_verdict=learning.opening_verdict(openings) if openings else None,
    )


class CampaignTestCallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: str = Field(min_length=8, max_length=20)
    number_is_mine: bool = False


class CampaignTestCallOut(_Out):
    status: Literal["queued", "blocked"]
    blocked_reason: str | None = None
    call_id: UUID | None = None


@router.post(
    "/{campaign_id}/test-call",
    response_model=CampaignTestCallOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Put the campaign's script on its agent and ring your own phone to hear it",
)
async def campaign_test_call(
    campaign_id: UUID,
    payload: CampaignTestCallIn,
    request: Request,
    session: Session,
    principal: Dispatcher,
) -> CampaignTestCallOut:
    """The same gated, capped, idempotent test call as the agent's Try it (`agents/trial_calls`),
    after the campaign's script is put live on the agent exactly as Start would put it."""
    assert principal.tenant_id is not None
    idem_key = require_idempotency_key(
        request.headers.get("Idempotency-Key"),
        title="A test call needs an Idempotency-Key header",
        detail="Each test call rings a real phone, so every attempt names itself.",
    )
    space = await workspace.read_workspace(session, campaign_id)
    name = (
        await session.execute(text("SELECT name FROM campaigns WHERE id = :c"), {"c": campaign_id})
    ).scalar_one()
    await workspace.put_script_live(
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        campaign_name=str(name),
        user_id=principal.user_id,
    )
    if payload.number_is_mine:
        await attest_own_number(
            principal=principal, number=payload.number, ip=client_request_ip(request)
        )
    result = await place_trial_call(
        session,
        principal=principal,
        agent_id=space.agent_id,
        number=payload.number,
        idempotency_key=idem_key,
        ip=client_request_ip(request),
        own_number_attested=payload.number_is_mine,
    )
    return CampaignTestCallOut(
        status=result.status, blocked_reason=result.blocked_reason, call_id=result.call_id
    )


@router.post(
    "/{campaign_id}/materials/upload",
    response_model=MaterialOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Upload a file for the campaign; a file already in the knowledge is reused",
)
async def upload_material(
    campaign_id: UUID,
    session: Session,
    request: Request,
    file: Annotated[UploadFile, File()],
    principal: KbWriter,
    title: Annotated[str | None, Form(max_length=workspace.TITLE_MAX)] = None,
) -> MaterialOut:
    """The file goes into the client's knowledge exactly as `POST /v1/kb/uploads` puts it,
    unless these exact bytes are already live there: then that upload is attached instead of
    being refused as a duplicate, because the campaign only needs to point at it (D-992)."""
    assert principal.tenant_id is not None
    await workspace.read_workspace(session, campaign_id)
    data = await read_bounded_upload(file, kb_uploads.MAX_UPLOAD_BYTES)
    upload_id = await kb_uploads.live_duplicate_of(
        session, tenant_id=principal.tenant_id, data=data
    )
    if upload_id is None:
        made = await kb_uploads.create_upload(
            session,
            tenant_id=principal.tenant_id,
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
            tenant_id=principal.tenant_id,
            object_type="kb_source",
            object_id=str(made["source_id"]),
            ip=client_request_ip(request),
            summary={"upload_id": str(upload_id), "via": "campaign_material"},
        )
    material = await workspace.add_material(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        kind="file",
        title=(title or "").strip() or (file.filename or "Document"),
        url=None,
        note=None,
        kb_upload_id=upload_id,
        created_by=principal.user_id,
    )
    return _material(material)
