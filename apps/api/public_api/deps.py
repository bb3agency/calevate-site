"""What every public-surface route shares: its session, its key, paging, the agent binding
and the daily call budget (D-1047)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final
from uuid import UUID

from calevate_shared.calling_window import IST
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.trials import read_trial
from apps.api.core.auth import ApiKeyCall, current_api_key
from apps.api.core.context import note_request_fact
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.ratelimit import Decision
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session

log = get_logger(__name__)

KeyCall = Annotated[ApiKeyCall, Depends(current_api_key)]

#: Calls the API may place for one account in one IST day: lower on a free trial, where
#: we are paying for the minutes. The spend caps and the wallet stay the real ceiling.
DAILY_CALLS_TRIAL: Final = 20
DAILY_CALLS_PAID: Final = 500
#: Set on the ASGI scope when a request counted against the daily budget, so the outer
#: layer can report it in `RateLimit`.
DAILY_DECISION = "calevate_api_daily_calls"
DAILY_POLICY: Final = "calls-today"


async def key_db(call: KeyCall) -> AsyncIterator[AsyncSession]:
    """The key's own tenant session: RLS does the isolation, as on the console."""
    async with tenant_session(call.key.tenant_id) as session:
        yield session


KeyDb = Annotated[AsyncSession, Depends(key_db)]


def bound_agents(call: ApiKeyCall) -> list[UUID] | None:
    """The agents this key is limited to, or None for all of them."""
    return sorted(call.key.agent_ids) if call.key.agent_ids is not None else None


def require_agent(call: ApiKeyCall, agent_id: UUID | None) -> None:
    """Refuse an agent outside the key's binding. `None` passes: the route resolves the
    agent itself and asks again."""
    if agent_id is None or call.key.agent_ids is None or agent_id in call.key.agent_ids:
        return
    raise ProblemError(
        kind="permission",
        code="api_key_agent_refused",
        title="Not with this agent",
        detail="This key is limited to certain agents, and this request names another.",
        remediation="Use one of the key's agents, or make a key for this agent.",
    )


def paged[T](rows: Sequence[T], limit: int) -> tuple[list[T], bool]:
    """The page and whether there is more. Queries fetch `limit + 1` rows to know."""
    return list(rows[:limit]), len(rows) > limit


def _ist_day(now: datetime) -> tuple[str, int]:
    local = now.astimezone(IST)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.date().isoformat(), max(1, int((midnight - local).total_seconds()))


async def daily_budget(session: AsyncSession, tenant_id: UUID, *, now: datetime) -> int:
    trial = await read_trial(session, tenant_id=tenant_id)
    return DAILY_CALLS_TRIAL if trial is not None and trial.is_active(at=now) else DAILY_CALLS_PAID


def _day_key(tenant_id: UUID, day: str) -> str:
    return f"calevate:api:calls-today:{tenant_id}:{day}"


async def calls_placed_today(tenant_id: UUID, *, now: datetime | None = None) -> int:
    day, _ = _ist_day(now or datetime.now(UTC))
    try:
        value = await get_redis().get(_day_key(tenant_id, day))
    except Exception:
        log.warning("api_daily_budget_unavailable")
        return 0
    return int(value or 0)


async def spend_daily_call(
    request: Request, session: AsyncSession, tenant_id: UUID, *, now: datetime | None = None
) -> str:
    """Count one API-placed call against today's budget, or refuse it. Returns the bucket
    key so a call the gate refused can be given back (`refund_daily_call`).

    Fails CLOSED: a dial is the costly act, and a counter we cannot read is no bound."""
    at = now or datetime.now(UTC)
    day, resets = _ist_day(at)
    budget = await daily_budget(session, tenant_id, now=at)
    key = _day_key(tenant_id, day)
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 2 * 24 * 3600, nx=True)
        count = int((await pipe.execute())[0])
    except Exception:
        log.warning("api_daily_budget_unavailable")
        raise ProblemError(
            kind="transient",
            code="rate_limit_unavailable",
            title="Temporarily unavailable",
            detail="We're busy for a moment and could not place that call.",
            status=503,
            remediation="Try again in a minute.",
            headers={"Retry-After": "60"},
        ) from None
    decision = Decision(
        allowed=count <= budget,
        retry_after_s=0 if count <= budget else resets,
        reason="ok" if count <= budget else "over_limit",
        limit=budget,
        remaining=max(0, budget - count),
        resets_in_s=resets,
    )
    request.scope[DAILY_DECISION] = decision
    note_request_fact(DAILY_DECISION, decision)
    if not decision.allowed:
        await refund_daily_call(key)
        raise ProblemError(
            kind="transient",
            code="api_daily_call_budget",
            title="Today's API calls are used up",
            detail=f"This account may place {budget} calls a day through the API.",
            status=429,
            remediation="Calls through the API start again at midnight India time.",
            headers={"Retry-After": str(resets)},
        )
    return key


async def refund_daily_call(key: str) -> None:
    try:
        await get_redis().decr(key)
    except Exception:
        log.warning("api_daily_budget_unavailable")


__all__ = [
    "DAILY_CALLS_PAID",
    "DAILY_CALLS_TRIAL",
    "DAILY_DECISION",
    "DAILY_POLICY",
    "KeyCall",
    "KeyDb",
    "bound_agents",
    "calls_placed_today",
    "daily_budget",
    "key_db",
    "paged",
    "refund_daily_call",
    "require_agent",
    "spend_daily_call",
]
