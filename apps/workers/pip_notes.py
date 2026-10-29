"""Pip's detectors, once an hour in the IST working day (D-936, `apps/api/copilot/notes.py`).

`sweep_pip_notes` is the cron: it reads the client directory once and queues one
`detect_pip_notes` per open account on the BULK queue, keyed by account and hour, so a
retried tick queues nothing twice and the detectors never hold a slot the post-call
pipeline is waiting for. The walk resumes from where the last pass stopped
(`fleet_walk.resumed_walk`) and stops itself inside the time budget.

`detect_pip_notes` runs one account's detectors in that account's own session (RLS). Its
writes land in `copilot_notes`, whose live topic (`assistant`) tells an open panel to read
again. Nothing is mailed, so no quiet-hours rule binds it; the cron's hours keep notes to the
working day anyway, when somebody can act on them.

Log lines carry the tenant id and counts only (hard rule 6).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.plans import IST
from apps.api.copilot.notes import run_detectors
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.workers.fleet_walk import WalkBudget, resumed_walk

log = get_logger(__name__)

JOB_NAME: Final = "detect_pip_notes"

#: IST hours the sweep fires in (`apps/workers/settings.py`): 08:00 to 21:00.
SWEEP_HOURS: Final = frozenset(range(8, 22))
SWEEP_MINUTE: Final = 56

_DIRECTORY: Final = (
    "SELECT id FROM organizations WHERE deleted_at IS NULL "
    "AND status IN ('onboarding', 'active') ORDER BY id"
)


async def detect_pip_notes(ctx: dict[str, Any], tenant_id: str) -> str:
    del ctx
    tid = UUID(str(tenant_id))
    async with tenant_session(tid) as session:
        counts = await run_detectors(session, tenant_id=tid)
    log.info("pip_notes_detected", extra={"tenant_id": str(tid), **counts})
    return json.dumps(counts)


async def sweep_pip_notes(ctx: dict[str, Any]) -> str:
    del ctx
    if not get_settings().pip_notes_enabled:
        return json.dumps({"skipped": "disabled"})
    hour = datetime.now(UTC).astimezone(IST).strftime("%Y%m%d%H")
    async with admin_session() as directory:
        tenant_ids = [UUID(str(r[0])) for r in (await directory.execute(text(_DIRECTORY))).all()]
    budget = WalkBudget()
    counts = {"queued": 0, "failed": 0}
    async for tenant_id in resumed_walk("pip_notes", tenant_ids, budget):
        try:
            await enqueue(
                JOB_NAME, str(tenant_id), job_id=job_id_for(JOB_NAME, str(tenant_id), hour)
            )
            counts["queued"] += 1
        except Exception as exc:
            counts["failed"] += 1
            log.warning(
                "pip_notes_sweep_tenant_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
    unreached = len(tenant_ids) - counts["queued"] - counts["failed"]
    log.info("pip_notes_sweep", extra={**counts, "unreached": unreached})
    if unreached:
        alert(
            "WORKER_DELIVERY",
            "pip_notes_sweep_truncated",
            detail=(
                f"the hourly Pip notes pass queued {len(tenant_ids) - unreached} of "
                f"{len(tenant_ids)} client(s) inside its time budget; the rest are reached "
                "next hour"
            ),
        )
    return json.dumps(counts)


__all__ = ["JOB_NAME", "SWEEP_HOURS", "SWEEP_MINUTE", "detect_pip_notes", "sweep_pip_notes"]
