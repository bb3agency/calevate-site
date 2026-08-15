"""The scheduled drift sweep: the two divergences a publish-time read-back cannot see.

D-121 built `engine_drift_for` and left it ON DEMAND, so a drift was found by whoever
thought to open one agent's screen. This file is the sweep that finds them without being
asked, and the two cases below are the whole reason it exists — a publish-time check is
structurally incapable of either, because in neither case does any code of ours run:

    A VENDOR-DASHBOARD EDIT      somebody changes the agent on the vendor's own console.
                                 Every table we own agrees with itself and is wrong.
    A LOST-RESPONSE PUBLISH      the vendor committed and the response never reached us,
                                 so OUR transaction rolled back to the previous script
                                 and the engine kept the new one. The divergence points
                                 the OTHER WAY and no amount of re-reading our own tables
                                 can find it.

**EVERY ASSERTION IS AGAINST WHAT THE SWEEP RECORDED AND WHAT THE ENGINE STILL HOLDS**,
never only against our own rows — the defect class here IS our database agreeing with
itself. In particular the second case is set up by making the vendor commit and then
failing our side, which is why it needs a double that fails on the RESPONSE rather than
on the request.

RECONCILIATION IS A READ. The clause `test_the_sweep_never_republishes_over_a_drift` is
not decoration: D-121 argues that re-publishing would overwrite an operator's emergency
console edit, and the only way that argument survives a future refactor is a test that
fails when somebody helpfully adds a repair.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts, publishing
from apps.api.agents.reconciliation import (
    DRIFT_STATES,
    claim_drift_batch,
    read_engine_drift,
    record_drift,
)
from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers import engine_reconciliation
from apps.workers.engine_reconciliation import SWEEP_INTERVAL_S, sweep_engine_drift
from arq import Retry
from calevate_shared.engine import AgentConfig, AgentSnapshot, EngineAgentRef
from sqlalchemy import text

SCRIPT = "Sunrise Clinic receptionist. Greet in Telugu, then take the appointment."
VOICE = "bulbul:v3:anushka"
DASHBOARD_EDIT = "Whatever the vendor's console was used to write at 3am."
NEW_SCRIPT = "Sunrise Clinic receptionist. Quote the NEW price list."


# --- doubles -----------------------------------------------------------------


class RecordingEngine(FakeEngine):
    """`FakeEngine` that remembers what it was ASKED, in order.

    The base class keeps what it HOLDS; what no other instrument can see is the SEQUENCE
    of calls, and "did the sweep write anything back?" is a question about the sequence.
    """

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.calls: list[tuple[str, str]] = []

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        ref = await super().create_agent(cfg)
        self.calls.append(("create_agent", ref))
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        await super().update_agent(ref, cfg)
        self.calls.append(("update_agent", ref))

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        self.calls.append(("get_agent", ref))
        return await super().get_agent(ref)

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        self.calls.append(("delete_agent", ref))
        await super().delete_agent(ref)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class LostResponseEngine(RecordingEngine):
    """The vendor COMMITS and the response never arrives.

    This is the second drift, and it is the one a naive double cannot produce: an engine
    that raises BEFORE storing leaves both sides agreeing that nothing happened, which is
    not a divergence at all. So the write lands first and the exception is raised after —
    a connection reset on the response, which is exactly the failure `EngineDrift`'s
    docstring names.
    """

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        await super().update_agent(ref, cfg)
        raise ProblemError(
            kind="dependency",
            code="engine_unreachable",
            title="Voice engine unreachable",
            detail="The voice platform did not respond.",
        )


class UnreachableOnReadEngine(RecordingEngine):
    """Answers writes and fails every read-back — the `unreachable` verdict."""

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        self.calls.append(("get_agent", ref))
        raise ProblemError(
            kind="dependency",
            code="engine_unavailable",
            title="Voice engine unavailable",
            detail="The voice platform did not answer.",
        )


@contextmanager
def _engine(instance: FakeEngine) -> Iterator[FakeEngine]:
    """Run the block against `instance`, restoring the cache afterwards. Reaches into
    `apps.api.engine`'s instance cache because that is what `get_engine()` resolves
    through — the shape `publish_verification_test._engine` established."""
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


# --- fixtures ----------------------------------------------------------------


async def _published_agent(engine: FakeEngine) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A tenant with one agent that is genuinely live on `engine`, and its vendor ref."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Drift Clinic",
        slug=f"dr-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=SCRIPT,
            notes=None,
            created_by=None,
        )
        await session.execute(
            text("UPDATE agents SET tts_voice = :v, tts_provider = 'sarvam' WHERE id = :a"),
            {"v": VOICE, "a": agent_id},
        )
    with _engine(engine):
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return tenant_id, agent_id, ref


async def _only(*refs: str) -> None:
    """Put exactly these vendor objects in the sweep's scope, platform-wide.

    THE SUITE SHARES ONE DATABASE and nothing truncates between files, so by the time this
    module runs there are routing rows from every other suite that has ever published an
    agent. The sweep is deliberately GLOBAL — that is the feature — so `checked=1` would
    otherwise mean "one plus however many agents the campaign tests happened to leave
    behind", which is a number that changes with test ordering.

    `active` is the right lever rather than a hack: it is precisely the predicate
    `claim_drift_batch` and `read_engine_drift` filter on (an agent nobody publishes to any
    more is not worth a vendor round trip), it is written by `experiments.py` in production
    for exactly that meaning, and NO other query in the tree reads it — so flipping it here
    cannot perturb another suite.
    """
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE engine_agent_routes SET active = (engine_agent_ref = ANY(:mine))"),
            {"mine": list(refs)},
        )


async def _route(ref: str) -> tuple[str | None, datetime | None, datetime | None]:
    """(drift_state, drift_checked_at, drift_detected_at) for one vendor object."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT drift_state, drift_checked_at, drift_detected_at "
                    "FROM engine_agent_routes WHERE engine = 'fake' AND engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).first()
    assert row is not None, "the publish did not write a routing row"
    return row[0], row[1], row[2]


# --- 1. the schema and the code agree on the vocabulary ----------------------


async def test_the_stored_verdicts_are_exactly_the_ones_the_check_constraint_allows() -> None:
    """`DRIFT_STATES` is derived from `VerifyState`, and the CHECK in `d4b8e1c73f05` is a
    literal. A verdict added to the type and not to the constraint is a sweep that starts
    failing every write at 03:07 with nothing on any screen to explain it, so the two are
    compared against the LIVE database rather than against the migration's source."""
    async with untenanted_session() as session:
        clause = (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_engine_agent_routes_drift_state'"
                )
            )
        ).scalar_one()
    in_constraint = {word.strip("'") for word in str(clause).split("'") if word.strip("', ()")}
    assert in_constraint >= DRIFT_STATES, (
        "the application can produce a verdict the database will reject: "
        + str(sorted(DRIFT_STATES - in_constraint))
    )


# --- 2. the two drifts only reconciliation can see ---------------------------


async def test_the_sweep_finds_an_agent_edited_in_the_vendors_dashboard() -> None:
    """DRIFT ONE. Nothing of ours ran, so no table of ours can know — and nobody opened
    the agent's screen, which is the whole difference from D-121's on-demand read."""
    engine = RecordingEngine()
    _, _, ref = await _published_agent(engine)
    await _only(ref)

    with _engine(engine):
        # Clean first, so a green verdict is proved reachable and the red one below is
        # not simply "this sweep always says not_applied".
        assert await sweep_engine_drift({}) == "checked=1 drifted=0"
        clean_state, clean_checked, clean_detected = await _route(ref)
        assert clean_state == "applied"
        assert clean_checked is not None
        assert clean_detected is None, "an in-sync object was stamped as drifted"

        # Somebody edits the agent on the vendor's console. Our rows are untouched.
        engine._agents[ref] = engine._agents[ref].model_copy(
            update={"system_prompt": DASHBOARD_EDIT}
        )
        assert await sweep_engine_drift({}) == "checked=1 drifted=1"

    state, checked_at, detected_at = await _route(ref)
    assert state == "not_applied"
    assert checked_at is not None
    assert detected_at is not None, "a drift with no start date cannot be aged by an operator"
    # THE READ PROPERTY: the vendor's edit is still standing.
    assert engine._agents[ref].system_prompt == DASHBOARD_EDIT


async def test_the_sweep_finds_a_publish_that_landed_after_our_side_failed() -> None:
    """DRIFT TWO, and the one every naive double gets wrong.

    The vendor COMMITTED the update and the response was lost, so `publish_agent` raised,
    our transaction rolled back, and our rows still describe the previous script while the
    engine is running the new one. The divergence points the other way: re-reading
    `agents` finds a perfectly consistent row. Only a read of THEIRS can see it.
    """
    engine = LostResponseEngine()
    tenant_id, agent_id, ref = await _published_agent(engine)
    await _only(ref)

    with _engine(engine):
        assert await sweep_engine_drift({}) == "checked=1 drifted=0"

        # A new script is STAGED (two-speed publishing: `write_prompt_version` moves the
        # draft pointer, not the live one), then applied.
        async with tenant_session(tenant_id) as session:
            await prompts.write_prompt_version(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                body=NEW_SCRIPT,
                notes=None,
                created_by=None,
            )

        # `apply_to_live` is the REAL caller and the reason this divergence exists at all:
        # it moves `live_prompt_id` and pushes to the engine INSIDE ONE TRANSACTION. The
        # vendor takes the write and the response is lost, so our half rolls back to the
        # previous script and theirs keeps the new one. Doing this by hand in two
        # committed transactions would leave our row pointing at the same script the
        # engine holds — a green sweep measuring nothing.
        with pytest.raises(ProblemError):
            await publishing.apply_to_live(tenant_id=tenant_id, agent_id=agent_id)

        # OUR OWN TABLES ARE CONSISTENT AND WRONG. This is the assertion that makes the
        # case distinct from the dashboard edit: nothing we store is self-contradictory.
        async with tenant_session(tenant_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT a.status, a.live_verify_state, pv.body FROM agents a "
                        "JOIN prompt_versions pv ON pv.id = a.live_prompt_id WHERE a.id = :a"
                    ),
                    {"a": agent_id},
                )
            ).first()
        assert row is not None
        assert row[0] == "live" and row[1] == "applied"
        assert NEW_SCRIPT not in str(row[2]), (
            "the rolled-back publish left our own row claiming the new script, so this "
            "test is measuring something other than the lost-response divergence"
        )

        assert await sweep_engine_drift({}) == "checked=1 drifted=1"

    state, _, detected_at = await _route(ref)
    assert state == "not_applied"
    assert detected_at is not None
    # The engine really is running the script our tables have never heard of.
    assert NEW_SCRIPT in engine._agents[ref].system_prompt


async def test_the_sweep_never_republishes_over_a_drift() -> None:
    """D-121's argument, held as a property rather than a comment.

    Re-publishing over a drift overwrites whatever the vendor's dashboard was used to
    change, which may have been the correct emergency edit made while our console was the
    thing that was down. Doing that platform-wide, on a schedule, unattended, is the worst
    possible way to make that decision. So the sweep may call `get_agent` and NOTHING
    else, and this fails the day somebody adds a helpful repair.
    """
    engine = RecordingEngine()
    _, _, ref = await _published_agent(engine)
    await _only(ref)
    engine._agents[ref] = engine._agents[ref].model_copy(update={"system_prompt": DASHBOARD_EDIT})
    engine.calls.clear()

    with _engine(engine):
        await sweep_engine_drift({})

    assert engine.names() == ["get_agent"], (
        "the sweep did more than read: " + str(engine.names()) + ". Reconciliation reports; "
        "a repair is a decision with a blast radius and belongs to a human."
    )
    assert engine._agents[ref].system_prompt == DASHBOARD_EDIT


# --- 3. the bounds, which are what keep this from taking the platform down ----


async def test_the_batch_is_bounded_and_ordered_by_staleness() -> None:
    """One vendor round trip per agent per tick is the whole bill, so the cap is the
    feature — and the ORDERING is what makes a cap fair instead of starving. A row that
    has never been checked outranks every checked one; among checked ones, oldest first.
    """
    engine = RecordingEngine()
    refs = [(await _published_agent(engine))[2] for _ in range(3)]
    await _only(*refs)
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        # Two checked at known instants, one never checked.
        for ref, age_h in ((refs[0], 1), (refs[1], 9)):
            await session.execute(
                text(
                    "UPDATE engine_agent_routes SET drift_state = 'applied', "
                    "drift_checked_at = :t WHERE engine_agent_ref = :r"
                ),
                {"t": now - timedelta(hours=age_h), "r": ref},
            )

    async with untenanted_session() as session:
        batch = await claim_drift_batch(session, engine="fake", limit=2)
    assert [c.engine_agent_ref for c in batch] == [refs[2], refs[1]], (
        "the batch is not stalest-first: a never-checked agent must outrank a stale one, "
        "and without that ordering the cap starves whatever sorts last forever"
    )

    # And the cap is honoured against the engine, not just against the query.
    engine.calls.clear()
    with _engine(engine):
        result = await sweep_engine_drift({})
    assert result == "checked=3 drifted=0"
    assert engine.names().count("get_agent") == 3


async def test_a_full_batch_leaves_the_rest_first_in_line_rather_than_unread() -> None:
    """The bound must not become a blind spot. Rows a capped tick did not reach keep their
    old `drift_checked_at`, so the NEXT tick takes them first — which is why the sweep
    needs no cursor and cannot lose its place when a tick dies halfway."""
    engine = RecordingEngine()
    refs = [(await _published_agent(engine))[2] for _ in range(3)]
    await _only(*refs)

    with _engine(engine), _batch_size(1):
        assert await sweep_engine_drift({}) == "checked=1 drifted=0"
        first = {ref for ref in refs if (await _route(ref))[0] is not None}
        assert len(first) == 1

        assert await sweep_engine_drift({}) == "checked=1 drifted=0"
        second = {ref for ref in refs if (await _route(ref))[0] is not None}
    assert len(second) == 2 and first < second, (
        "the second tick re-read what the first already did — the cap is a cap on "
        "COVERAGE rather than on cost, and the tail is never reached"
    )


@contextmanager
def _batch_size(size: int) -> Iterator[None]:
    previous = engine_reconciliation.SWEEP_BATCH_SIZE
    engine_reconciliation.SWEEP_BATCH_SIZE = size
    try:
        yield
    finally:
        engine_reconciliation.SWEEP_BATCH_SIZE = previous


def test_the_tick_cannot_outlive_its_own_interval() -> None:
    """The sweep skips the Redis lease `campaign_dispatch` needs, and the whole licence
    for that is an arithmetic relationship between its budget and its schedule. An
    assumption that has stopped being true must fail at import, not at 03:07."""
    assert engine_reconciliation.SWEEP_BUDGET_S + 60.0 < SWEEP_INTERVAL_S
    engine_reconciliation._assert_the_tick_fits_its_interval()

    previous = engine_reconciliation.SWEEP_BUDGET_S
    engine_reconciliation.SWEEP_BUDGET_S = float(SWEEP_INTERVAL_S)
    try:
        with pytest.raises(AssertionError, match="overlap"):
            engine_reconciliation._assert_the_tick_fits_its_interval()
    finally:
        engine_reconciliation.SWEEP_BUDGET_S = previous


# --- 4. what an operator can see ---------------------------------------------


async def test_the_ops_summary_counts_drift_undetermined_and_unswept_separately() -> None:
    """A job that writes a state nobody reads is the half-wired-feature defect, so the
    sweep's output has to reach the screen that already carries the DLQ depth — and it has
    to arrive as THREE numbers, not one.

    `undetermined` is held out of `out_of_sync` for the reason `verification.py` separates
    them at the source: "the engine is provably running something else" and "we could not
    read the answer" are different facts and only one is evidence. A console that added
    them would report a vendor having a slow afternoon as a fleet of drifted agents, which
    is a number an operator learns to ignore inside a week.
    """
    good = RecordingEngine()
    drifted_ref = (await _published_agent(good))[2]
    clean_ref = (await _published_agent(good))[2]
    good._agents[drifted_ref] = good._agents[drifted_ref].model_copy(
        update={"system_prompt": DASHBOARD_EDIT}
    )
    unread = UnreachableOnReadEngine()
    unread_ref = (await _published_agent(unread))[2]
    # One agent nobody has swept at all.
    never_ref = (await _published_agent(good))[2]
    await _only(drifted_ref, clean_ref, unread_ref, never_ref)

    with _engine(good), _batch_size(2):
        await sweep_engine_drift({})  # reaches the two never-checked of good's three
    async with untenanted_session() as session:
        # Drive the two named objects deterministically rather than relying on which two
        # the capped tick happened to take.
        for ref, state in ((drifted_ref, "not_applied"), (clean_ref, "applied")):
            await record_drift(session, engine="fake", ref=ref, state=state)
        await record_drift(session, engine="fake", ref=unread_ref, state="unreachable")
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET drift_state = NULL, drift_checked_at = NULL, "
                "drift_detected_at = NULL WHERE engine_agent_ref = :r"
            ),
            {"r": never_ref},
        )

    async with untenanted_session() as session:
        summary = await read_engine_drift(session, engine="fake")

    assert summary.live_agents == 4
    assert summary.out_of_sync == 1, "the one provably wrong agent is the alarm"
    assert summary.undetermined == 1, "an unreadable engine was counted as a drifted agent"
    assert summary.in_sync == 1
    assert summary.never_checked == 1, "an agent nobody swept was counted as one we liked"
    assert (
        summary.live_agents
        == summary.out_of_sync + summary.undetermined + summary.in_sync + summary.never_checked
    ), "the parts do not sum to the total, so the panel contradicts itself"
    assert summary.oldest_drift_at is not None
    assert summary.oldest_checked_at is not None


async def test_a_drift_that_persists_keeps_the_detection_time_it_was_first_given() -> None:
    """The number that separates a race from a real divergence is AGE, so re-stamping
    `drift_detected_at` every tick would report a fortnight-old vendor edit as "detected
    just now" — and an operator triaging by age would deprioritise the worst one."""
    engine = RecordingEngine()
    _, _, ref = await _published_agent(engine)
    await _only(ref)
    engine._agents[ref] = engine._agents[ref].model_copy(update={"system_prompt": DASHBOARD_EDIT})

    with _engine(engine):
        await sweep_engine_drift({})
        first = (await _route(ref))[2]
        await sweep_engine_drift({})
        second = (await _route(ref))[2]
    assert first is not None and first == second, "the drift clock was reset by re-observing it"

    # And it CLEARS the moment the object reads back clean, so a fixed drift stops being
    # counted without anyone having to acknowledge it.
    async with untenanted_session() as session:
        await record_drift(session, engine="fake", ref=ref, state="applied")
    assert (await _route(ref))[2] is None


async def test_an_unreachable_engine_is_recorded_and_does_not_raise_the_alarm() -> None:
    """One sick agent must not fail the sweep for the other twenty-four, and must not fire
    the alarm either: `unreachable` is not evidence of a drift, and an alert that treats it
    as one is an alert nobody reads by the second week."""
    engine = UnreachableOnReadEngine()
    _, _, ref = await _published_agent(engine)
    await _only(ref)
    engine.calls.clear()

    with _engine(engine):
        assert await sweep_engine_drift({}) == "checked=1 drifted=0"
    state, checked_at, detected_at = await _route(ref)
    assert state == "unreachable"
    assert checked_at is not None, "an attempt that failed was not recorded as an attempt"
    assert detected_at is None, "a vendor we could not reach was filed as a proven drift"


async def test_a_soft_deleted_agent_is_skipped_rather_than_failing_the_tick() -> None:
    """A sweep works from a snapshot, so a delete landing mid-tick is normal. It must not
    be a recorded verdict either — writing `not_published` for an agent that no longer
    exists would put a permanent row on the console that nothing can ever clear."""
    engine = RecordingEngine()
    tenant_id, agent_id, ref = await _published_agent(engine)
    await _only(ref)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET deleted_at = now() WHERE id = :a"), {"a": agent_id}
        )
    engine.calls.clear()

    with _engine(engine):
        assert await sweep_engine_drift({}) == "checked=0 drifted=0"
    assert engine.names() == [], "a deleted agent cost a vendor round trip"
    assert (await _route(ref))[0] is None


async def test_a_route_deleted_mid_sweep_records_nothing_and_is_not_counted() -> None:
    """A sweep works from a snapshot, so the object can be unpublished between the batch
    read and the round trip. `record_drift` returns False on zero rows, and that must be a
    non-outcome rather than a verdict: a `checked` count that included objects we never
    recorded would report coverage the console cannot corroborate."""
    engine = RecordingEngine()
    _, _, ref = await _published_agent(engine)
    await _only(ref)

    engine.calls.clear()
    original = engine_reconciliation.claim_drift_batch

    async def deleting_claim(session: Any, **kw: Any) -> Any:
        batch = await original(session, **kw)
        # The route disappears AFTER it is claimed — the window the rowcount guards.
        async with untenanted_session() as other:
            await other.execute(
                text("DELETE FROM engine_agent_routes WHERE engine_agent_ref = :r"), {"r": ref}
            )
        return batch

    engine_reconciliation.claim_drift_batch = deleting_claim  # type: ignore[assignment]
    try:
        with _engine(engine):
            assert await sweep_engine_drift({}) == "checked=0 drifted=0"
    finally:
        engine_reconciliation.claim_drift_batch = original  # type: ignore[assignment]
    # The read still happened — the vendor was asked — and nothing was written.
    assert engine.names().count("get_agent") == 1


async def test_a_tick_that_runs_out_of_budget_stops_rather_than_overrunning() -> None:
    """The bound that stops a slow vendor turning one tick into an overlapping pair.

    The batch cap bounds the COUNT and this bounds the TIME, and they are different
    failures: 25 agents behind a vendor answering in ten seconds each is a four-minute
    tick. What the sweep must not do is treat running out of budget as a failure — the
    rows it did not reach keep their old `drift_checked_at` and are first next time.
    """
    engine = RecordingEngine()
    refs = [(await _published_agent(engine))[2] for _ in range(3)]
    await _only(*refs)
    engine.calls.clear()

    previous = engine_reconciliation.SWEEP_BUDGET_S
    # Zero, so the budget is already spent at the top of the very first iteration.
    engine_reconciliation.SWEEP_BUDGET_S = 0.0
    try:
        with _engine(engine):
            assert await sweep_engine_drift({}) == "checked=0 drifted=0"
    finally:
        engine_reconciliation.SWEEP_BUDGET_S = previous

    assert engine.names() == [], "the budget was exhausted and the sweep dialled anyway"
    for ref in refs:
        assert (await _route(ref))[0] is None, (
            "an agent the tick never reached was recorded as checked, so it drops to the "
            "back of the staleness queue without anyone having looked at it"
        )
    # And the next tick, with a real budget, does the work that was deferred.
    with _engine(engine):
        assert await sweep_engine_drift({}) == "checked=3 drifted=0"


async def test_a_sweep_that_cannot_run_at_all_asks_for_the_retry_ladder() -> None:
    """arq 0.28 retries a job for `arq.Retry` and for NOTHING else, so a sweep that fails
    on its batch read must raise `Retry` explicitly or the platform goes unwatched until
    the next half hour with nothing marked wrong. The defer climbs with the attempt.

    Distinct from a VENDOR failure, which `_reconcile_one` records as `unreachable` for
    that one agent and does not escalate — re-running the whole sweep because one agent's
    engine was slow would spend the other twenty-four's budget twice.
    """
    original = engine_reconciliation.claim_drift_batch

    async def broken_claim(session: Any, **kw: Any) -> Any:
        raise RuntimeError("the database went away")

    engine_reconciliation.claim_drift_batch = broken_claim  # type: ignore[assignment]
    try:
        with _engine(RecordingEngine()):
            with pytest.raises(Retry) as first:
                await sweep_engine_drift({"job_try": 1})
            with pytest.raises(Retry) as third:
                await sweep_engine_drift({"job_try": 3})
    finally:
        engine_reconciliation.claim_drift_batch = original  # type: ignore[assignment]

    assert first.value.defer_score is not None and third.value.defer_score is not None
    assert third.value.defer_score > first.value.defer_score, (
        "the retry ladder is flat, so three sweeps hit a restarting database in ninety "
        "seconds instead of backing off"
    )


async def test_a_platform_with_nothing_live_costs_no_vendor_round_trip() -> None:
    """The empty batch is a real branch and not a formality: on a fresh deployment, and on
    any tick where every live agent was checked seconds ago, this is the whole tick. It
    must return cleanly rather than alerting, and it must not dial."""
    engine = RecordingEngine()
    await _only()  # nothing at all is in scope
    with _engine(engine):
        assert await sweep_engine_drift({}) == "checked=0 drifted=0"
    assert engine.names() == []
