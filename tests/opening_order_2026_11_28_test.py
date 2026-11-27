"""A placed call's opening orients before it asks (founder, 28 Nov 2026).

The Rytu Khata calls of 27-28 Nov 2026 opened with the task ("I'm calling to help you install
the app on your phone") before the person knew who the business was or why they were rung,
and the first steps ("Introduction", "Why we called") then said who was calling and why
again. The opening now says who is calling, why this person is called (what they did that
led to the call) and asks whether now suits; the task waits for the first step.
"""

from __future__ import annotations

from apps.api.agents import script_checks
from apps.api.agents.call_rules import (
    OPENING_LINE_RULE,
    PLACED_FIRST_STAGE_RULE,
    PLACED_OPENING_RULE,
    SCRIPT_FLOW_RULE,
    placed_opening_problems,
    reason_redone_problems,
    task_first_problem,
)
from apps.api.agents.owner_plan import (
    PlanBranch,
    PlannedStep,
    opening_folded,
    opening_only,
    owner_plan,
)
from apps.api.agents.script_lint import PLACED_OPENING_BRIEF, CapabilityManifest, LintContext
from apps.api.agents.script_plan import plan_from_owner, without_opening_acts
from apps.workers.opening_line import OPENING_WRITER_INSTRUCTION, PLACED_TASK, opening_rules
from calevate_shared.call_script import CallScript, ConversationStage

#: The opening the founder heard on both calls, as the campaign's script held it.
LIVE_OPENING = (
    "{{lead_name}} గారు, Rytu Khata నుండి Varsha మాట్లాడుతున్నాను. మీ ఫోన్‌లో యాప్ "
    "ఇన్‌స్టాల్ చేయడంలో సాయం చేయడానికి కాల్ చేశాను. ఇప్పుడు మాట్లాడటానికి వీలుగా ఉందా?"
)
ORIENTED = (
    "Hello {{lead_name}}, this is Asha from Acme Farms, the farm accounts app. You registered "
    "on our website last week. Is now a good time to talk?"
)
PLACED = LintContext(
    manifest=CapabilityManifest(direction="outbound"), agent_name="Asha", business_name="Acme"
)


# --- the rule, said once to every writer ---------------------------------------------------


def test_the_rule_puts_the_persons_reason_before_the_question_and_the_task_after_it() -> None:
    assert "why this person is being called" in PLACED_OPENING_RULE
    assert "never the task the call will do" in PLACED_OPENING_RULE
    assert PLACED_OPENING_RULE in OPENING_LINE_RULE
    assert "the task and the business's own questions wait" in OPENING_LINE_RULE
    assert PLACED_FIRST_STAGE_RULE in SCRIPT_FLOW_RULE
    assert "never the task" in PLACED_OPENING_BRIEF
    assert "never the task the call will do" in OPENING_WRITER_INSTRUCTION
    assert "never the task the call will do" in PLACED_TASK
    rules = opening_rules("te-IN", names=("Acme",), placed=True, agent_name="Asha")
    assert PLACED_OPENING_RULE in rules


# --- (a) the opening that names the task first ---------------------------------------------


def test_the_live_opening_is_sent_back_for_naming_the_task() -> None:
    found = placed_opening_problems(
        "opening_line", LIVE_OPENING, agent_name="Varsha", business_name="Rytu Khata"
    )
    assert len(found) == 1 and "names the task for this call" in found[0]


def test_an_opening_that_says_who_and_why_and_asks_passes() -> None:
    assert (
        placed_opening_problems(
            "opening_line", ORIENTED, agent_name="Asha", business_name="Acme Farms"
        )
        == []
    )


def test_the_task_words_are_read_in_english_too_but_not_a_past_sign_up() -> None:
    assert task_first_problem("opening_line", "I am calling to help you set it up.") is not None
    assert task_first_problem("opening_line", "Let us get you started today.") is not None
    assert task_first_problem("opening_line", "You signed up with us last week.") is None
    assert task_first_problem("opening_line", "You registered on our website.") is None


def test_the_registry_warns_on_a_placed_opening_only() -> None:
    script = CallScript(schema_version=2, opening_line=LIVE_OPENING)
    found = script_checks.run(script, PLACED, ids=("task_first_opening",))
    assert [f.path for f in found] == ["opening_line"]
    assert found[0].severity == "warn"
    answering = LintContext(manifest=CapabilityManifest(direction="inbound"))
    assert script_checks.run(script, answering, ids=("task_first_opening",)) == []


# --- (b) a first step that says who or why again ------------------------------------------


def _script(first: str, *, opening: str = ORIENTED) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=opening,
        stages=[
            ConversationStage(id="s1", name="First", instruction=first, step=1),
            ConversationStage(id="s2", name="Close", instruction="Thank them and close.", step=2),
        ],
    )


def test_a_first_step_told_to_say_why_again_is_found() -> None:
    script = _script(
        "Say we are calling because they registered on the website, then offer to set it up."
    )
    found = reason_redone_problems(script, PLACED)
    assert len(found) == 1 and found[0].startswith("stages.0.instruction:")
    assert PLACED_FIRST_STAGE_RULE in found[0]
    assert [f.check for f in script_checks.run(script, PLACED, ids=("reason_redone",))] == [
        "reason_redone"
    ]


def test_a_first_step_that_goes_on_with_the_offer_passes() -> None:
    script = _script("Say what the app lets them do in a sentence and offer to set it up now.")
    assert reason_redone_problems(script, PLACED) == []
    answering = LintContext(manifest=CapabilityManifest(direction="inbound"))
    why = _script("Say we are calling because they registered.")
    assert reason_redone_problems(why, answering) == []


# --- the plan: a step that only redoes the opening is folded into it ----------------------

OWNER_STEPS = (
    "Steps, in this order: "
    "1. Introduction: right after the opening, say who is calling and from Rytu Khata. "
    "Outcome: They know who is calling. - Busy now: offer a call back. "
    "2. Why we called: say what the app does and offer to set it up together now. "
    "Outcome: They agree to set it up. - Not interested: thank them and end the call. "
    "3. App on the home screen: ask them to look for the icon. Outcome: They see the icon. "
    "- Cannot find it: go to Introduction. "
    "4. Close: thank them and say goodbye. Outcome: The call is closed."
)


def test_an_introduction_step_is_folded_into_the_opening_on_a_placed_call() -> None:
    plan = owner_plan(OWNER_STEPS)
    assert plan is not None and opening_only(plan.steps[0])
    folded = opening_folded(plan)
    assert [(s.name, s.number) for s in folded.steps] == [
        ("Why we called", 1),
        ("App on the home screen", 2),
        ("Close", 3),
    ]
    # The introduction's ways out now belong to the step the call starts with.
    assert ("Busy now", "call_back") in [(b.when, b.goes_to) for b in folded.steps[0].branches]
    # A way into the introduction now goes to the step that replaced it.
    assert [b.goes_to for b in folded.steps[1].branches] == ["Why we called"]
    assert opening_folded(folded) == folded
    written = plan_from_owner(folded, placed=True)
    assert written.first is not None and written.first.name == "Why we called"


def test_a_first_step_with_a_job_of_its_own_is_kept() -> None:
    kept = PlannedStep(
        name="Introduction",
        instruction="Say who is calling, then explain the free soil test and offer one.",
        number=1,
    )
    assert not opening_only(kept)
    only = PlannedStep(name="Greeting", instruction="Greet them by name.", number=1)
    assert opening_only(only)
    two = (
        only,
        PlannedStep(name="Close", instruction="Close.", number=2, branches=(PlanBranch("x", ""),)),
    )
    from apps.api.agents.owner_plan import OwnerPlan

    assert opening_folded(OwnerPlan(two)).steps == two


def test_the_first_step_of_a_placed_plan_loses_who_is_calling_and_the_permission_ask() -> None:
    said = without_opening_acts(
        "right after the opening, say who is calling and from Rytu Khata, say we want to help "
        "them start using the app, then ask if now is a good time to talk."
    )
    assert said == "say we want to help them start using the app."


def test_the_first_step_of_a_placed_call_is_told_to_go_on_with_the_offer() -> None:
    from apps.api.agents.script_plan import plan_from_script
    from apps.workers.step_writer import StepAsk, step_request
    from tests.script_writer_rebuild_2026_11_26_test import LANG, _context, _script

    context = _context()
    plan = plan_from_script(_script())
    ask = StepAsk(
        brief=context.written_brief(),
        plan=plan,
        step=plan.steps[0],
        languages=(LANG,),
        opening=_script().opening_line,
    )
    assert PLACED_FIRST_STAGE_RULE in step_request(ask)
    later = StepAsk(
        brief=context.written_brief(), plan=plan, step=plan.steps[1], languages=(LANG,), opening=""
    )
    assert PLACED_FIRST_STAGE_RULE not in step_request(later)
