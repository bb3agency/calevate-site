"""A script suggestion that gets one line wrong after its repair keeps the rest (A-07).

Before, one model line that still broke a rule after the one repair failed the whole
suggestion, and the owner got none of the good changes ("Pip refused its own Telugu",
5 Nov 2026). The model is replaced at its seam; the lines here are English.
"""

from __future__ import annotations

import pytest
from apps.workers.script_assist import UnusableAnswerError, edited_script, owners_where
from calevate_shared.call_script import CallScript, ConversationStage, StageBranch

CURRENT = CallScript(
    schema_version=2,
    opening_line="Hello, how can I help you today?",
    goal="Help callers.",
    stages=[ConversationStage(id="a", name="Greet", instruction="Greet them.")],
)
ANSWER = {
    "goal": "Help callers with their orders.",
    "opening_line": "As I said, how can I help you today?",
}


def test_the_first_answer_is_sent_back_for_its_one_repair() -> None:
    with pytest.raises(UnusableAnswerError):
        edited_script(ANSWER, CURRENT)


def test_after_the_repair_the_broken_line_is_the_owners_and_the_rest_is_kept() -> None:
    kept = edited_script(ANSWER, CURRENT, lenient=True)
    assert kept is not None
    assert kept.goal == "Help callers with their orders."
    assert kept.opening_line == CURRENT.opening_line


def test_an_answer_with_nothing_right_is_still_unusable() -> None:
    with pytest.raises(UnusableAnswerError):
        edited_script({"opening_line": ANSWER["opening_line"]}, CURRENT, lenient=True)


def test_a_broken_step_the_model_added_is_dropped_with_the_ways_to_it() -> None:
    added = ConversationStage(id="b", name="Pitch", instruction="Pitch.")
    pointing = CURRENT.stages[0].model_copy(
        update={"branches": [StageBranch(when="they ask", target="b")], "otherwise": "b"}
    )
    edited = CURRENT.model_copy(update={"stages": [pointing, added], "goal": "New goal."})
    restored = owners_where(edited, CURRENT, ["stages.1.instruction: breaks a rule"])
    assert [s.id for s in restored.stages] == ["a"]
    assert restored.stages[0].branches == [] and restored.stages[0].otherwise == ""
    assert restored.goal == "New goal."
