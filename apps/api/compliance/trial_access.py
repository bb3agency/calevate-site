"""What a FREE-TRIAL account may do, and the sentence each refusal says (D-697).

A trial account is one whose newest trial has not converted and which has not yet made its
first payment (`first_payment.has_paid`). It may build agents and place outbound test calls
from the shared trial number, and nothing else. Every refusal below is asked INSIDE the gate
it belongs to — `compliance.service.check_dispatch`, `campaigns.service.launch_blockers`, the
number purchase and record gates, the KYC write routes, `agents.service.publish_agent` — so
there is no parallel gate, and each returns the `(rule, reason)` pair those gates already
compose.

An account that has paid is never restricted, even if an operator gives it a trial
afterwards: that trial is the D-536 billing gift and nothing more. An account with no trial
is never restricted either; it simply has nothing to call with until it pays.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Final, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.engine_minutes import OWN_VOICE_RATE_KEYS
from apps.api.billing.first_payment import has_paid
from apps.api.billing.rates import PREMIUM_VOICE_TIER
from apps.api.billing.trials import (
    TRIAL_ACTIVE,
    TRIAL_CONVERTED,
    TrialState,
    minutes_of,
    read_trial,
    trial_calls_since,
    trial_seconds_used,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

_IST: Final = ZoneInfo("Asia/Kolkata")

#: The shortest limit a call can be placed with (`maxCallSeconds` minimum 60,
#: thinnest-findings/mirror/snapshots/2026-10-15/pages/api-reference/calls/
#: place-call.md:1264-1268), so a test call's last limit may overrun an allowance by under
#: a minute.
TRIAL_MIN_CALL_SECONDS: Final = 60

#: What a trial account is refused, by the gate that refuses it.
TrialLocked = Literal["campaigns", "numbers", "kyc", "inbound", "live_outbound"]

#: The next step every trial refusal ends on.
ADD_CREDIT_STEP: Final = "Add credit from Billing to go live."


def _refusal(*, rule: str, reason: str) -> tuple[str, str]:
    return (rule, reason)


TRIAL_REFUSALS: Final[dict[TrialLocked, tuple[str, str]]] = {
    "campaigns": _refusal(
        rule="trial_campaigns_unavailable",
        reason="Campaigns open once you add credit. During your free trial you can place test "
        "calls from your dashboard.",
    ),
    "numbers": _refusal(
        rule="trial_numbers_unavailable",
        reason="Phone numbers are available once you add credit and verify your business. During "
        "your free trial, test calls ring from a shared Calevate number.",
    ),
    "kyc": _refusal(
        rule="trial_kyc_unavailable",
        reason="Business verification is available once you add credit.",
    ),
    "inbound": _refusal(
        rule="trial_inbound_unavailable",
        reason=(
            "Answering calls starts after your first top-up and business check. Until then, "
            "use Try it, or give it a test call from your dashboard."
        ),
    ),
    "live_outbound": _refusal(
        rule="trial_live_outbound_unavailable",
        reason=(
            "During your free trial, calls go out only as test calls from your dashboard. "
            "Calling your leads opens once you add credit and verify your business."
        ),
    ),
}

#: The refusals a test call itself can meet, beside the ordinary dial gate.
TRIAL_ENDED_RULE: Final = "trial_ended"
TRIAL_ENDED_REASON: Final = "Your free trial has ended. Add credit to continue."
TRIAL_MINUTES_USED_RULE: Final = "trial_minutes_used"
TRIAL_MINUTES_USED_REASON: Final = (
    "You have used your free trial minutes, so your trial has ended. Add credit to continue."
)
TRIAL_DAILY_CAP_RULE: Final = "trial_daily_cap"
NOT_ON_TRIAL_RULE: Final = "trial_call_not_on_trial"
#: An account with neither a trial nor a first payment (D-859: a paid account's test calls
#: ring from its own number).
NOT_ON_TRIAL_REASON: Final = "Test calls open with a free trial, or once you add credit."


#: A trial account's agent cannot promise a call back (founder decision 1, 10 Oct 2026):
#: nothing can ring a caller back until the account pays, so a promise would be broken.
TRIAL_CALLBACK_RULE: Final = "trial_call_back_unavailable"
#: What the AGENT is told when it tries to book one, mid-call.
TRIAL_CALLBACK_SAY: Final = (
    "You could NOT book a call-back: call-backs are not available on this test call. Do "
    "NOT promise a call-back or a time. Tell the caller the business will follow up with "
    "them, then carry on helping."
)
#: What the CLIENT reads on a call back a trial account could not place.
TRIAL_CALLBACK_REASON: Final = (
    "Call backs are not placed during your free trial, so this caller was not rung back. "
    "Follow up with them yourself; call backs start once you add credit and verify your "
    "business."
)
#: The dial gate's trial refusals. Waiting cannot lift any of them inside a call back's
#: grace window, so the dispatcher ends the call back at once with `TRIAL_CALLBACK_REASON`
#: instead of showing it as waiting for two hours (first-call review F-5).
TRIAL_DIAL_REFUSALS: Final = frozenset(
    {
        TRIAL_REFUSALS["live_outbound"][0],
        TRIAL_ENDED_RULE,
        TRIAL_MINUTES_USED_RULE,
        TRIAL_DAILY_CAP_RULE,
    }
)


def daily_cap_reason(cap: int) -> str:
    return (
        f"You have placed today's {cap} test calls. You can place more tomorrow, or add "
        "credit to go live."
    )


async def restricting_trial(session: AsyncSession, *, tenant_id: UUID) -> TrialState | None:
    """The trial that restricts this account to test calls, or None if it is not restricted.

    Two indexed reads. Restricted means: a trial exists, it did not convert, and the account
    has not paid. The trial may still be running or may have ended unpaid — an ended trial
    keeps the restrictions and only stops the test calls.
    """
    trial = await read_trial(session, tenant_id=tenant_id)
    if trial is None or trial.status == TRIAL_CONVERTED:
        return None
    if await has_paid(session, tenant_id=tenant_id):
        return None
    return trial


async def trial_blocker(
    session: AsyncSession, *, tenant_id: UUID, locked: TrialLocked
) -> tuple[str, str] | None:
    """`(rule, reason)` when a trial account asks for `locked`, else None."""
    if await restricting_trial(session, tenant_id=tenant_id) is None:
        return None
    return TRIAL_REFUSALS[locked]


async def refuse_on_trial(session: AsyncSession, *, tenant_id: UUID, locked: TrialLocked) -> None:
    """The raising form of `trial_blocker`, for a single action with a single answer."""
    blocked = await trial_blocker(session, tenant_id=tenant_id, locked=locked)
    if blocked is not None:
        rule, reason = blocked
        raise ProblemError.business_rule(rule, reason, remediation=ADD_CREDIT_STEP)


async def refuse_trial_numbers(session: AsyncSession, *, tenant_id: UUID) -> None:
    await refuse_on_trial(session, tenant_id=tenant_id, locked="numbers")


def ist_day_start(at: datetime) -> datetime:
    """Midnight IST of the day `at` falls in, as a UTC instant: the daily cap's window."""
    local = at.astimezone(_IST)
    return datetime.combine(local.date(), time(0), tzinfo=_IST).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TrialAccess:
    """A trial account's test-call allowance right now. No money, no personal data."""

    trial: TrialState
    seconds_used: int
    calls_today: int
    daily_cap: int
    max_call_seconds: int
    at: datetime

    @property
    def free_seconds(self) -> int | None:
        minutes = self.trial.free_minutes
        return None if minutes is None else minutes * 60

    @property
    def minutes_used(self) -> int:
        return minutes_of(self.seconds_used)

    @property
    def minutes_left(self) -> int | None:
        free = self.free_seconds
        return None if free is None else max(0, (free - self.seconds_used) // 60)

    @property
    def ended(self) -> tuple[str, str] | None:
        """`(rule, reason)` once the trial is over by any measure, else None."""
        free = self.free_seconds
        if free is not None and self.seconds_used >= free:
            return (TRIAL_MINUTES_USED_RULE, TRIAL_MINUTES_USED_REASON)
        if self.trial.status != TRIAL_ACTIVE or not self.trial.is_active(at=self.at):
            return (TRIAL_ENDED_RULE, TRIAL_ENDED_REASON)
        return None

    @property
    def call_seconds(self) -> int:
        """How long the next test call may run: the console limit, or what is left of the
        free minutes if that is less. Never under the platform's 60-second floor
        (`place-call.md:1122-1126`), so the last call may overrun the allowance by under a
        minute."""
        free = self.free_seconds
        limit = self.max_call_seconds
        if free is not None:
            limit = min(limit, free - self.seconds_used)
        return max(TRIAL_MIN_CALL_SECONDS, limit)

    @property
    def blocker(self) -> tuple[str, str] | None:
        """Why the next test call cannot be placed, before the dial gate's own rules."""
        ended = self.ended
        if ended is not None:
            return ended
        if self.calls_today >= self.daily_cap:
            return (TRIAL_DAILY_CAP_RULE, daily_cap_reason(self.daily_cap))
        return None


async def read_trial_access(
    session: AsyncSession, *, tenant_id: UUID, at: datetime | None = None
) -> TrialAccess | None:
    """The account's test-call allowance, or None when it is not a trial account."""
    trial = await restricting_trial(session, tenant_id=tenant_id)
    if trial is None:
        return None
    now = at or datetime.now(UTC)
    settings = get_settings()
    return TrialAccess(
        trial=trial,
        seconds_used=await trial_seconds_used(session, tenant_id=tenant_id, trial=trial),
        calls_today=await trial_calls_since(session, tenant_id=tenant_id, since=ist_day_start(now)),
        daily_cap=settings.trial_daily_call_cap,
        max_call_seconds=settings.trial_call_max_seconds,
        at=now,
    )


# --- Studio minutes on a trial (D-727) ---------------------------------------------------

TRIAL_STUDIO_MINUTES_USED_RULE: Final = "trial_studio_minutes_used"

#: Is this agent's live vendor agent on a Studio voice (our own voice key)?
_AGENT_ON_STUDIO_SQL: Final = (
    "SELECT EXISTS (SELECT 1 FROM engine_agent_routes WHERE agent_id = :aid AND active "
    "AND engine = :engine AND engine_rate_key = ANY(:studio_keys))"
)

#: The trial's Studio seconds: metered test-call minutes on the Studio rung, plus the
#: recorded length of any test call not metered yet whose agent is on a Studio voice, so a
#: call that ended a moment ago counts before the post-call pipeline has run.
_TRIAL_STUDIO_SECONDS_SQL: Final = (
    "SELECT COALESCE((SELECT SUM(u.qty) * 60 FROM usage_events u JOIN calls c "
    "ON c.id = u.call_id AND c.tenant_id = u.tenant_id WHERE u.tenant_id = :tid "
    "AND u.unit_type = 'platform_min' AND u.meta->>'voice_tier' = :studio_tier "
    "AND c.trial_call AND c.created_at >= :since), 0) "
    "+ COALESCE((SELECT SUM(COALESCE(c.duration_s, 0)) FROM calls c WHERE c.tenant_id = :tid "
    "AND c.trial_call AND c.created_at >= :since AND NOT EXISTS (SELECT 1 FROM usage_events u "
    "WHERE u.tenant_id = c.tenant_id AND u.call_id = c.id AND u.unit_type = 'platform_min') "
    "AND EXISTS (SELECT 1 FROM engine_agent_routes r WHERE r.agent_id = c.agent_id AND r.active "
    "AND r.engine = :engine AND r.engine_rate_key = ANY(:studio_keys))), 0)"
)


async def trial_studio_seconds_used(
    session: AsyncSession, *, tenant_id: UUID, trial: TrialState
) -> int:
    """Seconds of Studio test calls this trial has used (`_TRIAL_STUDIO_SECONDS_SQL`)."""
    value = (
        await session.execute(
            text(_TRIAL_STUDIO_SECONDS_SQL),
            {
                "tid": tenant_id,
                "since": trial.started_at,
                "studio_tier": PREMIUM_VOICE_TIER,
                "engine": get_settings().engine,
                "studio_keys": sorted(OWN_VOICE_RATE_KEYS),
            },
        )
    ).scalar()
    return int(value or 0)


async def refuse_trial_studio_over_cap(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> int | None:
    """Refuse a trial test call on a Studio voice once the trial's Studio minutes reach
    `trial_studio_minutes`, and otherwise answer how many Studio seconds are left, which the
    call's own limit must not exceed. None for a Clear test call, which is not asked.

    Called by `agents.service.dispatch_call` inside the intent transaction, after
    `_hold_trial_line` took the platform's trial-line lock: the count and the new call's row
    are serialised with every other test call, so two dials cannot both pass it."""
    trial = await restricting_trial(session, tenant_id=tenant_id)
    if trial is None:
        return None
    settings = get_settings()
    on_studio = (
        await session.execute(
            text(_AGENT_ON_STUDIO_SQL),
            {
                "aid": agent_id,
                "engine": settings.engine,
                "studio_keys": sorted(OWN_VOICE_RATE_KEYS),
            },
        )
    ).scalar()
    if not on_studio:
        return None
    allowance = settings.trial_studio_minutes
    used = await trial_studio_seconds_used(session, tenant_id=tenant_id, trial=trial)
    if used < allowance * 60:
        return allowance * 60 - used
    raise ProblemError(
        kind="business_rule",
        code=TRIAL_STUDIO_MINUTES_USED_RULE,
        title="Your Studio minutes for the trial are used up",
        detail=f"This free trial includes {allowance} minutes of test calls on Studio voices.",
        remediation="Switch this agent to a Clear voice, or add credit to keep using Studio.",
    )


#: How long a placed trial call holds the shared number before its row ages out of the line
#: count even if its end was never reported: the call limit plus this margin for ringing and
#: a late end-of-call delivery. Ringing time is not documented by the platform, so the margin
#: is generous rather than measured.
TRIAL_LINE_MARGIN: Final = timedelta(minutes=3)


def trial_line_horizon() -> timedelta:
    return timedelta(seconds=get_settings().trial_call_max_seconds) + TRIAL_LINE_MARGIN


__all__ = [
    "ADD_CREDIT_STEP",
    "NOT_ON_TRIAL_REASON",
    "NOT_ON_TRIAL_RULE",
    "TRIAL_CALLBACK_REASON",
    "TRIAL_CALLBACK_RULE",
    "TRIAL_CALLBACK_SAY",
    "TRIAL_DAILY_CAP_RULE",
    "TRIAL_DIAL_REFUSALS",
    "TRIAL_ENDED_REASON",
    "TRIAL_ENDED_RULE",
    "TRIAL_LINE_MARGIN",
    "TRIAL_MINUTES_USED_REASON",
    "TRIAL_MINUTES_USED_RULE",
    "TRIAL_MIN_CALL_SECONDS",
    "TRIAL_REFUSALS",
    "TRIAL_STUDIO_MINUTES_USED_RULE",
    "TrialAccess",
    "TrialLocked",
    "daily_cap_reason",
    "ist_day_start",
    "read_trial_access",
    "refuse_on_trial",
    "refuse_trial_numbers",
    "refuse_trial_studio_over_cap",
    "restricting_trial",
    "trial_blocker",
    "trial_line_horizon",
    "trial_studio_seconds_used",
]
