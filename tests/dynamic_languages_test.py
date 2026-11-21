"""No consumer assumes the client speaks Telugu, Hindi or English.

The server already knows which languages an account may use
(`agents/languages.client_language_tags`). These tests hold the consumers to it: the
platform's starting language is a console setting (Telugu by default, so nothing changes
for an existing account), Pip's language choices accept a staged language switched on for
the account, the core `language` lead field names the agent's own languages, the short
privacy notice offers exactly the languages its lines exist in, and WhatsApp templates may
be written in any of the account's languages.

Run: uv run pytest -q tests/dynamic_languages_test.py
"""

from __future__ import annotations

from datetime import date

import pytest
from apps.api.agents import languages
from apps.api.agents.languages import (
    StagedLanguageReadiness,
    assert_default_language_offered,
    client_language_tags,
    default_extra_languages,
    default_primary_language,
    default_reply_languages,
    platform_default_language,
)
from apps.api.agents.starters import starter_opening
from apps.api.compliance import privacy_notice
from apps.api.copilot.actions import WriteRefusedError, parse_args
from apps.api.copilot.agent_actions import AGENT_CREATE, _AgentCreateArgs
from apps.api.core import platform_config as pc
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.ops import config_controls as controls
from apps.api.whatsapp.templates import client_template_languages
from calevate_shared.extraction import (
    CALLER_LANGUAGE_REASON,
    ExtractionSchemaSpec,
    build_extraction_prompt,
    caller_language_reason,
)
from calevate_shared.languages import offered_language_tags
from calevate_shared.lead_fields import CORE_LEAD_FIELDS

TAMIL = "ta-IN"
READY = StagedLanguageReadiness(
    sentences_reviewed_by="A native speaker",
    sentences_reviewed_on=date(2026, 10, 24),
    test_call_checked_on=date(2026, 10, 25),
    engine_confirmation="ThinnestAI reply of 25 Oct 2026",
    tag=TAMIL,
)


@pytest.fixture
def tamil_for_everyone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tamil switched on and its readiness complete, its data files as a reviewer would
    leave them."""
    monkeypatch.setattr(languages, "opt_out_phrases_recorded", lambda tag: True)
    monkeypatch.setattr(languages, "privacy_notice_recorded", lambda tag: True)
    monkeypatch.setitem(languages.STAGED_LANGUAGE_READINESS, TAMIL, READY)  # type: ignore[arg-type]
    monkeypatch.setattr(get_settings(), "staged_agent_languages_enabled", TAMIL)


# --------------------------------------------------------- the platform starting language


def test_the_default_changes_nothing_for_an_existing_account() -> None:
    assert get_settings().default_agent_language == "te-IN"
    assert client_language_tags() == offered_language_tags()
    assert platform_default_language() == "te-IN"
    assert default_primary_language(None) == "te-IN"
    assert default_reply_languages() == ("te-IN", "en-IN")
    assert default_extra_languages("te-IN") == ["en-IN"]
    assert default_extra_languages("hi-IN") == ["te-IN", "en-IN"]


def test_a_new_starting_language_leads_every_list_and_every_new_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "default_agent_language", "hi-IN")
    assert client_language_tags() == ("hi-IN", "te-IN", "en-IN")
    assert default_primary_language(None) == "hi-IN"
    assert default_primary_language(["en-IN"]) == "en-IN", "the business's own wins"
    assert default_extra_languages("hi-IN") == ["en-IN"]
    assert default_extra_languages("en-IN") == ["hi-IN"]


@pytest.mark.usefixtures("tamil_for_everyone")
def test_a_switched_on_staged_language_can_be_the_starting_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "default_agent_language", TAMIL)
    assert client_language_tags()[0] == TAMIL
    assert platform_default_language() == TAMIL
    assert_default_language_offered(TAMIL)


def test_a_starting_language_the_account_may_not_choose_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set while Tamil was on, then Tamil switched off: the account starts in the first
    language it may choose rather than in one it would be refused at publish."""
    monkeypatch.setattr(get_settings(), "default_agent_language", TAMIL)
    assert TAMIL not in client_language_tags()
    assert platform_default_language() == "te-IN"


def test_the_console_refuses_a_starting_language_not_offered_to_everyone() -> None:
    with pytest.raises(ProblemError) as refused:
        assert_default_language_offered(TAMIL)
    assert refused.value.code == "default_agent_language_not_offered"
    assert_default_language_offered("en-IN")


def test_the_console_offers_every_language_every_client_has() -> None:
    field = next(f for f in pc.describe(get_settings()) if f.key == "default_agent_language")
    assert controls.control_for(field).kind == "select"
    assert [c.value for c in controls.choices_for(field)] == list(offered_language_tags())


def test_a_ready_made_opening_follows_the_starting_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telugu = starter_opening(None, "answer_calls", business="Acme")
    assert telugu == starter_opening(None, "answer_calls", business="Acme", language="te-IN")
    monkeypatch.setattr(get_settings(), "default_agent_language", "en-IN")
    assert starter_opening(None, "answer_calls", business="Acme") == starter_opening(
        None, "answer_calls", business="Acme", language="en-IN"
    )


# --------------------------------------------------------------------------- Pip


def test_pip_may_choose_any_built_language_and_the_account_decides() -> None:
    """The tool list is the same bytes for every caller, so it names every built language;
    the account's own set is enforced when the card is planned, with a sentence naming it."""
    prop = AGENT_CREATE.schema["function"]["parameters"]["properties"]["language_primary"]
    assert TAMIL in prop["enum"]
    with pytest.raises(WriteRefusedError) as refused:
        parse_args(
            _AgentCreateArgs,
            {"name": "Reception", "direction": "inbound", "language_primary": TAMIL},
        )
    assert "Tamil" in str(refused.value)
    assert "te-IN (Telugu)" in str(refused.value)


@pytest.mark.usefixtures("tamil_for_everyone")
def test_pip_can_create_an_agent_in_a_switched_on_staged_language() -> None:
    parsed = parse_args(
        _AgentCreateArgs, {"name": "Reception", "direction": "inbound", "language_primary": TAMIL}
    )
    assert parsed.language_primary == TAMIL


# ------------------------------------------------------------ the core language field


def test_the_core_language_field_names_no_language_of_its_own() -> None:
    field = next(f for f in CORE_LEAD_FIELDS if f.key == "language")
    assert field.reason == CALLER_LANGUAGE_REASON
    for name in ("Telugu", "Hindi", "Tamil"):
        assert name not in field.reason


def test_the_extraction_prompt_names_the_agents_own_languages() -> None:
    spec = ExtractionSchemaSpec(fields=list(CORE_LEAD_FIELDS))
    tamil = build_extraction_prompt(spec, "Agent: Vanakkam.", languages=["ta-IN"])
    assert caller_language_reason(["ta-IN"]) in tamil
    assert "(such as Tamil, English)" in tamil
    assert "such as Telugu" not in tamil
    telugu = build_extraction_prompt(spec, "Agent: Namaskaram.", languages=["te-IN", "en-IN"])
    assert "(such as Telugu, English)" in telugu
    assert "(such as Telugu, English)" in caller_language_reason(())


# ---------------------------------------------------------------- the privacy notice


def test_the_short_notice_offers_exactly_the_languages_its_lines_exist_in() -> None:
    assert privacy_notice.NOTICE_LANGUAGES == ("en", "te", "hi")
    assert privacy_notice.has_notice_lines("te-IN")
    assert not privacy_notice.has_notice_lines(TAMIL)
    assert privacy_notice.notice_language_name("hi") == "Hindi"


def test_the_disclaimer_names_the_machine_drafted_language() -> None:
    assert privacy_notice.disclaimer("en") == (
        "DRAFT — not legal advice. Generated from your own settings. Have your advocate check "
        "it before you use it. Anything in double braces is a blank only you can fill."
    )
    assert privacy_notice.disclaimer("te") == (
        "DRAFT — not legal advice. This Telugu wording was machine-drafted: have a native "
        "speaker and your advocate check it before you use it. Anything in double braces is "
        "a blank only you can fill."
    )


# -------------------------------------------------------------------- WhatsApp


def test_whatsapp_templates_follow_the_accounts_languages() -> None:
    assert client_template_languages() == ("te", "hi", "en", "en_US", "en_GB", "en_IN")


@pytest.mark.usefixtures("tamil_for_everyone")
def test_a_switched_on_language_can_be_a_template_language() -> None:
    assert "ta" in client_template_languages()
