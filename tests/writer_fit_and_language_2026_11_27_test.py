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
