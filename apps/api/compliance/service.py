"""The compliance gate — the ONE function every dispatch path must call.

Hard rule 5, stated as code: campaign launch, the D-21 "call this lead" button and the
instant-lead-callback webhook all place outbound calls, so they all pass through here.
There is **no bypass flag, not even for testing** — staging fixtures exist for that. A
`for_testing=True` parameter on this function would be the single most likely cause of
a real TRAI violation, because the one place it gets left on is production.

Checks, in the order that fails cheapest-first:

1. **Big red switch** — a global outbound halt beats every other consideration.
2. **Spend caps** — a capped tenant's outbound is refused (TRD §9); inbound is
   unaffected, which is why this gate is outbound-only.
3. **Calling hours** — per-tenant window in IST (SEC-COMP §3).
4. **DNC** — global + tenant entries, read LIVE. Additions must take effect before the
   next dispatch tick (hard rule 5), so this must never be cached.
5. **Disclosure line** — an agent without one may not dial at all.

Inbound calls never reach this function: the caller initiated them, which is the
consent-clean property D-38 leads with.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import record_compliance_block
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger

log = get_logger(__name__)

# IST. The DB stores UTC (conventions); the RULE is expressed in the caller's time,
# so the conversion happens here and nowhere else.
IST = timedelta(hours=5, minutes=30)
DEFAULT_WINDOW = (time(9, 0), time(21, 0))


@dataclass(frozen=True, slots=True)
class DispatchDecision:
    allowed: bool
    reason: str | None = None
    rule: str | None = None


def ist_now() -> datetime:
    return datetime.now(UTC) + IST


def within_calling_hours(
    now_ist: datetime | None = None, window: tuple[time, time] = DEFAULT_WINDOW
) -> bool:
    current = (now_ist or ist_now()).time()
    start, end = window
    return start <= current <= end


async def check_dispatch(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    phone_e164: str,
) -> DispatchDecision:
    """Returns a decision rather than raising, so callers can render *why* a button is
    disabled — SURFACES §2b asks for blocked features to be visibly explained instead
    of silently missing."""
    platform = await get_platform_status()
    if platform.outbound_halted:
        return DispatchDecision(
            allowed=False,
            rule="big_red_switch",
            reason="Outbound calling is halted platform-wide by the operations team.",
        )

    agent = (
        await session.execute(
            text(
                "SELECT disclosure_line, status, direction FROM agents "
                "WHERE id = :aid AND tenant_id = :tid AND deleted_at IS NULL"
            ),
            {"aid": agent_id, "tid": tenant_id},
        )
    ).first()
    if agent is None:
        return DispatchDecision(allowed=False, rule="agent_missing", reason="Agent not found.")
    disclosure, status, direction = agent
    if not disclosure or not str(disclosure).strip():
        # Belt and braces: the column is NOT NULL with a length CHECK, so reaching this
        # means something bypassed the schema. Refuse loudly rather than dial.
        return DispatchDecision(
            allowed=False,
            rule="disclosure_missing",
            reason="This agent has no AI disclosure line and may not place calls.",
        )
    if status != "live":
        return DispatchDecision(
            allowed=False, rule="agent_not_live", reason="This agent is not live yet."
        )
    if direction == "inbound":
        return DispatchDecision(
            allowed=False,
            rule="agent_inbound_only",
            reason="This agent only answers calls; it cannot place them.",
        )

    spend = (
        await session.execute(
            text("SELECT capped FROM spend_state WHERE tenant_id = :tid"), {"tid": tenant_id}
        )
    ).first()
    if spend is not None and bool(spend[0]):
        return DispatchDecision(
            allowed=False,
            rule="spend_cap",
            reason="This account has reached its spending cap for the month.",
        )

    if not within_calling_hours():
        return DispatchDecision(
            allowed=False,
            rule="calling_hours",
            reason="Outbound calls are only placed between 9:00 and 21:00 IST.",
        )

    # LIVE read, never cached: an opt-out captured mid-call must block the very next
    # dispatch. Covers both the tenant's own list and global entries (RLS lets a tenant
    # read global rows precisely so this query can see them).
    blocked = (
        await session.execute(
            text(
                "SELECT 1 FROM dnc_list WHERE phone_e164 = :phone "
                "AND (tenant_id = :tid OR tenant_id IS NULL) LIMIT 1"
            ),
            {"phone": phone_e164, "tid": tenant_id},
        )
    ).first()
    if blocked:
        return DispatchDecision(
            allowed=False,
            rule="dnc",
            reason="This number is on the do-not-call list.",
        )

    return DispatchDecision(allowed=True)


async def assert_dispatch_allowed(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, phone_e164: str
) -> None:
    """The raising form, for code paths that have no UI to explain a refusal."""
    decision = await check_dispatch(
        session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone_e164
    )
    if decision.allowed:
        return
    record_compliance_block(rule=decision.rule or "unknown")
    # Log the RULE and the tenant, never the number (hard rule 6).
    log.info("dispatch_blocked", extra={"rule": decision.rule, "tenant_id": str(tenant_id)})
    raise ProblemError.business_rule(
        f"dispatch_blocked_{decision.rule}",
        decision.reason or "This call cannot be placed.",
        remediation="Resolve the blocking condition and try again.",
    )


async def add_to_dnc(
    session: AsyncSession, *, tenant_id: UUID, phone_e164: str, source: str
) -> None:
    """Tenant-scope only. A global entry is not a tenant-reachable write (see the
    dnc_list migration) — the RLS WITH CHECK enforces that, not this function."""
    await session.execute(
        text(
            "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
            "created_at) VALUES (gen_random_uuid(), :tid, :phone, 'tenant', :source, now(), "
            "now()) ON CONFLICT (tenant_id, phone_e164) DO NOTHING"
        ),
        {"tid": tenant_id, "phone": phone_e164, "source": source},
    )


__all__ = [
    "DEFAULT_WINDOW",
    "IST",
    "DispatchDecision",
    "add_to_dnc",
    "assert_dispatch_allowed",
    "check_dispatch",
    "ist_now",
    "within_calling_hours",
]
