"""D-893 lane L5: Pip answers questions, changes facts and runs and saves practice tests.

Held to `docs/COPILOT-CONTRACT.md` §5: each planner's canonical arguments and refusals, the
confirm through the page button's own service function with its audit row, the Undo of the
one immediate tool, and the permission refusal inside the tool.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.teach_questions_test import _gap, _owner, _tenant

from apps.api.copilot import write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.console_reads import CONSOLE_READ_TOOLS
from apps.api.copilot.tools import ToolContext
from apps.api.copilot.undo import undo_client_action
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.teach import facts as fact_store


async def _member(tenant_id: UUID, role: str = "owner") -> UUID:
    token = await _owner(tenant_id)
    user_id = _user_of(token)
    if role != "owner":
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE memberships SET role = :role WHERE user_id = :uid"),
                {"role": role, "uid": user_id},
            )
    return user_id


async def _propose(tenant_id: UUID, user_id: UUID, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name,
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, user_id)),
    )


async def _fact(tenant_id: UUID, words: str) -> UUID:
    async with tenant_session(tenant_id) as session:
        added = await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=[words],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
    return added[0]


async def _facts(tenant_id: UUID) -> list[fact_store.Fact]:
    async with tenant_session(tenant_id) as session:
        return await fact_store.list_facts(session)


# --- knowledge_questions ------------------------------------------------------------------


async def test_the_read_lists_questions_with_their_keys() -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _gap(tenant_id, agent_id, "Do you deliver to Kukatpally?")
    tool = next(t for t in CONSOLE_READ_TOOLS if t.name == "knowledge_questions")
    async with tenant_session(tenant_id) as session:
        out = await tool.run(
            session, ToolContext(tenant_id=tenant_id, role="owner"), {"agent_id": None}
        )
    assert "[question_key delivery]" in out
    assert "asked on 1 call(s)" in out
    assert "[question_key timings]" in out


# --- knowledge_question_settle ------------------------------------------------------------


async def test_answering_a_question_through_pip_saves_the_fact_and_closes_the_gap() -> None:
    tenant_id, agent_id, _ = await _tenant()
    user_id = await _member(tenant_id)
    await _gap(tenant_id, agent_id, "Do you deliver to Kukatpally?")
    proposal = await _propose(
        tenant_id,
        user_id,
        "knowledge_question_settle",
        {"question_key": "delivery", "answer": "  We deliver across Hyderabad. "},
    )
    assert proposal.proposed == "We deliver across Hyderabad."
    await _confirm(tenant_id, user_id, proposal.token)
    assert [f.text for f in await _facts(tenant_id)] == ["We deliver across Hyderabad."]
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM knowledge_gaps WHERE topic_key = 'delivery'")
            )
        ).scalar()
    assert status == "taught"
    assert ("teach_question.answer", "teach_question", "delivery") in await _audit(tenant_id)


async def test_a_null_answer_dismisses_and_an_unknown_key_is_refused() -> None:
    tenant_id, _agent_id, _ = await _tenant()
    user_id = await _member(tenant_id)
    proposal = await _propose(
        tenant_id,
        user_id,
        "knowledge_question_settle",
        {"question_key": "location", "answer": None},
    )
    await _confirm(tenant_id, user_id, proposal.token)
    async with tenant_session(tenant_id) as session:
        settled = (
            await session.execute(
                text("SELECT settled FROM teach_questions WHERE question_key = 'location'")
            )
        ).scalar()
    assert settled == "dismissed"
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(
            tenant_id, user_id, "knowledge_question_settle", {"question_key": "nope", "answer": "x"}
        )
    assert "knowledge_questions" in refused.value.reason


async def test_a_staff_member_without_curation_is_refused_inside_the_tool() -> None:
    tenant_id, _agent_id, _ = await _tenant()
    user_id = await _member(tenant_id, role="staff")
    with pytest.raises((ProblemError, WriteRefusedError)):
        await write_tools.plan_write(
            "knowledge_question_settle",
            json.dumps({"question_key": "location", "answer": None}),
            actor=write_tools.actor_for(_principal(tenant_id, user_id, role="staff")),
        )


# --- knowledge_fact_change ----------------------------------------------------------------


async def test_a_fact_is_edited_pinned_moved_and_removed_through_the_buttons_functions() -> None:
    tenant_id, _agent_id, _ = await _tenant()
    user_id = await _member(tenant_id)
    first = await _fact(tenant_id, "We open at 9.")
    second = await _fact(tenant_id, "Parking is free.")

    async def change(fact_id: UUID, **args: Any) -> None:
        proposal = await _propose(
            tenant_id,
            user_id,
            "knowledge_fact_change",
            {"fact_id": str(fact_id), "text": None, "position": None, **args},
        )
        await _confirm(tenant_id, user_id, proposal.token)

    await change(first, change="edit", text="We open at 9 am.")
    await change(first, change="pin")
    await change(second, change="pin")
    await change(second, change="move", position=1)
    pinned = [f for f in await _facts(tenant_id) if f.pinned]
    assert [f.id for f in pinned] == [second, first]
    assert pinned[1].text == "We open at 9 am."
    await change(first, change="remove")
    assert [f.id for f in await _facts(tenant_id)] == [second]


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"change": "edit", "text": None, "position": None}, "needs `text`"),
        ({"change": "move", "text": None, "position": 1}, "only pinned facts"),
        ({"change": "unpin", "text": None, "position": None}, "not pinned"),
    ],
)
async def test_the_fact_refusals_the_model_can_act_on(args: dict[str, Any], reason: str) -> None:
    tenant_id, _agent_id, _ = await _tenant()
    user_id = await _member(tenant_id)
    fact_id = await _fact(tenant_id, "We open at 9.")
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(
            tenant_id, user_id, "knowledge_fact_change", {"fact_id": str(fact_id), **args}
        )
    assert reason in refused.value.reason
    with pytest.raises(WriteRefusedError):
        await _propose(
            tenant_id,
            user_id,
            "knowledge_fact_change",
            {"fact_id": str(uuid.uuid4()), "change": "remove", "text": None, "position": None},
        )


# --- agent_tests_run ----------------------------------------------------------------------


async def test_a_run_is_refused_for_an_agent_that_cannot_be_tested_yet() -> None:
    tenant_id, agent_id, _ = await _tenant()
    user_id = await _member(tenant_id)
    with pytest.raises(WriteRefusedError):
        await _propose(
            tenant_id, user_id, "agent_tests_run", {"agent_id": str(agent_id), "again": False}
        )


async def test_a_run_goes_through_request_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.copilot import question_actions

    tenant_id, agent_id, _ = await _tenant()
    user_id = await _member(tenant_id)

    class _Ready:
        available = True
        reason = None

    class _Run:
        id = uuid.uuid4()
        set_version = 1

    asked: dict[str, Any] = {}

    async def ready(session: Any, aid: UUID) -> Any:
        return _Ready()

    async def allowed(session: Any, *, tenant_id: UUID) -> None:
        return None

    async def request_run(session: Any, **kwargs: Any) -> Any:
        asked.update(kwargs)
        return _Run()

    monkeypatch.setattr(question_actions.test_conversations, "readiness", ready)
    monkeypatch.setattr(question_actions.test_conversations, "request_run", request_run)
    monkeypatch.setattr(question_actions, "require_ai_assist", allowed)
    with pytest.raises(WriteRefusedError):
        await _propose(
            tenant_id, user_id, "agent_tests_run", {"agent_id": str(agent_id), "again": True}
        )
    proposal = await _propose(
        tenant_id, user_id, "agent_tests_run", {"agent_id": str(agent_id), "again": False}
    )
    assert proposal.cost is not None
    await _confirm(tenant_id, user_id, proposal.token)
    assert asked["agent_id"] == agent_id and asked["retest_of"] is None
    assert ("agent.tests_requested", "agent", str(agent_id)) in await _audit(tenant_id)


# --- agent_test_add -----------------------------------------------------------------------


async def test_a_saved_test_is_added_at_once_and_undo_deletes_it() -> None:
    tenant_id, agent_id, _ = await _tenant()
    user_id = await _member(tenant_id)
    principal = _principal(tenant_id, user_id)
    done = await write_tools.run_immediate(
        "agent_test_add",
        json.dumps(
            {
                "agent_id": str(agent_id),
                "caller_lines": ["Do you deliver on Sunday?"],
                "expected": "Says yes, before noon.",
                "title": None,
            }
        ),
        principal=principal,
        seed=f"add-{uuid.uuid4()}",
        ip=None,
    )
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM agent_test_cases WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar()
    assert count == 1
    assert done.action_id is not None
    async with tenant_session(tenant_id) as session:
        undone = await undo_client_action(
            session, UUID(str(done.action_id)), principal=principal, ip=None
        )
    assert "deleted" in undone.detail
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM agent_test_cases WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar()
    assert count == 0
    with pytest.raises(ProblemError):
        async with tenant_session(tenant_id) as session:
            await undo_client_action(
                session, UUID(str(done.action_id)), principal=principal, ip=None
            )
