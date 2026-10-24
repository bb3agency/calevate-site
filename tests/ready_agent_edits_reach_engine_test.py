"""A ready agent's edits reach the engine (D-838 "Ready, not taking calls").

A ready agent is `paused` WITH an engine agent: published, so its Try it chat and a free
trial's test calls run what the engine holds. Every write path used to republish only a
`live` agent, so an edit to a ready one (its script put live, its name, its notices, its
call length, a platform-wide change) was saved to our rows and never sent: the drift sweep
then read the engine back as `not_applied` and the owner's test call spoke the old words.

Each test edits a ready agent, asserts the engine reads back `applied` and the agent stayed
ready (no number bound, still `paused`), and one proves that a genuine edit on the engine
side is still reported.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.agents import lifecycle, publishing, script_builder
from apps.api.agents.live_apply import converge_agent
from apps.api.db.session import tenant_session
from calevate_shared.call_script import CallScript
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine, _number, _tenant, _write_script

pytestmark = pytest.mark.asyncio


async def _ready_agent() -> tuple[uuid.UUID, uuid.UUID]:
    """A ready agent saying its AI notice, with a bound number, so the tests can see that
    an edit changes what the engine must hold and that the agent stays unanswered."""
    tenant_id, agent_id, _ = await _tenant()
    await _write_script(tenant_id, agent_id)
    await _number(tenant_id, agent_id, ref=f"num_{uuid.uuid4().hex[:8]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET ai_disclosure_enabled = true WHERE id = :a"), {"a": agent_id}
        )
        await lifecycle.prepare_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return tenant_id, agent_id


async def _status(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[str, str]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).one()
    return str(row[0]), str(row[1])


async def _assert_ready_and_in_sync(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    drift = await publishing.engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)
    assert drift.state == "applied", drift
    status, _ = await _status(tenant_id, agent_id)
    assert status == "paused", "an edit put a ready agent on the phone"


async def test_put_it_live_on_a_ready_agent_reaches_the_engine() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _ready_agent()
    async with tenant_session(tenant_id) as session:
        saved = await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(
                schema_version=2,
                identity="You call people back about their plot enquiry.",
                opening_line="Hello, this is about the plot you asked about.",
            ),
            notes="New opening",
            created_by=None,
        )
    assert not saved.staged
    await publishing.apply_to_live(
        tenant_id=tenant_id, agent_id=agent_id, expected_version=saved.version
    )
    await _assert_ready_and_in_sync(tenant_id, agent_id)


async def test_renaming_a_ready_agent_reaches_the_engine() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _ready_agent()
    async with tenant_session(tenant_id) as session:
        await lifecycle.update_agent(session, tenant_id=tenant_id, agent_id=agent_id, name="Anjali")
    await _assert_ready_and_in_sync(tenant_id, agent_id)


async def test_switching_a_ready_agents_notices_reaches_the_engine() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _ready_agent()
    await publishing.set_disclosure_posture(
        tenant_id=tenant_id,
        agent_id=agent_id,
        ai_disclosure_enabled=False,
        recording_notice_enabled=True,
    )
    await _assert_ready_and_in_sync(tenant_id, agent_id)


async def test_a_ready_agents_call_length_reaches_the_engine() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _ready_agent()
    await publishing.set_call_cap(tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=420)
    _, ref = await _status(tenant_id, agent_id)
    assert engine._agents[ref].max_call_duration_s == 420
    await _assert_ready_and_in_sync(tenant_id, agent_id)


async def test_a_platform_wide_apply_converges_a_ready_agent_and_keeps_it_ready() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _ready_agent()
    # Our rows move as a deploy that changes the composition moves them: the engine still
    # holds what the earlier publish sent.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET name = 'Sravani', recording_notice_enabled = true WHERE id = :a"
            ),
            {"a": agent_id},
        )
    before = await publishing.engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)
    assert before.state == "not_applied"

    outcome, name = await converge_agent(tenant_id=tenant_id, agent_id=agent_id)
    assert (outcome, name) == ("applied", "Sravani")
    await _assert_ready_and_in_sync(tenant_id, agent_id)
    _, ref = await _status(tenant_id, agent_id)
    assert ref in engine._agents


async def test_a_draft_agent_is_still_not_published_by_an_edit() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _tenant()
    await _write_script(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await lifecycle.update_agent(session, tenant_id=tenant_id, agent_id=agent_id, name="New")
    status, ref = await _status(tenant_id, agent_id)
    assert status == "draft" and ref == "None"
    assert not engine._agents
    assert await converge_agent(tenant_id=tenant_id, agent_id=agent_id) == ("not_live", None)


async def test_a_prompt_edited_on_the_engine_is_still_reported() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _ready_agent()
    _, ref = await _status(tenant_id, agent_id)
    engine._agents[ref] = engine._agents[ref].model_copy(
        update={"system_prompt": "Somebody's console edit."}
    )
    drift = await publishing.engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)
    assert (drift.state, drift.prompt_applied) == ("not_applied", False)
