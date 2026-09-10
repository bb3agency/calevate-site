"""The truthful-answer directive stops being a detection and becomes a refusal (D-562).

THE GAP THIS FILE PINS. `tests/engine_drift_reconciliation_test.py` proves the half-hourly
sweep FINDS a vendor-dashboard edit and writes it down. Nothing proved — because nothing
did — that finding it changed anything: an agent the sweep had positively proven was
running a prompt with no truthful-answer directive in it went on answering and went on
placing calls until a human read an email. Hard rule 5 requires that directive to be
"verified against the engine on every publish and every drift sweep"; the publish half
refuses, the sweep half only recorded.

THE THREE PROPERTIES, and the middle one is as load-bearing as the first:

    1. A PROVEN-MISSING directive REFUSES the dial, by name, at `check_dispatch`.
    2. ORDINARY DRIFT DOES NOT. An agent whose script merely differs from what we
       published keeps calling — halting a paying client on a cosmetic difference is a
       worse failure than the one being fixed, and a gate that overreaches is a gate an
       operator disarms.
    3. THE REFUSAL EXPIRES WITH ITS EVIDENCE. The sweep is the only thing that can ever
       restate or clear a verdict, so a refusal that outlived the sweep would be one the
       sweep's own death makes permanent — an operator could republish the agent, fix the
       engine, and still not get their client's calling back.

Every assertion here is against what the SWEEP recorded off a vendor object it read, never
against a row a test wrote by hand, except where the test is deliberately ageing a verdict.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents.reconciliation import (
    DRIFT_STATES,
    DRIFT_STATES_OUT_OF_SYNC,
    TRUTHFUL_ANSWER_MISSING,
    TRUTHFUL_ANSWER_VERDICT_TTL_S,
    recorded_drift_state,
)
from apps.api.agents.service import publish_agent
from apps.api.compliance.service import (
    TRUTHFUL_ANSWER_DRIFT_REASON,
    TRUTHFUL_ANSWER_DRIFT_RULE,
    check_dispatch,
    truthful_answer_drift_blocker,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers.engine_reconciliation import (
    SWEEP_BATCH_SIZE,
    SWEEP_INTERVAL_S,
    SWEEP_MINUTES,
    sweep_engine_drift,
)
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_MARKER,
    AgentSnapshot,
    EngineAgentRef,
)
from sqlalchemy import text
from tests.conftest import accept_agreements

SCRIPT = "Sunrise Clinic receptionist. Greet in Telugu, then take the appointment."
#: The SCRIPT edited on the vendor's own console — an ordinary drift, and the case that
#: must NOT stop a client's calling. `FakeEngine.get_agent` recomposes the prompt from the
#: config it holds, so the floor is still underneath it exactly as a real engine's would
#: be when only the client's words were changed.
CONSOLE_EDIT = "Whatever the vendor's console was used to write at 3am."


class TruncatingEngine(FakeEngine):
    """An engine holding a prompt with the FLOOR CUT OFF THE END.

    `compose_engine_prompt` appends `TRUTHFUL_ANSWER_DIRECTIVE` last, which is precisely
    where a vendor's prompt-length ceiling truncates — `verification.judge` scores the
    directive separately from the script for that exact reason. `FakeEngine` recomposes
    the prompt from the config it stores, so no amount of editing what it HOLDS can
    produce this; only the read-back can. That makes this double the one instrument in the
    suite able to reproduce the case (`agents/publishing.py` names it alongside a
    console edit), and it edits nothing but what the vendor ANSWERS.
    """

    #: OFF until the publish has landed, and that ordering is the case being modelled
    #: rather than a convenience: the agent went live carrying the floor — the publish
    #: read-back REFUSES otherwise, which this suite proves by construction — and the
    #: engine stopped holding it afterwards, with nothing of ours running. That window is
    #: the whole of the finding.
    truncating: bool = False

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        if not self.truncating:
            return snapshot
        prompt = snapshot.system_prompt or ""
        return snapshot.model_copy(
            update={"system_prompt": prompt.split(TRUTHFUL_ANSWER_MARKER)[0]}
        )


@contextmanager
def _engine(instance: FakeEngine) -> Iterator[FakeEngine]:
    """Run the block against `instance` — `engine_drift_reconciliation_test._engine`'s
    shape, and reaching into the same instance cache `get_engine()` resolves through."""
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


async def _published_agent(engine: FakeEngine) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A tenant with one agent genuinely live on `engine`, and its vendor ref."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Truthful Clinic",
        slug=f"ta-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    await accept_agreements(uuid.UUID(str(created["id"])))
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
        # OUTBOUND, because the property under test is a DIAL refusal and
        # `agent_inbound_only` is asked one step earlier. The default template agent
        # answers only; that is a fact about the fixture, not about this rule.
        await session.execute(
            text("UPDATE agents SET direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    with _engine(engine):
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return tenant_id, agent_id, ref


async def _only(*refs: str) -> None:
    """Put exactly these vendor objects in the sweep's platform-wide scope. The suite
    shares one database and nothing truncates between files, so `active` is the lever —
    exactly the predicate `claim_drift_batch` filters on."""
    # ONLY THE TENANTS WHOSE ROWS ACTUALLY CHANGE, and the bound is why. An untenanted
    # session reads every route and writes none since `b8e2d47f0c19`, so this is now a
    # read followed by one session per owner — and looping over EVERY tenant with a route
    # was measured at minutes on this shared database (2,124 tenants carry a route, 29
    # carry a LIVE one). The rows that move are exactly: the active ones that are not
    # mine, and mine.
    async with untenanted_session() as session:
        owners = [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT DISTINCT tenant_id FROM engine_agent_routes "
                        "WHERE active AND NOT (engine_agent_ref = ANY(:mine))"
                    ),
                    {"mine": list(refs)},
                )
            ).all()
        ]
        mine = [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT DISTINCT tenant_id FROM engine_agent_routes "
                        "WHERE engine_agent_ref = ANY(:mine)"
                    ),
                    {"mine": list(refs)},
                )
            ).all()
        ]
    for owner in owners:
        async with tenant_session(owner) as session:
            await session.execute(
                text(
                    "UPDATE engine_agent_routes SET active = false "
                    "WHERE active AND NOT (engine_agent_ref = ANY(:mine))"
                ),
                {"mine": list(refs)},
            )
    for owner in mine:
        async with tenant_session(owner) as session:
            await session.execute(
                text(
                    "UPDATE engine_agent_routes SET active = true "
                    "WHERE engine_agent_ref = ANY(:mine)"
                ),
                {"mine": list(refs)},
            )


async def _state(ref: str) -> str | None:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT drift_state FROM engine_agent_routes "
                    "WHERE engine = 'fake' AND engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).scalar()


async def _age_verdict(ref: str, *, seconds: int) -> None:
    """Backdate the SWEEP'S OWN stamp. Nothing else is touched: the verdict stays exactly
    what the sweep wrote, which is what makes the staleness test about time and not about
    a hand-written row."""
    async with untenanted_session() as session:
        owner = (
            await session.execute(
                text(
                    "SELECT tenant_id FROM engine_agent_routes "
                    "WHERE engine = 'fake' AND engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).scalar_one()
    async with tenant_session(owner) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes "
                "SET drift_checked_at = now() - make_interval(secs => :s) "
                "WHERE engine = 'fake' AND engine_agent_ref = :r"
            ),
            {"r": ref, "s": seconds},
        )


async def _edit_on_the_vendors_console(engine: FakeEngine, ref: str, prompt: str) -> None:
    """Nothing of ours runs — which is the entire reason the sweep exists."""
    engine._agents[ref] = engine._agents[ref].model_copy(update={"system_prompt": prompt})


# --- 1. the vocabulary ---------------------------------------------------------------


def test_the_compliance_verdict_is_a_refinement_of_not_applied_and_not_a_new_axis() -> None:
    """`verification.judge` returns `not_applied` the moment any checked property is
    provably False, so a missing directive is ALWAYS a `not_applied` underneath. Recording
    it as its own value partitions that verdict; it must never widen or narrow what counts
    as out of sync, or every console aggregate and alert count silently changes meaning."""
    assert recorded_drift_state("not_applied", truthful_answer_applied=False) == (
        TRUTHFUL_ANSWER_MISSING
    )
    assert recorded_drift_state("not_applied", truthful_answer_applied=True) == "not_applied"
    # "We could not read it" is not "it is missing" — the `AgentSnapshot` doctrine, held
    # all the way to a gate that stops a client's calling.
    assert recorded_drift_state("not_applied", truthful_answer_applied=None) == "not_applied"
    assert recorded_drift_state("unreachable", truthful_answer_applied=None) == "unreachable"
    assert TRUTHFUL_ANSWER_MISSING in DRIFT_STATES
    assert {"not_applied", TRUTHFUL_ANSWER_MISSING} == DRIFT_STATES_OUT_OF_SYNC


def test_the_sweep_can_restate_a_verdict_before_the_gate_stops_honouring_it() -> None:
    """The gate refuses on a MEASUREMENT and the sweep is the only thing that can refresh
    one. If a verdict could expire faster than the sweep comes round, the gate would stop
    enforcing under entirely normal operation with nothing anywhere to say so. Asserted
    here as well as at import because an import-time assertion that nobody imports in CI
    is a guard that has never run."""
    ticks_per_ttl = (TRUTHFUL_ANSWER_VERDICT_TTL_S / SWEEP_INTERVAL_S) * len(SWEEP_MINUTES)
    assert ticks_per_ttl * SWEEP_BATCH_SIZE >= 1000


# --- 2. the sweep records WHICH divergence -------------------------------------------


async def test_a_console_edit_that_drops_the_directive_is_recorded_as_its_own_verdict() -> None:
    """The read is of THEIRS. Our tables agree with themselves and are wrong."""
    engine = TruncatingEngine()
    _, _, ref = await _published_agent(engine)
    await _only(ref)
    engine.truncating = True

    with _engine(engine):
        assert await sweep_engine_drift({}) == "checked=1 drifted=1"

    assert await _state(ref) == TRUTHFUL_ANSWER_MISSING
    # STILL A READ. Reconciliation reports; a repair is a decision with a blast radius.
    assert TRUTHFUL_ANSWER_MARKER not in (
        (await engine.get_agent(EngineAgentRef(ref))).system_prompt or ""
    )


async def test_a_script_that_drifted_with_the_floor_intact_is_ordinary_drift() -> None:
    """The distinction IS the fix. Both are `not_applied` to `judge`; only one of them
    ends with an agent that cannot tell a caller it is an AI."""
    engine = FakeEngine()
    _, _, ref = await _published_agent(engine)
    await _only(ref)
    await _edit_on_the_vendors_console(engine, ref, CONSOLE_EDIT)

    with _engine(engine):
        assert await sweep_engine_drift({}) == "checked=1 drifted=1"

    assert await _state(ref) == "not_applied"


# --- 3. the refusal ------------------------------------------------------------------


async def test_the_dial_gate_refuses_an_agent_the_sweep_proved_cannot_answer_honestly() -> None:
    """THE FINDING. Before this, the sweep proved it, recorded it, emailed a count, and
    the agent went on placing regulated outbound calls."""
    engine = TruncatingEngine()
    tenant_id, agent_id, ref = await _published_agent(engine)
    await _only(ref)
    engine.truncating = True
    with _engine(engine):
        await sweep_engine_drift({})

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000001"
        )
    assert decision.allowed is False
    assert decision.rule == TRUTHFUL_ANSWER_DRIFT_RULE
    # The operator (and the client) must be able to act on it: what is wrong, and the one
    # thing that fixes it. Never the prompt itself (hard rule 6).
    assert decision.reason is not None
    assert "Publishing the agent again" in decision.reason
    assert SCRIPT not in decision.reason


async def test_an_agent_whose_script_merely_drifted_keeps_calling() -> None:
    """SCOPE, and it is half the decision. This gate answers for one verdict only."""
    engine = FakeEngine()
    tenant_id, agent_id, ref = await _published_agent(engine)
    await _only(ref)
    await _edit_on_the_vendors_console(engine, ref, CONSOLE_EDIT)
    with _engine(engine):
        await sweep_engine_drift({})

    async with tenant_session(tenant_id) as session:
        assert (
            await truthful_answer_drift_blocker(session, tenant_id=tenant_id, agent_id=agent_id)
            is None
        )
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000001"
        )
    # It may still be refused for something this test did not arm (credit, KYC, the DLT
    # chain) — what it must never be refused for is a drift that is not this one.
    assert decision.rule != TRUTHFUL_ANSWER_DRIFT_RULE


async def test_an_agent_the_sweep_has_never_faulted_is_not_refused() -> None:
    """The default is not the refusal. An agent the sweep read back and liked, and an
    agent nobody has swept at all, are both dialable as far as THIS gate is concerned."""
    engine = FakeEngine()
    tenant_id, agent_id, ref = await _published_agent(engine)
    await _only(ref)
    async with tenant_session(tenant_id) as session:
        assert (
            await truthful_answer_drift_blocker(session, tenant_id=tenant_id, agent_id=agent_id)
            is None
        ), "never swept must not refuse"
    with _engine(engine):
        await sweep_engine_drift({})
    assert await _state(ref) == "applied"
    async with tenant_session(tenant_id) as session:
        assert (
            await truthful_answer_drift_blocker(session, tenant_id=tenant_id, agent_id=agent_id)
            is None
        )


# --- 4. the refusal expires with its evidence ----------------------------------------


async def test_a_verdict_older_than_its_ttl_stops_refusing() -> None:
    """THE STALE DIRECTION, chosen and pinned.

    `record_drift` is the ONLY writer of this column, so nothing but the sweep can restate
    or clear a verdict — a publish that fixes the agent does not touch it. A refusal that
    never expired would therefore be one the sweep's own death makes permanent: the
    operator republishes, the engine is correct, and the client's calling stays stopped
    until a cron nobody noticed was dead comes back. Meanwhile every agent that drifted
    AFTER the cron died dials freely, because no verdict was ever written for them.

    So the refusal lives exactly as long as the measurement, and the system degrades to
    what it did before this rule existed — with `WORKER_TERMINAL/engine_drift_sweep_
    abandoned` and `EngineDriftSummary.oldest_checked_at` already reporting the real fault.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref = await _published_agent(engine)
    await _only(ref)
    engine.truncating = True
    with _engine(engine):
        await sweep_engine_drift({})

    # One second inside the window still refuses — the boundary is the measurement's age
    # and nothing else.
    await _age_verdict(ref, seconds=TRUTHFUL_ANSWER_VERDICT_TTL_S - 60)
    async with tenant_session(tenant_id) as session:
        assert await truthful_answer_drift_blocker(
            session, tenant_id=tenant_id, agent_id=agent_id
        ) == (TRUTHFUL_ANSWER_DRIFT_RULE, TRUTHFUL_ANSWER_DRIFT_REASON)

    await _age_verdict(ref, seconds=TRUTHFUL_ANSWER_VERDICT_TTL_S + 60)
    async with tenant_session(tenant_id) as session:
        assert (
            await truthful_answer_drift_blocker(session, tenant_id=tenant_id, agent_id=agent_id)
            is None
        ), "a verdict nobody has restated for a day may not go on stopping a client's calls"
        # And the verdict itself is untouched: it expired out of the GATE, it was not
        # cleared. The console still reports the agent as out of sync, which is true.
        assert await _state(ref) == TRUTHFUL_ANSWER_MISSING
