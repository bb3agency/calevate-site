"""Inbound lines API (D-997): `/v1/inbound-lines`. `inbound/lines.py` holds the rules.

Reads are `agents:read`; every write is `org:manage`, as an agent's script is, because a line
says what callers hear. A write that changes what callers hear (the script, the voice, the
actions) commits first and then puts the line live in its own transactions
(`inbound/publish.put_line_live`), so the edit is kept even when the platform refuses, and the
refusal says so.

Pip's draft is returned in the campaign's shape (`CampaignProposalOut`), so the web reviews a
line's draft with the campaign's review.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from calevate_shared.call_script import CallScript
from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import give_callers_time
from apps.api.agents import service as agents_service
from apps.api.agents.mistake_fixes import Holder
from apps.api.agents.trial_calls import attest_own_number, place_trial_call
from apps.api.agents.workspace_slots import SLOTS_FULL_RESPONSES
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.campaigns import notes as job_notes
from apps.api.campaigns import notes_live, number_catalog, script_draft, script_history
from apps.api.campaigns.workspace import MAIN_TASK_MAX
from apps.api.campaigns.workspace_routes import (
    GIVE_TIME_DESCRIPTION,
    TEST_CALLS_SHOWN,
    CampaignProposalIn,
    CampaignProposalOut,
    CampaignTestCallIn,
    CampaignTestCallItem,
    CampaignTestCallOut,
    ExampleLimitsOut,
    HolderDiagnosisOut,
    HolderGiveTimeIn,
    HolderGiveTimeOut,
    JobNotesIn,
    JobNotesOut,
    TestNumbersOut,
    asked_summary,
    example_limits_out,
    holder_diagnosis,
    holder_give_time_out,
    job_notes_out,
    part_focus,
    remember_test_number,
    saved_test_numbers,
)
from apps.api.campaigns.workspace_routes import _proposal as proposal_out
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine.answering import saved_goes_live_later
from apps.api.inbound import lines
from apps.api.inbound.publish import put_line_live, route_numbers
from apps.api.reliability.service import require_idempotency_key
from apps.workers.engine_outage import engine_unavailable

router = APIRouter(prefix="/v1/inbound-lines", tags=["inbound"])
Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("agents:read"))]
Writer = Annotated[Principal, Depends(requires("org:manage"))]
#: A test call rings a phone, as a campaign's does: the same permissions as its routes.
Dispatcher = Annotated[Principal, Depends(requires("leads:dispatch"))]
TestReader = Annotated[Principal, Depends(requires("leads:read"))]

#: Calls listed on a line's page; the call logs hold the rest.
CALLS_SHOWN = 50


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LineNumberOut(_Out):
    id: UUID
    e164: str


class InboundLineOut(_Out):
    id: UUID
    name: str
    agent_id: UUID
    agent_name: str
    main_task: str
    script: CallScript | None
    proposal: CampaignProposalOut | None
    #: Moves on every saved script; 0 before the first.
    version: int
    #: When the script now live went out; null while the line is a draft.
    published_at: datetime | None
    live: bool
    #: The agent's actions this line does not use, by name.
    actions_off: list[str]
    #: The sources from What your agents know this line is written from.
    source_ids: list[UUID]
    numbers: list[LineNumberOut]
    #: The languages its calls are in, main first: a step's examples are written in each.
    call_languages: list[str]
    #: How much a step's examples hold, for the script editor.
    example_limits: ExampleLimitsOut
    created_at: datetime


class InboundLinesOut(_Out):
    lines: list[InboundLineOut]


def _out(line: lines.Line) -> InboundLineOut:
    return InboundLineOut(
        id=line.id,
        name=line.name,
        agent_id=line.agent_id,
        agent_name=line.agent_name,
        main_task=line.main_task,
        script=line.script,
        proposal=proposal_out(line.proposal),
        version=line.version,
        published_at=line.published_at,
        live=line.live,
        actions_off=list(line.actions_off),
        source_ids=list(line.sources),
        numbers=[LineNumberOut(id=n.id, e164=n.e164) for n in line.numbers],
        call_languages=list(line.call_languages),
        example_limits=example_limits_out(),
        created_at=line.created_at,
    )


def _tenant(principal: Principal) -> UUID:
    assert principal.tenant_id is not None
    return principal.tenant_id


async def _read(tenant_id: UUID, line_id: UUID) -> InboundLineOut:
    async with tenant_session(tenant_id) as session:
        return _out(await lines.read_line(session, line_id))


async def _put_live_after_save(tenant_id: UUID, line_id: UUID) -> None:
    """Put the line live after an edit committed. A refusal says the edit is kept, so the
    owner presses Put it live rather than typing it again; an engine that is not answering
    queues the put-live, so the owner has nothing to press."""
    await notes_live.put_live_or_queue(
        tenant_id,
        "line",
        line_id,
        retry="put_live",
        publish=lambda: put_line_live(tenant_id=tenant_id, line_id=line_id),
    )


async def _republish_if_live(tenant_id: UUID, line_id: UUID) -> bool:
    """Put a live line live again after an edit; returns whether it was live."""
    async with tenant_session(tenant_id) as session:
        live = (await lines.read_line(session, line_id)).live
    if live:
        await _put_live_after_save(tenant_id, line_id)
    return live


@router.get(
    "",
    response_model=InboundLinesOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Every inbound line: what each number says, in which agent's voice",
)
async def list_lines(session: Session, _: Reader) -> InboundLinesOut:
    return InboundLinesOut(lines=[_out(line) for line in await lines.list_lines(session)])


class NewInboundLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID
    name: str | None = Field(default=None, max_length=lines.NAME_MAX)
    main_task: str | None = Field(default=None, max_length=MAIN_TASK_MAX)


@router.post(
    "",
    response_model=InboundLineOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Start an inbound line in one agent's voice; a draft until its script is live",
)
async def create_line(
    payload: NewInboundLineIn, request: Request, principal: Writer
) -> InboundLineOut:
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=payload.agent_id,
            name=payload.name,
            main_task=payload.main_task,
            created_by=principal.user_id,
        )
        await write_audit(
            session,
            action="inbound_line.created",
            actor=principal,
            tenant_id=tenant_id,
            object_type="inbound_line",
            object_id=str(line_id),
            ip=client_request_ip(request),
            summary={"agent_id": str(payload.agent_id)},
        )
    return await _read(tenant_id, line_id)


@router.get(
    "/{line_id}",
    response_model=InboundLineOut,
    openapi_extra=permission_meta("agents:read"),
    summary="One inbound line",
)
async def read_line(line_id: UUID, session: Session, _: Reader) -> InboundLineOut:
    return _out(await lines.read_line(session, line_id))


class InboundLinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=lines.NAME_MAX)
    agent_id: UUID | None = None
    main_task: str | None = Field(default=None, max_length=MAIN_TASK_MAX)


@router.patch(
    "/{line_id}",
    response_model=InboundLineOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Rename the line, save its main task, or give it another agent's voice",
)
async def update_line(
    line_id: UUID, payload: InboundLinePatch, request: Request, principal: Writer
) -> InboundLineOut:
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        voice_changed = await lines.update_line(
            session,
            line_id,
            name=payload.name,
            agent_id=payload.agent_id,
            main_task=payload.main_task,
        )
        if voice_changed:
            await write_audit(
                session,
                action="inbound_line.voice_changed",
                actor=principal,
                tenant_id=tenant_id,
                object_type="inbound_line",
                object_id=str(line_id),
                ip=client_request_ip(request),
                summary={"agent_id": str(payload.agent_id)},
            )
    # A draft line's numbers are answered by its voice's own engine agent
    # (`route_line_numbers`), so they move to the new voice now; a live line's are routed by
    # its put-live.
    if voice_changed and not await _republish_if_live(tenant_id, line_id):
        await route_numbers(tenant_id=tenant_id, line_id=line_id)
    return await _read(tenant_id, line_id)


class InboundLineSourcesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[UUID] = Field(max_length=200)


@router.put(
    "/{line_id}/sources",
    response_model=InboundLineOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Choose the sources from What your agents know that Pip writes this line from",
)
async def set_sources(
    line_id: UUID, payload: InboundLineSourcesIn, principal: Writer
) -> InboundLineOut:
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        await lines.set_sources(
            session,
            tenant_id=tenant_id,
            line_id=line_id,
            kb_source_ids=payload.source_ids,
            created_by=principal.user_id,
        )
    return await _read(tenant_id, line_id)


class InboundLineActionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The agent's actions this line does not use, by name; every other one is on.
    off: list[str] = Field(max_length=100)


@router.put(
    "/{line_id}/actions",
    response_model=InboundLineOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Switch the agent's actions on or off for this line",
)
async def set_actions(
    line_id: UUID, payload: InboundLineActionsIn, principal: Writer
) -> InboundLineOut:
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        await lines.set_actions_off(session, line_id, payload.off)
    await _republish_if_live(tenant_id, line_id)
    return await _read(tenant_id, line_id)


async def _line_notes_out(session: AsyncSession, line_id: UUID) -> JobNotesOut:
    live = (await lines.read_line(session, line_id)).live
    return await job_notes_out(session, "line", line_id, applied_now=live)


@router.get(
    "/{line_id}/notes",
    response_model=JobNotesOut,
    openapi_extra=permission_meta("agents:read"),
    summary="What this line's calls note",
)
async def line_notes_read(line_id: UUID, session: Session, _: Reader) -> JobNotesOut:
    return await _line_notes_out(session, line_id)


@router.put(
    "/{line_id}/notes",
    response_model=JobNotesOut,
    responses=SLOTS_FULL_RESPONSES,
    openapi_extra=permission_meta("org:manage"),
    summary="Set what this line's calls note, and put a live line live again",
)
async def line_notes_save(
    line_id: UUID, payload: JobNotesIn, request: Request, principal: Writer
) -> JobNotesOut:
    """The whole list under a compare-and-set on the digest the editor read (D-1028). What the
    line asks callers for is compiled into its script, so a live line is put live again; a
    draft line's list reaches its calls when it is put live."""
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        changed = await job_notes.save_notes(
            session, "line", line_id, payload.fields, expected_digest=payload.expected_digest
        )
        if changed:
            await write_audit(
                session,
                action="inbound_line.notes_saved",
                actor=principal,
                tenant_id=tenant_id,
                object_type="inbound_line",
                object_id=str(line_id),
                ip=client_request_ip(request),
                # The keys, never a value: who changed which details is what is audited.
                summary={"fields": [field.key for field in payload.fields]},
            )
    # Unchanged too: an unchanged save is the Save again a refused put-live asks for.
    await _republish_if_live(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        return await _line_notes_out(session, line_id)


class InboundLineScriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script: CallScript
    #: The Pip draft this save keeps, settled in the same transaction.
    proposal_id: UUID | None = None


@router.put(
    "/{line_id}/script",
    response_model=InboundLineOut,
    responses=SLOTS_FULL_RESPONSES,
    openapi_extra=permission_meta("org:manage"),
    summary="Save the line's script and put it live on its numbers",
)
async def save_script(
    line_id: UUID, payload: InboundLineScriptIn, request: Request, principal: Writer
) -> InboundLineOut:
    return await _save_then_put_live(
        request, principal, line_id, script=payload.script, proposal_id=payload.proposal_id
    )


async def _save_then_put_live(
    request: Request,
    principal: Principal,
    line_id: UUID,
    *,
    script: CallScript | None,
    proposal_id: UUID | None,
) -> InboundLineOut:
    """Save, settle the draft it came from, then put the line live: the one way the page's
    Save and Keep on a streamed draft both take. `script` None keeps the draft exactly as
    Pip wrote it, read under the row lock (`script_draft.ready_script`)."""
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        if script is None:
            assert proposal_id is not None
            script = await script_draft.ready_script(session, "inbound_line", line_id, proposal_id)
        version = await lines.save_script(
            session,
            line_id,
            script,
            author="owner" if proposal_id is None else "pip_draft",
            made_by=principal.user_id,
        )
        if proposal_id is not None:
            await lines.clear_proposal(session, line_id, proposal_id)
        await write_audit(
            session,
            action="inbound_line.script_saved",
            actor=principal,
            tenant_id=tenant_id,
            object_type="inbound_line",
            object_id=str(line_id),
            ip=client_request_ip(request),
            summary={"version": version, "from_draft": proposal_id is not None},
        )
    await _put_live_after_save(tenant_id, line_id)
    return await _read(tenant_id, line_id)


@router.get(
    "/{line_id}/script/versions",
    response_model=script_history.ScriptVersionsOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The line's saved script versions, and what putting back the script restores",
)
async def read_script_versions(
    line_id: UUID, session: Session, _: Reader
) -> script_history.ScriptVersionsOut:
    line = await lines.read_line(session, line_id)
    return await script_history.versions_out(session, "line", line_id, line.script)


async def _restore(
    request: Request,
    principal: Principal,
    line_id: UUID,
    *,
    version_id: UUID | None,
    expected_version_id: UUID | None,
) -> InboundLineOut:
    """Saved as a new version, then put live as the line's Save is."""
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        brought = await lines.restore_version(
            session,
            line_id,
            version_id=version_id,
            expected_version_id=expected_version_id,
            made_by=principal.user_id,
        )
        await write_audit(
            session,
            action="inbound_line.script_version_restored",
            actor=principal,
            tenant_id=tenant_id,
            object_type="inbound_line",
            object_id=str(line_id),
            ip=client_request_ip(request),
            summary={"version_id": str(brought.id), "owner_made": brought.owner_made},
        )
    await _put_live_after_save(tenant_id, line_id)
    return await _read(tenant_id, line_id)


@router.post(
    "/{line_id}/script/restore-before-pip",
    response_model=InboundLineOut,
    responses={
        **SLOTS_FULL_RESPONSES,
        409: {"description": "Nothing to put back, or the script changed since"},
    },
    openapi_extra=permission_meta("org:manage"),
    summary="Put back the owner's own last version of the line's script, before Pip's changes",
)
async def restore_script_before_pip(
    line_id: UUID, payload: script_history.ScriptRestoreIn, request: Request, principal: Writer
) -> InboundLineOut:
    return await _restore(
        request,
        principal,
        line_id,
        version_id=None,
        expected_version_id=payload.expected_version_id,
    )


@router.post(
    "/{line_id}/script/versions/{script_version_id}/restore",
    response_model=InboundLineOut,
    responses={
        **SLOTS_FULL_RESPONSES,
        409: {"description": "That version is the script now, or it changed since"},
    },
    openapi_extra=permission_meta("org:manage"),
    summary="Put back one saved version of the line's script",
)
async def restore_script_version(
    line_id: UUID,
    script_version_id: UUID,
    payload: script_history.ScriptRestoreIn,
    request: Request,
    principal: Writer,
) -> InboundLineOut:
    return await _restore(
        request,
        principal,
        line_id,
        version_id=script_version_id,
        expected_version_id=payload.expected_version_id,
    )


_DRAFT_STREAM_DESCRIPTION = """\
A `text/event-stream` following the line's Pip draft, with exactly the events of
`GET /v1/campaigns/{campaign_id}/script-draft/stream`: `phase`, then at `ready` every `line`
and one `diff`. It ends after `ready`, `failed` or `cancelled`; opening it again replays the
draft's current state, and a line with no draft answers 404.\
"""


async def _line_draft_open(line_id: UUID, principal: Reader) -> None:
    """The stream's checks as a dependency, so another account's line, or one with no draft,
    is an ordinary 404 before the stream opens."""
    async with tenant_session(_tenant(principal)) as session:
        if (await script_draft.read_draft(session, "inbound_line", line_id)).proposal is None:
            raise ProblemError.not_found("Draft")


@router.get(
    "/{line_id}/script-draft/stream",
    response_class=EventSourceResponse,
    openapi_extra=permission_meta("agents:read"),
    summary="Follow Pip's draft of the line's script as it is written (server-sent events)",
    description=_DRAFT_STREAM_DESCRIPTION,
)
async def stream_script_draft(
    line_id: UUID, principal: Reader, _open: None = Depends(_line_draft_open)
) -> AsyncIterator[ServerSentEvent]:
    """NO `Depends(db)`: a stream must not hold a pooled connection while it waits."""
    async for event in script_draft.draft_events(_tenant(principal), "inbound_line", line_id):
        yield event


@router.post(
    "/{line_id}/script-draft/{line_proposal_id}/keep-live",
    response_model=InboundLineOut,
    responses={**SLOTS_FULL_RESPONSES, 409: {"description": "The draft is not the one ready now"}},
    openapi_extra=permission_meta("org:manage"),
    summary="Keep Pip's written draft as the line's script and put it live, as Save does",
)
async def keep_script_draft_live(
    line_id: UUID, line_proposal_id: UUID, request: Request, principal: Writer
) -> InboundLineOut:
    return await _save_then_put_live(
        request, principal, line_id, script=None, proposal_id=line_proposal_id
    )


@router.post(
    "/{line_id}/script-draft/{line_proposal_id}/cancel",
    response_model=script_draft.DraftCancelOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Cancel Pip's draft while it is written; the line stays as it was",
)
async def cancel_script_draft(
    line_id: UUID, line_proposal_id: UUID, session: Session, principal: Writer
) -> script_draft.DraftCancelOut:
    await script_draft.read_draft(session, "inbound_line", line_id)
    cancelled = await script_draft.cancel_draft(
        session,
        tenant_id=_tenant(principal),
        holder_kind="inbound_line",
        holder_id=line_id,
        proposal_id=line_proposal_id,
    )
    return script_draft.DraftCancelOut(cancelled=cancelled)


@router.post(
    "/{line_id}/publish",
    response_model=InboundLineOut,
    responses=SLOTS_FULL_RESPONSES,
    openapi_extra=permission_meta("org:manage"),
    summary="Put the line's saved script live on its numbers again",
)
async def publish(line_id: UUID, principal: Writer) -> InboundLineOut:
    tenant_id = _tenant(principal)
    try:
        await put_line_live(tenant_id=tenant_id, line_id=line_id)
    except ProblemError as exc:
        # The script is already saved; with the engine not answering, pressing again would
        # only time out again, so it is queued and goes live by itself.
        if not engine_unavailable(exc):
            raise
        async with tenant_session(tenant_id) as session:
            await notes_live.queue_put_live(
                session, tenant_id=tenant_id, jobs=[("line", line_id)], always=True
            )
        raise saved_goes_live_later() from exc
    return await _read(tenant_id, line_id)


@router.post(
    "/{line_id}/proposal",
    response_model=CampaignProposalOut,
    status_code=202,
    openapi_extra=permission_meta("org:manage"),
    summary="Ask Pip to write the line's script from its main task and sources",
)
async def request_proposal(
    line_id: UUID,
    session: Session,
    request: Request,
    principal: Writer,
    payload: CampaignProposalIn | None = None,
) -> CampaignProposalOut:
    tenant_id = _tenant(principal)
    # A one-part ask (`part`, `language`, `want`) as a campaign's (`part_focus`).
    focus = part_focus(payload)
    ask = payload.ask() if payload is not None else {}
    # Writing it spends the account's dashboard AI allowance, as a campaign's script does.
    assert_view_as_may(principal, "billing.ai_assist")
    await require_ai_assist(session, tenant_id=tenant_id)
    proposal = await lines.request_proposal(
        session,
        tenant_id=tenant_id,
        line_id=line_id,
        requested_by=principal.user_id,
        ask=ask or None,
        focus=focus,
    )
    await write_audit(
        session,
        action="inbound_line.script_requested",
        actor=principal,
        tenant_id=tenant_id,
        object_type="inbound_line",
        object_id=str(line_id),
        ip=client_request_ip(request),
        summary={"proposal_id": str(proposal.id), **(focus or {}), **asked_summary(ask)},
    )
    out = proposal_out(proposal)
    assert out is not None
    return out


@router.delete(
    "/{line_id}/proposal/{line_proposal_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Stop Pip's draft while it is written, or discard it",
)
async def clear_proposal(
    line_id: UUID, line_proposal_id: UUID, session: Session, _: Writer
) -> None:
    await lines.clear_proposal(session, line_id, line_proposal_id)


class InboundLineNumberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number_id: UUID


@router.post(
    "/{line_id}/numbers",
    response_model=InboundLineOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Put a number on this line; it answers with the line from now on",
)
async def assign_number(
    line_id: UUID, payload: InboundLineNumberIn, request: Request, principal: Writer
) -> InboundLineOut:
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
        # The number's own gates (activation, the platform binding) are the number
        # assignment's, applied as for any agent.
        await number_catalog.assign_number_to_agent(
            session,
            tenant_id=tenant_id,
            number_id=payload.number_id,
            agent_id=line.agent_id,
            onto_line=line_id,
        )
        moved_from = await lines.assign_number(session, line_id, payload.number_id)
        await write_audit(
            session,
            action="inbound_line.number_assigned",
            actor=principal,
            tenant_id=tenant_id,
            object_type="inbound_line",
            object_id=str(line_id),
            ip=client_request_ip(request),
            summary={
                "number_id": str(payload.number_id),
                "from_line": None if moved_from is None else str(moved_from),
            },
        )
    await route_numbers(tenant_id=tenant_id, line_id=line_id)
    return await _read(tenant_id, line_id)


@router.post(
    "/{line_id}/archive",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Archive a line that answers no number",
)
async def archive_line(line_id: UUID, request: Request, principal: Writer) -> None:
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        agent_id = (await lines.read_line(session, line_id)).agent_id
        ref = await lines.archive_line(session, line_id)
        if ref:
            from apps.api.kb.service import withdraw_line_knowledge

            # Its knowledge copies would otherwise stay attached, billed and stale.
            await withdraw_line_knowledge(session, tenant_id=tenant_id, line_id=line_id)
            # Deleted after this commits and once no call is connected on it.
            await agents_service.retire_engine_agent(
                session, tenant_id=tenant_id, agent_id=agent_id, ref=ref
            )
        await write_audit(
            session,
            action="inbound_line.archived",
            actor=principal,
            tenant_id=tenant_id,
            object_type="inbound_line",
            object_id=str(line_id),
            ip=client_request_ip(request),
            summary={},
        )


class LineCallOut(_Out):
    id: UUID
    started_at: datetime | None
    duration_s: int | None
    status: str
    outcome_tag: str | None


class LineCallsOut(_Out):
    calls: list[LineCallOut]


@router.get(
    "/{line_id}/calls",
    response_model=LineCallsOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The calls this line took, newest first",
)
async def line_calls(line_id: UUID, session: Session, _: Reader) -> LineCallsOut:
    await lines.read_line(session, line_id)
    rows = (
        await session.execute(
            text(
                # The owner's own test calls are listed under Test call, not as calls taken.
                "SELECT id, started_at, duration_s, status, outcome_tag FROM calls "
                "WHERE inbound_line_id = :lid AND NOT trial_call AND NOT paid_test_call "
                "ORDER BY started_at DESC NULLS LAST, id DESC LIMIT :n"
            ),
            {"lid": line_id, "n": CALLS_SHOWN},
        )
    ).all()
    return LineCallsOut(
        calls=[
            LineCallOut(
                id=r.id,
                started_at=r.started_at,
                duration_s=r.duration_s,
                status=str(r.status),
                outcome_tag=r.outcome_tag,
            )
            for r in rows
        ]
    )


@router.get(
    "/{line_id}/diagnosis",
    response_model=HolderDiagnosisOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Where this line's calls lose people, its mistakes, and why people said no",
)
async def line_diagnosis(line_id: UUID, session: Session, _: TestReader) -> HolderDiagnosisOut:
    await lines.read_line(session, line_id)
    return await holder_diagnosis(session, Holder("inbound_line", line_id))


@router.get(
    "/{line_id}/give-callers-time",
    response_model=HolderGiveTimeOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Whether this line's calls give a quiet caller time",
    description=GIVE_TIME_DESCRIPTION,
)
async def line_give_time(line_id: UUID, session: Session, _: Reader) -> HolderGiveTimeOut:
    return holder_give_time_out(
        await give_callers_time.read_holder_give_time(session, Holder("inbound_line", line_id))
    )


@router.put(
    "/{line_id}/give-callers-time",
    response_model=HolderGiveTimeOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Switch giving a quiet caller time on or off for this line",
    description=GIVE_TIME_DESCRIPTION + " A live line is put live again with the choice.",
)
async def set_line_give_time(
    line_id: UUID, payload: HolderGiveTimeIn, request: Request, principal: Writer
) -> HolderGiveTimeOut:
    tenant_id = _tenant(principal)
    holder = Holder("inbound_line", line_id)
    async with tenant_session(tenant_id) as session:
        await give_callers_time.read_holder_give_time(session, holder)
        moved = await give_callers_time.set_holder_give_time(session, holder, on=payload.on)
        await write_audit(
            session,
            action="inbound_line.give_callers_time",
            actor=principal,
            tenant_id=tenant_id,
            object_type="inbound_line",
            object_id=str(line_id),
            ip=client_request_ip(request),
            summary={"on": payload.on},
        )
    if moved:
        await _republish_if_live(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        return holder_give_time_out(await give_callers_time.read_holder_give_time(session, holder))


@router.post(
    "/{line_id}/test-call",
    response_model=CampaignTestCallOut,
    responses=SLOTS_FULL_RESPONSES,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Ring your own phone with this line, as a caller would hear it",
    description=(
        "Puts the line's script on its own engine agent first: a live line is put live again, "
        "and a draft is readied as a test holder, so a line with no number can be heard while "
        "it stays a draft. Then the same gated, capped, idempotent test call as an agent's "
        "(`POST /v1/trial/calls`): the dial gate, the trial's minutes and Studio minutes, a "
        "paid account's daily cap. Needs an `Idempotency-Key` header."
    ),
)
async def line_test_call(
    line_id: UUID,
    payload: CampaignTestCallIn,
    request: Request,
    session: Session,
    principal: Dispatcher,
) -> CampaignTestCallOut:
    idem_key = require_idempotency_key(
        request.headers.get("Idempotency-Key"),
        title="A test call needs an Idempotency-Key header",
        detail="Each test call rings a real phone, so every attempt names itself.",
    )
    line = await lines.read_line(session, line_id)
    if payload.number_is_mine:
        await attest_own_number(
            principal=principal, number=payload.number, ip=client_request_ip(request)
        )
    result = await place_trial_call(
        session,
        principal=principal,
        agent_id=line.agent_id,
        number=payload.number,
        idempotency_key=idem_key,
        ip=client_request_ip(request),
        own_number_attested=payload.number_is_mine,
        line_id=line_id,
    )
    if result.call_id is not None:
        await remember_test_number(session, payload.number)
    return CampaignTestCallOut(
        status=result.status,
        blocked_reason=result.blocked_reason,
        blocked_rule=result.blocked_rule,
        call_id=result.call_id,
        shared_fallback=result.shared_fallback,
    )


@router.get(
    "/{line_id}/test-calls",
    response_model=list[CampaignTestCallItem],
    openapi_extra=permission_meta("leads:read"),
    summary="The test calls rung through this line, newest first",
)
async def line_test_calls(
    line_id: UUID, session: Session, _: TestReader
) -> list[CampaignTestCallItem]:
    await lines.read_line(session, line_id)
    rows = await session.execute(
        text(
            "SELECT id, created_at, status, duration_s, recording_url IS NOT NULL FROM calls "
            "WHERE inbound_line_id = :lid AND (trial_call OR paid_test_call) "
            "ORDER BY created_at DESC, id DESC LIMIT :n"
        ),
        {"lid": line_id, "n": TEST_CALLS_SHOWN},
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


@router.get(
    "/{line_id}/test-numbers",
    response_model=TestNumbersOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The account's saved test numbers, offered under this line's Test call",
)
async def line_test_numbers(line_id: UUID, session: Session, _: TestReader) -> TestNumbersOut:
    await lines.read_line(session, line_id)
    return TestNumbersOut(numbers=await saved_test_numbers(session))
