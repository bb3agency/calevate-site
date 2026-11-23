"""Puts campaigns and lines live again after a change to what they note committed away from a
route that could do it itself: `put_job_notes_live`, from the outbox
(`campaigns/notes_live.queue_put_live`).

A refusal leaves that job on its previous list until its next put-live, as the Lead details
screen's applies do (`notes_live.put_live_each`); it is logged there and not retried, because
a retry would meet the same gate.
"""

from __future__ import annotations

from typing import Any, Final

from apps.api.campaigns import notes_live
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: The ARQ name, spelled in this file for `scripts/check_job_wiring.py`.
JOB_NAME: Final = "put_job_notes_live"


async def put_job_notes_live(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id, jobs = notes_live.queued_jobs(payload)
    refused = await notes_live.put_live_each(tenant_id, jobs)
    log.info(
        "job_notes_put_live",
        extra={"tenant_id": str(tenant_id), "jobs": len(jobs), "refused": refused},
    )
    return f"refused:{refused}" if refused else "done"


__all__ = ["JOB_NAME", "put_job_notes_live"]
