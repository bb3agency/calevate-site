"""Routines: instructions the assistant runs on a schedule, as background jobs (D-694 item 5).

A routine is a standing request ("every morning, call back yesterday's missed leads") with a
schedule in IST. When it is due, `fire_routine` turns it into an ordinary background job
(`copilot/jobs.create_job`), so a routine runs the SAME tool loop, under the SAME job limits,
as a request the person typed — and therefore meets every gate a typed request meets:

* the fair-use cap and the platform brake, which the job worker asks before its first turn;
* the permission ladder, re-read when the job starts, so a demoted author is refused;
* calling hours, DNC, KYC and the pledge, credit, the trial rules and the big red switch,
  which live inside the service functions every action calls. A routine cannot dial
  anyone by itself: inside a job a confirm-tier action is STAGED in the Approvals inbox
  (`write_tools.stage_for_approval`) and runs only when a person approves it, through the
  button's own function, which is where those gates are.

So this module enforces no gate of its own, deliberately. A second copy of a dispatch rule
here would be a second place for it to drift.

WHAT THIS MODULE DOES DECIDE is when a slot fires, and three reasons a slot is skipped
rather than fired, each recorded on the run with a sentence for the person:

* the author is no longer on the account (the routine is also switched off — it has nobody
  to run as);
* the author already has the most background jobs one person may run at once;
* the tick reached the slot more than `LATE_LIMIT` after it was due. "Every morning at 9"
  run at 4 in the afternoon is a different instruction from the one the person gave, so a
  late slot is skipped, not run late, and a worker outage never fires a backlog.

A slot fires at most once: `copilot_routine_runs` is unique on `(routine_id, slot_at)` and
the routine row is locked while its slot is claimed and its schedule advanced, in the same
transaction as the job row and its outbox message.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot import jobs
from apps.api.copilot.memory import redacted_content
from apps.api.copilot.routine_models import (
    MAX_ROUTINE_INSTRUCTION,
    MAX_ROUTINE_NAME,
    MAX_RUN_REASON,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: Routines are scheduled in India's time, the only time zone this product's clients keep.
IST: Final = ZoneInfo("Asia/Kolkata")

#: Monday first, matching `date.weekday()`; bit N of `days` is `WEEKDAYS[N]`.
WEEKDAYS: Final[tuple[str, ...]] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
EVERY_DAY: Final = 0b1111111

#: How many routines one person may keep. A list bound and a guard against a model or a
#: script minting a routine per request.
MAX_ROUTINES_PER_USER: Final = 20

#: A slot reached later than this after it was due is skipped, not run late.
LATE_LIMIT: Final = timedelta(hours=1)

#: How many recent runs one routine's history returns at most.
RUNS_PAGE_MAX: Final = 50

#: The screen a routine's job says it was started from. The workspace's route template.
ROUTINE_SCREEN_ROUTE: Final = "/c/{slug}/assistant"

RunTrigger = Literal["schedule", "manual"]


@dataclass(frozen=True, slots=True)
class RoutineRow:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    name: str
    instruction: str
    days: int
    at_minute: int
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RunRow:
    id: UUID
    routine_id: UUID
    slot_at: datetime
    trigger: str
    status: str
    reason: str | None
    job_id: UUID | None
    job_status: str | None
    created_at: datetime


_COLUMNS: Final = (
    "id, tenant_id, user_id, name, instruction, days, at_minute, enabled, next_run_at, "
    "last_run_at, created_at, updated_at"
)


def _routine(record: Sequence[Any]) -> RoutineRow:
    return RoutineRow(
        id=record[0],
        tenant_id=record[1],
        user_id=record[2],
        name=record[3],
        instruction=record[4],
        days=int(record[5]),
        at_minute=int(record[6]),
        enabled=bool(record[7]),
        next_run_at=record[8],
        last_run_at=record[9],
        created_at=record[10],
        updated_at=record[11],
    )


# --- the schedule -------------------------------------------------------------------------


def days_mask(days: Iterable[str]) -> int:
    """`["mon", "fri"]` → `0b0010001`. Unknown names are refused, not ignored."""
    mask = 0
    for day in days:
        if day not in WEEKDAYS:
            raise ValueError(f"not a weekday: {day!r}")
        mask |= 1 << WEEKDAYS.index(day)
    return mask


def days_of(mask: int) -> list[str]:
    """`0b0010001` → `["mon", "fri"]`, Monday first."""
    return [day for index, day in enumerate(WEEKDAYS) if mask & (1 << index)]


def next_occurrence(days: int, at_minute: int, *, after: datetime) -> datetime:
    """The first instant strictly after `after` that falls on one of `days` at `at_minute`
    past midnight IST, in UTC.

    Strictly after, so advancing from the slot that just fired can never return that slot
    again. India keeps no daylight saving, so every IST wall-clock minute exists exactly
    once and the combine below is never ambiguous.
    """
    if not 1 <= days <= EVERY_DAY:
        raise ValueError("a routine runs on at least one day of the week")
    local = after.astimezone(IST)
    clock = time(at_minute // 60, at_minute % 60)
    start: date = local.date()
    for offset in range(8):
        day = start + timedelta(days=offset)
        if not days & (1 << day.weekday()):
            continue
        candidate = datetime.combine(day, clock, tzinfo=IST)
        if candidate > local:
            return candidate.astimezone(UTC)
    raise AssertionError("unreachable: a non-empty weekday mask recurs within eight days")


# --- reads ----------------------------------------------------------------------------------


async def list_routines(session: AsyncSession, *, user_id: UUID, limit: int) -> list[RoutineRow]:
    """This person's routines, newest first. RLS scopes the account; the predicate scopes
    the person, as for jobs: a colleague's standing instructions are not theirs to read."""
    bounded = max(1, min(limit, MAX_ROUTINES_PER_USER))
    records = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM copilot_routines WHERE user_id = :uid "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"uid": user_id, "limit": bounded},
        )
    ).all()
    return [_routine(record) for record in records]


async def read_routine(session: AsyncSession, *, routine_id: UUID, user_id: UUID) -> RoutineRow:
    record = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM copilot_routines WHERE id = :id AND user_id = :uid"),
            {"id": routine_id, "uid": user_id},
        )
    ).first()
    if record is None:
        raise ProblemError.not_found("Routine")
    return _routine(record)


async def list_runs(
    session: AsyncSession, *, routine_id: UUID, user_id: UUID, limit: int
) -> list[RunRow]:
    """One routine's runs, newest first, each with its job's status when it has one."""
    await read_routine(session, routine_id=routine_id, user_id=user_id)
    bounded = max(1, min(limit, RUNS_PAGE_MAX))
    records = (
        await session.execute(
            text(
                "SELECT r.id, r.routine_id, r.slot_at, r.trigger, r.status, r.reason, r.job_id, "
                "j.status, r.created_at FROM copilot_routine_runs r "
                "LEFT JOIN copilot_jobs j ON j.id = r.job_id "
                "WHERE r.routine_id = :rid ORDER BY r.created_at DESC LIMIT :limit"
            ),
            {"rid": routine_id, "limit": bounded},
        )
    ).all()
    return [
        RunRow(
            id=record[0],
            routine_id=record[1],
            slot_at=record[2],
            trigger=record[3],
            status=record[4],
            reason=record[5],
            job_id=record[6],
            job_status=record[7],
            created_at=record[8],
        )
        for record in records
    ]


# --- writes ---------------------------------------------------------------------------------


def _clean_name(name: str) -> str:
    cleaned = " ".join(strip_invisible(name).split())
    if not cleaned:
        raise _invalid("copilot_routine_name_blank", "Give the routine a name.")
    return cleaned[:MAX_ROUTINE_NAME]


def _clean_instruction(instruction: str) -> str:
    cleaned = redacted_content(strip_invisible(instruction)).strip()
    if not cleaned:
        raise _invalid(
            "copilot_routine_instruction_blank", "Say what the assistant should do each time."
        )
    return cleaned[:MAX_ROUTINE_INSTRUCTION]


def _invalid(code: str, detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code=code,
        title="That routine cannot be saved",
        detail=detail,
        remediation="Change it and save again.",
    )


async def create_routine(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    name: str,
    instruction: str,
    days: int,
    at_minute: int,
    enabled: bool,
    now: datetime,
) -> RoutineRow:
    count = (
        await session.execute(
            text("SELECT count(*) FROM copilot_routines WHERE user_id = :uid"), {"uid": user_id}
        )
    ).scalar_one()
    if int(count) >= MAX_ROUTINES_PER_USER:
        raise ProblemError(
            kind="conflict",
            code="copilot_routine_limit",
            title="You have the most routines one person can keep",
            detail=f"One person can keep up to {MAX_ROUTINES_PER_USER} routines.",
            remediation="Delete a routine you no longer need, then add this one.",
        )
    next_run = next_occurrence(days, at_minute, after=now) if enabled else None
    record = (
        await session.execute(
            text(
                "INSERT INTO copilot_routines (id, tenant_id, user_id, name, instruction, days, "
                "at_minute, enabled, next_run_at, created_at, updated_at) VALUES (:id, :tid, "
                f":uid, :name, :instruction, :days, :at, :enabled, :next, now(), now()) "
                f"RETURNING {_COLUMNS}"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "uid": user_id,
                "name": _clean_name(name),
                "instruction": _clean_instruction(instruction),
                "days": days,
                "at": at_minute,
                "enabled": enabled,
                "next": next_run,
            },
        )
    ).one()
    return _routine(record)


async def update_routine(
    session: AsyncSession,
    *,
    routine_id: UUID,
    user_id: UUID,
    name: str | None,
    instruction: str | None,
    days: int | None,
    at_minute: int | None,
    enabled: bool | None,
    now: datetime,
) -> RoutineRow:
    """Change a routine. A changed schedule, or switching it on, re-derives the next run
    from NOW, so an edit never fires a slot that was already in the past."""
    current = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM copilot_routines WHERE id = :id AND user_id = :uid "
                "FOR UPDATE"
            ),
            {"id": routine_id, "uid": user_id},
        )
    ).first()
    if current is None:
        raise ProblemError.not_found("Routine")
    row = _routine(current)
    new_days = row.days if days is None else days
    new_minute = row.at_minute if at_minute is None else at_minute
    new_enabled = row.enabled if enabled is None else enabled
    reschedule = new_days != row.days or new_minute != row.at_minute or not row.enabled
    if not new_enabled:
        next_run: datetime | None = None
    elif reschedule:
        next_run = next_occurrence(new_days, new_minute, after=now)
    else:
        next_run = row.next_run_at
    record = (
        await session.execute(
            text(
                "UPDATE copilot_routines SET name = :name, instruction = :instruction, "
                "days = :days, at_minute = :at, enabled = :enabled, next_run_at = :next, "
                f"updated_at = now() WHERE id = :id RETURNING {_COLUMNS}"
            ),
            {
                "id": routine_id,
                "name": row.name if name is None else _clean_name(name),
                "instruction": (
                    row.instruction if instruction is None else _clean_instruction(instruction)
                ),
                "days": new_days,
                "at": new_minute,
                "enabled": new_enabled,
                "next": next_run,
            },
        )
    ).one()
    return _routine(record)


async def delete_routine(session: AsyncSession, *, routine_id: UUID, user_id: UUID) -> None:
    """Delete a routine and its run history. What its runs DID stays in the activity log
    and in `audit_log`; jobs it queued keep running."""
    result = await session.execute(
        text("DELETE FROM copilot_routines WHERE id = :id AND user_id = :uid"),
        {"id": routine_id, "uid": user_id},
    )
    if not getattr(result, "rowcount", 0):
        raise ProblemError.not_found("Routine")


# --- firing -----------------------------------------------------------------------------------


def _ist_clock(instant: datetime) -> str:
    return instant.astimezone(IST).strftime("%H:%M")


async def _record_run(
    session: AsyncSession,
    *,
    routine: RoutineRow,
    slot_at: datetime,
    trigger: RunTrigger,
    status: Literal["queued", "skipped"],
    reason: str | None,
    job_id: UUID | None,
) -> UUID | None:
    """Claim the slot. None when this slot already has a run — the unique key is the
    guarantee that a slot fires once, whatever retried or overlapped."""
    value = (
        await session.execute(
            text(
                "INSERT INTO copilot_routine_runs (id, tenant_id, routine_id, slot_at, trigger, "
                "status, reason, job_id, created_at, updated_at) VALUES (:id, :tid, :rid, :slot, "
                ":trigger, :status, :reason, :job, now(), now()) "
                "ON CONFLICT (routine_id, slot_at) DO NOTHING RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": routine.tenant_id,
                "rid": routine.id,
                "slot": slot_at,
                "trigger": trigger,
                "status": status,
                "reason": None if reason is None else reason[:MAX_RUN_REASON],
                "job": job_id,
            },
        )
    ).scalar()
    return None if value is None else UUID(str(value))


@dataclass(frozen=True, slots=True)
class _Skip:
    """Why a run started no job, in the person's words, and whether the routine stops."""

    reason: str
    switch_off: bool = False


async def _start_job(session: AsyncSession, routine: RoutineRow) -> UUID | _Skip:
    """A job id, or why no job was started."""
    role = (
        await session.execute(
            text("SELECT role FROM memberships WHERE user_id = :uid"), {"uid": routine.user_id}
        )
    ).scalar()
    if role is None:
        return _Skip(
            "The person who set this up is no longer on the account, so it was switched off.",
            switch_off=True,
        )
    try:
        job = await jobs.create_job(
            session,
            tenant_id=routine.tenant_id,
            user_id=routine.user_id,
            goal=f"{routine.name}: {routine.instruction}",
            screen_route=ROUTINE_SCREEN_ROUTE,
        )
    except jobs.TooManyJobsError:
        return _Skip(
            f"You already had {jobs.MAX_ACTIVE_JOBS_PER_USER} tasks running, so this run was "
            "skipped."
        )
    return job.id


async def fire_due(session: AsyncSession, *, routine_id: UUID, now: datetime) -> str:
    """Fire one routine's due slot, if it is still due. Runs in the routine's TENANT session.

    `SKIP LOCKED`, so two ticks that both saw the routine as due do not queue behind each
    other: the second finds nothing to claim and returns. Returns what happened, for the
    tick's counts: `queued`, `skipped`, or `not_due`.
    """
    record = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM copilot_routines WHERE id = :id AND enabled "
                "AND next_run_at <= :now FOR UPDATE SKIP LOCKED"
            ),
            {"id": routine_id, "now": now},
        )
    ).first()
    if record is None:
        return "not_due"
    routine = _routine(record)
    slot = routine.next_run_at
    assert slot is not None  # `ck_copilot_routines_due_iff_enabled`
    upcoming = next_occurrence(routine.days, routine.at_minute, after=max(now, slot))

    outcome: UUID | _Skip
    if now - slot > LATE_LIMIT:
        outcome = _Skip(
            f"It was due at {_ist_clock(slot)} but could not start on time, so this run was "
            "skipped rather than run late."
        )
    else:
        outcome = await _start_job(session, routine)
    started = isinstance(outcome, UUID)
    switch_off = isinstance(outcome, _Skip) and outcome.switch_off
    await _record_run(
        session,
        routine=routine,
        slot_at=slot,
        trigger="schedule",
        status="queued" if started else "skipped",
        reason=outcome.reason if isinstance(outcome, _Skip) else None,
        job_id=outcome if isinstance(outcome, UUID) else None,
    )
    await session.execute(
        text(
            "UPDATE copilot_routines SET next_run_at = :next, enabled = :enabled, "
            "last_run_at = CASE WHEN :ran THEN :now ELSE last_run_at END, updated_at = now() "
            "WHERE id = :id"
        ),
        {
            "id": routine.id,
            "next": None if switch_off else upcoming,
            "enabled": not switch_off,
            "ran": started,
            "now": now,
        },
    )
    return "queued" if started else "skipped"


async def run_now(
    session: AsyncSession, *, routine_id: UUID, user_id: UUID, now: datetime
) -> RunRow:
    """Run a routine once, now, outside its schedule. The schedule is left as it was."""
    record = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM copilot_routines WHERE id = :id AND user_id = :uid "
                "FOR UPDATE"
            ),
            {"id": routine_id, "uid": user_id},
        )
    ).first()
    if record is None:
        raise ProblemError.not_found("Routine")
    routine = _routine(record)
    outcome = await _start_job(session, routine)
    if isinstance(outcome, _Skip):
        raise ProblemError(
            kind="conflict",
            code="copilot_routine_not_started",
            title="That routine could not start",
            detail=outcome.reason,
            remediation="Wait for a running task to finish, then try again.",
        )
    run_id = await _record_run(
        session,
        routine=routine,
        slot_at=now,
        trigger="manual",
        status="queued",
        reason=None,
        job_id=outcome,
    )
    await session.execute(
        text("UPDATE copilot_routines SET last_run_at = :now, updated_at = now() WHERE id = :id"),
        {"id": routine.id, "now": now},
    )
    return RunRow(
        id=run_id or uuid7(),
        routine_id=routine.id,
        slot_at=now,
        trigger="manual",
        status="queued",
        reason=None,
        job_id=outcome,
        job_status="queued",
        created_at=now,
    )


__all__ = [
    "IST",
    "LATE_LIMIT",
    "MAX_ROUTINES_PER_USER",
    "ROUTINE_SCREEN_ROUTE",
    "RUNS_PAGE_MAX",
    "WEEKDAYS",
    "RoutineRow",
    "RunRow",
    "Weekday",
    "create_routine",
    "days_mask",
    "days_of",
    "delete_routine",
    "fire_due",
    "list_routines",
    "list_runs",
    "next_occurrence",
    "read_routine",
    "run_now",
    "update_routine",
]
