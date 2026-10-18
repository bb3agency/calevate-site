"""An agent's reply checked as speech, by rules, before any AI judge (D-739).

The failing replies are production ones: an outbound call on 11 Oct 2026 that in one turn
asked the same question three times, spoke the caller's line and read out two bracketed
notes, and a Telugu turn in textbook words with two questions joined into one. The passing
replies are what a good agent says, including opening hours and a truthful AI answer, which
the rules must leave alone.
"""

from __future__ import annotations

from apps.api.agents.test_conversations import (
    Turn,
    decide,
    hard_check,
    probe_scenario,
    standard_scenarios,
)
from apps.api.agents.turn_checks import formal_swaps, sentences, turn_problems
from calevate_shared.call_script import (
    ONE_DETAIL_PER_TURN,
    STAGE_DETAIL_MAX,
    CallScript,
    ConversationStage,
    native_steps,
)
from calevate_shared.engine import VOICE_STYLE_GUIDANCE
from calevate_shared.spoken_style import register_guidance, style_for

RAGHAVA_TURN = (
    "మీకు whole chilli కావాలా, chilli powder కావాలా? Whole chilli or chilli powder? "
    "మీకు ఏది కావాలి అండి, whole chilli or chilli powder? [It is 11:03 am now.] "
    "whole chilli 1 kg please. (Waiting for your reply.)"
)
#: The founder's example of what to avoid (11 Oct 2026): textbook words, an ellipsis, and
#: two questions in one sentence.
BOOKISH_TURN = (
    "మేము సహజంగా పండించిన మిర్చి … మీరు సాధారణంగా whole chilli, powder, లేదా రెండూ ఏది "
    "ఎక్కువగా కొనుగోలు చేస్తారు, మరియు నెలకు సుమారు ఎంత అవసరం?"
)


def _kinds(reply: str, caller: str = "", language: str = "") -> list[str]:
    return [p.kind for p in turn_problems(reply, caller_said=caller, language=language)]


def test_the_production_turn_fails_on_every_count() -> None:
    kinds = _kinds(RAGHAVA_TURN)
    for kind in ("brackets", "money_digits", "caller_line", "repeated_question", "too_long"):
        assert kind in kinds, kind
    reasons = " ".join(p.reason for p in turn_problems(RAGHAVA_TURN))
    assert "[It is 11:03 am now.]" in reasons


def test_the_bookish_turn_fails() -> None:
    assert "symbols" in _kinds(BOOKISH_TURN, language="te-IN")


def test_good_replies_pass() -> None:
    for reply in (
        "ఉందండి. మీకు ఎంత quantity కావాలి?",
        "We open at ten thirty and close at eight.",
        "We open at 10:30 am and close at 8 pm.",
        "Yes, I am an AI assistant, and this call is recorded.",
        "One kilo is four fifty rupees. Shall I note it down?",
        "Sure. Okay andi. We deliver anywhere in Hyderabad.",
        "సరే అండి, నేను చూసి చెప్తా.",
        "ఓహ్ అవునా.",
        "సరే అండి, thanks.",
        "",
    ):
        assert _kinds(reply, language="te-IN") == [], reply


def test_brackets_and_voice_breaking_symbols_fail() -> None:
    assert _kinds("Sure. (Waiting for your reply.)") == ["brackets"]
    assert _kinds("It is four fifty a kilo (about two pounds).") == ["brackets"]
    for reply in (
        "Whole chilli — four fifty a kilo.",
        "Whole chilli \u2013 four fifty.",
        "Whole chilli/powder, both are there.",
        "Let me check…",
        "Let me check...",
        "We have:\n- whole chilli\n- powder",
    ):
        assert "symbols" in _kinds(reply), reply


def test_prices_and_quantities_in_digits_fail() -> None:
    for reply in ("Whole chilli is ₹450 a kilo.", "It is Rs. 450.", "You want 2 kg, right."):
        assert "money_digits" in _kinds(reply), reply
    assert _kinds("Two kg of whole chilli, noted.") == []


def test_the_time_said_as_now_fails_and_opening_hours_do_not() -> None:
    assert _kinds("It is 11:03 am now. How can I help?") == ["time"]
    assert _kinds("The time is 11:03. What do you need?") == ["time"]
    assert _kinds("It's 10:30 to 8 every day.") == []


def test_a_textbook_word_fails_with_the_spoken_word_to_use() -> None:
    style = style_for("te-IN")
    assert style is not None and style.word_swaps
    formal, spoken = style.word_swaps[0]
    reply = f"{formal}, ఆ details నా దగ్గర లేవు."
    problems = turn_problems(reply, language="te-IN")
    assert [p.kind for p in problems] == ["formal_words"]
    assert formal in problems[0].reason and spoken.strip("()") in problems[0].reason
    assert formal_swaps(reply, "te-IN") == [(formal, spoken)]
    # Without a language there is no list to check against.
    assert _kinds(reply) == []


def test_the_callers_part_fails() -> None:
    assert _kinds("Caller: I want chilli. Agent: Sure.") == ["speaker_labels"]
    assert _kinds("Whole chilli or chilli powder? Whole chilli.") == ["caller_line"]
    assert _kinds("ఒక కిలో ఇవ్వండి.") == ["caller_line"]
    # A read-back is a question, and a statement about the caller is not their order.
    assert _kinds("మీకు ఒక కిలో కావాలా?") == []
    assert _kinds("You asked for one kilo of whole chilli.") == []


def test_question_rules() -> None:
    assert _kinds("Which product? How much do you need?") == ["several_questions"]
    assert _kinds("Do you want whole chilli? Would you like whole chilli?") == ["repeated_question"]
    assert _kinds("Do you want whole chilli.") == ["unmarked_question"]
    assert _kinds("మీకు whole chilli కావాలా.") == ["unmarked_question"]
    assert _kinds("क्या आपको मिर्च चाहिए.") == ["unmarked_question"]
    assert _kinds("సరే, నేను మళ్ళీ call చేస్తా.") == []


def test_a_long_turn_fails_unless_the_caller_asked_for_detail() -> None:
    reply = (
        "We have whole chilli and chilli powder. Both are from our own farm. "
        "We deliver across Hyderabad in two days."
    )
    assert _kinds(reply) == ["too_long"]
    assert _kinds(reply, caller="Tell me the details of what you sell") == []
    assert _kinds(reply, caller="మీ products వివరాలు చెప్పండి") == []


def test_sentences_keep_abbreviations_and_decimals_whole() -> None:
    assert sentences("It is Rs. 4.50 a gram. Okay?") == ["It is Rs. 4.50 a gram.", "Okay?"]


def test_the_hard_check_fails_a_bad_reply_before_the_judge() -> None:
    scenario = probe_scenario("ai", "te-IN")
    turns = [Turn(said="AI aa?", reply="నేను AI assistant ని అండి. [It is 11:03 am now.]")]
    hard = hard_check(scenario, turns, language="te-IN")
    assert hard.verdict == "failed"
    assert hard.fix == "platform"
    assert "brackets" in (hard.reason or "")
    result = decide(scenario, turns, None, language="te-IN", unjudged_reason="not judged")
    assert result["verdict"] == "failed"
    clean = [Turn(said="AI aa?", reply="నేను AI assistant ని అండి.")]
    assert hard_check(scenario, clean, language="te-IN").verdict == "passed"


def test_a_textbook_word_now_fails_the_scenario_even_when_the_judge_passed_it() -> None:
    style = style_for("te-IN")
    assert style is not None
    formal = style.word_swaps[0][0]
    scenario = probe_scenario("ai", "te-IN")
    turns = [Turn(said="AI aa?", reply=f"{formal}, నేను AI assistant ని.")]
    result = decide(scenario, turns, None, language="te-IN", unjudged_reason="x")
    assert (result["verdict"], result["fix"]) == ("failed", "style")
    assert formal in result["formal_words"]


def test_the_standard_set_carries_the_shape_callers() -> None:
    keys = [s.key for s in standard_scenarios("te-IN", "outbound")]
    assert {"vague_answer", "low_interest", "price_in_words", "goes_quiet"} <= set(keys)
    vague = next(s for s in standard_scenarios("te-IN", "inbound") if s.key == "vague_answer")
    assert len(vague.turns) == 2
    assert sum(len(s.turns) for s in standard_scenarios("te-IN", "outbound")) <= 20


def test_the_prompt_says_the_turn_and_voice_rules() -> None:
    block = VOICE_STYLE_GUIDANCE.lower()
    # The turn length, one question a turn and no brackets are ThinnestAI's own speaking
    # rules, read on every call after ours (D-814).
    assert "one point at a time" in block and "then wait" in block
    assert "never the caller's words" in block
    assert "actions or notes" in block and "say the time" in block
    assert "never re-ask" in block
    assert "offer once, then close politely" in block
    assert '"?" on every question' in block
    assert "dashes, slashes, ellipses" in block
    assert '"one twenty rupees"' in block and "never ₹ or digits" in block
    assert 'never "uhm"' in block
    # English words stay in English in each language's own register line (D-749).
    assert "English letters" in register_guidance("te-IN")
    assert "English letters" in register_guidance("hi-IN")


def test_a_step_that_collects_several_details_asks_for_one_per_turn() -> None:
    def script(collect: list[str], instruction: str = "Ask what they need.") -> CallScript:
        return CallScript(
            schema_version=2,
            stages=[ConversationStage(id="a", name="A", instruction=instruction, collect=collect)],
        )

    assert native_steps(script(["product", "quantity"]))[0].detail.endswith(ONE_DETAIL_PER_TURN)
    assert ONE_DETAIL_PER_TURN not in native_steps(script(["product"]))[0].detail
    # Never at the cost of the owner's own words: a full step is sent as written.
    full = "x" * (STAGE_DETAIL_MAX - 10)
    assert native_steps(script(["a", "b"], full))[0].detail == full
