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

from arq.jobs import SerializationError
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.processor_erasure import OVERDUE_AFTER_DAYS
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
from apps.workers.fleet_walk import FLEET_WALK_DEADLINE, WalkBudget
from apps.workers.pipeline import EXTRACTION_OWED_SQL, PIPELINE_STALL_AFTER, callable_tenants

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

#: What a POISONED MESSAGE can actually raise, and nothing else (D-182).
#:
#: This branch used to be `except Exception`, and its handler answers by issuing ANOTHER
#: statement on the same session (`mark_outbox_failed`). That is correct for a payload the
#: queue refuses and wrong for a database error — `mark_outbox_published` is inside the
#: same `try`, so a `DBAPIError` from it landed here, the session was already in a failed
#: transaction, psycopg refused the next statement with `InFailedSqlTransaction`, and the
#: whole tick aborted with every status write in the batch rolled back. The attempt counts
#: survive (the claim commits on its own connection), so up to fifty messages were charged
#: an attempt per pass until either the database recovered or
#: `_dead_letter_exhausted_claims` retired them as poison they never were. The distinction
#: the DLQ exists to record — bad message versus bad database — was the thing being lost.
#:
#: `SerializationError` is what arq raises when the job cannot be serialised
#: (`arq/jobs.py:serialize_job` wraps every serializer failure in it); `TypeError` and
#: `ValueError` are what a malformed payload raises before it gets that far. Anything
#: else — a `DBAPIError` above all — now escapes, where "the database is gone" is the
#: correct verdict: the tick fails red and the rows return to the claim once their
#: two-minute lease lapses, rather than being relabelled one message at a time.
POISON_PAYLOAD = (SerializationError, TypeError, ValueError)


async def dispatch_outbox(ctx: dict[str, Any]) -> str:
    """Runs every few seconds. Publishes claimed rows; failures walk to the DLQ.

    THREE KINDS OF FAILURE, AND THEY MUST NOT BE TREATED ALIKE.

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

    A DATABASE that has gone is neither, and it is the one this loop used to get wrong.
    The status writes go through the caller's session, so a `DBAPIError` from
    `mark_outbox_published` leaves that session in a failed transaction — and the poison
    handler's answer is to write ANOTHER statement on it. It escapes now (see
    `POISON_PAYLOAD`): the tick fails red — visibly, on the job — and the messages keep
    their committed attempt counts instead of being dead-lettered as poison they never
    were. Recovery is the NEXT TICK rather than an arq retry (this cron runs every ten
    seconds and takes `cron()`'s default `max_tries`): the claim's lease is two minutes,
    so the rows come back to the first tick after it lapses, with their counts intact.

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
            except POISON_PAYLOAD as exc:
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
    tenants = await callable_tenants()
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

#: How long the probe below may spend walking the fleet before it stops and SAYS SO.
#:
#: **THE REASONING NOW LIVES IN `fleet_walk.py`, WHICH IS WHERE THE BUDGET IS SPENT.**
#: This walk was the first to get one (D-369) and the argument turned out to be about the
#: SHAPE rather than about erasures: two more crons (`qa_sampling.draw_qa_samples`,
#: `kb_aggregation.send_agent_knowledge_digests`) walk the same directory the same way and
#: had the same unbounded pass. `WalkBudget` is that one mechanism; this constant stays
#: because the number is still this job's to choose, and it is the module's default.
#:
#: **IT WAS THE ONE FLEET-WIDE WALK IN THIS TREE WITH NO BOUND (D-369)**, and its cost
#: shape is the most expensive one there is: `deletion_requests` is FORCE-RLS'd, so every
#: organization costs a `tenant_session` — a connection checkout, a `set_config`, a
#: statement — and the directory is EVERY organization, not the published ones
#: (`_ERASURE_DIRECTORY` argues why, and is right to). `retention._due_tenants` records
#: the measurement for exactly this walk on the development database: ~16k organizations,
#: ~3 minutes of round-trips, which is why P6.2 took it OUT of the nightly retention
#: sweep. This job reinstated the same walk on an HOURLY schedule without anyone
#: reconciling the two, and `WorkerSettings.job_timeout` is 300 seconds.
#:
#: What happens past that timeout is the part that matters. arq cancels the job, and
#: `CancelledError` is one of the three exceptions it RETRIES — so the tick is re-run,
#: cancelled again, re-run, cancelled again, and the ladder ends at `job_try > max_tries`
#: with `install_arq_terminal_alerter`'s notice. That notice says the JOB failed; it
#: cannot say that the alarm the job carries has gone dark. And the alarm it carries is
#: the one watching a STATUTORY right (DPDP §12) that this docstring already says cannot
#: self-heal. So the failure mode is: the fleet grows past the walk's budget, and the
#: only mechanism that notices a forgotten erasure stops running — permanently, and
#: growing worse rather than better.
#:
#: A TIME budget, not a tenant COUNT — the opposite of `pipeline.OUTSTANDING_PROBE_BUDGET`
#: and for a stated reason. That one bounds VENDOR REQUESTS, whose cost per item is
#: roughly fixed, so a count is a faithful proxy. Here the per-item cost is a database
#: session under whatever load the box is carrying, and the thing that must not happen is
#: arq killing the job, which is a wall-clock condition. A count tuned for a healthy night
#: would be the wrong count on a slow one, which is when this matters most.
#:
#: 180s leaves two full minutes under `job_timeout` for the alert, the last tenant session
#: to close and the pool to settle — the same "strictly under, with headroom" reasoning
#: `job_completion_wait` uses against the compose grace.
ERASURE_PROBE_DEADLINE = FLEET_WALK_DEADLINE

#: The minute the overdue-erasure walk fires on.
#:
#: **IT WAS :25, WHICH IS `copilot_memory.DISTILL_MINUTE`** — so the two heaviest hourly
#: fan-outs in the tree started in the same minute, every hour, on the same worker fleet
#: and the same connection pool. That is not a style point: this walk opens one
#: `tenant_session` per ORGANIZATION and is already bounded by a wall clock
#: (`ERASURE_PROBE_DEADLINE`) it must finish inside, so a neighbour holding pooled
#: connections for the same minute spends this walk's budget on waiting and shortens the
#: fleet it reaches — an alarm on a statutory right going quiet because an unrelated
#: feature was scheduled on the same number. The distillation cron's own comment argued
#: at length that :25 was "clear of the poller, `report_stalled_pipeline` and
#: `reconcile_outstanding_calls`, so no two O(tenants) fan-outs share a minute", which was
#: true when it was written and false the moment this job was registered on the same
#: minute without anyone re-reading it.
#:
#: :55 is the free slot: :00 to :50 in tens is the execution poller, :05/:35 the stall alarm,
#: :07/:37 the engine drift sweep, :15/:45 the outstanding-call sweep, :23 the KB drift
#: sweep, :25 the distillation and :50 the violations sweep. Only `pull_fx_rate` also
#: fires at :55, and that is one HTTP GET for one number.
#:
#: `tests/job_registration_test.py::test_no_two_fleet_wide_walks_share_a_firing_minute` is
#: what keeps this true — a comment could not, as this minute's history shows.
ERASURE_PROBE_MINUTE = 55

#: Open erasure requests past the bound, for ONE tenant. Counts only — never the number,
#: never `subject_ref`, which is a hash of the number and is exactly what an alert body
#: must not carry (hard rule 6, and `deletion.py` argues it at length about the status
#: page).
_OVERDUE_ERASURES = """
SELECT count(*) FROM deletion_requests
WHERE completed_at IS NULL AND requested_at < :cutoff
"""

#: The erasure obligations that are OUTSIDE this system and still unanswered (D-433).
#:
#: A DIFFERENT FAILURE FROM THE QUERY ABOVE, which is why it is a second count and a
#: second alarm rather than a bigger number on the first. `_OVERDUE_ERASURES` finds an
#: erasure that never RAN — our job was lost, and the fix is to re-queue it. This finds an
#: erasure that ran perfectly and left a copy at a sub-processor that no API of ours can
#: delete (`docs/evidence/subprocessor-erasure-reach.md`), where the fix is a person
#: writing to the vendor. Re-queueing the first would do nothing for the second, and an
#: operator who read one message for both would do the wrong thing twice.
#:
#: `status IN ('open','requested')` counts both, and the alarm reports them apart: `open`
#: is OUR failure to ask, `requested` is the vendor's failure to answer, and only the
#: first is fixable from here.
#:
#: It rides the SAME bounded per-tenant walk rather than adding a second full-fleet
#: sweep — one way per problem, and the walk is already the expensive part.
_OVERDUE_PROCESSOR_TASKS = """
SELECT count(*) FILTER (WHERE status = 'open')      AS unasked,
       count(*) FILTER (WHERE status = 'requested') AS unanswered
FROM processor_erasure_tasks
WHERE status IN ('open', 'requested') AND opened_at < :cutoff
"""

#: Every organization, and NOT `callable_tenants()`.
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
    """Tenant ids for the erasure probe. `ORDER BY` for `callable_tenants`' reason.

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

    **AND IT IS BOUNDED NOW (D-369).** This walked every organization with no ceiling of
    any kind, on an hourly schedule, at one `tenant_session` per organization — the cost
    shape P6.2 removed from the nightly retention sweep after measuring it at ~3 minutes
    on ~16k organizations. `WorkerSettings.job_timeout` is 300s, and past it arq cancels
    and retries and cancels, so the alarm watching a statutory right would have gone dark
    on fleet growth alone, with only a generic job-failure notice to show for it.
    `ERASURE_PROBE_DEADLINE` argues the number and why it is a clock rather than a count.
    """
    del ctx
    cutoff = datetime.now(UTC) - ERASURE_OVERDUE_AFTER
    # A LONGER clock than the one above, on purpose. `ERASURE_OVERDUE_AFTER` measures a
    # job we run ourselves and should take seconds; this measures a vendor answering an
    # email, and 30 days is the period the DPA clause we are seeking demands of them
    # (`docs/evidence/subprocessor-erasure-reach.md` §6). One shared cutoff would either
    # page on day one of a reasonable vendor turnaround or let a lost job sit for a month.
    processor_cutoff = datetime.now(UTC) - timedelta(days=OVERDUE_AFTER_DAYS)
    total = 0
    tenants_affected = 0
    unreached = 0
    probed = 0
    unasked = 0
    unanswered = 0
    processor_tenants = 0
    # The wall clock, not a counter — see `fleet_walk.WalkBudget`.
    budget = WalkBudget(ERASURE_PROBE_DEADLINE)
    tenants = await _all_tenants()
    for tenant_id in tenants:
        if budget.spent():
            break
        probed += 1
        try:
            async with tenant_session(tenant_id) as session:
                overdue = int(
                    (await session.execute(text(_OVERDUE_ERASURES), {"cutoff": cutoff})).scalar()
                    or 0
                )
                # In the SAME session as the probe above: it is the same tenant, the
                # same deadline budget and the same RLS scope, so a second walk would
                # buy nothing but another 16k sessions.
                stuck = (
                    await session.execute(
                        text(_OVERDUE_PROCESSOR_TASKS), {"cutoff": processor_cutoff}
                    )
                ).one()
        except Exception:
            log.exception("overdue_erasure_probe_failed", extra={"tenant_id": str(tenant_id)})
            unreached += 1
            continue
        if overdue:
            total += overdue
            tenants_affected += 1
        if stuck.unasked or stuck.unanswered:
            unasked += int(stuck.unasked or 0)
            unanswered += int(stuck.unanswered or 0)
            processor_tenants += 1
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
    if unasked or unanswered:
        alert(
            "WORKER_STALL",
            "processor_erasure_overdue",
            detail=(
                f"{unasked + unanswered} vendor-side erasure obligation(s) across "
                f"{processor_tenants} tenant(s) have been open longer than "
                f"{OVERDUE_AFTER_DAYS} days: {unasked} never sent to the processor, "
                f"{unanswered} sent and unanswered. These are NOT stuck jobs and "
                "re-queueing does nothing — the erasure ran, and a copy the vendor "
                "publishes no API to delete is still there. "
                "runbooks/processor-erasure.md"
            ),
        )
    if budget.exhausted:
        # A SEPARATE ALERT, and the reason is that it says something the count above
        # cannot: `overdue_erasures=0` from a walk that only reached part of the fleet is
        # not "no erasure is stuck", it is "no erasure is stuck among the tenants we got
        # to". Silent truncation on THIS alarm is worse than on any other in the tree,
        # because the thing it stops watching is a statutory right with no poller behind
        # it. The starved tail is stable — `_ERASURE_DIRECTORY` orders by tenant id — so
        # the same tenants are skipped every hour until this is acted on, which is the
        # same deliberate-and-therefore-announced trade `pipeline.
        # reconcile_outstanding_calls` makes.
        alert(
            "WORKER_DELIVERY",
            "erasure_probe_deadline_exhausted",
            detail=(
                f"the overdue-erasure walk reached {probed} of {len(tenants)} tenant(s) "
                f"in {ERASURE_PROBE_DEADLINE} and stopped there; the rest were not "
                "probed, so a filed erasure sitting in one of them is currently watched "
                "by nothing. The walk costs one session per organization and the fleet "
                "has outgrown one tick — this needs a cross-tenant probe, not a longer "
                "deadline (the next stop after this one is arq's job timeout)"
            ),
        )
    return f"overdue_erasures={total} probed={probed} unreached={unreached}"


__all__ = [
    "ERASURE_PROBE_DEADLINE",
    "ERASURE_PROBE_MINUTE",
    "_OVERDUE_PROCESSOR_TASKS",
    "dispatch_outbox",
    "report_overdue_erasures",
    "report_stalled_pipeline",
    "sweep_expired",
]
