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

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import experiments, prompts
from apps.api.agents import publishing as publishing_service
from apps.api.agents.service import dispatch_call
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers.pipeline import ingest_engine_event
from calevate_shared.engine import CallContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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
    RECORDED arm. `dialled` is reported separately so a connection problem is visible
    rather than read as a script difference."""
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
    assert sum(v.dialled for v in results.variants) == 20
    assert sum(v.attributed for v in results.variants) == 10
    assert by_label["B"].conversions == 0
    assert by_label["A"].conversions == by_label["A"].attributed
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
    tenant_id, agent_id, _, _ = await _running()
    await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="B")
    with pytest.raises(ProblemError) as caught:
        await experiments.conclude(tenant_id=tenant_id, agent_id=agent_id, promote_label="A")
    assert caught.value.code == "no_running_experiment"


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
    assert (by_label["B"].dialled, by_label["B"].attributed) == (1, 1)
    assert by_label["A"].dialled == 0


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
    assert {v.label: v.dialled for v in results.variants} == {"A": 1, "B": 0}


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
