"""FLOWS §3's after-hours flag: the READER for `agents.business_hours`.

FLOWS.md:100 says it in one sentence — *"agent runs 24/7 by default; `after_hours` flag
set from business_hours → dashboard 'after-hours captured' metric; escalation rules can
differ after hours"*. `admin.intake.record_intake` has written the column since the
intake step landed; until this module, nothing had ever read it, and the dashboard tile
that the sentence names counted a HARDCODED 09:00-21:00 IST window instead (see
`crm.service.dashboard`) — the right answer only for a client who happens to keep those
hours, and wrong in both directions for the late-night clinic and the Sunday-closed
salon that D-38 sells this tile to.

**Whose timezone is the window in? IST — `Asia/Kolkata`, by name, never by a fixed
offset.**

The stored value is a human answer to a human question ("what time do you open?") typed
into the intake form by an operator sitting with an Indian SMB. It is wall-clock local
time, and it carries no zone of its own: `{"mon": {"opens": "09:30", "closes": "18:00"}}`
is 09:30 in the shop, not 09:30 UTC. Three facts make IST the correct and only
defensible reading:

1. Every tenant is an Indian SMB (BRD §1, Telugu-first), and India is one zone.
2. Neither `organizations` nor `agents` has a timezone column (DATA-MODEL §2/§3), so
   there is no per-tenant zone to prefer even if we wanted one. A tenant outside IST is
   a schema change plus a migration, not a default to guess at here.
3. The repo already made this choice everywhere else time meets a human: `crm.performance`
   renders its busiest-hours histogram `AT TIME ZONE 'Asia/Kolkata'`, and billing months
   are IST months. A second convention would put two different "days" on one dashboard.

`ZoneInfo("Asia/Kolkata")` rather than `+05:30` for the same reason `IST_HOUR_SQL` uses
the name: an offset is a fact about today, a zone is a fact about the calendar. India
has not changed its offset since 1945, but a comparison written as arithmetic is one
that silently encodes "the DB session is in UTC" — the exact bug this docstring exists
to keep out.

**The three answers.** `is_after_hours` returns a THREE-valued result, and the third
value is the point:

* `False` — the instant falls inside a recorded open window.
* `True`  — the instant falls outside every recorded window for a day whose hours we
  actually know (including a day recorded closed).
* `None`  — *we do not know*: `business_hours` is NULL/empty, or the relevant day has no
  entry. FLOWS §3's default is that the agent runs 24/7, so an agent nobody gave hours
  to must never be reported as shut; and `DayHours` itself draws the line — "we do not
  open on Sunday" and "nobody filled Sunday in" are different answers. Callers count
  `True`, and count nothing for `None`.

**Midnight-spanning windows.** `{"sat": {"opens": "18:00", "closes": "02:00"}}` means
Saturday evening until Sunday morning. 01:00 on Sunday is INSIDE Saturday's window even
when Sunday itself is recorded closed, so every evaluation looks at the previous day's
window as well as today's. A same-day `opens <= t < closes` comparison — the obvious
implementation — reports that bar as shut during its busiest hour.

`opens` is inclusive, `closes` is exclusive: a call landing exactly at closing time is
after-hours, which is the reading that makes "18:00" mean "we stop at 18:00".
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The zone the stored windows are written in. By NAME (see the module docstring).
BUSINESS_HOURS_TZ = ZoneInfo("Asia/Kolkata")

# `admin.intake.DAYS`' order, indexed the way `datetime.weekday()` counts: Monday = 0.
# Duplicated rather than imported: this module is the READ side and must not depend on
# the admin console's write side to answer a question during a call pipeline run.
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _window(raw: Any) -> tuple[time, time] | None:
    """One day's `{"opens": "09:30", "closes": "18:00"}` → the pair, or None if the
    value cannot be read as a window.

    The column is JSONB written by an admin form, so a malformed value must degrade
    rather than raise inside a worker mid-pipeline — and it degrades to UNKNOWN, not to
    closed. The stored `null` that means "closed" is recognised by the caller before it
    ever gets here; a shape we cannot parse is a shape we cannot draw conclusions from.
    """
    if not isinstance(raw, Mapping):
        return None
    opens, closes = raw.get("opens"), raw.get("closes")
    if not isinstance(opens, str) or not isinstance(closes, str):
        return None
    try:
        return time.fromisoformat(opens), time.fromisoformat(closes)
    except ValueError:
        return None


def _covers(window: tuple[time, time], at: time, *, from_previous_day: bool) -> bool:
    """Does `window` contain the local time `at`?

    A window whose `closes` is not after its `opens` spans midnight. Read from the day
    it STARTS on, it covers `opens..24:00`; read from the following day it covers
    `00:00..closes`. A window that does not span midnight covers nothing on the next
    day, which is why `from_previous_day` is not a symmetric flag.
    """
    opens, closes = window
    spans_midnight = closes <= opens
    if from_previous_day:
        return spans_midnight and at < closes
    if spans_midnight:
        return at >= opens
    return opens <= at < closes


def is_after_hours(business_hours: Mapping[str, Any] | None, at: datetime) -> bool | None:
    """Was `at` outside this agent's business hours? `None` when we cannot know.

    `at` is an instant — the timezone-aware `calls.started_at` the DB stores in UTC. It
    is converted to IST before anything is compared, because the stored window is IST
    wall clock (module docstring). A NAIVE datetime is refused rather than assumed: the
    two plausible assumptions (UTC, IST) are 5h30m apart and both are silent, which is
    precisely how a call at 03:00 gets filed as a lunchtime enquiry.
    """
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("is_after_hours needs an aware datetime; calls.started_at is timestamptz")
    if not business_hours:
        return None

    local = at.astimezone(BUSINESS_HOURS_TZ)
    today_key = DAYS[local.weekday()]
    yesterday_key = DAYS[(local.weekday() - 1) % 7]
    clock = local.timetz().replace(tzinfo=None)

    # Yesterday's window first: it is the one that can still be running past midnight,
    # and it wins even over a day recorded closed.
    spill = _window(business_hours.get(yesterday_key))
    if spill is not None and _covers(spill, clock, from_previous_day=True):
        return False

    if today_key not in business_hours:
        # Nobody filled this day in. Not open, not closed — unknown (FLOWS §3: 24/7 by
        # default), so the caller counts it as neither.
        return None
    raw_today = business_hours[today_key]
    if raw_today is None:
        return True  # recorded closed, and no window spilled over into it
    today = _window(raw_today)
    if today is None:
        return None  # stored shape we cannot read — unknown, never "closed"
    return not _covers(today, clock, from_previous_day=False)


async def count_after_hours_calls(session: AsyncSession, *, since: datetime) -> int:
    """The "after-hours captured" tile (FLOWS §3, BRD §2, SURFACES §3), per agent hours.

    Evaluated in Python rather than SQL deliberately. The midnight-spanning rule above
    needs the PREVIOUS day's window, which in SQL is a self-join against a JSONB object
    keyed by weekday name — a query nobody can read and only one place would use, and
    the arithmetic would then exist twice with two chances to disagree.

    **TWO QUERIES, NOT A JOIN, and that is the whole change here.** This used to join
    `agents` to `calls` and select `a.business_hours` beside every call row, so the
    tenant's JSONB opening hours came back once PER CALL — the same few hundred bytes
    repeated across the window, on an endpoint the dashboard polls (D-24). The hours are
    a property of the AGENT, and there are a handful of agents; reading them once and
    the calls separately transports the same information with the blob sent once.

    What that does NOT do is make the row set constant, and it is worth being exact about
    what bounds it: the second query still returns one row per call in the window. That is
    bounded by PLATFORM CAPACITY rather than by the tenant's history — `PLATFORM_LINES_TOTAL`
    is 10 concurrent lines, so the whole platform cannot produce more than roughly 34k
    calls in seven days — and each row is now a uuid and a timestamp. It is a real ceiling
    with a number attached, which is what the previous shape did not have.

    Runs inside the caller's tenant-scoped session, so RLS decides which agents and which
    calls are visible — this function never widens that (hard rule 1). The `agent_id =
    ANY(...)` predicate is therefore a narrowing on top of RLS, never a substitute: it is
    what keeps calls taken by an agent with no recorded hours out of the transport, since
    those contribute zero by definition.

    It counts only `True`: an agent with no hours recorded contributes zero, not
    everything.
    """
    hours: dict[UUID, Any] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                text("SELECT id, business_hours FROM agents WHERE business_hours IS NOT NULL")
            )
        ).all()
    }
    if not hours:
        # No agent has hours, so every call is UNKNOWN rather than after-hours, and the
        # calls query would be `= ANY('{}')` — a round trip that can only return nothing.
        return 0
    rows = (
        await session.execute(
            text(
                "SELECT agent_id, started_at FROM calls "
                "WHERE started_at >= :since AND agent_id = ANY(:agents)"
            ),
            {"since": since, "agents": list(hours)},
        )
    ).all()
    return sum(
        1 for agent_id, started_at in rows if is_after_hours(hours[agent_id], started_at) is True
    )


__all__ = ["BUSINESS_HOURS_TZ", "DAYS", "count_after_hours_calls", "is_after_hours"]
