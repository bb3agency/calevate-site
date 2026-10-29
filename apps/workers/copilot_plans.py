"""Runs an approved plan (D-893 F3): `run_copilot_plan`, and the sweep that resumes one.

ENQUEUED THROUGH THE OUTBOX by `copilot/plans.approve`, in the transaction that approved
the plan, so an approved plan always has its run queued.

EXACTLY THE FROZEN TARGETS, EACH RE-CHECKED. Every target is run in its own transaction:
lock the next pending targets (`SKIP LOCKED`), run the action's per-target function — the
service function the console button calls, which applies every gate as it stands now —
and settle the target with a compare-and-set on `pending`. A crash rolls that target back
to pending; the next run picks it up, and a target already settled is never run twice.

WHO IT RUNS AS: the person who approved it, their role re-read NOW, so a member demoted
or removed since is refused by the same permission ladder (or, gone, the rest is skipped).

A DIALLING PLAN does not dial here: it creates a `pip` campaign over the frozen leads and
launches it (`SetAction.dial`), so the dispatcher's line limit, pacing, calling hours,
retries and per-dial compliance gate apply.

`resume_copilot_plans` (every 5 minutes) re-queues a plan whose worker stopped holding it:
approved or running, with no progress for `STALL_AFTER`. Idempotent per target, so a
double delivery costs a read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.copilot import plans
from apps.api.copilot.actions import ToolActor, may_act
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

#: The ARQ names, spelled in this file for `scripts/check_job_wiring.py`.
JOB_NAME: Final = "run_copilot_plan"
RESUME_JOB_NAME: Final = "resume_copilot_plans"

#: A running plan with no progress for this long has lost its worker.
STALL_AFTER: Final = timedelta(minutes=10)
#: Plans one resume tick re-queues at most.
MAX_RESUMES_PER_TICK: Final = 50

_STALLED_SQL: Final = (
    "SELECT id, tenant_id FROM copilot_plans WHERE status IN ('approved', 'running') "
    "AND updated_at < :cutoff ORDER BY updated_at LIMIT :limit"
)


async def _actor(tenant_id: UUID, user_id: UUID) -> ToolActor | None:
    async with tenant_session(tenant_id) as session:
        role = (
            await session.execute(
                # A deactivated person's approval stops counting the moment they are
                # deactivated, exactly like a removed membership.
                text(
                    "SELECT m.role FROM memberships m JOIN users u ON u.id = m.user_id "
                    "WHERE m.user_id = :uid AND u.deactivated_at IS NULL"
                ),
                {"uid": user_id},
            )
        ).scalar_one_or_none()
    if role is None:
        return None
    return ToolActor(tenant_id=tenant_id, user_id=user_id, role=str(role), impersonating=False)


async def _close(tenant_id: UUID, plan_id: UUID, *, skip_reason: str | None, note: str) -> None:
    async with tenant_session(tenant_id) as session:
        if skip_reason is not None:
            await plans.skip_rest(session, plan_id, reason=skip_reason)
        await plans.finish(session, plan_id, note=note)


async def run_copilot_plan(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Run one approved plan to the end, or until it is cancelled. Returns an outcome word."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    plan_id = UUID(str(payload["plan_id"]))
    async with tenant_session(tenant_id) as session:
        plan = await plans.claim_run(session, plan_id)
    if plan is None:
        return "not_runnable"
    action = plans.set_action_of(plan.tool)
    from apps.api.copilot import write_tools

    tool = write_tools.tool_named(plan.tool)
    if action is None or tool is None:
        await _close(
            tenant_id,
            plan_id,
            skip_reason="This kind of plan can no longer be run.",
            note="Nothing was done.",
        )
        return "unknown_tool"
    actor = await _actor(tenant_id, plan.user_id)
    if actor is None:
        await _close(
            tenant_id,
            plan_id,
            skip_reason="The person who approved it is no longer on the account.",
            note="Nothing more was done.",
        )
        return "member_gone"
    async with tenant_session(tenant_id) as session:
        allowed = await may_act(session, actor, tool.permission)
    if not allowed:
        await _close(
            tenant_id,
            plan_id,
            skip_reason="The approver's role no longer allows this.",
            note="Nothing more was done.",
        )
        return "forbidden"

    if action.dial is not None:
        return await _run_dial(tenant_id, plan, actor, action)
    return await _run_each(tenant_id, plan_id, actor, action)


async def _run_each(
    tenant_id: UUID, plan_id: UUID, actor: ToolActor, action: plans.SetAction
) -> str:
    assert action.run_one is not None
    plan = None
    while True:
        async with tenant_session(tenant_id) as session:
            if not await plans.still_running(session, plan_id):
                return "stopped"
            plan = await plans.read_plan(session, plan_id)
            batch = await plans.pending_batch(session, plan_id, size=plans.BATCH)
        if not batch or plan is None:
            break
        for target_id in batch:
            await _run_target(tenant_id, plan_id, actor, action, plan.args, target_id)
        async with tenant_session(tenant_id) as session:
            await plans.heartbeat(session, plan_id)
    async with tenant_session(tenant_id) as session:
        await plans.finish(session, plan_id)
    log.info("copilot_plan_finished", extra={"plan_id": str(plan_id)})
    return "done"


async def _run_target(
    tenant_id: UUID,
    plan_id: UUID,
    actor: ToolActor,
    action: plans.SetAction,
    change: dict[str, Any],
    target_id: UUID,
) -> None:
    """One target, one transaction: the effect and its settlement commit together."""
    assert action.run_one is not None
    try:
        async with tenant_session(tenant_id) as session:
            claimed = (
                await session.execute(
                    text(
                        "SELECT 1 FROM copilot_plan_targets WHERE plan_id = :pid "
                        "AND target_id = :tid AND status = 'pending' FOR UPDATE SKIP LOCKED"
                    ),
                    {"pid": plan_id, "tid": target_id},
                )
            ).first()
            if claimed is None:
                return
            try:
                outcome = await action.run_one(session, actor, change, target_id)
            except ProblemError as problem:
                outcome = plans.TargetOutcome("failed", problem.detail)
            await plans.record_outcome(session, plan_id, target_id, outcome)
    except Exception as failure:
        # Ids only (hard rule 6). The effect rolled back with the transaction; the target
        # is settled as failed in a fresh one so the plan can finish.
        log.warning(
            "copilot_plan_target_failed",
            extra={"plan_id": str(plan_id), "error": type(failure).__name__},
        )
        async with tenant_session(tenant_id) as session:
            await plans.record_outcome(
                session,
                plan_id,
                target_id,
                plans.TargetOutcome("failed", "Something went wrong; nothing was changed."),
            )


async def _run_dial(
    tenant_id: UUID, plan: plans.PlanRow, actor: ToolActor, action: plans.SetAction
) -> str:
    assert action.dial is not None
    if plan.campaign_id is not None:
        # A resumed run of a plan whose campaign already exists: the campaign holds it now.
        async with tenant_session(tenant_id) as session:
            await plans.finish(session, plan.id, note="The calls run as a campaign.")
        return "done"
    try:
        async with tenant_session(tenant_id) as session:
            batch = await plans.pending_batch(session, plan.id, size=plan.target_count)
            started = await action.dial(session, actor, plan.args, plan.title, batch)
            await plans.attach_campaign(session, plan.id, started.campaign_id)
            for target_id, outcome in started.outcomes.items():
                await plans.record_outcome(session, plan.id, target_id, outcome)
            await plans.finish(session, plan.id, note="The calls run as a campaign.")
    except ProblemError as problem:
        # The launch gate (or the campaign) refused: nothing was created, and the plan says
        # why in the gate's own words.
        await _close(
            tenant_id,
            plan.id,
            skip_reason=problem.detail,
            note="No calls were placed.",
        )
        return "refused"
    return "done"


async def resume_copilot_plans(ctx: dict[str, Any]) -> str:
    """Re-queue the plans a worker stopped holding. Counts only, never an id."""
    del ctx
    cutoff = datetime.now(UTC) - STALL_AFTER
    try:
        async with untenanted_session() as session:
            stalled = [
                (UUID(str(r[0])), UUID(str(r[1])))
                for r in (
                    await session.execute(
                        text(_STALLED_SQL), {"cutoff": cutoff, "limit": MAX_RESUMES_PER_TICK}
                    )
                ).all()
            ]
    except Exception as failure:
        alert(
            "WORKER_TERMINAL",
            "copilot_plans_resume_failed",
            detail="the plan resume sweep could not read which plans stalled",
            error=type(failure).__name__,
        )
        raise
    for plan_id, tenant_id in stalled:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE copilot_plans SET updated_at = now() WHERE id = :id"),
                {"id": plan_id},
            )
            await enqueue_outbox(
                session,
                job=JOB_NAME,
                payload={"tenant_id": str(tenant_id), "plan_id": str(plan_id)},
            )
    if stalled:
        log.warning("copilot_plans_resumed", extra={"count": len(stalled)})
    return f"resumed={len(stalled)}"


__all__ = [
    "JOB_NAME",
    "MAX_RESUMES_PER_TICK",
    "RESUME_JOB_NAME",
    "STALL_AFTER",
    "resume_copilot_plans",
    "run_copilot_plan",
]
