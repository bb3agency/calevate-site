"""The room the opening line has in what an agent says first, and the switches that use it.

ThinnestAI speaks at most 200 characters as an agent's greeting (`greeting` maxLength 200,
`thinnest-findings/mirror/snapshots/2026-10-19/openapi.json:24843`), and the greeting is the
notices switched on and then the opening line (D-708). Turning on a notice used to be saved
and then refused by the publish as `engine_greeting_too_long`. D-846: the budget is shown
before anything is refused, a notice switch with no room is refused before it is saved with
a problem naming the switch, and the opening line can be shortened in place.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from apps.api.agents import script_builder
from apps.api.agents.engine_limits import (
    NOTICE_NEEDS_ROOM,
    OPENING_TOO_LONG,
    greeting_budget,
    refuse_over_engine_limits,
)
from apps.api.agents.publishing import set_caller_memory, set_disclosure_posture
from apps.api.agents.roster import agent_by_id
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from calevate_shared.call_script import SCRIPT_SCHEMA_VERSION, CallScript, compile_call_script
from calevate_shared.engine import AgentConfig, DisclosurePosture, compose_opening_line
from sqlalchemy import text
from tests.conftest import _owner_of, create_org_with_receptionist

AI = "Idi Raghava Organics AI assistant."
RECORDING = "Ee call record avutundi."
MEMORY = "Meeru adigina daani gurinchi oka chinna note gurtu pettukuntanu."


def _thinnest() -> FakeEngine:
    return FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)


def _posture(**on: bool) -> DisclosurePosture:
    return DisclosurePosture(
        ai_disclosure_line=AI,
        ai_disclosure_enabled=on.get("ai", False),
        recording_notice_line=RECORDING,
        recording_notice_enabled=on.get("recording", False),
        caller_memory_notice_line=MEMORY,
        caller_memory_enabled=on.get("memory", False),
    )


def _cfg(posture: DisclosurePosture, opening: str, direction: str = "inbound") -> AgentConfig:
    return AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name="Receptionist",
        direction=direction,  # type: ignore[arg-type]
        system_prompt=compile_call_script(CallScript(opening_line=opening), collect=[]),
        opening_line=compose_opening_line(posture, call_is_recorded=True),
    )


# --- the budget is the publish check -----------------------------------------------------


@pytest.mark.parametrize("direction", ["inbound", "outbound"])
def test_the_room_is_exactly_what_the_publish_lets_through(direction: str) -> None:
    engine = _thinnest()
    posture = _posture(ai=True, recording=True)
    budget = greeting_budget(engine, posture=posture, opening="", direction=direction)
    assert budget is not None and budget.limit == 200
    refuse_over_engine_limits(engine, _cfg(posture, "a" * budget.opening_room, direction))
    with pytest.raises(ProblemError) as refused:
        refuse_over_engine_limits(engine, _cfg(posture, "a" * (budget.opening_room + 1), direction))
    assert refused.value.code == OPENING_TOO_LONG


def test_each_switch_room_is_what_the_publish_would_let_through_with_it_on() -> None:
    engine = _thinnest()
    budget = greeting_budget(engine, posture=_posture(), opening="Namaskaram", direction="inbound")
    assert budget is not None
    assert budget.opening_chars == len("Namaskaram")
    assert budget.opening_room == 200
    for switch, room in (
        ("ai", budget.opening_room_with_ai_disclosure),
        ("recording", budget.opening_room_with_recording_notice),
        ("memory", budget.opening_room_with_caller_memory),
    ):
        on = _posture(**{switch: True})
        refuse_over_engine_limits(engine, _cfg(on, "a" * room))
        with pytest.raises(ProblemError):
            refuse_over_engine_limits(engine, _cfg(on, "a" * (room + 1)))
    assert budget.opening_room_with_caller_memory == 200 - len(MEMORY) - 1


def test_an_engine_with_no_ceiling_has_no_budget() -> None:
    budget = greeting_budget(FakeEngine(), posture=_posture(), opening="x", direction="inbound")
    assert budget is None


# --- the switches, end to end -----------------------------------------------------------


@contextmanager
def _on_thinnest() -> Iterator[FakeEngine]:
    import apps.api.engine as engine_module

    reset_engine_cache()
    previous = dict(engine_module._instances)
    engine = _thinnest()
    engine_module._instances["fake"] = engine
    try:
        yield engine
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


async def _agent(opening: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Raghava Organics",
        slug=f"gb-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(
                schema_version=SCRIPT_SCHEMA_VERSION, opening_line=opening, goal="Take the order."
            ),
            notes=None,
            created_by=None,
        )
        await session.execute(
            text(
                "UPDATE agents SET ai_disclosure_enabled = false, "
                "recording_notice_enabled = false, caller_memory_enabled = false "
                "WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
    return tenant_id, agent_id, await _owner_of(tenant_id)


async def _row(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT a.caller_memory_enabled, a.ai_disclosure_enabled, "
                    "o.caller_memory_attested_at FROM agents a "
                    "JOIN organizations o ON o.id = a.tenant_id WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).one()


@pytest.mark.anyio
async def test_the_agent_read_carries_the_budget_for_its_stored_lines() -> None:
    with _on_thinnest():
        tenant_id, agent_id, _owner = await _agent("Namaskaram, cheppandi.")
        async with tenant_session(tenant_id) as session:
            agent = await agent_by_id(session, agent_id)
    assert agent is not None and agent.greeting_budget is not None
    budget = agent.greeting_budget
    assert budget.limit == 200
    assert budget.opening_chars == len("Namaskaram, cheppandi.")
    assert budget.opening_room == 200
    memory = agent.caller_memory_notice_line
    assert budget.opening_room_with_caller_memory == 200 - len(memory) - 1


@pytest.mark.anyio
async def test_remembering_callers_without_room_is_refused_before_anything_is_saved() -> None:
    with _on_thinnest():
        tenant_id, agent_id, owner = await _agent("a" * 180)
        with pytest.raises(ProblemError) as refused:
            await set_caller_memory(
                tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
            )
    problem = refused.value
    assert problem.code == NOTICE_NEEDS_ROOM
    assert problem.detail.startswith("Remembering callers adds a sentence")
    assert problem.remediation is not None and "at least" in problem.remediation
    row = await _row(tenant_id, agent_id)
    # Neither the switch nor the attestation that would have come with it.
    assert row[0] is False and row[2] is None


@pytest.mark.anyio
async def test_a_notice_switch_without_room_is_refused_and_naming_it() -> None:
    with _on_thinnest():
        tenant_id, agent_id, _owner = await _agent("a" * 190)
        with pytest.raises(ProblemError) as refused:
            await set_disclosure_posture(
                tenant_id=tenant_id,
                agent_id=agent_id,
                ai_disclosure_enabled=True,
                recording_notice_enabled=None,
            )
    assert refused.value.code == NOTICE_NEEDS_ROOM
    assert refused.value.detail.startswith("Saying that it is an AI assistant")
    assert (await _row(tenant_id, agent_id))[1] is False


@pytest.mark.anyio
async def test_shortening_the_opening_line_makes_room_and_the_switch_then_goes_on() -> None:
    with _on_thinnest():
        tenant_id, agent_id, owner = await _agent("a" * 180)
        async with tenant_session(tenant_id) as session:
            done = await script_builder.replace_opening_line(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                opening_line="  Namaskaram, cheppandi.  ",
                created_by=owner,
            )
        assert done.opening_line == "Namaskaram, cheppandi." and done.version is not None
        async with tenant_session(tenant_id) as session:
            agent = await agent_by_id(session, agent_id)
            loaded = await script_builder.load_agent_script(session, agent_id)
        assert agent is not None and agent.script_opening_line == "Namaskaram, cheppandi."
        # The rest of the script is kept.
        assert loaded.script.goal == "Take the order."
        on = await set_caller_memory(
            tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
        )
    assert on.enabled is True


@pytest.mark.anyio
async def test_a_shortened_line_that_still_does_not_fit_is_refused() -> None:
    with _on_thinnest():
        tenant_id, agent_id, owner = await _agent("Namaskaram")
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as refused:
                await script_builder.replace_opening_line(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    opening_line="a" * 201,
                    created_by=owner,
                )
    assert refused.value.code == OPENING_TOO_LONG


@pytest.mark.anyio
async def test_the_working_copy_follows_the_new_line_unless_the_owner_changed_it() -> None:
    with _on_thinnest():
        tenant_id, agent_id, owner = await _agent("a" * 180)
        async with tenant_session(tenant_id) as session:
            loaded = await script_builder.load_agent_script(session, agent_id)
            await script_builder.save_draft(
                session, agent_id, loaded.script.model_copy(update={"goal": "Take orders."})
            )
            await script_builder.replace_opening_line(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                opening_line="Namaskaram",
                created_by=owner,
            )
            draft = await script_builder.read_draft(session, agent_id)
    assert draft is not None
    assert draft.script.opening_line == "Namaskaram"
    assert draft.script.goal == "Take orders."
