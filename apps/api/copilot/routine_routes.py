"""The assistant workspace's own routes: routines, their runs, and approval previews.

Mounted beside `copilot/routes.py` under the same `/v1/copilot` prefix and the same door:
`copilot:use`, which is withheld from a view-as session, and every read is scoped to the
person as well as the account — a routine runs as its author and is theirs alone, like the
jobs it queues.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.copilot import routines
from apps.api.copilot.approval_preview import preview_approval
from apps.api.copilot.routine_schemas import (
    CopilotApprovalPreviewOut,
    CopilotRoutineIn,
    CopilotRoutineOut,
    CopilotRoutinePageOut,
    CopilotRoutinePatch,
    CopilotRoutineRunOut,
    CopilotRoutineRunPageOut,
    CopilotRoutineSchedule,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import Permission, permission_meta

router = APIRouter(prefix="/v1", tags=["copilot"])

_USE: Permission = "copilot:use"

#: The door every route here shares: a signed-in person on the client realm.
CopilotUser = Annotated[Principal, Depends(requires(_USE))]


def _ids(principal: Principal) -> tuple[UUID, UUID]:
    """The account and the person. Unreachable without both through `requires(copilot:use)`
    on the client realm; raised rather than asserted so a future caller gets a sentence."""
    if principal.tenant_id is None or principal.client_user_id is None:
        raise ProblemError(
            kind="permission",
            code="copilot_routine_not_yours",
            title="This belongs to someone else",
            detail="Only the person who set up a routine can see or change it.",
            remediation="Sign in to your own dashboard and open the assistant there.",
        )
    return principal.tenant_id, principal.client_user_id


def _clock(at_minute: int) -> str:
    return f"{at_minute // 60:02d}:{at_minute % 60:02d}"


def _minute(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def _routine_out(row: routines.RoutineRow) -> CopilotRoutineOut:
    return CopilotRoutineOut(
        id=str(row.id),
        name=row.name,
        instruction=row.instruction,
        schedule=CopilotRoutineSchedule.model_validate(
            {"days": routines.days_of(row.days), "time": _clock(row.at_minute)}
        ),
        enabled=row.enabled,
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _run_out(row: routines.RunRow) -> CopilotRoutineRunOut:
    return CopilotRoutineRunOut(
        id=str(row.id),
        routine_id=str(row.routine_id),
        slot_at=row.slot_at,
        trigger="manual" if row.trigger == "manual" else "schedule",
        status="skipped" if row.status == "skipped" else "queued",
        reason=row.reason,
        job_id=None if row.job_id is None else str(row.job_id),
        job_status=row.job_status,
        created_at=row.created_at,
    )


async def _audit(
    session: AsyncSession,
    principal: Principal,
    request: Request,
    *,
    action: str,
    routine_id: UUID,
    summary: dict[str, object],
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="copilot_routine",
        object_id=str(routine_id),
        ip=client_request_ip(request),
        summary=summary,
    )


@router.get(
    "/copilot/routines",
    response_model=CopilotRoutinePageOut,
    openapi_extra=permission_meta(_USE),
    summary="Your routines — what the assistant does for you on a schedule",
)
async def list_copilot_routines(
    session: Annotated[AsyncSession, Depends(db)],
    principal: CopilotUser,
    limit: Annotated[int, Query(ge=1, le=routines.MAX_ROUTINES_PER_USER)] = (
        routines.MAX_ROUTINES_PER_USER
    ),
) -> CopilotRoutinePageOut:
    _, user_id = _ids(principal)
    rows = await routines.list_routines(session, user_id=user_id, limit=limit)
    return CopilotRoutinePageOut(routines=[_routine_out(row) for row in rows])


@router.post(
    "/copilot/routines",
    response_model=CopilotRoutineOut,
    status_code=201,
    openapi_extra=permission_meta(_USE),
    summary="Add a routine",
)
async def create_copilot_routine(
    body: CopilotRoutineIn,
    session: Annotated[AsyncSession, Depends(db)],
    request: Request,
    principal: CopilotUser,
) -> CopilotRoutineOut:
    """A routine runs as YOU, through your own permissions, as a background task. Anything
    that would call someone, spend money or cannot be undone waits in your Approvals inbox."""
    tenant_id, user_id = _ids(principal)
    row = await routines.create_routine(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        name=body.name,
        instruction=body.instruction,
        days=routines.days_mask(body.schedule.days),
        at_minute=_minute(body.schedule.time),
        enabled=body.enabled,
        now=datetime.now(UTC),
    )
    await _audit(
        session,
        principal,
        request,
        action="copilot.routine_created",
        routine_id=row.id,
        summary={"days": row.days, "at_minute": row.at_minute, "enabled": row.enabled},
    )
    return _routine_out(row)


@router.patch(
    "/copilot/routines/{routine_id}",
    response_model=CopilotRoutineOut,
    openapi_extra=permission_meta(_USE),
    summary="Change a routine, or switch it on or off",
)
async def update_copilot_routine(
    routine_id: UUID,
    body: CopilotRoutinePatch,
    session: Annotated[AsyncSession, Depends(db)],
    request: Request,
    principal: CopilotUser,
) -> CopilotRoutineOut:
    _, user_id = _ids(principal)
    row = await routines.update_routine(
        session,
        routine_id=routine_id,
        user_id=user_id,
        name=body.name,
        instruction=body.instruction,
        days=None if body.schedule is None else routines.days_mask(body.schedule.days),
        at_minute=None if body.schedule is None else _minute(body.schedule.time),
        enabled=body.enabled,
        now=datetime.now(UTC),
    )
    await _audit(
        session,
        principal,
        request,
        action="copilot.routine_updated",
        routine_id=row.id,
        summary={"days": row.days, "at_minute": row.at_minute, "enabled": row.enabled},
    )
    return _routine_out(row)


@router.delete(
    "/copilot/routines/{routine_id}",
    status_code=204,
    openapi_extra=permission_meta(_USE),
    summary="Delete a routine and its run history",
)
async def delete_copilot_routine(
    routine_id: UUID,
    session: Annotated[AsyncSession, Depends(db)],
    request: Request,
    principal: CopilotUser,
) -> Response:
    """Tasks it already queued keep running, and what they did stays in your activity log."""
    _, user_id = _ids(principal)
    await routines.delete_routine(session, routine_id=routine_id, user_id=user_id)
    await _audit(
        session,
        principal,
        request,
        action="copilot.routine_deleted",
        routine_id=routine_id,
        summary={},
    )
    return Response(status_code=204)


@router.post(
    "/copilot/routines/{routine_id}/run",
    response_model=CopilotRoutineRunOut,
    openapi_extra=permission_meta(_USE),
    summary="Run a routine once, now",
)
async def run_copilot_routine(
    routine_id: UUID,
    session: Annotated[AsyncSession, Depends(db)],
    request: Request,
    principal: CopilotUser,
) -> CopilotRoutineRunOut:
    """Queues one background task now; the schedule is unchanged. `409` when you already
    have the most tasks running that one person may."""
    _, user_id = _ids(principal)
    run = await routines.run_now(
        session, routine_id=routine_id, user_id=user_id, now=datetime.now(UTC)
    )
    await _audit(
        session,
        principal,
        request,
        action="copilot.routine_run",
        routine_id=routine_id,
        summary={"job_id": None if run.job_id is None else str(run.job_id)},
    )
    return _run_out(run)


@router.get(
    "/copilot/routines/{routine_id}/runs",
    response_model=CopilotRoutineRunPageOut,
    openapi_extra=permission_meta(_USE),
    summary="When a routine ran, and what became of each run",
)
async def list_copilot_routine_runs(
    routine_id: UUID,
    session: Annotated[AsyncSession, Depends(db)],
    principal: CopilotUser,
    limit: Annotated[int, Query(ge=1, le=routines.RUNS_PAGE_MAX)] = 20,
) -> CopilotRoutineRunPageOut:
    _, user_id = _ids(principal)
    rows = await routines.list_runs(session, routine_id=routine_id, user_id=user_id, limit=limit)
    return CopilotRoutineRunPageOut(runs=[_run_out(row) for row in rows])


@router.get(
    "/copilot/approvals/{action_id}/preview",
    response_model=CopilotApprovalPreviewOut,
    openapi_extra=permission_meta(_USE),
    summary="What approving a waiting action would change, read fresh",
)
async def preview_copilot_approval(
    action_id: UUID,
    session: Annotated[AsyncSession, Depends(db)],
    principal: CopilotUser,
) -> CopilotApprovalPreviewOut:
    """Re-runs the planner on the waiting action against the world as it is now — what
    changes, from what, the cost and whether it can be taken back. Changes nothing."""
    _ids(principal)
    return await preview_approval(session, action_id, principal=principal)


__all__ = ["router"]
