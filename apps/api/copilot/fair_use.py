"""The assistant's fair-use cap: free, up to a daily amount per account (D-694).

THE FOUNDER'S DECISION: the in-app assistant costs the client nothing — no allowance is
drawn, no wallet is charged — and each account may use it up to a daily cap set in the
console (`copilot_daily_message_cap`, `copilot_daily_ktok_cap`). Past either, the
assistant says so plainly and an operator is told.

COUNTED ON THE EXISTING LEDGER, not a new counter. Every metered assistant answer already
writes its `usage_events` pair under `meta.feature = 'copilot'` (`crm/assist.meter_assist`,
D-499/G-3/G-4), so "how much has this account used today" is one indexed read of rows that
exist for billing reasons anyway — a second counter would be a second number that could
disagree with the first. A question answered on the free disclosed fallback writes no row
(D-36), so it is not counted; that is the generous direction and it is bounded by the
platform brake, which still applies.

THE DAY IS THE IST DAY, the clock every client-facing period in this product uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import ai_quota
from apps.api.billing.models import AI_ASSIST_UNIT_TYPES, FREE_ASSIST_FEATURES
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings

log = get_logger(__name__)

IST: Final = ZoneInfo("Asia/Kolkata")

#: The Redis marker that makes the operator alarm once per account per day.
_ALERTED_KEY: Final = "calevate:copilot:fair-use:alerted:{tenant}:{day}"

_TODAY_SQL: Final = (
    "SELECT COUNT(DISTINCT ref), COALESCE(SUM(qty), 0) FROM usage_events "
    "WHERE tenant_id = :tid AND unit_type = ANY(:units) AND ref IS NOT NULL "
    "AND meta->>'feature' = ANY(:features) "
    "AND occurred_at >= :day_from AND occurred_at < :day_to"
)


@dataclass(frozen=True, slots=True)
class FairUse:
    """Today's use against today's cap."""

    day: str
    messages: int
    ktok: Decimal
    message_cap: int
    ktok_cap: int

    @property
    def reached(self) -> bool:
        return self.messages >= self.message_cap or self.ktok >= self.ktok_cap


def ist_day_bounds(now: datetime | None = None) -> tuple[str, datetime, datetime]:
    """Today's IST date and its [start, end) as UTC instants."""
    local = (now or datetime.now(UTC)).astimezone(IST)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        start.date().isoformat(),
        start.astimezone(UTC),
        (start + timedelta(days=1)).astimezone(UTC),
    )


async def read_fair_use(
    session: AsyncSession, *, tenant_id: UUID, now: datetime | None = None
) -> FairUse:
    day, day_from, day_to = ist_day_bounds(now)
    row = (
        await session.execute(
            text(_TODAY_SQL),
            {
                "tid": tenant_id,
                "units": list(AI_ASSIST_UNIT_TYPES),
                "features": list(FREE_ASSIST_FEATURES),
                "day_from": day_from,
                "day_to": day_to,
            },
        )
    ).one()
    settings = get_settings()
    return FairUse(
        day=day,
        messages=int(row[0] or 0),
        ktok=Decimal(str(row[1] or 0)),
        message_cap=settings.copilot_daily_message_cap,
        ktok_cap=settings.copilot_daily_ktok_cap,
    )


async def _alert_once(tenant_id: UUID, day: str) -> None:
    """Raise the operator alarm the first time an account reaches the cap today.

    FAILS TOWARDS ALERTING: if Redis cannot answer, the alarm fires anyway — a duplicate
    console row is noise, a missed one is an account an operator never heard about.
    """
    first = True
    try:
        first = bool(
            await get_redis().set(
                _ALERTED_KEY.format(tenant=tenant_id, day=day), "1", nx=True, ex=2 * 86_400
            )
        )
    except Exception:
        log.warning("copilot_fair_use_marker_unavailable")
    if first:
        alert(
            "CORE_LOGIC",
            "copilot_fair_use_reached",
            detail=(
                "An account reached the in-app assistant's daily fair-use cap and is being "
                "told so. Check whether the usage looks like a person or a loop, and raise "
                "the cap in platform configuration if it is legitimate."
            ),
            tenant_id=str(tenant_id),
            day=day,
        )


async def require_copilot_fair_use(session: AsyncSession, *, tenant_id: UUID) -> FairUse:
    """May this account ask the assistant now? Returns today's use, or REFUSES.

    The platform brake first, with the same code and words every other AI surface uses, so
    a client sees one sentence for one event.
    """
    if await ai_quota.platform_brake_tripped(session):
        raise ProblemError(
            kind="transient",
            code="ai_paused_platform_wide",
            title="AI help is paused",
            detail=(
                "AI help is paused across Calevate while we check unusually high usage. "
                "Your calls, campaigns and leads are unaffected."
            ),
            remediation="Try again later, or ask your account manager for an update.",
        )
    usage = await read_fair_use(session, tenant_id=tenant_id)
    if usage.reached:
        await _alert_once(tenant_id, usage.day)
        raise ProblemError.business_rule(
            "copilot_daily_limit_reached",
            (
                "You have used the assistant a lot today and reached today's limit. It is "
                "free, and the limit resets at midnight."
            ),
            remediation=(
                "Your calls, campaigns and leads keep working as normal. You can still do "
                "everything yourself from the screens, and the assistant is back tomorrow."
            ),
        )
    return usage


__all__ = ["FairUse", "ist_day_bounds", "read_fair_use", "require_copilot_fair_use"]
