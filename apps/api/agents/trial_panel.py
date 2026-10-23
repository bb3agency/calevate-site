"""The free-trial panel a client reads (D-697): one builder, two routes.

`GET /v1/trial` serves it on its own (the header chip, an agent's Try it section), and
`GET /v1/dashboard` carries it so the dashboard's trial card arrives with the rest of the
dashboard instead of in a second round trip after it (D-787).

Dates, counts and sentences only; no cost, no number of ours, no vendor name.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.paid_test_calls import read_paid_test_access
from apps.api.agents.trial_calls import NOT_READY_REASON, TRIAL_CALL_ENGINES, trial_calling_ready
from apps.api.compliance.outbound_pledge import pledge_blocker
from apps.api.compliance.trial_access import TRIAL_REFUSALS, read_trial_access
from apps.api.core.settings import get_settings


class TrialPanelOut(BaseModel):
    """The trial as its own client reads it. `on_trial` false means the trial fields do not
    apply: the account has paid (then `paid_test_calls` carries its own test calls), or was
    never given a trial."""

    model_config = ConfigDict(extra="forbid")

    on_trial: bool
    #: The account has paid (D-859): its test calls ring from its own number, or before it has
    #: one from the shared trial line, and are billed. The panel shows today's test calls and
    #: the limits, never trial copy. `on_trial` is then false.
    paid_test_calls: bool = False
    #: `active`, `expired` or `stopped`; null when not on a trial.
    status: str | None = None
    ends_at: datetime | None = None
    days_remaining: int | None = None
    #: The free test-call minutes, used and left. Null on a trial with no minutes cap.
    free_minutes: int | None = None
    minutes_used: int = 0
    minutes_left: int | None = None
    calls_today: int = 0
    daily_cap: int = 0
    #: The longest one test call may run, in seconds.
    max_call_seconds: int = 0
    #: Whether the no-cold-calls pledge is accepted; a test call needs it.
    pledge_accepted: bool = False
    #: Whether a test call can be placed now, and the sentence that says why not.
    can_call: bool = False
    blocked_reason: str | None = None
    #: Why an agent that only answers calls cannot be switched on to take them during the
    #: trial, for the line beside its locked "Taking calls" switch (D-853). The same
    #: sentence `publish_agent` refuses with, so the screen and the refusal cannot differ.
    answering_locked_reason: str | None = None


async def read_trial_panel(session: AsyncSession, *, tenant_id: UUID) -> TrialPanelOut:
    """This tenant's trial panel; one indexed read when the account is not on a trial."""
    now = datetime.now(UTC)
    access = await read_trial_access(session, tenant_id=tenant_id, at=now)
    if access is None:
        return await _paid_panel(session, tenant_id=tenant_id, at=now)
    unpledged = await pledge_blocker(session, tenant_id=tenant_id)
    blocked = access.blocker
    reason: str | None = None
    if not trial_calling_ready():
        reason = NOT_READY_REASON
    elif blocked is not None:
        reason = blocked[1]
    elif unpledged is not None:
        reason = unpledged[1]
    return TrialPanelOut(
        on_trial=True,
        status=access.trial.status,
        ends_at=access.trial.ends_at,
        days_remaining=access.trial.days_remaining(at=now),
        free_minutes=access.trial.free_minutes,
        minutes_used=access.minutes_used,
        minutes_left=access.minutes_left,
        calls_today=access.calls_today,
        daily_cap=access.daily_cap,
        max_call_seconds=access.call_seconds,
        pledge_accepted=unpledged is None,
        can_call=reason is None,
        blocked_reason=reason,
        answering_locked_reason=TRIAL_REFUSALS["inbound"][1],
    )


async def _paid_panel(session: AsyncSession, *, tenant_id: UUID, at: datetime) -> TrialPanelOut:
    """A paid account's test calls (D-859), or the empty panel for an account that has
    neither paid nor a trial."""
    paid = await read_paid_test_access(session, tenant_id=tenant_id, at=at)
    if paid is None or get_settings().engine not in TRIAL_CALL_ENGINES:
        return TrialPanelOut(on_trial=False)
    unpledged = await pledge_blocker(session, tenant_id=tenant_id)
    reason: str | None = None
    if paid.blocker is not None:
        reason = paid.blocker[1]
    elif unpledged is not None:
        reason = unpledged[1]
    return TrialPanelOut(
        on_trial=False,
        paid_test_calls=True,
        calls_today=paid.calls_today,
        daily_cap=paid.daily_cap,
        max_call_seconds=paid.max_call_seconds,
        pledge_accepted=unpledged is None,
        can_call=reason is None,
        blocked_reason=reason,
    )


__all__ = ["TrialPanelOut", "read_trial_panel"]
