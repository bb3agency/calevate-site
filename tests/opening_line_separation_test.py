"""The opening notices and the opening line are separate things (D-708).

The two switches decide only whether the AI disclosure and the recording notice are said
BEFORE the agent's opening line. They never remove, add or replace the opening line, which
is the greeting in the agent's script. What a caller hears first is therefore
[AI notice if on] + [recording notice if on] + opening line; with both off, the opening
line alone. The truthful answer to a caller who asks is untouched by any of it.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from apps.api.agents.engine_limits import (
    OPENING_REQUIRED,
    OPENING_TOO_LONG,
    refuse_over_engine_limits,
)
from apps.api.agents.roster import agent_out
from apps.api.agents.verification import judge
from apps.api.compliance.disclosure import AI_DISCLOSURE_TEMPLATES
from apps.api.core.errors import ProblemError
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from apps.api.engine.hosted_platform import engine_greeting
from calevate_shared.call_script import CallScript, compile_call_script, opening_line_of
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    AgentSnapshot,
    CallContext,
    compose_engine_prompt,
    compose_first_utterance,
    join_first_words,
)
from tests.thinnest_engine_test import _agent_write, _body, _cfg, _engine, _recorder

NOTICES = "Idi Sunrise Clinic AI assistant. Ee call record avutundi."
GREETING = "Namaskaram! Sunrise Clinic, meeku ela sahayam cheyagalanu?"


def _script(opening: str = GREETING) -> str:
    return compile_call_script(CallScript(opening_line=opening))


def _config(*, notices: str = NOTICES, opening: str = GREETING, **kw: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "tenant_id": str(uuid.uuid4()),
        "agent_id": str(uuid.uuid4()),
        "name": "Sunrise Clinic receptionist",
        "direction": "both",
        "system_prompt": _script(opening),
        "opening_line": notices,
    }
    return AgentConfig(**{**base, **kw})


def _thinnest() -> FakeEngine:
    return FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)


# --- reading the opening line out of a script -----------------------------------------


def test_the_opening_line_is_read_back_from_the_compiled_script() -> None:
    assert opening_line_of(_script()) == GREETING
    assert opening_line_of(_script("")) == ""
    assert opening_line_of(None) == ""
    # A free-text script without the section has no opening line of its own.
    assert opening_line_of("[IDENTITY] You are the receptionist.") == ""


def test_the_opening_section_ends_at_the_next_section_wherever_it_sits() -> None:
    body = (
        "[IDENTITY] Receptionist.\n[T0 FACTS]\nOpen 9 to 6.\n[OPENING]\nHello there.\n[FAQ]\nQ: x"
    )
    assert opening_line_of(body) == "Hello there."


# --- what a caller hears first --------------------------------------------------------


@pytest.mark.parametrize(
    ("notices", "opening", "expected"),
    [
        (NOTICES, GREETING, f"{NOTICES} {GREETING}"),
        ("", GREETING, GREETING),  # both switches off: the greeting still opens the call
        (NOTICES, "", NOTICES),
        ("", "", ""),
    ],
)
def test_first_words_are_the_notices_then_the_opening_line(
    notices: str, opening: str, expected: str
) -> None:
    assert join_first_words(notices, opening) == expected
    assert compose_first_utterance(_config(notices=notices, opening=opening)) == expected


def test_switching_both_notices_off_never_touches_the_truthful_answer() -> None:
    prompt = compose_engine_prompt(_config(notices=""))
    assert TRUTHFUL_ANSWER_MARKER in prompt


def test_the_notice_templates_carry_no_greeting_word() -> None:
    """A greeting word in a notice made it read as the greeting and doubled the hello."""
    for template in AI_DISCLOSURE_TEMPLATES.values():
        lowered = template.lower()
        assert not lowered.startswith(("namaskaram", "namaste", "hello")), template
        assert "AI assistant" in template


# --- ThinnestAI: one greeting field holds the whole first words -----------------------


async def _created_greeting(cfg: AgentConfig) -> str:
    handler, seen = _recorder(
        {
            ("GET", "/agents"): httpx.Response(200, json={"items": [], "nextCursor": None}),
            ("POST", "/agents"): httpx.Response(201, json={"id": "ag_1"}),
        }
    )
    await _engine(handler).create_agent(cfg)
    return str(_body(_agent_write(seen))["greeting"])


async def test_the_engine_greeting_is_the_notices_then_the_opening_line() -> None:
    cfg = _cfg(system_prompt=_script(), opening_line=NOTICES)
    assert await _created_greeting(cfg) == f"{NOTICES} {GREETING}"


async def test_with_both_notices_off_the_engine_still_greets_with_the_opening_line() -> None:
    cfg = _cfg(system_prompt=_script(), opening_line="")
    assert await _created_greeting(cfg) == GREETING


async def test_an_outbound_purpose_fills_the_opening_lines_variables() -> None:
    held = "Namaskaram {{lead_name}}, Sunrise Clinic nundi call chestunnanu."

    async def dial(ctx: CallContext) -> str:
        handler, seen = _recorder(
            {
                ("GET", "/agents/ag_1"): httpx.Response(200, json={"id": "ag_1", "greeting": held}),
                ("POST", "/calls"): httpx.Response(202, json={"id": "out_1", "status": "ringing"}),
            }
        )
        await _engine(handler).start_outbound_call("ag_1", "+919876543210", ctx)
        return str(_body(seen[-1])["purpose"])

    assert await dial(CallContext(lead_name="Asha")) == (
        "Namaskaram Asha, Sunrise Clinic nundi call chestunnanu."
    )
    # Unfilled: the braces are never spoken and the gap they leave is closed.
    assert await dial(CallContext()) == "Namaskaram, Sunrise Clinic nundi call chestunnanu."


# --- the publish limits measure what the engine will speak ----------------------------


def test_an_outbound_agent_with_notices_off_but_an_opening_line_publishes() -> None:
    refuse_over_engine_limits(_thinnest(), _config(notices="", direction="outbound"))


def test_the_refusal_asks_for_an_opening_line_not_for_a_notice() -> None:
    with pytest.raises(ProblemError) as caught:
        refuse_over_engine_limits(
            _thinnest(), _config(notices="", opening="", direction="outbound")
        )
    problem = caught.value
    assert problem.code == OPENING_REQUIRED
    text = f"{problem.title} {problem.detail} {problem.remediation}"
    assert "opening line" in (problem.remediation or "")
    assert "Switch on" not in text and "switched off" not in text


def test_the_length_ceiling_counts_the_notices_and_the_opening_line_together() -> None:
    opening = "a" * (200 - len(NOTICES))  # with the joining space, one over
    with pytest.raises(ProblemError) as caught:
        refuse_over_engine_limits(_thinnest(), _config(opening=opening, direction="inbound"))
    assert caught.value.code == OPENING_TOO_LONG
    assert "script" in (caught.value.remediation or "")
    refuse_over_engine_limits(_thinnest(), _config(opening=opening[1:], direction="inbound"))


def test_an_engine_whose_model_greets_holds_the_notices_alone() -> None:
    """The owned runtime speaks the notices and the model then greets from [OPENING]."""
    cfg = _config()
    words = {"notices": cfg.opening_line, "first_words": compose_first_utterance(cfg)}
    assert engine_greeting(FakeEngine(), **words) == NOTICES
    assert engine_greeting(_thinnest(), **words) == f"{NOTICES} {GREETING}"


# --- the read-back compares against the same first words ------------------------------


def _snapshot(cfg: AgentConfig, greeting: str) -> AgentSnapshot:
    return AgentSnapshot(
        engine_agent_ref="ag_1",
        system_prompt=compose_engine_prompt(cfg),
        system_prompt_readable=True,
        greeting=greeting,
        greeting_readable=True,
    )


def test_an_engine_still_holding_only_the_notices_is_not_applied() -> None:
    cfg = _config()
    engine = _thinnest()
    assert judge(engine, cfg, _snapshot(cfg, f"{NOTICES} {GREETING}")).disclosure_applied is True
    assert judge(engine, cfg, _snapshot(cfg, NOTICES)).disclosure_applied is False


def test_with_both_notices_off_the_engine_must_hold_the_opening_line() -> None:
    cfg = _config(notices="")
    engine = _thinnest()
    assert judge(engine, cfg, _snapshot(cfg, GREETING)).disclosure_applied is True
    assert judge(engine, cfg, _snapshot(cfg, "")).disclosure_applied is False


# --- the client is shown both halves --------------------------------------------------


def test_the_roster_serves_the_notices_the_opening_line_and_the_first_words() -> None:
    row = (
        uuid.uuid4(),  # 0 id
        "Receptionist",
        "inbound",
        "draft",
        "te-IN",
        NOTICES,  # 5 legacy bundle
        "fake",
        None,
        None,  # 8 extraction fields
        "Idi Sunrise Clinic AI assistant.",  # 9
        False,  # 10 AI notice off
        "Ee call record avutundi.",  # 11
        False,  # 12 recording notice off
        None,  # 13 archived_at
        0,  # 14 numbers
        None,  # 15 agent model
        None,  # 16 account model
        "I keep a short note.",  # 17
        False,  # 18 memory off
        None,  # 19 engine voice
        None,  # 20 engine model
        _script(),  # 21 applied script body
    )
    out = agent_out(row)
    assert out.opening_line == ""
    assert out.script_opening_line == GREETING
    assert out.first_words == GREETING
