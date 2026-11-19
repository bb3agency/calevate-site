"""`whatsapp.caller_locale`: one caller's language, among the languages a template is
approved in, else the platform locale."""

from __future__ import annotations

import pytest
from apps.api.core.settings import get_settings
from apps.api.whatsapp.caller_locale import caller_locale, language_head

APPROVED = ("en", "hi", "te")


@pytest.fixture(autouse=True)
def _platform_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "whatsapp_template_locale", "en_IN")


@pytest.mark.parametrize(
    ("call_language", "agent_language", "expected"),
    [
        ("hi-IN", "te-IN", "hi"),  # the call's language wins over the agent's
        (None, "te-IN", "te"),  # no language read on the call: the agent's
        ("", "hi-IN", "hi"),
        ("ta-IN", "te-IN", "en_IN"),  # the caller's language is unapproved: platform
        (None, "kn-IN", "en_IN"),
        (None, None, "en_IN"),
    ],
)
def test_the_callers_language_among_the_approved_ones(
    call_language: str | None, agent_language: str | None, expected: str
) -> None:
    assert (
        caller_locale(APPROVED, call_language=call_language, agent_language=agent_language)
        == expected
    )


def test_a_template_approved_in_english_only_never_names_another_language() -> None:
    assert caller_locale(("en",), call_language="te-IN", agent_language="te-IN") == "en_IN"
    assert caller_locale(("en",), call_language="en-IN", agent_language="te-IN") == "en"


@pytest.mark.parametrize(
    ("tag", "head"), [("te-IN", "te"), ("en_US", "en"), ("HI", "hi"), (None, ""), ("", "")]
)
def test_language_head(tag: str | None, head: str) -> None:
    assert language_head(tag) == head
