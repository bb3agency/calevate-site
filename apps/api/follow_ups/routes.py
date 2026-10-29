"""`/v1/follow-ups` (D-940), the client realm's Follow-ups.

Reads are `leads:read`; every write is `leads:dispatch`, the permission that already decides
who may have a lead called, because a Follow-up places calls and sends messages. A view-as
session follows `rbac.withheld_from_view_as` through `requires()`. Every write is audited in
its own transaction.

`/starters` is declared before `/{follow_up_id}` so the literal segment is matched first.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.follow_ups import definition as d
from apps.api.follow_ups import service, starters
from apps.api.follow_ups.schemas import (
    CountsOut,
    FollowUpCreateIn,
    FollowUpDraftIn,
    FollowUpEditIn,
    FollowUpListOut,
    FollowUpOut,
    FollowUpPublishIn,
    FollowUpResultsOut,
    FollowUpRunOut,
    FollowUpRunsOut,
    FollowUpStarterOut,
    FollowUpStartersOut,
    FollowUpStartIn,
    FollowUpStartOut,
    FollowUpSummaryOut,
    LiveVersionOut,
    ProblemOut,
    RunEventOut,
    RunStatus,
    StepEditIn,
    StepOut,
    StepResultOut,
)

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("leads:read"))]
Writer = Annotated[Principal, Depends(requires("leads:dispatch"))]

router = APIRouter(prefix="/v1/follow-ups", tags=["follow-ups"])


_STEP_OUT: TypeAdapter[StepOut] = TypeAdapter(StepOut)


def _step_out(step: d.AnyStep, names: d.Names) -> StepOut:
    return _STEP_OUT.validate_python({**step.model_dump(), "summary": d.summary(step, names)})


def _counts(counts: service.Counts) -> CountsOut:
    return CountsOut(
        running=counts.running,
        waiting=counts.waiting,
        done_30d=counts.done_30d,
        goal_30d=counts.goal_30d,
    )


def starts_when(trigger: d.AnyTrigger) -> str:
    """What starts a Follow-up, as one plain line for the list."""
    if isinstance(trigger, d.NewLeadTrigger):
        return "A new lead arrives" + ("" if trigger.source_ids is None else " from chosen sources")
    if isinstance(trigger, d.CallEndedTrigger):
        which = {"inbound": "An incoming call", "outbound": "A call we made", "both": "A call"}
        return f"{which[trigger.calls]} ends"
    if isinstance(trigger, d.LeadDateTrigger):
        field = trigger.field.replace("_", " ")
        if trigger.offset_days == 0:
            return f"On the lead's {field}"
        side = "before" if trigger.offset_days < 0 else "after"
        return f"{abs(trigger.offset_days)} day(s) {side} the lead's {field}"
    return "You start it for chosen leads"


async def _out(session: AsyncSession, row: service.Row) -> FollowUpOut:
    names = await service.names(session)
    problems = await service.problems_of(session, row.trigger, row.steps, row.settings)
    counts = (await service.counts(session, [row.id]))[row.id]
    return FollowUpOut(
        id=row.id,
        name=row.name,
        status=row.status,  # type: ignore[arg-type]
        starter=row.starter,  # type: ignore[arg-type]
        trigger=row.trigger,
        settings=row.settings,
        steps=[_step_out(s, names) for s in row.steps],
        has_unpublished_changes=row.has_unpublished_changes,
        live_version=(
            LiveVersionOut(number=row.live_number, published_at=row.live_published_at)
            if row.live_number is not None and row.live_published_at is not None
            else None
        ),
        counts=_counts(counts),
        problems=[ProblemOut(step_id=p.step_id, code=p.code, message=p.message) for p in problems],
        updated_at=row.updated_at,
    )


async def _audit(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    action: str,
    object_id: str,
    summary: dict[str, object] | None = None,
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="follow_up",
        object_id=object_id,
        ip=client_request_ip(request),
        summary=summary,
    )


@router.get(
    "",
    response_model=FollowUpListOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The account's Follow-ups",
)
async def list_follow_ups(
    session: Session,
    _: Reader,
    limit: int = Query(service.LIST_MAX, ge=1, le=service.LIST_MAX),
) -> FollowUpListOut:
    rows = await service.list_all(session, limit=limit)
    counts = await service.counts(session, [r.id for r in rows])
    return FollowUpListOut(
        items=[
            FollowUpSummaryOut(
                id=r.id,
                name=r.name,
                status=r.status,  # type: ignore[arg-type]
                starter=r.starter,  # type: ignore[arg-type]
                trigger=r.trigger,
                starts_when=starts_when(r.trigger),
                has_unpublished_changes=r.has_unpublished_changes,
                counts=_counts(counts[r.id]),
                updated_at=r.updated_at,
            )
            for r in rows
        ]
    )


@router.get(
    "/starters",
    response_model=FollowUpStartersOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The ready-made Follow-ups, filled in for this account",
)
async def list_starters(session: Session, _: Reader) -> FollowUpStartersOut:
    names = await service.names(session)
    return FollowUpStartersOut(
        items=[
            FollowUpStarterOut(
                key=s.key,  # type: ignore[arg-type]
                name=s.name,
                description=s.description,
                trigger=s.trigger,
                steps=[_step_out(step, names) for step in s.steps],
                settings=s.settings,
                available=s.available,
                needs=s.needs,
            )
            for s in await starters.for_account(session)
        ]
    )


@router.post(
    "",
    response_model=FollowUpOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Make a Follow-up (a draft until it is published)",
)
async def create_follow_up(
    payload: FollowUpCreateIn, session: Session, request: Request, principal: Writer
) -> FollowUpOut:
    assert principal.tenant_id is not None
    row = await service.create(
        session,
        tenant_id=principal.tenant_id,
        name=payload.name,
        trigger=payload.trigger,
        steps=list(payload.steps),
        settings=payload.settings,
        starter=payload.starter,
        user_id=principal.client_user_id,
    )
    await _audit(
        session,
        request,
        principal,
        "follow_up.created",
        str(row.id),
        {"steps": len(row.steps), "starter": row.starter or "", "trigger": row.trigger.kind},
    )
    return await _out(session, row)


@router.get(
    "/{follow_up_id}",
    response_model=FollowUpOut,
    openapi_extra=permission_meta("leads:read"),
    summary="One Follow-up, its steps and what stops it from publishing",
)
async def get_follow_up(follow_up_id: UUID, session: Session, _: Reader) -> FollowUpOut:
    return await _out(session, await service.get(session, follow_up_id))


def _step_edit(edit: StepEditIn) -> service.StepEdit:
    return service.StepEdit(
        step_id=edit.step_id,
        wait_minutes=edit.wait.total_minutes() if edit.wait is not None else None,
        template_id=edit.template_id,
        values=edit.values,
        agent_id=edit.agent_id,
        remove=edit.remove,
    )


@router.patch(
    "/{follow_up_id}",
    response_model=FollowUpOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Small edits: the name, a wait, a message, the calling agent, remove a step",
)
async def edit_follow_up(
    follow_up_id: UUID,
    payload: FollowUpEditIn,
    session: Session,
    request: Request,
    principal: Writer,
) -> FollowUpOut:
    edits = [_step_edit(e) for e in payload.step_edits or []]
    row = await service.edit(
        session, follow_up_id, name=payload.name, step_edits=edits, settings=payload.settings
    )
    await _audit(
        session,
        request,
        principal,
        "follow_up.edited",
        str(follow_up_id),
        {
            "step_edits": len(edits),
            "removed": sum(e.remove for e in edits),
            "name": payload.name is not None,
            "settings": payload.settings is not None,
        },
    )
    return await _out(session, row)


@router.put(
    "/{follow_up_id}/draft",
    response_model=FollowUpOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Replace the draft: trigger, steps and settings",
)
async def save_follow_up_draft(
    follow_up_id: UUID,
    payload: FollowUpDraftIn,
    session: Session,
    request: Request,
    principal: Writer,
) -> FollowUpOut:
    row = await service.save_draft(
        session,
        follow_up_id,
        trigger=payload.trigger,
        steps=list(payload.steps),
        settings=payload.settings,
    )
    await _audit(
        session,
        request,
        principal,
        "follow_up.draft_saved",
        str(follow_up_id),
        {"steps": len(row.steps), "trigger": row.trigger.kind},
    )
    return await _out(session, row)


@router.post(
    "/{follow_up_id}/publish",
    response_model=FollowUpOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Publish the draft as the next version; runs already going keep theirs",
)
async def publish_follow_up(
    follow_up_id: UUID,
    payload: FollowUpPublishIn,
    session: Session,
    request: Request,
    principal: Writer,
) -> FollowUpOut:
    assert principal.tenant_id is not None
    row = await service.publish(
        session,
        follow_up_id,
        tenant_id=principal.tenant_id,
        expected_updated_at=payload.expected_updated_at,
        user_id=principal.client_user_id,
    )
    await _audit(
        session,
        request,
        principal,
        "follow_up.published",
        str(follow_up_id),
        {"version": row.live_number or 0, "status": row.status},
    )
    return await _out(session, row)


@router.post(
    "/{follow_up_id}/pause",
    response_model=FollowUpOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Pause: leads wait where they are",
)
async def pause_follow_up(
    follow_up_id: UUID, session: Session, request: Request, principal: Writer
) -> FollowUpOut:
    row = await service.pause(session, follow_up_id)
    await _audit(session, request, principal, "follow_up.paused", str(follow_up_id))
    return await _out(session, row)


@router.post(
    "/{follow_up_id}/resume",
    response_model=FollowUpOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Turn a paused or turned-off Follow-up back on",
)
async def resume_follow_up(
    follow_up_id: UUID, session: Session, request: Request, principal: Writer
) -> FollowUpOut:
    assert principal.tenant_id is not None
    row = await service.resume(session, follow_up_id, tenant_id=principal.tenant_id)
    await _audit(session, request, principal, "follow_up.resumed", str(follow_up_id))
    return await _out(session, row)


@router.post(
    "/{follow_up_id}/turn-off",
    response_model=FollowUpOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Turn off: no new leads start, and leads going through it stop",
)
async def turn_off_follow_up(
    follow_up_id: UUID, session: Session, request: Request, principal: Writer
) -> FollowUpOut:
    row = await service.turn_off(session, follow_up_id)
    await _audit(session, request, principal, "follow_up.turned_off", str(follow_up_id))
    return await _out(session, row)


@router.post(
    "/{follow_up_id}/start",
    response_model=FollowUpStartOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Start picked leads, or the leads a filter matches, on this Follow-up",
)
async def start_follow_up(
    follow_up_id: UUID,
    payload: FollowUpStartIn,
    session: Session,
    request: Request,
    principal: Writer,
) -> FollowUpStartOut:
    from apps.api.crm import lens

    assert principal.tenant_id is not None
    if (payload.lead_ids is None) == (payload.lens is None):
        raise ProblemError(
            kind="validation",
            code="follow_up_start_unclear",
            title="Choose the leads",
            detail="Send either the lead ids or a filter, not both.",
        )
    if payload.lead_ids is not None:
        lead_ids = list(dict.fromkeys(payload.lead_ids))
    else:
        assert payload.lens is not None
        lead_ids = await lens.lead_ids(
            session, await lens.resolve_lead_scope(session, payload.lens)
        )
    if payload.expected_count is not None and payload.expected_count != len(lead_ids):
        raise ProblemError.conflict(
            "follow_up_start_set_moved",
            f"This now matches {len(lead_ids)} leads rather than the {payload.expected_count} "
            "you confirmed, so nobody was started.",
            remediation="Check the leads and start again.",
        )
    if len(lead_ids) > service.MAX_START_LEADS:
        raise ProblemError(
            kind="validation",
            code="follow_up_start_too_many",
            title="Too many leads at once",
            detail=f"Start at most {service.MAX_START_LEADS} leads at a time, or ask Pip.",
        )
    outcome = await service.start_leads(
        session, follow_up_id, tenant_id=principal.tenant_id, lead_ids=lead_ids
    )
    await _audit(
        session,
        request,
        principal,
        "follow_up.started",
        str(follow_up_id),
        {"started": outcome.started, "skipped": outcome.skipped},
    )
    return FollowUpStartOut(started=outcome.started, skipped=outcome.skipped, plan_id=None)


async def _runs_out(session: AsyncSession, views: list[service.RunView]) -> list[FollowUpRunOut]:
    names = await service.names(session)
    steps = await service.run_steps(session, [v.id for v in views])
    out: list[FollowUpRunOut] = []
    for view in views:
        step = d.step_by_id(steps.get(view.id, []), view.step_id)
        out.append(
            FollowUpRunOut(
                id=view.id,
                lead_id=view.lead_id,
                lead_name=view.lead_name,
                status=view.status,  # type: ignore[arg-type]
                step_id=view.step_id,
                step_summary=d.summary(step, names) if step is not None else None,
                attempt=view.attempt,
                wake_at=view.wake_at,
                started_at=view.started_at,
                ended_at=view.ended_at,
                end_reason=view.end_reason,
                goal_reached=view.goal_reached,
                last_result=view.last_result,
            )
        )
    return out


@router.get(
    "/{follow_up_id}/runs",
    response_model=FollowUpRunsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The leads going (or gone) through a Follow-up, newest first",
)
async def list_follow_up_runs(
    follow_up_id: UUID,
    session: Session,
    _: Reader,
    status: RunStatus | None = None,
    cursor: str | None = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=service.RUNS_PAGE_MAX),
) -> FollowUpRunsOut:
    views, next_cursor = await service.list_runs(
        session, follow_up_id, status=status, cursor=cursor, limit=limit
    )
    return FollowUpRunsOut(items=await _runs_out(session, views), next_cursor=next_cursor)


@router.get(
    "/{follow_up_id}/runs/{run_id}",
    response_model=FollowUpRunOut,
    openapi_extra=permission_meta("leads:read"),
    summary="One lead's way through a Follow-up, step by step",
)
async def get_follow_up_run(
    follow_up_id: UUID, run_id: UUID, session: Session, _: Reader
) -> FollowUpRunOut:
    view, events = await service.get_run(session, follow_up_id, run_id)
    item = (await _runs_out(session, [view]))[0]
    return item.model_copy(
        update={
            "events": [
                RunEventOut(
                    step_id=e.step_id, kind=e.kind, result=e.result, at=e.at, call_id=e.call_id
                )
                for e in events
            ]
        }
    )


@router.post(
    "/{follow_up_id}/runs/{run_id}/stop",
    response_model=FollowUpRunOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Stop one lead's way through a Follow-up",
)
async def stop_follow_up_run(
    follow_up_id: UUID, run_id: UUID, session: Session, request: Request, principal: Writer
) -> FollowUpRunOut:
    await service.stop_run(session, follow_up_id, run_id)
    await _audit(
        session,
        request,
        principal,
        "follow_up.run_stopped",
        str(follow_up_id),
        {"run_id": str(run_id)},
    )
    view, _events = await service.get_run(session, follow_up_id, run_id)
    return (await _runs_out(session, [view]))[0]


@router.get(
    "/{follow_up_id}/results",
    response_model=FollowUpResultsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="How many leads reached each step and each exit, last 30 days",
)
async def follow_up_results(follow_up_id: UUID, session: Session, _: Reader) -> FollowUpResultsOut:
    found = await service.results(session, follow_up_id)
    return FollowUpResultsOut(
        days=service.RESULT_DAYS,
        started=found.started,
        finished=found.finished,
        goal_reached=found.goal_reached,
        steps=[
            StepResultOut(step_id=s.step_id, reached=s.reached, exits=s.exits) for s in found.steps
        ],
    )


__all__ = ["router", "starts_when"]
