"""The writer's two 26 Nov 2026 production failures on the Rytu Khata campaign: a script
7,012 characters over the engine's box (step-by-step lists 13,501), and an English close
line in a Telugu call."""

from __future__ import annotations

import pytest
from apps.workers.campaign_script import trimmed_procedures
from apps.workers.step_writer import UnusableAnswerError, parsed_step
from calevate_shared.call_script import CallScript, ConversationStage


def _stage(sid: str, actions: int) -> ConversationStage:
    return ConversationStage.model_validate(
        {
            "id": sid,
            "name": f"Step {sid}",
            "instruction": "Guide them through it.",
            "procedure": [
                {"action": f"Tap button {n} on the screen", "wait_for": "They see it"}
                for n in range(actions)
            ],
        }
    )


def test_trimming_takes_the_longest_list_first_and_stops_at_the_cut() -> None:
    script = CallScript(schema_version=2, stages=[_stage("a", 6), _stage("b", 2)])
    out = trimmed_procedures(script, 40)  # one action is 49 characters with its wait
    assert out is not None
    assert [len(s.procedure) for s in out.stages] == [5, 2]
    assert out.stages[0].instruction == "Guide them through it."


def test_nothing_to_trim_is_none() -> None:
    assert trimmed_procedures(CallScript(schema_version=2, stages=[_stage("a", 0)]), 100) is None


def _answer(turns: list[str]) -> dict[str, object]:
    return {
        "instruction": "Thank them and end the call.",
        "examples": {"te-IN": {"turns": turns}},
    }


def test_an_english_line_in_a_telugu_call_is_refused() -> None:
    """FAILS IF: "Yes, please feel free to reach out to us…" is kept as a Telugu close."""
    with pytest.raises(UnusableAnswerError, match="own script"):
        parsed_step(
            _answer(["Yes, please feel free to reach out to us at any time if you need help."]),
            languages=["te-IN"],
            first=False,
            close=True,
        )


def test_a_telugu_line_with_an_english_word_stays() -> None:
    words = parsed_step(
        _answer(["ఏమైనా డౌట్ ఉంటే మా నంబర్‌కు కాల్ చేయండి, thanks అండి."]),
        languages=["te-IN"],
        first=False,
        close=True,
    )
    assert words.examples["te-IN"].turns
