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
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability.service import (
    claim_outbox_batch,
    mark_outbox_failed,
    mark_outbox_published,
    record_outbox_metrics,
    sweep_idempotency,
)

log = get_logger(__name__)

# A completed call with no extraction after this long is a call the pipeline dropped
# (post-call SLO: lead visible in under 2 minutes, OPERATIONS §4).
STALL_AFTER_MINUTES = 10
# ...and one older than this is history, not an incident. Without an upper bound the
# alarm counts every call ever left unextracted — a number that only grows, fires on
# every tick, and tells an operator nothing about today. The cron runs twice an hour,
# so a real stall is still reported ~48 times before it ages out of the window.
STALL_WINDOW_HOURS = 24


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


async def _callable_tenants() -> list[UUID]:
    """Every tenant that can have call rows at all.

    `engine_agent_routes` is the SAME non-tenant-scoped bridge `ingest_engine_event`
    uses, and it exists precisely so a cross-tenant resolution needs no RLS exemption
    (hard rule 1, `db/registry.py`). A call row is only ever created for an agent the
    engine knows, the publish path upserts the route in the transaction that mints the
    ref, and routes are deactivated rather than deleted — so this set covers every
    tenant a stalled call can belong to, without walking organizations that have never
    taken one.

    Deliberately unfiltered on `active`: an agent unpublished after a call still leaves
    that call's extraction owed.
    """
    async with untenanted_session() as session:
        rows = (
            (await session.execute(text("SELECT DISTINCT tenant_id FROM engine_agent_routes")))
            .scalars()
            .all()
        )
    return [UUID(str(row)) for row in rows]


async def _count_stalled(session: AsyncSession) -> int:
    """Completed calls this tenant is still owed an extraction for.

    MUST run inside a `tenant_session`. Counts only — no phone numbers, no transcript
    text ever leaves this query (hard rule 6).
    """
    stalled = (
        await session.execute(
            text(
                "SELECT count(*) FROM calls c WHERE c.status = 'completed' "
                "AND c.ended_at < now() - make_interval(mins => :after) "
                "AND c.ended_at > now() - make_interval(hours => :window) "
                "AND NOT EXISTS (SELECT 1 FROM call_extractions e WHERE e.call_id = c.id)"
            ),
            {"after": STALL_AFTER_MINUTES, "window": STALL_WINDOW_HOURS},
        )
    ).scalar()
    return int(stalled or 0)


async def report_stalled_pipeline(ctx: dict[str, Any]) -> str:
    """The post-call SLO is 'lead visible under 2 minutes'. A completed call with no
    extraction after 10 minutes means the pipeline dropped it — alert rather than wait
    for a client to notice their leads stopped appearing.

    THE COUNT ONLY EXISTS INSIDE A TENANT SESSION. `calls` and `call_extractions` are
    FORCE-RLS'd, so the untenanted probe this replaced returned zero rows for every
    tenant on every tick: the alarm reported a healthy pipeline no matter how many
    leads were being dropped, and had never once been able to fire. The fix is the same
    one the reconciliation poller took — resolve the tenants, then ask each of them —
    and NOT an RLS exemption, which would trade a blind alarm for a blind spot in
    isolation.
    """
    total = 0
    tenants_affected = 0
    for tenant_id in await _callable_tenants():
        async with tenant_session(tenant_id) as session:
            stalled = await _count_stalled(session)
        if stalled:
            total += stalled
            tenants_affected += 1
    if total:
        alert(
            "WORKER_STALL",
            "postcall_pipeline_stalled",
            detail=f"{total} calls across {tenants_affected} tenants",
        )
    return f"stalled={total}"


__all__ = ["dispatch_outbox", "report_stalled_pipeline", "sweep_expired"]
