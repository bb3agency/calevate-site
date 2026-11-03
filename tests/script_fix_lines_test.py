""" "Fix them first" on Put it live (founder, 3 Nov 2026): the lines the script check found
are fixed by a suggestion written in the background, made from the draft on screen."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import script_proposals
from apps.api.db.session import tenant_session
from apps.api.main import app
from calevate_shared.call_script import CallScript
from httpx import ASGITransport, AsyncClient
from tests.agent_starters_test import _create, _tenant


async def _fix(token: str, agent_id: uuid.UUID, script: CallScript) -> tuple[int, dict[str, Any]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post(
            f"/v1/agents/{agent_id}/script/fix-lines",
            json={"script": script.model_dump(mode="json")},
            headers={"Authorization": f"Bearer {token}"},
        )
    return response.status_code, response.json()


@pytest.mark.rls
async def test_the_flagged_lines_are_sent_to_be_fixed_and_a_clean_script_is_refused() -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    code, body = await _create(token, {"name": "Varsha", "starter": "call_leads"})
    assert code == 201, body
    agent_id = uuid.UUID(body["id"])
    async with tenant_session(tenant_id) as session:
        starter = await script_proposals.read_proposal(session, agent_id)
        assert starter is not None
        base = starter.base_script
        # The starter's own suggestion is still being written; this test asks for its own.
        await script_proposals.store_failed(
            session, agent_id=agent_id, proposal_id=starter.id, note="x"
        )

    clean_code, clean = await _fix(token, agent_id, base)
    assert clean_code == 409, clean
    assert clean["type"].endswith("/script_has_nothing_to_fix")

    stages = list(base.stages)
    stages[0] = stages[0].model_copy(update={"sounds_like": "Is now a good time? Shall I go on?"})
    flagged = base.model_copy(update={"stages": stages})
    code, asked = await _fix(token, agent_id, flagged)
    assert code == 202, asked
    assert (asked["mode"], asked["status"]) == ("change", "drafting")
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
    assert proposal is not None
    # Made from the draft on screen, which is now the working copy.
    assert proposal.base_script.stages[0].sounds_like == "Is now a good time? Shall I go on?"


@pytest.mark.rls
async def test_a_failed_written_script_can_be_asked_for_again() -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    code, body = await _create(token, {"name": "Varsha", "starter": "call_leads"})
    assert code == 201, body
    agent_id = uuid.UUID(body["id"])
    async with tenant_session(tenant_id) as session:
        first = await script_proposals.read_proposal(session, agent_id)
        assert first is not None
        await script_proposals.store_failed(
            session, agent_id=agent_id, proposal_id=first.id, note="x"
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post(
            f"/v1/agents/{agent_id}/script/proposal/starter",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 202, response.text
    assert (response.json()["mode"], response.json()["status"]) == ("starter", "drafting")
