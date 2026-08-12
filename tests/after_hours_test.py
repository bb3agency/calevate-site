"""FLOWS §3's after-hours flag — the reader `agents.business_hours` never had.

FLOWS.md:100 is one sentence: *"agent runs 24/7 by default; `after_hours` flag set from
business_hours → dashboard 'after-hours captured' metric"*. The writer existed
(`admin.intake.record_intake`), the column existed (DATA-MODEL §3), and nothing on the
read side had ever opened it — the dashboard tile counted a hardcoded 09:00-21:00 IST
window, which is the right answer only for a client who happens to keep those hours.

The cases below are the ones that make a naive implementation wrong:

* a window that crosses midnight (18:00-02:00) — 01:00 is still INSIDE the previous
  day's window, and a same-day `opens <= t < closes` comparison says it is not;
* a day recorded closed (`null`) — after-hours all day, EXCEPT while the previous day's
  midnight-spanning window is still running;
* a day nobody filled in — `DayHours`' own docstring says "we do not open on Sunday"
  and "nobody filled Sunday in" are different answers, so the absent day is UNKNOWN and
  must not be counted either way;
* `business_hours` NULL — the FLOWS default is 24/7, so an agent with no hours recorded
  must never be reported as closed, and must not raise.

Timezone: the stored windows are IST wall clock (see the module docstring), so every
case here is written as a UTC instant and asserted through the IST offset — a test that
built naive local datetimes would pass against the bug it is here to catch.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from apps.api.admin import service as admin_service
from apps.api.agents.business_hours import count_after_hours_calls, is_after_hours
from apps.api.crm.service import dashboard
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_IST_OFFSET = timedelta(hours=5, minutes=30)

# 18:00-02:00 Saturday: a bar, and the shape that breaks same-day comparisons.
LATE_NIGHT = {
    "fri": {"opens": "18:00", "closes": "02:00"},
    "sat": {"opens": "18:00", "closes": "02:00"},
    "sun": None,  # closed
    # mon-thu deliberately absent: nobody filled them in.
}

CLINIC = {
    "mon": {"opens": "09:30", "closes": "18:00"},
    "tue": {"opens": "09:30", "closes": "18:00"},
    "wed": {"opens": "09:30", "closes": "18:00"},
    "thu": {"opens": "09:30", "closes": "18:00"},
    "fri": {"opens": "09:30", "closes": "18:00"},
    "sat": {"opens": "09:30", "closes": "13:00"},
    "sun": None,
}


def _ist(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """An IST wall-clock moment, handed over as the UTC instant the DB would store."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC) - _IST_OFFSET


# --- the pure reader ----------------------------------------------------------


def test_ordinary_day_inside_and_outside_the_window() -> None:
    # 2026-08-10 is a Monday.
    assert is_after_hours(CLINIC, _ist(2026, 8, 10, 11, 0)) is False
    assert is_after_hours(CLINIC, _ist(2026, 8, 10, 8, 0)) is True
    assert is_after_hours(CLINIC, _ist(2026, 8, 10, 19, 0)) is True
    # The boundaries: opens is inclusive, closes is exclusive.
    assert is_after_hours(CLINIC, _ist(2026, 8, 10, 9, 30)) is False
    assert is_after_hours(CLINIC, _ist(2026, 8, 10, 18, 0)) is True


def test_the_window_is_ist_not_the_servers_clock() -> None:
    """23:00 UTC on Sunday is 04:30 IST on Monday — before the clinic opens, and NOT
    the Sunday-closed answer a UTC-evaluated implementation would give."""
    sunday_2300_utc = datetime(2026, 8, 9, 23, 0, tzinfo=UTC)
    assert is_after_hours(CLINIC, sunday_2300_utc) is True
    # 04:00 UTC Monday = 09:30 IST Monday: open, though UTC says the day has barely begun.
    assert is_after_hours(CLINIC, datetime(2026, 8, 10, 4, 0, tzinfo=UTC)) is False


def test_a_window_that_crosses_midnight_is_still_open_after_midnight() -> None:
    """Saturday 18:00-02:00. 01:00 on SUNDAY belongs to Saturday's window, even though
    Sunday itself is recorded closed."""
    assert is_after_hours(LATE_NIGHT, _ist(2026, 8, 8, 19, 0)) is False  # sat 19:00
    assert is_after_hours(LATE_NIGHT, _ist(2026, 8, 9, 1, 0)) is False  # sun 01:00
    assert is_after_hours(LATE_NIGHT, _ist(2026, 8, 9, 2, 0)) is True  # closes exclusive
    assert is_after_hours(LATE_NIGHT, _ist(2026, 8, 8, 17, 59)) is True  # before opening


def test_a_day_recorded_closed_is_after_hours_all_day() -> None:
    assert is_after_hours(CLINIC, _ist(2026, 8, 9, 11, 0)) is True  # sunday, closed
    # Same day in the late-night shape, but outside the spill-over: still closed.
    assert is_after_hours(LATE_NIGHT, _ist(2026, 8, 9, 11, 0)) is True


def test_a_day_nobody_filled_in_is_unknown_not_closed() -> None:
    """`DayHours` distinguishes them on purpose; the flag must too."""
    assert is_after_hours(LATE_NIGHT, _ist(2026, 8, 10, 11, 0)) is None  # monday absent


def test_null_business_hours_never_declares_the_business_closed() -> None:
    """FLOWS §3: the agent runs 24/7 by default. Unknown is unknown, not shut."""
    assert is_after_hours(None, _ist(2026, 8, 10, 3, 0)) is None
    assert is_after_hours({}, _ist(2026, 8, 10, 3, 0)) is None


def test_malformed_hours_do_not_crash_the_reader() -> None:
    """The column is JSONB written by an admin form; a bad value degrades to unknown
    rather than taking a worker down mid-pipeline."""
    assert is_after_hours({"mon": {"opens": "nine", "closes": "18:00"}}, _ist(2026, 8, 10, 11)) is (
        None
    )
    assert is_after_hours({"mon": "09:30-18:00"}, _ist(2026, 8, 10, 11)) is None
    assert is_after_hours({"mon": {"opens": "09:30"}}, _ist(2026, 8, 10, 11)) is None


def test_a_naive_instant_is_refused_rather_than_guessed() -> None:
    """UTC in the DB, IST at the edge — an instant with no timezone has no answer."""
    try:
        is_after_hours(CLINIC, datetime(2026, 8, 10, 11, 0))
    except ValueError:
        return
    raise AssertionError("a naive datetime must not be silently treated as UTC or IST")


# --- the dashboard metric -----------------------------------------------------


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Night Owl Diagnostics",
        slug=f"afterhours-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _record_hours(
    session: AsyncSession, agent_id: uuid.UUID, hours: dict[str, object]
) -> None:
    """The column exactly as `admin.intake._hours_map` writes it.

    Written directly rather than through `record_intake`: that path is the WRITER, it
    has its own readiness rules about branches and escalation contacts, and this file
    is a test of the READER. `tests/intake_test.py` is where the stored shape is pinned
    to what the wizard produces — if these two ever disagree, that test is the one that
    says so.
    """
    await session.execute(
        text("UPDATE agents SET business_hours = CAST(:h AS jsonb) WHERE id = :aid"),
        {"h": json.dumps(hours), "aid": agent_id},
    )


async def _call(
    session: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, at: datetime
) -> None:
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
            "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
            "'completed', :at, now(), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "ecid": f"ah-{uuid.uuid4().hex}",
            "at": at,
        },
    )


async def test_the_after_hours_captured_metric_counts_by_the_clients_own_hours() -> None:
    """The tile FLOWS §3 names. A 20:00 call is after-hours for this clinic and inside
    a 09:00-21:00 hardcoded window — which is exactly the call the old count missed."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _record_hours(session, agent_id, CLINIC)
        await _call(session, tenant_id, agent_id, _ist(2026, 8, 10, 11, 0))  # mon, open
        await _call(session, tenant_id, agent_id, _ist(2026, 8, 10, 20, 0))  # mon, closed
        await _call(session, tenant_id, agent_id, _ist(2026, 8, 9, 11, 0))  # sun, closed
        counted = await count_after_hours_calls(session, since=_ist(2026, 8, 1, 0, 0))
    assert counted == 2, "one evening call and one Sunday call"


async def test_the_metric_ignores_agents_with_no_hours_recorded() -> None:
    """24/7 by default (FLOWS §3): an agent nobody gave hours to captures no
    'after-hours' calls, rather than every call it ever took."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _call(session, tenant_id, agent_id, _ist(2026, 8, 10, 3, 0))
        await _call(session, tenant_id, agent_id, _ist(2026, 8, 10, 11, 0))
        counted = await count_after_hours_calls(session, since=_ist(2026, 8, 1, 0, 0))
    assert counted == 0


# --- the tile itself ----------------------------------------------------------
#
# The reader existing is not the same as the dashboard using it. These two pin the
# WIRING, which is the half that was missing: a correct function nothing calls counts
# nothing, and the hardcoded window would have gone on answering forever.


async def test_the_tile_uses_the_clients_hours_and_says_that_it_did() -> None:
    """With hours recorded, the tile counts by them AND reports the basis.

    Every day is recorded closed, so the single call is after-hours whenever the suite
    happens to run — the alternative is a fixture that passes in August and fails the
    first time someone runs it on a Sunday.
    """
    tenant_id, agent_id = await _tenant()
    closed_all_week = dict.fromkeys(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
    async with tenant_session(tenant_id) as session:
        await _record_hours(session, agent_id, closed_all_week)
        await _call(session, tenant_id, agent_id, datetime.now(UTC) - timedelta(hours=1))
        tile = await dashboard(session)

    assert tile.after_hours_basis == "business_hours"
    assert tile.after_hours_captured_7d == 1


async def test_a_client_who_has_not_done_the_intake_gets_the_fallback_and_is_told_so() -> None:
    """The tile does not drop to zero for a client with no hours — it falls back to the
    09:00-21:00 IST window and admits that is what it did. A silent fallback would let
    a guess and a fact render identically."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _call(session, tenant_id, agent_id, _midnight_ist_within_the_week())
        tile = await dashboard(session)

    assert tile.after_hours_basis == "default_window"
    assert tile.after_hours_captured_7d == 1, "the fallback still counts a 02:00 call"


def _midnight_ist_within_the_week() -> datetime:
    """02:00 IST on a day inside the dashboard's 7-day window — outside 09:00-21:00 by
    either definition, so the assertion is about the BASIS, not about the clock."""
    yesterday = (datetime.now(UTC) + _IST_OFFSET - timedelta(days=1)).date()
    return _ist(yesterday.year, yesterday.month, yesterday.day, 2, 0)
