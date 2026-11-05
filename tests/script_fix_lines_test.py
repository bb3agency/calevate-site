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
    # Only the flagged line may change (A-02).
    assert proposal.paths == ["stages.0.sounds_like"]
    assert asked["draft_saved_at"]


_TENANTS: dict[uuid.UUID, uuid.UUID] = {}


async def _tenant_of(agent_id: uuid.UUID) -> uuid.UUID:
    return _TENANTS[agent_id]


async def _agent_with_no_proposal(name: str = "Rytu Khata") -> tuple[uuid.UUID, str, Any]:
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
    _TENANTS[agent_id] = tenant_id
    return agent_id, token, starter.base_script


@pytest.mark.rls
async def test_a_hand_written_script_is_never_sent_to_be_fixed() -> None:
    """A-01: the writer edits steps; handed one text it replaced the owner's whole script."""
    agent_id, token, _base = await _agent_with_no_proposal()
    raw = CallScript(raw_override="Tell them we will send an SMS with the details.")
    code, body = await _fix(token, agent_id, raw)
    assert code == 422, body
    assert body["type"].endswith("/fix_lines_hand_written")


@pytest.mark.rls
async def test_a_fix_does_not_overwrite_a_draft_changed_in_another_tab() -> None:
    """A-13: the draft saved by fix-lines is a compare-and-set like every autosave."""
    agent_id, token, base = await _agent_with_no_proposal()
    stages = list(base.stages)
    stages[0] = stages[0].model_copy(update={"sounds_like": "Is now a good time? Shall I go on?"})
    flagged = base.model_copy(update={"stages": stages})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post(
            f"/v1/agents/{agent_id}/script/fix-lines",
            json={
                "script": flagged.model_dump(mode="json"),
                "base_saved_at": "2020-01-01T00:00:00+00:00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/script_changed_elsewhere")


@pytest.mark.rls
async def test_a_new_fix_does_not_replace_a_suggestion_waiting_for_review() -> None:
    """A-14: a ready suggestion the owner may be reading is never replaced unseen."""
    agent_id, token, base = await _agent_with_no_proposal()
    stages = list(base.stages)
    stages[0] = stages[0].model_copy(update={"sounds_like": "Is now a good time? Shall I go on?"})
    flagged = base.model_copy(update={"stages": stages})
    code, asked = await _fix(token, agent_id, flagged)
    assert code == 202, asked
    tenant_id = await _tenant_of(agent_id)
    async with tenant_session(tenant_id) as session:
        await script_proposals.store_ready(
            session,
            agent_id=agent_id,
            proposal_id=uuid.UUID(asked["id"]),
            script=flagged,
            unplaced=[],
            disclosure=None,
        )
    again, refused = await _fix(token, agent_id, flagged)
    assert again == 409, refused
    assert refused["type"].endswith("/script_suggestion_waiting")


def test_a_fix_keeps_every_line_the_check_did_not_name() -> None:
    """A-02: whatever the model returns, only the flagged lines change and none is emptied."""
    from calevate_shared.call_script import ConversationStage, Objection

    base = CallScript(
        schema_version=2,
        opening_line="Hello, how can I help?",
        goal="Help callers with the app.",
        stages=[
            ConversationStage(id="a", name="Greet", instruction="Greet them.", sounds_like="Hi?"),
            ConversationStage(id="b", name="Help", instruction="Help them.", sounds_like="Ok"),
        ],
        objections=[Objection(objection="Busy", response="Call later.")],
    )
    written = CallScript(
        schema_version=2,
        opening_line="",
        goal="Sell them more.",
        stages=[
            ConversationStage(id="b", name="Help", instruction="Help.", sounds_like="Fixed line"),
        ],
        objections=[],
    )
    kept = script_proposals.kept_to_paths(written, base, ["stages.1.sounds_like"])
    assert kept.stages[1].sounds_like == "Fixed line"
    assert kept.stages[0] == base.stages[0]
    assert kept.stages[1].instruction == "Help them."
    assert (kept.goal, kept.opening_line, kept.objections) == (
        base.goal,
        base.opening_line,
        base.objections,
    )
    # A flagged line the model emptied stays as written.
    emptied = written.model_copy(
        update={"stages": [written.stages[0].model_copy(update={"sounds_like": ""})]}
    )
    assert script_proposals.kept_to_paths(emptied, base, ["stages.1.sounds_like"]) == base


def test_a_document_suggestion_never_empties_a_part() -> None:
    from calevate_shared.call_script import Objection

    base = CallScript(
        schema_version=2,
        goal="Help callers.",
        objections=[Objection(objection="Busy", response="Call later.")],
    )
    written = CallScript(schema_version=2, goal="", objections=[], ending="Thank you.")
    kept = script_proposals.emptied_kept(written, base)
    assert (kept.goal, kept.objections, kept.ending) == (base.goal, base.objections, "Thank you.")


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
