"""An experiment ARM is a vendor agent object too — and neither drift sweep could see it.

`agents/service.publish_variant` writes a row in `engine_agent_routes` for every arm of a
running script test, because an inbound webhook naming an arm has to resolve to a tenant
(D-60). Both sweeps claim ROUTES from that table and both then asked a question about the
AGENT, which produced two distinct defects — measured here before they were fixed, and
pinned here so they cannot come back (D-380):

    THE KB SWEEP CRIED WOLF     `handles_if_no_publish_in_flight` returned the AGENT's
                                recorded handles for an ARM's route. The arm's own
                                listing never held the agent's documents (an arm holds
                                its own copies since D-806, before that none), so
                                `recorded - attached` was non-empty on EVERY tick:
                                verdict `missing`, counted as a PROVEN divergence,
                                `engine_kb_drift_detected` alerting every hour for as
                                long as the client's A/B test ran. The
                                module's own docstring says an alarm that fires on a
                                schedule is one somebody mutes before it ever catches a
                                real dashboard edit.

    THE AGENT SWEEP LOOKED AWAY `engine_drift_for` took only an agent id, so it read the
                                AGENT's object back once per route and recorded that
                                verdict against the ARM's ref. The arm's own script and
                                its own AI-disclosure sentence — the traffic actually
                                under test — were never read back after the publish that
                                created them, so a vendor-console edit or a prompt-length
                                truncation of `TRUTHFUL_ANSWER_DIRECTIVE` on an arm was
                                invisible to every instrument in this repository. Hard
                                rule 5 requires that directive to be verified against the
                                engine "on every publish and every drift sweep"; for arms
                                only the first half was true.

Every assertion below is against what the sweep RECORDED and what the engine was actually
ASKED, never against our own rows agreeing with themselves — the second defect is a case
of exactly that.

Run: uv run pytest -q tests/variant_drift_coverage_test.py
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents.service import _load_agent, _to_config, publish_variant
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.workers import engine_reconciliation, kb_reconciliation
from calevate_shared.engine import AgentSnapshot, EngineAgentRef
from kb_drift_reconciliation_test import _agent_with_knowledge, _batch_size, _engine
from sqlalchemy import text

FEES = "A consultation costs 500 rupees and is payable at reception."
ARM_SCRIPT = "You are the clinic receptionist. Quote the fee only when asked."


class ReadbackSpy(FakeEngine):
    """A `FakeEngine` that remembers which refs it was asked to READ BACK.

    The defect is about which vendor object was inspected, and no assertion on our own
    tables can see that — the sweep wrote a plausible verdict either way.
    """

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.read_back: list[str] = []
        #: Refs whose prompt the "vendor console" has been edited down to the bare
        #: script — no opening line, no `TRUTHFUL_ANSWER_DIRECTIVE` underneath it.
        self.stripped: set[str] = set()

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        self.read_back.append(str(ref))
        snapshot = await super().get_agent(ref)
        if str(ref) in self.stripped:
            return snapshot.model_copy(
                update={"system_prompt": self._agents[str(ref)].system_prompt}
            )
        return snapshot


async def _running_arm(
    engine: FakeEngine, tenant_id: uuid.UUID, agent_id: uuid.UUID, body: str = ARM_SCRIPT
) -> tuple[uuid.UUID, str]:
    """One RUNNING script test with a single published arm. Returns (variant_id, arm ref).

    The rows are written directly rather than through `experiments.start` because that
    function's own preconditions (two arms, weights, a metric, an unpublished agent) are
    `experiments_test`'s subject; what this file needs from it is the state it leaves
    behind — a `running` experiment, a variant carrying an engine ref, and the routing row
    `publish_variant` writes. `publish_variant` itself is the real one.
    """
    variant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        prompt_version_id = (
            await session.execute(
                text(
                    "SELECT id FROM prompt_versions WHERE agent_id = :a "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
        experiment_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO prompt_experiments (id, tenant_id, agent_id, name, status, "
                "conversion_metric, started_at) VALUES (:i, :t, :a, 'arm coverage', "
                "'running', 'call_outcome_resolved', now())"
            ),
            {"i": experiment_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO prompt_experiment_variants (id, tenant_id, experiment_id, "
                "label, prompt_version_id, disclosure_line, weight_bp) "
                "VALUES (:i, :t, :e, 'B', :pv, :disc, 5000)"
            ),
            {
                "i": variant_id,
                "t": tenant_id,
                "e": experiment_id,
                "pv": prompt_version_id,
                "disc": "This is an AI assistant from the clinic.",
            },
        )
        with _engine(engine):
            arm_ref = await publish_variant(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                variant_id=variant_id,
                label="B",
                body=body,
                disclosure_line="This is an AI assistant from the clinic.",
                existing_ref=None,
            )
    return variant_id, arm_ref


async def _vendor_holds_the_agent(
    engine: FakeEngine, tenant_id: uuid.UUID, agent_id: uuid.UUID, agent_ref: str
) -> None:
    """Give the fake vendor the agent object a publish would have created.

    `_agent_with_knowledge` deliberately writes `engine_agent_ref` by hand without
    `status = 'live'` (its own comment says why: `publish_source` would re-publish through
    `publish_agent`, which writes an engine name the CHECK constraint refuses). That
    leaves the vendor holding nothing for the agent, so a read-back is `unreachable` — the
    verdict this file needs to be `applied` for the comparison to mean anything.
    """
    async with tenant_session(tenant_id) as session:
        row = await _load_agent(session, tenant_id, agent_id)
    await engine.update_agent(agent_ref, _to_config(tenant_id, row, engine=engine))


async def _kb_verdict(engine: FakeEngine, ref: str) -> str | None:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT kb_drift_state FROM engine_agent_routes "
                    "WHERE engine = :e AND engine_agent_ref = :r"
                ),
                {"e": engine.name, "r": ref},
            )
        ).scalar()


async def _drift_verdict(engine: FakeEngine, ref: str) -> str | None:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT drift_state FROM engine_agent_routes "
                    "WHERE engine = :e AND engine_agent_ref = :r"
                ),
                {"e": engine.name, "r": ref},
            )
        ).scalar()


# --- 1. the KB sweep must not report an arm as a lost knowledge base ---------


@pytest.mark.asyncio
async def test_an_arms_route_is_not_reported_as_lost_knowledge() -> None:
    """The reproduction: publish knowledge, start a script test, sweep.

    Before the fix this recorded `missing` on the arm's route and returned `drifted=1`,
    which is what fires `engine_kb_drift_detected` — every hour, for a platform in which
    nothing whatever had drifted.
    """
    engine = ReadbackSpy(name=f"fake-arm-{uuid.uuid4().hex[:10]}")
    tenant_id, agent_id, agent_ref = await _agent_with_knowledge(engine, ("fees", FEES))
    _, arm_ref = await _running_arm(engine, tenant_id, agent_id)

    # Since D-806 the arm holds its own copy of the client's knowledge, recorded as its own
    # claims, which is what its route is compared against.
    assert await engine.list_kb(agent_ref), "fixture: the agent should hold its published KB"
    assert await engine.list_kb(arm_ref), "the arm holds the client's knowledge too"
    assert not set(await engine.list_kb(arm_ref)) & set(await engine.list_kb(agent_ref))

    with _engine(engine), _batch_size(50):
        summary = await kb_reconciliation._sweep()

    assert await _kb_verdict(engine, agent_ref) == "in_sync"
    assert await _kb_verdict(engine, arm_ref) == "in_sync", (
        "the arm's route was scored against the AGENT's recorded handles, so a routine "
        "A/B test reads as a client who lost their knowledge base"
    )
    assert summary.endswith("drifted=0"), summary


@pytest.mark.asyncio
async def test_knowledge_the_vendor_holds_on_an_arm_is_still_the_dangerous_direction() -> None:
    """The empty recorded set is not a mute button.

    An arm the vendor is serving a knowledge base on is text that went through no approval
    gate reaching callers under the client's own PE registration (FLOWS §7) — `unaccounted`,
    the direction that alerts. A fix that filtered arm routes out of the sweep would have
    lost this, which is why it was rejected.
    """
    engine = ReadbackSpy(name=f"fake-arm-{uuid.uuid4().hex[:10]}")
    tenant_id, agent_id, agent_ref = await _agent_with_knowledge(engine, ("fees", FEES))
    _, arm_ref = await _running_arm(engine, tenant_id, agent_id)

    # Somebody attached a knowledge base to the arm in the vendor's own console.
    from calevate_shared.engine import KBSourceRef

    await engine.attach_kb(
        arm_ref, KBSourceRef(kb_id=str(uuid.uuid4()), title="pasted", text="Whatever they typed.")
    )

    with _engine(engine), _batch_size(50):
        summary = await kb_reconciliation._sweep()

    assert await _kb_verdict(engine, agent_ref) == "in_sync"
    assert await _kb_verdict(engine, arm_ref) == "unaccounted"
    assert summary.endswith("drifted=1"), summary


# --- 2. the agent sweep must read the arm's OWN object back ------------------


@pytest.mark.asyncio
async def test_the_sweep_reads_back_the_arm_itself_not_its_parent_twice() -> None:
    """Call inventory, not row inspection: which refs did the sweep actually ask about?

    Before the fix this list was `[agent_ref, agent_ref]` — the arm's own object was never
    inspected, and the verdict recorded against its row described the parent.
    """
    engine = ReadbackSpy(name=f"fake-arm-{uuid.uuid4().hex[:10]}")
    tenant_id, agent_id, agent_ref = await _agent_with_knowledge(engine, ("fees", FEES))
    _, arm_ref = await _running_arm(engine, tenant_id, agent_id)
    await _vendor_holds_the_agent(engine, tenant_id, agent_id, agent_ref)

    engine.read_back.clear()
    with _engine(engine):
        await _run_agent_sweep()

    assert sorted(engine.read_back) == sorted([agent_ref, arm_ref]), (
        "the drift sweep must inspect each vendor object it records a verdict about; "
        f"it inspected {engine.read_back}"
    )


@pytest.mark.asyncio
async def test_an_arm_that_lost_the_truthful_answer_rule_is_caught_by_the_sweep() -> None:
    """Hard rule 5 on the half of the traffic an A/B test moves.

    `TRUTHFUL_ANSWER_DIRECTIVE` is appended to every prompt by `compose_engine_prompt` and
    sits at the END, which is where a vendor's prompt-length ceiling truncates. Somebody
    pasting an arm's script back into the vendor console without the block underneath it
    produces exactly the state below. Before the fix the sweep recorded `applied` for this
    arm — the parent agent's verdict — forever.
    """
    engine = ReadbackSpy(name=f"fake-arm-{uuid.uuid4().hex[:10]}")
    tenant_id, agent_id, agent_ref = await _agent_with_knowledge(engine, ("fees", FEES))
    _, arm_ref = await _running_arm(engine, tenant_id, agent_id)

    await _vendor_holds_the_agent(engine, tenant_id, agent_id, agent_ref)
    # The vendor-console edit: the arm now holds its script and nothing beneath it.
    engine.stripped.add(arm_ref)

    with _engine(engine):
        await _run_agent_sweep()

    assert await _drift_verdict(engine, agent_ref) == "applied"
    # `truthful_answer_missing` since D-562: a strict REFINEMENT of `not_applied` that
    # names WHICH property failed, because that is the one divergence the dial gate
    # refuses on (`compliance.service.truthful_answer_drift_blocker`). An arm is exactly
    # the case that makes it matter — it has its own script and its own live callers.
    assert await _drift_verdict(engine, arm_ref) == "truthful_answer_missing", (
        "an arm answering callers without the truthful-answer rule must be a PROVEN "
        "divergence, not a verdict inherited from the agent nobody was dialling"
    )


async def _run_agent_sweep() -> str:
    """One agent-drift tick with the batch cap widened to cover this file's fixtures."""
    previous = engine_reconciliation.SWEEP_BATCH_SIZE
    engine_reconciliation.SWEEP_BATCH_SIZE = 50
    try:
        return await engine_reconciliation._sweep()
    finally:
        engine_reconciliation.SWEEP_BATCH_SIZE = previous
