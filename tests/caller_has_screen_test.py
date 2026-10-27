"""An agent whose caller follows along on a screen (D-906).

A guided-setup or support agent walks the caller through an app while they hold the phone, so
it must name what is on their screen, give one step a turn, say a failed step again shorter and
spell a web address. Off, which every agent is until its owner turns it on, nothing changes.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

import pytest
from apps.api.agents import publishing, roster
from apps.api.agents.service import _load_agent, _to_config
from apps.api.agents.turn_checks import caller_says_done, claims_done, conversation_problems
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.main import app
from apps.workers.agent_test_ai import SCREEN_BRIEF_LINE, brief_text
from calevate_shared.engine import (
    CALL_INSTRUCTIONS,
    SCREEN_CALL_INSTRUCTIONS,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    call_instructions,
    compose_engine_prompt,
    engine_prompt_layers,
    screen_steps_bullet,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_test_loop_test import BRIEF
from tests.api_security_test import _make_tenant
from tests.conftest import create_org_with_receptionist


def _cfg(language: str = "te-IN", **kw: object) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="RytuKhata",
        direction="outbound",
        language_primary=language,
        system_prompt="[TASK FLOW]\nHelp them install the app.",
        opening_line="",
        call_is_recorded=True,
        **kw,  # type: ignore[arg-type]
    )


def _how_to_speak(cfg: AgentConfig) -> str:
    return dict(engine_prompt_layers(cfg))["how_to_speak"]


# --- the prompt -------------------------------------------------------------------------


def test_off_composes_exactly_what_every_agent_had() -> None:
    off = _cfg()
    assert _how_to_speak(off) == VOICE_STYLE_GUIDANCE
    assert compose_engine_prompt(off) == compose_engine_prompt(_cfg(caller_has_screen=False))
    assert call_instructions(off) == CALL_INSTRUCTIONS
    assert "caller_has_screen" not in off.model_dump()


def test_on_names_labels_one_step_at_a_time_and_waits_for_done() -> None:
    on = _how_to_speak(_cfg(caller_has_screen=True))
    bullet = screen_steps_bullet("te-IN")
    assert bullet in on
    assert "one step a turn" in bullet and "label word for word" in bullet
    assert "wait until they say it is done" in bullet
    # Placed after the written-output bullet, which still forbids markup, lists and links.
    assert on.index("No markdown, emoji") < on.index(bullet)
    assert "lists, links, actions or notes" in on


def test_on_lets_a_failed_step_be_said_again_shorter() -> None:
    on = _how_to_speak(_cfg(caller_has_screen=True))
    assert "Never re-ask what they said or repeat a sentence." not in on
    assert "a step they could not do, say again, shorter." in on
    assert "Never re-ask what they said" in on


@pytest.mark.parametrize(
    ("language", "spelled"),
    [
        ("te-IN", '("ఆర్, వై, టీ, డాట్ కామ్")'),
        ("hi-IN", '("आर, वाई, टी, डॉट कॉम")'),
        ("en-IN", '("R, Y, T, dot com")'),
    ],
)
def test_a_web_address_is_spelled_by_english_letter_names_in_the_calls_letters(
    language: str, spelled: str
) -> None:
    bullet = screen_steps_bullet(language)
    assert "each by its English letter name in the call's letters" in bullet
    assert spelled in bullet


def test_a_language_without_an_example_gets_the_rule_without_one() -> None:
    bullet = screen_steps_bullet("ta-IN")
    assert "English letter name" in bullet and '("' not in bullet


def test_our_call_frame_lets_the_screen_be_named() -> None:
    assert "buttons" in CALL_INSTRUCTIONS
    assert "buttons" not in SCREEN_CALL_INSTRUCTIONS
    assert "their own screen" in SCREEN_CALL_INSTRUCTIONS
    assert call_instructions(_cfg(caller_has_screen=True)) == SCREEN_CALL_INSTRUCTIONS


# --- the checks ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Turn:
    said: str
    reply: str
    tools: Sequence[str] = ()


@pytest.mark.parametrize("said", ["సేవ్ అయింది అండి", "Add చేశాను", "done", "yes, it's saved", "हो गया"])
def test_acknowledging_the_callers_own_step_is_no_claim(said: str) -> None:
    assert caller_says_done(said)
    reply = "సూపర్ అండి, Add అయింది. ఇప్పుడు కింద Expenses నొక్కండి."
    assert claims_done(reply)
    assert not claims_done(reply, caller_said=said)
    kinds = [p.kind for p in conversation_problems([_Turn(said=said, reply=reply)])]
    assert "unconfirmed_action" not in kinds


@pytest.mark.parametrize(
    "said", ["సేవ్ అయిందా?", "not done yet", "ఇంకా కాలేదు అండి", "नहीं हुआ", "order kavali"]
)
def test_a_claim_without_the_callers_word_is_still_caught(said: str) -> None:
    reply = "మీ ఆర్డర్ బుక్ అయింది అండి."
    kinds = [p.kind for p in conversation_problems([_Turn(said=said, reply=reply)])]
    assert "unconfirmed_action" in kinds


def test_the_judge_is_told_a_screen_step_is_right() -> None:
    assert SCREEN_BRIEF_LINE not in brief_text(BRIEF)
    assert SCREEN_BRIEF_LINE in brief_text(replace(BRIEF, caller_has_screen=True))


# --- the switch, end to end ---------------------------------------------------------------


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="RytuKhata",
        slug=f"scr-{uuid.uuid4().hex[:8]}",
        vertical_template="custom",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def test_the_switch_reaches_the_roster_and_the_published_config() -> None:
    tenant_id, agent_id = await _tenant()
    first = await publishing.set_caller_has_screen(
        tenant_id=tenant_id, agent_id=agent_id, enabled=True
    )
    assert first.enabled and not first.unchanged
    again = await publishing.set_caller_has_screen(
        tenant_id=tenant_id, agent_id=agent_id, enabled=True
    )
    assert again.unchanged and not again.engine_synced
    async with tenant_session(tenant_id) as session:
        listed = await roster.agent_by_id(session, agent_id)
        row = await _load_agent(session, tenant_id, agent_id)
    assert listed is not None and listed.caller_has_screen
    assert row["caller_has_screen"]
    scripted = {**row, "prompt": "[TASK FLOW]\nHelp them install the app."}
    assert _to_config(tenant_id, scripted, engine=get_engine()).caller_has_screen  # type: ignore[arg-type]
    off = await publishing.set_caller_has_screen(
        tenant_id=tenant_id, agent_id=agent_id, enabled=False
    )
    assert not off.enabled and not off.unchanged
    async with tenant_session(tenant_id) as session:
        after = await roster.agent_by_id(session, agent_id)
    assert after is not None and not after.caller_has_screen


async def test_the_owner_switches_it_over_http_and_the_flip_is_audited() -> None:
    tenant_id, slug, token = await _make_tenant("owner")
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        flipped = await http.patch(
            f"/v1/agents/{agent_id}/caller-screen", headers=headers, json={"enabled": True}
        )
        read = await http.get(f"/v1/agents/{agent_id}", headers=headers)
    assert flipped.status_code == 200, flipped.text
    assert flipped.json() == {"agent_id": str(agent_id), "enabled": True, "engine_synced": False}
    assert read.json()["caller_has_screen"] is True
    async with tenant_session(tenant_id) as session:
        actions = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE object_id = :a"), {"a": str(agent_id)}
            )
        ).scalars()
        assert "agent.caller_has_screen_enabled" in set(actions)


async def test_an_unknown_agent_is_not_found() -> None:
    tenant_id, _ = await _tenant()
    with pytest.raises(ProblemError) as caught:
        await publishing.set_caller_has_screen(
            tenant_id=tenant_id, agent_id=uuid.uuid4(), enabled=True
        )
    assert caught.value.kind == "not_found"
