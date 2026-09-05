"""DRAINING IS NOT ACTIVE, and the platform may not become ACTIVE while work is in flight.

The founder's sentence is the specification and one clause of it is the whole feature:

    "maintenance mode is fully activated in the backend also ONLY when there are no
    active calls or active jobs across the whole of Calevate and every client."

So the load-bearing test in this file is `test_active_is_unreachable_while_a_call_is_up`.
Everything else exists to make that one meaningful: that the probe counts what it claims
to count, that a truncated walk cannot pass for a drained platform, and that the deadline
is the ONLY other way through — with the stragglers recorded rather than discarded.

CONCURRENCY. `platform_maintenance_windows` has a partial UNIQUE index over the three open
states, so at most one window in this suite may be open at a time, and
`platform_state.load_shed_mode` is a single global row every other suite reads. The pattern
is `platform_halt_test`'s: exactly one test drives a full cycle, it holds the platform for
as few statements as possible, and it restores both in `finally`. Every other test here
either asserts a REFUSAL (moving nothing) or works on a window it deletes itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.core.loadshed import get_platform_status, set_platform_status
from apps.api.db.session import untenanted_session
from apps.api.ops.maintenance import (
    InFlight,
    activate,
    amend_window,
    begin_drain,
    cancel_window,
    claim_notice,
    complete_window,
    read_open_window,
    read_window,
    record_probe,
    schedule_window,
)
from apps.workers.maintenance import (
    _maintenance_greeting,
    _maintenance_prompt,
    _restore_mode,
    probe_in_flight,
)
from calevate_shared.engine import TRUTHFUL_ANSWER_DIRECTIVE, DisclosurePosture
from calevate_shared.events import TERMINAL_STATUSES
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def _clear_windows() -> None:
    """Leave no open window behind. This table has ONE open slot for the whole suite."""
    async with untenanted_session() as session:
        await session.execute(text("DELETE FROM platform_maintenance_windows"))


async def _schedule(*, minutes_out: int = 60, drain: int = 15) -> uuid.UUID:
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        window = await schedule_window(
            session,
            reason="Upgrading the telephony stack. Nothing is deleted.",
            starts_at=now + timedelta(minutes=minutes_out),
            ends_at=now + timedelta(minutes=minutes_out + 60),
            max_drain_minutes=drain,
            actor_id=None,
        )
    return window.id


# --------------------------------------------------------------- the two states


async def test_active_is_unreachable_while_a_call_is_up() -> None:
    """THE ONE THAT MATTERS. A live call is a person mid-sentence; the platform may not
    shut its client surface on top of them because a clock said so.

    Asserted against the DECIDER (`InFlight.drained`) rather than against the tick,
    because that predicate is what every path — the tick, the console, the forced arm —
    consults, and a test that drove the tick would be measuring the orchestration around
    the rule instead of the rule.
    """
    assert InFlight(calls=1, jobs=0, tenants_unreached=0, complete=True).drained is False
    assert InFlight(calls=0, jobs=1, tenants_unreached=0, complete=True).drained is False
    assert InFlight(calls=3, jobs=7, tenants_unreached=0, complete=True).drained is False
    # ...and the one case that IS drained, so the test cannot pass by always saying no.
    assert InFlight(calls=0, jobs=0, tenants_unreached=0, complete=True).drained is True


async def test_a_truncated_walk_is_not_a_drained_platform() -> None:
    """A ZERO NOBODY STANDS BEHIND IS NOT A ZERO.

    `probe_in_flight` walks the fleet one tenant session at a time under a wall-clock
    budget, so on a large client list it can run out before it has asked everybody. The
    tenants it did not reach may each be holding a live call. Counting that as "drained"
    would make the founder's "ONLY when" degrade silently, and in the direction that
    repairs itself the wrong way: the more clients we have, the more likely it is to be
    wrong.
    """
    truncated = InFlight(calls=0, jobs=0, tenants_unreached=4, complete=False)
    assert truncated.drained is False, "a walk that gave up early reported a clean drain"


async def test_the_state_machine_only_advances_one_step_at_a_time() -> None:
    """Each transition is a CAS from exactly one state, so a lost race is a no-op and a
    skipped state is impossible — no window may go from `scheduled` straight to `active`
    without having drained."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            # `activate` is `draining -> active`. From `scheduled` it must move nothing.
            with pytest.raises(Exception) as refused:
                await activate(
                    session,
                    window_id=window_id,
                    forced=False,
                    stragglers=None,
                    restore_mode="normal",
                )
            assert "scheduled" in str(refused.value) or "409" in str(refused.value)

        async with untenanted_session() as session:
            assert await begin_drain(session, window_id=window_id, max_drain_minutes=15)
            window = await read_window(session, window_id)
        assert window.state == "draining"
        assert window.drain_deadline_at is not None, "the deadline is stamped with the state"
        assert window.draining_since is not None
        # The operator must be able to SEE the deadline, so it has to be roughly right.
        elapsed = (window.drain_deadline_at - window.draining_since).total_seconds()
        assert 890 <= elapsed <= 910, "the drain deadline is not the bound the window carries"

        async with untenanted_session() as session:
            # And the second worker to reach the same edge does nothing rather than
            # writing a second `draining_since`.
            assert await begin_drain(session, window_id=window_id, max_drain_minutes=15) is False
    finally:
        await _clear_windows()


async def test_a_forced_activation_records_what_was_still_running() -> None:
    """The deadline is allowed to end the WAIT. It is not allowed to end it quietly.

    An operator who comes back to a window that activated itself has exactly one question
    — what was still going — and `stragglers` is the only place the answer survives the
    probe that measured it.
    """
    window_id = await _schedule(drain=1)
    try:
        async with untenanted_session() as session:
            await begin_drain(session, window_id=window_id, max_drain_minutes=1)
            # Backdate the deadline rather than sleeping: the property under test is that
            # an OVERDUE drain activates and records, not that time passes.
            await session.execute(
                text(
                    "UPDATE platform_maintenance_windows "
                    "SET drain_deadline_at = now() - interval '1 minute' WHERE id = :id"
                ),
                {"id": window_id},
            )
        async with untenanted_session() as session:
            window = await read_window(session, window_id)
        assert window.drain_overdue(datetime.now(UTC)) is True

        stuck = InFlight(calls=2, jobs=5, tenants_unreached=0, complete=True)
        async with untenanted_session() as session:
            assert await activate(
                session,
                window_id=window_id,
                forced=True,
                stragglers='{"calls": 2, "jobs": 5, "tenants_unreached": 0, "complete": true}',
                restore_mode="normal",
            )
            window = await read_window(session, window_id)
        assert window.state == "active"
        assert window.forced is True, "a forced activation that does not say so is a lie"
        assert window.stragglers == stuck.as_json()
        assert window.activated_at is not None
    finally:
        await _clear_windows()


async def test_drain_overdue_is_false_outside_draining() -> None:
    """A window that is not draining cannot be overdue, whatever the clock says — so no
    caller can force a `scheduled` window by moving a deadline it does not have."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            window = await read_window(session, window_id)
        assert window.drain_overdue(datetime.now(UTC) + timedelta(days=7)) is False
    finally:
        await _clear_windows()


# --------------------------------------------------------------- the probe itself


async def test_the_probe_counts_the_non_terminal_statuses_and_no_others() -> None:
    """The drain waits for calls that are still happening — and only those.

    The SQL spells its statuses as literal text (`check_raw_sql` requires every character
    of an interpolated fragment to be ours), so nothing at runtime keeps it in step with
    `calevate_shared.events.TERMINAL_STATUSES`. This is that check. A sixth terminal status
    added there and forgotten here would make every drain wait for calls that are over.
    """
    from apps.api.crm.models import CALL_STATUSES
    from apps.workers.maintenance import _ACTIVE_CALL_SQL

    sql = str(_ACTIVE_CALL_SQL)
    counted = {status for status in CALL_STATUSES if f"'{status}'" in sql}
    assert counted == set(CALL_STATUSES) - TERMINAL_STATUSES, (
        "the drain's idea of a live call has drifted from the shared terminal-status set"
    )


async def test_the_probe_runs_and_reports_a_complete_walk() -> None:
    """The real thing, against the real database. On a suite with no live calls it must
    answer a COMPLETE walk — a probe that reported `complete=False` on an idle platform
    would make every drain run to its deadline for ever."""
    in_flight = await probe_in_flight()
    assert in_flight.complete is True
    assert in_flight.tenants_unreached == 0
    assert in_flight.calls >= 0 and in_flight.jobs >= 0


async def test_the_recorded_probe_is_what_the_console_reads() -> None:
    """The screen and the decision read ONE measurement. An operator forcing a window on
    numbers taken by a different code path is the failure mode this shares-one-row design
    exists to prevent."""
    window_id = await _schedule()
    try:
        measured = InFlight(calls=4, jobs=1, tenants_unreached=0, complete=True)
        async with untenanted_session() as session:
            await record_probe(session, window_id=window_id, in_flight=measured)
            window = await read_window(session, window_id)
        assert window.in_flight == measured.as_json()
        assert window.probed_at is not None, "the console cannot say how old the numbers are"
    finally:
        await _clear_windows()


# --------------------------------------------------------------- announced = committed


async def test_an_announced_window_may_not_have_its_start_moved() -> None:
    """A window clients have been told about is a commitment, and the commitment is the
    START. Moving it in either direction breaks somebody's plan: earlier takes away notice
    they arranged their morning around, later strands the client who rescheduled. The
    honest verb is cancel-and-reschedule, which every client hears."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            assert await claim_notice(session, window_id=window_id, kind="advance")
        async with untenanted_session() as session:
            with pytest.raises(Exception) as refused:
                await amend_window(
                    session,
                    window_id=window_id,
                    starts_at=datetime.now(UTC) + timedelta(hours=3),
                )
        assert "maintenance_start_announced" in str(refused.value)
    finally:
        await _clear_windows()


async def test_an_unannounced_window_may_still_be_moved_freely() -> None:
    """The control on the test above: before anybody has been told, there is nothing to
    break, so an operator fixing a typo in a start time is not made to cancel."""
    window_id = await _schedule()
    try:
        moved = datetime.now(UTC) + timedelta(hours=5)
        async with untenanted_session() as session:
            window = await amend_window(
                session, window_id=window_id, starts_at=moved, ends_at=moved + timedelta(hours=1)
            )
        assert abs((window.starts_at - moved).total_seconds()) < 1
    finally:
        await _clear_windows()


async def test_a_client_visible_amendment_re_announces() -> None:
    """An amendment nobody hears is worse than no amendment: the client's last message
    about this window would describe a window that no longer exists. Changing the END
    clears the amendment claim so the tick mails everybody again."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            await claim_notice(session, window_id=window_id, kind="advance")
            await claim_notice(session, window_id=window_id, kind="amended")
            assert (await read_window(session, window_id)).amended_notice_at is not None
        async with untenanted_session() as session:
            window = await amend_window(
                session, window_id=window_id, ends_at=datetime.now(UTC) + timedelta(hours=9)
            )
        assert window.amended_notice_at is None, "the changed window will not re-announce"
    finally:
        await _clear_windows()


async def test_a_drain_bound_change_alone_does_not_re_announce() -> None:
    """The control in the other direction. The drain bound is an operational number no
    client is shown; mailing every client because an operator gave the drain five more
    minutes is how announcement emails become noise people filter."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            await claim_notice(session, window_id=window_id, kind="advance")
            await claim_notice(session, window_id=window_id, kind="amended")
        async with untenanted_session() as session:
            window = await amend_window(session, window_id=window_id, max_drain_minutes=30)
        assert window.amended_notice_at is not None, "a private change mailed every client"
        assert window.max_drain_minutes == 30
    finally:
        await _clear_windows()


async def test_the_deadline_moves_when_the_drain_bound_is_extended_mid_drain() -> None:
    """An operator watching a drain must be able to give it longer, and the extension has
    to reach the DEADLINE — a bound whose deadline did not move is a bound that does not
    apply, and the window would force at the old instant regardless."""
    window_id = await _schedule(drain=5)
    try:
        async with untenanted_session() as session:
            await begin_drain(session, window_id=window_id, max_drain_minutes=5)
            before = await read_window(session, window_id)
        async with untenanted_session() as session:
            after = await amend_window(session, window_id=window_id, max_drain_minutes=45)
        assert before.drain_deadline_at is not None and after.drain_deadline_at is not None
        assert after.drain_deadline_at > before.drain_deadline_at
    finally:
        await _clear_windows()


# --------------------------------------------------------------- the singleton and the verbs


async def test_only_one_window_may_be_open() -> None:
    """One maintenance slot, refused with a sentence rather than a constraint name."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            with pytest.raises(Exception) as refused:
                await schedule_window(
                    session,
                    reason="A second, overlapping window nobody asked for.",
                    starts_at=datetime.now(UTC) + timedelta(days=2),
                    ends_at=datetime.now(UTC) + timedelta(days=2, hours=1),
                    actor_id=None,
                )
        assert "maintenance_window_exists" in str(refused.value)
        assert str(window_id) in str(refused.value) or "scheduled" in str(refused.value)
    finally:
        await _clear_windows()


async def test_a_window_cannot_start_in_the_past_or_be_instantaneous() -> None:
    """Both refusals name what to do. A past start would drain the platform on the next
    tick with no notice sent; a five-second window would complete before its drain."""
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        with pytest.raises(Exception) as past:
            await schedule_window(
                session,
                reason="A window that has already started, which is not a plan.",
                starts_at=now - timedelta(minutes=1),
                ends_at=now + timedelta(hours=1),
                actor_id=None,
            )
        assert "maintenance_starts_in_the_past" in str(past.value)

        with pytest.raises(Exception) as short:
            await schedule_window(
                session,
                reason="A window too short for its own drain to finish.",
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=1, seconds=30),
                actor_id=None,
            )
        assert "maintenance_window_too_short" in str(short.value)


async def test_an_active_window_is_ended_not_cancelled() -> None:
    """`cancel` is "never mind"; `end` is "we are finished". An ACTIVE window has already
    shut the client surface and owes restoration work, so it may only be ended — and the
    refusal is what stops an operator taking the cheaper-looking verb and leaving every
    campaign paused."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            await begin_drain(session, window_id=window_id, max_drain_minutes=15)
            await activate(
                session,
                window_id=window_id,
                forced=False,
                stragglers=None,
                restore_mode="normal",
            )
        async with untenanted_session() as session:
            with pytest.raises(Exception) as refused:
                await cancel_window(session, window_id=window_id)
        assert "active" in str(refused.value)

        async with untenanted_session() as session:
            assert await complete_window(session, window_id=window_id)
            assert (await read_window(session, window_id)).state == "completed"
    finally:
        await _clear_windows()


async def test_a_notice_is_claimed_exactly_once() -> None:
    """The fan-out runs on every worker process. The claim is what makes each client's
    advance warning arrive once rather than once per worker."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            assert await claim_notice(session, window_id=window_id, kind="advance") is True
        async with untenanted_session() as session:
            assert await claim_notice(session, window_id=window_id, kind="advance") is False
            # ...and the other kinds are unaffected: they are separate promises.
            assert await claim_notice(session, window_id=window_id, kind="active") is True
    finally:
        await _clear_windows()


async def test_read_open_window_ignores_finished_ones() -> None:
    """A completed window is not a window. If it answered here, every client would see a
    banner for an outage that is over and the tick would try to advance it for ever."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            assert (await read_open_window(session)) is not None
            await cancel_window(session, window_id=window_id)
        async with untenanted_session() as session:
            assert (await read_open_window(session)) is None
    finally:
        await _clear_windows()


# --------------------------------------------------------------- what the caller hears


async def test_the_maintenance_prompt_keeps_hard_rule_5s_floor() -> None:
    """A maintenance agent is still an agent. A caller who asks whether they are talking to
    an AI, or whether the call is recorded, gets the truth during a window exactly as they
    do outside one — no column, config row or window may withdraw it."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            window = await read_window(session, window_id)
        prompt = _maintenance_prompt(window)
        assert TRUTHFUL_ANSWER_DIRECTIVE in prompt
        # And it tells the agent to stop rather than to keep doing business over a
        # platform that is being worked on.
        assert "call back" in prompt.lower() or "call again" in prompt.lower()
    finally:
        await _clear_windows()


async def test_the_maintenance_greeting_keeps_the_clients_own_disclosures() -> None:
    """THE COMPLIANCE-LOAD-BEARING LINE. `opening_line` is what an agent VOLUNTEERS — the
    AI disclosure and the recording notice, each on its own client-set switch (D-163).
    Replacing it with a maintenance sentence would switch both off, silently, for every
    client at once, for the length of the window. So it is PREPENDED."""
    window_id = await _schedule()
    try:
        async with untenanted_session() as session:
            window = await read_window(session, window_id)
        posture = DisclosurePosture(
            ai_disclosure_line="Idi AI assistant.",
            ai_disclosure_enabled=True,
            recording_notice_line="Ee call record avutundi.",
            recording_notice_enabled=True,
            caller_memory_notice_line="",
            caller_memory_enabled=False,
        )
        greeting = _maintenance_greeting(window, posture)
        assert greeting.startswith("Idi AI assistant.")
        assert "Ee call record avutundi." in greeting
        assert "maintenance" in greeting.lower()

        # An agent with both notices off composes an EMPTY opening line, which is a
        # legitimate configuration — the maintenance sentence must not arrive with a
        # leading space or an empty limb in front of it.
        silent = posture.model_copy(
            update={"ai_disclosure_enabled": False, "recording_notice_enabled": False}
        )
        assert _maintenance_greeting(window, silent).startswith("We are briefly closed")
    finally:
        await _clear_windows()


# --------------------------------------------------------------- restoring the shed mode


async def test_the_restored_mode_is_narrowed_and_never_maintenance() -> None:
    """A window that opened during a `reduced` shed must not end by declaring the platform
    healthy — the shed is somebody else's decision with its own reason. And `maintenance`
    must never be restorable: a window that ended by re-entering maintenance would be an
    outage nothing ends."""
    assert _restore_mode("reduced") == "reduced"
    assert _restore_mode("emergency") == "emergency"
    assert _restore_mode("normal") == "normal"
    assert _restore_mode("maintenance") == "normal"
    assert _restore_mode(None) == "normal"
    assert _restore_mode("nonsense-from-a-future-deploy") == "normal"


async def test_activating_stores_the_mode_to_put_back() -> None:
    """Read at activation and written in the same statement, so completion restores rather
    than assuming. THIS TEST MOVES THE GLOBAL SHED MODE and restores it in `finally` —
    `platform_halt_test`'s pattern, because every other suite reads that row."""
    window_id = await _schedule()
    before = (await get_platform_status(force_refresh=True)).mode
    try:
        await set_platform_status(mode="reduced", actor_id=None)
        current = (await get_platform_status(force_refresh=True)).mode
        async with untenanted_session() as session:
            await begin_drain(session, window_id=window_id, max_drain_minutes=15)
            await activate(
                session,
                window_id=window_id,
                forced=False,
                stragglers=None,
                restore_mode=current,
            )
            window = await read_window(session, window_id)
        assert window.restore_load_shed_mode == "reduced"
    finally:
        await set_platform_status(mode=before, actor_id=None)
        await _clear_windows()
