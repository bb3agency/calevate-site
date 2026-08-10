"""Health & readiness — three endpoints, ONE word for the dashboard.

BACKEND-PATTERNS §6:
- `/healthz/live`   — process is up. Touches NO dependency (a DB blip must not get
                      the container killed by the orchestrator).
- `/healthz`        — DB SELECT 1 + Redis PING. 503 problem+json when degraded.
- `/healthz/ready`  — adds queue depth + oldest-waiting age (stale-worker detection)
                      and `runtime_config_missing_keys`. This is the GO-LIVE GATE that
                      tolerant worker boot defers to.

`degradation_mode` is priority-ordered so a dashboard shows one word:
db_down > redis_down > queue_stale > config_missing > none.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Response
from sqlalchemy import text

from apps.api.core.errors import PROBLEM_CONTENT_TYPE
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings, runtime_config_missing_keys
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

DegradationMode = Literal["db_down", "redis_down", "queue_stale", "config_missing", "none"]

# A job waiting longer than this means no worker is draining the queue.
QUEUE_STALE_AFTER_S = 120.0
ARQ_QUEUE_KEY = "arq:queue"


async def _check_db() -> bool:
    try:
        async with untenanted_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        log.warning("health_db_unavailable")
        return False


async def _check_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        log.warning("health_redis_unavailable")
        return False


async def _queue_stats() -> tuple[int, float | None]:
    """(depth, oldest_waiting_seconds). ARQ scores its queue zset with the run-at
    timestamp in ms, so the minimum score is the oldest ready job."""
    redis = get_redis()
    depth = int(await redis.zcard(ARQ_QUEUE_KEY))
    if depth == 0:
        return 0, None
    oldest = await redis.zrange(ARQ_QUEUE_KEY, 0, 0, withscores=True)
    if not oldest:
        return depth, None
    score_ms = float(oldest[0][1])
    return depth, max(0.0, time.time() - score_ms / 1000.0)


def build_health_router(service: str) -> APIRouter:
    """Same three endpoints for api, voice-runtime and (via a tiny shim) workers."""
    router = APIRouter(tags=["health"])

    @router.get("/healthz/live", summary="Liveness — touches no dependency")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": service}

    @router.get("/healthz", summary="Health — DB + Redis")
    async def health(response: Response) -> dict[str, Any]:
        db_ok = await _check_db()
        redis_ok = await _check_redis()
        mode: DegradationMode = "db_down" if not db_ok else "redis_down" if not redis_ok else "none"
        body: dict[str, Any] = {
            "status": "ok" if mode == "none" else "degraded",
            "service": service,
            "degradation_mode": mode,
            "checks": {"db": db_ok, "redis": redis_ok},
        }
        if mode != "none":
            response.status_code = 503
            response.media_type = PROBLEM_CONTENT_TYPE
        return body

    @router.get("/healthz/ready", summary="Readiness — the go-live gate")
    async def ready(response: Response) -> dict[str, Any]:
        db_ok = await _check_db()
        redis_ok = await _check_redis()
        depth = 0
        oldest: float | None = None
        if redis_ok:
            try:
                depth, oldest = await _queue_stats()
            except Exception:
                redis_ok = False
        missing = runtime_config_missing_keys(get_settings())
        queue_stale = oldest is not None and oldest > QUEUE_STALE_AFTER_S

        mode: DegradationMode = (
            "db_down"
            if not db_ok
            else "redis_down"
            if not redis_ok
            else "queue_stale"
            if queue_stale
            else "config_missing"
            if missing
            else "none"
        )
        body: dict[str, Any] = {
            "status": "ready" if mode == "none" else "not_ready",
            "service": service,
            "degradation_mode": mode,
            "checks": {"db": db_ok, "redis": redis_ok},
            "queue": {"depth": depth, "oldest_waiting_s": oldest},
            # Missing config renders as validation-style fields[] — one shape for
            # "something's not right" (§6).
            "fields": [
                {"field": key, "rule": "required_for_readiness", "message": f"{key} is not set"}
                for key in missing
            ],
        }
        if mode != "none":
            response.status_code = 503
            response.media_type = PROBLEM_CONTENT_TYPE
        return body

    return router


__all__ = ["QUEUE_STALE_AFTER_S", "DegradationMode", "build_health_router"]
