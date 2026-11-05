"""The call back a caller asked for, booked after the call when the call itself booked none.

In a call the agent books a call back through its call-back action, which reads the time
back to the caller and books it (`apps/api/worker/in_call_tools.book_callback_for`). A caller
who says "I'll talk to you later" and hangs up never reaches that action, so the request was
read (`calls.callback_requested`), turned into "Needs you", and nothing rang them back
(4 Nov 2026 call review). This books it, once per call, after the reading.

WHEN, in this order:

1. the time the caller named, as the reading resolved it against the call's date and
   `calling_window.resolve_slot` accepts it; a named time outside the calling window moves to
   the next lawful one, as the in-call action offers it;
2. otherwise the next day at the hour of this call, because they answered at that hour,
   clamped to `DEFAULT_EARLIEST`..`DEFAULT_LATEST` so the dispatcher's two-hour grace
   (`callbacks.service.GRACE`) still falls inside the 21:00 close.

Dialers configure this per disposition rather than share one default: JustCall's "Callback
Requested" disposition sets a reminder call two days out
(https://justcall.io/product/call-disposition/), and Genesys schedules callbacks per
disposition with a configured delay, none by default
(help.genesys.com/cic/.../auto_scheduled_callbacks.htm). Next day at the hour they answered
is our choice, not an industry rule: soon enough that the conversation is remembered, and
at an hour this person has already shown they pick up.

What it does NOT do:

- book when the same reading says only the caller has something to do (`next_step_by`
  is `caller`): the caller said they would call, not that they want to be called;
- book on a trial account (no call back can ring until the account pays, founder
  decision 1), on a call whose caller opted out, or where a call back of this call already
  exists in any state (a cancelled one is the caller's own "don't ring me back");
- write a consent row. The in-call booking writes one because the caller confirmed a time
  read back to them (`record_callback_request_consent`); this is a model's reading of the
  conversation, so the dial gate decides on what is already on file when the time comes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Final, Literal
from uuid import UUID

from calevate_shared.calling_window import (
    IST,
    MIN_LEAD,
    Slot,
    SlotRefusal,
    resolve_slot,
)
from calevate_shared.extraction import ExtractionOutput
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.callbacks import service as callbacks
from apps.api.campaigns.scheduling import first_dial_not_before
from apps.api.compliance.trial_access import restricting_trial
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)


#: The default slot's bounds, IST. The latest leaves the two-hour grace inside 21:00.
DEFAULT_EARLIEST: Final = time(10, 0)
DEFAULT_LATEST: Final = time(19, 0)

#: What the agent is told the call back is about when it rings. No caller words: the reading
#: holds no note of its own, and a note goes into the agent's instructions.
AFTER_CALL_NOTE: Final = "They asked to continue the conversation on another call."

TimeFrom = Literal["caller", "default"]


@dataclass(frozen=True, slots=True)
class Booked:
    callback_id: UUID
    at: datetime
    time_from: TimeFrom


def default_slot(call_at: datetime, *, now: datetime) -> datetime:
    """The next day at the hour of the call, inside `DEFAULT_EARLIEST`..`DEFAULT_LATEST` IST.

    Never earlier than `now + MIN_LEAD`, for a call re-read long after it ended.
    """
    at_ist = call_at.astimezone(IST)
    clock = min(
        max(at_ist.time().replace(second=0, microsecond=0), DEFAULT_EARLIEST), DEFAULT_LATEST
    )
    slot = datetime.combine(at_ist.date() + timedelta(days=1), clock, tzinfo=IST)
    floor = now + MIN_LEAD
    if slot < floor:
        floor_ist = floor.astimezone(IST)
        slot = datetime.combine(floor_ist.date() + timedelta(days=1), clock, tzinfo=IST)
    return slot.astimezone(UTC)


def caller_slot(
    extraction: ExtractionOutput, call_at: datetime, *, now: datetime
) -> datetime | None:
    """The time the caller named, as a bookable instant; None when they named none or it
    cannot be booked (gone by, more than 30 days out, unreadable).

    A time with no day is the next such time after the call; a day with no time is that day
    at the call's own hour, inside the default bounds.
    """
    day, clock = extraction.requested_callback_date, extraction.requested_callback_time
    if day is None and clock is None:
        return None
    call_ist = call_at.astimezone(IST)
    if clock is None:
        hour = min(max(call_ist.time(), DEFAULT_EARLIEST), DEFAULT_LATEST)
        clock = f"{hour.hour:02d}:{hour.minute:02d}"
    if day is None:
        candidate = datetime.combine(call_ist.date(), time.fromisoformat(clock), tzinfo=IST)
        day = (
            (candidate if candidate > call_ist else candidate + timedelta(days=1))
            .date()
            .isoformat()
        )
    answer: Slot | SlotRefusal = resolve_slot(day, clock, now=now)
    if isinstance(answer, Slot):
        return answer.at_utc
    if answer.alternative is not None:
        return answer.alternative.at_utc
    return None


async def _already_has_one(
    session: AsyncSession, call_id: UUID, engine_call_id: str | None
) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM scheduled_callbacks "
                    "WHERE source_call_id = :cid OR (CAST(:ecid AS text) IS NOT NULL "
                    "AND source_execution_id = :ecid))"
                ),
                {"cid": call_id, "ecid": engine_call_id},
            )
        ).scalar()
    )


async def _campaign_hours(session: AsyncSession, call_id: UUID) -> dict[str, object] | None:
    hours = (
        await session.execute(
            text(
                "SELECT g.calling_hours FROM calls c JOIN campaigns g ON g.id = c.campaign_id "
                "WHERE c.id = :cid"
            ),
            {"cid": call_id},
        )
    ).scalar()
    return hours if isinstance(hours, dict) else None


async def book_requested_callback(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    engine_call_id: str | None,
    phone_e164: str | None,
    call_at: datetime,
    extraction: ExtractionOutput,
    opted_out: bool,
    now: datetime | None = None,
) -> Booked | None:
    """Book the call back this reading says the caller wants; None when none is booked."""
    if not extraction.callback_requested or opted_out or phone_e164 is None:
        return None
    if extraction.next_step_by == "caller":
        # The same reading says only the caller has something left to do: "I'll call you"
        # read as "call me back" (L5-17). An unwanted outbound call costs more than a
        # missed one the owner still sees as "Needs you".
        return None
    if await restricting_trial(session, tenant_id=tenant_id) is not None:
        return None
    if await _already_has_one(session, call_id, engine_call_id):
        return None
    moment = now or datetime.now(UTC)
    named = caller_slot(extraction, call_at, now=moment)
    at = named if named is not None else default_slot(call_at, now=moment)
    # A campaign's own hours may be narrower than the platform's window.
    at = first_dial_not_before(at, await _campaign_hours(session, call_id))
    time_from: TimeFrom = "caller" if named is not None else "default"
    prefix = (
        callbacks.AFTER_CALL_PREFIX if named is not None else callbacks.AFTER_CALL_DEFAULT_PREFIX
    )
    booked = await callbacks.book(
        session,
        callback_id=uuid7(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_call_id=call_id,
        source_execution_id=f"{prefix}{call_id}",
        lead_id=None,
        phone_e164=phone_e164,
        requested_at=at,
        booked_at=moment,
        note=AFTER_CALL_NOTE,
        language=None,
    )
    if booked is None:
        return None
    log.info(
        "after_call_callback_booked",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "callback_id": str(booked[0]),
            "time_from": time_from,
        },
    )
    return Booked(callback_id=booked[0], at=booked[1], time_from=time_from)


__all__ = [
    "AFTER_CALL_NOTE",
    "DEFAULT_EARLIEST",
    "DEFAULT_LATEST",
    "Booked",
    "book_requested_callback",
    "caller_slot",
    "default_slot",
]
