"""After the first payment, the owner's TEST CALL to their own phone (D-859).

During a trial a test call rings from the shared trial number, held in our developer workspace
and lent to the trial agent for the call (`trial_calls`). After payment the agents move into the
client's own workspace (`go_live/moves.py`), and that number cannot follow them: a call runs in
one workspace, its `agent` must answer the phone there and its `from` must be one of that agent's
numbers (`thinnest-findings/mirror/snapshots/2026-10-19/pages/api-reference/calls/place-call.md:
544-549,617-629`), and a number can be pointed only at an agent of the workspace that holds it
(`phone-numbers/update-phone-number.md:514`). Moving the shared number into the client's
workspace for a call is the one documented way across (`phone-numbers/move-phone-number.md:9`),
and it is not one: the number leaves every other agent and calling pool, arrives answered by
nobody, and an Indian number moves only to a workspace whose business details are approved
(`:598-618`).

So a paid test call rings from the client's OWN number: it is placed by an agent that holds one
(live, with its number attached in its own workspace), billed at the normal rates through the
ordinary post-call metering, under the same dial gate as every test call (halt, account, agent
and its truthful answers, pledge, agreements, spend cap, credits, calling hours, India only, the
do-not-call list and consent). Its limits are the trial's console settings: today's cap
(`trial_daily_call_cap`) and one call's length (`trial_call_max_seconds`). Until the account has
a number, a test call is refused with the step that opens it; what to offer in between is a
founder decision (D-859).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.first_payment import has_paid
from apps.api.compliance.trial_access import ist_day_start
from apps.api.core.settings import get_settings
from apps.api.tenancy.engine_workspace import resolve_workspace

AGENT_MOVING_RULE: Final = "paid_test_call_agent_moving"
AGENT_MOVING_REASON: Final = (
    "This agent is still moving to your own account. Test calls open again once it has moved."
)
NEEDS_OWN_NUMBER_RULE: Final = "paid_test_call_needs_own_number"
NEEDS_OWN_NUMBER_REASON: Final = (
    "Test calls now ring from your own number. Get your number and switch this agent on, "
    "then call it here."
)
DAILY_CAP_RULE: Final = "paid_test_daily_cap"

PLACED_TODAY_SQL: Final = (
    "SELECT count(*) FROM calls WHERE tenant_id = :tid AND paid_test_call "
    "AND created_at >= :since AND not_placed_reason IS NULL"
)
#: Each agent's status, direction, vendor agent and the vendor handles of its numbers. With
#: `:aid` NULL, the account's live agents (the dashboard's "can any agent take a test call?").
_AGENT_LINES_SQL: Final = (
    "SELECT a.status, a.direction, a.engine_agent_ref, ARRAY(SELECT p.engine_number_ref "
    "FROM phone_numbers p WHERE p.agent_id = a.id AND p.released_at IS NULL "
    "AND p.engine_number_ref IS NOT NULL) FROM agents a "
    "WHERE a.tenant_id = :tid AND a.deleted_at IS NULL AND (CAST(:aid AS uuid) IS NULL "
    "AND a.status = 'live' OR a.id = CAST(:aid AS uuid)) ORDER BY a.id LIMIT 50"
)


def paid_daily_cap_reason(cap: int) -> str:
    return f"You have placed today's {cap} test calls. You can place more tomorrow."


@dataclass(frozen=True, slots=True)
class PaidTestAccess:
    """A paid account's test calls today. No money, no personal data."""

    calls_today: int
    daily_cap: int
    max_call_seconds: int
    day_start: datetime
    #: `(rule, reason)` when the next test call cannot be placed, else None.
    blocker: tuple[str, str] | None


def _line_blocker(row: Any, workspace: str | None) -> tuple[str, str] | None:
    """Why this agent cannot place a paid test call, or None when it can."""
    from apps.api.agents.service import holds_a_number

    status, direction, ref, numbers = row
    if workspace is None or not ref or scope_of(str(ref)) != workspace:
        return (AGENT_MOVING_RULE, AGENT_MOVING_REASON)
    if not holds_a_number(
        status=str(status),
        direction=str(direction),
        engine_agent_ref=ref,
        number_refs=list(numbers or ()),
    ):
        return (NEEDS_OWN_NUMBER_RULE, NEEDS_OWN_NUMBER_REASON)
    return None


async def _agent_lines(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID | None
) -> tuple[list[Any], str | None]:
    rows = (
        await session.execute(
            text(_AGENT_LINES_SQL),
            {"tid": tenant_id, "aid": str(agent_id) if agent_id else None},
        )
    ).all()
    return list(rows), await resolve_workspace(session, tenant_id)


async def read_paid_test_access(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID | None = None,
    at: datetime | None = None,
) -> PaidTestAccess | None:
    """The account's paid test calls, or None when it has not paid. With `agent_id`, the
    blocker also says whether that agent can place one."""
    if not await has_paid(session, tenant_id=tenant_id):
        return None
    settings = get_settings()
    since = ist_day_start(at or datetime.now(UTC))
    placed = int(
        (
            await session.execute(text(PLACED_TODAY_SQL), {"tid": tenant_id, "since": since})
        ).scalar_one()
    )
    cap = settings.trial_daily_call_cap
    blocker: tuple[str, str] | None = None
    if agent_id is not None:
        rows, workspace = await _agent_lines(session, tenant_id=tenant_id, agent_id=agent_id)
        # A missing agent is worded by the dial gate; nothing to add here.
        blocker = _line_blocker(rows[0], workspace) if rows else None
    if blocker is None and placed >= cap:
        blocker = (DAILY_CAP_RULE, paid_daily_cap_reason(cap))
    return PaidTestAccess(
        calls_today=placed,
        daily_cap=cap,
        max_call_seconds=settings.trial_call_max_seconds,
        day_start=since,
        blocker=blocker,
    )


async def any_agent_can_test(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Does any of the account's live agents hold its own number in the account's workspace?
    One read of at most 50 agents."""
    rows, workspace = await _agent_lines(session, tenant_id=tenant_id, agent_id=None)
    return any(_line_blocker(row, workspace) is None for row in rows)


__all__ = [
    "AGENT_MOVING_REASON",
    "AGENT_MOVING_RULE",
    "DAILY_CAP_RULE",
    "NEEDS_OWN_NUMBER_REASON",
    "NEEDS_OWN_NUMBER_RULE",
    "PLACED_TODAY_SQL",
    "PaidTestAccess",
    "any_agent_can_test",
    "paid_daily_cap_reason",
    "read_paid_test_access",
]
