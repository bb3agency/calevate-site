"""Speech naturalness (founder, 9 Nov 2026): every writer of spoken lines gets the in-call
prompt's written-form rule and the punctuation the voice paces by, and every spoken line a
writer produces is held to the language's own letters, not only the opening.

The Telugu lines here are the ones `opening_continues_test` already uses: no new wording.
"""

from __future__ import annotations

from apps.api.engine.thinnest import ENGINE_DEFAULT_CALL_RULES_CHARS
from apps.api.ops.config_catalog import FIELD_META
from apps.workers.agent_test_ai import IMPROVE_INSTRUCTION
from apps.workers.opening_line import opening_request
from apps.workers.script_assist import (
    _SYSTEM_INSTRUCTION,
    CONVERT_INSTRUCTION,
    EDIT_INSTRUCTION,
    ScriptBrief,
    language_problems,
)
from calevate_shared.call_script import CallScript, ConversationStage, ExampleLine, SpeakingStyle
from calevate_shared.engine import CALL_INSTRUCTIONS, VOICE_STYLE_GUIDANCE
from calevate_shared.spoken_guard import (
    SPOKEN_LINE_RULES,
    WRITTEN_FORM_RULE,
    generation_guidance,
    has_indic_letters,
)
from tests.opening_continues_test import CALL_OPENING, OPENING

NAMES = ("Sri Estates",)
#: The check runs only for a language that writes English words in its own letters: Hindi
#: since Telugu went back to English letters (20 Nov 2026). It reads only the English letters
#: of a line, so the Telugu fixture lines serve it as they are.
OWN_LETTERS = "hi-IN"

# --- R3: the writers carry the same rules -------------------------------------------------


def test_the_in_call_prompt_and_the_writers_share_one_written_form_sentence() -> None:
    assert f"- {WRITTEN_FORM_RULE}\n" in VOICE_STYLE_GUIDANCE
    assert WRITTEN_FORM_RULE in SPOKEN_LINE_RULES


def test_the_writer_rules_name_no_languages_words() -> None:
    assert not has_indic_letters(SPOKEN_LINE_RULES)
    for mark in ('"!"', "comma", "question mark", "ellipses", "dotted abbreviations", "digit"):
        assert mark in SPOKEN_LINE_RULES, mark


def test_every_languages_writer_guide_ends_with_the_rules() -> None:
    for tag in ("te-IN", "hi-IN", "en-IN", "ta-IN"):
        guide = generation_guidance(tag, "custom")
        assert guide.endswith(SPOKEN_LINE_RULES), tag
        assert guide.count(WRITTEN_FORM_RULE) == 1, tag
    # A language with no style row keeps no guide, so the writer falls back to its register.
    assert generation_guidance("xx-YY") == ""
    assert generation_guidance("te-IN", side="caller").count(SPOKEN_LINE_RULES) == 0


def test_the_script_and_opening_writers_read_the_rules_once() -> None:
    brief = ScriptBrief(business_name="Sri Estates", agent_name="Anjali", language="te-IN")
    for request in (brief.user_message(), opening_request(brief)):
        assert request.count(SPOKEN_LINE_RULES) == 1
    # The instructions defer to the guide rather than keep a second copy of its marks.
    for instruction in (_SYSTEM_INSTRUCTION, CONVERT_INSTRUCTION, EDIT_INSTRUCTION):
        assert WRITTEN_FORM_RULE not in instruction
        assert "ellipses" not in instruction


def test_the_fix_writer_which_has_no_guide_carries_the_rules() -> None:
    assert SPOKEN_LINE_RULES in IMPROVE_INSTRUCTION


def test_the_edit_writer_writes_english_words_as_the_guide_shows() -> None:
    assert "the English words people use written as the spoken-style guide" in EDIT_INSTRUCTION


# --- R7: every spoken line in the language's own letters ----------------------------------


def _script(**update: object) -> CallScript:
    return CallScript(schema_version=2, opening_line=OPENING).model_copy(update=update)


def _latin(script: CallScript, **kwargs: object) -> list[str]:
    return [
        p
        for p in language_problems(script, OWN_LETTERS, names=NAMES, **kwargs)  # type: ignore[arg-type]
        if "English letters" in p
    ]


def test_a_steps_example_line_in_english_letters_is_sent_back() -> None:
    stage = ConversationStage(id="ask", name="Ask", instruction="Ask.", sounds_like=CALL_OPENING)
    found = _latin(_script(stages=[stage]))
    assert [p.split(":")[0] for p in found] == ["stages.0.sounds_like"]
    assert "“call”" in found[0]
    fixed = stage.model_copy(update={"sounds_like": CALL_OPENING.replace("call", "కాల్")})
    assert _latin(_script(stages=[fixed])) == []


def test_sample_phrases_and_the_example_call_are_held_to_it_too() -> None:
    script = _script(
        style=SpeakingStyle(sample_phrases=[CALL_OPENING]),
        example_exchange=[
            ExampleLine(speaker="caller", text=CALL_OPENING),
            ExampleLine(speaker="agent", text=CALL_OPENING),
        ],
    )
    paths = {p.split(":")[0] for p in _latin(script)}
    assert paths == {
        "style.sample_phrases.0",
        "example_exchange.0.text",
        "example_exchange.1.text",
    }


def test_the_owners_own_line_and_the_names_are_theirs() -> None:
    stage = ConversationStage(id="ask", name="Ask", instruction="Ask.", sounds_like=CALL_OPENING)
    assert _latin(_script(stages=[stage]), allowed=CALL_OPENING) == []
    # "Sri Estates" is a name and stays as written: only "call" is named.
    (problem,) = _latin(_script(stages=[stage]))
    assert "Sri" not in problem.split("writes")[1].split(";")[0]


# --- R8: the console's help text ----------------------------------------------------------


def test_the_call_rules_help_text_gives_each_size_to_its_owner() -> None:
    details = FIELD_META["thinnest_call_instructions"].details or ""
    assert f"Ours are {len(CALL_INSTRUCTIONS)} characters" in details
    assert f"ThinnestAI's are about {ENGINE_DEFAULT_CALL_RULES_CHARS:,}" in details
    assert "Ours are about 1,675" not in details
