"""The writer's two 26 Nov 2026 production failures on the Rytu Khata campaign: a script
7,012 characters over the engine's box (step-by-step lists 13,501), and an English close
line in a Telugu call."""

from __future__ import annotations

from typing import Any

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

    script = _script()
    old = script.stages[0].model_copy(update={"sounds_like": "Old line."})
    return script.model_copy(
        update={
            "stages": [old, *script.stages[1:]],
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
    edited ending stays theirs. The whole example call goes either way once the steps carry
    examples, since the compiler then never reads it."""
    from dataclasses import replace

    from apps.workers.script_writer import WriteRequest, write_script
    from tests.script_writer_rebuild_2026_11_26_test import _context

    context = replace(_context(), pip_owned=pip_owned)
    result = await write_script(WriteRequest("whole", context, base=_stale()))
    script = result.script
    assert script.outbound_opening_line == ""  # an outbound campaign never speaks it
    assert script.example_exchange == []
    assert all(not s.sounds_like and not s.scripts for s in script.stages)
    if pip_owned:
        assert script.ending == "Thank them and say goodbye."
    else:
        assert script.ending == "Ask them to message us on WhatsApp."


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
    2026: 19,162 characters, every step's examples in Telugu and English), or an English
    call's other language is trimmed before its turns are."""
    from apps.workers.campaign_script import trimmed_examples

    script = CallScript(schema_version=2, stages=[_spoken("a", 5), _spoken("b", 4)])
    # In a Telugu call the English examples go whole first, the longest step's first.
    fewer = trimmed_examples(script, 60, "te-IN")
    assert fewer is not None
    assert [set(s.examples) for s in fewer.stages] == [{"te-IN"}, {"te-IN", "en-IN"}]
    assert all(
        len(s.examples["te-IN"].turns) == len(o.examples["te-IN"].turns)
        for s, o in zip(fewer.stages, script.stages, strict=True)
    )
    # In an English call the other language's turns are trimmed before it goes whole.
    english = trimmed_examples(script, 20, "en-IN")
    assert english is not None
    assert [len(s.examples["te-IN"].turns) for s in english.stages] == [3, 4]

    most = trimmed_examples(script, 100_000, "te-IN")
    assert most is not None
    assert all(set(s.examples) == {"te-IN"} for s in most.stages)
    assert all(len(s.examples["te-IN"].turns) == 3 for s in most.stages)
    assert trimmed_examples(most, 100, "te-IN") is None


# --- examples kept to their own step, three of them (27 Nov 2026, the Rytu Khata draft) -----


def test_the_writer_asks_for_and_keeps_three_turns() -> None:
    """FAILS IF: five turns are asked for or kept per language, the size that pushed the
    Rytu Khata draft past the engine's box."""
    from apps.workers import step_writer

    assert step_writer.MIN_TURNS == 3
    assert "exactly 3 different ways" in step_writer.STEP_INSTRUCTION
    raw = {
        "instruction": "Guide them to log in.",
        "examples": {"te-IN": {"turns": [f"{_IN} {n}" for n in range(5)]}},
    }
    words = parsed_step(raw, languages=["te-IN"], first=False, close=False)
    assert words.examples["te-IN"].turns == [f"{_IN} {n}" for n in range(3)]


def test_a_doubled_particle_is_said_once() -> None:
    """FAILS IF: the doubled particle of the Rytu Khata draft reaches the script."""
    from apps.workers.step_writer import DOUBLED_PARTICLES, undoubled

    particle = DOUBLED_PARTICLES[0]
    assert undoubled(f"{_IN} {particle} {particle}.") == f"{_IN} {particle}."
    assert undoubled(f"{_IN} {_IN} {particle}") == f"{_IN} {_IN} {particle}"
    raw = {
        "instruction": "Thank them and end the call.",
        "examples": {"te-IN": {"turns": [f"{_IN} {particle} {particle}"]}},
    }
    words = parsed_step(raw, languages=["te-IN"], first=False, close=True)
    assert words.examples["te-IN"].turns == [f"{_IN} {particle}"]


def _scoped() -> CallScript:
    from calevate_shared.call_script import ProcedureStep, StepExamples

    def stage(sid: str, name: str, step: int, action: str, said: StepExamples) -> ConversationStage:
        return ConversationStage(
            id=sid,
            name=name,
            instruction=f"Guide them through {name.lower()}.",
            step=step,
            procedure=[ProcedureStep(action=action, wait_for="They say it is done")],
            examples={"en-IN": said},
        )

    return CallScript(
        schema_version=2,
        stages=[
            stage(
                "farms",
                "My Farms",
                1,
                "Tap Add Farm on the Acme Farms screen",
                StepExamples(turns=["Please tap Add Farm."]),
            ),
            stage(
                "expense",
                "First expense",
                2,
                "Tap New Expense",
                StepExamples(
                    turns=["Please tap Add Farm.", "Open Acme Farms and tap New Expense."],
                    stuck="If it still does not work, we will call you back later.",
                    confused="Tap New Expense, the button at the bottom.",
                ),
            ),
        ],
    )


def test_a_line_naming_another_steps_button_is_found() -> None:
    """FAILS IF: the expense step's "Please tap Add Farm." (the farm step's button) passes;
    the business's own name, said in every step, is never another step's."""
    from apps.workers.script_writer import example_problems
    from tests.script_writer_rebuild_2026_11_26_test import _context

    found = [p for p in example_problems(_scoped(), _context()) if "which is step" in p]
    assert found == [
        'stages.1.examples.en-IN.turns.0: names "add farm", which is step "My Farms"\'s; '
        "keep each line to this step's own action."
    ]


def test_a_stuck_line_offering_a_call_back_is_found() -> None:
    """FAILS IF: the stuck hint offers a call back while the agent can still help."""
    from apps.workers.script_writer import example_problems
    from tests.script_writer_rebuild_2026_11_26_test import _context

    found = [p for p in example_problems(_scoped(), _context()) if "offers a call back" in p]
    assert [p.partition(":")[0] for p in found] == ["stages.1.examples.en-IN.stuck"]


async def test_a_stuck_call_back_is_written_again_told_why(fake: Any) -> None:
    """FAILS IF: the writer keeps a stuck line offering a call back without asking again."""
    from apps.workers.script_writer import WriteRequest, write_script
    from tests.script_writer_rebuild_2026_11_26_test import LANG, OWNER_STEPS, _context, _good

    asked: dict[str, int] = {}

    def answer(name: str, request: str) -> dict[str, Any]:
        asked[name] = asked.get(name, 0) + 1
        raw = _good(name)
        if name == "Login" and asked[name] == 1:
            raw["examples"][LANG]["stuck"] = "No problem, we can call you back later."
        return raw

    fake.answer = answer
    result = await write_script(WriteRequest("whole", _context(instruction=OWNER_STEPS)))
    login = next(s for s in result.script.stages if s.name == "Login")
    assert asked["Login"] == 2
    assert "call you back" not in login.examples[LANG].stuck
    again = [r for r in fake.requests if 'THIS STEP: "Login"' in r][-1]
    assert "offers a call back" in again
