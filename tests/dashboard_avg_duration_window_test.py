"""The dashboard's average call length is a SEVEN-DAY average, and says so (D-215).

`DashboardOut.avg_duration_s` was the one tile on that screen with no time bound at all:
`avg(duration_s) FILTER (WHERE status = 'completed') FROM calls`, over the account's whole
history, on an endpoint the dashboard polls (D-24), against a table nothing ever deletes
from. No index fixes an aggregate that must visit every row — the fix is a window, and a
window redefines a number a client reads, which is why it also renamed the field.

Two behaviours are pinned, and the first is the one that fails without the fix:

* a call OUTSIDE the window does not move the number. The fixture puts a very long call
  30 days back and a short one inside the week, so an unwindowed average and a windowed
  one cannot produce the same value — an off-by-anything is a different number, not a
  rounding difference.
* the STATEMENT carries the bound, not three of its four columns. `calls_today`,
  `calls_7d` and the after-hours count moved under one `WHERE started_at >= :since` in
  the same change, which is what lets `ix_calls_tenant_started` serve the whole tile
  (27.2 ms / 1,017 buffers → 0.84 ms / 61 on a 45,000-call tenant). A revert that
  windowed only the average would leave that plan on the floor while every assertion
  above it stayed green, so the SQL is asserted too.

NOT pinned here: that seven is the right number. That is a product decision argued at the
call site (every other bounded figure on the screen is seven days, and the thirty-day
reading of the same statistic already exists on the performance tab with its own window
in the response). A test asserting "7" would only restate the constant.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

from apps.api.admin import service as admin_service
from apps.api.crm.schemas import DashboardOut
from apps.api.crm.service import DASHBOARD_DAYS, dashboard
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Deliberately far apart. An average that accidentally includes the old call lands
# somewhere near 1,830s; one that correctly excludes it is exactly 60.
INSIDE_DURATION_S = 60
OUTSIDE_DURATION_S = 3600


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Window Motors",
        slug=f"avgwin-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _completed_call(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    at: datetime,
    duration_s: int,
) -> None:
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
            "started_at, duration_s, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
            "'inbound', 'completed', :at, :dur, now(), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "ecid": f"avgwin-{uuid.uuid4().hex}",
            "at": at,
            "dur": duration_s,
        },
    )


async def test_a_call_older_than_the_window_does_not_move_the_average() -> None:
    """RED WITHOUT THE FIX: the unwindowed average answers 1830, not 60.

    The old call is a MONTH back rather than eight days: eight days would test the
    boundary, which a rewrite could pass by accident with an off-by-one, and the claim
    being made here is about the window existing at all.
    """
    tenant_id, agent_id = await _tenant()
    now = datetime.now(UTC)

    async with tenant_session(tenant_id) as session:
        await _completed_call(
            session,
            tenant_id,
            agent_id,
            at=now - timedelta(days=30),
            duration_s=OUTSIDE_DURATION_S,
        )
        await _completed_call(
            session, tenant_id, agent_id, at=now - timedelta(days=2), duration_s=INSIDE_DURATION_S
        )
        out = await dashboard(session)

    assert out.avg_duration_s_7d == INSIDE_DURATION_S, (
        "the average included a call from outside the window — the tile is back to "
        "averaging the account's whole history (D-215)"
    )


async def test_an_account_whose_only_calls_are_old_reports_no_average() -> None:
    """None, not zero, and not last month's number.

    "No completed calls this week" is a real state and the tile renders it as an em dash.
    A zero here would read as "your calls averaged nothing", and the pre-fix value would
    read as this week's activity — both are claims about the world that the data does not
    support.
    """
    tenant_id, agent_id = await _tenant()
    now = datetime.now(UTC)

    async with tenant_session(tenant_id) as session:
        await _completed_call(
            session,
            tenant_id,
            agent_id,
            at=now - timedelta(days=30),
            duration_s=OUTSIDE_DURATION_S,
        )
        out = await dashboard(session)

    assert out.avg_duration_s_7d is None


async def test_the_other_tiles_did_not_change_meaning() -> None:
    """The window moved onto the statement, so every other column had to keep its answer.

    `calls_today` in particular: it used to carry its own `started_at::date = :today`
    FILTER over an unbounded scan and now carries it inside a seven-day bound. Today is a
    subset of the last seven days, so the number is unchanged — asserted rather than
    assumed, because "obviously a subset" is how off-by-one windows ship.
    """
    tenant_id, agent_id = await _tenant()
    now = datetime.now(UTC)

    async with tenant_session(tenant_id) as session:
        await _completed_call(session, tenant_id, agent_id, at=now, duration_s=INSIDE_DURATION_S)
        await _completed_call(
            session, tenant_id, agent_id, at=now - timedelta(days=3), duration_s=INSIDE_DURATION_S
        )
        await _completed_call(
            session,
            tenant_id,
            agent_id,
            at=now - timedelta(days=30),
            duration_s=OUTSIDE_DURATION_S,
        )
        out = await dashboard(session)

    assert out.calls_today == 1, "today's count changed when the window moved"
    assert out.calls_7d == 2, "the 7-day count picked up the month-old call"


def test_the_bound_is_on_the_statement_so_the_index_can_serve_it() -> None:
    """The plan is the point, and only the SQL's SHAPE can pin it.

    `ix_calls_tenant_started` is `(tenant_id, started_at DESC NULLS LAST, id DESC)`
    (D-206). It serves this tile only while the seven-day bound is a WHERE clause the
    planner can turn into an index condition; written as four `FILTER`s over
    `FROM calls`, the same numbers come back from a full scan of the tenant's history.
    Measured: 27.2 ms / 1,017 buffers → 0.84 ms / 61 buffers, 45,000 tenant calls.
    """
    source = inspect.getsource(dashboard)
    assert "FROM calls WHERE started_at >= :since" in source, (
        "the dashboard's counts statement lost its WHERE clause; the numbers may still "
        "be right and the scan is unbounded again (D-215)"
    )


def test_the_field_name_states_its_window_like_every_other_bounded_number() -> None:
    """A renamed field is the client-facing half of a redefined number.

    `DashboardOut` spells the window into `calls_7d`, `leads_new_7d`,
    `after_hours_captured_7d` and `daily_7d`. The average was the only bounded figure
    whose name said nothing, because until D-215 it had nothing to say. Restoring the
    bare name would put the screen back to rendering two different statistics
    identically.
    """
    fields = DashboardOut.model_fields
    assert "avg_duration_s_7d" in fields
    assert "avg_duration_s" not in fields, (
        "the unwindowed name is back on the dashboard model; `PerformanceOut` is the one "
        "that legitimately carries it, because its window is a field on the response"
    )
    assert DASHBOARD_DAYS == 7, "the field name and the window it names have drifted apart"
