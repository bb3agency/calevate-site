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

An agent with no engine agent of its own (D-1019: only inbound lines and campaigns hold one)
rings through its test copy holding "Just the business".

Once the client holds a number of its own in its workspace (`own_test_workspace`), every test
call rings from it (D-1020): the test copy is then made in the client's workspace, beside its
numbers, kept an hour after its last use and given back
(`service.retire_idle_client_test_copies`); with no free engine agent there, it is made in
ours and rings from the shared line as before.

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
#: republished first; `own` when the agent has not moved yet and is itself there). An agent
#: holding no engine agent (D-1019) is always `copy`.
PaidLine = Literal["own_number", "trial_line_own", "trial_line_copy"]

PLACED_TODAY_SQL: Final = (
    "SELECT count(*) FROM calls WHERE tenant_id = :tid AND paid_test_call "
    "AND created_at >= :since AND not_placed_reason IS NULL"
)
#: The agent's status, direction, vendor agent, the vendor handles of every number its client
#: can call out from (a client's number serves all its agents, lent per call), and its own
#: longest-call setting.
_AGENT_LINE_SQL: Final = (
    "SELECT a.status, a.direction, a.engine_agent_ref, ARRAY(SELECT p.engine_number_ref "
    "FROM phone_numbers p WHERE p.released_at IS NULL AND p.engine_number_ref IS NOT NULL "
    "AND p.direction IN ('outbound', 'both')), a.max_call_duration_s FROM agents a "
    "WHERE a.tenant_id = :tid AND a.id = :aid AND a.deleted_at IS NULL"
)


#: The account's numbers it can call out from, with their vendor handles: what
#: `service.caller_lines` offers on an engine that rings only its own numbers (`:carrier`).
_CALLING_NUMBERS_SQL: Final = (
    "SELECT engine_number_ref FROM phone_numbers WHERE released_at IS NULL "
    "AND engine_number_ref IS NOT NULL AND direction IN ('outbound', 'both') "
    "AND (CAST(:carrier AS text) IS NULL OR provider = :carrier)"
)


async def own_test_workspace(session: AsyncSession, *, tenant_id: UUID) -> str | None:
    """The client's own workspace when this account's test calls ring from its own number
    (D-1020, founder 18 Nov 2026): it has paid and holds at least one number there it can
    call out from. None for a free trial or a paid account with no number yet, whose test
    calls ring from the shared test number. A call's `agent` must answer the phone in the
    workspace placing it and its `from` must be one of that agent's numbers
    (`thinnest-findings/mirror/snapshots/2026-10-19/pages/api-reference/calls/
    place-call.md:544-547,617-620`), so a number in another workspace does not count."""
    from apps.api.agents.service import outbound_number_provider

    if not await has_paid(session, tenant_id=tenant_id):
        return None
    workspace = await resolve_workspace(session, tenant_id)
    if workspace is None:
        return None
    refs = (
        await session.execute(text(_CALLING_NUMBERS_SQL), {"carrier": outbound_number_provider()})
    ).scalars()
    return workspace if any(scope_of(str(ref)) == workspace for ref in refs) else None


async def own_caller_number(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> str | None:
    """The account's own number a test call would ring from (D-1020), E.164, or None when it
    rings from the shared test number. A line's test: one of its numbers; a campaign's: its
    calling number; otherwise the account's first (`service.caller_lines`' order, the agent's
    own first). For the screen before the call; the dial chooses again with the same order."""
    from apps.api.agents.service import caller_lines

    workspace = await own_test_workspace(session, tenant_id=tenant_id)
    if workspace is None:
        return None
    lines = [
        line
        for line in await caller_lines(session, agent_id=agent_id, workspace=workspace)
        if line.engine_number_ref and scope_of(line.engine_number_ref) == workspace
    ]
    preferred: set[UUID] = set()
    if line_id is not None:
        rows = await session.execute(
            text(
                "SELECT id FROM phone_numbers WHERE inbound_line_id = :lid AND released_at IS NULL"
            ),
            {"lid": line_id},
        )
        preferred = {UUID(str(number_id)) for number_id in rows.scalars()}
    elif campaign_id is not None:
        chosen = (
            await session.execute(
                text("SELECT number_id FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
            )
        ).scalar_one_or_none()
        preferred = {UUID(str(chosen))} if chosen is not None else set()
    first = next((line for line in lines if line.number_id in preferred), None)
    if first is None and lines:
        first = lines[0]
    return first.e164 if first is not None else None


@dataclass(frozen=True, slots=True)
class RingsFrom:
    """Where a test call would ring from, said before the call (D-1020)."""

    #: The account's own number, E.164; None when it rings from our test number.
    own_number: str | None = None
    #: It would ring from our test number only because the workspace has no free setup.
    setups_busy: bool = False
    #: Why it cannot ring at all right now: no free setup and no shared number to fall back to.
    unavailable: str | None = None


async def rings_from(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> RingsFrom:
    """`own_caller_number`, checked against the workspace's free setups: a test that must make
    a new engine agent in a full workspace rings from our test number, or not at all when that
    is not set (`trial_calls.place_trial_call` decides the same way when the owner presses)."""
    from apps.api.agents.service import allowance_refusal, test_copy_ref
    from apps.api.agents.trial_calls import trial_calling_ready

    number = await own_caller_number(
        session, tenant_id=tenant_id, agent_id=agent_id, line_id=line_id, campaign_id=campaign_id
    )
    if number is None:
        return RingsFrom()
    workspace = await resolve_workspace(session, tenant_id)
    if not await _needs_new_setup(
        session,
        tenant_id=tenant_id,
        workspace=workspace,
        agent_id=agent_id,
        line_id=line_id,
        campaign_id=campaign_id,
        copy_ref=await test_copy_ref(session, agent_id),
    ):
        return RingsFrom(own_number=number)
    refusal = await allowance_refusal(
        session, tenant_id=tenant_id, workspace=workspace, context="test_call"
    )
    if refusal is None:
        return RingsFrom(own_number=number)
    if trial_calling_ready():
        return RingsFrom(setups_busy=True)
    return RingsFrom(
        unavailable=" ".join(part for part in (refusal.detail, refusal.remediation) if part)
    )


async def _needs_new_setup(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace: str | None,
    agent_id: UUID,
    line_id: UUID | None,
    campaign_id: UUID | None,
    copy_ref: str | None,
) -> bool:
    """Whether this test has nothing in the client's workspace to ring through yet: a
    campaign's or line's own engine agent, the agent's own on a number, or a test copy made
    there for an earlier test."""
    if campaign_id is not None:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :id"), {"id": campaign_id}
            )
        ).scalar_one_or_none()
        return not (ref and scope_of(str(ref)) == workspace)
    if line_id is not None:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM inbound_lines WHERE id = :id"), {"id": line_id}
            )
        ).scalar_one_or_none()
        return not (ref and scope_of(str(ref)) == workspace)
    row = (
        await session.execute(text(_AGENT_LINE_SQL), {"tid": tenant_id, "aid": agent_id})
    ).first()
    if row is not None and line_of(row, workspace) == "own_number":
        return False
    return not (copy_ref and scope_of(copy_ref) == workspace)


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
    #: The client's workspace when its test calls ring from its own number (D-1020).
    own_workspace: str | None = None


def line_of(row: Any, workspace: str | None) -> PaidLine:
    """Which line this agent's paid test call rings from."""
    from apps.api.agents.service import holds_a_number

    status, direction, ref, numbers = row[:4]
    if not ref:
        # Nothing of its own to ring from or to dial through (D-1019): its test copy.
        return "trial_line_copy"
    if scope_of(str(ref)) is None:
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
    own_workspace = await own_test_workspace(session, tenant_id=tenant_id)
    if agent_id is not None:
        row = (
            await session.execute(text(_AGENT_LINE_SQL), {"tid": tenant_id, "aid": agent_id})
        ).first()
        # A missing agent is worded by the dial gate; nothing to add here.
        if row is not None:
            line = line_of(row, await resolve_workspace(session, tenant_id))
            if line == "own_number" or own_workspace is not None:
                call_seconds = own_number_call_seconds(row[4])
    if (
        own_workspace is None
        and line in ("trial_line_own", "trial_line_copy")
        and not settings.trial_caller_number
    ):
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
        own_workspace=own_workspace,
    )


#: A test call of this agent through its test copy that has not ended: one on the shared
#: trial line (every call through a developer-workspace copy takes it), or a paying account's
#: own-number call through a copy in its workspace (D-1020), which names the copy it rang.
_COPY_CALL_LIVE_SQL: Final = (
    "SELECT EXISTS (SELECT 1 FROM calls WHERE agent_id = :aid AND inbound_line_id IS NULL "
    "AND (trial_call OR (paid_test_call AND engine_agent_ref = "
    "(SELECT engine_agent_ref FROM agent_test_copies WHERE agent_id = :aid))) "
    "AND status IN ('queued', 'ringing', 'in_progress') "
    "AND created_at > now() - make_interval(secs => :horizon))"
)


async def copy_call_live(session: AsyncSession, agent_id: UUID) -> bool:
    """Might a test call be on the agent's test copy right now?

    One copy holds either "Just the business" or the agent with a campaign's script, and what
    re-publishing a vendor agent does to a call in progress is not documented (OPERATIONS
    T-28), so the copy is never re-published under a live call: the business chat and call
    and a campaign's test call take turns on it, as they already do on the one trial line.
    Reads `calls` rather than the vendor's connected list, which misses a call still ringing."""
    from apps.api.compliance.trial_access import trial_line_horizon

    return bool(
        (
            await session.execute(
                text(_COPY_CALL_LIVE_SQL),
                {"aid": agent_id, "horizon": trial_line_horizon().total_seconds()},
            )
        ).scalar()
    )


async def refresh_test_copy(
    *, tenant_id: UUID, agent_id: UUID, business: bool = False, in_client: bool | None = None
) -> str:
    """Republish the agent's current config onto its test copy (made again if it is gone) and
    mark it used, in its own committed transaction, before the call or chat that goes through
    it. `business` publishes it as "Just the business" (`agents/business_only`). Returns the
    copy's handle.

    `in_client` is where the copy must be: True in the client's own workspace, for a test
    call from the client's own number (D-1020); False in our developer workspace, for one on
    the shared test line; None wherever it already is (a chat, which places no call), and in
    ours when there is none.

    Refused as `trial_line_busy` while a test call may be on the copy (`copy_call_live`);
    that call would hold the shared line anyway, so the dial behind this could not ring."""
    from apps.api.agents.service import TRIAL_LINE_BUSY_RULE, publish_agent, test_copy_ref
    from apps.api.core.errors import ProblemError
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        if await copy_call_live(session, agent_id):
            raise ProblemError.conflict(
                TRIAL_LINE_BUSY_RULE,
                "Another test call is in progress.",
                remediation="Try again in a minute.",
            )
        if in_client is None:
            held = await test_copy_ref(session, agent_id)
            in_client = held is not None and scope_of(held) is not None
        ref = await publish_agent(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            take_calls=False,
            onto_test_copy=True,
            business_only=business,
            in_client=in_client,
        )
        await session.execute(
            text(
                "UPDATE agent_test_copies SET last_used_at = now(), updated_at = now() "
                "WHERE agent_id = :aid"
            ),
            {"aid": agent_id},
        )
    return ref


async def business_copy_ref(*, tenant_id: UUID, agent_id: UUID) -> str:
    """The agent's test copy holding "Just the business", republished first so it holds the
    agent as it is now. While a test call may be on a copy that already holds it, that copy is
    used as it is rather than refused, since republishing would change nothing it says;
    a copy holding anything else waits for the call (`refresh_test_copy`)."""
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref, business_only FROM agent_test_copies "
                    "WHERE agent_id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()
        if row is not None and row.business_only and await copy_call_live(session, agent_id):
            return str(row.engine_agent_ref)
    return await refresh_test_copy(tenant_id=tenant_id, agent_id=agent_id, business=True)


async def agent_test_ref(*, tenant_id: UUID, agent_id: UUID, own_ref: str | None) -> str:
    """The engine agent a test chat of this agent talks to: its own while it holds one, else
    (D-1019, an agent holds none; its lines and campaigns do) its "Just the business" copy,
    which is the agent with no job's script. Not called inside another session: the
    republish commits in its own transaction."""
    if own_ref:
        return own_ref
    return await business_copy_ref(tenant_id=tenant_id, agent_id=agent_id)


__all__ = [
    "DAILY_CAP_RULE",
    "PLACED_TODAY_SQL",
    "PaidLine",
    "PaidTestAccess",
    "RingsFrom",
    "agent_test_ref",
    "business_copy_ref",
    "copy_call_live",
    "line_of",
    "own_caller_number",
    "own_test_workspace",
    "paid_daily_cap_reason",
    "read_paid_test_access",
    "refresh_test_copy",
    "rings_from",
]
