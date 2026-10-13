"""The forwarding verification call (D-746): placing it, seeing it arrive, the findings, the
concurrency result, the limits, and that every minute of it is ours."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.forwarding_probe import ForwardingLegReport
from apps.api.forwarding import testing
from sqlalchemy import text
from tests.forwarding_fixtures import (
    SECOND_NUMBER,
    TRIAL_NUMBER,
    Rig,
    add_line,
    give_calevate_number,
    make_client,
    owner,
    rig_fixture,  # noqa: F401  (the `rig` fixture)
)

pytestmark = [pytest.mark.rls]


async def _client_with_line(**kwargs: object) -> tuple[UUID, UUID, UUID, str]:
    tenant_id, agent_id, _ = await make_client("verify")
    await give_calevate_number(tenant_id, agent_id)
    line = await add_line(tenant_id, **kwargs)  # type: ignore[arg-type]
    return tenant_id, agent_id, line.id, line.e164


async def _start(tenant_id: UUID, line_id: UUID) -> testing.ForwardingTestView:
    async with tenant_session(tenant_id) as session:
        return await testing.start_test(
            session, principal=owner(tenant_id), tenant_id=tenant_id, line_id=line_id, ip=None
        )


async def _inbound_call(tenant_id: UUID, agent_id: UUID, caller: str) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "from_e164, status, started_at, created_at, updated_at) VALUES (:id, :t, :a, "
                ":ecid, 'inbound', :f, 'completed', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "ecid": f"in_{call_id}", "f": caller},
        )
    return call_id


async def _claim(tenant_id: UUID, call_id: UUID, caller: str) -> testing.InboundClaim:
    async with tenant_session(tenant_id) as session:
        return await testing.claim_inbound_call(
            session, call_id=call_id, from_e164=caller, started_at=datetime.now(UTC)
        )


async def _close_window(tenant_id: UUID, test_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE forwarding_tests SET window_ends_at = now() WHERE id = :id"),
            {"id": test_id},
        )


async def test_two_legs_ring_the_recorded_number_from_both_platform_numbers(rig: Rig) -> None:
    tenant_id, _, line_id, e164 = await _client_with_line()
    test = await _start(tenant_id, line_id)
    assert (test.status, test.legs_placed) == ("ringing", 2)
    assert sorted(placed[1] for placed in rig.engine.placed) == sorted(
        [TRIAL_NUMBER, SECOND_NUMBER]
    )
    assert {placed[2] for placed in rig.engine.placed} == {e164}
    assert [job for job, _ in rig.enqueued] == [testing.HANG_UP_JOB, testing.SETTLE_JOB]
    async with tenant_session(tenant_id) as session:
        status = (await session.execute(text("SELECT status FROM forwarded_lines"))).scalar_one()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'forwarding.test_started' "
                    "AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert status == "testing" and audited == 1


async def test_both_legs_arriving_with_the_caller_shown_is_working_and_concurrent(rig: Rig) -> None:
    tenant_id, agent_id, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    for caller in (TRIAL_NUMBER, SECOND_NUMBER):
        call_id = await _inbound_call(tenant_id, agent_id, caller)
        claim = await _claim(tenant_id, call_id, caller)
        assert claim.test_id == test.id and not claim.caller_hidden
    await _close_window(tenant_id, test.id)
    assert await testing.settle_test(tenant_id, test.id) == "arrived"
    async with tenant_session(tenant_id) as session:
        line = (
            await session.execute(
                text("SELECT status, caller_id_finding, concurrency_finding FROM forwarded_lines")
            )
        ).one()
    assert tuple(line) == ("working", "caller_shown", "both_arrived")


async def test_the_business_number_shown_is_recorded_and_one_of_two_arriving(rig: Rig) -> None:
    tenant_id, _, line_id, e164 = await _client_with_line()
    test = await _start(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        verdict = await testing.record_lookup_arrival(
            session, tenant_id=tenant_id, caller_e164=e164, engine_call_id="conv_1"
        )
        # The vendor repeating its lookup for the same call is one arrival, not two.
        await testing.record_lookup_arrival(
            session, tenant_id=tenant_id, caller_e164=e164, engine_call_id="conv_1"
        )
    assert verdict.test_id == test.id
    await _close_window(tenant_id, test.id)
    await testing.settle_test(tenant_id, test.id)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT outcome, caller_id_finding, concurrency_finding FROM forwarding_tests")
            )
        ).one()
    assert tuple(row) == ("arrived", "business_number_shown", "one_arrived")


async def test_nothing_arriving_after_an_answered_leg_is_answered_on_the_phone(rig: Rig) -> None:
    tenant_id, _, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    await _close_window(tenant_id, test.id)
    assert await testing.settle_test(tenant_id, test.id) == "answered_on_phone"
    async with tenant_session(tenant_id) as session:
        status = (await session.execute(text("SELECT status FROM forwarded_lines"))).scalar_one()
    assert status == "not_working"


async def test_nothing_answered_and_nothing_arriving_is_not_arrived(rig: Rig) -> None:
    tenant_id, _, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    for placed in list(rig.engine.placed):
        assert placed
    async with untenanted_session() as session:
        refs = (
            (
                await session.execute(
                    text("SELECT engine_call_ref FROM forwarding_test_legs WHERE test_id = :t"),
                    {"t": test.id},
                )
            )
            .scalars()
            .all()
        )
    for ref in refs:
        rig.engine.reports[str(ref)] = ForwardingLegReport(ended=True, answered=False, seconds=0)
    await _close_window(tenant_id, test.id)
    assert await testing.settle_test(tenant_id, test.id) == "not_arrived"


async def test_one_platform_number_tests_one_leg_and_says_concurrency_was_not_tested(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "forwarding_test_second_number", None)
    tenant_id, agent_id, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    assert test.legs_placed == 1
    call_id = await _inbound_call(tenant_id, agent_id, TRIAL_NUMBER)
    await _claim(tenant_id, call_id, TRIAL_NUMBER)
    await _close_window(tenant_id, test.id)
    await testing.settle_test(tenant_id, test.id)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text("SELECT concurrency_finding FROM forwarding_tests"))
        ).one()
    assert row[0] == "not_tested"


async def test_settling_twice_settles_once(rig: Rig) -> None:
    tenant_id, _, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    await _close_window(tenant_id, test.id)
    await testing.settle_test(tenant_id, test.id)
    assert await testing.settle_test(tenant_id, test.id) == "already_settled"


async def test_one_refused_leg_places_the_other(rig: Rig) -> None:
    rig.engine.refuse_leg = 1
    tenant_id, _, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    assert (test.status, test.legs_placed) == ("ringing", 1)


async def test_every_leg_refused_leaves_the_test_failed_and_the_line_as_it_was(rig: Rig) -> None:
    rig.engine.refuse_all = True
    tenant_id, _, line_id, _ = await _client_with_line()
    failed = await _start(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, outcome, failure_code FROM forwarding_tests WHERE id = :i"),
                {"i": failed.id},
            )
        ).one()
        line_status = (await session.execute(text("SELECT status FROM forwarded_lines"))).scalar()
    assert tuple(row) == ("failed", "not_placed", "engine_call_refused")
    assert line_status == "untested"
    assert rig.enqueued == []


async def test_one_test_at_a_time_and_a_daily_cap(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _, line_id, _ = await _client_with_line()
    first = await _start(tenant_id, line_id)
    with pytest.raises(ProblemError) as busy:
        await _start(tenant_id, line_id)
    # The shared line is held by the first test's live legs, before the per-client check.
    assert busy.value.code in ("forwarding_test_running", "forwarding_test_line_busy")
    await _close_window(tenant_id, first.id)
    await testing.settle_test(tenant_id, first.id)
    monkeypatch.setattr(get_settings(), "forwarding_test_daily_cap", 1)
    with pytest.raises(ProblemError) as capped:
        await _start(tenant_id, line_id)
    assert capped.value.code == "forwarding_test_daily_cap" and capped.value.status == 429


async def test_only_between_nine_and_nine(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        testing, "ist_wall_clock", lambda _now: datetime(2026, 10, 11, 21, 30, tzinfo=UTC)
    )
    tenant_id, _, line_id, _ = await _client_with_line()
    with pytest.raises(ProblemError) as refused:
        await _start(tenant_id, line_id)
    assert refused.value.code == "forwarding_test_outside_hours"


async def test_a_trial_call_and_a_test_cannot_share_the_line(rig: Rig) -> None:
    from apps.api.agents import service as agents_service

    tenant_id, _, line_id, _ = await _client_with_line()
    await _start(tenant_id, line_id)
    other, _, _ = await make_client("trial")
    async with tenant_session(other) as session:
        with pytest.raises(ProblemError) as busy:
            await agents_service._hold_trial_line(session)
    assert busy.value.code == agents_service.TRIAL_LINE_BUSY_RULE


async def test_every_minute_of_a_test_is_absorbed(rig: Rig) -> None:
    from apps.api.billing.models import PLATFORM_ABSORBED_UNIT_TYPES

    tenant_id, agent_id, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    call_id = await _inbound_call(tenant_id, agent_id, TRIAL_NUMBER)
    await _claim(tenant_id, call_id, TRIAL_NUMBER)
    async with tenant_session(tenant_id) as session:
        metered = await testing.meter_test_arrival(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            minutes=Decimal("0.5"),
            cost=Decimal("1.38"),
        )
        again = await testing.meter_test_arrival(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            minutes=Decimal("0.5"),
            cost=Decimal("1.38"),
        )
    assert metered and again
    await _close_window(tenant_id, test.id)
    await testing.settle_test(tenant_id, test.id)
    async with tenant_session(tenant_id) as session:
        units = (
            await session.execute(text("SELECT unit_type, call_id IS NOT NULL FROM usage_events"))
        ).all()
    assert units, "the test metered nothing"
    assert {unit for unit, _ in units} == {"forwarding_test_min"}
    assert "forwarding_test_min" in PLATFORM_ABSORBED_UNIT_TYPES
    # One row for the arrival, one per outbound leg.
    assert sorted(bool(on_call) for _, on_call in units) == [False, False, True]


async def test_a_real_caller_inside_the_window_is_not_claimed(rig: Rig) -> None:
    tenant_id, agent_id, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    stranger = "+919700000001"
    call_id = await _inbound_call(tenant_id, agent_id, stranger)
    claim = await _claim(tenant_id, call_id, stranger)
    assert claim.test_id is None and not claim.caller_hidden
    # Nothing else arrived: the test reports another number arrived, said as uncertain.
    await _close_window(tenant_id, test.id)
    await testing.settle_test(tenant_id, test.id)
    async with tenant_session(tenant_id) as session:
        finding = (
            await session.execute(text("SELECT caller_id_finding FROM forwarding_tests"))
        ).scalar()
    assert finding == "other_number_shown"


async def test_hang_up_ends_the_live_legs(rig: Rig) -> None:
    tenant_id, _, line_id, _ = await _client_with_line()
    test = await _start(tenant_id, line_id)
    assert await testing.hang_up_legs(tenant_id, test.id) == 2
    assert len(rig.engine.hung) == 2
