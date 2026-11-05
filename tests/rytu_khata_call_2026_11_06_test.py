"""The founder's Rytu Khata test call of 6 Nov 2026, 04:33 IST (agent Varsha, placed, 3:01).

1. The caller said "give me a minute, I'll do it" while installing the app, and was asked
   "are you there?" about every 11 s, twice. That question is the engine's own nudge
   (`voice.nudgeAfterSeconds`, `nudgePhrase`), not the model: Calevate sent 8 s and no phrase.
   The wait is now the console's `thinnest_nudge_after_seconds` (default 15, floor 10), and an
   agent of one language asks in the founder's words from `spoken_lines.json`.
2. The caller spoke over "Android or iPhone?" and the next turn asked it word for word; asked
   "how do I use it?", the agent said its explanation of the app again.
3. To "which app? I don't remember", the next turn opened with a greeting word.

Transcript lines are quoted from the call as the founder pasted it.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents.call_handling import CallSettings, platform_settings, resolve_settings
from apps.api.agents.call_handling_routes import _bounds
from apps.api.agents.service import _call_settings_fields
from apps.api.agents.turn_checks import opened_again
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.ops.config_service import validated_value
from calevate_shared import spoken_lines
from calevate_shared.engine import (
    OPENING_CONTINUES_RULE,
    VOICE_STYLE_GUIDANCE,
    compose_engine_prompt,
)
from calevate_shared.spoken_guard import opens_with_greeting
from tests.agent_call_rules_test import _cfg

# --- 1. "are you there?" while the caller does what was asked ------------------------------


def test_the_still_there_wait_is_a_console_value_of_at_least_ten_seconds() -> None:
    assert get_settings().thinnest_nudge_after_seconds == 15
    assert validated_value("thinnest_nudge_after_seconds", 10) == 10
    for bad in (8, 9, 181):
        with pytest.raises(ProblemError):
            validated_value("thinnest_nudge_after_seconds", bad)
    assert applies_rule("thinnest_nudge_after_seconds").applies == LIVE_AGENTS


def test_every_agent_without_its_own_wait_follows_the_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_nudge_after_seconds", 25)
    assert platform_settings().nudge_after_seconds == 25
    resolved = resolve_settings(CallSettings(), CallSettings())
    assert (resolved.values.nudge_after_seconds, resolved.sources["nudge_after_seconds"]) == (
        25,
        "platform",
    )
    empty: Any = {}
    assert _call_settings_fields(empty, languages=("te-IN",))["nudge_after_seconds"] == 25
    assert _bounds().platform_nudge_after_seconds == 25
    # The account's and the agent's own still win, and 0 is still "never ask".
    account = resolve_settings(CallSettings(), CallSettings(nudge_after_seconds=40))
    assert (account.values.nudge_after_seconds, account.sources["nudge_after_seconds"]) == (
        40,
        "organization",
    )
    assert (
        resolve_settings(CallSettings(nudge_after_seconds=0), CallSettings()).values
    ).nudge_after_seconds == 0
    row: Any = {"call_settings": CallSettings(nudge_after_seconds=0)}
    assert _call_settings_fields(row, languages=("te-IN",))["nudge_after_seconds"] is None


def test_a_telugu_agent_asks_in_the_founders_words() -> None:
    line = spoken_lines.lines("on_the_line")["te-IN"]
    assert spoken_lines.in_own_script(line, "te-IN")
    assert spoken_lines.review("on_the_line") == "needs_native_review"
    empty: Any = {}
    assert _call_settings_fields(empty, languages=("te-IN",))["nudge_phrase"] == line


def test_the_platforms_question_stays_where_ours_would_be_wrong() -> None:
    empty: Any = {}
    # One question per agent, said whatever the caller speaks: an agent of several languages
    # keeps the engine's own, which is asked in the caller's language.
    assert _call_settings_fields(empty, languages=("te-IN", "en-IN"))["nudge_phrase"] is None
    # A language the founder has written no line for.
    assert _call_settings_fields(empty, languages=("hi-IN",))["nudge_phrase"] is None
    # The owner's own question wins.
    own: Any = {"call_settings": CallSettings(nudge_phrase="Hello?")}
    assert _call_settings_fields(own, languages=("te-IN",))["nudge_phrase"] == "Hello?"


# --- 2. the same words after being talked over, the same explanation for "how?" ------------


def test_a_line_the_caller_spoke_over_comes_back_in_new_words() -> None:
    """Turn 12 asked turn 10's "మీది ఆండ్రాయిడ్ ఫోనా లేక ఐఫోనా అండి?" word for word after the
    caller spoke over it."""
    rule = "Talked over or too fast? Stop, answer, sorry once, no promise, go on shorter, in new"
    assert f"{rule} words." in VOICE_STYLE_GUIDANCE
    cfg, _ = _cfg()
    assert "go on shorter, in new words." in compose_engine_prompt(cfg)


def test_a_how_question_is_answered_rather_than_the_last_point_repeated() -> None:
    cfg, _ = _cfg()
    prompt = compose_engine_prompt(cfg)
    assert "Lead with the answer to it, never your last point again" in prompt


# --- 3. a greeting word in a later turn ------------------------------------------------------

#: Turn 2, the opening the engine said, turn 3, the caller's reply, and turn 4.
OPENING = (
    "నమస్కారం గారు, నా పేరు వర్ష, రైతు ఖాతా నుండి. మీరు మన యాప్ లో రిజిస్టర్ అయ్యారు, మీకు "
    "ఏమైనా హెల్ప్ కావాలా అని కాల్ చేశాను. ఇప్పుడు మాట్లాడటానికి వీలుగా ఉందా అండి?"
)
CALLER = "చెప్పండి, ఏ యాప్ నాకేం గుర్తులేదు దేంట్లో రీసెర్చ్ చేశాను నేను?"
GREETED_AGAIN = (
    "నమస్కారం అండి, మీరు రైతు ఖాతా యాప్ లో రిజిస్టర్ అయ్యారు. ఇది మీ సాగు పనులు, కూలీల ఖర్చులు "
    "రాసి పెట్టుకునే యాప్ అండి, దీని గురించి మీకు గుర్తుందా అండి?"
)


def test_the_second_greeting_is_the_one_the_call_page_reports() -> None:
    """The opening greets, the caller answers, and the agent's next turn greets again without
    starting over: the "greeted again" detector catches that shape."""
    assert opens_with_greeting(OPENING)
    assert not opens_with_greeting(CALLER)
    assert opened_again(GREETED_AGAIN) is not None


def test_a_placed_call_is_told_its_first_turn_was_its_only_greeting() -> None:
    inbound, _ = _cfg()
    placed = inbound.model_copy(update={"direction": "outbound"})
    prompt = compose_engine_prompt(placed)
    assert OPENING_CONTINUES_RULE in prompt
    assert "Never greet again in any turn" in OPENING_CONTINUES_RULE
    # An answering agent is told the same about its own first words.
    assert OPENING_CONTINUES_RULE in compose_engine_prompt(inbound)
