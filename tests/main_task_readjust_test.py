"""The "Re-adjust script" button on the agent page (founder, 9 Nov 2026): Pip rewrites the
working script to fit the agent's main task as an ordinary suggestion, reviewed on the Script
tab."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import script_builder, script_proposals
from apps.api.db.session import tenant_session
from apps.api.main import app
from calevate_shared.call_script import CallScript
from httpx import ASGITransport, AsyncClient
from tests.agent_starters_test import _create, _tenant

GOAL = "Get the farmer to install the app and open it once while on the call."


async def _readjust(token: str, agent_id: uuid.UUID) -> tuple[int, dict[str, Any]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post(
            f"/v1/agents/{agent_id}/script/proposal/main-task",
            headers={"Authorization": f"Bearer {token}"},
        )
    return response.status_code, response.json()


async def _agent(name: str) -> tuple[uuid.UUID, uuid.UUID, str, CallScript]:
    """An agent made from a starter, with the starter's own suggestion out of the way."""
    tenant_id, token = await _tenant("custom", name)
    code, body = await _create(token, {"name": "Varsha", "starter": "call_leads"})
    assert code == 201, body
    agent_id = uuid.UUID(body["id"])
    async with tenant_session(tenant_id) as session:
        starter = await script_proposals.read_proposal(session, agent_id)
        assert starter is not None
        await script_proposals.store_failed(
            session, agent_id=agent_id, proposal_id=starter.id, note="x"
        )
    return tenant_id, agent_id, token, starter.base_script


async def _save_draft(tenant_id: uuid.UUID, agent_id: uuid.UUID, script: CallScript) -> None:
    async with tenant_session(tenant_id) as session:
        await script_builder.save_draft(session, agent_id, script)


@pytest.mark.rls
async def test_the_script_is_adjusted_to_the_main_task_just_saved_into_the_draft() -> None:
    tenant_id, agent_id, token, base = await _agent("Rytu Khata")
    await _save_draft(tenant_id, agent_id, base.model_copy(update={"goal": GOAL}))

    code, asked = await _readjust(token, agent_id)
    assert code == 202, asked
    assert (asked["mode"], asked["status"]) == ("change", "drafting")
    # The owner reads what was asked on the Script tab, main task included.
    assert GOAL in asked["request"]
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
    assert proposal is not None
    # Made from the draft, so the main task the owner just edited is the one written to.
    assert proposal.base_script.goal == GOAL
    assert proposal.request == script_proposals.MAIN_TASK_CHANGE.format(goal=GOAL)
    # A suggestion, never a fix limited to named lines.
    assert proposal.paths == []


@pytest.mark.rls
async def test_an_agent_with_no_main_task_is_told_to_add_one() -> None:
    tenant_id, agent_id, token, base = await _agent("Rytu Khata Two")
    await _save_draft(tenant_id, agent_id, base.model_copy(update={"goal": "   "}))
    code, body = await _readjust(token, agent_id)
    assert code == 422, body
    assert body["type"].endswith("/script_main_task_missing")


@pytest.mark.rls
async def test_a_hand_written_script_is_never_re_adjusted() -> None:
    tenant_id, agent_id, token, _base = await _agent("Rytu Khata Three")
    await _save_draft(
        tenant_id, agent_id, CallScript(raw_override="Tell them we will send an SMS.")
    )
    code, body = await _readjust(token, agent_id)
    assert code == 422, body
    assert body["type"].endswith("/script_main_task_hand_written")


@pytest.mark.rls
async def test_a_suggestion_waiting_for_review_is_never_replaced() -> None:
    tenant_id, agent_id, token, base = await _agent("Rytu Khata Four")
    await _save_draft(tenant_id, agent_id, base.model_copy(update={"goal": GOAL}))
    code, asked = await _readjust(token, agent_id)
    assert code == 202, asked

    # Still being written: a second press is refused rather than racing the first.
    again, busy = await _readjust(token, agent_id)
    assert again == 409, busy
    assert busy["type"].endswith("/script_proposal_in_progress")

    async with tenant_session(tenant_id) as session:
        await script_proposals.store_ready(
            session,
            agent_id=agent_id,
            proposal_id=uuid.UUID(asked["id"]),
            script=base,
            unplaced=[],
            disclosure=None,
        )
    later, refused = await _readjust(token, agent_id)
    assert later == 409, refused
    assert refused["type"].endswith("/script_suggestion_waiting")
