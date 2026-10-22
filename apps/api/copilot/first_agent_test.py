"""The first-agent chat's abilities (D-854): a ready-made job on `agent_create`, the opening
line on `agent_edit`, the pinned answers card, and the guide only that screen carries."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from calevate_shared.call_script import opening_line_of
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import prompt, write_tools
from apps.api.copilot.console_actions_test import _draft_agent
from apps.api.copilot.schemas import CopilotAskIn, CopilotScreen
from apps.api.copilot.screen_guides import FIRST_AGENT_GUIDE, screen_guide
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.db.session import tenant_session
from apps.api.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _run(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.run_immediate(
        name,
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"first-agent-{uuid.uuid4()}",
        ip=None,
    )


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name, json.dumps(args), actor=write_tools.actor_for(_principal(tenant_id, _user_of(token)))
    )


async def _one(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _opening(tenant_id: UUID, agent_id: UUID) -> str:
    row = await _one(
        tenant_id,
        "SELECT pv.body FROM agents a JOIN prompt_versions pv "
        "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) WHERE a.id = :a",
        a=agent_id,
    )
    return opening_line_of(row[0])


def _create(name: str, direction: str, job: str | None) -> dict[str, Any]:
    return {"name": name, "direction": direction, "language_primary": "en-IN", "job": job}


# --- agent_create with a job ----------------------------------------------------------------


async def test_a_job_gives_the_new_agent_its_ready_made_script_and_details() -> None:
    tenant_id, _slug, token = await _make_tenant()
    receipt = await _run(
        tenant_id, token, "agent_create", _create("Front desk", "inbound", "answer_calls")
    )
    assert receipt.applied is True
    agent_id = UUID(receipt.object_id)
    row = await _one(
        tenant_id,
        "SELECT direction, status FROM agents WHERE id = :a",
        a=agent_id,
    )
    assert (row[0], row[1]) == ("inbound", "draft")
    assert await _opening(tenant_id, agent_id) != ""


async def test_both_starts_from_the_answering_job_and_is_widened() -> None:
    tenant_id, _slug, token = await _make_tenant()
    receipt = await _run(
        tenant_id, token, "agent_create", _create("Both ways", "both", "answer_calls")
    )
    agent_id = UUID(receipt.object_id)
    row = await _one(tenant_id, "SELECT direction FROM agents WHERE id = :a", a=agent_id)
    assert row[0] == "both"
    assert await _opening(tenant_id, agent_id) != ""


@pytest.mark.parametrize(
    ("direction", "job"),
    [("both", "call_leads"), ("inbound", "call_leads"), ("outbound", "answer_calls")],
)
async def test_a_job_and_direction_that_disagree_are_refused_before_anything_is_made(
    direction: str, job: str
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _run(tenant_id, token, "agent_create", _create("Mismatch", direction, job))
    assert "job" in refused.value.reason
    assert await _one(tenant_id, "SELECT 1 FROM agents WHERE name = 'Mismatch'") is None


async def test_without_a_job_the_agent_is_blank_as_before() -> None:
    tenant_id, _slug, token = await _make_tenant()
    receipt = await _run(tenant_id, token, "agent_create", _create("Blank", "outbound", None))
    row = await _one(
        tenant_id, "SELECT system_prompt_id FROM agents WHERE id = :a", a=UUID(receipt.object_id)
    )
    assert row[0] is None


# --- the opening line on agent_edit ---------------------------------------------------------


def _edit(agent_id: UUID, opening_line: str | None) -> dict[str, Any]:
    return {
        "agent_id": str(agent_id),
        "language_primary": None,
        "voice_id": None,
        "ai_disclosure_enabled": None,
        "recording_notice_enabled": None,
        "opening_line": opening_line,
    }


async def _starter_agent(tenant_id: UUID, token: str) -> UUID:
    receipt = await _run(
        tenant_id, token, "agent_create", _create("Greeter", "inbound", "answer_calls")
    )
    return UUID(receipt.object_id)


async def test_the_opening_line_is_replaced_and_undo_puts_the_old_one_back() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _starter_agent(tenant_id, token)
    before = await _opening(tenant_id, agent_id)
    line = "Hello, you have reached the front desk. How can I help you today?"
    receipt = await _run(tenant_id, token, "agent_edit", _edit(agent_id, line))
    assert receipt.applied is True
    assert "opening line" in receipt.detail
    assert await _opening(tenant_id, agent_id) == line
    async with _client() as http:
        undone = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert undone.status_code == 200, undone.text
    assert await _opening(tenant_id, agent_id) == before


async def test_a_blank_opening_line_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _starter_agent(tenant_id, token)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _run(tenant_id, token, "agent_edit", _edit(agent_id, "   "))
    assert "opening_line" in refused.value.reason


async def test_an_edit_without_an_opening_line_leaves_the_script_alone() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _draft_agent(tenant_id)
    receipt = await _run(
        tenant_id,
        token,
        "agent_edit",
        {**_edit(agent_id, None), "language_primary": "hi-IN"},
    )
    assert receipt.applied is True


# --- knowledge_facts_pin ----------------------------------------------------------------------


def _facts(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"facts": [{"question": q, "answer": a} for q, a in pairs]}


_THREE = (
    ("Do you open on Sundays?", "No, Monday to Saturday, 9 to 6."),
    ("Is there parking?", "Yes, free parking behind the building."),
    ("Can I pay by UPI?", "Yes, UPI and cards are both fine."),
)


async def test_one_card_pins_all_three_answers_with_one_confirm() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(tenant_id, token, "knowledge_facts_pin", _facts(*_THREE))
    assert proposal.tool == "knowledge_facts_pin"
    for question, answer in _THREE:
        assert question in proposal.proposed and answer in proposal.proposed
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    rows = await _all(
        tenant_id, "SELECT question FROM kb_facts WHERE pinned AND removed_at IS NULL"
    )
    assert {r[0] for r in rows} >= {q for q, _ in _THREE}
    assert ("kb_fact.add", "kb_fact") in {(a, o) for a, o, _ in await _audit(tenant_id)}


async def _all(tenant_id: UUID, sql: str) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list((await session.execute(text(sql))).all())


async def test_a_question_already_pinned_is_refused_by_name() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(tenant_id, token, "knowledge_facts_pin", _facts(_THREE[0]))
    await _confirm(tenant_id, _user_of(token), proposal.token)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "knowledge_facts_pin", _facts(_THREE[0], _THREE[1]))
    assert "already" in refused.value.reason


@pytest.mark.parametrize(
    "facts",
    [
        _facts(("What is your number?", "Call us on +91 98765 43210.")),
        _facts(("Open on Sundays?", "No."), ("open on sundays?", "Never.")),
        _facts(("", "Something")),
        {"facts": []},
        _facts(*_THREE, ("A fourth?", "Too many.")),
    ],
)
async def test_unsafe_or_malformed_answers_are_refused_before_a_card(facts: dict[str, Any]) -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "knowledge_facts_pin", facts)


async def test_staff_cannot_pin_answers() -> None:
    tenant_id, _slug, token = await _make_tenant()
    actor = write_tools.actor_for(_principal(tenant_id, _user_of(token), role="staff"))
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(
            "knowledge_facts_pin", json.dumps(_facts(_THREE[0])), actor=actor
        )
    assert "role may not" in refused.value.reason


# --- the guide ---------------------------------------------------------------------------------


def _payload(route: str) -> CopilotAskIn:
    return CopilotAskIn(
        question="Let's start", screen=CopilotScreen(route=route, title="t", realm="client")
    )


def test_the_guide_rides_only_the_first_agent_screen_and_after_the_screen_state() -> None:
    assert screen_guide("/c/{slug}/agents/first") == FIRST_AGENT_GUIDE
    assert screen_guide("/c/acme/agents/first") == FIRST_AGENT_GUIDE
    for route in ("/c/acme/agents", "/c/acme/agents/new", "/c/acme/agents/first/x", "/c/acme"):
        assert screen_guide(route) == ""
    on = prompt.build_messages(_payload("/c/{slug}/agents/first"))
    off = prompt.build_messages(_payload("/c/{slug}/agents"))
    assert on[0] == off[0]  # the cached prefix is untouched
    last = on[-1]["content"]
    assert FIRST_AGENT_GUIDE in last
    assert (
        last.index(prompt.SCREEN_CLOSE)
        < last.index(FIRST_AGENT_GUIDE)
        < last.index(prompt.CLOSING_RULES)
    )
    assert FIRST_AGENT_GUIDE not in off[-1]["content"]


def test_the_guide_names_only_tools_that_exist() -> None:
    import re

    named = set(re.findall(r"`([a-z_]+)`", FIRST_AGENT_GUIDE))
    tools = {schema["function"]["name"] for schema in write_tools.write_tool_schemas()}
    from apps.api.copilot import service

    tools |= {tool.name for tool in service.realm_read_tools("client")}
    arguments = {"job", "answer_calls", "call_new_leads", "call_leads", "opening_line"}
    assert named - arguments <= tools, named - arguments - tools
