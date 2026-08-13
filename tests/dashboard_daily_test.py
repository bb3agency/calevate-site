"""`DashboardOut.daily_7d` — the 7-day stacked bar chart's series.

The chart is the centrepiece of the client dashboard, and the two ways a per-day series
goes quietly wrong are the two things pinned here:

* **a silent day going missing.** `GROUP BY day` over the calls table answers only the
  days that HAVE calls, so a quiet Sunday simply is not in the list — and a chart that
  renders whatever the server sent draws six bars for a week, or worse, slides every
  label one day left. The server zero-fills, exactly as `busiest_hours_ist` does with
  its 24 hours, and the test below deletes a day's worth of calls from the middle of
  the week to prove it.
* **parts that do not add up.** The bar is drawn as stacked segments; if the class
  counts sum to less than `total` the segments do not reach the top and nobody can say
  whether that gap is a live call or a dropped row. The classes PARTITION
  `calls.status`, which is asserted twice — against the CHECK constraint's own tuple
  (so a ninth status fails CI rather than unbalancing a bucket) and against real rows.

Timezone: buckets are IST CALENDAR DAYS. Every instant here is written as IST wall
clock and handed over as the UTC instant the column stores, because the bug this guards
against — bucketing by the UTC date — is invisible to a test that builds its fixtures in
UTC. An Indian working day runs 18:30-18:30 UTC, so the evening half of every one of
them lands on the previous UTC date.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from apps.api.admin import service as admin_service
from apps.api.crm.models import CALL_STATUSES
from apps.api.crm.schemas import DashboardDayOut
from apps.api.crm.service import DAILY_CALL_CLASSES, DASHBOARD_DAYS, dashboard
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_IST_OFFSET = timedelta(hours=5, minutes=30)


def _today_ist() -> date:
    return (datetime.now(UTC) + _IST_OFFSET).date()


def _ist(day: date, hour: int, minute: int = 0) -> datetime:
    """An IST wall-clock moment on `day`, as the UTC instant the DB would store."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - _IST_OFFSET


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Seven Day Motors",
        slug=f"daily7-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _call(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    at: datetime,
    status: str,
) -> None:
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
            "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
            ":status, :at, now(), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "ecid": f"d7-{uuid.uuid4().hex}",
            "at": at,
            "status": status,
        },
    )


def _by_date(series: list[DashboardDayOut]) -> dict[date, DashboardDayOut]:
    return {bucket.ist_date: bucket for bucket in series}


# --- the partition ------------------------------------------------------------
#
# Pure, no database: it is a claim about two tuples of strings, and it is the claim that
# makes every arithmetic assertion below possible.


def test_the_classes_partition_every_status_the_system_writes() -> None:
    """Every value the `status_enum` CHECK allows belongs to exactly one chart class.

    This is what "the parts sum to the total" rests on. Adding a ninth status to
    `CALL_STATUSES` without giving it a class would leave its calls counted in `total`
    and in nothing else — every bucket short by an unexplained amount, on a chart whose
    whole job is to be checkable by eye. That failure is silent in production and loud
    here.
    """
    classed = [status for statuses in DAILY_CALL_CLASSES.values() for status in statuses]

    assert sorted(classed) == sorted(CALL_STATUSES), "a status is unclassified or invented"
    assert len(classed) == len(set(classed)), "a status is counted in two classes"


# --- the zero-fill ------------------------------------------------------------


async def test_a_day_with_no_calls_is_a_zero_bucket_not_a_missing_one() -> None:
    """The week always has seven buckets, oldest first, whatever the calls table holds.

    The quiet day is put in the MIDDLE of the week on purpose: a series that simply
    dropped it would still be plausible at either end (a client who started on Tuesday),
    and would still be seven long if the implementation padded from whichever end it
    found first.
    """
    tenant_id, agent_id = await _tenant()
    today = _today_ist()
    quiet_day = today - timedelta(days=3)

    async with tenant_session(tenant_id) as session:
        for back in range(DASHBOARD_DAYS):
            day = today - timedelta(days=back)
            if day == quiet_day:
                continue
            await _call(session, tenant_id, agent_id, at=_ist(day, 12), status="completed")
        series = (await dashboard(session)).daily_7d

    assert len(series) == DASHBOARD_DAYS
    # Oldest first, contiguous, ending today. The equality is against a Python-computed
    # IST date: a run straddling IST midnight (18:30 UTC) would see the DB advance a day
    # after this list was built. Accepted — the alternative is an assertion that cannot
    # tell a week ending today from a week ending last month.
    assert [bucket.ist_date for bucket in series] == [
        today - timedelta(days=back) for back in range(DASHBOARD_DAYS - 1, -1, -1)
    ]

    quiet = _by_date(series)[quiet_day]
    assert quiet.total == 0
    assert (quiet.completed, quiet.no_answer, quiet.failed, quiet.in_flight) == (0, 0, 0, 0)
    # The point of the zero-fill: the silent day is a fact the server stated, and every
    # other day still answered its own count rather than being shifted into the hole.
    assert all(bucket.total == 1 for bucket in series if bucket.ist_date != quiet_day)


# --- the arithmetic -----------------------------------------------------------


async def test_the_class_counts_sum_to_the_bucket_total() -> None:
    """Every status the system writes lands in a class, on a real bucket.

    One call per status, all on one day, so a status quietly dropped shows up as a bar
    whose segments do not reach its own top.
    """
    tenant_id, agent_id = await _tenant()
    day = _today_ist() - timedelta(days=2)

    async with tenant_session(tenant_id) as session:
        for status in CALL_STATUSES:
            await _call(session, tenant_id, agent_id, at=_ist(day, 11), status=status)
        series = (await dashboard(session)).daily_7d

    for bucket in series:
        assert bucket.completed + bucket.no_answer + bucket.failed + bucket.in_flight == (
            bucket.total
        ), f"{bucket.ist_date} does not add up"

    counted = _by_date(series)[day]
    assert counted.total == len(CALL_STATUSES)
    assert counted.completed == 1  # completed
    assert counted.no_answer == 3  # no_answer + busy + voicemail
    assert counted.failed == 1  # failed
    assert counted.in_flight == 3  # queued + ringing + in_progress
    # And the week's totals are the week's calls — nothing double-counted into a
    # neighbouring day by the join.
    assert sum(bucket.total for bucket in series) == len(CALL_STATUSES)


# --- the calendar -------------------------------------------------------------


async def test_buckets_are_ist_calendar_days_not_utc_ones() -> None:
    """00:30 and 23:30 IST on one day are one bucket, though they straddle a UTC date.

    A UTC-bucketed implementation files the 00:30 call under the day before (19:00 UTC)
    and the 23:30 one under the correct date, so this day reads 1 and its neighbour
    reads 1 — the shape that makes an owner's Monday morning rush show up on Sunday.
    """
    tenant_id, agent_id = await _tenant()
    day = _today_ist() - timedelta(days=2)

    async with tenant_session(tenant_id) as session:
        await _call(session, tenant_id, agent_id, at=_ist(day, 0, 30), status="completed")
        await _call(session, tenant_id, agent_id, at=_ist(day, 23, 30), status="completed")
        series = (await dashboard(session)).daily_7d

    buckets = _by_date(series)
    assert buckets[day].total == 2, "the IST day runs 00:00-24:00 IST, not 00:00-24:00 UTC"
    assert buckets[day - timedelta(days=1)].total == 0
    assert buckets[day + timedelta(days=1)].total == 0


async def test_a_call_that_was_never_dialled_is_in_no_bucket() -> None:
    """`started_at IS NULL` has no calendar day, so it cannot be given one.

    Counting it as "today" would make a queued campaign look like a day's traffic that
    never happened.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                "'queued', now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"d7-null-{uuid.uuid4().hex}",
            },
        )
        series = (await dashboard(session)).daily_7d

    assert sum(bucket.total for bucket in series) == 0
    assert sum(bucket.in_flight for bucket in series) == 0


# --- tenancy ------------------------------------------------------------------


async def test_the_series_never_shows_another_tenants_day() -> None:
    """No new table, so no new policy — but the chart is a new READER of `calls`, and a
    CTE is exactly the shape where someone assumes the policy stopped applying. It does
    not: `days` is a bare `generate_series` and `recent` reads `calls` under the same
    FORCEd policy every other query in this module relies on."""
    mine, my_agent = await _tenant()
    theirs, their_agent = await _tenant()
    day = _today_ist() - timedelta(days=1)

    async with tenant_session(theirs) as session:
        for _ in range(3):
            await _call(session, theirs, their_agent, at=_ist(day, 15), status="completed")

    async with tenant_session(mine) as session:
        await _call(session, mine, my_agent, at=_ist(day, 15), status="failed")
        series = (await dashboard(session)).daily_7d

    mine_that_day = _by_date(series)[day]
    assert mine_that_day.total == 1, "the neighbouring tenant's three calls leaked in"
    assert mine_that_day.failed == 1
    assert mine_that_day.completed == 0
