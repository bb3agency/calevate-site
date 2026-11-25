"""Puts campaigns and lines live again after a change committed away from a route that could
do it itself, or after a page's own Save found the engine not answering: `put_job_notes_live`,
from the outbox (`campaigns/notes_live.queue_put_live`).

A refusal leaves that job on its previous settings until its next put-live, as the Lead
details screen's applies do (`notes_live.put_live_each`); it is logged there and not retried,
because a retry would meet the same gate. The exception is the engine not answering: the
owner was told the change goes live by itself, so those jobs are retried on a ladder, and a
ladder that runs out while the outage is still on starts a fresh one through the outbox
rather than dropping the change (`live_apply.apply_live_agent` waits out a maintenance window
the same way).
"""

from __future__ import annotations

from typing import Any, Final

from arq import Retry
from calevate_shared.backoff import ladder_delay_s

from apps.api.campaigns import notes_live
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.db.session import tenant_session
from apps.api.engine.answering import still_not_answering

log = get_logger(__name__)

#: The ARQ name, spelled in this file for `scripts/check_job_wiring.py`.
JOB_NAME: Final = "put_job_notes_live"

#: Seconds before each retry while the engine is not answering: a blip, then a longer outage.
RETRY_AFTER_S: Final = (30, 120, 600)


async def put_job_notes_live(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id, jobs = notes_live.queued_jobs(payload)
    always = notes_live.queued_always(payload)
    refused, waiting = await notes_live.put_live_sorted(tenant_id, jobs, always=always)
    log.info(
        "job_notes_put_live",
        extra={
            "tenant_id": str(tenant_id),
            "jobs": len(jobs),
            "refused": refused,
            "waiting": len(waiting),
        },
    )
    if not waiting:
        return f"refused:{refused}" if refused else "done"
    attempt = job_try(ctx)
    if attempt < WORKER_MAX_TRIES:
        # Putting a job live twice changes nothing, so the jobs that did go through are
        # safe to repeat with the ones that waited.
        raise Retry(defer=ladder_delay_s(RETRY_AFTER_S, attempt))
    if await still_not_answering():
        async with tenant_session(tenant_id) as session:
            await notes_live.queue_put_live(
                session, tenant_id=tenant_id, jobs=waiting, always=always
            )
        return f"waiting:{len(waiting)}"
    # The engine answers other requests but still not this put-live: an owner was told it
    # would go live by itself, so somebody has to look.
    alert(
        "WORKER_TERMINAL",
        "job_put_live_gave_up",
        detail=(
            f"{len(waiting)} saved line or campaign change(s) could not be put live: the phone "
            "service did not answer these requests although it is answering others. They "
            "keep their previous settings until the owner saves again."
        ),
        tenant_id=str(tenant_id),
    )
    return f"gave_up:{len(waiting)}"


__all__ = ["JOB_NAME", "RETRY_AFTER_S", "put_job_notes_live"]
