"""Runs one assistant background job (D-694 item 7): `run_copilot_job`.

ENQUEUED THROUGH THE OUTBOX by `copilot/jobs.create_job`, in the same transaction as the
job row, so a job row always has its work queued and queued work always has its row.

ONE ATTEMPT, NO RETRY LADDER. A job performs actions; re-running a half-finished one would
redo the half that landed. The idempotency records `write_tools.run_immediate` claims would
replay those receipts rather than repeat the acts, but "the job ran twice" is still the
wrong story to tell a person, so a failure marks the job `failed` with a code and the
person asks again. arq only retries on `Retry`, which this never raises.

WHO IT RUNS AS. The person who started it, re-read NOW: their membership role is looked up
at the start of the run, so a member demoted or removed since they asked is refused by the
same permission ladder every action uses, rather than acting on yesterday's role. Every
action writes its own `audit_log` row naming that person, exactly as from the panel.

THE SAME GATES AS THE PANEL. The fair-use cap and the platform brake are asked before the
first model call; calling hours, DNC, KYC and the pledge, credit and the big red switch are
enforced where they always are — inside the service functions the actions call, and
inside `launch_campaign` behind the approval, which is the only way a job can reach a
caller at all.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.ai_quota import new_assist_ref
from apps.api.copilot import jobs, model_tiers, service
from apps.api.copilot.context import live_state_block, viewer_for
from apps.api.copilot.fair_use import require_copilot_fair_use
from apps.api.copilot.schemas import CopilotAskIn, CopilotScreen
from apps.api.copilot.tools import ToolContext
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.crm.assist import ASSIST_FEATURE_COPILOT, meter_assist
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: The ARQ name, spelled in this file for `scripts/check_job_wiring.py`, which resolves
#: same-file constants; `copilot/jobs.COPILOT_JOB` is the enqueue side's spelling.
JOB_NAME: Final = "run_copilot_job"


async def _finish(
    tenant_id: UUID, job_id: UUID, *, status: str, result: str | None, code: str | None
) -> None:
    async with tenant_session(tenant_id) as session:
        await jobs.finish_job(
            session,
            job_id=job_id,
            status="done" if status == "done" else "failed",
            result=result,
            error_code=code,
        )


async def run_copilot_job(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Claim the job, run the tool loop under `service.job_limits`, record what happened."""
    del ctx
    job_id = UUID(str(payload["job_id"]))
    tenant_id = UUID(str(payload["tenant_id"]))

    async with tenant_session(tenant_id) as session:
        job = await jobs.claim_job(session, job_id=job_id)
    if job is None:
        # Cancelled before it started, or already claimed by an earlier delivery.
        return "not_queued"

    async with tenant_session(tenant_id) as session:
        role = (
            await session.execute(
                text("SELECT role FROM memberships WHERE user_id = :uid"), {"uid": job.user_id}
            )
        ).scalar()
        refusal: ProblemError | None = None
        if role is not None:
            try:
                await require_copilot_fair_use(session, tenant_id=tenant_id)
            except ProblemError as problem:
                refusal = problem
    if role is None:
        await _finish(
            tenant_id,
            job_id,
            status="failed",
            result="The person who started this is no longer on the account.",
            code="copilot_job_member_gone",
        )
        return "member_gone"
    if refusal is not None:
        await _finish(tenant_id, job_id, status="failed", result=refusal.detail, code=refusal.code)
        return refusal.code

    principal = Principal(realm="client", user_id=job.user_id, tenant_id=tenant_id, role=str(role))
    question = CopilotAskIn(
        screen=CopilotScreen(route=job.screen_route, title="Background job", realm="client"),
        question=job.goal,
    )
    live = await live_state_block(tenant_id, viewer_for(role=str(role), route=job.screen_route))
    spends: list[service.CopilotSpend] = []
    answer: list[str] = []
    status, code = "done", None
    try:
        async for event in service.run_copilot(
            question,
            tenant_leg=model_tiers.tier_leg(model_tiers.route_tier(job.goal, background=True)),
            allow_azure=get_settings().copilot_azure_fallback,
            tool_context=ToolContext(tenant_id=tenant_id, role=str(role)),
            live=live,
            principal=principal,
            # The job id is the conversation: a redelivered job replays its own receipts.
            seed=f"copilot-job:{job_id}",
            ip=None,
            limits=service.job_limits(job_id),
        ):
            entries: list[dict[str, Any]] = []
            if event.text is not None:
                answer.append(event.text)
            if event.step is not None and event.step.status != "running":
                entries.append(
                    jobs.progress_entry("step", f"{event.step.tool}: {event.step.detail or ''}")
                )
            if event.action is not None:
                entries.append(
                    jobs.progress_entry(
                        "action", event.action.detail, action_id=event.action.action_id
                    )
                )
            if event.approval is not None:
                entries.append(
                    jobs.progress_entry(
                        "approval",
                        f"Waiting for your approval: {event.approval.summary}",
                        action_id=event.approval.action_id,
                    )
                )
            if event.spend is not None:
                spends.append(event.spend)
            if entries:
                async with tenant_session(tenant_id) as session:
                    await jobs.append_progress(session, job_id=job_id, entries=entries)
                    if await jobs.job_status(session, job_id=job_id) == "cancelled":
                        status, code = "cancelled", None
                        break
    except Exception:
        # Ids only (hard rule 6). The person sees the job as failed with a code; what it
        # already did stays in the activity log with its Undo.
        log.exception("copilot_job_failed", extra={"job_id": str(job_id)})
        status, code = "failed", "copilot_job_interrupted"
    finally:
        # THE METER, on every way out — `copilot/routes.py`'s rule: a completed model turn is
        # money spent whether or not the job finished.
        if spends:
            async with tenant_session(tenant_id) as session:
                for spent in spends:
                    await meter_assist(
                        session,
                        tenant_id=tenant_id,
                        ref=new_assist_ref(),
                        result=spent,
                        feature=ASSIST_FEATURE_COPILOT,
                        model=spent.model,
                    )
    if status == "cancelled":
        return "cancelled"
    await _finish(
        tenant_id,
        job_id,
        status=status,
        result="".join(answer).strip()
        or (
            "The job stopped before it finished. Anything it already did is in the activity log."
            if status == "failed"
            else "Done."
        ),
        code=code,
    )
    return status


__all__ = ["JOB_NAME", "run_copilot_job"]
