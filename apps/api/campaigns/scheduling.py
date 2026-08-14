"""Scheduled campaign starts — `campaigns.schedule`, and the only code that reads it.

A client says "start this campaign on Monday at 10am". Before this module the column
existed and nothing wrote or read it (`check_wiring.UNWIRED_BASELINE`), so the only way
to start a campaign was to be at a keyboard at the moment it should start.

Four decisions shape everything below. They are here rather than scattered through the
functions because each one is a place a plausible alternative is wrong.

**1. ONE-TIME ONLY. Recurrence is deliberately not built.**
`schedule` holds `{"kind": "one_time", "start_at": "<UTC ISO-8601>"}` and
`_parse_schedule` REFUSES any other `kind` rather than treating it as a one-time start.
Recurrence is a much larger surface than a start time — RRULE parsing, "skip if the
previous run is still going", IST DST (none today, but the rule outlives the assumption),
and a "next occurrence" the client has to be able to see and cancel. A half-built one
would fire a recurring campaign once and look finished. The `kind` discriminator exists
precisely so that the day recurrence lands, every row already in the table says plainly
which of the two it is, and nothing has to guess. Until then the honest statement is:
this column holds one-time starts.

**2. THE COMPLIANCE GATE RUNS AT FIRE TIME, and it is the SAME gate.**
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

**3. STARTING IS NOT DIALLING, so a 22:00 start is accepted and dials at 09:00.**
`calling_hours` is a per-day window enforced PER DIAL under TRAI; a schedule is a
one-time START. Refusing a 22:00 start would be refusing a perfectly lawful intent
("have it ready to go first thing"), and firing it into a dial would be the TRAI
violation. So a fired schedule does exactly what `POST /launch` at 22:00 does today —
the campaign becomes `running` and dials nothing until the window opens. `launch_blockers`
already states this as settled: "a campaign launched at 22:00 to dial tomorrow morning is
correct, not blocked".

What the client gets instead of a refusal is the truth: `first_dial_not_before` is
returned by the schedule endpoint, so a 22:00 start says on screen that dialling begins
at 09:00 the next morning.

**4. IST AT THE EDGE, UTC IN THE DB — and a naive datetime is REFUSED, not assumed.**
Elsewhere in this package (`_validated_provenance`) a naive datetime is pinned to UTC.
That is right there and wrong here. Provenance records something that already happened,
so a mis-assumed zone is a wrong log line; a schedule decides when a phone rings, so a
"10:00" read as UTC rings a household at 15:30 IST — or, at the other end of the window,
at 02:30. The wire model is `AwareDatetime` so the generated TypeScript client cannot
send a bare local string, and `schedule_campaign` refuses one again for callers that are
not HTTP requests.
"""

from __future__ import annotations

import json
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

# The only `kind` this module will fire. See decision 1 in the module docstring.
ONE_TIME = "one_time"

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

_SCHEDULE_PAST = "campaign_schedule_in_past"
_SCHEDULE_NAIVE = "campaign_schedule_timezone_missing"
_SCHEDULE_TOO_FAR = "campaign_schedule_too_far"


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
class DueSchedule:
    campaign_id: UUID
    start_at: datetime


def _require_aware(start_at: datetime) -> datetime:
    """Decision 4: a schedule with no timezone is refused, never guessed at."""
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

    NO GATE HERE, by design — see decision 2 in the module docstring.
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


async def unschedule_campaign(session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID) -> None:
    """Cancel a pending start: `scheduled` → `draft`, and the column goes back to NULL.

    Back to `draft` rather than to a third "was scheduled" state, because that is what
    it now is: a campaign nobody has started, editable again (contacts, provenance) by
    exactly the rules that govern any other draft.
    """
    result = await session.execute(
        text(
            "UPDATE campaigns SET schedule = NULL, status = 'draft', updated_at = now() "
            "WHERE id = :cid AND tenant_id = :tid AND status = 'scheduled'"
        ),
        {"cid": campaign_id, "tid": tenant_id},
    )
    if rowcount_of(result) == 0:
        raise await _why_not_schedulable(session, campaign_id, unscheduling=True)


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
            f"This campaign is {status}, so there is no scheduled start to cancel.",
        )
    return ProblemError.business_rule(
        "campaign_not_schedulable",
        f"A {status} campaign cannot be given a start time; only a draft can.",
    )


def _parse_schedule(raw: object, *, campaign_id: UUID) -> datetime | None:
    """The stored JSON → a start instant, or None with a reason logged.

    FAILS CLOSED on everything it does not understand, and each branch is a real
    possibility rather than defensive noise:

    - an unknown `kind` is the recurrence this module did not build. Firing it as a
      one-time start is the specific "half-built recurrence" failure the module
      docstring refuses — a recurring campaign that runs once and looks finished;
    - an unparseable `start_at` cannot be compared to anything. `schedule_campaign` is
      the only writer and it serializes an aware UTC instant, so this is unreachable by
      design — which is exactly why it alerts rather than passing quietly. Something
      wrote to this column that is not this module.
    """
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind != ONE_TIME:
        alert(
            "WORKER_TERMINAL",
            "campaign_schedule_kind_unknown",
            detail=f"schedule kind {kind!r} has no reader; campaign not started",
            campaign_id=str(campaign_id),
        )
        return None
    try:
        parsed = datetime.fromisoformat(str(raw.get("start_at")))
    except (TypeError, ValueError):
        alert(
            "WORKER_TERMINAL",
            "campaign_schedule_unparseable",
            detail="schedule.start_at is not an ISO-8601 instant; campaign not started",
            campaign_id=str(campaign_id),
        )
        return None
    if parsed.tzinfo is None:
        alert(
            "WORKER_TERMINAL",
            "campaign_schedule_unparseable",
            detail="schedule.start_at carries no offset; campaign not started",
            campaign_id=str(campaign_id),
        )
        return None
    return parsed.astimezone(UTC)


async def due_schedules(session: AsyncSession, *, now: datetime) -> list[DueSchedule]:
    """Scheduled campaigns of THIS tenant whose start time has arrived.

    **THIS IS THE AUTHORITY ON WHAT "DUE" MEANS.** `dispatch_scan()`'s `has_due_schedule`
    (migration c7e4b19d3f52) asks a similar question in SQL, and the relationship between
    the two is deliberate and one-directional: the scan is a coarse SCREEN that decides
    whether a tenant is worth a session at all, and it is a proven SUPERSET of this — the
    same relationship `engine_agent_routes` already has with the dispatch tick. Anything
    that makes a schedule un-runnable is decided HERE and nowhere else:

    - `kind`, the discriminator that keeps an unbuilt recurrence from being fired once as
      a one-time start. A WHERE clause could express it, and then there would be two
      places that decide what a schedule is, in a repo where one of them is frozen
      migration history;
    - the offset requirement and the parse, whose failures need to name the campaign in
      an alert. A row silently skipped by a SQL predicate names nothing.

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
        start_at = _parse_schedule(raw, campaign_id=UUID(str(campaign_id)))
        if start_at is not None and start_at <= now:
            due.append(DueSchedule(campaign_id=UUID(str(campaign_id)), start_at=start_at))
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
      client can act on them.
    """
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


__all__ = [
    "GRACE",
    "MAX_HORIZON",
    "ONE_TIME",
    "DueSchedule",
    "ScheduledStart",
    "due_schedules",
    "fire_schedule",
    "first_dial_not_before",
    "schedule_campaign",
    "unschedule_campaign",
]
