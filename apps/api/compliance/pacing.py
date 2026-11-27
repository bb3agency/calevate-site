"""How often one person may be rung by one account (D-1046).

Two limits, both counted from `calls` rather than from a table of their own, because a call
row is the one record every dial path already writes before the phone can ring
(`agents.service.dispatch_call`'s intent row):

* **Calls to one person in 24 hours** (`person_daily_call_cap`, default 3). Asked by the dial
  gate (`compliance.service.check_dispatch`) on every outbound path: campaigns, a new lead's
  first call, call-backs, follow-ups, Make a call, Pip's calls. Rolling rather than per IST
  day, so a person rung three times at 8 PM is not rung three more at 9 AM. Transient: it
  lifts when the oldest of those calls is 24 hours old, and the refusal carries that instant
  so a campaign contact waits exactly that long instead of being settled.
* **Skip people another campaign reached recently** (`campaigns.skip_recent_days`, default 7,
  NULL = off). Asked by the campaign dispatcher only, because it is the campaign's setting:
  a call that reached the person from anywhere but this campaign in the last N days holds
  the contact until N days after that call. The campaign's own earlier tries do not count,
  or its retry ladder would hold itself.

Both are per account. RLS scopes the read to the tenant, and the tenant id is in the WHERE
clause as well so the index's leading column is used; one account never learns how often
another rang a number.

What counts. A dial with a `not_placed_reason` proved nothing rang (`calevate_shared.events`),
so it is not counted by either, as the daily test-call caps do not count one. Inbound calls are
never counted. For the campaign skip, an attempt nobody answered (`no_answer`, `busy`,
`voicemail`) is not "reached": otherwise a "call the people we did not reach" duplicate of a
campaign would wait a week to call anyone, and unanswered rings are bounded by the 24-hour
cap already. Test calls are not counted for the skip either: an owner who rang their own
number to hear the agent is not then skipped by their own campaign.

A race this does not close: two dials to one number gated in the same instant by two
processes both see the same count, because the gate's read and the dial's intent row are
separate transactions. The dispatcher claims a campaign's contacts under one lease, so the
race needs two different paths ringing one person within the same second; the cost is one
call over the cap, never an unbounded run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from calevate_shared.calling_window import DEFAULT_WINDOW, IST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: The rolling window the per-person cap counts over.
PERSON_PACING_WINDOW: Final = timedelta(hours=24)

#: The campaign dispatcher's refusal for a contact another campaign reached recently.
RECENTLY_CALLED_RULE: Final = "recently_called"
#: A new campaign skips people reached in the last week; an owner may pick 1 to 30 days or off.
RECENT_SKIP_DEFAULT_DAYS: Final = 7
RECENT_SKIP_MIN_DAYS: Final = 1
RECENT_SKIP_MAX_DAYS: Final = 30

#: Outbound calls to one number in the window, newest first. Served by
#: `ix_calls_outbound_to_person` (tenant, number, created_at; outbound only).
_PERSON_CALLS_SQL: Final = text(
    "SELECT created_at FROM calls WHERE tenant_id = :tid AND to_e164 = :phone "
    "AND direction = 'outbound' AND not_placed_reason IS NULL "
    "AND created_at > now() - make_interval(secs => :window) "
    "ORDER BY created_at DESC LIMIT :cap"
)

#: A call that reached (or may have reached) the person: placed, and not one of the endings
#: that say nobody picked up.
_REACHED: Final = (
    "c.direction = 'outbound' AND c.not_placed_reason IS NULL "
    "AND c.status NOT IN ('no_answer', 'busy', 'voicemail') "
    "AND NOT c.trial_call AND NOT c.paid_test_call "
    "AND c.campaign_id IS DISTINCT FROM :cid "
    "AND c.created_at > now() - make_interval(days => :days)"
)

_LAST_REACHED_SQL: Final = text(
    "SELECT max(c.created_at) FROM calls c WHERE c.tenant_id = :tid AND c.to_e164 = :phone "
    f"AND {_REACHED}"
)

#: Contacts of one campaign still to be called whom the skip would hold now.
_WAITING_SQL: Final = text(
    "SELECT count(*) FROM campaign_contacts cc WHERE cc.campaign_id = :cid "
    "AND cc.status = 'pending' AND cc.included AND EXISTS ("
    "  SELECT 1 FROM calls c WHERE c.tenant_id = cc.tenant_id AND c.to_e164 = cc.phone_e164 "
    f"  AND {_REACHED})"
)


async def person_pacing_opens_at(
    session: AsyncSession, *, tenant_id: UUID, phone_e164: str, cap: int
) -> datetime | None:
    """When this person may be rung again, or None when the account is under its cap.

    With `cap` calls in the window, the next call waits until the oldest of them is 24 hours
    old, which is the moment the count drops back under the cap."""
    rows = (
        await session.execute(
            _PERSON_CALLS_SQL,
            {
                "tid": tenant_id,
                "phone": phone_e164,
                "window": PERSON_PACING_WINDOW.total_seconds(),
                "cap": cap,
            },
        )
    ).all()
    if len(rows) < cap:
        return None
    oldest: datetime = rows[-1][0]
    return oldest + PERSON_PACING_WINDOW


async def recently_called_opens_at(
    session: AsyncSession, *, tenant_id: UUID, phone_e164: str, campaign_id: UUID, days: int
) -> datetime | None:
    """When a campaign skipping people reached in the last `days` may ring this person, or
    None when nothing outside the campaign reached them in that time."""
    last = (
        await session.execute(
            _LAST_REACHED_SQL,
            {"tid": tenant_id, "phone": phone_e164, "cid": campaign_id, "days": days},
        )
    ).scalar()
    if last is None:
        return None
    opens: datetime = last + timedelta(days=days)
    return opens


async def recently_called_waiting(session: AsyncSession, *, campaign_id: UUID, days: int) -> int:
    """How many of the campaign's people still to call the skip holds right now."""
    count = (await session.execute(_WAITING_SQL, {"cid": campaign_id, "days": days})).scalar_one()
    return int(count)


def next_callable_instant(at: datetime) -> datetime:
    """`at`, or the next opening of the 09:00-21:00 IST window after it, in IST.

    The time an owner is told they can call again has to be one the calling-hours check will
    then allow; a limit that lifts at 10 PM lifts, for them, at 9 AM."""
    local = at.astimezone(IST)
    start, end = DEFAULT_WINDOW
    if local.time() < start:
        return datetime.combine(local.date(), start, tzinfo=IST)
    if local.time() >= end:
        return datetime.combine(local.date() + timedelta(days=1), start, tzinfo=IST)
    return local


def _clock(at: datetime) -> str:
    hour = at.hour % 12 or 12
    meridiem = "AM" if at.hour < 12 else "PM"
    return f"{hour}:{at:%M} {meridiem}"


def when_text(at: datetime, *, now: datetime | None = None) -> str:
    """When, in IST: "at 4:10 PM", "tomorrow at 9:00 AM" or "on 3 Dec at 9:00 AM"."""
    local = next_callable_instant(at)
    today = (now or datetime.now(UTC)).astimezone(IST).date()
    if local.date() == today:
        return f"at {_clock(local)}"
    if local.date() == today + timedelta(days=1):
        return f"tomorrow at {_clock(local)}"
    return f"on {local.day} {local:%b} at {_clock(local)}"


def pacing_reason(cap: int, opens_at: datetime, *, now: datetime | None = None) -> str:
    """The owner's sentence for the per-person cap."""
    times = "once" if cap == 1 else "twice" if cap == 2 else f"{cap} times"
    return f"Called {times} in the last 24 hours. Can call again {when_text(opens_at, now=now)}."


__all__ = [
    "PERSON_PACING_WINDOW",
    "RECENTLY_CALLED_RULE",
    "RECENT_SKIP_DEFAULT_DAYS",
    "RECENT_SKIP_MAX_DAYS",
    "RECENT_SKIP_MIN_DAYS",
    "next_callable_instant",
    "pacing_reason",
    "person_pacing_opens_at",
    "recently_called_opens_at",
    "recently_called_waiting",
    "when_text",
]
