"""Scheduled campaign starts — `campaigns.schedule`, and the only code that reads it.

A client says "start this campaign on Monday at 10am", or "every Tuesday at 10am".
Before this module the column existed and nothing wrote or read it
(`check_wiring.UNWIRED_BASELINE`), so the only way to start a campaign was to be at a
keyboard at the moment it should start.

Five decisions shape everything below. They are here rather than scattered through the
functions because each one is a place a plausible alternative is wrong.

**1. TWO KINDS, ONE COLUMN, ONE MEANING OF "NEXT".**
`schedule` holds `{"kind": "one_time", "start_at": "<UTC ISO-8601>"}` or
`{"kind": "recurring", "start_at": "<UTC ISO-8601 of the NEXT occurrence>", "rule":
{"days": [1-7 ISO weekdays], "at": "HH:MM IST"}, "until": ...}`, and `_parse_schedule`
still REFUSES any other `kind` rather than guessing. The recurring shape deliberately
reuses the `start_at` KEY for its next occurrence, which is what lets `dispatch_scan()`
(migration c7e4b19d3f52) keep screening tenants with the predicate it already has —
recurrence owes no migration, only this module's reader.

The rule is WEEKDAY + TIME, not RRULE and not day-of-month, and that is a bound rather
than a stepping stone. "Every Tuesday at 10am" has no month-end ambiguity: walking
forward in IST wall-clock days crosses months and years without a special case. "The
31st of every month" does not exist in four months a year, and RFC 5545 §3.3.10's
BYMONTHDAY leaves the answer to the implementation (skip vs clamp), so the same rule
means different things in different calendars. A recurrence a client cannot predict is a
recurrence that dials when they did not expect it, and the whole product is phone calls
to strangers. Daily is `days` = all seven; there is no second discriminator for it.

**2. A MISSED OCCURRENCE IS SKIPPED, NEVER CAUGHT UP.**
An occurrence fires only inside `RECURRENCE_CATCHUP` of its own instant. Past that the
occurrence is abandoned — audited, alerted, and the schedule advances to the next FUTURE
occurrence rather than the next one after the one we missed. The alternative (fire what
was missed) is what a naive queue does and it is a compliance incident: a worker down
from Monday to Wednesday would, on recovery, launch Monday's, Tuesday's and Wednesday's
occurrences within one minute of each other, tripling the dial volume into one window
and placing calls at a time of day nobody chose. Kubernetes' CronJob makes exactly this
call with `startingDeadlineSeconds` (miss the deadline, count it missed, do not run),
and cron itself has never caught up either; the established answer is the right one
here, and the reason is stronger for us than for either of them because our jobs ring
strangers' phones.

The same bound answers "skip if the previous run is still going" without a second
mechanism: a run that overruns leaves the campaign `running`, so nothing is due until it
finishes and re-arms (`complete_or_rearm`), and the occurrence it slept through is by
then outside its catch-up window and is skipped by the rule above. A PAUSED campaign
behaves the same way and deliberately so — `due_schedules` reads `scheduled` only, so a
paused repeat fires nothing at all (which is what pause means), and the occurrence it
sat through is recorded as skipped the first time the campaign is `scheduled` again.

`RECURRENCE_CATCHUP` is deliberately much shorter than the one-time `GRACE`, and the
asymmetry is the point: a one-time start that never happens is a start the client loses
entirely, so it is worth retrying for a day; a recurring occurrence that never happens
is followed by another one, so retrying it into a different time of day buys nothing and
costs the client's trust in what the screen says.

**3. THE COMPLIANCE GATE RUNS AT FIRE TIME, and it is the SAME gate.**
`fire_schedule` calls `campaigns.service.launch_campaign`, the identical function the
`POST /launch` button calls, which begins by calling `launch_blockers`. Nothing is
skipped and there is no scheduled-launch variant of the gate (hard rule 5).

Scheduling itself runs NO gate, on purpose. A client scheduling Monday's campaign on
Friday may still be waiting for the registrar to approve their voice template; refusing
to accept the date would be refusing today for a condition Monday will have fixed. And
the converse is the real argument: a gate passed on Friday proves nothing about Monday.
Between the two, a number can join the DNC list, a spend cap can trip, a KYC can expire,
a PE registration can be suspended, and the platform halt can go on. A gate at
schedule time only would be a bypass wearing a clock.

The client is not left guessing in the meantime: `GET /launch-check` is unchanged and
answers "would this launch right now" for a scheduled campaign exactly as it does for a
draft, because `launch_blockers` already accepts both statuses.

**4. STARTING IS NOT DIALLING, so a 22:00 ONE-TIME start is accepted and dials at 09:00
— and a 22:00 RECURRENCE is refused outright.**
`calling_hours` is a per-day window enforced PER DIAL under TRAI; a schedule is a START.
Refusing a 22:00 one-time start would be refusing a perfectly lawful intent ("have it
ready to go first thing"), and firing it into a dial would be the TRAI violation. So a
fired one-time schedule does exactly what `POST /launch` at 22:00 does today — the
campaign becomes `running` and dials nothing until the window opens. `launch_blockers`
already states this as settled: "a campaign launched at 22:00 to dial tomorrow morning is
correct, not blocked". What the client gets instead of a refusal is the truth:
`first_dial_not_before` is returned by the schedule endpoint, so a 22:00 start says on
screen that dialling begins at 09:00 the next morning.

A RECURRENCE is refused if its time of day is outside the PLATFORM window (R-11's
mitigation, `DEFAULT_WINDOW`), and the difference is not inconsistency. A one-time start
is a one-off intent a client can hold in their head; a recurrence is a STANDING
instruction that has to be readable on a screen for weeks — "every day at 22:00", quietly
reinterpreted as "every day at 09:00 the next morning", is a schedule the client cannot
predict and would not have written. Refusing at creation, with the window named, is the
only answer that keeps "next: Tuesday 14 Aug, 10:00 IST" a true sentence for every
occurrence. The platform window is a constant, so this refusal makes "an occurrence
outside calling hours" unreachable at fire time rather than something the tick has to
decide about.

The campaign's OWN narrowed `calling_hours` is not part of that refusal: it is a
narrowing the client chose, it can be narrower than any sensible start time, and the
existing defer-within-window answer covers it — `first_dial_not_before` is returned for
the next occurrence too, so a 10:00 recurrence on a 12:00-14:00 campaign says 12:00 on
screen.

**5. IST AT THE EDGE, UTC IN THE DB — and a naive datetime is REFUSED, not assumed.**
Elsewhere in this package (`_validated_provenance`) a naive datetime is pinned to UTC.
That is right there and wrong here. Provenance records something that already happened,
so a mis-assumed zone is a wrong log line; a schedule decides when a phone rings, so a
"10:00" read as UTC rings a household at 15:30 IST — or, at the other end of the window,
at 02:30. The wire model is `AwareDatetime` so the generated TypeScript client cannot
send a bare local string, and `schedule_campaign` refuses one again for callers that are
not HTTP requests.

ONE MORE THING WORTH KNOWING BEFORE READING `_fire_recurrence`
--------------------------------------------------------------------------------------
**The OCCURRENCE, not the wall clock, is what makes a recurrence idempotent — and the
same claim is what makes it stoppable.** `_claim_occurrence` takes a row lock with the
occurrence instant in its WHERE clause, so the two ticks the lease deliberately allows
(`campaign_dispatch._tick_lease` fails open on a Redis error) contend on the identity of
the occurrence rather than on "is it after 10:00": the loser re-reads a row whose
`start_at` has already advanced, does not match, and stops without calling the gate.

That claim is also why STOPPING a recurrence takes effect before the next tick rather
than one tick later. The tick reads the due set in one transaction and fires in another,
so a client pressing "stop repeating" in between must not be overtaken by the read that
came first — the claim re-checks the column under the lock, finds it cleared, and the
occurrence does not fire. Same doctrine as DNC propagation: the enforcement is a read at
the moment of acting, never a snapshot taken earlier.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.service import launch_campaign
from apps.api.compliance.service import DEFAULT_WINDOW, IST
from apps.api.core.alerting import alert, record_compliance_block
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of

log = get_logger(__name__)

# The two `kind`s this module will fire. See decision 1 in the module docstring; anything
# else is refused rather than guessed at.
ONE_TIME = "one_time"
RECURRING = "recurring"

# How far ahead a start may be set. Not a compliance rule — a typo bound. The failure it
# catches is the year field ("2027-08-17" for next Monday), and the reason it matters is
# that everything the gate will check at fire time is being assembled TODAY: a list whose
# consent was collected this week, a template approved this month. A campaign that fires
# from paperwork nobody remembers assembling is a compliance surprise even when every
# blocker happens to be green.
MAX_HORIZON = timedelta(days=180)

# How long past its start time a schedule keeps trying before it is given up on.
#
# The alternative shapes were both worse. Firing forever means a campaign scheduled for
# Monday 10:00 and blocked by a spend cap starts itself on Thursday afternoon, which is
# not what "Monday 10:00" meant and is the one outcome nobody can explain to a client.
# Failing on the first blocked tick means a template the registrar approves twenty
# minutes later has already lost its start. A day is long enough for a client to fix a
# paperwork gap the same working day and short enough that the start still means what
# they picked.
GRACE = timedelta(hours=24)

# How late ONE OCCURRENCE of a recurrence may fire. See decision 2: past this the
# occurrence is skipped, never caught up, and the schedule advances to the next FUTURE
# one. An hour is chosen against three facts rather than by feel: the tick runs every 30
# seconds, so under normal operation an occurrence fires inside one tick and this window
# is never approached; a worker restart or a deploy is minutes, not hours, so the window
# covers the failures that actually happen; and an hour is shorter than the shortest
# interval this module can express (daily), so two occurrences of the same campaign can
# never be inside their catch-up windows at the same moment. Longer than this and
# "10:00 every Tuesday" starts dialling at lunchtime, which is a different promise.
RECURRENCE_CATCHUP = timedelta(hours=1)

# ISO weekday numbers, Monday = 1, as `datetime.isoweekday()` returns them. The wire
# model, the rule and the UI all speak this one vocabulary — a second numbering (0-based,
# or Sunday-first) is an off-by-one that dials on the wrong day.
_ISO_WEEKDAYS = range(1, 8)

_SCHEDULE_PAST = "campaign_schedule_in_past"
_SCHEDULE_NAIVE = "campaign_schedule_timezone_missing"
_SCHEDULE_TOO_FAR = "campaign_schedule_too_far"
_RECURRENCE_NO_DAYS = "campaign_recurrence_no_days"
_RECURRENCE_BAD_DAY = "campaign_recurrence_day_out_of_range"
_RECURRENCE_OUTSIDE_HOURS = "campaign_recurrence_outside_calling_hours"
_RECURRENCE_ENDS_TOO_SOON = "campaign_recurrence_ends_before_it_starts"
_RECURRENCE_ENDS_TOO_FAR = "campaign_recurrence_end_too_far"


@dataclass(frozen=True, slots=True)
class ScheduledStart:
    """What the client gets back — and the second field is the point of the first.

    `first_dial_not_before` is when this campaign can actually place its first call:
    the start time itself if it lands inside the calling window, otherwise the next
    opening of that window. A schedule screen that showed only `start_at` would let a
    client pick 22:00, see 22:00 echoed back, and conclude we dial at 22:00.
    """

    start_at: datetime
    first_dial_not_before: datetime


@dataclass(frozen=True, slots=True)
class Recurrence:
    """Every Tuesday at 10am, as the only two things that sentence contains.

    `days` are ISO weekday numbers and `at` is an IST wall-clock time — deliberately not
    an instant, because "10am" is what the client meant and an instant would freeze one
    particular Tuesday's 10am. India has no DST, so the fixed `IST` offset the rest of
    this repo uses converts the two exactly; a `ZoneInfo` here would be a second spelling
    of the same thing that agrees with the first (see `first_dial_not_before`).
    """

    days: tuple[int, ...]
    at: time
    until: datetime | None

    def next_after(self, moment: datetime) -> datetime | None:
        """The first occurrence STRICTLY after `moment`, or None once `until` has passed.

        Strictly after, because this is called with the occurrence just fired: an
        inclusive comparison would return the same instant and the recurrence would
        never advance. Walks IST wall-clock days rather than adding a fixed interval, so
        month and year boundaries need no special case and a rule that names four
        weekdays is the same walk as one that names one.
        """
        moment_ist = moment.astimezone(UTC) + IST
        # Eight days covers today plus a full week, so a non-empty `days` always matches:
        # the only way today's slot is missed is that its time has already passed, and
        # then the same weekday seven days later is in range.
        for offset in range(8):
            day_ist = moment_ist + timedelta(days=offset)
            if day_ist.isoweekday() not in self.days:
                continue
            candidate_ist = day_ist.replace(
                hour=self.at.hour, minute=self.at.minute, second=0, microsecond=0
            )
            if candidate_ist <= moment_ist:
                continue
            candidate = candidate_ist - IST
            if self.until is not None and candidate > self.until:
                return None
            return candidate
        return None  # pragma: no cover - unreachable while `days` is validated non-empty


@dataclass(frozen=True, slots=True)
class ScheduledRecurrence:
    """What the client gets back when they set a repeat, and what the screen renders.

    `next_occurrence_at` and `first_dial_not_before` are both here for the reason
    `ScheduledStart` carries two fields: they differ whenever the campaign narrowed its
    own calling hours, and a screen that showed only the first would promise a dial at a
    time this campaign will not dial at.
    """

    days: tuple[int, ...]
    at: time
    until: datetime | None
    next_occurrence_at: datetime
    first_dial_not_before: datetime


@dataclass(frozen=True, slots=True)
class CancelledSchedule:
    """What was stopped, and what the campaign is now.

    `kind` so the audit row can say WHICH promise was cancelled — "we stopped a weekly
    repeat" and "we cancelled Monday's start" are different facts to answer for later.
    `status` because stopping a repeat on a RUNNING campaign leaves it running, and a
    route that answered "draft" for every cancellation would be reporting a state
    transition that did not happen.
    """

    kind: str
    status: str


@dataclass(frozen=True, slots=True)
class DueSchedule:
    """One occurrence that has come due.

    `start_at` is THE OCCURRENCE INSTANT for both kinds — for a one-time schedule it is
    the start the client picked, for a recurrence it is this occurrence's slot. It is
    the identity the whole fire path is idempotent on.

    `occurrence_key` is that instant as it is SPELLED IN THE COLUMN, and it is a separate
    field on purpose: `_claim_occurrence` compares text, so it must compare the bytes it
    read rather than a re-serialization of them. A round trip through `datetime` is
    lossless for everything this module writes and is not guaranteed to be for anything
    else, and the claim's failure mode has to be "somebody else moved this schedule",
    never "we formatted it differently this time".
    """

    campaign_id: UUID
    start_at: datetime
    recurrence: Recurrence | None = None
    occurrence_key: str = ""


def _require_aware(start_at: datetime) -> datetime:
    """Decision 5: a schedule with no timezone is refused, never guessed at."""
    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise ProblemError(
            kind="validation",
            code=_SCHEDULE_NAIVE,
            title="Start time has no timezone",
            detail=(
                "A campaign start must carry its timezone offset (for example "
                "2026-08-17T10:00:00+05:30 for 10am IST). Without one we would have to "
                "guess which hour you meant, and the guess decides when a phone rings."
            ),
            fields=[
                {
                    "field": "start_at",
                    "rule": "timezone_required",
                    "message": "include the +05:30 offset",
                }
            ],
        )
    return start_at.astimezone(UTC)


def _window_for(calling_hours: dict[str, Any] | None) -> tuple[time, time]:
    """The campaign's effective window: its own if it narrowed, else the platform's.

    Intersected with the platform window rather than trusted: `create_campaign` refuses
    a wider one, so this can only ever be a no-op — but this function's answer is shown
    to a client as a promise about when we will dial, and a promise derived from a
    column is worth re-bounding against the law it is supposed to sit inside.
    """
    platform_start, platform_end = DEFAULT_WINDOW
    if not calling_hours:
        return platform_start, platform_end
    try:
        start = datetime.strptime(str(calling_hours["start"]), "%H:%M").time()
        end = datetime.strptime(str(calling_hours["end"]), "%H:%M").time()
    except (KeyError, TypeError, ValueError):
        # Unreadable window: the dispatcher fails closed on this too
        # (`campaign_window_open`), so the honest answer here is the narrowest one.
        return platform_start, platform_end
    return max(start, platform_start), min(end, platform_end)


def first_dial_not_before(
    start_at: datetime, calling_hours: dict[str, Any] | None = None
) -> datetime:
    """When this campaign can place its first call, given a UTC start instant.

    IST at the edge: the window is expressed in IST clock time, so the start is shifted
    into IST, compared there, and shifted back. `+ IST` rather than a `ZoneInfo`
    localization is the convention `compliance.service.ist_now` established — India has
    no DST, so a fixed offset is exact, and one spelling of "IST" across the repo is
    worth more than a second mechanism that agrees with it.
    """
    window_start, window_end = _window_for(calling_hours)
    start_ist = start_at.astimezone(UTC) + IST
    if start_ist.time() < window_start:
        opens_ist = start_ist.replace(
            hour=window_start.hour, minute=window_start.minute, second=0, microsecond=0
        )
    elif start_ist.time() > window_end:
        opens_ist = (start_ist + timedelta(days=1)).replace(
            hour=window_start.hour, minute=window_start.minute, second=0, microsecond=0
        )
    else:
        return start_at.astimezone(UTC)
    return opens_ist - IST


async def schedule_campaign(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID, start_at: datetime
) -> ScheduledStart:
    """Set a one-time start and move the campaign `draft`/`scheduled` → `scheduled`.

    Re-scheduling an already-scheduled campaign is allowed and is the same call: the
    client changed their mind about the date, which is not a state-machine violation.
    Anything past `scheduled` is refused — a running campaign is started, and a
    completed one cannot be un-completed by putting a date on it.

    NO GATE HERE, by design — see decision 3 in the module docstring.
    """
    start = _require_aware(start_at)
    now = datetime.now(UTC)
    if start <= now:
        raise ProblemError(
            kind="validation",
            code=_SCHEDULE_PAST,
            title="Start time is in the past",
            detail=(
                "A campaign can only be scheduled to start in the future. To start it "
                "now, launch it."
            ),
        )
    if start > now + MAX_HORIZON:
        raise ProblemError(
            kind="validation",
            code=_SCHEDULE_TOO_FAR,
            title="Start time is too far ahead",
            detail=(
                f"A campaign can be scheduled up to {MAX_HORIZON.days} days ahead. A "
                "date further out than that is nearly always a typo, and the consent, "
                "template and registration this campaign relies on are being checked "
                "today."
            ),
        )

    payload = {"kind": ONE_TIME, "start_at": start.isoformat()}
    # CAS (BACKEND-PATTERNS §5): the guard is in the WHERE clause, so a campaign that
    # launched a moment ago cannot have a start date written onto it. `schedule` is
    # replaced wholesale rather than merged — `last_blocked` from a previous attempt
    # describes a start that is no longer the start.
    result = await session.execute(
        text(
            "UPDATE campaigns SET schedule = CAST(:sched AS jsonb), status = 'scheduled', "
            "updated_at = now() WHERE id = :cid AND tenant_id = :tid "
            "AND status IN ('draft', 'scheduled') "
            "RETURNING calling_hours"
        ),
        {"sched": json.dumps(payload), "cid": campaign_id, "tid": tenant_id},
    )
    row = result.first()
    if row is None:
        raise await _why_not_schedulable(session, campaign_id)
    return ScheduledStart(
        start_at=start, first_dial_not_before=first_dial_not_before(start, row[0])
    )


def _validated_rule(days: Sequence[int], at: time, until: datetime | None) -> Recurrence:
    """The client's repeat, checked before it can become a standing instruction.

    Every refusal here is one a client can act on in the form, and each is a rule the
    fire path would otherwise have to carry forever: an empty day list is a schedule that
    never fires (and would sit on screen saying "repeats" for weeks), and a time outside
    the platform's calling window is decision 4's refusal.
    """
    unique = tuple(sorted(set(days)))
    if not unique:
        raise ProblemError(
            kind="validation",
            code=_RECURRENCE_NO_DAYS,
            title="Pick at least one day",
            detail="A repeating campaign needs at least one day of the week to repeat on.",
            fields=[{"field": "days", "rule": "required", "message": "choose one or more days"}],
        )
    if any(day not in _ISO_WEEKDAYS for day in unique):
        raise ProblemError(
            kind="validation",
            code=_RECURRENCE_BAD_DAY,
            title="That is not a day of the week",
            detail="Days are 1 (Monday) to 7 (Sunday).",
            fields=[{"field": "days", "rule": "range", "message": "1 (Monday) to 7 (Sunday)"}],
        )

    window_start, window_end = DEFAULT_WINDOW
    if not window_start <= at <= window_end:
        raise ProblemError(
            kind="validation",
            code=_RECURRENCE_OUTSIDE_HOURS,
            title="That time is outside calling hours",
            detail=(
                f"Calls may only be placed between {window_start:%H:%M} and "
                f"{window_end:%H:%M} IST, so a campaign that repeats at {at:%H:%M} would "
                "never dial at the time it says. Pick a time inside those hours."
            ),
            fields=[
                {
                    "field": "at",
                    "rule": "calling_hours",
                    "message": f"between {window_start:%H:%M} and {window_end:%H:%M} IST",
                }
            ],
        )

    end = _require_aware(until) if until is not None else None
    if end is not None and end > datetime.now(UTC) + MAX_HORIZON:
        raise ProblemError(
            kind="validation",
            code=_RECURRENCE_ENDS_TOO_FAR,
            title="That end date is too far ahead",
            detail=(
                f"A repeat can be set to end up to {MAX_HORIZON.days} days out. Leave the "
                "end date empty for a repeat that runs until you stop it."
            ),
        )
    return Recurrence(days=unique, at=at, until=end)


async def schedule_recurrence(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    days: Sequence[int],
    at: time,
    until: datetime | None = None,
) -> ScheduledRecurrence:
    """Set a repeat and move the campaign `draft`/`scheduled` → `scheduled`.

    Same states in and out as `schedule_campaign`, and the same CAS, because this IS that
    function's other kind: the column holds one schedule, so setting a repeat on a
    campaign that had a one-time start REPLACES it rather than accumulating a second
    promise the client cannot see. Anything past `scheduled` is refused for the reason
    the one-time path refuses it — a running campaign has already started, and the repeat
    it would need is a decision about a campaign that is currently dialling.

    NO GATE HERE either, and the argument is decision 3's, only stronger: a repeat set
    today makes its claim about a Tuesday six weeks out. `fire_schedule` runs the gate on
    EVERY occurrence.
    """
    rule = _validated_rule(days, at, until)
    first = rule.next_after(datetime.now(UTC))
    if first is None:
        raise ProblemError(
            kind="validation",
            code=_RECURRENCE_ENDS_TOO_SOON,
            title="This repeat would never run",
            detail=(
                "The end date is before the first time this campaign would repeat. Pick a "
                "later end date, or a day that comes sooner."
            ),
        )

    payload = _recurrence_payload(rule, next_at=first)
    # The same wholesale replacement and the same WHERE-clause guard as the one-time
    # path: `last_blocked` and `last_skipped` from a previous rule describe occurrences
    # that are no longer this schedule's.
    result = await session.execute(
        text(
            "UPDATE campaigns SET schedule = CAST(:sched AS jsonb), status = 'scheduled', "
            "updated_at = now() WHERE id = :cid AND tenant_id = :tid "
            "AND status IN ('draft', 'scheduled') "
            "RETURNING calling_hours"
        ),
        {"sched": json.dumps(payload), "cid": campaign_id, "tid": tenant_id},
    )
    row = result.first()
    if row is None:
        raise await _why_not_schedulable(session, campaign_id)
    return ScheduledRecurrence(
        days=rule.days,
        at=rule.at,
        until=rule.until,
        next_occurrence_at=first,
        first_dial_not_before=first_dial_not_before(first, row[0]),
    )


def _recurrence_payload(rule: Recurrence, *, next_at: datetime) -> dict[str, Any]:
    """The stored shape. `start_at` is the NEXT occurrence — see decision 1 for why that
    key is reused rather than named `next_at`: `dispatch_scan()` already screens on it."""
    return {
        "kind": RECURRING,
        "start_at": next_at.isoformat(),
        "rule": {"days": list(rule.days), "at": f"{rule.at:%H:%M}"},
        "until": rule.until.isoformat() if rule.until else None,
    }


async def unschedule_campaign(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> CancelledSchedule:
    """ONE stop button for both kinds: the column goes back to NULL.

    A campaign that was WAITING (`scheduled`) goes back to `draft` — not to a third "was
    scheduled" state, because that is what it now is: a campaign nobody has started,
    editable again (contacts, provenance) by exactly the rules that govern any other
    draft. **A campaign that is RUNNING keeps running**, and that is the case recurrence
    added: stopping a repeat means "do not start this again", never "abandon the calls
    currently going out". Cancelling those is what pause is for, and silently doing it
    here would be a stop button with a second, unadvertised effect.

    Keyed on `schedule IS NOT NULL` rather than on a status, because "is there a promise
    to cancel" is the question, and after recurrence the answer no longer implies a
    status. Stopping is what makes a recurrence stoppable BEFORE the next tick: the tick
    re-reads this column under a row lock at the moment it fires (`_claim_occurrence`),
    so a cleared schedule stops the very next occurrence rather than the one after it.
    """
    # `FROM campaigns before` is the standard way to RETURN a value the same statement is
    # about to destroy: `RETURNING` sees the NEW row, so `schedule->>'kind'` there is
    # always NULL. The joined row is read from the statement's snapshot, i.e. the schedule
    # as it was, which is the one the audit line has to name. A separate SELECT would be
    # two observations of a column another tick can advance between them.
    row = (
        await session.execute(
            text(
                "UPDATE campaigns c SET schedule = NULL, "
                "  status = CASE WHEN c.status = 'scheduled' THEN 'draft' ELSE c.status END, "
                "  updated_at = now() "
                "FROM campaigns before WHERE before.id = c.id "
                "AND c.id = :cid AND c.tenant_id = :tid AND c.schedule IS NOT NULL "
                "RETURNING c.status, before.schedule->>'kind'"
            ),
            {"cid": campaign_id, "tid": tenant_id},
        )
    ).first()
    if row is None:
        raise await _why_not_schedulable(session, campaign_id, unscheduling=True)
    return CancelledSchedule(kind=str(row[1] or ONE_TIME), status=str(row[0]))


async def _why_not_schedulable(
    session: AsyncSession, campaign_id: UUID, *, unscheduling: bool = False
) -> ProblemError:
    """Zero rows is two different facts, and a client fixes only one of them.

    Returns the error rather than raising it, so the caller's `raise` is visible at the
    call site (the same shape `declare_consent_provenance` reaches for, one level up).
    """
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    if status is None:
        return ProblemError.not_found("Campaign")
    if unscheduling:
        return ProblemError.business_rule(
            "campaign_not_scheduled",
            f"This campaign is {status} and has no start or repeat to cancel.",
        )
    return ProblemError.business_rule(
        "campaign_not_schedulable",
        f"A {status} campaign cannot be given a start time; only a draft can.",
    )


def _rule_from(raw: object, until_raw: object) -> Recurrence:
    """The stored `rule` → a `Recurrence`. Raises `ValueError` on anything unreadable.

    Pure and loud, so the two callers can differ on what to DO about an unreadable
    repeat: the fire path alerts (something wrote to this column that is not this
    module), the read path renders "no repeat" rather than alerting once per page view.

    The day list is the branch that matters. A rule whose days cannot be read would
    otherwise default to "every day" or "no day", and one of those dials seven times a
    week.
    """
    if not isinstance(raw, dict):
        raise ValueError("rule is not an object")
    days = tuple(sorted({int(day) for day in raw["days"]}))
    at = datetime.strptime(str(raw["at"]), "%H:%M").time()
    if not days or any(day not in _ISO_WEEKDAYS for day in days):
        raise ValueError("rule names no usable weekday")
    until: datetime | None = None
    if until_raw is not None:
        until = datetime.fromisoformat(str(until_raw))
        if until.tzinfo is None:
            raise ValueError("until carries no offset")
        until = until.astimezone(UTC)
    return Recurrence(days=days, at=at, until=until)


def _parse_rule(raw: object, until_raw: object, *, campaign_id: UUID) -> Recurrence | None:
    """`_rule_from`, failing closed with a named campaign, for the fire path."""
    try:
        return _rule_from(raw, until_raw)
    except (KeyError, TypeError, ValueError):
        alert(
            "WORKER_TERMINAL",
            "campaign_recurrence_unreadable",
            detail="schedule.rule is not a usable repeat; campaign not started",
            campaign_id=str(campaign_id),
        )
        return None


def describe_recurrence(raw: object) -> dict[str, Any] | None:
    """The stored repeat as the campaign screen reads it, or None when there is none.

    Lives here rather than in `service.campaign_progress` for the reason the parse does:
    the shape of this column has ONE owner, and a screen that assembled its own reading
    of the JSON would be a second place that decides what a repeat is.

    Returns the NEXT occurrence and the last skip, because those are the two facts a
    client cannot get from the word "scheduled" — "when does this run again" and "why
    did it not run last Tuesday". An unreadable repeat renders as no repeat: the fire
    path alerts about it with the campaign id, and inventing a next occurrence for a rule
    we could not read would be the worse of the two silences.
    """
    if not isinstance(raw, dict) or raw.get("kind") != RECURRING:
        return None
    try:
        rule = _rule_from(raw.get("rule"), raw.get("until"))
        next_at = datetime.fromisoformat(str(raw.get("start_at")))
    except (KeyError, TypeError, ValueError):
        return None
    if next_at.tzinfo is None:
        return None
    skipped = raw.get("last_skipped") if isinstance(raw.get("last_skipped"), dict) else None
    return {
        "days": list(rule.days),
        "at": f"{rule.at:%H:%M}",
        "until": rule.until,
        "next_occurrence_at": next_at.astimezone(UTC),
        "last_skipped_at": (skipped or {}).get("at"),
        "last_skipped_reason": (skipped or {}).get("reason"),
    }


def _parse_instant(raw: object, *, campaign_id: UUID, field: str) -> datetime | None:
    """An ISO-8601 instant WITH an offset, or None with a reason logged.

    `schedule_campaign`/`schedule_recurrence` are the only writers and both serialize an
    aware UTC instant, so every branch below is unreachable by design — which is exactly
    why they alert rather than passing quietly. Something wrote to this column that is
    not this module.
    """
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        alert(
            "WORKER_TERMINAL",
            "campaign_schedule_unparseable",
            detail=f"the schedule's {field} value isn't a valid date and time; campaign not started",
            campaign_id=str(campaign_id),
        )
        return None
    if parsed.tzinfo is None:
        alert(
            "WORKER_TERMINAL",
            "campaign_schedule_unparseable",
            detail=f"the schedule's {field} value has no time zone; campaign not started",
            campaign_id=str(campaign_id),
        )
        return None
    return parsed.astimezone(UTC)


def _parse_schedule(raw: object, *, campaign_id: UUID) -> DueSchedule | None:
    """The stored JSON → the next occurrence and, for a repeat, the rule behind it.

    Returns a `DueSchedule` with the occurrence in `start_at` WITHOUT judging whether it
    has arrived — `due_schedules` compares it to the clock. FAILS CLOSED on everything it
    does not understand, and each branch is a real possibility rather than defensive
    noise:

    - an unknown `kind` is a schedule shape this build has no reader for. Firing it as a
      one-time start is the "half-built recurrence" failure the module docstring refuses
      — a repeating campaign that runs once and looks finished;
    - an unparseable `start_at` cannot be compared to anything (see `_parse_instant`);
    - an unreadable `rule` on a `recurring` schedule would leave us with an occurrence
      and no way to compute the next one, i.e. a campaign that fires once and then stalls
      silently. Refused rather than fired.
    """
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind not in (ONE_TIME, RECURRING):
        alert(
            "WORKER_TERMINAL",
            "campaign_schedule_kind_unknown",
            detail=f"this schedule type ({kind!r}) isn't one Calevate can run; campaign not started",
            campaign_id=str(campaign_id),
        )
        return None
    raw_start = raw.get("start_at")
    occurrence = _parse_instant(raw_start, campaign_id=campaign_id, field="start_at")
    if occurrence is None:
        return None
    recurrence: Recurrence | None = None
    if kind == RECURRING:
        recurrence = _parse_rule(raw.get("rule"), raw.get("until"), campaign_id=campaign_id)
        if recurrence is None:
            return None
    return DueSchedule(
        campaign_id=campaign_id,
        start_at=occurrence,
        recurrence=recurrence,
        occurrence_key=str(raw_start),
    )


async def due_schedules(session: AsyncSession, *, now: datetime) -> list[DueSchedule]:
    """Scheduled campaigns of THIS tenant whose start time has arrived.

    **THIS IS THE AUTHORITY ON WHAT "DUE" MEANS.** `dispatch_scan()`'s `has_due_schedule`
    (migration c7e4b19d3f52) asks a similar question in SQL, and the relationship between
    the two is deliberate and one-directional: the scan is a coarse SCREEN that decides
    whether a tenant is worth a session at all, and it is a proven SUPERSET of this — the
    same relationship `engine_agent_routes` already has with the dispatch tick. Anything
    that makes a schedule un-runnable is decided HERE and nowhere else:

    - `kind`, the discriminator that keeps a schedule shape this build has no reader for
      from being fired once as a one-time start. A WHERE clause could express it, and
      then there would be two places that decide what a schedule is, in a repo where one
      of them is frozen migration history;
    - the offset requirement and the parse, whose failures need to name the campaign in
      an alert. A row silently skipped by a SQL predicate names nothing;
    - the repeat rule, which the SQL screen cannot read at all. That is the asymmetry
      working as intended rather than a gap: the screen answers "is this tenant's next
      occurrence in the past", which is exactly as true for a recurrence as for a
      one-time start BECAUSE the recurring shape stores its next occurrence under the
      same `start_at` key (decision 1). No migration, one predicate, two kinds.

    A screen that is too WIDE costs one tenant session and this function then declines.
    A screen that is too NARROW is a campaign that never starts and never says why, which
    is why the asymmetry is the design rather than an accident of it.

    Reads the tenant's whole (small, bounded) scheduled set rather than filtering in SQL,
    for the same reason: the filter is this function.

    Oldest first, so two campaigns due in the same tick compete for the line pool in a
    deterministic order rather than a planner-dependent one — the rule
    `_TENANT_BUDGET_SQL` already applies to running campaigns.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, schedule FROM campaigns WHERE status = 'scheduled' "
                "AND schedule IS NOT NULL ORDER BY created_at, id"
            )
        )
    ).all()
    due: list[DueSchedule] = []
    for campaign_id, raw in rows:
        parsed = _parse_schedule(raw, campaign_id=UUID(str(campaign_id)))
        if parsed is not None and parsed.start_at <= now:
            due.append(parsed)
    return due


async def fire_schedule(
    session: AsyncSession, *, tenant_id: UUID, due: DueSchedule, now: datetime
) -> str:
    """Start one due campaign. Returns the outcome word the caller counts.

    **THE CALLER OWNS THE TRANSACTION AND MUST GIVE THIS ONE OF ITS OWN PER CAMPAIGN.**
    `launch_campaign` writes (the DNC scrub) before its CAS, so the loser of a race
    between two ticks has writes to roll back; sharing a transaction across campaigns
    would roll back the winners alongside it.

    Outcomes:

    - `fired` — the gate passed, the CAS won, the campaign is `running`;
    - `raced` — the CAS returned zero rows, i.e. another tick (or a human pressing
      Launch) started it first. Fires ONCE is the invariant, and this is the branch that
      proves the invariant held rather than the one that broke it. Not an alert: it is
      the designed outcome of a lease that fails open;
    - `blocked` — the compliance gate refused AT FIRE TIME. Recorded onto the schedule
      so the client's screen can name it, and retried on the next tick until GRACE;
    - `expired` — still blocked GRACE after its start. The schedule is cleared and the
      campaign returns to `draft`, where `/launch-check` names the same blockers and the
      client can act on them;
    - `skipped` — a RECURRING occurrence that came due too late to still mean what it
      said (decision 2). The occurrence is abandoned and the schedule advances.

    A recurrence takes `_fire_recurrence` from here, which runs THE SAME
    `launch_campaign` and therefore THE SAME gate. There is no second path to `running`
    in this module and `tests/campaign_schedule_test.py` asserts there is not.
    """
    if due.recurrence is not None:
        return await _fire_recurrence(
            session, tenant_id=tenant_id, due=due, recurrence=due.recurrence, now=now
        )
    if now > due.start_at + GRACE:
        return await _expire(session, tenant_id=tenant_id, due=due)

    try:
        await launch_campaign(session, tenant_id=tenant_id, campaign_id=due.campaign_id)
    except InvalidStatusTransitionError:
        # Lost the CAS: somebody started this campaign between our read and our write.
        # The caller rolls this transaction back — see the docstring.
        raise
    except ProblemError as exc:
        if exc.code != "campaign_launch_blocked":
            raise
        # A race can arrive HERE rather than at the CAS, and it must not be mistaken for
        # a compliance refusal. If the winner committed before this transaction read the
        # campaign's facts, `launch_blockers` sees `status = running` and reports its own
        # `status` blocker — the gate correctly refusing to launch an already-launched
        # campaign. Counting that as a compliance block would put a phantom
        # `compliance_blocks{rule="status"}` on the dashboard every time two ticks
        # overlapped, and writing it onto the schedule would describe a start that
        # already happened.
        if not await _still_scheduled(session, due.campaign_id):
            return "raced"
        rules = [str(field.get("rule", "")) for field in exc.fields or []]
        for rule in rules:
            record_compliance_block(rule=rule)
        await _record_block(session, campaign_id=due.campaign_id, rules=rules, now=now)
        # Rules and ids only — never a client's wording, never a number (hard rule 6).
        log.warning(
            "campaign_schedule_blocked",
            extra={"campaign_id": str(due.campaign_id), "rules": ",".join(rules)},
        )
        return "blocked"

    # The audit trail must not go quiet just because nobody was at the keyboard. Same
    # transaction as the launch it describes (`write_audit`'s contract), `actor_type`
    # resolves to "system" because there is no principal — which is the true answer.
    #
    # Imported here rather than at module scope: `compliance.audit` pulls the hash-chain
    # machinery, and this module is imported by `apps/api`'s route table at boot.
    from apps.api.compliance.audit import write_audit

    await write_audit(
        session,
        action="campaign.launched",
        tenant_id=tenant_id,
        object_type="campaign",
        object_id=str(due.campaign_id),
        summary={"via": "schedule", "scheduled_for": due.start_at.isoformat()},
    )
    log.info(
        "campaign_schedule_fired",
        # `total_seconds()`, not `.seconds`: a timedelta's `.seconds` is the remainder
        # after whole days, so a start fired 25 hours late would log as one hour late —
        # and "how late did this start" is the number that decides whether GRACE is right.
        extra={
            "campaign_id": str(due.campaign_id),
            "late_seconds": int((now - due.start_at).total_seconds()),
        },
    )
    return "fired"


async def _still_scheduled(session: AsyncSession, campaign_id: UUID) -> bool:
    """Is this campaign still waiting, as of this transaction's snapshot?

    Read after the gate refused, not before: the whole question is whether the refusal
    was a compliance fact or the trace of another writer getting there first, and only a
    read taken AFTER that refusal can tell the two apart.
    """
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    return str(status) == "scheduled"


async def _record_block(
    session: AsyncSession, *, campaign_id: UUID, rules: list[str], now: datetime
) -> None:
    """Write why the start did not happen onto the schedule itself.

    On the schedule rather than in a new column: "what is this schedule doing" is the
    one question the JSONB is already the home of, and a table for four ticks' worth of
    transient state would be a table with an RLS policy, a migration and a retention
    rule for something a `draft` transition deletes.

    Conditional on the rule set having CHANGED, so a campaign blocked for a day writes
    one row version rather than 2,880. `IS DISTINCT FROM` rather than `<>` because the
    first block has no previous value to compare against.
    """
    await session.execute(
        text(
            "UPDATE campaigns SET schedule = jsonb_set(schedule, '{last_blocked}', "
            "  jsonb_build_object('at', to_jsonb(CAST(:at AS text)), "
            "                     'rules', CAST(:rules AS jsonb))), "
            "  updated_at = now() "
            "WHERE id = :cid AND status = 'scheduled' "
            "AND schedule->'last_blocked'->'rules' IS DISTINCT FROM CAST(:rules AS jsonb)"
        ),
        {"cid": campaign_id, "rules": json.dumps(rules), "at": now.isoformat()},
    )


async def _expire(session: AsyncSession, *, tenant_id: UUID, due: DueSchedule) -> str:
    """A start that never became lawful inside GRACE stops being a start.

    Back to `draft` with the schedule cleared, so the campaign lands in the one state
    where the client can both see the problem (`/launch-check` names the same blockers)
    and fix it (contacts and provenance are draft-editable). Audited, because "your
    campaign did not start" is exactly the fact a client will later ask us to account
    for, and alerted, because a schedule expiring is either a client who needs chasing
    or a gate that is wrong.
    """
    result = await session.execute(
        text(
            "UPDATE campaigns SET status = 'draft', schedule = NULL, updated_at = now() "
            "WHERE id = :cid AND status = 'scheduled'"
        ),
        {"cid": due.campaign_id},
    )
    if rowcount_of(result) == 0:
        return "raced"

    from apps.api.compliance.audit import write_audit

    await write_audit(
        session,
        action="campaign.schedule_expired",
        tenant_id=tenant_id,
        object_type="campaign",
        object_id=str(due.campaign_id),
        summary={
            "scheduled_for": due.start_at.isoformat(),
            "grace_hours": GRACE // timedelta(hours=1),
        },
    )
    alert(
        "WORKER_TERMINAL",
        "campaign_schedule_expired",
        detail=(
            f"a scheduled start was still blocked {GRACE // timedelta(hours=1)}h later; "
            "the campaign is back in draft"
        ),
        campaign_id=str(due.campaign_id),
    )
    return "expired"


# --------------------------------------------------------------------------- recurrence


async def _claim_occurrence(
    session: AsyncSession, *, campaign_id: UUID, occurrence_key: str
) -> dict[str, Any] | None:
    """Take the row lock, or discover that this occurrence is no longer ours to fire.

    **THIS IS THE WHOLE IDEMPOTENCY AND STOPPABILITY ARGUMENT**, and it is one statement
    because both properties come from the same fact: the identity in the WHERE clause is
    the OCCURRENCE, not the clock.

    - Two ticks (the lease fails open — `campaign_dispatch._tick_lease`) both read this
      occurrence as due. One takes the lock, launches, advances `start_at` and commits.
      The other blocks on the lock, and under READ COMMITTED Postgres re-evaluates this
      statement's qual against the newly committed row: the status is now `running` and
      `start_at` has moved, so it matches nothing and the loser returns without calling
      the gate. One occurrence, one launch, decided by row identity rather than by which
      tick's wall clock was ahead.
    - A client pressing "stop repeating" between the tick's due-read and this transaction
      has already set `schedule` to NULL; this matches nothing and the occurrence does not
      fire. Stopping therefore takes effect on the NEXT tick rather than the one after it,
      which is the deadline DNC propagation is held to and the same reason: enforcement is
      a read at the moment of acting, never a snapshot taken earlier.

    Returns the schedule as stored, so the advance below can rewrite it wholesale from a
    value read under the lock rather than merging blind into a column it has not seen.
    """
    row = (
        await session.execute(
            text(
                "SELECT schedule FROM campaigns "
                "WHERE id = :cid AND status = 'scheduled' "
                "AND schedule->>'kind' = :kind AND schedule->>'start_at' = :key "
                "FOR UPDATE"
            ),
            {"cid": campaign_id, "kind": RECURRING, "key": occurrence_key},
        )
    ).first()
    if row is None:
        return None
    stored = row[0]
    return dict(stored) if isinstance(stored, dict) else None


async def _fire_recurrence(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    due: DueSchedule,
    recurrence: Recurrence,
    now: datetime,
) -> str:
    """One occurrence of a repeat: claim it, gate it, launch it, advance to the next.

    The gate is `launch_campaign` — the identical function `POST /launch` calls and the
    identical one the one-time path calls, so a lapsed DLT registration, a spend cap, a
    KYC expiry or the platform halt refuses the eighth Tuesday exactly as it would refuse
    the first (hard rule 5). There is no recurring-launch variant of the gate and no
    branch that reaches `running` around it.

    Ordering, which is the part a plausible alternative gets wrong: the claim is a LOCK,
    not an advance. Advancing first would make a blocked occurrence unretryable — the
    registrar approving a template four minutes later could no longer rescue today's run
    — and advancing after the gate keeps `blocked` meaning "still trying, inside the
    catch-up window" for both kinds of schedule.
    """
    stored = await _claim_occurrence(
        session, campaign_id=due.campaign_id, occurrence_key=due.occurrence_key
    )
    if stored is None:
        # Stopped, rewritten, or another tick took this occurrence. Not an alert: this is
        # the designed outcome of a lease that fails open and of a stop button that works.
        return "raced"

    if now > due.start_at + RECURRENCE_CATCHUP:
        return await _skip_occurrence(
            session,
            tenant_id=tenant_id,
            due=due,
            recurrence=recurrence,
            stored=stored,
            now=now,
            reason="missed",
        )

    try:
        await launch_campaign(session, tenant_id=tenant_id, campaign_id=due.campaign_id)
    except InvalidStatusTransitionError:
        # Unreachable while the claim above holds the row lock — the status cannot move
        # under us — but propagated rather than swallowed for the reason the one-time path
        # propagates it: the loser's DNC scrub must roll back with it.
        raise
    except ProblemError as exc:
        if exc.code != "campaign_launch_blocked":
            raise
        # No `_still_scheduled` re-read here, and its absence is the claim doing its job:
        # the one-time path needs that read to tell a compliance refusal from a race that
        # arrived through the gate, and under the row lock a race cannot have arrived at
        # all. So every block on this path is a real compliance refusal.
        rules = [str(field.get("rule", "")) for field in exc.fields or []]
        for rule in rules:
            record_compliance_block(rule=rule)
        await _record_block(session, campaign_id=due.campaign_id, rules=rules, now=now)
        # Rules and ids only — never a client's wording, never a number (hard rule 6).
        log.warning(
            "campaign_recurrence_blocked",
            extra={"campaign_id": str(due.campaign_id), "rules": ",".join(rules)},
        )
        return "blocked"

    next_at = recurrence.next_after(due.start_at)
    stored["last_fired"] = {"occurrence": due.occurrence_key, "at": now.isoformat()}
    # A block that no longer describes anything: this occurrence launched.
    stored.pop("last_blocked", None)
    await _rewrite_schedule(
        session,
        tenant_id=tenant_id,
        campaign_id=due.campaign_id,
        occurrence_key=due.occurrence_key,
        stored=stored,
        next_at=next_at,
    )

    from apps.api.compliance.audit import write_audit

    await write_audit(
        session,
        action="campaign.launched",
        tenant_id=tenant_id,
        object_type="campaign",
        object_id=str(due.campaign_id),
        summary={"via": "recurrence", "occurrence": due.start_at.isoformat()},
    )
    log.info(
        "campaign_recurrence_fired",
        extra={
            "campaign_id": str(due.campaign_id),
            "late_seconds": int((now - due.start_at).total_seconds()),
        },
    )
    return "fired"


async def _skip_occurrence(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    due: DueSchedule,
    recurrence: Recurrence,
    stored: dict[str, Any],
    now: datetime,
    reason: str,
) -> str:
    """Decision 2, in code: an occurrence that came due too late is abandoned, not queued.

    The next occurrence is computed from NOW rather than from the occurrence we are
    abandoning, which is what stops a backlog forming: a worker down for a day comes back
    to one upcoming occurrence, not to yesterday's plus today's. Audited AND alerted,
    because a skip is two different stories and both need an owner — a worker that was
    down (ours) or a run that overran its own interval (the client's list is too long for
    the repeat they chose), and neither is visible from a campaign that simply says
    "scheduled".
    """
    next_at = recurrence.next_after(now)
    stored["last_skipped"] = {
        "occurrence": due.occurrence_key,
        "at": now.isoformat(),
        "reason": reason,
    }
    stored.pop("last_blocked", None)
    await _rewrite_schedule(
        session,
        tenant_id=tenant_id,
        campaign_id=due.campaign_id,
        occurrence_key=due.occurrence_key,
        stored=stored,
        next_at=next_at,
    )

    from apps.api.compliance.audit import write_audit

    await write_audit(
        session,
        action="campaign.recurrence_skipped",
        tenant_id=tenant_id,
        object_type="campaign",
        object_id=str(due.campaign_id),
        summary={
            "occurrence": due.start_at.isoformat(),
            "reason": reason,
            "late_seconds": int((now - due.start_at).total_seconds()),
            "next_occurrence": next_at.isoformat() if next_at else None,
        },
    )
    alert(
        "WORKER_STALL",
        "campaign_recurrence_skipped",
        detail=(
            f"a repeating campaign's occurrence came due "
            f"{int((now - due.start_at).total_seconds() // 60)} minutes late and was "
            "skipped rather than fired into a different time of day"
        ),
        campaign_id=str(due.campaign_id),
    )
    return "skipped"


async def _rewrite_schedule(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    occurrence_key: str,
    stored: dict[str, Any],
    next_at: datetime | None,
) -> None:
    """Move the repeat on to `next_at`, or END it when there is no next occurrence.

    Guarded on the occurrence key it was read under even though the caller holds the row
    lock: the guard costs nothing, and it is what makes this function safe to read on its
    own — a future caller without the lock cannot silently overwrite a schedule that
    moved.

    `next_at is None` means the `until` date has passed. The column goes to NULL, which
    is the same end state as a stopped repeat: a campaign carrying a rule that can never
    produce another occurrence would sit on screen promising a next run forever.
    """
    if next_at is None:
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = NULL, updated_at = now() "
                "WHERE id = :cid AND schedule->>'start_at' = :key"
            ),
            {"cid": campaign_id, "key": occurrence_key},
        )
        from apps.api.compliance.audit import write_audit

        await write_audit(
            session,
            action="campaign.recurrence_ended",
            tenant_id=tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            summary={"reason": "end_date_reached"},
        )
        log.info("campaign_recurrence_ended", extra={"campaign_id": str(campaign_id)})
        return

    stored["start_at"] = next_at.isoformat()
    await session.execute(
        text(
            "UPDATE campaigns SET schedule = CAST(:sched AS jsonb), updated_at = now() "
            "WHERE id = :cid AND schedule->>'start_at' = :key"
        ),
        {"cid": campaign_id, "sched": json.dumps(stored), "key": occurrence_key},
    )


async def complete_or_rearm(session: AsyncSession, *, campaign_id: UUID) -> str | None:
    """A run with nothing left to dial either COMPLETES or RE-ARMS its repeat.

    Called by the dispatcher where `status = 'completed'` used to be written
    unconditionally, and it lives here rather than there because "what does this column
    mean" is this module's question — the dispatcher decides that a run is finished, this
    decides what finished means for a campaign that repeats.

    Without this the feature would be half-wired in the way that looks finished: the
    first occurrence would fire, the campaign would end `completed`, and every later
    occurrence would sit under a status that `due_schedules` and `dispatch_scan()` do not
    look at. A weekly campaign would run exactly once.

    The re-armed campaign goes back to `scheduled` with the SAME `start_at` the fire
    already advanced to, and its contacts stay where they are — a repeat repeats the
    START, not the dialling. Re-dialling everyone who was already reached would be an
    unrequested repeat call to a subscriber, which is what generates UCC complaints; what
    the next occurrence dials is whatever is `pending`, i.e. the contacts the client has
    added since. A repeat over an exhausted list is refused by the gate's `no_contacts`
    and reported as a skip, which is the honest outcome rather than a silent one.

    Returns the status now on the row, or None when the campaign was not `running` (the
    tick raced with a pause, a cancel, or another completion).
    """
    # `:from_status` is BOUND rather than written as a SQL literal, which is the direction
    # D-65 already moved `set_campaign_status` in — and here it buys one more thing:
    # `tests/campaign_schedule_test.py` reads this module's SOURCE to assert that only
    # `launch_campaign` can start a campaign, by searching for the assignment that would
    # do it. A read guard spelled the same way as that assignment would make the guardrail
    # unusable, and the guardrail is worth more than the literal. No plan cost either:
    # this is a primary-key lookup, not a partial-index scan.
    row = (
        await session.execute(
            text(
                "UPDATE campaigns SET status = "
                "  CASE WHEN schedule->>'kind' = :kind THEN 'scheduled' ELSE 'completed' END, "
                "  updated_at = now() "
                "WHERE id = :cid AND status = :from_status RETURNING status"
            ),
            {"cid": campaign_id, "kind": RECURRING, "from_status": "running"},
        )
    ).first()
    return str(row[0]) if row is not None else None


__all__ = [
    "GRACE",
    "MAX_HORIZON",
    "ONE_TIME",
    "RECURRENCE_CATCHUP",
    "RECURRING",
    "CancelledSchedule",
    "DueSchedule",
    "Recurrence",
    "ScheduledRecurrence",
    "ScheduledStart",
    "complete_or_rearm",
    "describe_recurrence",
    "due_schedules",
    "fire_schedule",
    "first_dial_not_before",
    "schedule_campaign",
    "schedule_recurrence",
    "unschedule_campaign",
]
