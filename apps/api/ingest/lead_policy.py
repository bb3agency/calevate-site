"""A client's plan for calling new leads: one per client, not per agent (D-716).

Founder decision 10 (10 Oct 2026): where leads come from, how long to wait, the calling
hours, days and holidays, what to do with a lead that arrives after hours (call when we
open, three hours after opening, the next day, or hold it for the client to release),
retries when nobody answers, the answering-machine switch, and which agent calls.

WHAT THIS IS NOT: a second dial path or a second gate. Every call it times is placed by the
existing machinery — `ingest.service.ingest_lead` dials at once, everything later is a
`scheduled_callbacks` row the dispatch tick dials through `check_dispatch` and
`dispatch_call` like every other call back — so the do-not-call list, the platform calling
window (09:00-21:00 IST) and the compliance gate apply on every path and none of it is
switchable here. The client's hours only ever NARROW the platform window (CHECK on the
table).

No row means `DEFAULT_PLAN`, which is the behaviour before this existed: call at once, any
day, inside the platform window, defer to the next opening, no retries, no machine check.

TIME: IST wall clock, `calevate_shared.calling_window`'s convention (`IST` offset, India has
no DST); instants in and out are UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.calling_window import DEFAULT_WINDOW, IST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.callbacks.service import book as book_callback
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.ingest.models import AFTER_HOURS_CHOICES, WEEKDAYS

log = get_logger(__name__)

AfterHours = Literal["next_open", "open_plus_3h", "next_day", "hold"]

#: `scheduled_callbacks.source_execution_id` prefixes of a NEW LEAD's call. The first is
#: `ingest.service.INGEST_CALLBACK_PREFIX` (re-exported there); the other two are this
#: module's: a lead the client released from hold, and a retry after no answer.
LEAD_INGEST_PREFIX: Final = "lead-ingest:"
LEAD_RELEASE_PREFIX: Final = "lead-release:"
LEAD_RETRY_PREFIX: Final = "lead-retry:"

RETRY_MAX: Final = 3
OPEN_PLUS: Final = timedelta(hours=3)
#: How far ahead an opening is looked for; a plan with every day a holiday has none.
_SEARCH_DAYS: Final = 400
#: A call still on the line holds its lead's retry back for this long at most.
LIVE_CALL_HORIZON: Final = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class LeadCallPlan:
    calling_agent_id: UUID | None = None
    wait_seconds: int = 0
    hours_start: time = DEFAULT_WINDOW[0]
    hours_end: time = DEFAULT_WINDOW[1]
    days: tuple[str, ...] = WEEKDAYS
    holidays: tuple[date, ...] = ()
    after_hours: str = "next_open"
    retry_attempts: int = 0
    retry_interval_minutes: int = 60
    detect_machines: bool = False
    updated_at: datetime | None = None


DEFAULT_PLAN: Final = LeadCallPlan()

_COLUMNS: Final = (
    "calling_agent_id, wait_seconds, hours_start, hours_end, days, holidays, after_hours, "
    "retry_attempts, retry_interval_minutes, detect_machines, updated_at"
)


def _plan(row: Any) -> LeadCallPlan:
    return LeadCallPlan(
        calling_agent_id=UUID(str(row[0])) if row[0] is not None else None,
        wait_seconds=int(row[1]),
        hours_start=row[2],
        hours_end=row[3],
        days=tuple(row[4]),
        holidays=tuple(sorted(row[5])),
        after_hours=str(row[6]),
        retry_attempts=int(row[7]),
        retry_interval_minutes=int(row[8]),
        detect_machines=bool(row[9]),
        updated_at=row[10],
    )


async def load_plan(session: AsyncSession) -> LeadCallPlan:
    """The tenant's plan (the session's RLS decides whose), or `DEFAULT_PLAN`."""
    row = (
        await session.execute(text(f"SELECT {_COLUMNS} FROM lead_call_policies LIMIT 1"))
    ).first()
    return _plan(row) if row is not None else DEFAULT_PLAN


async def machine_detection_on(session: AsyncSession) -> bool:
    """The client's answering-machine switch, for an agent's published config."""
    value = (
        await session.execute(text("SELECT detect_machines FROM lead_call_policies LIMIT 1"))
    ).scalar()
    return bool(value)


# --- the clock ------------------------------------------------------------------------


def _ist(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) + IST


def _utc(wall: datetime) -> datetime:
    return (wall - IST).replace(tzinfo=UTC)


def _open_day(plan: LeadCallPlan, day: date) -> bool:
    return WEEKDAYS[day.weekday()] in plan.days and day not in plan.holidays


def is_open(plan: LeadCallPlan, moment: datetime) -> bool:
    """Is `moment` inside the plan's hours, on an open day? Half-open, like the platform."""
    wall = _ist(moment)
    return _open_day(plan, wall.date()) and plan.hours_start <= wall.time() < plan.hours_end


def next_opening(plan: LeadCallPlan, moment: datetime) -> datetime | None:
    """The first instant at or after `moment` the plan allows, or None if it never opens."""
    if is_open(plan, moment):
        return moment
    wall = _ist(moment)
    day = wall.date()
    if wall.time() < plan.hours_start and _open_day(plan, day):
        return _utc(datetime.combine(day, plan.hours_start))
    for offset in range(1, _SEARCH_DAYS):
        candidate = day + timedelta(days=offset)
        if _open_day(plan, candidate):
            return _utc(datetime.combine(candidate, plan.hours_start))
    return None


def next_day_opening(plan: LeadCallPlan, moment: datetime) -> datetime | None:
    """The opening of the first open day AFTER `moment`'s own date (IST)."""
    day = _ist(moment).date()
    for offset in range(1, _SEARCH_DAYS):
        candidate = day + timedelta(days=offset)
        if _open_day(plan, candidate):
            return _utc(datetime.combine(candidate, plan.hours_start))
    return None


@dataclass(frozen=True, slots=True)
class Timing:
    """When a new lead's first call is placed: now, at `at`, or held for the client."""

    kind: Literal["now", "later", "hold"]
    at: datetime | None = None
    #: Why not now, for the lead's timeline: `wait`, `after_hours` or `closed`.
    reason: str | None = None


def when_to_call(plan: LeadCallPlan, now: datetime) -> Timing:
    """The plan's answer for a lead arriving at `now`."""
    candidate = now + timedelta(seconds=plan.wait_seconds)
    if is_open(plan, candidate):
        if plan.wait_seconds == 0:
            return Timing("now")
        return Timing("later", candidate, "wait")
    if plan.after_hours == "hold":
        return Timing("hold", None, "after_hours")
    if plan.after_hours == "next_day":
        at = next_day_opening(plan, candidate)
    elif plan.after_hours == "open_plus_3h":
        opening = next_opening(plan, candidate)
        at = None if opening is None else next_opening(plan, opening + OPEN_PLUS)
    else:
        at = next_opening(plan, candidate)
    if at is None:
        return Timing("hold", None, "closed")
    return Timing("later", at, "after_hours")


def align(plan: LeadCallPlan, moment: datetime) -> datetime | None:
    """`moment`, or the plan's next opening after it: where a retry or a release lands."""
    return next_opening(plan, moment)


# --- saving ---------------------------------------------------------------------------


def _refuse(code: str, detail: str, field: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code=code,
        title="This calling plan cannot be saved",
        detail=detail,
        fields=[{"field": field, "rule": code, "message": detail}],
    )


def validated(plan: LeadCallPlan) -> LeadCallPlan:
    """The plan as it will be stored, or a refusal naming the field. The table's CHECKs say
    the same; this is the sentence a person can act on."""
    start, end = DEFAULT_WINDOW
    if not (start <= plan.hours_start < plan.hours_end <= end):
        raise _refuse(
            "lead_hours_outside_window",
            "Calling hours must start before they end, inside 9 AM to 9 PM.",
            "hours_start",
        )
    days = tuple(day for day in WEEKDAYS if day in set(plan.days))
    if not days or len(days) != len(set(plan.days)):
        raise _refuse("lead_days_invalid", "Choose at least one calling day.", "days")
    if len(plan.holidays) > 60:
        raise _refuse("lead_holidays_too_many", "Add at most 60 holidays.", "holidays")
    if plan.after_hours not in AFTER_HOURS_CHOICES:
        raise _refuse("lead_after_hours_invalid", "Choose what happens after hours.", "after_hours")
    if not 0 <= plan.wait_seconds <= 3600:
        raise _refuse("lead_wait_invalid", "Wait between 0 seconds and one hour.", "wait_seconds")
    if not 0 <= plan.retry_attempts <= RETRY_MAX:
        raise _refuse("lead_retries_invalid", "Retry at most 3 times.", "retry_attempts")
    if not 10 <= plan.retry_interval_minutes <= 1440:
        raise _refuse(
            "lead_retry_interval_invalid",
            "Wait between 10 minutes and 24 hours before a retry.",
            "retry_interval_minutes",
        )
    return replace(plan, days=days, holidays=tuple(sorted(set(plan.holidays))))


async def _refuse_unusable_agent(session: AsyncSession, agent_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                "SELECT direction FROM agents WHERE id = :aid AND deleted_at IS NULL "
                "AND archived_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise _refuse("lead_agent_unknown", "That agent was not found.", "calling_agent_id")
    if str(row[0]) not in ("outbound", "both"):
        raise _refuse(
            "lead_agent_cannot_call",
            "That agent only answers calls. Choose an agent that places calls.",
            "calling_agent_id",
        )


async def save_plan(
    session: AsyncSession, *, tenant_id: UUID, plan: LeadCallPlan, user_id: UUID | None
) -> tuple[LeadCallPlan, bool]:
    """Store the plan. Returns it as stored and whether the machine switch changed."""
    clean = validated(plan)
    if clean.calling_agent_id is not None:
        await _refuse_unusable_agent(session, clean.calling_agent_id)
    before = await machine_detection_on(session)
    row = (
        await session.execute(
            text(
                "INSERT INTO lead_call_policies (id, tenant_id, calling_agent_id, wait_seconds, "
                "hours_start, hours_end, days, holidays, after_hours, retry_attempts, "
                "retry_interval_minutes, detect_machines, updated_by) VALUES (:id, :tid, :agent, "
                ":wait, :start, :end, :days, :holidays, :after, :retries, :interval, :machines, "
                ":by) ON CONFLICT (tenant_id) DO UPDATE SET "
                "calling_agent_id = EXCLUDED.calling_agent_id, "
                "wait_seconds = EXCLUDED.wait_seconds, hours_start = EXCLUDED.hours_start, "
                "hours_end = EXCLUDED.hours_end, days = EXCLUDED.days, "
                "holidays = EXCLUDED.holidays, after_hours = EXCLUDED.after_hours, "
                "retry_attempts = EXCLUDED.retry_attempts, "
                "retry_interval_minutes = EXCLUDED.retry_interval_minutes, "
                "detect_machines = EXCLUDED.detect_machines, updated_by = EXCLUDED.updated_by, "
                f"updated_at = now() RETURNING {_COLUMNS}"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "agent": clean.calling_agent_id,
                "wait": clean.wait_seconds,
                "start": clean.hours_start,
                "end": clean.hours_end,
                "days": list(clean.days),
                "holidays": list(clean.holidays),
                "after": clean.after_hours,
                "retries": clean.retry_attempts,
                "interval": clean.retry_interval_minutes,
                "machines": clean.detect_machines,
                "by": user_id,
            },
        )
    ).one()
    stored = _plan(row)
    return stored, stored.detect_machines != before


# --- holding --------------------------------------------------------------------------


async def hold_lead(
    session: AsyncSession, *, tenant_id: UUID, lead_id: UUID, agent_id: UUID, source: str
) -> UUID | None:
    """Put a lead in the client's release queue. None when it is already there."""
    row = (
        await session.execute(
            text(
                "INSERT INTO lead_call_holds (id, tenant_id, lead_id, agent_id, source) "
                "VALUES (:id, :tid, :lid, :aid, :src) "
                "ON CONFLICT (tenant_id, lead_id) WHERE status = 'held' DO NOTHING RETURNING id"
            ),
            {"id": uuid7(), "tid": tenant_id, "lid": lead_id, "aid": agent_id, "src": source},
        )
    ).first()
    return UUID(str(row[0])) if row is not None else None


@dataclass(frozen=True, slots=True)
class HeldLead:
    id: UUID
    lead_id: UUID
    lead_name: str | None
    agent_id: UUID
    agent_name: str | None
    source: str
    held_at: datetime


#: Held leads accumulate until the client acts on them, so the queue is read a page at a time.
MAX_HELD_PAGE: Final = 200


async def list_held(session: AsyncSession, *, limit: int = MAX_HELD_PAGE) -> list[HeldLead]:
    rows = (
        await session.execute(
            text(
                "SELECT h.id, h.lead_id, l.name, h.agent_id, a.name, h.source, h.held_at "
                "FROM lead_call_holds h JOIN leads l ON l.id = h.lead_id "
                "LEFT JOIN agents a ON a.id = h.agent_id "
                "WHERE h.status = 'held' AND l.deleted_at IS NULL "
                "ORDER BY h.held_at LIMIT :n"
            ),
            {"n": min(limit, MAX_HELD_PAGE)},
        )
    ).all()
    return [
        HeldLead(
            id=UUID(str(r[0])),
            lead_id=UUID(str(r[1])),
            lead_name=r[2],
            agent_id=UUID(str(r[3])),
            agent_name=r[4],
            source=str(r[5]),
            held_at=r[6],
        )
        for r in rows
    ]


async def count_held(session: AsyncSession) -> int:
    value = (
        await session.execute(text("SELECT count(*) FROM lead_call_holds WHERE status = 'held'"))
    ).scalar()
    return int(value or 0)


_SETTLED_VERB = {"released": "released, and its call is booked", "dropped": "taken off the list"}


async def _hold_not_found(
    session: AsyncSession, *, hold_id: UUID, user_id: UUID | None
) -> ProblemError:
    """Two people on one team (or two tabs) acting on the same held lead: say which
    happened and whether it was this person, so nobody releases it twice to be sure."""
    row = (
        await session.execute(
            text("SELECT status, settled_by FROM lead_call_holds WHERE id = :hid"),
            {"hid": hold_id},
        )
    ).first()
    detail = "It was already released or dropped."
    if row is not None and str(row[0]) in _SETTLED_VERB:
        who = (
            "You"
            if user_id is not None and row[1] is not None and UUID(str(row[1])) == user_id
            else "Someone on your team"
        )
        detail = f"{who} already had it {_SETTLED_VERB[str(row[0])]}."
    return ProblemError(
        kind="not_found",
        code="lead_hold_not_found",
        title="This lead is no longer waiting",
        detail=detail,
        remediation="Refresh the list.",
    )


async def release_held(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    hold_id: UUID,
    user_id: UUID | None,
    now: datetime | None = None,
) -> tuple[UUID, datetime]:
    """Release one held lead: its call is booked for now (or the plan's next opening), and
    the dispatch tick places it through the compliance gate. Returns the call back."""
    moment = now or datetime.now(UTC)
    row = (
        await session.execute(
            text(
                "SELECT h.lead_id, h.agent_id, h.source, l.phone_e164 FROM lead_call_holds h "
                "JOIN leads l ON l.id = h.lead_id "
                "WHERE h.id = :hid AND h.status = 'held' AND l.deleted_at IS NULL FOR UPDATE OF h"
            ),
            {"hid": hold_id},
        )
    ).first()
    if row is None:
        raise await _hold_not_found(session, hold_id=hold_id, user_id=user_id)
    plan = await load_plan(session)
    # The client asked for it now: the plan's own hours still apply, and the platform
    # window is the gate's when the tick dials.
    due = align(plan, moment) or moment
    booked = await book_callback(
        session,
        callback_id=uuid7(),
        tenant_id=tenant_id,
        agent_id=UUID(str(row[1])),
        source_call_id=None,
        source_execution_id=f"{LEAD_RELEASE_PREFIX}{hold_id}",
        lead_id=UUID(str(row[0])),
        phone_e164=str(row[3]),
        requested_at=due,
        booked_at=moment,
        note=f"New enquiry via {row[2]}, released by the business",
        language=None,
    )
    if booked is None:
        raise await _hold_not_found(session, hold_id=hold_id, user_id=user_id)
    await session.execute(
        text(
            "UPDATE lead_call_holds SET status = 'released', settled_at = now(), "
            "settled_by = :by, callback_id = :cb, updated_at = now() WHERE id = :hid"
        ),
        {"by": user_id, "cb": booked[0], "hid": hold_id},
    )
    return booked


async def drop_held(session: AsyncSession, *, hold_id: UUID, user_id: UUID | None) -> None:
    """The client will not call this lead: it leaves the queue; the lead itself stays."""
    result = await session.execute(
        text(
            "UPDATE lead_call_holds SET status = 'dropped', settled_at = now(), "
            "settled_by = :by, updated_at = now() WHERE id = :hid AND status = 'held' "
            "RETURNING id"
        ),
        {"by": user_id, "hid": hold_id},
    )
    if result.first() is None:
        raise await _hold_not_found(session, hold_id=hold_id, user_id=user_id)


# --- retries --------------------------------------------------------------------------


def retry_key(attempt: int, root: str) -> str:
    return f"{LEAD_RETRY_PREFIX}{attempt}:{root}"


def new_lead_attempt(execution_id: str | None) -> tuple[int, str] | None:
    """`(attempt number, root)` of a new lead's call back, or None for any other call back.
    The first call is attempt 0; `lead-retry:<n>:<root>` is attempt n."""
    if not execution_id:
        return None
    for prefix in (LEAD_INGEST_PREFIX, LEAD_RELEASE_PREFIX):
        if execution_id.startswith(prefix):
            return 0, execution_id.removeprefix(prefix)
    if execution_id.startswith(LEAD_RETRY_PREFIX):
        number, _, root = execution_id.removeprefix(LEAD_RETRY_PREFIX).partition(":")
        if number.isdigit() and root:
            return int(number), root
    return None


async def book_retry(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    plan: LeadCallPlan,
    lead_id: UUID | None,
    agent_id: UUID,
    phone_e164: str,
    attempt: int,
    root: str,
    now: datetime | None = None,
) -> datetime | None:
    """After a new lead's call `attempt` was placed, book the next try in case nobody
    answers. Booked in advance and checked when it falls due (`retry_still_wanted`): the
    call's outcome is not known yet, and booking now means a retry cannot be forgotten.
    Returns when, or None when the plan wants no more tries."""
    if lead_id is None or attempt >= plan.retry_attempts:
        return None
    moment = now or datetime.now(UTC)
    due = align(plan, moment + timedelta(minutes=plan.retry_interval_minutes))
    if due is None:
        return None
    booked = await book_callback(
        session,
        callback_id=uuid7(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_call_id=None,
        source_execution_id=retry_key(attempt + 1, root),
        lead_id=lead_id,
        phone_e164=phone_e164,
        requested_at=due,
        booked_at=moment,
        note="A new enquiry who did not answer the last try",
        language=None,
    )
    return booked[1] if booked else None


RetryVerdict = Literal["dial", "answered", "on_a_call"]


async def retry_still_wanted(
    session: AsyncSession, *, lead_id: UUID | None, phone_e164: str, booked_at: datetime | None
) -> RetryVerdict:
    """Is a booked retry still needed? Not once the lead answered (or called in) since the
    try before it; not yet while a call with them is still on the line."""
    since = (booked_at or datetime.now(UTC)) - timedelta(minutes=1)
    match = "(lead_id = :lid OR from_e164 = :p OR to_e164 = :p)"
    params = {"lid": lead_id, "p": phone_e164, "since": since}
    answered = (
        await session.execute(
            text(
                f"SELECT EXISTS (SELECT 1 FROM calls WHERE {match} "
                "AND status = 'completed' AND created_at >= :since)"
            ),
            params,
        )
    ).scalar()
    if answered:
        return "answered"
    live = (
        await session.execute(
            text(
                f"SELECT EXISTS (SELECT 1 FROM calls WHERE {match} "
                "AND status IN ('queued', 'ringing', 'in_progress') AND updated_at > :horizon)"
            ),
            {**params, "horizon": datetime.now(UTC) - LIVE_CALL_HORIZON},
        )
    ).scalar()
    return "on_a_call" if live else "dial"


__all__ = [
    "DEFAULT_PLAN",
    "LEAD_INGEST_PREFIX",
    "LEAD_RELEASE_PREFIX",
    "LEAD_RETRY_PREFIX",
    "MAX_HELD_PAGE",
    "AfterHours",
    "HeldLead",
    "LeadCallPlan",
    "Timing",
    "align",
    "book_retry",
    "count_held",
    "drop_held",
    "hold_lead",
    "is_open",
    "list_held",
    "load_plan",
    "machine_detection_on",
    "new_lead_attempt",
    "next_day_opening",
    "next_opening",
    "release_held",
    "retry_key",
    "retry_still_wanted",
    "save_plan",
    "validated",
    "when_to_call",
]
