"""The script cause of each mistake on a real call (D-985, `agents/mistake_lints`)."""

from __future__ import annotations

import pytest
from apps.api.agents.call_mistakes import LESSONS
from apps.api.agents.mistake_lints import SCRIPT_FIXABLE_KINDS, mistake_findings
from apps.api.agents.script_lint import LintContext, script_problems
from apps.api.agents.script_proposals import finding_key
from apps.api.agents.turn_checks import IN_CALL_KINDS
from calevate_shared.call_script import CallScript, ConversationStage, ProcedureStep, StepOutcome
from calevate_shared.spoken_style import style_for

_CLEAN_OPENING = "Hello, can we talk now?"


def _stage(
    sid: str, line: str, instruction: str = "Help them.", **extra: object
) -> ConversationStage:
    return ConversationStage.model_validate(
        {"id": sid, "name": sid, "instruction": instruction, "sounds_like": line, **extra}
    )


def _script(*stages: ConversationStage, opening: str = _CLEAN_OPENING) -> CallScript:
    return CallScript(schema_version=2, opening_line=opening, stages=list(stages))


def _paths(script: CallScript, kind: str, language: str = "") -> list[str]:
    found = mistake_findings(script, LintContext(language=language), kind)
    return [problem.partition(": ")[0] for problem in found]


def _telugu() -> str:
    style = style_for("te-IN")
    assert style is not None and style.fillers
    return style.fillers[0].text


def test_every_mistake_kind_has_a_script_check() -> None:
    # "brackets" has a script check whether or not a real call counts it yet. A kind shown
    # during the call whatever the script says (`missed_lookup`) has none.
    assert set(LESSONS) >= IN_CALL_KINDS and IN_CALL_KINDS.isdisjoint(SCRIPT_FIXABLE_KINDS)
    assert set(LESSONS) - {"brackets"} - IN_CALL_KINDS == SCRIPT_FIXABLE_KINDS - {"brackets"}


def test_an_unknown_kind_and_a_raw_script_find_nothing() -> None:
    script = _script(_stage("s1", "The caller's number is saved."))
    assert mistake_findings(script, LintContext(), "no_such_kind") == []
    raw = CallScript(schema_version=2, raw_override="As I said, it costs 500 rupees.")
    assert all(mistake_findings(raw, LintContext(), kind) == [] for kind in SCRIPT_FIXABLE_KINDS)


# (kind, the script that causes it, the path named, a script that does not)
_CASES: list[tuple[str, CallScript, str, CallScript]] = [
    (
        "opened_again",
        _script(_stage("s1", "", instruction="Greet the lead and introduce yourself.")),
        "stages.0.instruction",
        _script(_stage("s1", "", instruction="Ask which area they live in.")),
    ),
    (
        "same_opening",
        _script(
            _stage("s1", "OK, which area do you live in?"),
            _stage("s2", "OK, when would you like to visit?"),
        ),
        "stages.1.sounds_like",
        _script(
            _stage("s1", "Which area do you live in?"),
            _stage("s2", "Good, when would you like to visit?"),
        ),
    ),
    (
        "same_closing",
        _script(
            _stage("s1", "Open the app on your phone and tell me when it is done."),
            _stage("s2", "Now tap the farms tab below and tell me when it is done."),
            _stage("s3", "Add your first crop on that screen and tell me when it is done."),
        ),
        "stages.1.sounds_like",
        _script(
            _stage("s1", "Open the app on your phone and tell me when it is done."),
            _stage("s2", "Now tap the farms tab below. Do you see your farm?"),
            _stage("s3", "Add your first crop on that screen. Is it saved?"),
        ),
    ),
    (
        "said_again",
        _script(
            _stage("s1", "We deliver fresh vegetables to your home every morning."),
            _stage("s2", "We deliver fresh vegetables to your home every single morning."),
        ),
        "stages.1.sounds_like",
        _script(
            _stage("s1", "We deliver fresh vegetables to your home every morning."),
            _stage("s2", "When would you like the first delivery?"),
        ),
    ),
    (
        "too_long",
        _script(
            _stage(
                "s1",
                "We are open all day. We deliver to every area here. We take orders by phone too.",
            )
        ),
        "stages.0.sounds_like",
        _script(_stage("s1", "We are open all day, and we deliver.")),
    ),
    (
        "asked_again",
        _script(
            _stage("s1", "Which area do you live in?"),
            _stage("s2", "Sorry. Which area do you live in?"),
        ),
        "stages.1.sounds_like",
        _script(
            _stage("s1", "Which area do you live in?"),
            _stage("s2", "When would you like to visit?"),
        ),
    ),
    (
        "reasked_name",
        _script(
            _stage("s1", "What is your name?"),
            _stage("s2", "Which area do you live in?"),
            _stage("s3", "And your name, please?"),
        ),
        "stages.2.sounds_like",
        _script(
            _stage("s1", "What is your name?"),
            _stage("s2", "Which area do you live in?"),
        ),
    ),
    (
        "caller_line",
        _script(_stage("s1", "Two kg tomatoes please.")),
        "stages.0.sounds_like",
        _script(_stage("s1", "How many kilos would you like?")),
    ),
    (
        "goodbye_while_asking",
        _script(_stage("s1", "Thank you, bye."), _stage("s2", "When would you like to visit?")),
        "stages.0.sounds_like",
        _script(_stage("s1", "When would you like to visit?"), _stage("s2", "Thank you, bye.")),
    ),
    (
        "false_recall",
        _script(_stage("s1", "As I said, it costs 500 rupees.")),
        "stages.0.sounds_like",
        _script(
            _stage("s1", "It costs 500 rupees a month."),
            _stage("s2", "As I said, it costs 500 rupees."),
        ),
    ),
    (
        "third_person",
        _script(_stage("s1", "The caller's number is saved now.")),
        "stages.0.sounds_like",
        _script(_stage("s1", "Your number is saved now.")),
    ),
    (
        "offered_more_too_soon",
        _script(
            _stage("s1", "Is there anything else?"),
            _stage("s2", "Which area do you live in?"),
            _stage("s3", "Anything else I can help with?"),
        ),
        "stages.0.sounds_like",
        _script(
            _stage("s1", "Which area do you live in?"),
            _stage("s2", "Anything else I can help with?"),
        ),
    ),
    (
        "false_history",
        _script(
            _stage("s1", "Which area do you live in?"),
            opening="Hello, you enquired about our flats, can we talk now?",
        ),
        "opening_line",
        _script(_stage("s1", "Which area do you live in?")),
    ),
    (
        "stalled",
        _script(
            _stage("s1", "Which area?"),
            _stage("s2", "OK, no problem."),
            _stage("s3", "Thank you."),
        ),
        "stages.1.sounds_like",
        _script(
            _stage("s1", "Which area?"),
            _stage("s2", "OK, which day suits you?"),
            _stage("s3", "Thank you."),
        ),
    ),
    # Step outcomes (founder, 24 Nov 2026): a step with an outcome and no way out.
    (
        "moved_on_unconfirmed",
        _script(_stage("s1", "Is the app open?"), _stage("s2", "Thank you.")).model_copy(
            update={"step_outcomes": [StepOutcome(step=1, outcome="The app is open.")]}
        ),
        "stages.0.instruction",
        _script(
            _stage(
                "s1",
                "Is the app open?",
                branches=[{"when": "They cannot open it now", "target": "s2"}],
            ),
            _stage("s2", "Thank you."),
        ).model_copy(update={"step_outcomes": [StepOutcome(step=1, outcome="The app is open.")]}),
    ),
    (
        "brackets",
        _script(_stage("s1", "Tap Add to Home screen (the third option) and tell me.")),
        "stages.0.sounds_like",
        _script(_stage("s1", "Tap Add to Home screen and tell me when it shows.")),
    ),
]


@pytest.mark.parametrize(("kind", "causes", "path", "clean"), _CASES, ids=[c[0] for c in _CASES])
def test_each_kind_names_the_line_that_causes_it(
    kind: str, causes: CallScript, path: str, clean: CallScript
) -> None:
    assert path in _paths(causes, kind)
    assert _paths(clean, kind) == []


def test_the_cases_cover_every_kind() -> None:
    # The two language-bound kinds have their own tests (formal_words: call_2026_11_24_1215).
    assert {case[0] for case in _CASES} | {"wrong_language", "formal_words"} == (
        SCRIPT_FIXABLE_KINDS
    )


def test_a_line_wholly_in_english_in_a_telugu_call_is_the_wrong_language() -> None:
    script = _script(_stage("s1", "Which phone do you have?"))
    assert _paths(script, "wrong_language", "te-IN") == ["stages.0.sounds_like"]
    # The same line is right on an English call, and a Telugu line is right on a Telugu one.
    assert _paths(script, "wrong_language", "en-IN") == []
    telugu = _script(_stage("s1", _telugu()))
    assert _paths(telugu, "wrong_language", "te-IN") == []


def test_a_goodbye_after_a_question_in_the_close_is_found() -> None:
    script = _script(
        _stage("s1", "Which area do you live in?"),
        _stage("s2", "Do you have any questions? Thank you, goodbye."),
    )
    assert _paths(script, "goodbye_while_asking") == ["stages.1.sounds_like"]


def test_an_offer_of_more_inside_a_step_by_step_task_is_found() -> None:
    steps = [ProcedureStep(action="Open the app."), ProcedureStep(action="Tap the menu.")]
    script = _script(_stage("s1", "Is there anything else?", procedure=steps))
    assert _paths(script, "offered_more_too_soon") == ["stages.0.sounds_like"]


def test_steps_on_separate_ways_do_not_count_as_asking_twice() -> None:
    # Two ways out, each asking the name once: no caller hears it twice.
    script = _script(
        _stage(
            "s1",
            "Are you buying or renting?",
            branches=[
                {"when": "buying", "target": "buy"},
                {"when": "renting", "target": "rent"},
            ],
        ),
        _stage("buy", "What is your name?", otherwise="end"),
        _stage("rent", "What is your name?", otherwise="end"),
        _stage("end", "Thank you, bye."),
    )
    assert _paths(script, "reasked_name") == []


def test_findings_work_with_the_fix_flow_and_stay_off_the_readiness_card() -> None:
    script = _script(_stage("s1", "The caller's number is saved now."))
    (problem,) = mistake_findings(script, LintContext(), "third_person")
    assert finding_key(problem, script) == "stages#s1.sounds_like"
    assert problem not in script_problems(script, LintContext())
