"""A/B script testing end to end (ROADMAP M3) — the properties, not the CRUD.

What is pinned here, and why each one is worth a test:

1. **Hard rule 1.** Cross-tenant zero rows on all three new tables, on raw RLS-scoped
   sessions, so a service that filtered in Python would still fail.
2. **Assignment is deterministic AND recorded.** The same contact always lands in the
   same arm; and a recorded assignment does NOT move when the split is ramped
   afterwards. The second half is the one that matters — an attribution that recomputes
   the bucket at read time silently re-attributes history the moment anybody changes the
   traffic share, with no error and no log line.
3. **Hard rule 5 travels with the arm.** Every variant has a non-empty disclosure, the
   schema refuses one that does not, and the disclosure the ENGINE holds for each arm is
   that arm's — checked on the engine object, not on our row.
4. **The attribution arithmetic** counts completed calls of the arm actually recorded.
5. **Promotion goes through the existing publish path** — a new `prompt_versions` row
   (copy-forward), the applied pointer moved by `publishing.apply_to_live`, the engine
   holding the promoted script. Not a second way to change what an agent says.
6. **An experiment can be ENDED**, with or without a winner, and cannot be started twice.
   Ending answers the THREE questions `db/transition.py::transition_status` names, which
   this path used to answer with one 409 apiece: an agent with no test (or a neighbour's
   agent, which RLS makes the same thing) is a 404; a repeat of the ending the test
   already has is an idempotent success that promotes nothing twice and writes no second
   audit row; a DIFFERENT ending is a 409 that names the one it found. Two concurrent
   Conclude presses end it exactly once.
7. **The fast lane still reaches a running experiment**: a call-cap change republishes
   the arms, so the cost-runaway guard does not silently stop guarding mid-test.
8. **Inbound is attributed by FACT or not at all.** A call the engine says was answered
   by the agent's own line carries no arm — nobody split that caller's traffic, and
   crediting a script they may never have heard is the one error this feature cannot
   survive. A call the engine says was answered by an ARM's own line carries that arm,
   because that is not an inference. `attributed_directions` is read off those rows, so
   it cannot drift from what the pipeline does.

The statistical half — the refusal to declare a winner below the minimum — is in
`tests/experiment_stats_test.py`, over hand-written counts.

Run: uv run pytest -q tests/prompt_experiment_test.py
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import experiment_routes, experiments, prompts
from apps.api.agents import publishing as publishing_service
from apps.api.agents.service import dispatch_call
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers.pipeline import ingest_engine_event
from calevate_shared.engine import CallContext
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.rls]

CONTROL = "Namaskaram. Sunrise Clinic. How may I help you today, at length and politely."
CHALLENGER = "Namaskaram! Sunrise Clinic — shall I book you the next free slot right away?"
# DIFFERENT per arm, on purpose. An inherited disclosure would be identical on both arms
# and on the agent, and a test asserting "the engine holds this arm's disclosure" would
# then pass under an implementation that ignored the variant column entirely — the
# unique-by-construction false positive BUILD-LOG §52 warns about.
DISCLOSURE_A = "This is an AI assistant calling on behalf of Sunrise Clinic."
DISCLOSURE_B = "Sunrise Clinic here — you are speaking to an automated assistant."


async def _agent(direction: str = "outbound") -> tuple[uuid.UUID, uuid.UUID, FakeEngine]:
    """A live, published outbound agent with a control script as v1."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Sunrise Clinic",
        slug=f"ab-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = :d WHERE id = :a"),
            {"d": direction, "a": agent_id},
        )
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=CONTROL,
            notes="control",
            created_by=None,
        )
    ref = f"fakeagent_ab_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, "
                "now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    return tenant_id, agent_id, engine


async def _challenger(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> int:
    """v2, written the ordinary way — which STAGES it on a live agent (§2b)."""
    async with tenant_session(tenant_id) as session:
        return await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=CHALLENGER,
            notes="challenger",
            created_by=None,
        )


async def _running(
    split_bp: int = 5000, direction: str = "outbound"
) -> tuple[uuid.UUID, uuid.UUID, FakeEngine, uuid.UUID]:
    tenant_id, agent_id, engine = await _agent(direction)
    await _challenger(tenant_id, agent_id)
    started = await experiments.start(
        tenant_id=tenant_id,
        agent_id=agent_id,
        name="Direct booking greeting",
        control_version=1,
        challenger_version=2,
        split_bp=split_bp,
        conversion_metric="call_outcome_resolved",
        control_disclosure=DISCLOSURE_A,
        challenger_disclosure=DISCLOSURE_B,
    )
    return tenant_id, agent_id, engine, started.experiment_id


async def _dial(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> None:
    async with tenant_session(tenant_id) as session:
        await dispatch_call(
            session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None, phone_e164=phone
        )


async def _assignments(tenant_id: uuid.UUID) -> dict[str, str]:
    """{to_e164: variant label} straight off the recorded rows."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.to_e164, v.label FROM call_variant_assignments a "
                    "JOIN calls c ON c.id = a.call_id "
                    "JOIN prompt_experiment_variants v ON v.id = a.variant_id"
                )
            )
        ).all()
    return {str(r[0]): str(r[1]) for r in rows}


# --- 1. hard rule 1 -----------------------------------------------------------


async def test_tenant_b_sees_no_rows_of_tenant_a() -> None:
    """FORCEd RLS on all three tables, proved on the raw session."""
    tenant_a, agent_a, _, _ = await _running()
    await _dial(tenant_a, agent_a, "+919000000101")
    tenant_b, _, _ = await _agent()

    async with tenant_session(tenant_a) as session:
        mine = [
            (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            for table in (
                "prompt_experiments",
                "prompt_experiment_variants",
                "call_variant_assignments",
            )
        ]
    assert mine == [1, 2, 1], mine

    async with tenant_session(tenant_b) as session:
        theirs = [
            (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            for table in (
                "prompt_experiments",
                "prompt_experiment_variants",
                "call_variant_assignments",
            )
        ]
    assert theirs == [0, 0, 0], theirs


# --- 2. deterministic, and RECORDED -------------------------------------------


async def test_the_same_contact_always_lands_in_the_same_arm() -> None:
    """A prospect called twice must hear the same script both times; otherwise their
    conversion belongs to neither arm."""
    tenant_id, agent_id, _, _ = await _running()
    for _ in range(4):
        await _dial(tenant_id, agent_id, "+919000000202")

    async with tenant_session(tenant_id) as session:
        labels = (
            await session.execute(
                text(
                    "SELECT DISTINCT v.label FROM call_variant_assignments a "
                    "JOIN prompt_experiment_variants v ON v.id = a.variant_id"
                )
            )
        ).all()
    assert len(labels) == 1, f"one contact reached {len(labels)} arms"


async def test_a_recorded_assignment_does_not_move_when_the_split_changes() -> None:
    """THE point of storing the assignment.

    Dial a spread of contacts at 50/50, then ramp the split hard. Every historical call
    must still report the arm it actually ran. An implementation that recomputed the
    bucket at read time would re-attribute most of these rows and change every rate on
    the screen with nothing to show why.
    """
    tenant_id, agent_id, _, experiment_id = await _running(split_bp=5000)
    contacts = [f"+91900001{n:04d}" for n in range(40)]
    for phone in contacts:
        await _dial(tenant_id, agent_id, phone)

    before = await _assignments(tenant_id)
    assert len(before) == len(contacts)
    # Both arms actually used — an all-A fixture would make this test unfalsifiable.
    assert set(before.values()) == {"A", "B"}, before

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE prompt_experiment_variants SET weight_bp = CASE label "
                "WHEN 'A' THEN 9500 ELSE 500 END WHERE experiment_id = :e"
            ),
            {"e": experiment_id},
        )

    assert await _assignments(tenant_id) == before


# --- 3. hard rule 5 -----------------------------------------------------------


async def test_every_arm_reaches_the_engine_with_its_own_disclosure_and_script() -> None:
    """Checked on the ENGINE's copy, not on ours: our row saying the right thing while
    the vendor holds something else is the failure this asserts against."""
    tenant_id, _agent_id, engine, experiment_id = await _running()
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT v.label, v.engine_agent_ref, v.disclosure_line "
                    "FROM prompt_experiment_variants v WHERE v.experiment_id = :e"
                ),
                {"e": experiment_id},
            )
        ).all()
    refs = {str(r[0]): (str(r[1]), str(r[2])) for r in rows}
    assert len(refs) == 2
    assert refs["A"][0] != refs["B"][0], "both arms published to ONE engine agent"

    bodies = {"A": CONTROL, "B": CHALLENGER}
    expected = {"A": DISCLOSURE_A, "B": DISCLOSURE_B}
    for label, (ref, disclosure) in refs.items():
        config = engine._agents[ref]
        assert config.disclosure_line.strip(), f"variant {label} published without a disclosure"
        # THIS arm's disclosure, not the agent's — the two differ in this fixture so an
        # implementation that ignored the variant column would fail here.
        assert config.disclosure_line == disclosure == expected[label]
        assert config.system_prompt == bodies[label]


async def test_the_schema_refuses_an_arm_with_no_disclosure() -> None:
    """The floor under every writer: not a service check that a future caller can miss."""
    tenant_id, _agent_id, _, experiment_id = await _running()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "UPDATE prompt_experiment_variants SET disclosure_line = '   ' "
                    "WHERE experiment_id = :e AND label = 'B'"
                ),
                {"e": experiment_id},
            )


async def test_a_blank_disclosure_override_is_refused_with_a_usable_message() -> None:
    tenant_id, agent_id, _ = await _agent()
    await _challenger(tenant_id, agent_id)
    with pytest.raises(ProblemError) as caught:
        await experiments.start(
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Blank disclosure",
            control_version=1,
            challenger_version=2,
            split_bp=5000,
            conversion_metric="call_outcome_resolved",
            challenger_disclosure="   ",
        )
    assert caught.value.code == "variant_disclosure_required"


# --- 4. the attribution arithmetic --------------------------------------------


async def test_the_tally_counts_completed_calls_of_the_arm_recorded() -> None:
    """Denominator = completed calls; numerator = the metric; both grouped by the
    RECORDED arm. `outbound_dialled` is reported separately so a connection problem is
    visible rather than read as a script difference."""
    tenant_id, agent_id, _, _ = await _running()
    for n in range(20):
        await _dial(tenant_id, agent_id, f"+91900002{n:04d}")

    async with tenant_session(tenant_id) as session:
        # Half the calls complete; of those, the ones on arm A resolve.
        await session.execute(
            text(
                "UPDATE calls SET status = 'completed' WHERE id IN ("
                "  SELECT id FROM calls ORDER BY to_e164 LIMIT 10)"
            )
        )
        await session.execute(
            text(
                "UPDATE calls SET outcome_tag = 'resolved' WHERE status = 'completed' "
                "AND id IN (SELECT a.call_id FROM call_variant_assignments a "
                "  JOIN prompt_experiment_variants v ON v.id = a.variant_id WHERE v.label = 'A')"
            )
        )

    results = await experiments.results_for(tenant_id=tenant_id, agent_id=agent_id)
    assert results is not None
    by_label = {v.label: v for v in results.variants}
    assert sum(v.outbound_dialled for v in results.variants) == 20
    assert sum(v.completed for v in results.variants) == 10
    # Every call here was placed by us, so none of the denominator is unrandomised.
    assert [v.inbound_completed for v in results.variants] == [0, 0]
    assert by_label["B"].conversions == 0
    assert by_label["A"].conversions == by_label["A"].completed
    assert by_label["A"].rate == 1.0
    # Nowhere near 40 per arm, so no comparison is published.
    assert results.basis == "insufficient_data"
    assert results.verdict == "not_enough_data"
    assert results.difference_low is None and results.winner_label is None


# --- 5. ending it, through the path that already exists -----------------------


async def test_promoting_an_arm_goes_through_the_publish_path() -> None:
    tenant_id, agent_id, engine, _ = await _running()
    result = await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="B")
    assert result.promoted_label == "B"
    assert result.new_version == 3, "promotion is copy-forward, not a pointer rewind"
    assert result.applied and result.engine_synced

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT pv.body, pv.version, pv.notes, a.engine_agent_ref, a.disclosure_line "
                    "FROM agents a JOIN prompt_versions pv ON pv.id = a.live_prompt_id "
                    "WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).first()
    assert row is not None
    assert str(row[0]) == CHALLENGER, "the live script is not the promoted arm's"
    assert int(row[1]) == 3
    assert "promoted variant B" in str(row[2])
    # And the ENGINE holds it — a promotion our table alone believed in is the defect.
    assert engine._agents[str(row[3])].system_prompt == CHALLENGER
    assert engine._agents[str(row[3])].disclosure_line == str(row[4])

    # Nothing is left staged: the publishing screen must not show a pending change for a
    # promotion that already applied.
    state = await publishing_service.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.has_pending is False


async def test_an_experiment_can_be_ended_without_a_winner() -> None:
    """The commonest honest ending. It must be a first-class outcome, and it must stop
    assigning calls."""
    tenant_id, agent_id, _, _ = await _running()
    result = await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label=None)
    assert result.promoted_label is None and result.new_version is None

    await _dial(tenant_id, agent_id, "+919000000303")
    async with tenant_session(tenant_id) as session:
        assignments = (
            await session.execute(text("SELECT count(*) FROM call_variant_assignments"))
        ).scalar()
        status = (
            await session.execute(
                text("SELECT status FROM prompt_experiments WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar()
        active = (
            await session.execute(
                text(
                    "SELECT count(*) FROM engine_agent_routes r "
                    "JOIN prompt_experiment_variants v ON v.engine_agent_ref = r.engine_agent_ref "
                    "WHERE r.active AND v.tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert assignments == 0, "a concluded experiment kept assigning calls"
    assert status == "concluded"
    assert active == 0, "the retired arms are still live routes"


async def test_concluding_twice_is_a_conflict_not_a_second_promotion() -> None:
    """A DIFFERENT ending is the one genuine conflict, and the refusal has to NAME the
    ending it found — "conflict" with no state in it leaves an operator with nothing to
    reload towards (`db/transition.py`'s contract)."""
    tenant_id, agent_id, _, _ = await _running()
    await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="B")
    with pytest.raises(ProblemError) as caught:
        await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="A")
    assert caught.value.code == "no_running_experiment"
    assert caught.value.status == 409
    assert "variant B" in caught.value.detail, "the 409 does not say how the test ended"

    async with tenant_session(tenant_id) as session:
        live = (
            await session.execute(
                text(
                    "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.live_prompt_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar()
    assert str(live) == CHALLENGER, "the refused promotion changed the live script anyway"


# --- 5b. the three answers a conclude owes its caller -------------------------
#
# D-65 established the discriminator in `db/transition.py` and named this path as one it
# had not audited. It answered ONE 409 (`no_running_experiment`) to all three questions:
# an agent that never ran a test, a neighbour's agent that RLS hides, and a retry of a
# conclude that had already succeeded.


async def test_an_agent_with_no_script_test_is_a_404_not_a_409() -> None:
    """A 409 asserts a conflict with a resource that is there. Neither of these is:
    the first agent has never run a test, and the second id names nothing at all.
    Telling an operator "conflict" for a typo sends them looking for the test."""
    tenant_id, agent_id, _ = await _agent()

    with pytest.raises(ProblemError) as never_tested:
        await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label=None)
    assert never_tested.value.status == 404, never_tested.value.detail

    with pytest.raises(ProblemError) as no_such_agent:
        await experiments.conclude(tenant_id=tenant_id, agent_id=uuid.uuid4(), promote_label=None)
    assert no_such_agent.value.status == 404, no_such_agent.value.detail


async def test_another_tenants_experiment_is_a_404_and_is_left_running() -> None:
    """Hard rule 1. Under RLS the neighbour's rows are invisible, so the honest answer
    is the one a typo gets — a 409 would confirm to tenant B that tenant A has a script
    test on this agent id."""
    tenant_a, agent_a, _, _ = await _running()
    tenant_b, _, _ = await _agent()

    with pytest.raises(ProblemError) as caught:
        await experiments.conclude(tenant_id=tenant_b, agent_id=agent_a, promote_label="B")

    assert caught.value.status == 404, caught.value.detail
    async with tenant_session(tenant_a) as session:
        status = (
            await session.execute(
                text("SELECT status FROM prompt_experiments WHERE agent_id = :a"), {"a": agent_a}
            )
        ).scalar()
    assert str(status) == "running", "a neighbour ended tenant A's test"


async def test_repeating_a_conclude_promotes_nothing_a_second_time() -> None:
    """The retry of a lost response, and the second operator on the same screen.

    RFC 9110 §9.2.2: N identical requests have the effect of one. So it is a SUCCESS —
    the test has ended the way the caller asked — and `changed=False` says this call is
    not what ended it. What must not happen is a second copy-forward: two promotions of
    one arm would leave the agent on v4 of a script it already ran as v3, with an Apply
    banner for a change nobody made.
    """
    tenant_id, agent_id, _, _ = await _running()

    first = await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="B")
    second = await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="B")

    assert first.changed is True and first.new_version == 3
    assert second.changed is False
    # The ending the test HAS, not a claim about what this call did — the console prints
    # the arm, and blanking it would read as "stopped, kept the control".
    assert second.promoted_label == "B"
    # ...and nothing this call performed, because it performed nothing.
    assert (second.new_version, second.applied, second.engine_synced) == (None, False, False)

    async with tenant_session(tenant_id) as session:
        versions = (
            await session.execute(
                text("SELECT count(*) FROM prompt_versions WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar()
    assert versions == 3, "the repeat minted a second promotion version"


async def test_repeating_a_stop_with_no_winner_is_a_success_too() -> None:
    """`promote: null` is an ending in its own right, so a repeat of it is a repeat."""
    tenant_id, agent_id, _, _ = await _running()

    first = await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label=None)
    second = await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label=None)

    assert first.changed is True
    assert second.changed is False
    assert (second.promoted_label, second.new_version) == (None, None)


async def test_promoting_over_a_test_that_was_stopped_without_a_winner_is_a_409() -> None:
    """The mirror of the case above: "stopped, kept the control" is not a repeat of
    "promote B", and answering 200 would tell the operator B is live when it is not."""
    tenant_id, agent_id, _, _ = await _running()
    await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label=None)

    with pytest.raises(ProblemError) as caught:
        await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="B")

    assert caught.value.status == 409
    assert "no promotion" in caught.value.detail


async def test_two_concurrent_concludes_end_the_test_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two operators pressing Promote B at the same moment, on two connections.

    The CAS in `transition_status` is what makes exactly one of them the one that ended
    it. A read-then-write would let both read `running`, both write, both mint a
    copy-forward version and both write an audit row for one ending.

    The barrier is what makes this deterministic rather than lucky — the same argument
    `campaigns_test.py::test_two_concurrent_pauses...` makes. It is installed on
    `tenant_session` rather than inside the service, so it holds whatever the transition
    is implemented with: both callers are inside their transactions, past nothing and
    before every statement, when they are released.
    """
    tenant_id, agent_id, _, _ = await _running()
    both_inside = asyncio.Barrier(2)
    real_session = experiments.tenant_session

    @asynccontextmanager
    async def barriered(tid: uuid.UUID) -> AsyncIterator[AsyncSession]:
        async with real_session(tid) as session:
            # Bounded, so a change that stops opening a session here fails this test
            # instead of hanging the suite.
            await asyncio.wait_for(both_inside.wait(), timeout=15)
            yield session

    monkeypatch.setattr(experiments, "tenant_session", barriered)

    async def end() -> experiments.ConcludeResult:
        return await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="B")

    outcomes = await asyncio.gather(end(), end())

    assert sorted(o.changed for o in outcomes) == [False, True], (
        f"two writers both ended one test: {[o.changed for o in outcomes]}"
    )
    assert {o.promoted_label for o in outcomes} == {"B"}, "the loser lost the ending too"
    async with tenant_session(tenant_id) as session:
        versions = (
            await session.execute(
                text("SELECT count(*) FROM prompt_versions WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar()
        concluded = (
            await session.execute(
                text("SELECT count(*) FROM prompt_experiments WHERE status = 'concluded'")
            )
        ).scalar()
    assert versions == 3, "both callers minted a promotion version"
    assert concluded == 1


# --- 6. refusals --------------------------------------------------------------


async def test_two_experiments_cannot_run_on_one_agent() -> None:
    tenant_id, agent_id, _, _ = await _running()
    with pytest.raises(ProblemError) as caught:
        await experiments.start(
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="A second one",
            control_version=1,
            challenger_version=2,
            split_bp=5000,
            conversion_metric="call_outcome_resolved",
        )
    assert caught.value.code == "experiment_already_running"


async def test_an_inbound_only_agent_is_refused_rather_than_measured_forever() -> None:
    """Assignment happens where a call is PLACED. An inbound-only agent would report
    'not enough data' for ever, which is a broken screen wearing a valid state."""
    tenant_id, agent_id, _ = await _agent(direction="inbound")
    await _challenger(tenant_id, agent_id)
    with pytest.raises(ProblemError) as caught:
        await experiments.start(
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Receptionist greeting",
            control_version=1,
            challenger_version=2,
            split_bp=5000,
            conversion_metric="call_outcome_resolved",
        )
    assert caught.value.code == "experiment_needs_outbound"


async def test_a_two_way_agent_says_which_half_it_is_measuring() -> None:
    """Nothing dialled yet, so nothing is attributed — and the field says so rather than
    promising an outbound coverage no row has yet earned."""
    tenant_id, agent_id, _, _ = await _running(direction="both")
    results = await experiments.results_for(tenant_id=tenant_id, agent_id=agent_id)
    assert results is not None
    assert results.attributed_directions == ()
    assert results.unattributed_inbound == 0
    assert experiments.INBOUND_NOT_SPLIT_NOTE in results.coverage_note


# --- 8. inbound: the fact the engine reports, and nothing more ----------------


async def _agent_ref(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar_one()
        )


async def _arm_ref(tenant_id: uuid.UUID, experiment_id: uuid.UUID, label: str) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text(
                        "SELECT engine_agent_ref FROM prompt_experiment_variants "
                        "WHERE experiment_id = :e AND label = :l"
                    ),
                    {"e": experiment_id, "l": label},
                )
            ).scalar_one()
        )


async def _backdate(tenant_id: uuid.UUID, experiment_id: uuid.UUID) -> None:
    """Make the experiment an hour old.

    The fake engine stages a call that STARTED `duration_s` ago, so against an
    experiment created microseconds earlier every seeded call falls outside the window
    and any assertion about the window is vacuously true. An hour-old experiment is also
    the realistic case: calls arrive during a test, not before it.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE prompt_experiments SET started_at = now() - interval '1 hour' WHERE id = :e"
            ),
            {"e": experiment_id},
        )


async def _ingest_inbound(engine: FakeEngine, agent_ref: str, caller: str) -> None:
    """One completed inbound call, discovered the way production discovers one: staged
    on the engine, then read back by the ingest job. No shortcut through the call row —
    the point of these tests is what `pipeline.py` does with the engine's answer."""
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    engine.seed_inbound_call(
        call_id=execution_id, agent_ref=agent_ref, from_e164=caller, to_e164="+911140000000"
    )
    outcome = await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    assert outcome == "pipeline_enqueued", outcome


async def _arms_of_calls(tenant_id: uuid.UUID) -> list[tuple[str, str]]:
    """[(direction, label)] for every call that carries an arm."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.direction, v.label FROM call_variant_assignments a "
                    "JOIN calls c ON c.id = a.call_id "
                    "JOIN prompt_experiment_variants v ON v.id = a.variant_id "
                    "ORDER BY c.direction, v.label"
                )
            )
        ).all()
    return [(str(r[0]), str(r[1])) for r in rows]


async def test_an_inbound_call_to_the_agents_own_line_is_credited_to_no_arm() -> None:
    """THE refusal this feature is built on.

    The caller dialled the client's number, which answers with the AGENT — so the script
    they heard was whatever was live, and it is not one of the two arms in any sense a
    conversion rate may use. Drawing a bucket for them at call creation would put a real
    conversion under a script nobody spoke, with nothing in the data to show it. So the
    call is counted in NEITHER arm, and the size of that exclusion is reported.
    """
    tenant_id, agent_id, engine, experiment_id = await _running(direction="both")
    await _backdate(tenant_id, experiment_id)
    agent_ref = await _agent_ref(tenant_id, agent_id)
    await _dial(tenant_id, agent_id, "+919000000404")
    await _ingest_inbound(engine, agent_ref, "+919000000405")

    assert [d for d, _ in await _arms_of_calls(tenant_id)] == ["outbound"]

    # A call the agent took BEFORE the test began belongs to no window of it, and must
    # not inflate the exclusion any more than it would inflate an arm.
    await _ingest_inbound(engine, agent_ref, "+919000000409")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET started_at = now() - interval '2 days' "
                "WHERE from_e164 = '+919000000409'"
            )
        )

    results = await experiments.results_for(tenant_id=tenant_id, agent_id=agent_id)
    assert results is not None
    assert results.attributed_directions == ("outbound",)
    assert results.unattributed_inbound == 1
    assert "1 completed inbound call in this window is in neither arm." in results.coverage_note
    assert experiments.INBOUND_ON_AN_ARM_NOTE not in results.coverage_note


async def test_an_inbound_call_answered_by_an_arms_own_line_carries_that_arm() -> None:
    """The one inbound attribution that is a FACT rather than a draw.

    Each arm is published as its own engine agent with its own ref, so when the engine
    reports that ref it has told us which script ran — no inference, no bucket. A client
    whose telephony account answers a DID with an arm gets that call attributed, and the
    coverage note says inbound is in the numbers so nobody reads the comparison as a
    clean split.
    """
    tenant_id, agent_id, engine, experiment_id = await _running(direction="both")
    await _backdate(tenant_id, experiment_id)
    await _ingest_inbound(engine, await _arm_ref(tenant_id, experiment_id, "B"), "+919000000406")

    assert await _arms_of_calls(tenant_id) == [("inbound", "B")]

    results = await experiments.results_for(tenant_id=tenant_id, agent_id=agent_id)
    assert results is not None
    assert results.attributed_directions == ("inbound",)
    # It carried an arm, so it is NOT in the unattributed count — the two must never
    # double-count the same call.
    assert results.unattributed_inbound == 0
    assert experiments.INBOUND_ON_AN_ARM_NOTE in results.coverage_note
    by_label = {v.label: v for v in results.variants}
    # WHERE the call lands, stated three ways, because the defect this replaced was a
    # single count that answered all three with the same number. It is NOT a call we
    # placed; it IS in the denominator the rate is computed over; and the share of that
    # denominator which was never split into the arm is exactly this one call.
    assert by_label["B"].outbound_dialled == 0, "nobody dialled this call"
    assert by_label["B"].completed == 1
    assert by_label["B"].inbound_completed == 1
    assert (by_label["A"].outbound_dialled, by_label["A"].completed) == (0, 0)
    assert by_label["A"].inbound_completed == 0


async def test_a_webhook_that_beats_the_dispatch_write_does_not_lose_the_arm() -> None:
    """The outbound gap the same lookup closes.

    `dispatch_call` records the arm only when its own INSERT wins the `engine_call_id`
    conflict. The engine can fire a webhook for a call it has already started before our
    transaction commits, and then the pipeline creates the row first — leaving a call
    that demonstrably ran arm A carrying no arm at all, and under-counting one side of
    the comparison for a reason no operator could ever see.

    Staged exactly that way: the engine call is started against the arm's ref (which is
    what `dispatch_call` does first) and the pipeline sees it before any row of ours
    exists.
    """
    tenant_id, agent_id, engine, experiment_id = await _running()
    ref_a = await _arm_ref(tenant_id, experiment_id, "A")
    handle = await engine.start_outbound_call(ref_a, "+919000000407", CallContext())

    outcome = await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": handle, "engine_agent_ref": ref_a}
    )
    assert outcome == "pipeline_enqueued"
    assert await _arms_of_calls(tenant_id) == [("outbound", "A")]

    results = await experiments.results_for(tenant_id=tenant_id, agent_id=agent_id)
    assert results is not None
    assert results.attributed_directions == ("outbound",)
    assert {v.label: v.outbound_dialled for v in results.variants} == {"A": 1, "B": 0}
    # It was placed by us, so it counts as dialled and NOT as unrandomised traffic —
    # the direction split has to tell this call apart from the inbound one above.
    assert {v.label: v.inbound_completed for v in results.variants} == {"A": 0, "B": 0}


async def test_a_second_event_for_the_same_call_cannot_move_it_between_arms() -> None:
    """Every webhook re-runs the lookup, so the guarantee that a call keeps its first
    arm has to survive the repeat. It is the `ON CONFLICT (call_id) DO NOTHING` that
    keeps it, and this is the test that would notice an upsert."""
    tenant_id, _agent_id, engine, experiment_id = await _running(direction="both")
    ref_b = await _arm_ref(tenant_id, experiment_id, "B")
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    engine.seed_inbound_call(
        call_id=execution_id, agent_ref=ref_b, from_e164="+919000000408", to_e164="+911140000000"
    )
    for _ in range(3):
        await ingest_engine_event(
            {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": ref_b}
        )
    assert await _arms_of_calls(tenant_id) == [("inbound", "B")]


# --- 7. the fast lane keeps working during a test -----------------------------


async def test_a_call_cap_change_reaches_the_running_arms() -> None:
    """The cost-runaway guard must not silently stop guarding mid-experiment: the arms
    are what the engine is dialling, so a cap applied to the agent alone protects an
    object no call uses."""
    tenant_id, agent_id, engine, experiment_id = await _running()
    await publishing_service.set_call_cap(
        tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=120
    )
    async with tenant_session(tenant_id) as session:
        refs = [
            str(r[0])
            for r in (
                await session.execute(
                    text(
                        "SELECT engine_agent_ref FROM prompt_experiment_variants "
                        "WHERE experiment_id = :e"
                    ),
                    {"e": experiment_id},
                )
            ).all()
        ]
    assert refs and all(engine._agents[ref].max_call_duration_s == 120 for ref in refs)


# --- 9. the audit row belongs to the ending, not to the button ----------------


def _conclude_app() -> FastAPI:
    """The conclude endpoint on its own router, with the error ladder installed.

    Assembled here rather than reached through `main.py` for the reason
    `two_speed_publishing_routes_test` gives: the router is adopted by
    `agents/routes.py`, and asserting against the assembled router catches a break when
    it is written rather than when somebody remembers where it is mounted.
    """
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(experiment_routes.router)
    return application


async def _admin_token() -> str:
    """A real `admin_users` row plus the dev-token spelling of its realm — the idiom
    `commercial_terms_test._make_admin` uses. `operator` holds `agents:write`."""
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', 'operator', now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id},
        )
    return f"dev:admin:{clerk_id}"


async def _conclude_over_http(
    token: str, tenant_id: uuid.UUID, agent_id: uuid.UUID, promote: str | None
) -> Response:
    async with AsyncClient(
        transport=ASGITransport(app=_conclude_app()), base_url="http://api"
    ) as client:
        return await client.post(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/experiment/conclude",
            headers={"Authorization": f"Bearer {token}"},
            json={"promote": promote},
        )


async def _conclusion_audit_rows(tenant_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        return [
            str(row[0])
            for row in (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE tenant_id = :t "
                        "AND action = 'agent.experiment_concluded' ORDER BY created_at"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        ]


async def test_a_repeated_conclude_writes_no_second_audit_row() -> None:
    """The defect D-65 fixed for KB approve, on this endpoint.

    `audit_log` is append-only (hard rule 4), so a row written for an ending that did not
    happen is not correctable — it is a second "concluded, promoted B" with a different
    actor and a later timestamp, in the one log that has to stay readable a year from
    now. The repeat is a 200 BECAUSE the intent already holds, and it is silent in the
    ledger for exactly the same reason.
    """
    tenant_id, agent_id, _, _ = await _running()
    token = await _admin_token()

    first = await _conclude_over_http(token, tenant_id, agent_id, "B")
    second = await _conclude_over_http(token, tenant_id, agent_id, "B")

    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is False
    assert second.json()["promoted_label"] == "B"
    assert await _conclusion_audit_rows(tenant_id) == ["agent.experiment_concluded"], (
        "the audit log records the ending, not the button press"
    )


async def test_the_endpoint_gives_404_for_no_test_and_409_for_another_ending() -> None:
    """The two refusals as an operator meets them: status codes, not exceptions."""
    tenant_id, agent_id, _ = await _agent()
    token = await _admin_token()

    missing = await _conclude_over_http(token, tenant_id, agent_id, None)
    assert missing.status_code == 404, missing.text
    assert missing.headers["content-type"].startswith("application/problem+json")

    running_tenant, running_agent, _, _ = await _running()
    assert (await _conclude_over_http(token, running_tenant, running_agent, "B")).status_code == 200
    clash = await _conclude_over_http(token, running_tenant, running_agent, "A")
    assert clash.status_code == 409, clash.text
    assert "variant B" in clash.json()["detail"]
    assert await _conclusion_audit_rows(running_tenant) == ["agent.experiment_concluded"]
