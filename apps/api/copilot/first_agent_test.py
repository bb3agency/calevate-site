"""The first-agent chat's abilities (D-854): a ready-made job on `agent_create`, the opening
line on `agent_edit`, the common questions card, and the guide only that screen carries."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from calevate_shared.call_script import opening_line_of
from calevate_shared.spoken_style import style_for
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import prompt, write_tools
from apps.api.copilot.console_actions import _AgentEditArgs, _describe_edit
from apps.api.copilot.console_actions_test import _draft_agent
from apps.api.copilot.schemas import CopilotAskIn, CopilotScreen
from apps.api.copilot.screen_guides import FIRST_AGENT_GUIDE, screen_guide
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.tenancy.business_profile import load_profile


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
    # No ready-made opening: a job's opening is written on its line or campaign.
    assert await _opening(tenant_id, agent_id) == ""


async def test_both_starts_from_the_answering_job_and_is_widened() -> None:
    tenant_id, _slug, token = await _make_tenant()
    receipt = await _run(
        tenant_id, token, "agent_create", _create("Both ways", "both", "answer_calls")
    )
    agent_id = UUID(receipt.object_id)
    row = await _one(tenant_id, "SELECT direction FROM agents WHERE id = :a", a=agent_id)
    assert row[0] == "both"
    assert await _opening(tenant_id, agent_id) == ""


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


async def test_during_the_first_run_pips_agent_is_the_first_runs_own() -> None:
    """Made from the first-agent chat, the agent is the one the screen's card and What first
    use, with its notice job queued; a second create makes an ordinary agent."""
    from apps.api.first_run import service as first_run
    from apps.api.first_run.work import NOTICE_JOB

    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        # The fixture's own agent would put the account past its first run (`due_for`).
        await session.execute(text("UPDATE agents SET deleted_at = now()"))
    receipt = await _run(tenant_id, token, "agent_create", _create("Anjali", "inbound", None))
    agent_id = UUID(receipt.object_id)
    async with tenant_session(tenant_id) as session:
        state = await first_run.read_state(session, tenant_id=tenant_id)
    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages "
                    "WHERE job = :j AND payload->>'agent_id' = :a"
                ),
                {"j": NOTICE_JOB, "a": str(agent_id)},
            )
        ).scalar()
    assert state.agent_id == agent_id and state.due
    assert queued == 1
    second = await _run(tenant_id, token, "agent_create", _create("Ravi", "outbound", None))
    async with tenant_session(tenant_id) as session:
        again = await first_run.read_state(session, tenant_id=tenant_id)
    assert again.agent_id == agent_id and UUID(second.object_id) != agent_id


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
    # A starter carries no opening (D-965), so the line undo puts back is set first.
    before = "Hello, front desk here. What can I do for you?"
    await _run(tenant_id, token, "agent_edit", _edit(agent_id, before))
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


async def test_only_the_fields_it_changes_and_one_opening_for_an_agent_that_calls() -> None:
    """Pip on Gemini (3 Nov 2026) sent only the fields it meant to change, and its line "for
    the calls it places" to an agent that only places calls; both used to be refused."""
    tenant_id, _slug, token = await _make_tenant()
    receipt = await _run(
        tenant_id, token, "agent_create", _create("Varsha", "outbound", "call_leads")
    )
    agent_id = UUID(receipt.object_id)
    line = "Hello, I am calling from Rytu Khata about the Chrome extension. Is now a good time?"
    receipt = await _run(
        tenant_id,
        token,
        "agent_edit",
        {"agent_id": str(agent_id), "outbound_opening_line": line},
    )
    assert receipt.applied is True
    assert await _opening(tenant_id, agent_id) == line


async def test_a_blank_opening_line_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _starter_agent(tenant_id, token)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _run(tenant_id, token, "agent_edit", _edit(agent_id, "   "))
    assert "opening_line" in refused.value.reason
    assert refused.value.plain == "The opening line was empty."


def _telugu_line_with_a_textbook_word() -> str:
    """A line built from the Telugu spoken-style list itself — one everyday word and one
    textbook word — so the test writes no Telugu of its own."""
    style = style_for("te-IN")
    assert style is not None and len(style.word_swaps) >= 2
    (textbook, _), (_, everyday) = style.word_swaps[0], style.word_swaps[1]
    return f"{everyday} {textbook}"


async def test_an_opening_line_the_owner_dictated_keeps_their_textbook_word() -> None:
    """FAILS IF: Pip's agent_edit refuses a textbook word the owner wrote in the
    conversation, as the form fill already lets it through (PIP-07), or the refusal shown to
    the owner names the field key instead of saying it plainly."""
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _starter_agent(tenant_id, token)
    line = _telugu_line_with_a_textbook_word()
    args = {**_edit(agent_id, line), "language_primary": "te-IN"}
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _run(tenant_id, token, "agent_edit", args)
    assert refused.value.plain == "The opening line used words callers do not say."

    receipt = await write_tools.run_immediate(
        "agent_edit",
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"first-agent-{uuid.uuid4()}",
        ip=None,
        said=(f"Make the opening line: {line}", "yes, put it in"),
    )
    assert receipt.applied is True
    assert await _opening(tenant_id, agent_id) == line


async def test_a_staged_opening_line_the_owner_dictated_can_be_approved() -> None:
    """FAILS IF: Approve (and its preview) re-plans a staged agent_edit with no conversation
    in hand, so the owner's own textbook word that passed at staging is refused at Approve
    and the card can never be approved."""
    from apps.api.copilot import jobs

    tenant_id, slug, token = await _make_tenant()
    agent_id = await _starter_agent(tenant_id, token)
    line = _telugu_line_with_a_textbook_word()
    async with tenant_session(tenant_id) as session:
        job = await jobs.create_job(
            session,
            tenant_id=tenant_id,
            user_id=_user_of(token),
            goal="set the opening",
            screen_route="/c/{slug}/agents",
        )
    staged = await write_tools.stage_for_approval(
        "agent_edit",
        json.dumps({**_edit(agent_id, line), "language_primary": "te-IN"}),
        principal=_principal(tenant_id, _user_of(token)),
        job_id=job.id,
        said=(f"Make the opening line: {line}",),
    )
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        preview = await http.get(
            f"/v1/copilot/approvals/{staged.action_id}/preview", headers=headers
        )
        approved = await http.post(
            f"/v1/copilot/approvals/{staged.action_id}/approve", headers=headers
        )
    assert preview.status_code == 200, preview.text
    assert preview.json()["still_applies"] is True, preview.json()
    assert approved.status_code == 200, approved.text
    assert approved.json()["applied"] is True, approved.json()
    assert await _opening(tenant_id, agent_id) == line


def test_a_voice_change_names_the_voice_never_its_id() -> None:
    """FAILS IF: the agent_edit card shows a catalogue voice id to the owner (PIP-15)."""
    parsed = _AgentEditArgs.model_validate(
        {
            "agent_id": str(uuid.uuid4()),
            "language_primary": None,
            "voice_id": "cat-voice-2",
            "ai_disclosure_enabled": None,
            "recording_notice_enabled": None,
        }
    )
    current = {"language_primary": "en-IN", "voice_id": "cat-voice-1"}
    was, becomes = _describe_edit(parsed, current, {"cat-voice-1": "Asha", "cat-voice-2": "Ravi"})
    assert (was, becomes) == (["voice Asha"], ["voice Ravi"])
    was, becomes = _describe_edit(parsed, current, {})
    assert (was, becomes) == (["its current voice"], ["a different voice"])
    assert "cat-voice" not in " ".join(was + becomes)


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


# --- business_faqs_add ------------------------------------------------------------------------


def _facts(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"faqs": [{"question": q, "answer": a} for q, a in pairs]}


_THREE = (
    ("Do you open on Sundays?", "No, Monday to Saturday, 9 to 6."),
    ("Is there parking?", "Yes, free parking behind the building."),
    ("Can I pay by UPI?", "Yes, UPI and cards are both fine."),
)


async def test_one_card_adds_all_three_answers_to_the_business_profile() -> None:
    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        before = len((await load_profile(session, tenant_id=tenant_id)).faqs)
    proposal = await _propose(tenant_id, token, "business_faqs_add", _facts(*_THREE))
    assert proposal.tool == "business_faqs_add"
    for question, answer in _THREE:
        assert question in proposal.proposed and answer in proposal.proposed
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    async with tenant_session(tenant_id) as session:
        faqs = (await load_profile(session, tenant_id=tenant_id)).faqs
    assert len(faqs) == before + 3
    assert [(f.question, f.answer) for f in faqs[-3:]] == list(_THREE)
    # One home: nothing is written as a fact beside the profile.
    assert (
        await _all(tenant_id, "SELECT id FROM kb_facts WHERE question = 'Is there parking?'") == []
    )
    audit = {(a, o) for a, o, _ in await _audit(tenant_id)}
    assert ("business_profile.updated", "organization") in audit


async def _all(tenant_id: UUID, sql: str) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list((await session.execute(text(sql))).all())


async def test_a_question_the_profile_already_answers_is_refused_by_name() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(tenant_id, token, "business_faqs_add", _facts(_THREE[0]))
    await _confirm(tenant_id, _user_of(token), proposal.token)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "business_faqs_add", _facts(_THREE[0], _THREE[1]))
    assert "already" in refused.value.reason


@pytest.mark.parametrize(
    "facts",
    [
        _facts(("What is your number?", "Call us on +91 98765 43210.")),
        _facts(("Open on Sundays?", "No."), ("open on sundays?", "Never.")),
        _facts(("", "Something")),
        {"faqs": []},
        _facts(*_THREE, ("A fourth?", "Too many.")),
    ],
)
async def test_unsafe_or_malformed_answers_are_refused_before_a_card(facts: dict[str, Any]) -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(tenant_id, token, "business_faqs_add", facts)


async def test_staff_cannot_add_answers() -> None:
    tenant_id, _slug, token = await _make_tenant()
    actor = write_tools.actor_for(_principal(tenant_id, _user_of(token), role="staff"))
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(
            "business_faqs_add", json.dumps(_facts(_THREE[0])), actor=actor
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
    arguments = {"job", "answer_calls", "call_new_leads", "call_leads", "opening_line", "inbound"}
    assert named - arguments <= tools, named - arguments - tools
