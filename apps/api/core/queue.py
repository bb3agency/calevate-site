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
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

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
    """Returns the job id, or None when ARQ deduped it against an in-flight job."""
    queue = await get_queue()
    result = await queue.enqueue_job(job, *args, _job_id=job_id, **kwargs)
    if result is None:
        log.info("job_deduped", extra={"job": job, "job_id": job_id})
        return None
    return str(result.job_id)


__all__ = [
    "close_queue",
    "enqueue",
    "enqueue_pool_settings",
    "get_queue",
    "job_id_for",
    "redis_settings",
]
