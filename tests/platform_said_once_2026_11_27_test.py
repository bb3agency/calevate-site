"""Each platform rule is said once (27 Nov 2026): the business line rides only in the engine's
business description, a script's own step lead and ending replace HOW TO SPEAK's versions,
and the placed-call claim rule leaves a step's example turns their weight."""

from __future__ import annotations

from calevate_shared.call_script import (
    BUSINESS_HEADER,
    PROCEDURE_HEADER,
    PROCEDURE_LEAD,
    business_line_of,
)
from calevate_shared.engine import (
    CALL_REASON_RULE,
    CLIENT_SCRIPT_OPEN,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    fenced_script,
)

LINE = "An organic produce shop in Kukatpally."
BODY = f"{BUSINESS_HEADER}\n{LINE}\n\n[GOAL]\nHelp them.\n\n[ENDING]\nThank them and say bye."


def _cfg(body: str) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="Raghava Organics",
        direction="inbound",
        language_primary="te-IN",
        system_prompt=body,
        opening_line="",
        call_is_recorded=True,
    )


def test_the_business_line_is_carried_once_by_the_business_description() -> None:
    assert business_line_of(BODY) == LINE
    assert fenced_script(BODY) == "[GOAL]\nHelp them.\n\n[ENDING]\nThank them and say bye."
    assert compose_engine_prompt(_cfg(BODY)).count(LINE) == 0


def test_a_script_of_only_a_business_line_has_no_fence() -> None:
    prompt = compose_engine_prompt(_cfg(f"{BUSINESS_HEADER}\n{LINE}"))
    assert CLIENT_SCRIPT_OPEN not in prompt


def test_a_script_ending_replaces_the_platform_close() -> None:
    prompt = compose_engine_prompt(_cfg(BODY))
    assert "- Close as [ENDING] says, in one line, no recap, then one goodbye" in prompt
    assert "- Close: what happens next" in compose_engine_prompt(_cfg("[GOAL]\nHelp them."))


def test_a_scripts_step_lead_replaces_the_platform_step_walk() -> None:
    body = f"[GOAL]\nHelp.\n\n{PROCEDURE_HEADER} {PROCEDURE_LEAD}\nInstall: put the app on."
    prompt = compose_engine_prompt(_cfg(body))
    assert prompt.count("One action a turn") == 1
    assert '- Steps: never "done?" or "understood?"; to check, ask what they see.' in prompt
    assert "- Steps? One action a turn" in VOICE_STYLE_GUIDANCE


def test_the_claim_rule_holds_even_against_a_steps_line() -> None:
    assert "even if a step's line says it" in CALL_REASON_RULE
