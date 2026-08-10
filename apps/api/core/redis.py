"""One lazily-built async Redis client per process.

Redis is used for: the health PING, the load-shed mode cache, the webhook fast-path
dedupe (SETNX), the audit chain-head lock, and ARQ's queue. It is never a system of
record — every durable truth is in Postgres (BACKEND-PATTERNS §4).
"""

from __future__ import annotations

from redis.asyncio import Redis

from apps.api.core.settings import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


__all__ = ["close_redis", "get_redis"]
