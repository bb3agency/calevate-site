"""Repeating campaign starts — `campaigns.schedule` with `kind = recurring`.

`campaign_schedule_test.py` proves the one-time start. This file attacks what recurrence
ADDS, and everything here is one of the five ways a repeat is dangerous in a way a
one-time start is not:

1. **The gate could be evaluated once, at creation.** A repeat makes a claim about a
   Tuesday six weeks out; a DLT registration, a spend cap, a KYC or the platform halt can
   all lapse in between. The central test schedules a repeat while every §3 condition is
   green, breaks one, and requires the OCCURRENCE to be refused — hard rule 5 with a
   calendar attached.
2. **A missed occurrence could be caught up.** A worker down from Monday to Wednesday
   must not, on recovery, fire Monday's, Tuesday's and Wednesday's occurrences into one
   afternoon. That is not a late campaign, it is three times the dial volume at a time of
   day nobody chose.
3. **One occurrence could fire twice.** The tick lease fails open by design, so two ticks
   read the same occurrence. What must hold is that the occurrence — not the wall clock —
   is the identity they contend on.
4. **A stop could take effect one tick late.** The tick reads the due set in one
   transaction and fires in another; a client pressing "stop repeating" in between must
   not be overtaken by the earlier read. Same deadline DNC propagation is held to.
5. **A repeat could run exactly once and look finished.** A campaign that completes its
   run has to come back to `scheduled`, or every occurrence after the first sits under a
   status nothing looks at.

Nothing here uses a test-only branch or a bypass flag. A blocked state is produced by
writing the row production writes (a rejected DLT template); an occurrence is made due by
rewriting the same JSON key `schedule_recurrence` writes, with a different instant.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta, timezone

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import scheduling, service
from apps.api.campaigns.scheduling import (
    MAX_HORIZON,
    RECURRENCE_CATCHUP,
    Recurrence,
    complete_or_rearm,
    due_schedules,
    fire_schedule,
    schedule_recurrence,
    unschedule_campaign,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import ACTIVE_STATUSES, dispatch_campaign_tick
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.national_dnd_test import record_test_scrub

# 11:00 IST on 2026-08-11 — inside the platform window, so a refusal is never the clock.
NOON_IST = datetime(2026, 8, 11, 5, 30, tzinfo=UTC)
IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TZ = timezone(IST_OFFSET)

MONDAY, TUESDAY, WEDNESDAY = 1, 2, 3
EVERY_DAY = [1, 2, 3, 4, 5, 6, 7]
TEN_AM = time(10, 0)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: NOON_IST + IST_OFFSET)


@pytest.fixture(autouse=True)
def _roomy_platform_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """The outbound pool is platform-wide and this suite is not alone on the database;
    FLOWS §5 rule 1 is asserted in `dispatch_scale_test.py`, not here."""
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10_000)


_TENANTS: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
async def _leave_the_platform_quiet() -> AsyncIterator[None]:
    """Cancel every campaign this module armed, after each test.

    Not tidiness: a repeat whose next occurrence this suite rewound into the past is
    permanently due, so a leaked one makes its tenant permanently dispatchable and
    `tests/dispatch_scale_test.py` measures this suite's litter instead of D-57's
    property. Recurrence makes that worse than the one-time suite did — a fired repeat
    re-arms itself.
    """
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'cancelled', schedule = NULL, "
                    "updated_at = now() WHERE status IN ('scheduled', 'running', 'paused')"
                )
            )
            await session.execute(
                text(f"UPDATE calls SET status = 'completed' WHERE status IN {ACTIVE_STATUSES!r}")
            )
    _TENANTS.clear()


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Repeat Motors",
        slug=f"rep-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_rep_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
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
            entity_name="Repeat Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _ready_campaign(
    *,
    calling_hours: dict[str, str] | None = None,
    phones: tuple[str, ...] = ("9876510001", "9876510002"),
) -> tuple[uuid.UUID, uuid.UUID]:
    """(tenant, campaign) — a promotional campaign that would launch right now."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        number_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, '140', 'registered', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                # BOUND TO THE CAMPAIGN'S AGENT (D-424): the launch gate refuses a campaign
                # whose approved number is not the number its agent dials from.
                "aid": agent_id,
                "e": f"+9180{uuid.uuid4().int % 10**8:08d}",
            },
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
            name="Weekly follow-up",
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
        # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9).
        # A promotional campaign is launch-ready only once an access provider has
        # preference-scrubbed its list, so this fixture supplies the fact through the
        # production writer — `tests/national_dnd_test.py` proves the refusal is real.
        await record_test_scrub(session, campaign_id)
    return tenant_id, campaign_id


async def _schedule(
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    days: list[int] | None = None,
    at: time = TEN_AM,
    until: datetime | None = None,
) -> scheduling.ScheduledRecurrence:
    async with tenant_session(tenant_id) as session:
        return await schedule_recurrence(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            days=days if days is not None else EVERY_DAY,
            at=at,
            until=until,
        )


async def _stored(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> tuple[str, dict | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, schedule FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).first()
    assert row is not None
    return str(row[0]), row[1]


async def _make_due(tenant_id: uuid.UUID, campaign_id: uuid.UUID, occurrence: datetime) -> None:
    """Move the NEXT OCCURRENCE to `occurrence`, through the same key production writes.

    Not a test-only branch and not a second shape: `start_at` is exactly where
    `schedule_recurrence` puts the next occurrence, and this writes a different instant
    into it — the only thing a test cannot do is wait a week.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{start_at}', "
                "to_jsonb(CAST(:s AS text))) WHERE id = :c"
            ),
            {"s": occurrence.isoformat(), "c": campaign_id},
        )


async def _set_end_date(tenant_id: uuid.UUID, campaign_id: uuid.UUID, end: datetime) -> None:
    """Move the repeat's end date, through the same key `schedule_recurrence` writes.

    Set at creation it would have to be far enough ahead to admit a first occurrence
    (the service refuses a repeat that ends before it starts), which puts the interesting
    moment — the LAST occurrence — a real week away.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{until}', "
                "to_jsonb(CAST(:s AS text))) WHERE id = :c"
            ),
            {"s": end.isoformat(), "c": campaign_id},
        )


async def _audit_count(tenant_id: uuid.UUID, campaign_id: uuid.UUID, action: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE object_id = :c AND action = :a"),
                    {"c": str(campaign_id), "a": action},
                )
            ).scalar()
            or 0
        )


# ------------------------------------------------------- what "every Tuesday" means


def test_a_weekly_occurrence_crosses_a_month_boundary_without_a_special_case() -> None:
    """The question day-of-month recurrence cannot answer and weekday recurrence never
    has to ask. From a Wednesday in August, "every Tuesday at 10am" is the first Tuesday
    in September — one walk forward in IST wall-clock days, no month arithmetic."""
    rule = Recurrence(days=(TUESDAY,), at=TEN_AM, until=None)
    from_wednesday = datetime(2026, 8, 26, 12, 0, tzinfo=IST_TZ)
    following = rule.next_after(from_wednesday)
    assert following is not None
    assert (following + IST_OFFSET).date() == datetime(2026, 9, 1).date()
    # 10:00 IST is 04:30Z — stored as the instant it names, not as the digits.
    assert following == datetime(2026, 9, 1, 4, 30, tzinfo=UTC)


def test_the_year_boundary_is_the_same_walk() -> None:
    rule = Recurrence(days=(MONDAY,), at=TEN_AM, until=None)
    following = rule.next_after(datetime(2026, 12, 29, 12, 0, tzinfo=IST_TZ))
    assert following is not None
    assert (following + IST_OFFSET).date() == datetime(2027, 1, 4).date()


def test_todays_slot_counts_until_it_has_passed_and_never_twice() -> None:
    """Strictly after, because `next_after` is called with the occurrence just fired: an
    inclusive comparison would return the same instant and the repeat would never move."""
    rule = Recurrence(days=(TUESDAY,), at=TEN_AM, until=None)
    tuesday_0959 = datetime(2026, 8, 11, 9, 59, tzinfo=IST_TZ)
    assert rule.next_after(tuesday_0959) == datetime(2026, 8, 11, 4, 30, tzinfo=UTC)
    exactly_ten = datetime(2026, 8, 11, 10, 0, tzinfo=IST_TZ)
    following = rule.next_after(exactly_ten)
    assert following is not None
    assert (following + IST_OFFSET).date() == datetime(2026, 8, 18).date()


def test_a_repeat_stops_at_its_end_date() -> None:
    rule = Recurrence(days=(TUESDAY,), at=TEN_AM, until=datetime(2026, 8, 12, tzinfo=UTC))
    assert rule.next_after(datetime(2026, 8, 11, 12, 0, tzinfo=IST_TZ)) is None


def test_several_days_are_one_walk_not_several_rules() -> None:
    rule = Recurrence(days=(MONDAY, WEDNESDAY), at=TEN_AM, until=None)
    from_monday_afternoon = datetime(2026, 8, 10, 14, 0, tzinfo=IST_TZ)
    following = rule.next_after(from_monday_afternoon)
    assert following is not None
    assert (following + IST_OFFSET).isoweekday() == WEDNESDAY


# --------------------------------------------------------------- creation refusals


async def test_a_repeat_outside_calling_hours_is_refused_rather_than_quietly_moved() -> None:
    """Decision 4. A ONE-TIME 22:00 start is accepted and dials at 09:00 the next
    morning, because "have it armed before I go home" is a lawful one-off intent. A
    STANDING instruction to repeat at 22:00 is a different object: reinterpreting it as
    09:00 the following day gives the client a schedule that says one thing on screen and
    does another every week."""
    tenant_id, campaign_id = await _ready_campaign()
    with pytest.raises(ProblemError) as excinfo:
        await _schedule(tenant_id, campaign_id, days=[TUESDAY], at=time(22, 0))
    assert excinfo.value.code == "campaign_recurrence_outside_calling_hours"
    assert excinfo.value.status == 422
    assert await _stored(tenant_id, campaign_id) == ("draft", None), "a refusal writes nothing"


async def test_a_repeat_at_exactly_nine_pm_is_refused_by_its_own_sentence() -> None:
    """The half-open end (D-311), on the validation side.

    This check was `window_start <= at <= window_end`, so 21:00 was accepted — while
    `within_calling_hours` puts 21:00:00 inside the forbidden band. The refusal's own
    wording is the proof it was wrong: it promises to reject a time at which the campaign
    "would never dial at the time it says", and 21:00 is exactly such a time. A weekly
    repeat armed at 21:00 fired every week and dialled nobody, for ever.

    09:00 stays accepted: the lower bound is inclusive because 09:00:00 is the first
    instant OUTSIDE the forbidden band.
    """
    tenant_id, campaign_id = await _ready_campaign()
    with pytest.raises(ProblemError) as excinfo:
        await _schedule(tenant_id, campaign_id, days=[TUESDAY], at=time(21, 0))
    assert excinfo.value.code == "campaign_recurrence_outside_calling_hours"
    assert await _stored(tenant_id, campaign_id) == ("draft", None), "a refusal writes nothing"

    await _schedule(tenant_id, campaign_id, days=[TUESDAY], at=time(9, 0))
    assert (await _stored(tenant_id, campaign_id))[0] == "scheduled"


async def test_a_repeat_with_no_days_is_refused_because_it_would_never_run() -> None:
    tenant_id, campaign_id = await _ready_campaign()
    with pytest.raises(ProblemError) as excinfo:
        await _schedule(tenant_id, campaign_id, days=[])
    assert excinfo.value.code == "campaign_recurrence_no_days"


async def test_a_day_that_is_not_a_day_of_the_week_is_refused() -> None:
    tenant_id, campaign_id = await _ready_campaign()
    with pytest.raises(ProblemError) as excinfo:
        await _schedule(tenant_id, campaign_id, days=[8])
    assert excinfo.value.code == "campaign_recurrence_day_out_of_range"


async def test_a_repeat_that_ends_before_its_first_occurrence_is_refused() -> None:
    tenant_id, campaign_id = await _ready_campaign()
    with pytest.raises(ProblemError) as excinfo:
        await _schedule(
            tenant_id,
            campaign_id,
            days=[TUESDAY],
            until=datetime.now(UTC) + timedelta(minutes=1),
        )
    assert excinfo.value.code == "campaign_recurrence_ends_before_it_starts"


async def test_a_running_campaign_cannot_be_given_a_repeat() -> None:
    tenant_id, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    with pytest.raises(ProblemError) as excinfo:
        await _schedule(tenant_id, campaign_id)
    assert excinfo.value.code == "campaign_not_schedulable"


async def test_setting_a_repeat_replaces_a_one_time_start_rather_than_stacking_on_it() -> None:
    """One column, one promise. Two schedules on one campaign would be two things the
    client cannot see and only one of which the tick would honour."""
    tenant_id, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await scheduling.schedule_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            start_at=datetime.now(UTC) + timedelta(days=1),
        )
    await _schedule(tenant_id, campaign_id, days=[TUESDAY])
    status, stored = await _stored(tenant_id, campaign_id)
    assert status == "scheduled"
    assert stored is not None and stored["kind"] == "recurring"
    assert stored["rule"] == {"days": [TUESDAY], "at": "10:00"}


async def test_the_repeat_answers_with_the_hour_it_will_actually_dial() -> None:
    """A campaign that narrowed its own hours to lunchtime and repeats at 10:00 is told
    12:00 — the campaign's own narrowing is a defer-within-window, not a refusal, and the
    screen must not promise a 10:00 dial that will not happen."""
    tenant_id, campaign_id = await _ready_campaign(calling_hours={"start": "12:00", "end": "14:00"})
    recorded = await _schedule(tenant_id, campaign_id, days=EVERY_DAY, at=TEN_AM)
    assert (recorded.next_occurrence_at + IST_OFFSET).time() == time(10, 0)
    assert (recorded.first_dial_not_before + IST_OFFSET).time() == time(12, 0)


# ---------------------------------------------- THE GATE, ON EVERY OCCURRENCE


async def test_the_gate_refuses_an_occurrence_for_a_condition_that_was_green_at_creation() -> None:
    """**The central test of this file (hard rule 5).**

    The repeat is set while every §3 condition is satisfied — so a gate at creation would
    have passed it — and the DLT voice template is then withdrawn by the registrar, which
    is an ordinary event between one Tuesday and the next. The occurrence must be
    refused, name the rule, and leave the campaign waiting rather than running. Then the
    registrar re-approves and the SAME occurrence fires, because a block inside the
    catch-up window is "still trying", not "given up".
    """
    tenant_id, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        assert (
            await service.launch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)
            == []
        ), "green at creation, so a gate here would have passed"
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY)

    async with tenant_session(tenant_id) as session:
        template_id = (
            await session.execute(
                text("SELECT dlt_template_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
        await service.set_template_status(session, template_id=template_id, status="rejected")

    now = datetime.now(UTC)
    await _make_due(tenant_id, campaign_id, now - timedelta(minutes=1))
    async with tenant_session(tenant_id) as session:
        due = await due_schedules(session, now=now)
    assert [d.campaign_id for d in due] == [campaign_id]
    async with tenant_session(tenant_id) as session:
        assert await fire_schedule(session, tenant_id=tenant_id, due=due[0], now=now) == "blocked"

    status, stored = await _stored(tenant_id, campaign_id)
    assert status == "scheduled", "a refused occurrence does not become a running campaign"
    assert stored is not None
    assert stored["last_blocked"]["rules"] == ["dlt_template_not_approved"]
    assert await _audit_count(tenant_id, campaign_id, "campaign.launched") == 0
    # And the occurrence was NOT consumed by the refusal: it is still the next one.
    assert stored["start_at"] == (now - timedelta(minutes=1)).isoformat()

    async with tenant_session(tenant_id) as session:
        await service.set_template_status(session, template_id=template_id, status="approved")
    async with tenant_session(tenant_id) as session:
        assert await fire_schedule(session, tenant_id=tenant_id, due=due[0], now=now) == "fired"
    status, stored = await _stored(tenant_id, campaign_id)
    assert status == "running"
    assert await _audit_count(tenant_id, campaign_id, "campaign.launched") == 1
    assert stored is not None
    # The block that no longer describes anything is gone, and the repeat has moved on.
    assert "last_blocked" not in stored
    assert datetime.fromisoformat(stored["start_at"]) > now


def test_every_path_from_a_recurrence_to_running_goes_through_the_launch_gate() -> None:
    """Hard rule 5 has no exceptions, including for a schedule that fires unattended.

    The structural half of the test above: `campaign_schedule_test.py` asserts this
    module writes `status = 'running'` nowhere, and this asserts the recurrence branch
    reaches `launch_campaign` — which begins with `launch_blockers` — rather than any
    other route into a dialling campaign.
    """
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(scheduling._fire_recurrence))
    called = {
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "launch_campaign" in called, "the recurrence path must reach the same gate"
    body = (scheduling.__file__ or "") and open(scheduling.__file__, encoding="utf-8").read()  # noqa: SIM115
    assert "status = 'running'" not in body


# ------------------------------------------------- a missed occurrence is SKIPPED


async def test_a_missed_occurrence_is_skipped_and_never_caught_up() -> None:
    """**Decision 2**, and the reason it is a decision rather than a default.

    Three days of daily occurrences pass while nothing is running the tick. On recovery
    the campaign must NOT launch three times in one afternoon: that is triple the dial
    volume at a time of day the client did not choose, which is a compliance incident
    wearing the costume of a feature. Exactly one occurrence is pending afterwards, it is
    in the FUTURE, and nothing launched.
    """
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY)

    now = datetime.now(UTC)
    await _make_due(tenant_id, campaign_id, now - timedelta(days=3))

    started = await campaign_dispatch._fire_due_schedules(tenant_id)

    assert started == 0, "a missed occurrence is not a start"
    status, stored = await _stored(tenant_id, campaign_id)
    assert status == "scheduled", "and the repeat survives the skip"
    assert await _audit_count(tenant_id, campaign_id, "campaign.launched") == 0
    assert stored is not None
    assert stored["last_skipped"]["reason"] == "missed"
    # THE CATCH-UP TEST: the next occurrence is computed from NOW, so the two days of
    # missed slots between the abandoned one and today are gone rather than queued.
    next_at = datetime.fromisoformat(stored["start_at"])
    assert next_at > now
    assert next_at - now <= timedelta(days=1)
    async with tenant_session(tenant_id) as session:
        assert await due_schedules(session, now=now) == [], "nothing is left owing"
    assert await _audit_count(tenant_id, campaign_id, "campaign.recurrence_skipped") == 1


async def test_an_occurrence_inside_the_catch_up_window_still_fires() -> None:
    """The other side of the same bound: a worker restart of a few minutes must not cost
    the client their 10am. Skipping everything late would make the rule above safe and
    useless."""
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY)
    now = datetime.now(UTC)
    await _make_due(tenant_id, campaign_id, now - RECURRENCE_CATCHUP + timedelta(minutes=5))

    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 1
    assert (await _stored(tenant_id, campaign_id))[0] == "running"


# ------------------------------------------------------ one occurrence, one launch


async def test_two_concurrent_ticks_fire_one_occurrence_exactly_once() -> None:
    """The tick lease fails OPEN on a Redis error, so two ticks reading the same
    occurrence is a state the system survives rather than prevents. What must hold is the
    claim underneath: the identity in its WHERE clause is the OCCURRENCE, so the loser
    re-reads a schedule that has already advanced and stops without calling the gate.

    Counted through `audit_log` and through the ADVANCE, not through `status`: a status
    can only say "running" once however many times it was written, which is precisely the
    evidence a double fire would hide. A schedule advanced twice would have skipped a
    whole occurrence — the campaign would silently miss next Tuesday.
    """
    tenant_id, campaign_id = await _ready_campaign()
    recorded = await _schedule(tenant_id, campaign_id, days=EVERY_DAY)
    now = datetime.now(UTC)
    await _make_due(tenant_id, campaign_id, now - timedelta(minutes=1))

    results = await asyncio.gather(
        campaign_dispatch._fire_due_schedules(tenant_id),
        campaign_dispatch._fire_due_schedules(tenant_id),
    )

    assert sum(results) == 1, f"exactly one tick may fire it, got {results}"
    assert await _audit_count(tenant_id, campaign_id, "campaign.launched") == 1
    status, stored = await _stored(tenant_id, campaign_id)
    assert status == "running"
    assert stored is not None
    advanced = datetime.fromisoformat(stored["start_at"])
    assert advanced - recorded.next_occurrence_at <= timedelta(days=1), (
        "the repeat advanced by ONE occurrence, not two"
    )


async def test_an_occurrence_the_schedule_has_already_moved_past_is_not_fired_again() -> None:
    """The deterministic half of the test above, and the statement of what makes the fire
    idempotent: a `DueSchedule` naming an occurrence the column no longer holds is a
    stale read, whatever the clock says."""
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY)
    now = datetime.now(UTC)
    await _make_due(tenant_id, campaign_id, now - timedelta(minutes=1))
    async with tenant_session(tenant_id) as session:
        due = (await due_schedules(session, now=now))[0]
    async with tenant_session(tenant_id) as session:
        assert await fire_schedule(session, tenant_id=tenant_id, due=due, now=now) == "fired"

    # Same DueSchedule, replayed — as a tick that read before the winner committed would.
    async with tenant_session(tenant_id) as session:
        assert await fire_schedule(session, tenant_id=tenant_id, due=due, now=now) == "raced"
    assert await _audit_count(tenant_id, campaign_id, "campaign.launched") == 1


# --------------------------------------------------------------- stopping a repeat


async def test_stopping_a_repeat_takes_effect_before_the_next_tick_not_after_it() -> None:
    """The tick reads the due set in ONE transaction and fires in ANOTHER. A client who
    presses "stop repeating" in that gap must not be overtaken by the earlier read — the
    same deadline DNC additions are held to, and for the same reason: enforcement is a
    read at the moment of acting, never a snapshot taken before it."""
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY)
    now = datetime.now(UTC)
    await _make_due(tenant_id, campaign_id, now - timedelta(minutes=1))

    # The tick's first transaction: this occurrence is due.
    async with tenant_session(tenant_id) as session:
        due = (await due_schedules(session, now=now))[0]

    # The client stops it, in the gap.
    async with tenant_session(tenant_id) as session:
        cancelled = await unschedule_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    assert cancelled == scheduling.CancelledSchedule(kind="recurring", status="draft")

    # The tick's second transaction, carrying the read that came first.
    async with tenant_session(tenant_id) as session:
        assert await fire_schedule(session, tenant_id=tenant_id, due=due, now=now) == "raced"

    assert await _stored(tenant_id, campaign_id) == ("draft", None)
    assert await _audit_count(tenant_id, campaign_id, "campaign.launched") == 0
    # And end to end, through the tick itself.
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0


async def test_stopping_a_repeat_on_a_dialling_campaign_leaves_it_dialling() -> None:
    """Stop means "do not start this again", never "abandon the calls going out now" —
    cancelling those is what pause is for, and a stop button with a second, unadvertised
    effect is how a client loses a run they wanted."""
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY)
    now = datetime.now(UTC)
    await _make_due(tenant_id, campaign_id, now - timedelta(minutes=1))
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 1

    async with tenant_session(tenant_id) as session:
        cancelled = await unschedule_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    assert cancelled.status == "running"
    assert await _stored(tenant_id, campaign_id) == ("running", None)


async def test_a_campaign_with_no_schedule_at_all_says_so_rather_than_reporting_success() -> None:
    tenant_id, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await unschedule_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    assert excinfo.value.code == "campaign_not_scheduled"


# ------------------------------------------------- a repeat that repeats


async def test_a_finished_run_re_arms_the_repeat_rather_than_completing_the_campaign() -> None:
    """**The half-wired failure this closes.** Without it the first occurrence fires, the
    run ends `completed`, and every later occurrence sits under a status neither
    `due_schedules` nor `dispatch_scan()` looks at — a weekly campaign that runs once and
    looks finished, which is exactly what the old module docstring refused to ship.

    Driven through the real dispatch tick rather than by calling the re-arm directly, so
    the seam is what is tested and not just the function behind it.
    """
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY)
    now = datetime.now(UTC)
    await _make_due(tenant_id, campaign_id, now - timedelta(minutes=1))
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 1

    # The run finishes: every contact reached a terminal state (the post-call pipeline's
    # job, written here directly because this test is about what happens AFTER it).
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'connected', updated_at = now() "
                "WHERE campaign_id = :c"
            ),
            {"c": campaign_id},
        )

    await dispatch_campaign_tick({})

    status, stored = await _stored(tenant_id, campaign_id)
    assert status == "scheduled", "a repeat is not finished when one run is"
    assert stored is not None and stored["kind"] == "recurring"
    assert datetime.fromisoformat(stored["start_at"]) > now


async def test_a_campaign_with_no_repeat_still_completes() -> None:
    """The other branch of the same statement, so the re-arm cannot be "never complete"."""
    tenant_id, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        assert await complete_or_rearm(session, campaign_id=campaign_id) == "completed"
    assert (await _stored(tenant_id, campaign_id))[0] == "completed"


async def test_a_repeat_past_its_end_date_clears_itself_rather_than_promising_forever() -> None:
    """A rule that can never produce another occurrence must not sit on screen saying
    "repeats weekly" — the column goes to NULL, the same end state a stopped repeat
    reaches, and the fact is audited because "why did my campaign stop repeating" is a
    question a client asks a week later."""
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY, until=datetime.now(UTC) + MAX_HORIZON)
    now = datetime.now(UTC)
    # Due now, with the end date falling before whatever would come after it: this is the
    # LAST occurrence of the repeat.
    last = now - timedelta(minutes=1)
    await _make_due(tenant_id, campaign_id, last)
    await _set_end_date(tenant_id, campaign_id, last)

    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 1

    status, stored = await _stored(tenant_id, campaign_id)
    assert status == "running", "the last occurrence still ran"
    assert stored is None, "and nothing is promised after it"
    assert await _audit_count(tenant_id, campaign_id, "campaign.recurrence_ended") == 1


# ---------------------------------------------------------- fail-closed and tenancy


async def test_a_repeat_whose_rule_cannot_be_read_is_never_fired_on_a_guess() -> None:
    """Unreachable through `schedule_recurrence`, which validates and serializes the
    rule — which is exactly why it must fail closed. A rule we cannot read would
    otherwise default to "every day", and that dials seven times a week."""
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=[TUESDAY])
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{rule,days}', "
                "'\"whenever\"') WHERE id = :c"
            ),
            {"c": campaign_id},
        )
    await _make_due(tenant_id, campaign_id, datetime.now(UTC) - timedelta(minutes=1))

    async with tenant_session(tenant_id) as session:
        assert await due_schedules(session, now=datetime.now(UTC)) == []
    assert (await _stored(tenant_id, campaign_id))[0] == "scheduled"


async def test_the_scan_does_not_leak_one_tenants_repeat_to_another() -> None:
    """`due_schedules` reads `campaigns` with no tenant predicate of its own — RLS is the
    isolation, exactly as `db/session.py` intends. Recurrence adds no table and therefore
    no policy; this is the cross-tenant zero-rows assertion that keeps that true anyway."""
    tenant_a, campaign_a = await _ready_campaign()
    tenant_b, _ = await _ready_campaign()
    await _schedule(tenant_a, campaign_a, days=EVERY_DAY)
    now = datetime.now(UTC)
    await _make_due(tenant_a, campaign_a, now - timedelta(minutes=1))

    async with tenant_session(tenant_b) as session:
        assert await due_schedules(session, now=now) == []
    async with tenant_session(tenant_a) as session:
        assert [d.campaign_id for d in await due_schedules(session, now=now)] == [campaign_a]


async def test_the_progress_surface_says_when_the_next_occurrence_is() -> None:
    """§52: "scheduled" on its own is a state pretending to be an answer, and for a
    repeat it is worse — the client cannot even tell which day it means."""
    tenant_id, campaign_id = await _ready_campaign()
    recorded = await _schedule(tenant_id, campaign_id, days=[TUESDAY])
    async with tenant_session(tenant_id) as session:
        progress = await service.campaign_progress(session, campaign_id)
    assert progress["recurrence"] is not None
    assert progress["recurrence"]["days"] == [TUESDAY]
    assert progress["recurrence"]["at"] == "10:00"
    assert progress["recurrence"]["next_occurrence_at"] == recorded.next_occurrence_at
    assert progress["recurrence"]["last_skipped_reason"] is None


async def test_a_running_campaign_still_reports_the_repeat_it_is_running_under() -> None:
    """Unlike a one-time start, which is spent when it fires: a client watching a
    campaign dial needs to know it will do this again next Tuesday, and needs the stop
    button that goes with that knowledge."""
    tenant_id, campaign_id = await _ready_campaign()
    await _schedule(tenant_id, campaign_id, days=EVERY_DAY)
    await _make_due(tenant_id, campaign_id, datetime.now(UTC) - timedelta(minutes=1))
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 1

    async with tenant_session(tenant_id) as session:
        progress = await service.campaign_progress(session, campaign_id)
    assert progress["status"] == "running"
    assert progress["scheduled_start_at"] is None, "the occurrence it fired is spent"
    assert progress["recurrence"] is not None, "the repeat is not"
