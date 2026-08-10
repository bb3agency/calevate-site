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

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_queue() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
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


__all__ = ["close_queue", "enqueue", "get_queue", "job_id_for", "redis_settings"]
