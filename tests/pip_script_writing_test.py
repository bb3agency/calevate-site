"""How Pip's script writer lays out a call, held to the Rytu Khata campaign calls of 4 Nov 2026.

The outbound agent opened with the business's question to a person it had not named or asked
for a minute, explained several app steps in one breath and then asked "did you understand?",
and never asked two of the business's own questions (how satisfied, what to add). The writer
is told the rules (`call_rules.OPENING_LINE_RULE`, `SCRIPT_FLOW_RULE`); the lint
(`script_lint`) checks what can be checked mechanically, so the writer's repair round, the
readiness card and "Fix them first" all see the same findings.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from apps.api.agents import readiness
from apps.api.agents.call_rules import (
    OPENING_LINE_RULE,
    SCRIPT_FLOW_RULE,
    writer_rules,
)
from apps.api.agents.script_lint import (
    NAME_FIELD,
    PLACED_OPENING_BRIEF,
    CapabilityManifest,
    LintContext,
    instruction_problems,
    placed_opening_problem,
    plain,
    script_problems,
    spoken_line_problems,
    stacked_actions,
    unasked_details,
)
from apps.workers.agent_test_ai import IMPROVE_INSTRUCTION
from apps.workers.script_assist import _SYSTEM_INSTRUCTION, EDIT_INSTRUCTION, language_problems
from calevate_shared.call_script import CallScript, ConversationStage, ProcedureStep
from calevate_shared.spoken_guard import latin_words

_NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
_LONG_OPENING = readiness.ReadinessInputs(
    agent_id=uuid.UUID("01890000-0000-7000-8000-000000000002"),
    agent_name="Varsha",
    knowledge_items=8,
    open_gaps=0,
    opening_chars=300,
    opening_room=None,
    published=True,
    live=True,
    draft_waiting=False,
    out_of_sync=False,
    missed_7d=0,
)
OUTBOUND = LintContext(manifest=CapabilityManifest(direction="outbound"))
INBOUND = LintContext(manifest=CapabilityManifest(direction="inbound"))

#: The shape of the 4 Nov opening, in English: no name, no permission, the business's question.
COLD_OPENING = "Hello, calling from Rytu Khata. Have you installed the Rytu Khata app?"
NAMED_OPENING = (
    f"Hello {NAME_FIELD}, calling from Rytu Khata about the app you installed. "
    "Can you talk for a minute now?"
)
FIELDS = ("Installed Rytu Khata app?", "Satisfaction level", "Suggestions for features")


def _stage(sid: str, name: str, instruction: str, **extra: object) -> ConversationStage:
    return ConversationStage(id=sid, name=name, instruction=instruction, **extra)  # type: ignore[arg-type]


def test_the_name_field_is_the_one_the_dial_fills() -> None:
    assert NAME_FIELD == "{{lead_name}}"


def test_every_writer_reads_the_placed_call_opening_and_the_step_rules() -> None:
    assert NAME_FIELD in OPENING_LINE_RULE
    assert "whether they can talk now" in OPENING_LINE_RULE
    assert "the business's own questions wait until they say yes" in OPENING_LINE_RULE
    # The answering opening is unchanged in substance: a greeting and one question.
    assert "greets, names the business and asks one short question" in OPENING_LINE_RULE
    assert SCRIPT_FLOW_RULE in writer_rules()
    for writer in (_SYSTEM_INSTRUCTION, EDIT_INSTRUCTION, IMPROVE_INSTRUCTION):
        assert SCRIPT_FLOW_RULE in writer
        assert OPENING_LINE_RULE in writer


def test_the_step_rules_name_each_failure_of_the_4_nov_calls() -> None:
    rule = SCRIPT_FLOW_RULE
    assert "Every detail to collect is asked in a stage" in rule
    assert "one action an item" in rule and "waits for the caller to say it is done" in rule
    assert "asking whether they understood" in rule
    assert "a few digits at a time" in rule
    assert "nothing about keeping a note" in rule


def test_a_cold_placed_opening_is_sent_back_for_the_persons_name() -> None:
    problem = placed_opening_problem("opening_line", COLD_OPENING)
    assert problem is not None and NAME_FIELD in problem and "can talk now" in problem
    assert placed_opening_problem("opening_line", NAMED_OPENING) is None
    # A list's own name column counts as the person's name (D-905).
    assert placed_opening_problem("opening_line", "Hello {{name}}, can you talk now?") is None
    asks_nothing = placed_opening_problem("opening_line", f"Hello {NAME_FIELD}, from Rytu Khata.")
    assert asks_nothing is not None and "asks nothing" in asks_nothing


def test_only_an_opening_said_on_placed_calls_is_held_to_it() -> None:
    assert any(
        NAME_FIELD in p for p in spoken_line_problems("opening_line", COLD_OPENING, OUTBOUND)
    )
    assert not any(
        NAME_FIELD in p for p in spoken_line_problems("opening_line", COLD_OPENING, INBOUND)
    )
    # Nobody read the direction: no opening is judged as a placed call's.
    assert not any(
        NAME_FIELD in p for p in spoken_line_problems("opening_line", COLD_OPENING, LintContext())
    )
    # A "both" agent's placed-call opening is always one.
    assert any(
        NAME_FIELD in p
        for p in spoken_line_problems("outbound_opening_line", COLD_OPENING, LintContext())
    )


def test_the_writer_gets_the_finding_in_its_repair_round() -> None:
    draft = CallScript(schema_version=2, opening_line=COLD_OPENING)
    problems = language_problems(draft, "en-IN", lint=OUTBOUND)
    assert any(p.startswith("opening_line: does not say the person's name") for p in problems)
    fixed = CallScript(schema_version=2, opening_line=NAMED_OPENING)
    assert not any("person's name" in p for p in language_problems(fixed, "en-IN", lint=OUTBOUND))


def test_a_merge_field_is_not_an_english_word_in_a_spoken_line() -> None:
    # Telugu and Hindi lines write every word in their own letters (D-861); the merge field
    # is replaced before anything is said, so its key is never heard.
    assert latin_words(f"{NAME_FIELD}, ?", "te-IN") == []
    assert latin_words("{{ lead_name }} {{village}}", "hi-IN") == []
    assert latin_words(f"{NAME_FIELD} app", "te-IN") == ["app"]


def test_a_step_that_explains_several_actions_at_once_is_found() -> None:
    explained = (
        "Tell them to open the app, then press Add Expense, then type this week's expense, "
        "then ask if they understood."
    )
    assert stacked_actions(explained)
    assert stacked_actions("1. Open the app. 2. Press Add Expense. 3. Type the amount.")
    assert not stacked_actions("Ask whether they have installed the app.")
    # The agent's own sequence in one turn is not the caller's to follow step by step: the
    # ready-made calling plans close this way.
    assert not stacked_actions(
        "Read back once: weekday, date, time and place. Then the true next step: noted for the "
        "team to confirm. Then close."
    )
    found = instruction_problems("stages.2.instruction", explained, LintContext())
    assert any("several actions in one go" in p and "step-by-step" in p for p in found)
    # Only a step's instruction: a goal may say "then".
    assert not any(
        "several actions" in p for p in instruction_problems("goal", explained, LintContext())
    )


def test_a_walkthrough_in_its_step_by_step_list_passes() -> None:
    stage = _stage(
        "s2",
        "Show how to add an expense",
        "Walk them through adding their first expense.",
        procedure=[
            ProcedureStep(action="Open the app", wait_for="They see the home screen"),
            ProcedureStep(action="Press Add Expense", wait_for="The form is open"),
        ],
    )
    script = CallScript(schema_version=2, stages=[stage])
    assert not any("several actions" in p for p in script_problems(script, LintContext()))


def test_a_business_question_no_step_asks_is_named() -> None:
    script = CallScript(
        schema_version=2,
        stages=[
            _stage("s1", "Check the install", "Ask whether they have installed the app."),
            _stage("s2", "Close", "Thank them and say goodbye."),
        ],
    )
    assert unasked_details(script, FIELDS) == ["Satisfaction level", "Suggestions for features"]
    findings = script_problems(script, LintContext(collect=FIELDS))
    assert (
        'script: no step asks for "Satisfaction level"; ask it in the step where the call '
        "reaches it, as one question." in findings
    )
    assert plain(findings[-1]).startswith('The script: no step asks for "Suggestions for features"')

    asked = script.model_copy(
        update={
            "stages": [
                *script.stages[:1],
                _stage("s3", "How it is going", "Ask how satisfied they are with the app."),
                _stage("s4", "Ideas", "Ask what features they would suggest adding."),
                *script.stages[1:],
            ]
        }
    )
    assert unasked_details(asked, FIELDS) == []
    # A step's own collect list names it outright.
    listed = script.model_copy(
        update={
            "stages": [
                _stage("s1", "Check", "Ask about the app.", collect=["Satisfaction level"]),
            ]
        }
    )
    assert "Satisfaction level" not in unasked_details(listed, FIELDS)


def test_details_are_not_judged_where_nothing_can_compare_them() -> None:
    # No steps: nowhere to ask, the details list still reaches the call.
    assert script_problems(CallScript(schema_version=2), LintContext(collect=FIELDS)) == []
    # A label with no English-letter word cannot be compared with English instructions.
    one = CallScript(schema_version=2, stages=[_stage("s1", "Ask", "Ask their name.")])
    assert unasked_details(one, ("?", "")) == []


def test_a_long_placed_call_opening_is_told_what_a_placed_opening_holds() -> None:
    placed = replace(_LONG_OPENING, places_calls=True)
    fix = next(f for f in readiness.score(placed, now=_NOW).fixes if f.component == "opening")
    assert fix.action == readiness.PLACED_OPENING_FIX
    fix = next(
        f for f in readiness.score(_LONG_OPENING, now=_NOW).fixes if f.component == "opening"
    )
    assert fix.action == readiness.ANSWERED_OPENING_FIX


def test_every_writer_of_an_outbound_opening_is_told_it_in_the_brief() -> None:
    assert NAME_FIELD in PLACED_OPENING_BRIEF
    assert PLACED_OPENING_BRIEF in CapabilityManifest(direction="outbound").brief_lines()
    for direction in ("inbound", "both", ""):
        assert PLACED_OPENING_BRIEF not in CapabilityManifest(direction=direction).brief_lines()
