"""How much of our own model's input was served from Google's cache (D-839, founder 20 Oct).

A call on our own model (D-764) is metered with the input tokens the engine counted and the
part of them it read from the provider's cache (`usage_events.meta.llm_input_tokens` and
`llm_cached_input_tokens` on the call's `llm_ktok_in` row, written by `workers/pipeline`).
Cached input is billed cheaper, so the share is what tells an operator whether the cost floor's
uncached assumption is far from what calls cost. Two readers:

* per call, for the admin Spend screen's call list (`call_cache_shares`, tenant session);
* for the fleet, over `FLEET_WINDOW`, beside the Cost floor on Voices, Our own model. It walks
  every tenant, so the hourly own-model sweep computes it (`refresh_fleet_cache_share`) and the
  card reads what was stored (`current_fleet_cache_share`), as the prompt-size basis does.

A call whose counts are missing (metered before the engine reported them) is left out, never
counted as zero cached.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.session import admin_session, tenant_session

log = get_logger(__name__)

#: How far back the fleet figure reads.
FLEET_WINDOW: Final = timedelta(days=30)
#: The stored fleet figure outlives two missed hourly sweeps, then reads as not measured.
CACHE_TTL_S: Final = 3 * 3600
_CACHE_KEY: Final = "calevate:own_model_cache_share"
#: The most calls one per-call read answers for (the Spend screen lists the costliest 50).
MAX_CALLS: Final = 200

_COUNTED: Final = (
    "unit_type = 'llm_ktok_in' AND meta->>'own_model' IS NOT NULL "
    "AND meta->>'llm_input_tokens' IS NOT NULL "
    "AND meta->>'llm_cached_input_tokens' IS NOT NULL"
)
_PER_CALL: Final = (
    "SELECT call_id, SUM((meta->>'llm_cached_input_tokens')::bigint), "
    "SUM((meta->>'llm_input_tokens')::bigint) FROM usage_events "
    f"WHERE call_id = ANY(:ids) AND {_COUNTED} GROUP BY call_id"
)
_TENANT_TOTAL: Final = (
    "SELECT COALESCE(SUM((meta->>'llm_cached_input_tokens')::bigint), 0), "
    "COALESCE(SUM((meta->>'llm_input_tokens')::bigint), 0), COUNT(DISTINCT call_id) "
    f"FROM usage_events WHERE occurred_at >= :since AND {_COUNTED}"
)
_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL"


@dataclass(frozen=True, slots=True)
class CacheShare:
    cached_input_tokens: int
    input_tokens: int
    calls: int

    @property
    def share(self) -> Decimal | None:
        """Cached input as a fraction of all input, to four places; None with no input."""
        if self.input_tokens <= 0:
            return None
        return (Decimal(self.cached_input_tokens) / Decimal(self.input_tokens)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )


@dataclass(frozen=True, slots=True)
class FleetCacheShare:
    totals: CacheShare
    computed_at: datetime


async def call_cache_shares(session: AsyncSession, call_ids: list[UUID]) -> dict[UUID, CacheShare]:
    """Each listed own-model call's cached and total input; other calls are absent. Tenant
    session: RLS is the filter."""
    if not call_ids:
        return {}
    rows = (await session.execute(text(_PER_CALL), {"ids": call_ids[:MAX_CALLS]})).all()
    return {
        UUID(str(r[0])): CacheShare(cached_input_tokens=int(r[1]), input_tokens=int(r[2]), calls=1)
        for r in rows
    }


async def compute_fleet_cache_share(*, now: datetime | None = None) -> FleetCacheShare:
    """Every tenant's own-model calls over `FLEET_WINDOW`, summed. `admin_session` reads the
    directory only; each tenant is read in its own session."""
    at = now or datetime.now(UTC)
    since = at - FLEET_WINDOW
    async with admin_session() as directory:
        tenants = [UUID(str(r[0])) for r in (await directory.execute(text(_DIRECTORY))).all()]
    cached = total = calls = 0
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            row = (await session.execute(text(_TENANT_TOTAL), {"since": since})).one()
        cached += int(row[0])
        total += int(row[1])
        calls += int(row[2])
    return FleetCacheShare(CacheShare(cached, total, calls), computed_at=at)


async def refresh_fleet_cache_share() -> FleetCacheShare:
    """Compute the fleet figure and store it for `CACHE_TTL_S`. The hourly sweep's step."""
    fleet = await compute_fleet_cache_share()
    payload = {
        "cached_input_tokens": fleet.totals.cached_input_tokens,
        "input_tokens": fleet.totals.input_tokens,
        "calls": fleet.totals.calls,
        "computed_at": fleet.computed_at.isoformat(),
    }
    await get_redis().set(_CACHE_KEY, json.dumps(payload), ex=CACHE_TTL_S)
    return fleet


async def current_fleet_cache_share() -> FleetCacheShare | None:
    """The stored fleet figure; None when none is stored or Redis cannot answer."""
    try:
        raw = await get_redis().get(_CACHE_KEY)
    except RedisError as exc:
        log.warning("own_model_cache_share_unreadable", extra={"error": type(exc).__name__})
        return None
    if raw is None:
        return None
    stored = json.loads(raw)
    return FleetCacheShare(
        CacheShare(
            cached_input_tokens=int(stored["cached_input_tokens"]),
            input_tokens=int(stored["input_tokens"]),
            calls=int(stored["calls"]),
        ),
        computed_at=datetime.fromisoformat(stored["computed_at"]),
    )


__all__ = [
    "FLEET_WINDOW",
    "MAX_CALLS",
    "CacheShare",
    "FleetCacheShare",
    "call_cache_shares",
    "compute_fleet_cache_share",
    "current_fleet_cache_share",
    "refresh_fleet_cache_share",
]
