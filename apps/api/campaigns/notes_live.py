"""Put a job's changed "What it notes" on its calls, for writes made away from its own page.

The campaign and line pages' Save puts the job live itself (`campaigns/workspace_routes`,
`inbound/routes`). The Lead details screen's account-wide applies and an accepted suggestion
change a job's list from elsewhere, so they call this after their transaction committed: a
campaign holding its own engine agent while it runs or is paused, and a live line, are put
live again so their next call asks for the new details. Any other job reads its list at its
next Start, test call or Put it live, exactly as after its own Save.

A write that cannot act after its own commit (Pip's confirmed or approved changes, which
commit with their audit row when the route returns) queues the same step through the outbox
instead (`queue_put_live`), so it runs only if the change committed.
"""

from __future__ import annotations

from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import CAMPAIGN_HOLDING_STATUSES
from apps.api.campaigns.engine_agent import put_campaign_live
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.inbound.publish import put_line_live
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

JobKind = Literal["campaign", "line"]

#: The worker job that runs `put_live_each` for a queued list (`workers/job_notes_live`).
PUT_LIVE_JOB: Final = "put_job_notes_live"


async def holds_calls(tenant_id: UUID, kind: JobKind, job_id: UUID) -> bool:
    """Does the job have an engine agent its calls ring now, which a saved list must reach?"""
    async with tenant_session(tenant_id) as session:
        if kind == "line":
            return (await lines.read_line(session, job_id)).live
        held = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref IS NOT NULL AND status = ANY(:holding) "
                    "FROM campaigns WHERE id = :c"
                ),
                {"c": job_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
            )
        ).scalar()
    return bool(held)


async def put_live(tenant_id: UUID, kind: JobKind, job_id: UUID) -> None:
    """Put the job live again when it holds calls. Raises what the publish refused."""
    if not await holds_calls(tenant_id, kind, job_id):
        return
    if kind == "campaign":
        await put_campaign_live(tenant_id=tenant_id, campaign_id=job_id, require_holding=True)
    else:
        await put_line_live(tenant_id=tenant_id, line_id=job_id)


#: How a kept edit is put live again: `save` is an unchanged Save of the same list or script
#: (every such save puts a job that holds calls live again); `put_live` is the line page's
#: header button.
Retry = Literal["save", "put_live"]


def kept_not_live(
    exc: ProblemError, *, retry: Retry = "save", operator: bool = False
) -> ProblemError:
    """Retitle a put-live refusal that followed a committed edit, so the reader learns the
    edit is kept and presses the retry their screen offers rather than typing it again. The
    web screens match on the title (`SAVED_NOT_ON_CALLS_TITLE`, `SAVED_NOT_LIVE_TITLE`)."""
    if retry == "put_live":
        exc.title = "Saved, but not live yet"
        lead = "Press Put it live to finish; your change is kept."
    else:
        exc.title = "Saved, but not on its calls yet"
        lead = (
            "The change is kept. Save again to put it on the calls."
            if operator
            else "Your change is kept. Save again to put it on the calls."
        )
    exc.remediation = f"{lead} {exc.remediation or ''}".strip()
    return exc


async def put_live_after_save(
    tenant_id: UUID, kind: JobKind, job_id: UUID, *, operator: bool = False
) -> None:
    """`put_live` after an edit to the job's list committed. A refusal asks for Save again,
    which What it notes offers on the job's page and on Lead details alike."""
    try:
        await put_live(tenant_id, kind, job_id)
    except ProblemError as exc:
        kept_not_live(exc, operator=operator)
        raise


async def put_live_each(tenant_id: UUID, jobs: list[tuple[JobKind, UUID]]) -> int:
    """`put_live` for several jobs after one apply. A refusal leaves that job on its previous
    list until its next put-live and does not stop the others; returns how many were refused.
    Logged by id and code only."""
    refused = 0
    for kind, job_id in jobs:
        try:
            await put_live(tenant_id, kind, job_id)
        except ProblemError as exc:
            refused += 1
            log.warning(
                "job_notes_put_live_refused",
                extra={"job_kind": kind, "job_id": str(job_id), "reason": exc.code},
            )
    return refused


async def queue_put_live(
    session: AsyncSession, *, tenant_id: UUID, jobs: list[tuple[JobKind, UUID]]
) -> None:
    """`put_live_each` for `jobs`, once `session`'s transaction commits. Nothing is queued
    for an empty list."""
    if not jobs:
        return
    payload: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "jobs": [{"kind": kind, "job_id": str(job_id)} for kind, job_id in jobs],
    }
    await enqueue_outbox(session, job=PUT_LIVE_JOB, payload=payload)


def queued_jobs(payload: dict[str, Any]) -> tuple[UUID, list[tuple[JobKind, UUID]]]:
    """`queue_put_live`'s payload read back."""
    jobs: list[tuple[JobKind, UUID]] = [
        ("campaign" if job["kind"] == "campaign" else "line", UUID(str(job["job_id"])))
        for job in payload["jobs"]
    ]
    return UUID(str(payload["tenant_id"])), jobs


__all__ = [
    "PUT_LIVE_JOB",
    "JobKind",
    "holds_calls",
    "kept_not_live",
    "put_live",
    "put_live_after_save",
    "put_live_each",
    "queue_put_live",
    "queued_jobs",
]
