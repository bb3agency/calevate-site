"""The campaign workspace: main task, sources, the campaign's script and Pip's draft of it,
and the questions its calls could not answer (D-992). `campaigns/workspace.py` holds the rules.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Final, Literal
from uuid import UUID

import openpyxl
from calevate_shared.call_script import CallScript
from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import core_fields
from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_proposals
from apps.api.agents.call_handling import read_agent_call_handling
from apps.api.agents.extraction_routes import MAX_EXTRACTION_FIELDS
from apps.api.agents.languages import LANGUAGE_LABELS, client_language_tags
from apps.api.agents.service import CAMPAIGN_HOLDING_STATUSES, effective_call_cap
from apps.api.agents.trial_calls import attest_own_number, place_trial_call
from apps.api.agents.voice_tuning import read_voice_tuning
from apps.api.agents.workspace_slots import SLOTS_FULL_RESPONSES
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.campaigns import learning, workspace
from apps.api.campaigns import notes as campaign_notes
from apps.api.campaigns import settings as campaign_settings_rules
from apps.api.campaigns.engine_agent import needs_its_own, put_campaign_live
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.hang_up import HangsUpCalls
from apps.api.ingest.service import normalize_phone
from apps.api.kb import uploads as kb_uploads
from apps.api.kb.curation import goes_live_without_review, requires_kb_curation
from apps.api.kb.picks import MAX_PICKS
from apps.api.reliability.service import require_idempotency_key
from apps.api.teach.routes import read_bounded_upload
from apps.api.teach.struggles import list_struggles
from apps.api.tenancy.core_labels import core_labels
from apps.workers.campaign_script_ask import INSTRUCTION_MAX, Tone

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])
Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("leads:read"))]
Dispatcher = Annotated[Principal, Depends(requires("leads:dispatch"))]
KbWriter = Annotated[Principal, Depends(requires_kb_curation())]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CampaignLeftOutOut(_Out):
    """A part of Pip's script kept as the owner had it, a warning its repairs could not clear
    (ready), or a part it could not write (failed). `LeftOutPartOut`'s shape."""

    part: str
    label: str
    rule: str
    added: bool
    unfixed: bool


class CampaignProposalOut(_Out):
    id: UUID
    status: Literal["drafting", "ready", "failed"]
    requested_at: datetime
    #: The script it was written from (null for a campaign's first script).
    base_script: CallScript | None
    script: CallScript | None
    note: str | None
    #: Who wrote it when it was not the account's own model (D-127 G-6), shown beside it.
    disclosure: str | None
    left_out: list[CampaignLeftOutOut]
    #: Failed: why (a refusal code, `crashed` or `stale`), so the screen can say what to do.
    reason: str | None
    #: Ready: Pip's one-sentence reason for each part it wrote, by the part's key
    #: (`opening_line`, `faqs`, `stages.<id>`, ...), shown beside the part in the review.
    why: dict[str, str]
    #: A fix of a mistake on real calls the healer asked Pip for (D-1005), in the owner's
    #: words; null for a draft the owner asked for.
    fixes: str | None
    #: The one part asked for ("flow", "translate", a part's name); null for the whole script.
    focus_part: str | None = None


class WorkspaceOut(_Out):
    campaign_id: UUID
    agent_id: UUID
    status: str
    main_task: str
    script: CallScript | None
    #: The agent script version this campaign put live at its last Start.
    script_live_version: int | None
    proposal: CampaignProposalOut | None
    #: The sources from What your agents know the campaign is written from.
    source_ids: list[UUID]
    #: When the script from before Pip's last draft was kept aside; None: nothing to put back.
    script_before_pip_at: datetime | None = None


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
        disclosure=p.disclosure,
        reason=p.reason,
        why=p.why,
        fixes=p.fixes,
        focus_part=p.focus_part,
        left_out=[
            CampaignLeftOutOut(
                part=part.part,
                label=script_proposals.part_label(part),
                rule=part.rule,
                added=part.added,
                unfixed=part.unfixed,
            )
            for part in p.left_out
        ],
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
        source_ids=list(w.sources),
        script_before_pip_at=w.script_before_pip_at,
    )


@router.get(
    "/{campaign_id}/workspace",
    response_model=WorkspaceOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The campaign's main task, sources, script and Pip's pending draft",
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


@router.post(
    "/{campaign_id}/script/restore-before-pip",
    response_model=WorkspaceOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Put back the script from before Pip's last draft (the two swap)",
)
async def restore_script_before_pip(
    campaign_id: UUID, session: Session, request: Request, principal: Dispatcher
) -> WorkspaceOut:
    assert principal.tenant_id is not None
    await workspace.restore_before_pip(session, campaign_id)
    await write_audit(
        session,
        action="campaign.script_restored_before_pip",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary={},
    )
    return await _workspace_out(session, campaign_id)


class ScriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script: CallScript


async def _holds_engine_agent(session: AsyncSession, campaign_id: UUID) -> bool:
    """The campaign has its own engine agent and is still going, so an edit reaches its
    calls now (`put_campaign_live`) rather than at its next Start or test call."""
    return bool(
        (
            await session.execute(
                text(
                    "SELECT engine_agent_ref IS NOT NULL AND status = ANY(:holding) "
                    "FROM campaigns WHERE id = :c"
                ),
                {"c": campaign_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
            )
        ).scalar_one_or_none()
    )


async def _put_live_after_save(tenant_id: UUID, campaign_id: UUID) -> None:
    """Put a committed edit on the campaign's engine agent. A refusal says the edit is kept,
    so the owner saves again rather than typing it again (`inbound/routes`' same step)."""
    try:
        await put_campaign_live(tenant_id=tenant_id, campaign_id=campaign_id)
    except ProblemError as exc:
        exc.title = "Saved, but not on its calls yet"
        exc.remediation = (
            "Your change is kept. Save again to put it on the calls. " + (exc.remediation or "")
        ).strip()
        raise


@router.put(
    "/{campaign_id}/script",
    response_model=WorkspaceOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Save the campaign's script; a running or paused campaign's calls get it at once",
)
async def save_script(
    campaign_id: UUID,
    payload: ScriptIn,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> WorkspaceOut:
    """Stored in its own transaction, then, when the campaign holds its engine agent, put live
    on it: Resume does not republish, so a running or paused campaign would otherwise keep
    its old script until it was stopped. A draft's reaches its calls at Start."""
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as own:
        await workspace.save_script(own, campaign_id, payload.script)
        await write_audit(
            own,
            action="campaign.script_saved",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            ip=client_request_ip(request),
            summary={},
        )
    if await _holds_engine_agent(session, campaign_id):
        await _put_live_after_save(principal.tenant_id, campaign_id)
    return await _workspace_out(session, campaign_id)


class CampaignSourcesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[UUID] = Field(max_length=MAX_PICKS)


@router.put(
    "/{campaign_id}/sources",
    response_model=WorkspaceOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Choose the sources from What your agents know that Pip writes the campaign from",
)
async def set_sources(
    campaign_id: UUID,
    payload: CampaignSourcesIn,
    session: Session,
    principal: Dispatcher,
) -> WorkspaceOut:
    assert principal.tenant_id is not None
    await workspace.set_sources(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        kb_source_ids=payload.source_ids,
        created_by=principal.user_id,
    )
    return await _workspace_out(session, campaign_id)


class CampaignNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Optional: without one the note is named after its first words.
    title: str | None = Field(default=None, max_length=workspace.TITLE_MAX)
    note: str = Field(min_length=1, max_length=workspace.NOTE_MAX)


async def _note_added(
    session: AsyncSession,
    principal: Principal,
    request: Request,
    *,
    campaign_id: UUID,
    title: str | None,
    note: str,
    via: str,
) -> None:
    assert principal.tenant_id is not None
    source_id = await workspace.add_note(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        title=title,
        note=note,
        created_by=principal.user_id,
        auto_approve=goes_live_without_review(
            realm=principal.realm, impersonating=principal.impersonating
        ),
    )
    await write_audit(
        session,
        action="kb.submitted",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=client_request_ip(request),
        summary={"campaign_id": str(campaign_id), "via": via},
    )


@router.post(
    "/{campaign_id}/sources/note",
    response_model=WorkspaceOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Write a note into What your agents know and pick it for the campaign",
)
async def add_note(
    campaign_id: UUID,
    payload: CampaignNoteIn,
    session: Session,
    request: Request,
    principal: KbWriter,
) -> WorkspaceOut:
    await _note_added(
        session,
        principal,
        request,
        campaign_id=campaign_id,
        title=payload.title,
        note=payload.note,
        via="campaign_note",
    )
    return await _workspace_out(session, campaign_id)


class CampaignLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2_000)
    name: str | None = Field(default=None, max_length=workspace.TITLE_MAX)


@router.post(
    "/{campaign_id}/sources/link",
    response_model=WorkspaceOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Add a web page to What your agents know and pick it for the campaign",
)
async def add_link(
    campaign_id: UUID,
    payload: CampaignLinkIn,
    session: Session,
    request: Request,
    principal: KbWriter,
) -> WorkspaceOut:
    """The link goes into the client's knowledge exactly as `POST /v1/kb/links` puts it."""
    assert principal.tenant_id is not None
    await workspace.read_workspace(session, campaign_id)
    made = await kb_uploads.create_link(
        session,
        tenant_id=principal.tenant_id,
        name=(payload.name or "").strip() or None,
        url=payload.url.strip(),
        submitted_by=principal.user_id,
        auto_approve=goes_live_without_review(
            realm=principal.realm, impersonating=principal.impersonating
        ),
    )
    await write_audit(
        session,
        action="kb.link_added",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_source",
        object_id=str(made["source_id"]),
        ip=client_request_ip(request),
        summary={"upload_id": str(made["id"]), "via": "campaign_source"},
    )
    await workspace.pick_source(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        kb_source_id=UUID(str(made["source_id"])),
        created_by=principal.user_id,
    )
    return await _workspace_out(session, campaign_id)


class CampaignProposalIn(BaseModel):
    """Empty for the whole script. With `part` and `language`: that one part, in that
    language. `tone` and `instruction` say how either is written (D-1004)."""

    model_config = ConfigDict(extra="forbid")
    #: The part's name as the script editor shows it ("Quick facts", "Opening line when it calls").
    part: str | None = Field(default=None, min_length=1, max_length=80)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    tone: Tone | None = None
    #: What the owner wants changed, in their words ("make the opening warmer").
    instruction: str | None = Field(default=None, max_length=INSTRUCTION_MAX)


@router.post(
    "/{campaign_id}/script/proposal",
    response_model=CampaignProposalOut,
    status_code=202,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Ask Pip to write the campaign's script from its main task and sources",
)
async def request_proposal(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Dispatcher,
    payload: CampaignProposalIn | None = None,
) -> CampaignProposalOut:
    assert principal.tenant_id is not None
    await workspace.read_workspace(session, campaign_id)
    focus: dict[str, str] | None = None
    if payload is not None and (payload.part or payload.language):
        if not (payload.part and payload.language) or payload.language not in LANGUAGE_LABELS:
            raise ProblemError(
                kind="validation",
                code="script_part_request_invalid",
                title="Choose a part and a language",
                detail="Name the part to rewrite and one of the offered languages.",
            )
        focus = {"part": payload.part, "language": payload.language}
    ask: dict[str, str] = {}
    if payload is not None and payload.tone:
        ask["tone"] = payload.tone
    if payload is not None and payload.instruction and payload.instruction.strip():
        ask["instruction"] = " ".join(payload.instruction.split())
    # Writing the script spends the account's dashboard AI allowance, as the agent Script
    # page's Pip does: refused at the ceiling or under view-as, before anything is queued.
    assert_view_as_may(principal, "billing.ai_assist")
    await require_ai_assist(session, tenant_id=principal.tenant_id)
    proposal = await workspace.request_proposal(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        requested_by=principal.user_id,
        focus=focus,
        ask=ask or None,
    )
    # The owner's typed instruction stays out of the audit row: it is free text.
    asked: dict[str, str | bool] = {"tone": ask["tone"]} if "tone" in ask else {}
    if "instruction" in ask:
        asked["instructed"] = True
    await write_audit(
        session,
        action="campaign.script_requested",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary={"proposal_id": str(proposal.id), **(focus or {}), **asked},
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
    response_model=WorkspaceOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Answer a question the agent could not: a note in What your agents know, picked",
)
async def answer_question(
    campaign_id: UUID,
    payload: CampaignAnswerIn,
    session: Session,
    request: Request,
    principal: KbWriter,
) -> WorkspaceOut:
    """The answer goes into What your agents know, so every agent can give it, and the
    campaign picks it, so the next script Pip writes works it in; the owner updates the
    script to put it on calls."""
    await _note_added(
        session,
        principal,
        request,
        campaign_id=campaign_id,
        title=payload.topic,
        note=payload.answer,
        via="campaign_question",
    )
    return await _workspace_out(session, campaign_id)


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
            title="Use plain words in the opening",
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
    #: The rule that refused it, so a screen can tell a trial limit from a fault.
    blocked_rule: str | None = None
    call_id: UUID | None = None


@router.post(
    "/{campaign_id}/test-call",
    response_model=CampaignTestCallOut,
    responses=SLOTS_FULL_RESPONSES,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Ring your own phone through the campaign's own engine agent to hear it",
)
async def campaign_test_call(
    campaign_id: UUID,
    payload: CampaignTestCallIn,
    request: Request,
    session: Session,
    principal: Dispatcher,
) -> CampaignTestCallOut:
    """The same gated, capped, idempotent test call as the agent's Try it (`agents/trial_calls`),
    rung through the campaign's own engine agent, published as a test holder first, so it says
    what the campaign says now in its agent's voice and never touches the agent (D-1003)."""
    assert principal.tenant_id is not None
    idem_key = require_idempotency_key(
        request.headers.get("Idempotency-Key"),
        title="A test call needs an Idempotency-Key header",
        detail="Each test call rings a real phone, so every attempt names itself.",
    )
    space = await workspace.read_workspace(session, campaign_id)
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
        # A campaign that says only what its agent says is heard through the agent itself,
        # while that agent holds an engine agent of its own (D-1019).
        campaign_id=campaign_id if await needs_its_own(session, campaign_id) else None,
    )
    if result.call_id is not None:
        await remember_test_number(session, payload.number)
        # Listed in the Test call section with its recording; once, whatever the retries.
        await session.execute(
            text(
                "UPDATE campaigns SET test_call_ids = array_append(test_call_ids, :call) "
                "WHERE id = :c AND NOT (:call = ANY (test_call_ids))"
            ),
            {"c": campaign_id, "call": result.call_id},
        )
    return CampaignTestCallOut(
        status=result.status,
        blocked_reason=result.blocked_reason,
        blocked_rule=result.blocked_rule,
        call_id=result.call_id,
    )


async def remember_test_number(session: AsyncSession, number: str) -> None:
    """The number a test call rang joins the account's saved test numbers, so the next test
    on a campaign or an inbound line offers it."""
    phone = normalize_phone(number)
    if phone is None:
        return
    await session.execute(
        text(
            "UPDATE organizations SET test_numbers = array_append(test_numbers, :n), "
            "updated_at = now() WHERE NOT (:n = ANY (test_numbers)) "
            "AND cardinality(test_numbers) < :cap"
        ),
        {"n": phone, "cap": MAX_TEST_NUMBERS},
    )


async def saved_test_numbers(session: AsyncSession) -> list[str]:
    """The account's saved test numbers. RLS scopes the read to the caller's account."""
    row = (await session.execute(text("SELECT test_numbers FROM organizations"))).first()
    return list(row[0]) if row is not None else []


async def _campaign_visible(session: AsyncSession, campaign_id: UUID) -> None:
    """For reads an archived campaign still shows (its test calls, the saved numbers), where
    `read_workspace` refuses an archived one."""
    found = await session.execute(text("SELECT 1 FROM campaigns WHERE id = :c"), {"c": campaign_id})
    if found.first() is None:
        raise ProblemError.not_found("Campaign")


#: Enough for a team's phones; a longer list is a call list, which is what campaigns are for.
MAX_TEST_NUMBERS = 10


class TestNumbersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numbers: list[str] = Field(max_length=MAX_TEST_NUMBERS)


class TestNumbersOut(_Out):
    numbers: list[str]


@router.get(
    "/{campaign_id}/test-numbers",
    response_model=TestNumbersOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The account's saved test numbers, offered under this campaign's Test call",
)
async def campaign_test_numbers(campaign_id: UUID, session: Session, _: Reader) -> TestNumbersOut:
    await _campaign_visible(session, campaign_id)
    return TestNumbersOut(numbers=await saved_test_numbers(session))


@router.put(
    "/{campaign_id}/test-numbers",
    response_model=TestNumbersOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Replace the account's saved test numbers",
)
async def save_campaign_test_numbers(
    campaign_id: UUID, payload: TestNumbersIn, session: Session, _: Dispatcher
) -> TestNumbersOut:
    await workspace.read_workspace(session, campaign_id)
    numbers: list[str] = []
    for raw in payload.numbers:
        phone = normalize_phone(raw)
        if phone is None:
            raise ProblemError(
                kind="validation",
                code="test_number_invalid",
                title="That is not a phone number we can ring",
                detail="Use a 10-digit Indian mobile, or a number starting with +.",
            )
        if phone not in numbers:
            numbers.append(phone)
    row = (
        await session.execute(
            text(
                "UPDATE organizations SET test_numbers = :n, updated_at = now() "
                "RETURNING test_numbers"
            ),
            {"n": numbers},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    return TestNumbersOut(numbers=list(row[0]))


#: Test calls listed under a campaign's or a line's Test call, newest first; older ones
#: stay in the call logs.
TEST_CALLS_SHOWN: Final = 20


class CampaignTestCallItem(_Out):
    call_id: UUID
    placed_at: datetime
    status: str
    duration_s: int | None
    #: A recording of our own exists; it is played through `/v1/calls/{id}/recording`.
    has_recording: bool


@router.get(
    "/{campaign_id}/test-calls",
    response_model=list[CampaignTestCallItem],
    openapi_extra=permission_meta("leads:read"),
    summary="The test calls this campaign placed, newest first",
)
async def campaign_test_calls(
    campaign_id: UUID, session: Session, _: Reader
) -> list[CampaignTestCallItem]:
    await _campaign_visible(session, campaign_id)
    rows = await session.execute(
        text(
            "SELECT k.id, k.created_at, k.status, k.duration_s, k.recording_url IS NOT NULL "
            "FROM campaigns c JOIN calls k ON k.id = ANY (c.test_call_ids) "
            "WHERE c.id = :c ORDER BY k.created_at DESC, k.id DESC LIMIT :n"
        ),
        {"c": campaign_id, "n": TEST_CALLS_SHOWN},
    )
    return [
        CampaignTestCallItem(
            call_id=r[0],
            placed_at=r[1],
            status=str(r[2]),
            duration_s=r[3],
            has_recording=bool(r[4]),
        )
        for r in rows
    ]


@router.delete(
    "/{campaign_id}/test-calls/{call_id}",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Take a test call off this campaign's list; the call stays in the call logs",
)
async def remove_campaign_test_call(
    campaign_id: UUID, call_id: UUID, session: Session, _: Dispatcher
) -> None:
    await workspace.read_workspace(session, campaign_id)
    await session.execute(
        text(
            "UPDATE campaigns SET test_call_ids = array_remove(test_call_ids, :call) WHERE id = :c"
        ),
        {"c": campaign_id, "call": call_id},
    )


#: A test call still on the line, by our call row's status.
_LIVE_CALL_STATUSES: Final = ("queued", "ringing", "in_progress")


@router.post(
    "/{campaign_id}/test-calls/{call_id}/end",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="End one of this campaign's test calls that is still ringing or connected",
    description=(
        "Only a call on this campaign's own test-call list, which rings the owner's phone. "
        "A call already over is a no-op. `call_not_endable` when the engine cannot end calls."
    ),
)
async def end_campaign_test_call(
    campaign_id: UUID,
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> None:
    assert principal.tenant_id is not None
    await _campaign_visible(session, campaign_id)
    row = (
        await session.execute(
            text(
                "SELECT k.engine_call_id, k.status FROM campaigns c "
                "JOIN calls k ON k.id = :call AND k.id = ANY (c.test_call_ids) WHERE c.id = :c"
            ),
            {"c": campaign_id, "call": call_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Test call")
    if str(row[1]) not in _LIVE_CALL_STATUSES:
        return
    engine = get_engine()
    if not isinstance(engine, HangsUpCalls):
        raise ProblemError.business_rule(
            "call_not_endable", "This call can't be ended from here. Hang up on your phone."
        )
    await engine.hang_up_call(str(row[0]))
    await write_audit(
        session,
        action="campaign.test_call_ended",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=client_request_ip(request),
        summary={"campaign_id": str(campaign_id)},
    )


@router.post(
    "/{campaign_id}/sources/upload",
    response_model=WorkspaceOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Upload a file into What your agents know and pick it; a copy there is reused",
)
async def upload_source(
    campaign_id: UUID,
    session: Session,
    request: Request,
    file: Annotated[UploadFile, File()],
    principal: KbWriter,
) -> WorkspaceOut:
    """The file goes into the client's knowledge exactly as `POST /v1/kb/uploads` puts it,
    unless these exact bytes are already live there: then that upload is attached instead of
    being refused as a duplicate, because the campaign only needs to pick it."""
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
            summary={"upload_id": str(upload_id), "via": "campaign_source"},
        )
    source_id = (
        await session.execute(
            text("SELECT source_id FROM kb_uploads WHERE id = :u"), {"u": upload_id}
        )
    ).scalar_one()
    await workspace.pick_source(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        kb_source_id=source_id,
        created_by=principal.user_id,
    )
    return await _workspace_out(session, campaign_id)


# --- The campaign's own settings over its agent's defaults (D-994) ---------------------------


class CampaignSettingsValues(BaseModel):
    """Each value null when not set: on `defaults`, the platform's; on `overrides`, the agent's."""

    model_config = ConfigDict(extra="forbid")
    language_primary: str | None = None
    #: The other languages the agent switches to when a caller speaks one; the script is
    #: written in `language_primary` and followed in each (founder, 16 Nov 2026).
    languages_extra: list[str] | None = None
    speaking_speed: Decimal | None = None
    max_call_duration_s: int | None = None
    nudge_after_seconds: int | None = None
    end_after_silence_seconds: int | None = None
    filler_lines: list[str] | None = None
    ambience: str | None = None
    ambience_volume_pct: int | None = None
    reask_after_ms: int | None = None


class CampaignSettingsOut(_Out):
    agent_id: UUID
    agent_name: str
    #: The agent's own settings, as its calls get them without this campaign.
    defaults: CampaignSettingsValues
    #: What this campaign sets instead; a null key follows the agent.
    overrides: CampaignSettingsValues
    #: The campaign has its own engine agent now (running or paused), so a save
    #: reaches its calls at once; otherwise at its next Start or test call.
    applied_now: bool
    #: The languages this account may choose, in picker order.
    offered_languages: list[str]


async def _settings_out(session: AsyncSession, campaign_id: UUID) -> CampaignSettingsOut:
    space = await workspace.read_workspace(session, campaign_id)
    agent = (
        await session.execute(
            text(
                "SELECT name, language_primary, max_call_duration_s, languages_extra "
                "FROM agents WHERE id = :a"
            ),
            {"a": space.agent_id},
        )
    ).one()
    tuning = await read_voice_tuning(session, space.agent_id)
    handling = await read_agent_call_handling(session, space.agent_id)
    values = handling.resolved.values
    raw = (
        await session.execute(
            text(
                "SELECT settings_overrides, engine_agent_ref IS NOT NULL "
                "AND status = ANY(:holding) FROM campaigns WHERE id = :c"
            ),
            {"c": campaign_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
        )
    ).one()
    return CampaignSettingsOut(
        agent_id=space.agent_id,
        agent_name=str(agent.name),
        defaults=CampaignSettingsValues(
            language_primary=str(agent.language_primary),
            languages_extra=list(agent.languages_extra or []),
            speaking_speed=tuning.tuning.speed,
            max_call_duration_s=effective_call_cap(agent.max_call_duration_s),
            nudge_after_seconds=values.nudge_after_seconds,
            end_after_silence_seconds=values.end_after_silence_seconds,
            filler_lines=list(values.filler_lines or ()),
            ambience=values.ambience,
            ambience_volume_pct=values.ambience_volume_pct,
            reask_after_ms=values.reask_after_ms,
        ),
        overrides=CampaignSettingsValues(**(raw[0] or {})),
        applied_now=bool(raw[1]),
        offered_languages=list(client_language_tags()),
    )


@router.get(
    "/{campaign_id}/settings",
    response_model=CampaignSettingsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The agent's default settings and what this campaign sets over them",
)
async def campaign_settings(campaign_id: UUID, session: Session, _: Reader) -> CampaignSettingsOut:
    return await _settings_out(session, campaign_id)


@router.put(
    "/{campaign_id}/settings",
    response_model=CampaignSettingsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Set this campaign's own settings over its agent's defaults; null follows the agent",
)
async def save_campaign_settings(
    campaign_id: UUID, payload: CampaignSettingsValues, session: Session, principal: Dispatcher
) -> CampaignSettingsOut:
    """Stored, then, when the campaign has its own engine agent, put live on it at once through
    the same publish Start uses; otherwise they reach its calls at the next Start or test
    call. The agent's own settings are never changed (D-1003)."""
    assert principal.tenant_id is not None
    cleaned = campaign_settings_rules.clean_overrides(payload.model_dump(exclude_none=True))
    await workspace.read_workspace(session, campaign_id)
    # Its own transaction, committed before the publish below reads it in another session;
    # committing the request's session instead would drop its tenant setting mid-request.
    async with tenant_session(principal.tenant_id) as own:
        await own.execute(
            text(
                "UPDATE campaigns SET settings_overrides = CAST(:o AS jsonb), updated_at = now() "
                "WHERE id = :c AND archived_at IS NULL"
            ),
            {"o": json.dumps(cleaned) if cleaned else None, "c": campaign_id},
        )
    out = await _settings_out(session, campaign_id)
    if out.applied_now:
        await _put_live_after_save(principal.tenant_id, campaign_id)
    return out


# --- What it notes ----------------------------------------------------------------------------


class CampaignNotesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The campaign's whole list; empty follows its agent's.
    fields: list[ExtractionField] = Field(max_length=MAX_EXTRACTION_FIELDS)
    #: The `digest` of the list the editor was showing. Sent, a save over a list changed since
    #: is refused rather than dropping the other change, because the body is the whole list.
    expected_digest: str | None = Field(default=None, max_length=64)


class CampaignNotesOut(_Out):
    agent_id: UUID
    agent_name: str
    #: The campaign's own list, in order; empty means its calls note what its agent notes.
    fields: list[ExtractionField]
    #: Its agent's list, which its calls note while `fields` is empty.
    agent_fields: list[ExtractionField]
    #: The details every call notes whatever the list (name, number, summary...).
    core_fields: list[ExtractionField]
    digest: str
    #: The campaign has its own engine agent now, so a save reaches its calls at once.
    applied_now: bool


async def _notes_out(session: AsyncSession, campaign_id: UUID) -> CampaignNotesOut:
    held = await campaign_notes.read_notes(session, campaign_id)
    live = (
        await session.execute(
            text(
                "SELECT engine_agent_ref IS NOT NULL AND status = ANY(:holding) "
                "FROM campaigns WHERE id = :c"
            ),
            {"c": campaign_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
        )
    ).scalar_one()
    return CampaignNotesOut(
        agent_id=held.agent_id,
        agent_name=held.agent_name,
        fields=list(held.fields),
        agent_fields=list(held.agent_fields),
        core_fields=core_fields(await core_labels(session)),
        digest=held.digest,
        applied_now=bool(live),
    )


@router.get(
    "/{campaign_id}/notes",
    response_model=CampaignNotesOut,
    openapi_extra=permission_meta("leads:read"),
    summary="What this campaign's calls note, and its agent's list it follows while empty",
)
async def campaign_notes_read(campaign_id: UUID, session: Session, _: Reader) -> CampaignNotesOut:
    return await _notes_out(session, campaign_id)


@router.put(
    "/{campaign_id}/notes",
    response_model=CampaignNotesOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Set what this campaign's calls note; an empty list follows its agent's",
)
async def campaign_notes_save(
    campaign_id: UUID,
    payload: CampaignNotesIn,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> CampaignNotesOut:
    """Stored in its own transaction, then, when the campaign has its own engine agent, put
    live on it so its calls ask for the new details (D-1003); otherwise they reach its calls
    at the next Start or test call. The agent's own list is never changed."""
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as own:
        changed = await campaign_notes.save_notes(
            own, campaign_id, payload.fields, expected_digest=payload.expected_digest
        )
        if changed:
            await write_audit(
                own,
                action="campaign.notes_saved",
                actor=principal,
                tenant_id=principal.tenant_id,
                object_type="campaign",
                object_id=str(campaign_id),
                ip=client_request_ip(request),
                # The keys, never a value: who changed which details is what is audited.
                summary={"fields": [field.key for field in payload.fields]},
            )
    out = await _notes_out(session, campaign_id)
    # Unchanged too, as the script and settings saves do: an unchanged save is the Save again
    # that `_put_live_after_save`'s refusal asks for, the list already stored.
    if out.applied_now:
        await _put_live_after_save(principal.tenant_id, campaign_id)
    return out


# --- A contact list from an Excel sheet --------------------------------------------------------

#: The contact file limit the screen already holds a CSV to (`ContactEditor.MAX_FILE_BYTES`).
CONTACT_SHEET_MAX_BYTES: Final = 4 * 1024 * 1024
CONTACT_SHEET_MAX_ROWS: Final = 20_000


class ContactSheetOut(_Out):
    #: The first sheet as CSV text, for the screen's own CSV checks (numbers, duplicates).
    csv: str
    rows: int


def _cell(value: object) -> str:
    """A cell as text. A phone number typed into Excel is often stored as a number
    (9876543210.0); it is written back without the decimal so it reads as the number."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


@router.post(
    "/contacts/from-excel",
    response_model=ContactSheetOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Read the first sheet of an Excel file (.xlsx) as CSV text for a contact list",
)
async def contacts_from_excel(
    file: Annotated[UploadFile, File()], principal: Dispatcher
) -> ContactSheetOut:
    """Nothing is stored: the screen checks the rows as it checks a CSV and adds them to the
    draft the same way, so one set of rules (numbers, duplicates, consent) covers both."""
    del principal
    data = await read_bounded_upload(file, CONTACT_SHEET_MAX_BYTES)
    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ProblemError(
            kind="validation",
            code="contact_sheet_unreadable",
            title="That file could not be read",
            detail="It is not an Excel workbook (.xlsx). Save it as .xlsx or CSV and try again.",
        ) from exc
    out = io.StringIO()
    writer = csv.writer(out)
    rows = 0
    try:
        sheet = book.worksheets[0] if book.worksheets else None
        if sheet is not None:
            for row in sheet.iter_rows(values_only=True):
                cells = [_cell(v) for v in row]
                if not any(cells):
                    continue
                if rows >= CONTACT_SHEET_MAX_ROWS:
                    raise ProblemError(
                        kind="validation",
                        code="contact_sheet_too_long",
                        title="That sheet is too long",
                        detail=f"Keep a list to {CONTACT_SHEET_MAX_ROWS:,} rows; split the rest.",
                    )
                writer.writerow(cells)
                rows += 1
    finally:
        book.close()
    return ContactSheetOut(csv=out.getvalue(), rows=rows)
