"""An agent's details drafted from its own script (founder, 3 Nov 2026): applied over the
set it was made with, never over a set somebody changed."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import script_proposals
from apps.api.agents.extraction_routes import write_schema
from apps.api.db.session import tenant_session
from apps.workers import agent_fields_draft as worker
from apps.workers.extraction import AssistCapability
from apps.workers.lead_fields_draft import fields_from_model
from apps.workers.script_assist import JsonAnswer
from calevate_shared.extraction import ExtractionField
from tests.agent_starters_test import _create, _tenant

ANSWER = {
    "fields": [
        {
            "label": "App installed",
            "type": "bool",
            "reason": "Whether they installed the app from Chrome.",
            "required": True,
            "choices": [],
        },
        {
            "label": "Satisfied",
            "type": "enum",
            "reason": "How happy they are with it.",
            "required": False,
            "choices": ["Yes", "Somewhat", "No"],
        },
    ]
}


def _answered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answer(*_args: Any, parse: Any, **_kwargs: Any) -> JsonAnswer[Any]:
        return JsonAnswer(
            value=parse(ANSWER),
            capability=AssistCapability(available=True, provider="gemini"),
            model="gemini-2.5-flash-lite",
        )

    async def meter(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "ask_json", answer)
    monkeypatch.setattr(worker.crm_assist, "meter_earlier", meter)
    monkeypatch.setattr(worker.crm_assist, "meter_assist", meter)


async def _agent(token: str) -> uuid.UUID:
    code, body = await _create(token, {"name": "Varsha", "starter": "call_leads"})
    assert code == 201, body
    return uuid.UUID(body["id"])


@pytest.mark.rls
async def test_the_scripts_details_replace_the_untouched_starting_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _answered(monkeypatch)
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    agent_id = await _agent(token)
    async with tenant_session(tenant_id) as session:
        started = await script_proposals.agent_own_fields(session, agent_id)
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "fields": started}
    assert await worker.draft_agent_fields({}, payload) == "applied"
    async with tenant_session(tenant_id) as session:
        now = await script_proposals.agent_own_fields(session, agent_id)
    assert [f["key"] for f in now] == ["app_installed", "satisfied"]


@pytest.mark.rls
async def test_a_set_the_owner_changed_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    _answered(monkeypatch)
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    agent_id = await _agent(token)
    async with tenant_session(tenant_id) as session:
        started = await script_proposals.agent_own_fields(session, agent_id)
        mine = [ExtractionField(key="farm_size", label="Farm size", type="text", reason="")]
        await write_schema(session, agent_id=agent_id, fields=mine)
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "fields": started}
    assert await worker.draft_agent_fields({}, payload) == "owner_changed"
    async with tenant_session(tenant_id) as session:
        now = await script_proposals.agent_own_fields(session, agent_id)
    assert [f["key"] for f in now] == ["farm_size"]


def test_the_agents_draft_keeps_the_business_drafts_rules() -> None:
    assert [f.key for f in fields_from_model(ANSWER)] == ["app_installed", "satisfied"]
    assert worker.AGENT_PROMPT.startswith(worker.SYSTEM_PROMPT)
