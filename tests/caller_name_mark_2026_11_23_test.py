"""The caller's name field in a script reaches the model as a mark (founder's Rytu Khata call
of 23 Nov 2026: with no name on the list, "నమస్కారం {{lead_name}} గారు" was said as
"నమస్కారం గారు")."""

from __future__ import annotations

import pytest
from apps.api.agents.live_apply import platform_prompt_revision
from calevate_shared import engine
from calevate_shared.engine import (
    CALLER_NAME_MARK,
    AgentConfig,
    compose_engine_prompt,
    mark_caller_name,
)


def test_the_name_field_and_its_title_become_one_mark() -> None:
    assert mark_caller_name("నమస్కారం {{lead_name}} గారు, ఎలా ఉన్నారు?") == (
        f"నమస్కారం {CALLER_NAME_MARK}, ఎలా ఉన్నారు?"
    )
    assert mark_caller_name("Hello {{ lead_name }} ji, this is Varsha.") == (
        f"Hello {CALLER_NAME_MARK}, this is Varsha."
    )
    assert mark_caller_name("Name: {{lead_name}}") == "Name: {{lead_name}}"
    assert mark_caller_name("From {{business_name}}.") == "From {{business_name}}."


def _cfg(script: str) -> AgentConfig:
    return AgentConfig.model_validate(
        {
            "tenant_id": "t",
            "agent_id": "a",
            "name": "A",
            "business": "B",
            "direction": "outbound",
            "language_primary": "te-IN",
            "system_prompt": script,
            "opening_line": "",
            "call_is_recorded": True,
        }
    )


def test_the_composed_prompt_carries_the_mark_in_place_of_the_name_and_title() -> None:
    prompt = compose_engine_prompt(_cfg("Step 1: say నమస్కారం {{lead_name}} గారు, then why."))
    assert f"నమస్కారం {CALLER_NAME_MARK}, then why." in prompt
    assert "{{lead_name}} గారు" not in prompt


def test_the_publish_read_back_looks_for_the_script_as_it_was_sent() -> None:
    """The read-back asks whether the engine holds `fenced_script(...)`; with the mark applied
    on the way out only, every script greeting by name and title failed it ("script did
    not read back as sent", 23 Nov 2026)."""
    from calevate_shared.engine import fenced_script
    from calevate_shared.invisible_text import plain_joins

    cfg = _cfg("Step 1: say నమస్కారం {{lead_name}} గారు, then why.")
    assert plain_joins(fenced_script(cfg.system_prompt)) in plain_joins(compose_engine_prompt(cfg))


@pytest.mark.parametrize(
    "name", ["CALLER_NAME_MARK", "TEST_CALL_OPENING_RULE", "PLACED_CALL_OPENING_RULE"]
)
def test_a_change_to_the_mark_or_an_opening_rule_republishes_every_live_agent(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The platform walk at worker start is keyed on this revision: a mark or rule that only
    a script with an opening and a name field shows must move it too, or live agents keep the
    old text until each is republished."""
    before = platform_prompt_revision()
    monkeypatch.setattr(engine, name, getattr(engine, name) + " x")
    assert platform_prompt_revision() != before
