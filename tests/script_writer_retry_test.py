"""Pip's script writer fixes what it can itself before the owner hears of a problem: a listed
textbook word is swapped for its spoken form, a v2 script's unused v1 fields are neither shown
to the model nor taken from it, and a draft that still broke a rule is written again."""

from __future__ import annotations

import time

from apps.api.core.errors import ProblemError
from apps.workers import campaign_script
from apps.workers.script_assist import (
    ANSWER_UNUSABLE_CODE,
    AskTrace,
    LeftOut,
    _answer_unusable,
    salvaged_edit,
    with_spoken_swaps,
)
from calevate_shared.call_script import (
    SCRIPT_SCHEMA_VERSION,
    CallScript,
    ConversationStage,
)
from calevate_shared.spoken_guard import spoken_swapped, textbook_words

FORMAL = "సహాయం"


def _v2(**fields: object) -> CallScript:
    return CallScript.model_validate(
        {
            "schema_version": SCRIPT_SCHEMA_VERSION,
            "stages": [
                ConversationStage(id="s1", name="Start", instruction="Say why you call."),
                ConversationStage(id="s2", name="Close", instruction="Thank them and end."),
            ],
            **fields,
        }
    )


def test_the_listed_word_is_the_one_swapped() -> None:
    assert (FORMAL, "help") in textbook_words(f"{FORMAL} చేస్తాను", "te-IN")


def test_a_whole_textbook_word_is_swapped_for_its_spoken_form() -> None:
    assert spoken_swapped(f"మీకు {FORMAL} చేస్తాను.", "te-IN") == "మీకు help చేస్తాను."


def test_a_word_with_a_suffix_and_the_owners_own_word_are_left() -> None:
    joined = f"{FORMAL}తో చూపిస్తాను."
    assert spoken_swapped(joined, "te-IN") == joined
    owners = f"మీకు {FORMAL} చేస్తాను."
    assert spoken_swapped(owners, "te-IN", allowed=FORMAL) == owners


def test_an_instruction_form_is_never_written_into_the_line() -> None:
    line = "అప్లికేషన్ మరియు వెబ్‌సైట్."
    assert textbook_words(line, "te-IN")
    assert "(" not in spoken_swapped(line, "te-IN")


def test_the_models_opening_is_swapped_and_the_owners_kept() -> None:
    before = _v2(outbound_opening_line=f"నేను మీకు {FORMAL} చేస్తాను.")
    written = before.model_copy(update={"opening_line": f"{FORMAL} కోసం కాల్ చేశాను."})
    swapped = with_spoken_swaps(written, "te-IN", before=before)
    assert swapped.opening_line == "help కోసం కాల్ చేశాను."
    assert swapped.outbound_opening_line == before.outbound_opening_line


def test_an_edit_of_a_v2_script_ignores_steps_written_as_strings() -> None:
    current = _v2()
    raw = {"steps": ["Introduce the call.", "Check the icon."], "goal": "Help them set it up."}
    edited, put_back = salvaged_edit(raw, current, language=None)
    assert edited.steps == []
    assert edited.goal == "Help them set it up."
    assert put_back == []


def test_a_v1_script_still_takes_its_steps() -> None:
    current = CallScript(opening_line="Hello.")
    edited, _ = salvaged_edit({"steps": [{"instruction": "Ask their name."}]}, current)
    assert [s.instruction for s in edited.steps] == ["Ask their name."]


def _refusal(code: str = ANSWER_UNUSABLE_CODE) -> ProblemError:
    refused = _answer_unusable()
    if code != ANSWER_UNUSABLE_CODE:
        return ProblemError.business_rule(code, "No.", remediation="Later.")
    return refused


def test_an_answer_that_broke_a_rule_is_written_again_while_there_is_time() -> None:
    now = time.monotonic()
    assert campaign_script._writes_again(_refusal(), AskTrace(), 1, now)
    assert campaign_script._writes_again(_refusal(), AskTrace(), 2, now)
    assert not campaign_script._writes_again(
        _refusal(), AskTrace(), campaign_script.WRITE_ATTEMPTS, now
    )


def test_no_retry_when_time_is_short_or_the_cause_is_not_a_broken_rule() -> None:
    late = time.monotonic() - 250
    assert not campaign_script._writes_again(_refusal(), AskTrace(), 1, late)
    cut = AskTrace()
    cut.truncated = True
    assert not campaign_script._writes_again(_refusal(), cut, 1, time.monotonic())
    other = _refusal("assist_quota_exhausted")
    assert not campaign_script._writes_again(other, AskTrace(), 1, time.monotonic())


def test_the_retry_tells_the_model_what_the_last_answer_broke() -> None:
    broke = [LeftOut("opening_line", "", "uses textbook words callers do not say")]
    asked = campaign_script.retry_change("Add an intro step.", broke)
    assert asked.startswith("Add an intro step.")
    assert "opening_line: uses textbook words callers do not say" in asked
    assert "plain everyday" in campaign_script.retry_change("Add an intro step.", [])
