"""Outbox dispatcher + housekeeping crons (BACKEND-PATTERNS §4).

The dispatcher is the second half of the transactional outbox: a domain write commits
its side effect as a `pending` row, and this loop turns those rows into queued jobs.
The pairing is what makes "lead created but the owner was never told" impossible —
either both commit or neither does.

Claiming is a conditional UPDATE with `SKIP LOCKED`, so N dispatchers can run without
coordination: whoever wins the row publishes it, everyone else moves on.
"""

from __future__ import annotations

from typing import Any

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import (
    claim_outbox_batch,
    mark_outbox_failed,
    mark_outbox_published,
    record_outbox_metrics,
    sweep_idempotency,
)

log = get_logger(__name__)


async def dispatch_outbox(ctx: dict[str, Any]) -> str:
    """Runs every few seconds. Publishes claimed rows; failures walk to the DLQ."""
    published = 0
    async with untenanted_session() as session:
        batch = await claim_outbox_batch(session)
        for message in batch:
            try:
                job_id = await enqueue(
                    message.job,
                    message.payload,
                    job_id=job_id_for(message.job, str(message.id)),
                )
                await mark_outbox_published(
                    session, message_id=message.id, job_id=job_id or "deduped"
                )
                published += 1
            except Exception as exc:
                # Never let one poisoned message stop the batch — that is how a single
                # bad payload stalls every tenant's notifications.
                await mark_outbox_failed(
                    session,
                    message_id=message.id,
                    error=f"{type(exc).__name__}: {exc}",
                    attempt_count=message.attempt_count,
                )
                log.warning("outbox_publish_failed", extra={"job": message.job})
        await record_outbox_metrics(session)
    return f"published={published}"


async def sweep_expired(ctx: dict[str, Any]) -> str:
    """Idempotency records are a 24h replay window, not history — sweep them so the
    table stays small enough for its unique index to matter."""
    async with untenanted_session() as session:
        removed = await sweep_idempotency(session)
    return f"idempotency_swept={removed}"


async def report_stalled_pipeline(ctx: dict[str, Any]) -> str:
    """The post-call SLO is 'lead visible under 2 minutes'. A completed call with no
    extraction after 10 minutes means the pipeline dropped it — alert rather than wait
    for a client to notice their leads stopped appearing."""
    async with untenanted_session() as session:
        # Deliberately NOT tenant-scoped: this is an operator view over infra health.
        # It reads counts only — no phone numbers, no transcript text (hard rule 6).
        from sqlalchemy import text as sql

        stalled = (
            await session.execute(
                sql(
                    "SELECT count(*) FROM calls c WHERE c.status = 'completed' "
                    "AND c.ended_at < now() - interval '10 minutes' "
                    "AND NOT EXISTS (SELECT 1 FROM call_extractions e WHERE e.call_id = c.id)"
                )
            )
        ).scalar()
    count = int(stalled or 0)
    if count:
        alert("WORKER_STALL", "postcall_pipeline_stalled", detail=f"{count} calls")
    return f"stalled={count}"


__all__ = ["dispatch_outbox", "report_stalled_pipeline", "sweep_expired"]
