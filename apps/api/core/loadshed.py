"""Load-shed guard — the big red switch's engineering face (BACKEND-PATTERNS §6).

Three-layer read, cheapest first: a 5s in-process memo → Redis cache → Postgres
(`platform_state`, the durable truth). A Redis flush therefore degrades performance,
never safety.

ALWAYS_ALLOWED_PREFIXES is the rule that keeps this from being a foot-gun: health,
auth, engine webhooks and the ops/admin surface are never shed. **The operator must
never lock themselves out, and provider callbacks must always land** — a dropped
engine webhook is a call whose lead never appears.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

LoadShedMode = Literal["normal", "reduced", "emergency", "maintenance"]

# Prefixes that bypass shedding entirely, in the order they matter.
ALWAYS_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/healthz",
    "/v1/auth",
    "/hooks",
    "/v1/ops",
    "/v1/admin",
    "/openapi.json",
    "/docs",
)

# What each mode sheds. `reduced` keeps every read working and stops the expensive
# writes; `emergency` is reads-only; `maintenance` is the planned-downtime mode.
_SHED_WRITES: frozenset[LoadShedMode] = frozenset({"reduced", "emergency", "maintenance"})
_SHED_READS: frozenset[LoadShedMode] = frozenset({"maintenance"})

_REDIS_KEY = "calevate:platform_state"
_MEMO_TTL_S = 5.0


@dataclass(frozen=True, slots=True)
class PlatformStatus:
    mode: LoadShedMode
    outbound_halted: bool


_memo: tuple[float, PlatformStatus] | None = None


async def get_platform_status(*, force_refresh: bool = False) -> PlatformStatus:
    global _memo
    now = time.monotonic()
    if not force_refresh and _memo is not None and now - _memo[0] < _MEMO_TTL_S:
        return _memo[1]

    status: PlatformStatus | None = None
    if not force_refresh:
        try:
            cached = await get_redis().hgetall(_REDIS_KEY)  # type: ignore[misc]
            if cached:
                status = PlatformStatus(
                    mode=_coerce_mode(cached.get("mode")),
                    outbound_halted=cached.get("outbound_halted") == "1",
                )
        except Exception:
            log.warning("loadshed_cache_unavailable")

    if status is None:
        status = await _read_durable()
        try:
            await get_redis().hset(  # type: ignore[misc]
                _REDIS_KEY,
                mapping={
                    "mode": status.mode,
                    "outbound_halted": "1" if status.outbound_halted else "0",
                },
            )
        except Exception:
            log.warning("loadshed_cache_write_failed")

    _memo = (now, status)
    return status


async def _read_durable() -> PlatformStatus:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT load_shed_mode, outbound_halted FROM platform_state WHERE id = 1")
            )
        ).first()
    if row is None:
        # Missing row = a fresh database, not an emergency. Fail OPEN here (and only
        # here): the durable default is what the seed script writes.
        return PlatformStatus(mode="normal", outbound_halted=False)
    return PlatformStatus(mode=_coerce_mode(row[0]), outbound_halted=bool(row[1]))


def _coerce_mode(value: str | None) -> LoadShedMode:
    # An unknown mode falls back to `normal` rather than failing closed: this value
    # comes from our own table, and a typo there must not take the platform down.
    modes: tuple[LoadShedMode, ...] = ("normal", "reduced", "emergency", "maintenance")
    for mode in modes:
        if value == mode:
            return mode
    return "normal"


async def set_platform_status(
    *, mode: LoadShedMode | None = None, outbound_halted: bool | None = None, actor_id: str | None
) -> PlatformStatus:
    """Write the durable row, then invalidate the cache. Callers MUST have passed the
    step-up confirmation check (§7) and MUST write an audit_log entry."""
    global _memo
    sets: list[str] = []
    params: dict[str, object] = {"actor": actor_id}
    if mode is not None:
        sets.append("load_shed_mode = :mode")
        params["mode"] = mode
    if outbound_halted is not None:
        sets.append("outbound_halted = :halted")
        params["halted"] = outbound_halted
    if not sets:
        return await get_platform_status()

    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE platform_state SET "
                + ", ".join(sets)
                + ", changed_by = CAST(NULLIF(:actor, '') AS uuid), changed_at = now() "
                "WHERE id = 1"
            ),
            params,
        )
    _memo = None
    try:
        await get_redis().delete(_REDIS_KEY)
    except Exception:
        log.warning("loadshed_cache_invalidate_failed")
    return await get_platform_status(force_refresh=True)


def is_shed(status: PlatformStatus, *, path: str, method: str) -> bool:
    if any(path.startswith(prefix) for prefix in ALWAYS_ALLOWED_PREFIXES):
        return False
    if status.mode in _SHED_READS:
        return True
    return method not in ("GET", "HEAD", "OPTIONS") and status.mode in _SHED_WRITES


__all__ = [
    "ALWAYS_ALLOWED_PREFIXES",
    "LoadShedMode",
    "PlatformStatus",
    "get_platform_status",
    "is_shed",
    "set_platform_status",
]
