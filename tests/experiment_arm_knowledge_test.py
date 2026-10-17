"""An experiment arm carries the client's knowledge like every other agent of the client
(D-689; founder 17 Oct 2026, D-806).

An arm of a running script test is its own vendor agent (D-60), answering real callers with
its own script. Before D-806 it held no knowledge of ours: `kb/service.publish_source` fanned
out to `agents.engine_agent_ref` only, and the arm's script was its frozen prompt version, so
neither a published document nor a pinned fact nor a new [T0 FACTS] block reached it.

Driven through the real paths (`kb.service.publish_source` / `withdraw_source`,
`teach.pinned.recompile_agent`, `agents.experiments.conclude`) on the shared fake engine.
"""

from __future__ import annotations

import uuid

from apps.api.agents import experiments
from apps.api.agents.prompts import insert_prompt_version
from apps.api.agents.t0_block import T0_HEADER, with_knowledge_of
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.kb import service as kb_service
from apps.api.teach import pinned
from calevate_shared.call_script import QUICK_FACTS_HEADER
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.variant_drift_coverage_test import _running_arm

FEES = "A consultation costs 500 rupees and is payable at reception."
HOURS = "We are open from nine in the morning to eight at night."
ARM_SCRIPT = "[IDENTITY] The shop's receptionist.\n[TASK FLOW]\nGreet, then help.\n"


async def _arm_test() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str, FakeEngine]:
    """A live agent with an applied script and one RUNNING arm, published."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    async with tenant_session(tenant_id) as session:
        await insert_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY] The shop's receptionist.\n",
            notes=None,
            created_by=None,
            apply_live=True,
        )
    await _arm_version(tenant_id, agent_id)
    variant_id, arm_ref = await _running_arm(engine, tenant_id, agent_id, body=ARM_SCRIPT)
    return tenant_id, agent_id, variant_id, arm_ref, engine


async def _arm_version(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """The arm's script as the agent's newest prompt version, which `_running_arm` points the
    arm at, without moving the agent's own pointers."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, tenant_id, agent_id, version, body, "
                "created_at, updated_at) SELECT :p, :t, :a, max(version) + 1, :body, now(), "
                "now() FROM prompt_versions WHERE agent_id = :a"
            ),
            {"p": uuid.uuid4(), "t": tenant_id, "a": agent_id, "body": ARM_SCRIPT},
        )


async def _publish(tenant_id: uuid.UUID, name: str, body: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, name=name, body=body, auto_approve=True
        )
    source_id = uuid.UUID(str(submitted["id"]))
    async with tenant_session(tenant_id) as session:
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    return source_id


async def _arm_claims(tenant_id: uuid.UUID, variant_id: uuid.UUID) -> dict[uuid.UUID, str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT source_id, engine_kb_ref FROM engine_kb_routes WHERE variant_id = :v"),
                {"v": variant_id},
            )
        ).all()
    return {uuid.UUID(str(row[0])): str(row[1]) for row in rows}


async def _agent_ref(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar()
        )


async def test_a_document_published_during_the_test_reaches_the_arm() -> None:
    tenant_id, agent_id, variant_id, arm_ref, engine = await _arm_test()

    source_id = await _publish(tenant_id, "Fees", FEES)

    claims = await _arm_claims(tenant_id, variant_id)
    assert set(claims) == {source_id}
    assert claims[source_id] in await engine.list_kb(arm_ref)
    assert await engine.list_kb(await _agent_ref(tenant_id, agent_id)), "and the agent's own"
    # The arm's instructions carry the recompiled [T0 FACTS] block with the knowledge line,
    # and its own script around it.
    prompt = engine._agents[arm_ref].system_prompt
    assert T0_HEADER in prompt and FEES in prompt
    assert "Greet, then help." in prompt


async def test_an_arm_started_after_a_publish_gets_the_live_knowledge() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    source_id = await _publish(tenant_id, "Fees", FEES)

    await _arm_version(tenant_id, agent_id)
    variant_id, arm_ref = await _running_arm(engine, tenant_id, agent_id, body=ARM_SCRIPT)

    claims = await _arm_claims(tenant_id, variant_id)
    assert set(claims) == {source_id}
    assert claims[source_id] in await engine.list_kb(arm_ref)
    assert FEES in engine._agents[arm_ref].system_prompt


async def test_a_withdrawn_document_leaves_the_arm() -> None:
    tenant_id, _agent_id, variant_id, arm_ref, engine = await _arm_test()
    source_id = await _publish(tenant_id, "Fees", FEES)
    handle = (await _arm_claims(tenant_id, variant_id))[source_id]

    async with tenant_session(tenant_id) as session:
        assert await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)

    assert await _arm_claims(tenant_id, variant_id) == {}
    assert handle not in await engine.list_kb(arm_ref)
    assert FEES not in engine._agents[arm_ref].system_prompt


async def test_a_pinned_fact_reaches_the_arm() -> None:
    tenant_id, agent_id, _variant_id, arm_ref, engine = await _arm_test()

    async with tenant_session(tenant_id) as session:
        await pinned.add_pinned(
            session,
            tenant_id=tenant_id,
            question="Do you deliver?",
            answer="Yes, within five kilometres.",
            origin="quick_fact",
            created_by=None,
        )
    async with tenant_session(tenant_id) as session:
        await pinned.recompile_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    prompt = engine._agents[arm_ref].system_prompt
    assert QUICK_FACTS_HEADER in prompt and "Yes, within five kilometres." in prompt
    assert "Greet, then help." in prompt


async def test_a_concluded_arm_gives_its_copies_back_and_is_not_targeted() -> None:
    tenant_id, agent_id, variant_id, arm_ref, engine = await _arm_test()
    first = await _publish(tenant_id, "Fees", FEES)
    handle = (await _arm_claims(tenant_id, variant_id))[first]
    async with tenant_session(tenant_id) as session:
        experiment_id = (
            await session.execute(
                text("SELECT experiment_id FROM prompt_experiment_variants WHERE id = :v"),
                {"v": variant_id},
            )
        ).scalar_one()

    await experiments.conclude(
        tenant_id=tenant_id,
        agent_id=agent_id,
        experiment_id=uuid.UUID(str(experiment_id)),
        promote_label=None,
        created_by=None,
    )

    assert await _arm_claims(tenant_id, variant_id) == {}
    assert handle not in await engine.list_kb(arm_ref)
    second = await _publish(tenant_id, "Hours", HOURS)
    assert await _arm_claims(tenant_id, variant_id) == {}
    async with tenant_session(tenant_id) as session:
        targets = await kb_service.vendor_targets(session, tenant_id=tenant_id)
    assert all(target.variant_id is None for target in targets)
    assert second


def test_an_arm_takes_the_agents_knowledge_sections_and_keeps_its_own_script() -> None:
    agent = (
        "[IDENTITY] Agent.\n[QUICK FACTS] These win over anything in your knowledge.\n"
        "Q: Open Sunday?\nA: No.\n\n[T0 FACTS]\nHours: 9 to 8\n[TASK FLOW]\nAgent flow.\n"
    )
    stale = (
        "[IDENTITY] Arm.\n[QUICK FACTS] These win over anything in your knowledge.\n"
        "- Old fact.\n\n[T0 FACTS]\nHours: 10 to 6\n[TASK FLOW]\nArm flow.\n"
    )
    out = with_knowledge_of(agent, stale, identity="Shop.")
    assert "Q: Open Sunday?\nA: No." in out and "Old fact" not in out
    assert "Hours: 9 to 8" in out and "10 to 6" not in out
    assert "Arm flow." in out and "Agent flow." not in out and "[IDENTITY] Arm." in out
    # Already matching: returned as it was.
    assert with_knowledge_of(agent, out, identity="Shop.") == out
    # The agent has neither section: the arm's stale ones go.
    bare = with_knowledge_of("[IDENTITY] Agent.\n", stale, identity="Shop.")
    assert QUICK_FACTS_HEADER not in bare and T0_HEADER not in bare and "Arm flow." in bare
    # An arm without the sections gets them, quick facts before the facts block.
    added = with_knowledge_of(agent, "[IDENTITY] Arm.\n[TASK FLOW]\nArm flow.\n", identity="S.")
    assert added.index(QUICK_FACTS_HEADER) < added.index(T0_HEADER) < added.index("Arm flow.")
