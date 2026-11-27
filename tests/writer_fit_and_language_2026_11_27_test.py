"""The writer's two 26 Nov 2026 production failures on the Rytu Khata campaign: a script
7,012 characters over the engine's box (step-by-step lists 13,501), and an English close
line in a Telugu call."""

from __future__ import annotations

import pytest
from apps.workers.campaign_script import trimmed_procedures
from apps.workers.step_writer import UnusableAnswerError, parsed_step
from calevate_shared.call_script import CallScript, ConversationStage
from tests.script_writer_rebuild_2026_11_26_test import fake as fake


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


# The opening Pip kept on 26 Nov 2026 (23:20) and carried into every regeneration after.
_ROMANISED = (
    "{{lead_name}} garu, nenu Varsha ni Rytu Khata nunchi. We are calling to help you install "
    "and start using the app. Ippudu matladagalara?"
)
_IN = "".join(chr(0x0C15 + i) for i in range(6))  # Telugu letters, no words
_TELUGU = f"{{{{lead_name}}}} {_IN}, {_IN} Varsha, Rytu Khata {_IN}. app {_IN} {_IN}?"


def test_an_opening_with_no_telugu_letters_or_an_english_sentence_breaks_the_rule() -> None:
    from apps.workers.opening_line import own_script_problem

    names = ("Rytu Khata", "Varsha")
    assert own_script_problem("opening_line", _ROMANISED, "te-IN", names=names)
    assert own_script_problem("opening_line", "{{lead_name}} garu, matladagalara?", "te-IN")
    assert own_script_problem("opening_line", _TELUGU, "te-IN", names=names) is None
    assert own_script_problem("opening_line", "Hello, can we talk now?", "en-IN") is None


@pytest.mark.parametrize(("pip_owned", "rewritten"), [(True, True), (False, False)])
async def test_a_broken_opening_carried_from_pips_own_script_is_rewritten(
    monkeypatch: pytest.MonkeyPatch, pip_owned: bool, rewritten: bool
) -> None:
    """FAILS IF: the opening of a script Pip still owns is taken as the owner's and kept
    unchecked, so a regeneration keeps the romanised line; an owner's line is never touched."""
    import time
    from dataclasses import replace

    from apps.workers import script_writer
    from apps.workers.opening_line import WrittenOpening
    from apps.workers.script_assist import JsonAnswer
    from calevate_shared.opening_notices import SaidNotices
    from tests.script_writer_rebuild_2026_11_26_test import CAP, _context, _script

    async def opening(brief: object, **kw: object) -> JsonAnswer[WrittenOpening]:
        return JsonAnswer(
            value=WrittenOpening(line=_TELUGU, said=SaidNotices()), capability=CAP, model="fake"
        )

    monkeypatch.setattr(script_writer, "write_opening", opening)
    base = _script().model_copy(update={"opening_line": _ROMANISED})
    context = _context()
    context = replace(context, brief=replace(context.brief, language="te-IN"), pip_owned=pip_owned)
    script, _spent = await script_writer._opening(context, base, base, time.monotonic())
    assert (script.opening_line == _TELUGU) is rewritten


# --- what a regeneration carries over (26 Nov 2026: a WhatsApp ending, a stale example call
# and a never-spoken placed-call opening outlived every regeneration) ------------------------


def _stale() -> CallScript:
    from calevate_shared.call_script import ExampleLine
    from tests.script_writer_rebuild_2026_11_26_test import _script

    return _script().model_copy(
        update={
            "identity": "Old role.",
            "ending": "Ask them to message us on WhatsApp.",
            "outbound_opening_line": "Never said on this campaign?",
            "example_exchange": [ExampleLine(speaker="agent", text="Old example.")],
        }
    )


@pytest.mark.parametrize("pip_owned", [True, False])
async def test_a_regeneration_of_pips_own_script_writes_the_frame_again(
    fake: object, pip_owned: bool
) -> None:
    """FAILS IF: the ending of a script Pip still owns is carried over unchanged; an owner's
    edited ending stays theirs."""
    from dataclasses import replace

    from apps.workers.script_writer import WriteRequest, write_script
    from tests.script_writer_rebuild_2026_11_26_test import _context

    context = replace(_context(), pip_owned=pip_owned)
    result = await write_script(WriteRequest("whole", context, base=_stale()))
    script = result.script
    assert script.outbound_opening_line == ""  # an outbound campaign never speaks it
    if pip_owned:
        assert script.ending == "Thank them and say goodbye."
        assert script.example_exchange == []
    else:
        assert script.ending == "Ask them to message us on WhatsApp."
        assert script.example_exchange


def test_the_steps_are_written_against_the_opening_the_call_speaks() -> None:
    from dataclasses import replace

    from apps.workers.script_writer import spoken_opening
    from tests.script_writer_rebuild_2026_11_26_test import _context

    script = _stale()
    assert spoken_opening(_context(), script) == script.opening_line
    both = _context()
    both = replace(both, brief=replace(both.brief, direction="both"))
    assert spoken_opening(both, script) == "Never said on this campaign?"


def _spoken(sid: str, turns: int) -> ConversationStage:
    from calevate_shared.call_script import StepExamples

    said = [f"line {n} " + "x" * 40 for n in range(turns)]
    return ConversationStage(
        id=sid,
        name=f"Step {sid}",
        instruction="Guide them.",
        examples={
            "te-IN": StepExamples(turns=[f"{_IN} {n}" for n in range(turns)], confused=_IN),
            "en-IN": StepExamples(turns=said, confused="Again, shorter."),
        },
    )


def test_examples_are_trimmed_other_language_first_and_the_main_one_is_kept() -> None:
    """FAILS IF: a script with no step-by-step lists cannot be brought inside the box (26 Nov
    2026: 19,162 characters, every step's examples in Telugu and English)."""
    from apps.workers.campaign_script import trimmed_examples

    script = CallScript(schema_version=2, stages=[_spoken("a", 5), _spoken("b", 4)])
    fewer = trimmed_examples(script, 60, "te-IN")
    assert fewer is not None
    assert [len(s.examples["en-IN"].turns) for s in fewer.stages] == [3, 4]
    assert all(
        len(s.examples["te-IN"].turns) == len(o.examples["te-IN"].turns)
        for s, o in zip(fewer.stages, script.stages, strict=True)
    )

    most = trimmed_examples(script, 100_000, "te-IN")
    assert most is not None
    assert all(set(s.examples) == {"te-IN"} for s in most.stages)
    assert all(len(s.examples["te-IN"].turns) == 3 for s in most.stages)
    assert trimmed_examples(most, 100, "te-IN") is None
