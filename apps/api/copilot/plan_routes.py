"""Plans on the wire (D-893 F3): read one, its targets and progress, approve it, cancel it.

Mounted beside `copilot/routes.py` under `/v1/copilot` and behind the same door,
`copilot:use`, which a view-as session does not hold. A plan is its author's: another
person's plan and another account's are the same 404. Approving re-checks the permission
of the plan's own action (`may_act`), so the role a person holds NOW decides, and binds the
plan's hash, so the approval is for the plan the person was shown.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.copilot import plans, write_tools
from apps.api.copilot.actions import actor_for, may_act
from apps.api.copilot.plan_schemas import (
    CopilotPlanApproveIn,
    CopilotPlanOut,
    CopilotPlanPageOut,
    CopilotPlanTargetPageOut,
    plan_out,
    target_out,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import Permission, permission_meta

router = APIRouter(prefix="/v1", tags=["copilot"])

_USE: Permission = "copilot:use"
CopilotUser = Annotated[Principal, Depends(requires(_USE))]
Session = Annotated[AsyncSession, Depends(db)]


def _user(principal: Principal) -> UUID:
    if principal.tenant_id is None or principal.client_user_id is None:
        raise ProblemError(
            kind="permission",
            code="copilot_plan_not_yours",
            title="This belongs to someone else",
            detail="Only the person a plan was made for can see or approve it.",
            remediation="Sign in to your own dashboard to see your plans.",
        )
    return principal.client_user_id


@router.get(
    "/copilot/plans",
    response_model=CopilotPlanPageOut,
    openapi_extra=permission_meta(_USE),
    summary="My recent plans, newest first",
)
async def list_copilot_plans(
    session: Session,
    principal: CopilotUser,
    limit: int = Query(20, ge=1, le=50),
) -> CopilotPlanPageOut:
    rows = await plans.recent_plans(session, user_id=_user(principal), limit=limit)
    return CopilotPlanPageOut(plans=[plan_out(row) for row in rows])


@router.get(
    "/copilot/plans/{plan_id}",
    response_model=CopilotPlanOut,
    openapi_extra=permission_meta(_USE),
    summary="One plan: who, why, when, the estimate, who is left out, and its progress",
)
async def get_copilot_plan(
    plan_id: UUID, session: Session, principal: CopilotUser
) -> CopilotPlanOut:
    return plan_out(await plans.plan_of(session, plan_id, user_id=_user(principal)))


@router.get(
    "/copilot/plans/{plan_id}/targets",
    response_model=CopilotPlanTargetPageOut,
    openapi_extra=permission_meta(_USE),
    summary="One page of a plan's targets and what happened to each",
)
async def get_copilot_plan_targets(
    plan_id: UUID,
    session: Session,
    principal: CopilotUser,
    limit: int = Query(25, ge=1, le=plans.MAX_TARGET_PAGE),
    offset: int = Query(0, ge=0),
    status: Literal["pending", "done", "skipped", "failed"] | None = None,
) -> CopilotPlanTargetPageOut:
    plan = await plans.plan_of(session, plan_id, user_id=_user(principal))
    rows, total = await plans.targets_page(session, plan, limit=limit, offset=offset, status=status)
    return CopilotPlanTargetPageOut(
        targets=[target_out(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.post(
    "/copilot/plans/{plan_id}/approve",
    response_model=CopilotPlanOut,
    openapi_extra=permission_meta(_USE),
    summary="Approve exactly this plan; it runs in the background",
)
async def approve_copilot_plan(
    plan_id: UUID,
    payload: CopilotPlanApproveIn,
    session: Session,
    request: Request,
    principal: CopilotUser,
) -> CopilotPlanOut:
    user_id = _user(principal)
    actor = actor_for(principal)
    assert actor is not None  # `_user` refused a principal without an account
    plan = await plans.plan_of(session, plan_id, user_id=user_id)
    tool = write_tools.tool_named(plan.tool)
    permission = None if tool is None else tool.permission
    if permission is None or not await may_act(session, actor, permission):
        raise ProblemError(
            kind="permission",
            code="forbidden",
            title="Forbidden",
            detail="You do not have permission to approve this plan.",
            remediation="Ask an owner or manager on this account to approve it instead.",
        )
    approved = await plans.approve(session, actor, plan_id=plan_id, expected_hash=payload.plan_hash)
    await write_audit(
        session,
        action="copilot.plan_approved",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="copilot_plan",
        object_id=str(plan_id),
        ip=client_request_ip(request),
        summary={
            "tool": approved.tool,
            "origin": approved.origin,
            "targets": approved.target_count,
            "excluded": approved.excluded_count,
        },
    )
    return plan_out(approved)


@router.post(
    "/copilot/plans/{plan_id}/cancel",
    response_model=CopilotPlanOut,
    openapi_extra=permission_meta(_USE),
    summary="Stop a plan; what already ran stays, nothing more runs",
)
async def cancel_copilot_plan(
    plan_id: UUID, session: Session, request: Request, principal: CopilotUser
) -> CopilotPlanOut:
    cancelled = await plans.cancel(session, plan_id=plan_id, user_id=_user(principal))
    await write_audit(
        session,
        action="copilot.plan_cancelled",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="copilot_plan",
        object_id=str(plan_id),
        ip=client_request_ip(request),
        summary={
            "tool": cancelled.tool,
            "done": cancelled.done_count,
            "skipped": cancelled.skipped_count,
        },
    )
    return plan_out(cancelled)


__all__ = ["router"]
