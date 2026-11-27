"""What each inbound line did today, and who it still owes a call (W4.1, W4.2).

Counted only from what our call rows hold. A call is filed under the IST day of
`lens.CALL_AT` (when it connected, else when it arrived), test calls left out, as the
call log and the dashboard file it.

THE DAY'S THREE COUNTS match the call-log filters they link to, so a number and the list
behind it never disagree. `answered`: the call connected (status `completed`, the log's
`status=completed`). `missed`: it never connected (`lens.CALL_STATUS_GROUPS["missed"]`, the
log's `status=missed`). `call_back`: of the answered, those that ended with a call-back
booked or the business owing the caller something (`call_back_booked`, `needs_you`). A call
still ringing is in none of them.

WHO IS STILL OWED A CALL (`waiting`, and the list behind it). One row per person (the
caller's number, or the call-back number a hidden-caller forward gave, D-746) whose latest
call to the line in the last `OWED_WINDOW_DAYS` was missed, a hang-up (`hung_up_early`) or
a request, unless a later call with that number, either way, connected to a conversation,
or the call was marked handled.

WHAT "MISSED" CANNOT SEE. Whether the engine reports a caller who rang off before the agent
answered as a call at all is not known (ThinnestAI question Q2 in the 28 Nov 2026 teardown
plan, unanswered), so such a caller may be absent; the screen says so rather than implying
the list is complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from calevate_shared.calling_window import IST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.crm.lens import CALL_AT, CALL_STATUS_GROUPS, day_start

#: The `calls.status` values of a call that never connected: the call log's "missed".
NOT_REACHED: Final = CALL_STATUS_GROUPS["missed"]
#: The outcomes of a connected call that left the caller waiting on the business.
ASKED: Final = ("call_back_booked", "needs_you")
HUNG_UP: Final = "hung_up_early"
#: How far back the owed list looks: past it a call-back reads as a cold call, and
#: `crm.service.CALLBACK_WINDOW_DAYS` refuses one on an older call anyway.
OWED_WINDOW_DAYS: Final = 7
#: Most rows the owed list returns; the call log holds the rest.
OWED_SHOWN: Final = 50

Reason = Literal["not_answered", "hung_up_early", "asked"]

_REAL_INBOUND: Final = (
    "c.direction = 'inbound' AND NOT c.trial_call AND NOT c.paid_test_call "
    "AND c.forwarding_test_id IS NULL"
)

_TODAY_SQL: Final = f"""
SELECT c.inbound_line_id,
       count(*) FILTER (WHERE c.status = 'completed') AS answered,
       count(*) FILTER (WHERE c.status = 'completed' AND c.outcome_tag = ANY(:asked)),
       count(*) FILTER (WHERE c.status = ANY(:not_reached)) AS missed
FROM calls c
WHERE c.inbound_line_id IS NOT NULL AND {_REAL_INBOUND}
  AND {CALL_AT} >= :since AND {CALL_AT} < :until
GROUP BY c.inbound_line_id
"""

# The person is the caller's number, except on a forward that showed the business's own
# number (D-746), where it is the call-back number they gave, filed as the call's lead.
_PERSON: Final = "CASE WHEN c.caller_id_hidden THEN l.phone_e164 ELSE c.from_e164 END"


def _owed_sql(*, one_line: bool) -> str:
    """Each person's latest call per line, kept while they are still owed one."""
    line = "c.inbound_line_id = :lid" if one_line else "c.inbound_line_id IS NOT NULL"
    return f"""
WITH line_calls AS (
    SELECT c.id, c.inbound_line_id, {CALL_AT} AS called_at, c.status, c.outcome_tag,
           c.follow_up_state, {_PERSON} AS phone, l.name AS lead_name
    FROM calls c LEFT JOIN leads l ON l.id = c.lead_id
    WHERE {line} AND {_REAL_INBOUND} AND {CALL_AT} >= :since
      AND c.status NOT IN ('queued', 'ringing', 'in_progress')
), latest AS (
    SELECT DISTINCT ON (inbound_line_id, phone) *,
           count(*) OVER (PARTITION BY inbound_line_id, phone) AS tries
    FROM line_calls WHERE phone IS NOT NULL
    ORDER BY inbound_line_id, phone, called_at DESC, id DESC
)
SELECT o.id, o.called_at, o.status, o.outcome_tag, o.phone, o.lead_name, o.tries,
       o.inbound_line_id
FROM latest o
WHERE o.follow_up_state IS DISTINCT FROM 'resolved'
  AND (o.status = ANY(:not_reached) OR o.outcome_tag = ANY(:owed_outcomes))
  AND NOT EXISTS (
      SELECT 1 FROM calls k
      WHERE k.created_at >= :since AND COALESCE(k.started_at, k.created_at) > o.called_at
        AND k.status = 'completed' AND k.outcome_tag IS DISTINCT FROM '{HUNG_UP}'
        AND NOT k.trial_call AND NOT k.paid_test_call
        AND ((k.direction = 'inbound' AND k.from_e164 = o.phone)
             OR (k.direction = 'outbound' AND k.to_e164 = o.phone)))
"""


_OWED_ROWS_SQL: Final = f"""
SELECT w.*,
       (SELECT min(s.requested_at) FROM scheduled_callbacks s
        WHERE s.phone_e164 = w.phone AND s.status IN ('scheduled', 'dialing')),
       EXISTS (SELECT 1 FROM calls k WHERE k.direction = 'outbound' AND k.to_e164 = w.phone
               AND k.created_at > w.called_at
               AND k.status IN ('queued', 'ringing', 'in_progress'))
FROM ({_owed_sql(one_line=True)}) w
ORDER BY w.called_at DESC, w.id DESC
LIMIT :n
"""

_WAITING_SQL: Final = f"""
SELECT w.inbound_line_id, count(*) FROM ({_owed_sql(one_line=False)}) w
GROUP BY w.inbound_line_id
"""


@dataclass(frozen=True, slots=True)
class LineToday:
    line_id: UUID
    answered: int
    call_back: int
    missed: int
    #: People the line still owes a call, over `OWED_WINDOW_DAYS`.
    waiting: int


@dataclass(frozen=True, slots=True)
class Owed:
    call_id: UUID
    at: datetime
    reason: Reason
    #: Calls from this person to the line inside the window.
    tries: int
    name: str | None
    phone_e164: str
    #: A call-back to this number is booked for then (any door booked it).
    call_back_at: datetime | None
    #: A call to this number is being placed now.
    calling: bool


def ist_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def _owed_params(now: datetime | None) -> tuple[date, dict[str, object]]:
    since_day = ist_today(now) - timedelta(days=OWED_WINDOW_DAYS - 1)
    return since_day, {
        "since": day_start(since_day),
        "not_reached": list(NOT_REACHED),
        "owed_outcomes": [*ASKED, HUNG_UP],
    }


async def lines_today(
    session: AsyncSession, *, now: datetime | None = None
) -> tuple[date, list[LineToday]]:
    """Every line's counts for today in IST. A line with no calls and nobody waiting is
    absent; the caller reads it as zeros."""
    day = ist_today(now)
    counted = (
        await session.execute(
            text(_TODAY_SQL),
            {
                "since": day_start(day),
                "until": day_start(day + timedelta(days=1)),
                "asked": list(ASKED),
                "not_reached": list(NOT_REACHED),
            },
        )
    ).all()
    _since, params = _owed_params(now)
    waiting = {
        UUID(str(r[0])): int(r[1])
        for r in (await session.execute(text(_WAITING_SQL), params)).all()
    }
    days = {UUID(str(r[0])): (int(r[1]), int(r[2]), int(r[3])) for r in counted}
    out: list[LineToday] = []
    for line_id in sorted({*days, *waiting}, key=str):
        answered, call_back, missed = days.get(line_id, (0, 0, 0))
        out.append(
            LineToday(
                line_id=line_id,
                answered=answered,
                call_back=call_back,
                missed=missed,
                waiting=waiting.get(line_id, 0),
            )
        )
    return day, out


def _reason(status: str, outcome: str | None) -> Reason:
    if status in NOT_REACHED:
        return "not_answered"
    return "hung_up_early" if outcome == HUNG_UP else "asked"


async def owed(
    session: AsyncSession, line_id: UUID, *, now: datetime | None = None
) -> tuple[date, list[Owed]]:
    """The people this line still owes a call, newest first, and the IST day the window
    opens on."""
    since_day, params = _owed_params(now)
    rows = (
        await session.execute(text(_OWED_ROWS_SQL), {**params, "lid": line_id, "n": OWED_SHOWN})
    ).all()
    return since_day, [
        Owed(
            call_id=UUID(str(r[0])),
            at=r[1],
            reason=_reason(str(r[2]), r[3]),
            tries=int(r[6]),
            name=str(r[5]) if r[5] else None,
            phone_e164=str(r[4]),
            call_back_at=r[8],
            calling=bool(r[9]),
        )
        for r in rows
    ]


__all__ = [
    "ASKED",
    "NOT_REACHED",
    "OWED_SHOWN",
    "OWED_WINDOW_DAYS",
    "LineToday",
    "Owed",
    "ist_today",
    "lines_today",
    "owed",
]
