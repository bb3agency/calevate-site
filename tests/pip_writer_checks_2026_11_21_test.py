"""What Pip's script writer sends back, held to the Varsha calls of 20-21 Nov 2026.

The in-call model copies a script's spoken lines nearly word for word, so the robotic habits
on those calls came from the script: nearly every reply opened with a stock reaction, and the
first step greeted the person again and asked whether they could talk straight after the
opening had asked. The Telugu here is built from the founder's word lists
(`call_words.json`) and from code points, never typed.
"""

from __future__ import annotations

import pytest
from apps.api.agents.call_rules import (
    SCRIPT_FLOW_RULE,
    opening_redone_line_problems,
    said_line_problem,
)
from apps.api.agents.mistake_lints import mistake_findings
from apps.api.agents.script_lint import CapabilityManifest, LintContext
from apps.api.agents.turn_checks import reaction_lead
from apps.workers import script_assist
from apps.workers.script_assist import UnusableAnswerError
from calevate_shared.call_script import CallScript, ConversationStage
from calevate_shared.call_words import say, table
from calevate_shared.spoken_guard import has_indic_letters, honorific_count

TE = "te-IN"
OUTBOUND = LintContext(manifest=CapabilityManifest(direction="outbound"))

#: A Telugu reaction from the founder's acknowledgement list, with no honorific in it.
REACTION = next(
    word
    for word in table("turn_checks.stall_words")["te"]["acknowledgements"]
    if has_indic_letters(word) and honorific_count(word) == 0
)
#: "now" and "tell me", by code point.
NOW = "".join(map(chr, (0x0C07, 0x0C2A, 0x0C4D, 0x0C2A, 0x0C41, 0x0C21, 0x0C41)))
TELL = "".join(map(chr, (0x0C1A, 0x0C46, 0x0C2A, 0x0C4D, 0x0C2A, 0x0C02, 0x0C21, 0x0C3F)))
#: A Telugu greeting and a Telugu "can we talk now?" from the founder's lists.
GREETING = say("spoken_guard._GREETING_HEAD.greetings").split("|")[0]
SUITS = next(
    alt
    for alt in say("turn_checks._ASKS_IF_NOW_SUITS").split("|")
    if has_indic_letters(alt) and not set(alt) & set("()[]?*+\\|")
)

REACTED = f"{REACTION}. {NOW} {TELL}?"
PLAIN = f"{NOW} {TELL}?"
OPENING = f"{GREETING} {{{{lead_name}}}}, {NOW} {SUITS}?"


def _stage(sid: str, sounds_like: str) -> ConversationStage:
    return ConversationStage(
        id=sid, name=sid, instruction="Ask which phone they use.", sounds_like=sounds_like
    )


def _script(*lines: str, opening: str = OPENING) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=opening,
        stages=[_stage(f"s{i}", line) for i, line in enumerate(lines)],
    )


# --- 1. a line that opens with a reaction ---------------------------------------------------


def test_the_writer_is_told_what_it_is_sent_back_for() -> None:
    assert "no spoken line opens with a reaction" in SCRIPT_FLOW_RULE
    assert "neither greets nor asks again whether they can talk" in SCRIPT_FLOW_RULE


def test_a_line_that_opens_with_a_reaction_is_sent_back() -> None:
    """FAILS IF: a written line may open with a stock reaction before its point, which the
    agent then copies into every reply."""
    problem = said_line_problem("stages.0.sounds_like", REACTED)
    assert problem is not None
    assert problem.startswith("stages.0.sounds_like: opens with the reaction")
    assert said_line_problem("stages.0.sounds_like", PLAIN) is None
    english = said_line_problem("style.sample_phrases.0", "Very good. Which phone do you use?")
    assert english is not None and '"very good"' in english
    assert said_line_problem("x", "Great, shall we open the app now?") is not None


@pytest.mark.parametrize(
    "line",
    [
        # Only a reaction: the stalled-step check's, not this one's.
        "OK, no problem.",
        # An address, not a reaction.
        "Sir, which phone do you use?",
        # A close: thanks before the goodbye is the turn.
        "Thank you, goodbye.",
        # A reaction word that is part of the line's own content.
        "Good morning, which phone do you use?",
        "Which phone do you use? OK.",
    ],
)
def test_a_line_that_does_not_lead_with_a_reaction_is_kept(line: str) -> None:
    assert reaction_lead(line) is None
    assert said_line_problem("x", line) is None


def test_the_close_may_thank_before_it_goes_on() -> None:
    assert said_line_problem("stages.2.sounds_like", "Thank you, our team will help.") is not None
    assert (
        said_line_problem("stages.2.sounds_like", "Thank you, our team will help.", close=True)
        is None
    )


# --- 2. a step's line that redoes the opening -----------------------------------------------


def test_a_step_line_that_greets_and_asks_again_is_sent_back() -> None:
    """FAILS IF: the first step's line may greet the person and ask whether they can talk,
    straight after the opening asked (21 Nov 2026, 10:14)."""
    script = _script(f"{GREETING} {{{{lead_name}}}}, {NOW} {SUITS}?", PLAIN)
    problems = opening_redone_line_problems(script)
    assert problems == [
        "stages.0.sounds_like: greets again or asks again whether now is a good time, which "
        "the opening line already did; start this step from what comes after their yes."
    ]
    # Asking again without greeting is the same mistake.
    assert opening_redone_line_problems(_script(f"{NOW} {SUITS}?"))
    # In English too, by the opening's own question.
    english = _script(
        "Can you talk now for two minutes?",
        opening="Hello {{lead_name}}, calling from Rytu Khata about the app. Can you talk now?",
    )
    assert opening_redone_line_problems(english)


def test_a_step_line_that_goes_on_from_the_opening_is_kept() -> None:
    assert opening_redone_line_problems(_script(PLAIN)) == []
    # With no opening line there is nothing for the step to redo.
    assert opening_redone_line_problems(_script(f"{GREETING}, {PLAIN}", opening="")) == []


def test_the_writer_and_the_healer_both_read_the_line_check() -> None:
    script = _script(f"{GREETING} {{{{lead_name}}}}, {NOW} {SUITS}?", PLAIN)
    written = script_assist.language_problems(script, TE, lint=OUTBOUND)
    assert any(p.startswith("stages.0.sounds_like: greets again") for p in written)
    # An edit that kept the owner's line as it was is not sent back for it.
    kept = script_assist.language_problems(script, TE, before=script, lint=OUTBOUND)
    assert not any("greets again" in p for p in kept)
    found = mistake_findings(script, OUTBOUND, "opened_again")
    assert any(p.startswith("stages.0.sounds_like: greets again") for p in found)


# --- the full write judges every line -------------------------------------------------------


def test_a_full_write_judges_lines_copied_from_the_current_script() -> None:
    """FAILS IF: a whole new script skips a line because the current script already held it.
    Only an edit (`before=`) leaves the owner's lines alone; a full write is all Pip's."""
    current = _script(REACTED, PLAIN, REACTED)
    written = script_assist.language_problems(current, TE)
    assert any(p.startswith("stages.0.sounds_like: opens with the reaction") for p in written)
    # The close may thank before it goes on.
    assert not any(p.startswith("stages.2.sounds_like: opens with") for p in written)
    edited = script_assist.language_problems(current, TE, before=current)
    assert not any("opens with the reaction" in p for p in edited)


def test_a_full_draft_is_refused_for_a_copied_reaction_line() -> None:
    raw = {
        "identity": "Helps farmers set up the app.",
        "goal": "Help them set up the app.",
        "opening_line": OPENING,
        "stages": [
            {"name": "Phone", "instruction": "Ask which phone they use.", "sounds_like": REACTED},
            {"name": "Close", "instruction": "Thank them and end the call.", "sounds_like": PLAIN},
        ],
    }
    with pytest.raises(UnusableAnswerError) as refused:
        script_assist.drafted_script(raw, language=TE)
    assert "stages.0.sounds_like: opens with the reaction" in refused.value.problems
