"""Scheduled campaign starts — `campaigns.schedule` and the tick that fires it.

`campaigns_test.py` proves the launch gate for a human pressing Launch.
`campaign_dispatch_audit_test.py` proves the §3 paperwork is re-asked while a campaign
runs. This file attacks the seam scheduling adds, and there are exactly four ways it
could be wrong in a way that matters:

1. **The gate could end up running at SCHEDULE time instead of FIRE time.** A campaign
   scheduled on Friday and started on Monday can have crossed a DNC addition, a spend
   cap, a KYC expiry, a withdrawn DLT template or the platform halt in between. A gate
   at the moment a human picked a date is a bypass wearing a clock (hard rule 5), so the
   central test here schedules a campaign while everything is GREEN, breaks a §3
   condition afterwards, and requires the tick to refuse.

2. **A schedule could fire twice.** The dispatch tick's lease fails open on a Redis
   error by design, so two ticks CAN overlap, and each would read the same campaign as
   due. Two ticks run concurrently here and the campaign must launch exactly once.

3. **An IST time could be silently treated as UTC.** "Monday 10am" meant by a client in
   Hyderabad is 04:30Z. Read as UTC it becomes 15:30 IST — or, for an evening slot,
   02:30 IST, outside TRAI's window entirely. Both the storage instant and the refusal
   of a datetime with no offset are pinned.

4. **A start could be confused with a dial.** `calling_hours` is a per-day window
   enforced per dial; a schedule is a one-time START. A campaign whose start fires at
   22:00 must become `running` and dial nobody.

Nothing here uses a test-only branch or a bypass flag. Blocked states are produced by
writing the rows production writes; the clock is moved by the two seams production
already has — `compliance.service.ist_now` for the calling window and the `now`
parameter `fire_schedule` takes from its caller.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import scheduling, service
from apps.api.campaigns.scheduling import (
    GRACE,
    MAX_HORIZON,
    DueSchedule,
    due_schedules,
    fire_schedule,
    first_dial_not_before,
    schedule_campaign,
    unschedule_campaign,
)
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import ACTIVE_STATUSES, dispatch_campaign_tick
from sqlalchemy import text

# 11:00 IST on 2026-08-11 — inside the platform window, so a refusal is never the clock.
NOON_IST = datetime(2026, 8, 11, 5, 30, tzinfo=UTC)
IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TZ = timezone(IST_OFFSET)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: NOON_IST + IST_OFFSET)


@pytest.fixture(autouse=True)
def _roomy_platform_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared outbound pool is platform-wide, and this suite is not the only thing
    on the database. Pinning it above anything here dials keeps FLOWS §5 rule 1 from
    deciding the outcome of a test about scheduling. Rule 1 is asserted in
    `dispatch_scale_test.py`, not here."""
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10_000)


# --------------------------------------------------------------------------- fixtures

# Tenants this module created, so the fixture below can put them back to sleep.
_TENANTS: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
async def _leave_the_platform_quiet() -> AsyncIterator[None]:
    """Cancel every campaign this module started or scheduled, after each test.

    Not tidiness. `tests/dispatch_scale_test.py` asserts D-57's actual property — that a
    dispatch tick opens NO session for a tenant with nothing to dial — against whatever
    the shared development database happens to hold. A suite that leaves twenty
    permanently-due schedules behind makes twenty tenants permanently dispatchable, and
    the next suite to measure the tick's cost measures this one's litter instead. The
    tests that deliberately rewind a start into the past are exactly the ones that would
    leak.
    """
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'cancelled', schedule = NULL, "
                    "updated_at = now() WHERE status IN ('scheduled', 'running')"
                )
            )
            await session.execute(
                text(f"UPDATE calls SET status = 'completed' WHERE status IN {ACTIVE_STATUSES!r}")
            )
    _TENANTS.clear()


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent is live, published and DLT-registered — launch-ready."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Sched Motors",
        slug=f"sched-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_sched_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        # The routing bridge `dispatch_scan()` enumerates. Without it the tick cannot
        # see this tenant at all, scheduled campaign or not.
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    async with tenant_session(tenant_id) as session:
        await service.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Sched Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _ready_campaign(
    *,
    calling_hours: dict[str, str] | None = None,
    phones: tuple[str, ...] = ("9876500001", "9876500002"),
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant, agent, campaign) — a promotional campaign that would launch right now."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        number_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, created_at, "
                "updated_at) VALUES (:id, :tid, :e, '140', 'registered', now(), now())"
            ),
            {"id": number_id, "tid": tenant_id, "e": f"+9180{uuid.uuid4().int % 10**8:08d}"},
        )
        template_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
        )
        campaign_id = await service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Diwali offers",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=3,
            calling_hours=calling_hours,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
        )
    return tenant_id, agent_id, campaign_id


async def _status(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> tuple[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, schedule FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).first()
    assert row is not None
    return str(row[0]), row[1]


async def _launch_audit_count(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE object_id = :c "
                        "AND action = 'campaign.launched'"
                    ),
                    {"c": str(campaign_id)},
                )
            ).scalar()
            or 0
        )


# ------------------------------------------------------------------- IST at the edge


async def test_an_ist_start_is_stored_as_the_instant_it_names_not_the_digits() -> None:
    """10:00 IST is 04:30Z. Stored as 10:00Z the campaign would start — and, worse,
    begin dialling — at 15:30 IST; an evening slot read the same way lands at 02:30 IST,
    outside TRAI's window entirely."""
    tenant_id, _, campaign_id = await _ready_campaign()
    # Exactly what the browser sends: the wall clock the client picked, with the +05:30
    # offset attached.
    picked_ist = datetime(2026, 8, 17, 10, 0, tzinfo=IST_TZ)

    async with tenant_session(tenant_id) as session:
        recorded = await schedule_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id, start_at=picked_ist
        )

    picked = datetime(2026, 8, 17, 4, 30, tzinfo=UTC)
    assert recorded.start_at == picked
    assert recorded.start_at.hour == 4 and recorded.start_at.minute == 30, (
        "10:00 IST must be stored as 04:30Z, not as 10:00Z"
    )
    status, stored = await _status(tenant_id, campaign_id)
    assert status == "scheduled"
    assert datetime.fromisoformat(str(stored["start_at"])) == picked
    assert stored["kind"] == "one_time"


async def test_a_start_time_with_no_timezone_is_refused_not_assumed() -> None:
    """The house rule elsewhere is "naive means UTC" (`_validated_provenance` does
    exactly that). That is right for a record of the past and wrong here: the guess
    decides which hour a phone rings, and it is wrong by five and a half of them."""
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await schedule_campaign(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                start_at=datetime(2026, 8, 17, 10, 0),
            )
    assert excinfo.value.code == "campaign_schedule_timezone_missing"
    assert excinfo.value.status == 422
    status, stored = await _status(tenant_id, campaign_id)
    assert (status, stored) == ("draft", None), "a refused schedule writes nothing"


async def test_the_wire_model_itself_refuses_a_naive_start() -> None:
    """The service check above is the invariant; this is the SHAPE, and it matters
    separately: `ScheduleIn` is what the generated TypeScript client is built from, so
    an `AwareDatetime` there is what stops a browser sending `2026-08-17T10:00` at all."""
    from apps.api.campaigns.routes import ScheduleIn
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ScheduleIn(start_at="2026-08-17T10:00:00")  # type: ignore[arg-type]
    assert ScheduleIn(start_at="2026-08-17T10:00:00+05:30").start_at.utcoffset() == IST_OFFSET  # type: ignore[arg-type]


# ------------------------------------------------------ starting is not dialling


def test_a_start_inside_the_calling_window_dials_immediately() -> None:
    start = datetime(2026, 8, 17, 10, 0, tzinfo=UTC) - IST_OFFSET  # 10:00 IST
    assert first_dial_not_before(start) == start


def test_a_late_evening_start_waits_for_the_window_rather_than_being_refused() -> None:
    """22:00 IST is a lawful thing to ASK for ("have it ready first thing") and an
    unlawful thing to DIAL. So it is accepted, and the answer the client is given is
    09:00 the next morning — not 22:00, and not a refusal."""
    start = datetime(2026, 8, 17, 22, 0, tzinfo=UTC) - IST_OFFSET
    opens = first_dial_not_before(start)
    assert (opens + IST_OFFSET).time() == time(9, 0)
    assert (opens + IST_OFFSET).date() == datetime(2026, 8, 18).date()


def test_an_early_morning_start_waits_for_the_same_days_window() -> None:
    start = datetime(2026, 8, 17, 6, 0, tzinfo=UTC) - IST_OFFSET
    opens = first_dial_not_before(start)
    assert (opens + IST_OFFSET).time() == time(9, 0)
    assert (opens + IST_OFFSET).date() == datetime(2026, 8, 17).date()


def test_a_campaigns_own_narrowed_window_moves_the_first_dial_later() -> None:
    """A client who narrowed to lunch hours and then scheduled 10:00 is told 12:00, not
    09:00: `calling_hours` narrows, and the promise has to narrow with it."""
    start = datetime(2026, 8, 17, 10, 0, tzinfo=IST_TZ)
    opens = first_dial_not_before(start, {"start": "12:00", "end": "14:00"})
    assert (opens + IST_OFFSET).time() == time(12, 0)

    # And the other side of the same window, chosen so that the IST reading and a
    # would-be UTC reading disagree: 13:00 IST is inside 12:00-14:00, but the same
    # instant read as UTC is 07:30 and would be pushed to 12:00. A narrowing test that
    # only used a morning start would pass either way.
    inside = datetime(2026, 8, 17, 13, 0, tzinfo=IST_TZ)
    assert first_dial_not_before(inside, {"start": "12:00", "end": "14:00"}) == inside


async def test_a_ten_pm_start_is_accepted_and_answered_with_the_hour_it_will_dial() -> None:
    """The design decision, end to end, and the one a plausible alternative gets wrong.

    Refusing a 22:00 start at schedule time is the other reading of "a campaign
    scheduled at 22:00 must not dial at 22:00", and it refuses a lawful intent — a
    client who wants tomorrow's campaign armed before they go home. So it is ACCEPTED,
    and the answer names 09:00 the next morning. A version that refused here would fail
    on the first assertion, and a version that echoed 22:00 back would fail on the
    second."""
    tenant_id, _, campaign_id = await _ready_campaign()
    at_22_ist = (
        (datetime.now(UTC) + timedelta(days=3))
        .astimezone(IST_TZ)
        .replace(hour=22, minute=0, second=0, microsecond=0)
    )
    async with tenant_session(tenant_id) as session:
        recorded = await schedule_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id, start_at=at_22_ist
        )
    assert recorded.start_at == at_22_ist.astimezone(UTC), "a 22:00 start is not refused"
    first_dial_ist = recorded.first_dial_not_before + IST_OFFSET
    assert first_dial_ist.time() == time(9, 0)
    assert first_dial_ist.date() == (at_22_ist + timedelta(days=1)).date()


async def test_a_campaign_started_at_night_becomes_running_and_dials_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end-to-end version of the rule: firing a schedule is a LAUNCH, and a launch
    at 22:00 dials nothing until 09:00. If the schedule were conflated with the calling
    window this campaign would place two calls at ten at night."""
    monkeypatch.setattr(
        "apps.api.compliance.service.ist_now",
        lambda: datetime(2026, 8, 11, 16, 30, tzinfo=UTC) + IST_OFFSET,  # 22:00 IST
    )
    tenant_id, _, campaign_id = await _ready_campaign()
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id, start_at=now + timedelta(hours=1)
        )
        outcome = await fire_schedule(
            session,
            tenant_id=tenant_id,
            due=DueSchedule(campaign_id=campaign_id, start_at=now),
            now=now,
        )
    assert outcome == "fired"

    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
        calls = (
            await session.execute(
                text(
                    "SELECT count(*) FROM calls c JOIN campaign_contacts cc "
                    "ON cc.last_call_id = c.id WHERE cc.campaign_id = :c"
                ),
                {"c": campaign_id},
            )
        ).scalar()
    assert status == "running", "the start happened"
    assert calls == 0, "and it dialled nobody at 22:00 IST"


# ------------------------------------------------------------------- schedule bounds


async def test_a_start_in_the_past_is_refused() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await schedule_campaign(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                start_at=datetime.now(UTC) - timedelta(minutes=1),
            )
    assert excinfo.value.code == "campaign_schedule_in_past"


async def test_a_start_beyond_the_horizon_is_refused_as_the_typo_it_almost_always_is() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await schedule_campaign(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                start_at=datetime.now(UTC) + MAX_HORIZON + timedelta(days=1),
            )
    assert excinfo.value.code == "campaign_schedule_too_far"


async def test_a_running_campaign_cannot_be_given_a_start_time() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        with pytest.raises(ProblemError) as excinfo:
            await schedule_campaign(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                start_at=datetime.now(UTC) + timedelta(days=1),
            )
    assert excinfo.value.code == "campaign_not_schedulable"


async def test_scheduling_a_campaign_that_does_not_exist_is_a_404() -> None:
    tenant_id, _, _ = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await schedule_campaign(
                session,
                tenant_id=tenant_id,
                campaign_id=uuid7(),
                start_at=datetime.now(UTC) + timedelta(days=1),
            )
    assert excinfo.value.status == 404


async def test_cancelling_a_start_returns_the_campaign_to_draft_and_clears_the_column() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(days=1),
        )
        await unschedule_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        with pytest.raises(ProblemError) as excinfo:
            await unschedule_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    assert excinfo.value.code == "campaign_not_scheduled"
    assert await _status(tenant_id, campaign_id) == ("draft", None)


async def test_contacts_can_still_be_added_while_a_campaign_waits_for_its_start() -> None:
    """A scheduled campaign has dialled nobody. Refusing its contact upload would leave
    "cancel the schedule, upload, re-pick the date" as the only route."""
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(days=1),
        )
        added = await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": "9876599999"}],
        )
    assert added["added"] == 1


# ------------------------------------------------------ the gate runs at FIRE time


async def test_the_gate_refuses_at_fire_time_for_a_condition_that_was_green_at_schedule_time() -> (
    None
):
    """**The central test of this file (hard rule 5).**

    The campaign is scheduled while every §3 condition is satisfied — so a gate at
    schedule time would have passed it — and the DLT voice template is then withdrawn by
    the registrar, which is an ordinary event between a Friday and a Monday. The tick
    must refuse, name the rule, and leave the campaign waiting rather than running.
    """
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        # Green now: the same gate the fire will run passes at this moment.
        assert (
            await service.launch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)
            == []
        )
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        template_id = (
            await session.execute(
                text("SELECT dlt_template_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
        await service.set_template_status(session, template_id=template_id, status="rejected")

    # The start time arrives.
    fired_at = datetime.now(UTC) + timedelta(minutes=6)
    async with tenant_session(tenant_id) as session:
        due = await due_schedules(session, now=fired_at)
    assert [d.campaign_id for d in due] == [campaign_id]
    async with tenant_session(tenant_id) as session:
        outcome = await fire_schedule(session, tenant_id=tenant_id, due=due[0], now=fired_at)

    assert outcome == "blocked"
    status, stored = await _status(tenant_id, campaign_id)
    assert status == "scheduled", "a refused start does not become a running campaign"
    assert stored["last_blocked"]["rules"] == ["dlt_template_not_approved"]
    assert await _launch_audit_count(tenant_id, campaign_id) == 0

    # ...and it starts the moment the registrar approves it again, without the client
    # having to re-pick a date.
    async with tenant_session(tenant_id) as session:
        await service.set_template_status(session, template_id=template_id, status="approved")
    async with tenant_session(tenant_id) as session:
        assert (
            await fire_schedule(session, tenant_id=tenant_id, due=due[0], now=fired_at) == "fired"
        )
    assert (await _status(tenant_id, campaign_id))[0] == "running"
    assert await _launch_audit_count(tenant_id, campaign_id) == 1


async def test_a_start_blocked_past_its_grace_window_gives_up_and_returns_to_draft() -> None:
    """Retrying forever would start a Monday-10:00 campaign on Thursday afternoon, which
    is not what the client picked. Giving up on the first blocked tick would lose a start
    to a template the registrar approves twenty minutes later. So: retry for GRACE, then
    hand the campaign back as a draft, where `/launch-check` names the same blockers."""
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        template_id = (
            await session.execute(
                text("SELECT dlt_template_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
        await service.set_template_status(session, template_id=template_id, status="rejected")

    start_at = datetime.now(UTC) + timedelta(minutes=5)
    due = DueSchedule(campaign_id=campaign_id, start_at=start_at)
    async with tenant_session(tenant_id) as session:
        assert (
            await fire_schedule(
                session, tenant_id=tenant_id, due=due, now=start_at + GRACE - timedelta(minutes=1)
            )
            == "blocked"
        ), "one minute inside the grace window it is still trying"
    async with tenant_session(tenant_id) as session:
        assert (
            await fire_schedule(
                session, tenant_id=tenant_id, due=due, now=start_at + GRACE + timedelta(minutes=1)
            )
            == "expired"
        )
    assert await _status(tenant_id, campaign_id) == ("draft", None)
    async with tenant_session(tenant_id) as session:
        expired = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE object_id = :c "
                    "AND action = 'campaign.schedule_expired'"
                ),
                {"c": str(campaign_id)},
            )
        ).scalar()
    assert expired == 1, "a start that never happened is a fact the client will ask about"


# ------------------------------------------------------------------ fires exactly once


async def test_two_concurrent_ticks_start_one_scheduled_campaign_exactly_once() -> None:
    """The tick lease fails OPEN on a Redis error (`_tick_lease`), so two ticks reading
    the same due campaign is a state the system is designed to survive rather than
    prevent. What must hold is the CAS underneath: `scheduled → running` with the guard
    in the WHERE clause, one transaction per campaign so the loser has something to roll
    back. Counted through `audit_log`, not through `status`: a status can only ever say
    "running" once no matter how many times it was written, which is precisely the
    evidence a double launch would hide."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start_at = datetime.now(UTC) - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        # Rewind the stored start so it is due NOW, through the same column and shape
        # `schedule_campaign` writes — no test-only branch, only a different instant.
        await session.execute(
            text("UPDATE campaigns SET schedule = CAST(:s AS jsonb) WHERE id = :c"),
            {
                "s": f'{{"kind": "one_time", "start_at": "{start_at.isoformat()}"}}',
                "c": campaign_id,
            },
        )

    results = await asyncio.gather(
        campaign_dispatch._fire_due_schedules(tenant_id),
        campaign_dispatch._fire_due_schedules(tenant_id),
    )

    assert sum(results) == 1, f"exactly one tick may start it, got {results}"
    assert (await _status(tenant_id, campaign_id))[0] == "running"
    assert await _launch_audit_count(tenant_id, campaign_id) == 1


async def test_the_tick_counts_a_lost_race_as_zero_starts_rather_than_dying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deterministic half of the test above.

    Two real ticks resolve their race through whichever of two paths wins by
    microseconds — the CAS returning zero rows, or the gate reporting the campaign as
    already `running`. Both are correct and only one of them exercises the worker's
    `except InvalidStatusTransitionError`, so the branch that decides a tick survives
    losing a race is pinned here instead of left to a scheduler."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start_at = datetime.now(UTC) - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text("UPDATE campaigns SET schedule = CAST(:s AS jsonb) WHERE id = :c"),
            {
                "s": f'{{"kind": "one_time", "start_at": "{start_at.isoformat()}"}}',
                "c": campaign_id,
            },
        )

    def _lost(*_args: object, **_kwargs: object) -> Any:
        raise InvalidStatusTransitionError("campaign", "scheduled", "running")

    monkeypatch.setattr(campaign_dispatch, "fire_schedule", _lost)
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0
    # And the tick did not take the campaign with it: the transaction rolled back, so
    # the campaign is exactly as the winner would have left it — here, still waiting.
    assert (await _status(tenant_id, campaign_id))[0] == "scheduled"


# ------------------------------------------------------------ the tick end to end


async def test_the_tick_starts_a_due_campaign_and_dials_it_in_the_same_pass() -> None:
    """`dispatch_scan()`'s fourth column is what makes this reachable at all: without it
    the tick never opens a session for a tenant whose only campaign is `scheduled`, and
    the start would wait for someone to launch it by hand — the exact gap this slice
    closes."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start_at = datetime.now(UTC) - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text("UPDATE campaigns SET schedule = CAST(:s AS jsonb) WHERE id = :c"),
            {
                "s": f'{{"kind": "one_time", "start_at": "{start_at.isoformat()}"}}',
                "c": campaign_id,
            },
        )

    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
        dialing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :c "
                    "AND status = 'dialing'"
                ),
                {"c": campaign_id},
            )
        ).scalar()
    assert status == "running", "the tick started it"
    assert dialing == 2, "and dialled it in the same pass rather than 30 seconds later"


async def test_a_campaign_scheduled_for_later_costs_the_tick_nothing_at_all() -> None:
    """Not started, and — the part that matters at scale — **not visited**.

    `dispatch_scan()`'s fourth column is `has_due_schedule`, not `has_scheduled_campaign`,
    and the difference is 2,880 tenant sessions a day per pending schedule. D-57's
    property is that a tick costs what there is WORK to do; a start set for next month is
    not work today. `tests/dispatch_scale_test.py` states the same invariant over a
    synthetic population — this states it over the one row that would break it.
    """
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(days=2),
        )

    scanned = {work.tenant_id: work for work in await campaign_dispatch._tenants_with_work()}
    assert tenant_id not in scanned, "a start set for the day after tomorrow is not work now"

    await dispatch_campaign_tick({})
    assert (await _status(tenant_id, campaign_id))[0] == "scheduled"


async def test_a_campaign_whose_start_has_arrived_is_reported_as_due() -> None:
    """The other half of the screen: too narrow is worse than too wide, because a start
    the scan never reports is a campaign that never runs and never says why."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start_at = datetime.now(UTC) - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text("UPDATE campaigns SET schedule = CAST(:s AS jsonb) WHERE id = :c"),
            {
                "s": f'{{"kind": "one_time", "start_at": "{start_at.isoformat()}"}}',
                "c": campaign_id,
            },
        )
    scanned = {work.tenant_id: work for work in await campaign_dispatch._tenants_with_work()}
    assert tenant_id in scanned and scanned[tenant_id].has_due_schedule


async def test_a_start_the_scan_cannot_parse_does_not_abort_the_platform_wide_walk() -> None:
    """One malformed JSON value in ONE tenant must not take the dispatch tick down for
    everybody. `dispatch_scan()` is a single function call across every tenant on the
    platform, so an unguarded `::timestamptz` would turn one bad row into a total dial
    outage — the guard is `pg_input_is_valid` inside a CASE (migration c7e4b19d3f52)."""
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{start_at}', "
                "'\"next monday\"') WHERE id = :c"
            ),
            {"c": campaign_id},
        )

    # The walk completes and answers for everyone else.
    scanned = await campaign_dispatch._tenants_with_work()
    assert isinstance(scanned, list)
    assert tenant_id not in {work.tenant_id for work in scanned}


async def test_the_scan_does_not_leak_one_tenants_pending_start_to_another() -> None:
    """`due_schedules` reads `campaigns` with no tenant predicate of its own — RLS is
    the isolation, exactly as `db/session.py` intends. This is the cross-tenant zero-rows
    assertion that keeps that true."""
    tenant_a, _, campaign_a = await _ready_campaign()
    tenant_b, _, _ = await _ready_campaign()
    now = datetime.now(UTC)
    async with tenant_session(tenant_a) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_a,
            campaign_id=campaign_a,
            start_at=now + timedelta(minutes=5),
        )
    later = now + timedelta(minutes=10)
    async with tenant_session(tenant_b) as session:
        assert await due_schedules(session, now=later) == []
    async with tenant_session(tenant_a) as session:
        assert [d.campaign_id for d in await due_schedules(session, now=later)] == [campaign_a]


# --------------------------------------------------------------- fail-closed parsing


async def test_a_schedule_kind_this_build_cannot_run_is_never_fired_as_a_one_time_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two kinds have readers (`one_time`, `recurring`); anything else has none.

    The `kind` discriminator is what let recurrence land without a migration, and it goes
    on earning that: a shape a future build introduces — `monthly` here — must be left
    alone by THIS one rather than fired once as a start and made to look finished. The
    same fail-closed branch, now guarding the next addition instead of the last one.
    """
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{kind}', '\"monthly\"') "
                "WHERE id = :c"
            ),
            {"c": campaign_id},
        )
    async with tenant_session(tenant_id) as session:
        due = await due_schedules(session, now=datetime.now(UTC) + timedelta(hours=1))
    assert due == []
    assert any(
        "campaign_schedule_kind_unknown" in record.getMessage()
        or getattr(record, "code", None) == "campaign_schedule_kind_unknown"
        for record in caplog.records
    ), "and it is loud about it"


async def test_an_unreadable_start_instant_blocks_the_start_rather_than_guessing() -> None:
    """Unreachable through `schedule_campaign`, which serializes an aware UTC instant —
    which is exactly why it must fail closed. Anything else in this column means
    something that is not this module wrote to it."""
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{start_at}', "
                "'\"next monday\"') WHERE id = :c"
            ),
            {"c": campaign_id},
        )
    async with tenant_session(tenant_id) as session:
        assert await due_schedules(session, now=datetime.now(UTC) + timedelta(hours=1)) == []
    assert (await _status(tenant_id, campaign_id))[0] == "scheduled"


async def test_a_start_instant_with_no_offset_in_the_column_is_refused_too() -> None:
    """The naive-datetime refusal has a second half, on the READ side. A value that
    parses as a datetime but carries no offset would be compared against an aware `now`
    — a TypeError inside the dispatch tick, or worse, a silent five-and-a-half-hour
    error if anyone ever "helpfully" pinned it to UTC on the way in."""
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{start_at}', "
                "'\"2026-08-17T10:00:00\"') WHERE id = :c"
            ),
            {"c": campaign_id},
        )
    async with tenant_session(tenant_id) as session:
        assert await due_schedules(session, now=datetime.now(UTC) + timedelta(days=30)) == []


# ------------------------------------------------------------------- progress surface


async def test_progress_says_when_a_scheduled_campaign_starts_and_why_it_has_not() -> None:
    """§52: a screen may not stop at a state. "Scheduled" with no date, and "scheduled"
    for a start the gate keeps refusing, are both states pretending to be answers."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start = datetime.now(UTC) + timedelta(minutes=5)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id, start_at=start
        )
        progress = await service.campaign_progress(session, campaign_id)
    assert datetime.fromisoformat(str(progress["scheduled_start_at"])) == start
    assert progress["schedule_blocked_rules"] == []

    async with tenant_session(tenant_id) as session:
        template_id = (
            await session.execute(
                text("SELECT dlt_template_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
        await service.set_template_status(session, template_id=template_id, status="rejected")
    async with tenant_session(tenant_id) as session:
        await fire_schedule(
            session,
            tenant_id=tenant_id,
            due=DueSchedule(campaign_id=campaign_id, start_at=start),
            now=start + timedelta(minutes=1),
        )
        progress = await service.campaign_progress(session, campaign_id)
    assert progress["schedule_blocked_rules"] == ["dlt_template_not_approved"]


async def test_a_running_campaign_does_not_advertise_a_start_that_already_happened() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    start = datetime.now(UTC) + timedelta(minutes=5)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id, start_at=start
        )
        await fire_schedule(
            session,
            tenant_id=tenant_id,
            due=DueSchedule(campaign_id=campaign_id, start_at=start),
            now=start + timedelta(minutes=1),
        )
        progress = await service.campaign_progress(session, campaign_id)
    assert progress["status"] == "running"
    assert progress["scheduled_start_at"] is None


def test_the_module_exposes_no_way_to_skip_the_gate() -> None:
    """Hard rule 5 has no exceptions, including for tests. The only path from
    `scheduled` to `running` in this module goes through `launch_campaign`, which begins
    with `launch_blockers`; a second UPDATE to `'running'` anywhere in this file would be
    that bypass."""
    source = scheduling.__file__ or ""
    assert source
    body = open(source, encoding="utf-8").read()  # noqa: SIM115
    assert "status = 'running'" not in body, "only launch_campaign may set a campaign running"
    assert body.count("launch_campaign(") >= 1


# ------------------------------------------------------------------ refusal branches


def test_an_unreadable_calling_window_promises_the_platform_hours_not_a_wider_one() -> None:
    """`create_campaign` validates the window, so this is unreachable through the API —
    and a promise about when we will dial, derived from a column we could not read, has
    exactly one safe answer. The dispatcher fails closed on the same value
    (`campaign_window_open`); this fails closed the same way rather than differently."""
    start = datetime(2026, 8, 17, 6, 0, tzinfo=IST_TZ)
    assert (first_dial_not_before(start, {"start": "noon"}) + IST_OFFSET).time() == time(9, 0)
    assert (first_dial_not_before(start, {}) + IST_OFFSET).time() == time(9, 0)


async def test_a_schedule_that_is_not_an_object_at_all_is_not_a_start() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text("UPDATE campaigns SET schedule = '\"monday\"'::jsonb WHERE id = :c"),
            {"c": campaign_id},
        )
    async with tenant_session(tenant_id) as session:
        assert await due_schedules(session, now=datetime.now(UTC) + timedelta(days=1)) == []


async def test_a_lost_cas_propagates_so_the_caller_can_roll_its_transaction_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`fire_schedule` must NOT swallow the CAS refusal. The loser's transaction holds a
    DNC scrub written before the CAS; only an exception out of this function gets it
    rolled back, and a swallowed one would leave the loser committing writes for a
    launch that never happened."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start = datetime.now(UTC)

    async def _cas_lost(*_a: object, **_k: object) -> None:
        raise InvalidStatusTransitionError("campaign", "non-draft", "running")

    monkeypatch.setattr(scheduling, "launch_campaign", _cas_lost)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(InvalidStatusTransitionError):
            await fire_schedule(
                session,
                tenant_id=tenant_id,
                due=DueSchedule(campaign_id=campaign_id, start_at=start),
                now=start,
            )


async def test_a_refusal_that_is_not_the_gate_is_not_dressed_up_as_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only `campaign_launch_blocked` means "the gate said no". A 404, a 409 or anything
    else is a real failure, and recording it as a compliance blocker on the schedule
    would put a rule name nobody can act on in front of the client and hide a bug."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start = datetime.now(UTC)

    async def _something_else(*_a: object, **_k: object) -> None:
        raise ProblemError.not_found("Campaign")

    monkeypatch.setattr(scheduling, "launch_campaign", _something_else)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await fire_schedule(
                session,
                tenant_id=tenant_id,
                due=DueSchedule(campaign_id=campaign_id, start_at=start),
                now=start,
            )
    assert excinfo.value.status == 404


async def test_expiry_that_loses_its_own_race_writes_no_audit_for_a_start_that_happened() -> None:
    """A schedule can be launched by hand in the moment between "past grace" and the
    UPDATE that gives up on it. `campaign.schedule_expired` on a campaign that is now
    running would be a false entry in the one artefact built to be unfalsifiable."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start = datetime.now(UTC) - GRACE - timedelta(hours=1)
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        outcome = await fire_schedule(
            session,
            tenant_id=tenant_id,
            due=DueSchedule(campaign_id=campaign_id, start_at=start),
            now=datetime.now(UTC),
        )
    assert outcome == "raced"
    async with tenant_session(tenant_id) as session:
        expired = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE object_id = :c "
                    "AND action = 'campaign.schedule_expired'"
                ),
                {"c": str(campaign_id)},
            )
        ).scalar()
    assert expired == 0


async def test_a_gate_refusal_caused_by_the_race_itself_is_not_recorded_as_one() -> None:
    """The subtle half of "fires exactly once".

    A race does not always surface at the CAS. If the winner commits before the loser
    reads the campaign's facts, the loser's gate reports its own `status` blocker — the
    gate correctly refusing to launch an already-launched campaign. Treated as a
    compliance refusal that would put a phantom `compliance_blocks{rule="status"}` on the
    dashboard every time two ticks overlapped, and write "we could not start this" onto
    a schedule whose campaign is dialling."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        outcome = await fire_schedule(
            session,
            tenant_id=tenant_id,
            due=DueSchedule(campaign_id=campaign_id, start_at=start),
            now=start,
        )
    assert outcome == "raced"


async def test_a_tenant_the_scan_flagged_but_whose_schedule_is_unrunnable_starts_nothing() -> None:
    """The scan is a SUPERSET screen, so `_fire_due_schedules` has to be safe when the
    service declines everything it was sent — a `kind` this build cannot run reaches the
    scan as "due" and must leave with nothing started and nothing raised."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start_at = datetime.now(UTC) - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text("UPDATE campaigns SET schedule = CAST(:s AS jsonb) WHERE id = :c"),
            {"s": f'{{"kind": "monthly", "start_at": "{start_at.isoformat()}"}}', "c": campaign_id},
        )
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0
    assert (await _status(tenant_id, campaign_id))[0] == "scheduled"


async def test_a_blocked_start_counts_as_zero_starts_not_as_a_start() -> None:
    """`started` is what the tick reports and what decides whether it bothers reading a
    budget. A blocked campaign counted as started would have the tick open a session to
    dial a campaign that is still a draft's worth of blockers away from running."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start_at = datetime.now(UTC) - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text("UPDATE campaigns SET schedule = CAST(:s AS jsonb) WHERE id = :c"),
            {
                "s": f'{{"kind": "one_time", "start_at": "{start_at.isoformat()}"}}',
                "c": campaign_id,
            },
        )
        template_id = (
            await session.execute(
                text("SELECT dlt_template_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
        await service.set_template_status(session, template_id=template_id, status="rejected")

    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0
    assert (await _status(tenant_id, campaign_id))[0] == "scheduled"


async def test_a_tick_reads_no_budget_for_a_tenant_whose_only_start_was_refused() -> None:
    """The tick visits this tenant — a due schedule IS work — but must not go on to read
    its dialling budget: nothing is running, so the read would be a session spent to
    discover an empty list. The end-to-end shape of the same claim
    `test_a_campaign_scheduled_for_later_costs_the_tick_nothing_at_all` makes about the
    scan."""
    tenant_id, _, campaign_id = await _ready_campaign()
    start_at = datetime.now(UTC) - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.execute(
            text("UPDATE campaigns SET schedule = CAST(:s AS jsonb) WHERE id = :c"),
            {
                "s": f'{{"kind": "one_time", "start_at": "{start_at.isoformat()}"}}',
                "c": campaign_id,
            },
        )
        template_id = (
            await session.execute(
                text("SELECT dlt_template_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
        await service.set_template_status(session, template_id=template_id, status="rejected")

    await dispatch_campaign_tick({})

    status, stored = await _status(tenant_id, campaign_id)
    assert status == "scheduled"
    assert stored["last_blocked"]["rules"] == ["dlt_template_not_approved"]
    async with tenant_session(tenant_id) as session:
        dialing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :c "
                    "AND status <> 'pending'"
                ),
                {"c": campaign_id},
            )
        ).scalar()
    assert dialing == 0, "a refused start dials nobody"
