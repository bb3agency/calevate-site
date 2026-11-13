"""D-988 (founder, 13 Nov 2026): a call leaves the language the agent greeted in only when the
caller asks or speaks two full sentences running in another. On the Varsha call of 13 Nov
2026 (11:30) "Ah, tell me." from a Telugu caller turned the agent English. The Telugu lines
below are the agent's own words from that call's transcript."""

from __future__ import annotations

from apps.api.agents.call_mistakes import mistakes_in
from apps.api.agents.turn_checks import ENGLISH_SWITCH_LINES, english_run
from calevate_shared.engine import VOICE_STYLE_GUIDANCE
from tests.call_mistakes_test import _call

GREETING = "నమస్కారం అండి, రైతు ఖాతా నుంచి మాట్లాడుతున్నాను, ఇప్పుడు మాట్లాడటానికి వీలు పడుతుందా అండి?"
TELUGU_REPLY = "తప్పకుండా అండి."


def test_one_short_english_reply_does_not_move_the_call_to_english() -> None:
    call = _call(
        ("agent", GREETING),
        ("caller", "Ah, tell me."),
        (
            "agent",
            "We have spoken before, regarding the app. Would you like to continue with "
            "the installation?",
        ),
    )
    assert "wrong_language" in mistakes_in(call, language="te-IN")


def test_two_full_english_sentences_running_do() -> None:
    call = _call(
        ("agent", GREETING),
        ("caller", "Ah, tell me what this is about."),
        ("agent", TELUGU_REPLY),
        ("caller", "No, it is not visible on my phone."),
        ("agent", "No problem at all. Is your phone an Android or an iPhone?"),
    )
    assert "wrong_language" not in mistakes_in(call, language="te-IN")


def test_the_run_resets_on_a_line_in_the_agents_language() -> None:
    run = english_run(0, "Ah, tell me what this is about.", "te-IN")
    assert run == 1
    assert english_run(run, "ఏం లేదండి, అన్నీ బానే ఉన్నాయి.", "te-IN") == 0
    assert ENGLISH_SWITCH_LINES == 2


def test_the_in_call_rule_says_the_same() -> None:
    assert "two full sentences running" in VOICE_STYLE_GUIDANCE
    assert "a few words never switch" in VOICE_STYLE_GUIDANCE
