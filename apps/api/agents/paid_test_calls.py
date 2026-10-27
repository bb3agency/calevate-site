"""After the first payment, the owner's TEST CALL to their own phone (D-859, founder option A).

A call runs in one ThinnestAI workspace: its `agent` must answer the phone there and its `from`
must be one of that agent's numbers (`thinnest-findings/mirror/snapshots/2026-10-19/pages/
api-reference/calls/place-call.md:544-549,617-629`), and a number is pointed only at an agent of
the workspace that holds it (`phone-numbers/update-phone-number.md:514`). So the shared trial
number, held in our developer workspace, cannot ring for an agent that has moved into the
client's own workspace. A paid test call therefore takes one of two lines:

* **The client's own number**, once the agent holds one there (live, its number attached):
  an ordinary call from the agent in the client workspace.
* **The shared trial line**, before that: exactly a trial call's path (the platform-wide trial
  line lock, `lend_trial_line`, the per-call limit) through a developer-workspace engine agent
  of this agent. That is the agent's own engine agent while it has not moved yet, and after the
  move its TEST COPY (`agent_test_copies`): the trial copy kept by the move while the client
  has no number, or made again. Before each such call the copy is republished from the agent's
  current config through `publish_agent(onto_test_copy=True)`, so it never lags the agent.

Either way the call is marked `calls.paid_test_call`, billed at the normal rates through the
ordinary post-call metering (the meter debits any call a trial does not cover,
`trials.trial_covers`), and passes the same dial gate as every test call (halt, account, agent
and its truthful answers, pledge, agreements, spend cap, credits, calling hours, India only,
the do-not-call list and consent). Today's cap is the trial's console setting
(`trial_daily_call_cap`). One call's length depends on the line (D-904): from the client's own
number it is the agent's own longest-call setting, at most `OWN_NUMBER_TEST_MAX_SECONDS`, so a
guided 5 to 10 minute call can be rehearsed as callers will hear it; on the shared trial line
it stays `trial_call_max_seconds`, because that one number serves every account's test calls
one at a time and a long rehearsal would hold it for everybody.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.first_payment import has_paid
from apps.api.compliance.trial_access import ist_day_start
from apps.api.core.settings import get_settings
from apps.api.tenancy.engine_workspace import resolve_workspace

DAILY_CAP_RULE: Final = "paid_test_daily_cap"
#: The longest a paying account's test call from its own number may run, whatever the agent's
#: own longest-call setting (D-904).
OWN_NUMBER_TEST_MAX_SECONDS: Final = 15 * 60

#: Which line a paid test call rings from: the client's own number, or the shared trial line
#: through the agent's developer-workspace engine agent (`copy` when that is its test copy,
#: republished first; `own` when the agent has not moved yet and is itself there).
PaidLine = Literal["own_number", "trial_line_own", "trial_line_copy"]

PLACED_TODAY_SQL: Final = (
    "SELECT count(*) FROM calls WHERE tenant_id = :tid AND paid_test_call "
    "AND created_at >= :since AND not_placed_reason IS NULL"
)
#: The agent's status, direction, vendor agent, the vendor handles of its numbers, and its own
#: longest-call setting.
_AGENT_LINE_SQL: Final = (
    "SELECT a.status, a.direction, a.engine_agent_ref, ARRAY(SELECT p.engine_number_ref "
    "FROM phone_numbers p WHERE p.agent_id = a.id AND p.released_at IS NULL "
    "AND p.engine_number_ref IS NOT NULL), a.max_call_duration_s FROM agents a "
    "WHERE a.tenant_id = :tid AND a.id = :aid AND a.deleted_at IS NULL"
)


def own_number_call_seconds(max_call_duration_s: int | None) -> int:
    """How long a test call from the client's own number may run: the agent's own cap, at
    most `OWN_NUMBER_TEST_MAX_SECONDS`, never below the shared line's."""
    from apps.api.agents.service import effective_call_cap

    shared = get_settings().trial_call_max_seconds
    return max(shared, min(effective_call_cap(max_call_duration_s), OWN_NUMBER_TEST_MAX_SECONDS))


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
    #: The line the asked-about agent rings from; None without an agent.
    line: PaidLine | None = None


def line_of(row: Any, workspace: str | None) -> PaidLine:
    """Which line this agent's paid test call rings from."""
    from apps.api.agents.service import holds_a_number

    status, direction, ref, numbers = row[:4]
    if not ref or scope_of(str(ref)) is None:
        return "trial_line_own"
    if (
        workspace is not None
        and scope_of(str(ref)) == workspace
        and holds_a_number(
            status=str(status),
            direction=str(direction),
            engine_agent_ref=ref,
            number_refs=list(numbers or ()),
        )
    ):
        return "own_number"
    return "trial_line_copy"


async def read_paid_test_access(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID | None = None,
    at: datetime | None = None,
) -> PaidTestAccess | None:
    """The account's paid test calls, or None when it has not paid. With `agent_id`, the line
    that agent rings from, and a blocker when the shared trial line is needed and not set up."""
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
    line: PaidLine | None = None
    call_seconds = settings.trial_call_max_seconds
    if agent_id is not None:
        row = (
            await session.execute(text(_AGENT_LINE_SQL), {"tid": tenant_id, "aid": agent_id})
        ).first()
        # A missing agent is worded by the dial gate; nothing to add here.
        if row is not None:
            line = line_of(row, await resolve_workspace(session, tenant_id))
            if line == "own_number":
                call_seconds = own_number_call_seconds(row[4])
    if line in ("trial_line_own", "trial_line_copy") and not settings.trial_caller_number:
        from apps.api.agents.trial_calls import NOT_READY_REASON, NOT_READY_RULE

        blocker = (NOT_READY_RULE, NOT_READY_REASON)
    if blocker is None and placed >= cap:
        blocker = (DAILY_CAP_RULE, paid_daily_cap_reason(cap))
    return PaidTestAccess(
        calls_today=placed,
        daily_cap=cap,
        max_call_seconds=call_seconds,
        day_start=since,
        blocker=blocker,
        line=line,
    )


async def refresh_test_copy(*, tenant_id: UUID, agent_id: UUID) -> str:
    """Republish the agent's current config onto its developer-workspace test copy (made again
    if it is gone) and mark it used, in its own committed transaction, before the call that
    rings through it. Returns the copy's handle."""
    from apps.api.agents.service import publish_agent
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        ref = await publish_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False, onto_test_copy=True
        )
        await session.execute(
            text(
                "UPDATE agent_test_copies SET last_used_at = now(), updated_at = now() "
                "WHERE agent_id = :aid"
            ),
            {"aid": agent_id},
        )
    return ref


__all__ = [
    "DAILY_CAP_RULE",
    "PLACED_TODAY_SQL",
    "PaidLine",
    "PaidTestAccess",
    "line_of",
    "paid_daily_cap_reason",
    "read_paid_test_access",
    "refresh_test_copy",
]
