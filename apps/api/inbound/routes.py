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

from datetime import datetime
from typing import Annotated
from uuid import UUID

from calevate_shared.call_script import CallScript
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import service as agents_service
from apps.api.agents.trial_calls import attest_own_number, place_trial_call
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.campaigns import number_catalog
from apps.api.campaigns.workspace import MAIN_TASK_MAX
from apps.api.campaigns.workspace_routes import (
    CampaignProposalOut,
    CampaignTestCallIn,
    CampaignTestCallItem,
    CampaignTestCallOut,
    TestNumbersOut,
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
from apps.api.inbound import lines
from apps.api.inbound.publish import put_line_live, route_numbers
from apps.api.reliability.service import require_idempotency_key

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
        created_at=line.created_at,
    )


def _tenant(principal: Principal) -> UUID:
    assert principal.tenant_id is not None
    return principal.tenant_id


async def _read(tenant_id: UUID, line_id: UUID) -> InboundLineOut:
    async with tenant_session(tenant_id) as session:
        return _out(await lines.read_line(session, line_id))


async def _republish_if_live(tenant_id: UUID, line_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        live = (await lines.read_line(session, line_id)).live
    if live:
        await put_line_live(tenant_id=tenant_id, line_id=line_id)


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
    if voice_changed:
        await _republish_if_live(tenant_id, line_id)
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


class InboundLineScriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script: CallScript
    #: The Pip draft this save keeps, settled in the same transaction.
    proposal_id: UUID | None = None


@router.put(
    "/{line_id}/script",
    response_model=InboundLineOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Save the line's script and put it live on its numbers",
)
async def save_script(
    line_id: UUID, payload: InboundLineScriptIn, request: Request, principal: Writer
) -> InboundLineOut:
    tenant_id = _tenant(principal)
    async with tenant_session(tenant_id) as session:
        version = await lines.save_script(session, line_id, payload.script)
        if payload.proposal_id is not None:
            await lines.clear_proposal(session, line_id, payload.proposal_id)
        await write_audit(
            session,
            action="inbound_line.script_saved",
            actor=principal,
            tenant_id=tenant_id,
            object_type="inbound_line",
            object_id=str(line_id),
            ip=client_request_ip(request),
            summary={"version": version, "from_draft": payload.proposal_id is not None},
        )
    try:
        await put_line_live(tenant_id=tenant_id, line_id=line_id)
    except ProblemError as exc:
        # The script is saved; only the platform step did not finish. Saying so keeps the
        # owner from typing it again.
        exc.title = "Saved, but not live yet"
        exc.remediation = (
            "Press Put it live to finish; your script is kept. " + (exc.remediation or "")
        ).strip()
        raise
    return await _read(tenant_id, line_id)


@router.post(
    "/{line_id}/publish",
    response_model=InboundLineOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Put the line's saved script live on its numbers again",
)
async def publish(line_id: UUID, principal: Writer) -> InboundLineOut:
    tenant_id = _tenant(principal)
    await put_line_live(tenant_id=tenant_id, line_id=line_id)
    return await _read(tenant_id, line_id)


@router.post(
    "/{line_id}/proposal",
    response_model=CampaignProposalOut,
    status_code=202,
    openapi_extra=permission_meta("org:manage"),
    summary="Ask Pip to write the line's script from its main task and sources",
)
async def request_proposal(
    line_id: UUID, session: Session, request: Request, principal: Writer
) -> CampaignProposalOut:
    tenant_id = _tenant(principal)
    # Writing it spends the account's dashboard AI allowance, as a campaign's script does.
    assert_view_as_may(principal, "billing.ai_assist")
    await require_ai_assist(session, tenant_id=tenant_id)
    proposal = await lines.request_proposal(
        session, tenant_id=tenant_id, line_id=line_id, requested_by=principal.user_id
    )
    await write_audit(
        session,
        action="inbound_line.script_requested",
        actor=principal,
        tenant_id=tenant_id,
        object_type="inbound_line",
        object_id=str(line_id),
        ip=client_request_ip(request),
        summary={"proposal_id": str(proposal.id)},
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
            session, tenant_id=tenant_id, number_id=payload.number_id, agent_id=line.agent_id
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


@router.post(
    "/{line_id}/test-call",
    response_model=CampaignTestCallOut,
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
    )


#: Test calls listed under a line's Test call; older ones stay in the call logs.
TEST_CALLS_SHOWN = 20


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
