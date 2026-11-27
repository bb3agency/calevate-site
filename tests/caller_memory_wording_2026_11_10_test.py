"""D-979 (founder, 10 Nov 2026): two in-call rule sentences reworded so an earlier call's
outcome, which the engine hands the model as part of the call's own history (ThinnestAI,
28 Oct 2026, VENDOR-STATED, `docs/vendor/thinnest-replies-2026-10-12.md` §39 item 7), is not
treated as true now (deep audit D3-01, the Varsha call of 10 Nov 2026)."""

from __future__ import annotations

import calevate_shared.engine as engine
import pytest
from apps.api.agents.live_apply import platform_prompt_revision
from apps.api.agents.prompt_size import measure
from apps.api.engine.thinnest import INSTRUCTIONS_MAX_CHARS
from calevate_shared.engine import (
    CALL_REASON_RULE,
    ENGINE_MEMORY_RULE,
    AgentConfig,
    compose_engine_prompt,
)


def _placed_with_memory() -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Varsha",
        business="B",
        direction="outbound",
        language_primary="te-IN",
        system_prompt="[TASK FLOW]\nHelp them.",
        opening_line="Hello, is now a good time?",
        call_is_recorded=True,
        caller_memory_enabled=True,
        caller_memory_in_engine=True,
    )


def test_what_they_said_counts_only_when_said_on_this_call() -> None:
    assert "unless they said so on this call or THIS CALL says so," in CALL_REASON_RULE
    assert "unless they or THIS CALL said so" not in CALL_REASON_RULE


def test_an_earlier_call_is_what_was_talked_about_not_what_is_true_now() -> None:
    assert ENGINE_MEMORY_RULE.endswith(
        "or invent one. It tells you what was talked about then, not what is true now: "
        "ask before saying they did, have or use anything. On a call you place, why you call "
        "comes first."
    )


def test_a_placed_call_with_memory_carries_both_sentences_and_fits_the_box() -> None:
    cfg = _placed_with_memory()
    prompt = compose_engine_prompt(cfg)
    assert CALL_REASON_RULE in prompt and ENGINE_MEMORY_RULE in prompt
    assert measure(cfg, INSTRUCTIONS_MAX_CHARS).total <= INSTRUCTIONS_MAX_CHARS


@pytest.mark.parametrize("name", ["CALL_REASON_RULE", "ENGINE_MEMORY_RULE"])
def test_either_sentence_moves_the_platform_revision(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The revision is what the worker-start platform walk keys on, so a moved revision is
    what brings every live agent onto the new words after a deploy, with no republish."""
    now = platform_prompt_revision()
    monkeypatch.setattr(engine, name, getattr(engine, name) + " x")
    assert platform_prompt_revision() != now


def test_an_earlier_call_is_raised_only_when_the_caller_does_or_it_is_why_we_call() -> None:
    """FAILS IF: the agent may open a call with an earlier conversation the caller did not
    bring up (founder's Varsha call of 13 Nov 2026, 22:27: "we have spoken before")."""
    assert "only when they do, or it is why you call; never open with it" in ENGINE_MEMORY_RULE
