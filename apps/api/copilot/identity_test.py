"""The assistant's name (D-772): one spelling per language, and never without "an AI"."""

from __future__ import annotations

import re
from pathlib import Path

from apps.api.copilot import admin_prompt, identity, prompt
from apps.api.copilot.identity import ASSISTANT_NAME

_WEB_NAME = Path(__file__).resolve().parents[3] / "apps/web/src/lib/copilot/assistantName.ts"


def test_the_web_app_spells_the_name_the_api_does() -> None:
    """Every web surface reads `ASSISTANT_NAME` from one module; it must be this one's."""
    source = _WEB_NAME.read_text(encoding="utf-8")
    spelled = re.findall(r'export const ASSISTANT_NAME = "([^"]+)";', source)
    assert spelled == [ASSISTANT_NAME]


def test_the_canonical_answer_gives_the_name_and_says_it_is_an_ai() -> None:
    answer = identity.CANONICAL_IDENTITY_ANSWER
    assert answer.startswith(f"I am {ASSISTANT_NAME}, the Calevate assistant — an AI")
    # A name is not a claim to be a person, and a caught vendor answer becomes this text.
    assert not identity.names_a_vendor(answer)


def test_both_ends_of_the_prompt_name_the_assistant_and_say_it_is_an_ai() -> None:
    assert f"You are {ASSISTANT_NAME}, the Calevate assistant. You are an AI" in (
        prompt.ASSISTANT_IDENTITY
    )
    assert f"You are {ASSISTANT_NAME}, the Calevate assistant, and you are an AI" in (
        prompt.CLOSING_RULES
    )


def test_the_admin_prompt_names_it_too() -> None:
    assert f"You are {ASSISTANT_NAME}, the Calevate assistant, and you are an AI" in (
        admin_prompt.ADMIN_CLOSING_RULES
    )
