"""Load-shed guard — the big red switch's engineering face (BACKEND-PATTERNS §6).

Three-layer read, cheapest first: a 5s in-process memo → Redis cache → Postgres
(`platform_state`, the durable truth). A Redis flush therefore degrades performance,
never safety.

**Every cached copy expires, and a copy that does not is not trusted.** The cache used
to be written with no TTL and invalidated only by a best-effort `DELETE` inside a
swallowed `except` — so ONE failed round trip, at the exact moment Redis is flaky and
an operator is pulling the big red switch, made a stale "open" permanent in every
process: they never consulted the durable row again. Staleness is now bounded by
`_CACHE_TTL_S + _MEMO_TTL_S`, which is shorter than one campaign dispatch tick, and a
key with no expiry is treated as a miss because this module never writes one.

ALWAYS_ALLOWED_PREFIXES is the rule that keeps this from being a foot-gun: health,
engine webhooks, the ops/admin surface and the schema/doc endpoints are never shed.
**The operator must never lock themselves out, and provider callbacks must always
land** — a dropped engine webhook is a call whose lead never appears.

It listed `/v1/auth` too, "so signing in survives maintenance", and that exemption was
aimed at a route this API did not have while Clerk owned sessions (TRD §11). D-177
brought them in-house, and `/v1/auth/**` is now real; nothing under
`/v1/auth` mints one. The ONE route the prefix actually covered was
`POST /v1/auth/signup` — a multi-table write that creates an organization, an agent, an
extraction schema and a set of retention policies — so the exemption's only effect was
to let the platform keep manufacturing tenants while it was too degraded to serve the
ones it had. Removed rather than narrowed: an exemption naming a surface that does not
exist cannot be narrowed to anything, and if a session route is ever added here it
should be exempted BY NAME, with the reason, on the day it exists. Its sibling
`POST /v1/invitations/accept` — the other write reachable by a caller with no
organization yet — was never exempt and is shed like any other write, which is the
consistency this restores. `tests/loadshed_exemption_test.py` asserts the census.
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

# Prefixes that bypass shedding entirely, in the order they matter. Three admissible
# reasons and no fourth: the platform must stay OBSERVABLE (`/healthz`, and the schema
# the console is generated from), the operator must stay ABLE TO ACT (`/v1/ops`,
# `/v1/admin` — a shed you cannot turn off is an outage you caused), and a provider
# callback must always LAND (`/hooks` — a dropped engine webhook is a call whose lead
# never appears). Nothing on this list is exempt because it is important to a customer;
# expensive customer-facing writes are exactly what shedding is for.
ALWAYS_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/healthz",
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
# How long a cached status may survive without anyone re-reading Postgres. Short on
# purpose: it is the ceiling on how long a HALT can go unnoticed if its invalidation
# was lost, and `dispatch_campaign_tick` (every 30s) reads the halt once per tick, so
# _CACHE_TTL_S + _MEMO_TTL_S must stay under a tick or a tick could dial through it.
# Cost of the shortness is one small Postgres read per process per TTL — nothing.
_CACHE_TTL_S = 15


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
            cached, ttl = await _cache_read()
            # `ttl <= 0` means the key exists with no expiry (-1) or not at all (-2).
            # Every write below sets an expiry, so a persistent key is a leftover — the
            # residue of an invalidation that never landed. Reading Postgres instead is
            # what stops it being served until someone notices the calls never stopped.
            if cached and ttl > 0:
                status = PlatformStatus(
                    mode=_coerce_mode(cached.get("mode")),
                    outbound_halted=cached.get("outbound_halted") == "1",
                )
        except Exception:
            log.warning("loadshed_cache_unavailable")

    if status is None:
        status = await _read_durable()
        try:
            await _cache_write(status)
        except Exception:
            log.warning("loadshed_cache_write_failed")

    _memo = (now, status)
    return status


async def _cache_read() -> tuple[dict[str, str], int]:
    """The cached value AND its remaining life, in one round trip.

    The TTL is read with the value rather than after it because the two together are
    the trust decision: a value whose key cannot expire is not one this module wrote
    and finished writing.
    """
    async with get_redis().pipeline(transaction=False) as pipe:
        pipe.hgetall(_REDIS_KEY)
        pipe.ttl(_REDIS_KEY)
        cached, ttl = await pipe.execute()
    return dict(cached or {}), int(ttl)


async def _cache_write(status: PlatformStatus) -> None:
    """Value and expiry in ONE transaction.

    Split into two calls, a crash or a connection drop between them would leave exactly
    the immortal key this file exists to rule out — so MULTI/EXEC, and every write of
    `_REDIS_KEY` goes through here.
    """
    async with get_redis().pipeline(transaction=True) as pipe:
        pipe.hset(
            _REDIS_KEY,
            mapping={
                "mode": status.mode,
                "outbound_halted": "1" if status.outbound_halted else "0",
            },
        )
        pipe.expire(_REDIS_KEY, _CACHE_TTL_S)
        await pipe.execute()


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
    *,
    mode: LoadShedMode | None = None,
    outbound_halted: bool | None = None,
    halt_reason: str | None = None,
    actor_id: str | None,
) -> PlatformStatus:
    """Write the durable row, invalidate the cache, then write the new value THROUGH.

    Callers MUST have passed the step-up confirmation check (§7) and MUST write an
    audit_log entry.

    Three layers of defence, because a halt that does not stick is the same as no halt:
    the DELETE makes peers miss immediately, the write-through (`force_refresh` below)
    puts the new value in the cache before this returns, and the expiry every write
    carries bounds the damage if BOTH of those fail.

    `halt_reason` MOVES WITH THE SWITCH and only with the switch. It is written in the
    same UPDATE as `outbound_halted` (one row, one statement — a second write could
    leave a halt with no reason or a reason with no halt), it is CLEARED on release
    because a reason sitting beside `outbound_halted = false` is read as current by
    everyone who did not read this file, and a request that does not carry
    `outbound_halted` at all leaves it untouched — tightening load-shedding during an
    incident must not erase why dialling stopped. The permanent history is `audit_log`;
    this column answers only "why is outbound stopped RIGHT NOW".

    It is not returned in `PlatformStatus` deliberately: this dataclass is the hot-path
    shed decision, cached in Redis and read on every request, and the reason is only
    ever for a human. `ops.service.read_halt_state` reads it durably, uncached, on the
    caller's session — the same argument `read_tm_registration` makes.
    """
    global _memo
    sets: list[str] = []
    params: dict[str, object] = {"actor": actor_id}
    if mode is not None:
        sets.append("load_shed_mode = :mode")
        params["mode"] = mode
    if outbound_halted is not None:
        sets.append("outbound_halted = :halted")
        params["halted"] = outbound_halted
        sets.append("halt_reason = :halt_reason")
        params["halt_reason"] = (halt_reason or None) if outbound_halted else None
        if outbound_halted and not (halt_reason or "").strip():
            # Reachable only from inside the process (test harnesses halt this way):
            # `ops.routes.PlatformStateIn` makes the reason mandatory at the boundary,
            # so no operator can produce this. Logged rather than raised because
            # refusing a HALT is the one failure this module must never invent — a
            # switch that will not throw is worse than one thrown without a note.
            log.warning("platform_halted_without_reason", extra={"actor_id": actor_id})
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
        # Best-effort, and known to be: this is the peers' fast path, never the
        # guarantee. The guarantee is the write-through on the next line plus the
        # expiry it carries.
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
