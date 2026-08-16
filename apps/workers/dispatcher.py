"""Outbox dispatcher + housekeeping crons (BACKEND-PATTERNS §4).

The dispatcher is the second half of the transactional outbox: a domain write commits
its side effect as a `pending` row, and this loop turns those rows into queued jobs.
The pairing is what makes "lead created but the owner was never told" impossible —
either both commit or neither does.

Claiming is a conditional UPDATE with `SKIP LOCKED`, so N dispatchers can run without
coordination: whoever wins the row publishes it, everyone else moves on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.reliability.service import (
    claim_outbox_batch,
    defer_outbox_claim,
    mark_outbox_failed,
    mark_outbox_published,
    record_outbox_metrics,
    sweep_idempotency,
)
from apps.workers.pipeline import EXTRACTION_OWED_SQL, PIPELINE_STALL_AFTER

log = get_logger(__name__)

# A completed call whose extraction is still owed after this long is a call the pipeline
# dropped (post-call SLO: lead visible in under 2 minutes, OPERATIONS §4).
#
# IMPORTED, NOT RESTATED. The same number decides when `pipeline._pipeline_settled` will
# let the reconciliation poller re-drive a call, and the two have to be one number: the
# alarm's whole meaning is "the poller is about to try, or has tried and failed", and a
# threshold that drifted would produce either an alarm for calls nothing repairs or a
# repair for calls nothing alarms about.
STALL_AFTER_MINUTES = int(PIPELINE_STALL_AFTER.total_seconds() // 60)
# ...and one older than this is history, not an incident. Without an upper bound the
# alarm counts every call ever left unextracted — a number that only grows, fires on
# every tick, and tells an operator nothing about today. The cron runs twice an hour,
# so a real stall is still reported ~48 times before it ages out of the window.
STALL_WINDOW_HOURS = 24


async def dispatch_outbox(ctx: dict[str, Any]) -> str:
    """Runs every few seconds. Publishes claimed rows; failures walk to the DLQ.

    TWO KINDS OF FAILURE, AND THEY MUST NOT BE TREATED ALIKE.

    A message whose payload the queue refuses is poison: it is charged an attempt, it
    stays `pending` while it has budget, and it walks to the DLQ. That is the loop's
    original behaviour and the reason the `except` exists at all — one bad payload must
    never stall every other tenant's notifications.

    A queue that is UNREACHABLE is not any message's fault. Every row in the batch fails
    identically, and charging each one an attempt at a ten-second tick dead-letters the
    whole outbox in under a minute — shorter than a Redis restart — leaving a
    step-up-confirmed operator replay as the only way back. So the tick stops on the
    first systemic failure, hands the untried remainder back with a backoff
    (`defer_outbox_claim`), and says so once.

    `RedisError, OSError` is the same pair `apps/api/core/queue.py`'s callers already
    treat as "the queue is down" (`tests/reliability_audit_test.py::
    test_enqueueing_against_a_dead_redis_fails_fast` pins it): redis-py raises its own
    `ConnectionError`/`TimeoutError` under `RedisError`, and a DNS or socket failure
    before that arrives as `OSError`.
    """
    published = 0
    async with untenanted_session() as session:
        batch = await claim_outbox_batch(session)
        for index, message in enumerate(batch):
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
            except (RedisError, OSError) as exc:
                # The queue itself. Nothing after this one would fare differently, so
                # trying them would spend 49 more attempts to learn what this one said.
                reason = f"{type(exc).__name__}: {exc}"
                deferred = await defer_outbox_claim(
                    session,
                    message_ids=[m.id for m in batch[index:]],
                    error=reason,
                )
                alert(
                    "OUTBOX_DISPATCH",
                    # A stable code so the alerter's per-fingerprint suppression folds a
                    # Redis outage into one notice rather than one per tick.
                    "outbox_queue_unreachable",
                    detail=f"{reason[:160]}; {deferred} message(s) deferred, not dead-lettered",
                )
                log.warning("outbox_queue_unreachable", extra={"deferred": deferred})
                break
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
            (
                await session.execute(
                    # ORDER BY for `retention._due_tenants`' reason: without it the order
                    # is planner-dependent, so which tenants a partially failing sweep
                    # reached changed from tick to tick.
                    text("SELECT DISTINCT tenant_id FROM engine_agent_routes ORDER BY tenant_id")
                )
            )
            .scalars()
            .all()
        )
    return [UUID(str(row)) for row in rows]


async def _count_stalled(session: AsyncSession) -> int:
    """Completed calls this tenant is still owed an extraction for.

    MUST run inside a `tenant_session`. Counts only — no phone numbers, no transcript
    text ever leaves this query (hard rule 6).

    **"OWED" IS THE PIPELINE'S OWN RULE, NOT "HAS NO ROW".** `EXTRACTION_OWED_SQL` is the
    SQL form of `_post_call_stages`'s `needs_extraction`, imported rather than restated.
    Without it this counted every completed call with no `call_extractions` row, and a
    silent call on an agent with no schema fields legitimately has none — the pipeline
    finishes it perfectly and writes nothing. Those calls sit inside the 24-hour window
    for the whole 24 hours, so the alarm fired twice an hour on healthy traffic, and an
    alarm that is always on is an alarm nobody reads when a real stall arrives. It
    matters more now than it did: the reconciliation poller repairs the calls this alarm
    used to be the only sign of, so what is left in it should be the residue that needs
    a human, not the calls that were never broken.
    """
    stalled = (
        await session.execute(
            text(
                "SELECT count(*) FROM calls c "
                # LEFT, so a call whose agent row was removed still counts on its
                # transcript alone rather than vanishing from the alarm.
                "LEFT JOIN agents a ON a.id = c.agent_id AND a.tenant_id = c.tenant_id "
                "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                "WHERE c.status = 'completed' "
                "AND c.ended_at < now() - make_interval(mins => :after) "
                "AND c.ended_at > now() - make_interval(hours => :window) "
                "AND NOT EXISTS (SELECT 1 FROM call_extractions e WHERE e.call_id = c.id) "
                f"AND {EXTRACTION_OWED_SQL}"
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

    ONE TENANT'S FAILURE IS NOT THE TICK'S (P6.2). This loop had no `try`, so a single
    tenant's database error ended the alarm's sweep for every tenant after it — and the
    result was not a red job but a QUIETER one: the alert fires on the total, so an
    aborted sweep produces a smaller number, or none, and reads exactly like a healthy
    fleet. An alarm that fails towards silence is worse than no alarm. Same shape as
    `retention.sweep_tenants` and `qa_sampling.draw_for_tenants`, and the unreached count
    rides the alert body so the number it quotes can be read for what it is.
    """
    total = 0
    tenants_affected = 0
    unreached = 0
    tenants = await _callable_tenants()
    for tenant_id in tenants:
        try:
            async with tenant_session(tenant_id) as session:
                stalled = await _count_stalled(session)
        except Exception:
            # The id, never the exception's payload: a psycopg error string can quote the
            # row that broke it, and these rows are calls (hard rule 6).
            log.exception("stall_probe_failed", extra={"tenant_id": str(tenant_id)})
            unreached += 1
            continue
        if stalled:
            total += stalled
            tenants_affected += 1
    if total or unreached:
        alert(
            "WORKER_STALL",
            "postcall_pipeline_stalled",
            detail=(
                f"{total} calls across {tenants_affected} tenants"
                + (
                    f"; {unreached} of {len(tenants)} tenant(s) could not be probed, so "
                    "the count is a floor rather than a total"
                    if unreached
                    else ""
                )
            ),
        )
    return f"stalled={total} unreached={unreached}"


#: How long a filed erasure may stay open before it is a machinery failure rather than a
#: queue that is busy.
#:
#: **DERIVED, and it is NOT a legal deadline** — `docs/SECURITY-COMPLIANCE.md` §4 states no
#: hour or day figure for DPDP §12, and inventing one here would put a commitment in a
#: constant that nobody made. What this number is: the outer bound of every mechanism on
#: the path. The request row and its outbox job are written in ONE transaction
#: (`compliance/deletion.request_erasure`), `dispatch_outbox` runs every 10 seconds, and
#: the worker's ladder is `WORKER_MAX_TRIES` attempts with a defer measured in tens of
#: seconds. An hour is therefore two orders of magnitude past any healthy path: a request
#: still open at it did not fail slowly, it never ran.
ERASURE_OVERDUE_AFTER = timedelta(hours=1)

#: Open erasure requests past the bound, for ONE tenant. Counts only — never the number,
#: never `subject_ref`, which is a hash of the number and is exactly what an alert body
#: must not carry (hard rule 6, and `deletion.py` argues it at length about the status
#: page).
_OVERDUE_ERASURES = """
SELECT count(*) FROM deletion_requests
WHERE completed_at IS NULL AND requested_at < :cutoff
"""

#: Every organization, and NOT `_callable_tenants()`.
#:
#: Reusing the stall probe's tenant list was the obvious move and it is wrong twice over.
#: That list is `SELECT DISTINCT tenant_id FROM engine_agent_routes` — tenants with a
#: PUBLISHED AGENT. A client can file a DPDP §12 request having never published one, and a
#: churned client's routes are torn down by `tenant_erasure` while their subjects' requests
#: stay open. So the tenants most likely to be holding a forgotten erasure are precisely
#: the ones that set excludes, and the alarm would have been blind exactly where it matters.
#:
#: NO `deleted_at IS NULL` either, which is where this departs from `qa_sampling._DIRECTORY`
#: rather than copying it: sampling a soft-deleted tenant's calls would be work for nobody,
#: but an erasure filed against a tenant that was later soft-deleted is the one with the
#: least chance of anybody noticing it by hand.
_ERASURE_DIRECTORY = "SELECT id FROM organizations ORDER BY id"


async def _all_tenants() -> list[UUID]:
    """Tenant ids for the erasure probe. `ORDER BY` for `_callable_tenants`' reason.

    `admin_session`, and NOT `untenanted_session` — which is what this was first written
    with, and it returned zero tenants on a real database every time. `organizations`
    carries its own FORCEd policy matching on `id`, so a session with no GUC set sees no
    clients at all: the alarm would have swept an empty fleet and reported a healthy one
    forever. Exactly the fail-closed-into-silence shape `report_stalled_pipeline` was
    fixed for, arrived at from the other direction.

    `app.admin` widens `USING` on `organizations` and NOTHING else (migration
    `b57e2f9c4a13`) — the per-tenant probe below still enters each client through a
    normal `tenant_session`, so hard rule 1 holds: this reads the directory, not the
    data. Same pairing `qa_sampling` and `campaign_dispatch` already use, followed rather
    than re-invented.
    """
    async with admin_session() as session:
        rows = (await session.execute(text(_ERASURE_DIRECTORY))).scalars().all()
    return [UUID(str(row)) for row in rows]


async def report_overdue_erasures(ctx: dict[str, Any]) -> str:
    """A DPDP erasure that was filed and never executed, surfaced (P6.5).

    **NOTHING WATCHED THIS.** `deletion_requests` rows sat `completed_at IS NULL` forever:
    no cron, no alert, no ops query. `report_stalled_pipeline` exists for calls, whose
    worst case is a lead a client did not see; the equivalent for the one workflow with a
    STATUTORY right behind it did not. A data principal exercised DPDP §12, the row was
    written, the job was lost to a deploy or a dead worker, and the only signal was a
    status page nobody was watching returning `pending` indefinitely.

    It cannot self-heal, and that is why it needs an alarm rather than a retry: the job is
    enqueued once, in the request's own transaction, and `execute_deletion_request` has no
    poller behind it the way the post-call pipeline has `reconcile_executions`. Once its
    ladder is spent the request is simply open forever.

    Same cross-tenant shape as `report_stalled_pipeline` — `deletion_requests` is
    FORCE-RLS'd, so an untenanted probe would return zero rows for every tenant and report
    a clean fleet no matter how many erasures were stuck. Same per-tenant isolation too,
    and for the same reason: an aborted sweep produces a smaller count and reads as
    healthy. Different tenant SOURCE, though — see `_ERASURE_DIRECTORY`.
    """
    del ctx
    cutoff = datetime.now(UTC) - ERASURE_OVERDUE_AFTER
    total = 0
    tenants_affected = 0
    unreached = 0
    tenants = await _all_tenants()
    for tenant_id in tenants:
        try:
            async with tenant_session(tenant_id) as session:
                overdue = int(
                    (await session.execute(text(_OVERDUE_ERASURES), {"cutoff": cutoff})).scalar()
                    or 0
                )
        except Exception:
            log.exception("overdue_erasure_probe_failed", extra={"tenant_id": str(tenant_id)})
            unreached += 1
            continue
        if overdue:
            total += overdue
            tenants_affected += 1
    if total or unreached:
        alert(
            "WORKER_STALL",
            "erasure_requests_overdue",
            detail=(
                f"{total} filed erasure request(s) across {tenants_affected} tenant(s) "
                f"have been open longer than {ERASURE_OVERDUE_AFTER}. The job is enqueued "
                "once with the request row and has no poller behind it, so these do not "
                "recover on their own — re-queue them"
                + (
                    f". {unreached} of {len(tenants)} tenant(s) could not be probed, so "
                    "the count is a floor"
                    if unreached
                    else ""
                )
            ),
        )
    return f"overdue_erasures={total} unreached={unreached}"


__all__ = [
    "dispatch_outbox",
    "report_overdue_erasures",
    "report_stalled_pipeline",
    "sweep_expired",
]
