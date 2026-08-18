"""Prompt versioning + rollback (ROADMAP M2 admin polish — backend).

The doctrine under test mirrors the KB (FLOWS §7): versions are immutable history,
rollback is republishing an earlier body as a NEW version (copy-forward, never
pointer-rewind), and a LIVE agent's change must reach the engine or it is a lie on
the admin screen.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from calevate_shared.engine import AgentSnapshot, EngineAgentRef
from sqlalchemy import text


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Prompt Clinic",
        slug=f"pr-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _make_live(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    """The kb_workflow shape: fake engine ref on the agent + the routing row."""
    ref = f"fakeagent_pr_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
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
    return ref


async def _pointed_version(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> int | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT pv.version FROM agents a "
                    "JOIN prompt_versions pv ON pv.id = a.system_prompt_id WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()
    return int(row[0]) if row else None


async def test_writing_versions_increments_and_the_agent_points_at_the_newest() -> None:
    """Version numbers are relative to whatever the wizard seeded (today: nothing —
    `create_organization` writes no prompt_versions row, so the first write is v1;
    asserting increments keeps this true even if the wizard later seeds one)."""
    tenant_id, agent_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        seeded = len(await prompts.list_prompt_versions(session, agent_id))
        first = await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="You are the clinic receptionist. Book appointments politely.",
            notes="initial draft",
            created_by=None,
        )
        second = await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="You are the clinic receptionist. Confirm the patient name first.",
            notes=None,
            created_by=None,
        )

    assert second == first + 1

    assert await _pointed_version(tenant_id, agent_id) == second

    async with tenant_session(tenant_id) as session:
        listed = await prompts.list_prompt_versions(session, agent_id)
    assert len(listed) == seeded + 2
    assert listed[0]["version"] == second, "history is newest first"
    assert [entry["version"] for entry in listed if entry["active"]] == [second]
    by_version = {entry["version"]: entry for entry in listed}
    assert by_version[first]["notes"] == "initial draft"


async def test_rollback_republishes_as_a_new_version_and_history_stays_immutable() -> None:
    tenant_id, agent_id = await _tenant()
    body_one = "Version one: greet in Telugu, then take the appointment details."
    body_two = "Version two: greet in Telugu, ask for the doctor's name first."

    async with tenant_session(tenant_id) as session:
        first = await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=body_one,
            notes=None,
            created_by=None,
        )
        second = await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=body_two,
            notes=None,
            created_by=None,
        )
        rolled = await prompts.rollback_prompt(
            session, tenant_id=tenant_id, agent_id=agent_id, version=first
        )

    assert rolled == second + 1, "rollback mints a THIRD version, no pointer-rewind"
    assert await _pointed_version(tenant_id, agent_id) == rolled

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT version, body FROM prompt_versions WHERE agent_id = :aid "
                    "ORDER BY version"
                ),
                {"aid": agent_id},
            )
        ).all()
        listed = await prompts.list_prompt_versions(session, agent_id)

    bodies = {int(r[0]): str(r[1]) for r in rows}
    assert bodies[rolled] == body_one, "the new version carries the target's body"
    # Immutable history: the original rows are untouched by the rollback.
    assert bodies[first] == body_one
    assert bodies[second] == body_two
    assert sorted(bodies) == [first, second, rolled], "linear history, no gaps, no edits"

    by_version = {entry["version"]: entry for entry in listed}
    assert by_version[rolled]["notes"] == f"rollback to v{first}"
    assert [entry["version"] for entry in listed if entry["active"]] == [rolled]


async def test_rollback_to_an_unknown_version_is_not_found() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="The only version this agent has ever had.",
            notes=None,
            created_by=None,
        )
        with pytest.raises(ProblemError) as exc:
            await prompts.rollback_prompt(
                session, tenant_id=tenant_id, agent_id=agent_id, version=999
            )
    assert exc.value.kind == "not_found"


async def test_a_live_agent_rollback_republishes_the_prompt_to_the_engine() -> None:
    """A prompt change that only lands in our DB is a lie on the admin screen: for a
    LIVE agent the rollback must reach the engine. The FakeEngine records the config
    it was last given per agent ref, which is the assertion surface."""
    reset_engine_cache()
    tenant_id, agent_id = await _tenant()
    body_one = "Live version one: the receptionist script the client approved."
    body_two = "Live version two: the experiment the client wants rolled back."

    async with tenant_session(tenant_id) as session:
        first = await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=body_one,
            notes=None,
            created_by=None,
        )
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=body_two,
            notes=None,
            created_by=None,
        )

    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    ref = await _make_live(tenant_id, agent_id)
    assert ref not in engine._agents, "draft-time writes never touched the engine"

    async with tenant_session(tenant_id) as session:
        new_version = await prompts.rollback_prompt(
            session, tenant_id=tenant_id, agent_id=agent_id, version=first
        )

    assert new_version > first
    assert get_engine() is engine, "same cached instance the service published through"
    config = engine._agents[ref]
    assert config.system_prompt == body_one, "the ENGINE got the rolled-back prompt"


async def test_a_rollback_the_engine_strips_the_truthful_answer_rule_from_is_refused() -> None:
    """Hard rule 5 on the RECOVERY path, which is the one nobody watches.

    A rollback is the click an operator makes while a bad script is taking calls, and it
    is the one publish this repository lets run without a second confirmation
    (`rollback_prompt`: "making the recovery path wait for a second click would cost more
    than it protects"). That makes it exactly the publish where a silently-dropped
    `TRUTHFUL_ANSWER_DIRECTIVE` would go unnoticed: the operator is watching the script
    change, and the directive sits at the END of the prompt, where a vendor's length
    ceiling truncates.

    It goes through `publish_agent`, so the read-back and the refusal apply — asserted
    here rather than assumed, because "the rollback reaches the engine" (above) is a
    claim about the script alone and would stay green with the rule gone.
    """
    reset_engine_cache()
    tenant_id, agent_id = await _tenant()

    class DirectiveTruncatingEngine(FakeEngine):
        """A vendor with a prompt-length ceiling: it keeps the head and drops the tail.

        The read-back returns the SCRIPT ALONE. `compose_engine_prompt` prepends the
        opening line and appends the platform rules, so answering with `cfg.system_prompt`
        is precisely "everything after the script fell off the end" — the truncation
        shape, not an invented one. Overriding the read-back rather than the write is
        deliberate: the vendor accepted the bytes, which is what makes this class of
        failure invisible to any caller that scores a publish by its status code.
        """

        async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
            snapshot = await super().get_agent(ref)
            return snapshot.model_copy(update={"system_prompt": self._agents[ref].system_prompt})

    async with tenant_session(tenant_id) as session:
        first = await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Version one: the receptionist script the client approved.",
            notes=None,
            created_by=None,
        )
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Version two: the experiment the client wants rolled back.",
            notes=None,
            created_by=None,
        )
    ref = await _make_live(tenant_id, agent_id)

    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = DirectiveTruncatingEngine()
    try:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as raised:
                await prompts.rollback_prompt(
                    session, tenant_id=tenant_id, agent_id=agent_id, version=first
                )
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)

    assert raised.value.code == "engine_publish_not_applied"
    # And the refusal is total: the transaction rolled back, so no row claims the
    # rolled-back version is live on a platform observed not to be running the rule.
    async with tenant_session(tenant_id) as session:
        state = (
            await session.execute(
                text("SELECT live_verify_state FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    assert state != "applied", "the row recorded a verdict the read-back never reached"
    assert ref is not None
