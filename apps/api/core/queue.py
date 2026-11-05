"""ARQ enqueue side, shared by the API (outbox dispatcher) and voice-runtime.

Redis + ARQ is the decided queue (TRD §2); Temporal only if campaign retry semantics
outgrow it, not before. This module owns the pool and the ONE naming convention that
makes jobs idempotent at the queue layer:

    job_id = "<job>:<natural key>"

ARQ refuses to enqueue a job whose id is already queued or recently completed, so a
duplicate webhook and a poller that rediscovers the same call collapse into one job
before a worker ever sees them. That is the cheapest layer of the "at-least-once
delivery + idempotent consumers" story (BACKEND-PATTERNS §4) — the DB-level claims
behind it still have to hold, because the ARQ dedupe window is finite.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Collection, Mapping
from typing import Any, Final

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.constants import default_queue_name
from arq.jobs import Job

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

_pool: ArqRedis | None = None
# One in-flight pool build per process. Without it a cold start under a burst — which
# is exactly how the voice-runtime meets a wave of webhooks — has every concurrent
# request build its own pool, and all but the last are leaked with their connections
# open and no reference left for close_queue() to shut.
_pool_lock = asyncio.Lock()


# The ONE retry budget every job and every 'is this the last try?' check reads.
# It lived only in WorkerSettings.max_tries while the outbound delivery worker
# compared against its own MAX_ATTEMPTS=5 — so ARQ stopped retrying at 3 and the
# 'delivery exhausted' alert could never fire. A client's broken integration went
# silently stale, which is exactly the failure the alert exists to catch.
WORKER_MAX_TRIES = 3


def job_try(ctx: Mapping[str, Any]) -> int:
    """Which attempt of this job arq is running, counting from 1.

    arq sets `ctx["job_try"]`; a job called directly (a test, a sweep that awaits another
    job's function, `healer.reconcile_engine_webhooks({"job_try": 1})`) may pass no key or
    None, and both read as the first attempt so a retry ladder never indexes from 0.
    """
    return int(ctx.get("job_try") or 1)


#: How long arq lets one job run before cancelling it. Both worker classes use it, and
#: `/healthz/ready` derives the bulk queue's staleness threshold from it.
WORKER_JOB_TIMEOUT_S: Final = 300

#: The two arq queues (D-929). arq routes a job by the sorted set it is added to
#: (`ArqRedis.enqueue_job(_queue_name=...)`) and a worker reads exactly one
#: (`Worker(queue_name=...)`), so a separate queue IS a separate worker process:
#: `apps.workers.settings.WorkerSettings` reads the default one, `BulkWorkerSettings` the
#: bulk one (`workers-bulk` in `compose.prod.yml`).
DEFAULT_QUEUE: Final = default_queue_name
BULK_QUEUE: Final = "arq:bulk"
QUEUES: Final = (DEFAULT_QUEUE, BULK_QUEUE)

#: Jobs that run on the bulk worker, so they never hold a slot the post-call pipeline,
#: a notification, an in-call follow-up, the outbox or a cron is waiting for.
#:
#: The rule for membership: the job does slow work (reads a document, OCRs pages, uploads
#: to the voice platform, makes several model calls, or walks every agent of an account)
#: AND nobody is watching a screen for its answer within seconds. Single-call drafts a
#: person has just asked for (lead fields, outcomes, a script proposal, a teach answer),
#: "meet your agent", translations, payments, DNC and erasure pushes stay on the default
#: queue: two bulk slots behind a long OCR would make a person wait minutes for them.
#:
#: Names, not functions: producers in api and voice-runtime may not import `apps.workers`.
#: `apps.workers.settings` refuses to import if a name here is not a registered job.
BULK_JOBS: Final[frozenset[str]] = frozenset(
    {
        # Document reads: text extraction, OCR, then the vendor upload.
        "ingest_kb_source",
        "read_kb_upload",
        # A model call per agent of the client after a document goes live.
        "suggest_scripts_from_document",
        # Simulated test conversations and the improvement pass: many model turns each.
        "run_agent_test_conversations",
        "improve_agent_test_run",
        "run_agent_test_cases",
        # An account's AI-written examples, from a trigger or the daily sweep.
        "generate_business_copy",
        # Walks over every agent of an account, republishing each one it changes.
        "refresh_field_reason",
        "strip_retired_example_lines",
        "recheck_call_quality",
        "recompute_hot_facts",
        # A Pip background job: up to `copilot.service.job_limits` (240 s) of tool loop.
        "run_copilot_job",
        # Pip's detectors for one account (D-936): several reads per account, nobody waiting.
        "detect_pip_notes",
    }
)


def queue_for(job: str) -> str:
    """The arq queue `job` is enqueued on. The one place routing is decided."""
    return BULK_QUEUE if job in BULK_JOBS else DEFAULT_QUEUE


#: Where each live bulk worker process says which job names it runs. A producer on one
#: release cannot know what the bulk worker on `arq:bulk` runs: during a deploy the two are
#: different releases, and arq fails a job whose name its reader lacks at once, with no
#: retry. So the outbox dispatcher publishes a bulk job only while EVERY live bulk worker
#: lists it (`bulk_jobs_served`). One key per process, refreshed well inside its TTL, so a
#: worker that dies without a shutdown stops counting within `BULK_CONSUMER_TTL_S`.
BULK_CONSUMER_KEY_PREFIX: Final = "calevate:consumers:bulk:"
BULK_CONSUMER_TTL_S: Final = 60
BULK_CONSUMER_REFRESH_S: Final = 20


async def advertise_bulk_consumer(redis: Any, instance: str, jobs: Collection[str]) -> None:
    """Say, for `BULK_CONSUMER_TTL_S`, that this bulk worker process runs `jobs`."""
    await redis.set(
        BULK_CONSUMER_KEY_PREFIX + instance, json.dumps(sorted(jobs)), ex=BULK_CONSUMER_TTL_S
    )


async def withdraw_bulk_consumer(redis: Any, instance: str) -> None:
    await redis.delete(BULK_CONSUMER_KEY_PREFIX + instance)


async def bulk_jobs_served(redis: Any) -> frozenset[str]:
    """The bulk job names every live bulk worker runs; empty when none is live.

    The intersection, not the union: arq hands a queued job to whichever reader polls
    first, so a name one live worker lacks can still be failed by that one.
    """
    keys = [key async for key in redis.scan_iter(match=BULK_CONSUMER_KEY_PREFIX + "*")]
    if not keys:
        return frozenset()
    served: frozenset[str] | None = None
    for raw in await redis.mget(keys):
        if raw is None:  # expired between the scan and the read
            continue
        names = frozenset(str(name) for name in json.loads(raw))
        served = names if served is None else served & names
    return served or frozenset()


async def earlier_run_failed(job: str, job_id: str) -> bool:
    """Whether arq holds a FAILED result for `job_id`, which is why it refused the id.

    `enqueue` returns None both for a run still queued or running (harmless) and for one
    whose failure arq keeps for `keep_result` (the message's work never happened). Only
    the second is a lost side effect.
    """
    result = await Job(job_id, await get_queue(), _queue_name=queue_for(job)).result_info()
    return result is not None and not result.success


def redis_settings() -> RedisSettings:
    """Worker-side settings: arq's defaults (5 connect retries, 1s apart) are exactly
    right for a worker booting alongside Redis in a compose/deploy race."""
    return RedisSettings.from_dsn(get_settings().redis_url)


def enqueue_pool_settings() -> RedisSettings:
    """The same Redis, a different patience budget.

    `enqueue` runs inside request handlers — including the voice-runtime receiver whose
    ENTIRE ack budget is 500ms (hard rule 3, alerted on when breached). arq's default
    connect policy waits ~5 seconds before admitting Redis is unreachable, so a Redis
    outage would turn every webhook into a 5-second hang holding a connection and a
    worker slot, and then a 500 — ten times the budget spent learning something the
    first refused connection already said. Fail fast here; the poller (D-31) and the
    outbox retry are what actually recover the work.
    """
    return dataclasses.replace(redis_settings(), conn_retries=1, conn_retry_delay=0, conn_timeout=2)


async def get_queue() -> ArqRedis:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:  # another waiter built it while we queued
                _pool = await create_pool(enqueue_pool_settings())
    return _pool


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def job_id_for(job: str, *key_parts: str) -> str:
    return ":".join([job, *[p for p in key_parts if p]])


async def enqueue(job: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> str | None:
    """Returns the job id, or None when ARQ deduped it against an in-flight job.

    The dedupe holds across both queues: arq checks the job and result keys, which are
    shared, not the queue's sorted set.
    """
    queue = await get_queue()
    result = await queue.enqueue_job(
        job, *args, _job_id=job_id, _queue_name=queue_for(job), **kwargs
    )
    if result is None:
        log.info("job_deduped", extra={"job": job, "job_id": job_id})
        return None
    return str(result.job_id)


__all__ = [
    "BULK_CONSUMER_KEY_PREFIX",
    "BULK_CONSUMER_REFRESH_S",
    "BULK_CONSUMER_TTL_S",
    "BULK_JOBS",
    "BULK_QUEUE",
    "DEFAULT_QUEUE",
    "QUEUES",
    "WORKER_JOB_TIMEOUT_S",
    "advertise_bulk_consumer",
    "bulk_jobs_served",
    "close_queue",
    "earlier_run_failed",
    "enqueue",
    "enqueue_pool_settings",
    "get_queue",
    "job_id_for",
    "job_try",
    "queue_for",
    "redis_settings",
    "withdraw_bulk_consumer",
]
