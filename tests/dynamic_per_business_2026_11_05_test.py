"""Nothing hardcoded per business, and no hand-written Indian-language text (audit of 5 Nov 2026,
`docs/evidence/e2e-audit-2026-11-05/6-hardcoded-dynamic.md`, lane D)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.agents import give_callers_time, handoff, starters, test_conversations
from apps.api.agents.business_fit import UNKNOWN, BusinessFit
from apps.api.billing import ai_quota
from apps.api.compliance.call_purpose import ScriptPart, lint, unread_languages
from apps.api.compliance.optout import detect_opt_out
from apps.api.core.settings import get_settings
from apps.api.tenancy.business_copy import STARTER_WORD_KEYS, StarterWords
from apps.api.tenancy.caller_words import CallerWords
from calevate_shared import spoken_lines, spoken_style
from calevate_shared.call_script import ScriptPolicies
from calevate_shared.engine import (
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
)
from calevate_shared.extraction import ExtractionSchemaSpec, build_extraction_prompt
from calevate_shared.lead_fields import CORE_LEAD_FIELDS, with_core
from tests.call_optout_test import _Turn

# --- F-5: words written joined, as native speakers write them -----------------------------

_WRITTEN_FORM = "Write as native speakers do: a suffix, particle or vowel joins its word."


def _cfg(language: str = "te-IN", direction: str = "outbound", **kw: object) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="B",
        direction=direction,
        language_primary=language,
        system_prompt="[TASK FLOW]\nHelp them.",
        opening_line="",
        call_is_recorded=True,
        **kw,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "cfg",
    [
        _cfg("te-IN"),
        _cfg("hi-IN"),
        _cfg("en-IN"),
        _cfg("ta-IN"),
        _cfg("te-IN", caller_has_screen=True),
        _cfg("te-IN", languages_extra=["hi-IN"]),
        _cfg("te-IN", direction="inbound"),
    ],
)
def test_the_written_form_rule_reaches_every_composed_prompt(cfg: AgentConfig) -> None:
    prompt = compose_engine_prompt(cfg)
    assert _WRITTEN_FORM in prompt
    assert _WRITTEN_FORM in dict(engine_prompt_layers(cfg))["how_to_speak"]


def test_the_rule_names_no_language_and_quotes_the_founders_example_only_when_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    how = dict(engine_prompt_layers(_cfg()))["how_to_speak"]
    rule = next(line for line in how.splitlines() if _WRITTEN_FORM in line)
    assert rule.isascii()
    assert "Like:" not in rule

    monkeypatch.setattr(
        "calevate_shared.engine.written_form", lambda tag: "EXAMPLE" if tag == "te-IN" else None
    )
    how = dict(engine_prompt_layers(_cfg()))["how_to_speak"]
    assert 'vowel joins its word. Like: "EXAMPLE"\n' in how
    assert "Like:" not in dict(engine_prompt_layers(_cfg("hi-IN")))["how_to_speak"]


def test_every_language_row_has_an_empty_written_form_slot_for_the_founder() -> None:
    rows = spoken_style._raw()["languages"]
    for tag in spoken_style.languages():
        assert rows[tag]["written_form"] == "", tag
        assert spoken_style.written_form(tag) is None, tag


# --- G1-1 / G1-2: unknown is neutral, and an agent's own switches are its job ------------


def test_an_unjudged_business_reads_neutral_words() -> None:
    unknown = CallerWords()
    assert (unknown.lead, unknown.hot_lead, unknown.hot_leads) == (
        "interested caller",
        "most interested caller",
        "most interested callers",
    )
    assert CallerWords(sells=True).hot_lead == "hot lead"
    assert CallerWords(sells=False, caller_noun="member").hot_leads == "most interested members"


def test_unknown_assumes_nothing_and_an_agents_switch_narrows_the_business() -> None:
    assert not (UNKNOWN.assumes_booking or UNKNOWN.assumes_prices or UNKNOWN.assumes_sale)
    assert not UNKNOWN.assumes_premises and not UNKNOWN.judged
    shop = BusinessFit(
        takes_bookings=True, takes_orders=True, quotes_prices=True, has_premises=True, sells=True
    )
    support = shop.for_agent(ScriptPolicies(take_bookings=False, share_prices=False))
    assert not support.assumes_booking and not support.assumes_prices
    assert shop.for_agent(None) is shop
    # A switch the owner left on asserts it only while the business is unjudged.
    switched = UNKNOWN.for_agent(ScriptPolicies())
    assert switched.assumes_booking and switched.assumes_prices
    judged_no = BusinessFit(
        takes_bookings=False, takes_orders=False, quotes_prices=False, sells=False
    )
    assert not judged_no.for_agent(ScriptPolicies()).assumes_booking


def test_the_copy_names_the_starter_words_and_they_replace_the_trade_row() -> None:
    assert STARTER_WORD_KEYS == ("answer_name", "calling_name", "topics", "capture", "caution")
    words = StarterWords(
        answer_name="App help desk",
        calling_name="New user calls",
        topics="the app, payments or account set-up",
        capture="their name and what they are stuck on",
        caution="Never promise a refund.",
    )
    fit = BusinessFit(sells=False, takes_bookings=False, takes_orders=False, words=words)
    trade = starters.trade_for("retail", fit)
    assert trade.receptionist_name == "App help desk"
    assert trade.caution == "Never promise a refund."
    assert starters.starter_for("retail", "answer_calls", fit).name_suggestion == "App help desk"


# --- G3: no trade example in every call's extraction prompt ------------------------------


def test_the_extraction_prompt_names_no_trade() -> None:
    prompt = build_extraction_prompt(
        ExtractionSchemaSpec(fields=with_core([])), "Caller: hello", languages=("te-IN",)
    )
    lowered = prompt.casefold()
    for word in ("chilli", "kilo", "in stock", "receptionist", "kavali", "cheppandi", "vaddu"):
        assert word not in lowered, word
    # L5-17: "I'll call you" and "we'll talk again" are not a request to be called back.
    assert "true only when the caller asked the BUSINESS to call them" in prompt
    assert '("I\'ll call you")' in prompt
    need = next(f for f in CORE_LEAD_FIELDS if f.key == "need")
    assert need.reason == "What the caller wants or why they called, in a few words of their own."


# --- G4: the founder's lines, read from data --------------------------------------------


def test_the_handover_line_is_in_the_callers_own_letters_or_english() -> None:
    # The romanised drafts are kept for the founder and never spoken.
    assert set(spoken_lines.drafts("handover")) == {"te-IN", "hi-IN"}
    english = spoken_lines.lines("handover")["en-IN"]
    assert handoff.spoken_line_for("te-IN") == english
    assert handoff.spoken_line_for("hi-IN") == english
    assert spoken_lines.in_own_script(handoff.spoken_line_for("ta-IN"), "ta-IN")
    assert not spoken_lines.in_own_script("Sare, konchem wait cheyandi.", "te-IN")


def test_every_moved_entry_records_its_review() -> None:
    for key in spoken_lines.entry_keys():
        assert spoken_lines.review(key) in ("needs_native_review", "native_reviewed"), key
        assert spoken_lines.by_language(key), key


@pytest.mark.parametrize(
    "said", ["Naaku malli call cheyakandi.", "मुझे कॉल मत करो", "Inka call చేయకండి"]
)
def test_the_opt_out_detector_still_hears_telugu_and_hindi(said: str) -> None:
    assert detect_opt_out([_Turn("caller", said)]) is not None


def test_not_now_still_is_not_an_opt_out() -> None:
    assert detect_opt_out([_Turn("caller", "Ippudu call cheyakandi.")]) is None


# --- G5-1: a practice run never tests another language ---------------------------------


def test_a_telugu_agent_gets_no_english_practice_caller() -> None:
    callers = test_conversations.standard_scenarios("te-IN", "outbound", UNKNOWN)
    english = [s.key for s in callers if s.probe is None and all(t.isascii() for t in s.turns)]
    assert english == []
    assert test_conversations.untested_callers("te-IN", "outbound", UNKNOWN)
    assert test_conversations.untested_callers("en-IN", "outbound", UNKNOWN) == []


# --- G5-3: the promo check never says clear about wording it cannot read ----------------


def test_the_promo_check_says_check_for_a_language_it_cannot_read() -> None:
    tamil = "இன்று மட்டும் தள்ளுபடி"
    assert unread_languages(tamil) == ("Tamil",)
    report = lint([ScriptPart("Opening", tamil)])
    assert report.verdict == "check" and report.not_checked_in == ("Tamil",)
    assert lint([ScriptPart("Opening", "Hello, how can I help?")]).verdict == "clear"


# --- G8-1: the extra AI block is the founder's console setting --------------------------


def test_the_extra_ai_block_is_a_console_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ai_quota.ai_overage_block_inr() == Decimal("500.00")
    monkeypatch.setattr(get_settings(), "ai_overage_block_inr", Decimal("750.00"))
    assert ai_quota.ai_overage_block_inr() == Decimal("750.00")


# --- A-12: "Can you see it?" only in the founder's lines --------------------------------


def test_can_you_see_it_is_only_the_founders() -> None:
    assert set(spoken_lines.drafts("still_there")) == {"hi-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN"}
    for language in spoken_lines.drafts("still_there"):
        assert give_callers_time.nudge_phrase_for(language, caller_has_screen=True) == ""


# --- PIP-11: textbook words, whatever their case; prefix matching pinned per language -----


def test_a_textbook_word_is_found_whatever_its_case() -> None:
    from calevate_shared.spoken_guard import textbook_words

    assert textbook_words("Please kindly wait.", "en-IN")
    assert textbook_words("KINDLY wait.", "en-IN")


@pytest.mark.parametrize(
    "tag",
    [t for t in spoken_style.languages() if (st := spoken_style.style_for(t)) and st.word_swaps],
)
def test_a_listed_word_matches_the_start_of_a_longer_word_today(tag: str) -> None:
    """Pinned, not endorsed: whether a listed word should also match the start of a longer,
    inflected word is the founder's decision (PIP-11). This fails the day it changes."""
    from calevate_shared.spoken_guard import textbook_words

    style = spoken_style.style_for(tag)
    assert style is not None
    formal, spoken = style.word_swaps[0]
    assert (formal, spoken) in textbook_words(f"{formal}xyz", tag)
