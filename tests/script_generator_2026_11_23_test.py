"""The script generator's fixes from the Rytu Khata campaign script of 23 Nov 2026, held for
any business and language, and the step outcomes the founder asked for the same day.

The defects, each with the check that finds it and, where code can mend it without guessing,
the mend `script_structure.settled` makes before any paid repair:

1. a step's line in the call language greeted again after the opening;
2. a step no way out led to;
3. step numbers out of order, missing, or alternatives numbered as if one after the other;
4. an "already done" way out that ended the call while the main task had more (review);
5. tasks of the main task with no step (review, against the step outcomes);
6. a "call me later" step that asked for a time and noted none;
7. a title said where the person's name belongs, with no name;
8. a pronunciation for one spelling of the business name while another was spoken;
10. prices and bookings left on for a job with no price and no calendar;
11. answers promising what the sources never said (review claims).

Pure: no database and no model. Lines in the call language are romanised placeholders, never
product wording.
"""

from __future__ import annotations

import json

from apps.api.agents import script_proposals
from apps.api.agents.call_rules import opening_redone_line_problems
from apps.api.agents.script_lint import (
    CapabilityManifest,
    LintContext,
    empty_title_problems,
    flow_problems,
    pronunciation_problems,
    step_number_problems,
    step_outcome_problems,
    unreachable_problems,
    untaken_time_problems,
)
from apps.api.agents.script_structure import (
    CALL_BACK_TIME,
    policies_for_job,
    reached,
    renumbered,
    settled,
    time_taken,
    without_empty_titles,
)
from apps.workers import campaign_script
from apps.workers import campaign_script_ask as ask
from apps.workers.script_assist import _script_from_model_json
from apps.workers.script_proposal import text_at
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    OUTCOMES_HEADER,
    CallScript,
    ConversationStage,
    ExampleLine,
    Pronunciation,
    ScenarioQa,
    ScriptPolicies,
    SpeakingStyle,
    StageBranch,
    StepOutcome,
    compile_call_script,
    native_steps,
)
from calevate_shared.spoken_guard import empty_title, without_empty_title


def _stage(
    sid: str, name: str, instruction: str = "Ask one thing.", **kw: object
) -> ConversationStage:
    return ConversationStage(id=sid, name=name, instruction=instruction, **kw)  # type: ignore[arg-type]


def _script(*stages: ConversationStage, **kw: object) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line="Hello {{lead_name}}, this is Asha from Acme Farms. Can we talk now?",
        stages=list(stages),
        **kw,  # type: ignore[arg-type]
    )


# --- step outcomes: schema and compile -----------------------------------------------------


def test_a_script_without_outcomes_compiles_exactly_as_before() -> None:
    """FAILS IF: adding step outcomes changed what a script without any compiles to."""
    script = _script(_stage("s1", "Purpose"), _stage("s2", "Close"))
    body = compile_call_script(script)
    assert OUTCOMES_HEADER not in body
    assert all("This step is done when" not in step.detail for step in native_steps(script))


def test_each_step_outcome_compiles_as_what_the_step_must_reach_however_the_call_goes() -> None:
    """FAILS IF: an outcome is not in the instructions, is not said to be reached by any
    scenario, or does not say what happens when it clearly cannot be reached."""
    script = _script(
        _stage("s1", "Has the app", step=1),
        _stage("s2", "No app yet", step=1),
        _stage("s3", "Close", step=2),
        step_outcomes=[StepOutcome(step=1, outcome="The person says the app is open.")],
    )
    body = compile_call_script(script)
    assert OUTCOMES_HEADER in body
    assert "Step 1 (Has the app, No app yet): The person says the app is open." in body
    lead = body.split(OUTCOMES_HEADER, 1)[1].splitlines()[0]
    assert "not the only ways" in lead and "Otherwise" in lead
    steps = native_steps(script)
    assert steps[0].detail.endswith("Go on only when: The person says the app is open.")
    assert "Go on only when" not in steps[2].detail


def test_one_outcome_per_step() -> None:
    """FAILS IF: two outcomes for one step are accepted, leaving the model two goals."""
    try:
        _script(
            _stage("s1", "A", step=1),
            step_outcomes=[StepOutcome(step=1, outcome="x"), StepOutcome(step=1, outcome="y")],
        )
    except ValueError:
        return
    raise AssertionError("two outcomes for one step were accepted")


def test_the_writer_reads_outcomes_policies_and_mode_from_its_draft() -> None:
    """FAILS IF: a drafted step outcome is dropped, put on the wrong step once the stages are
    renumbered, or the drafted policies and "say" mode are ignored."""
    raw = {
        "stages": [
            {"name": "Close", "instruction": "Thank them.", "sounds_like": "Thanks.", "step": 9},
            {"name": "Purpose", "instruction": "Say why.", "sounds_like": "We call.", "step": 4},
            {"name": "Web", "mode": "say", "instruction": "acme.example", "step": 5},
        ],
        "step_outcomes": [
            {"step": 4, "outcome": "They know why we call"},
            {"step": 9, "outcome": "Closed"},
        ],
        "policies": {"share_prices": False, "take_bookings": False, "offer_call_backs": True},
    }
    script = _script_from_model_json(raw)
    assert [s.name for s in script.stages] == ["Purpose", "Web", "Close"]
    assert [(o.step, o.outcome) for o in script.step_outcomes] == [
        (1, "They know why we call"),
        (3, "Closed"),
    ]
    assert script.policies == ScriptPolicies(share_prices=False, take_bookings=False)
    assert script.stages[1].mode == "say"


# --- 1. re-greeting in a step's line in the call language ---------------------------------


def test_a_steps_line_in_the_call_language_that_greets_again_is_found() -> None:
    """FAILS IF: only the English example of a step is read for a second greeting, so the line
    in the caller's language greets again after the opening."""
    script = _script(
        _stage(
            "s1",
            "Purpose",
            sounds_like="We are calling about the app.",
            scripts={"te-IN": "Namaskaram, mee app gurinchi."},
        ),
        _stage("s2", "Close"),
    )
    found = opening_redone_line_problems(script)
    assert any(p.startswith("stages.0.scripts.te-IN:") for p in found)
    assert not any(p.startswith("stages.0.sounds_like") for p in found)


# --- 2. a step nothing leads to ---------------------------------------------------------------


def _with_lost_step() -> CallScript:
    return _script(
        _stage("s1", "Purpose", step=1, otherwise="s3"),
        _stage("s1-remind", "Remind later", step=1),
        _stage("s3", "Close", step=2),
    )


def test_a_step_no_way_out_leads_to_is_found_and_given_a_way_in() -> None:
    """FAILS IF: a step the call can never reach is accepted, or the mend gives it no way in."""
    script = _with_lost_step()
    assert unreachable_problems(script) and unreachable_problems(script)[0].startswith("stages.1:")
    mended = reached(script, {"s1-remind"})
    assert not unreachable_problems(mended)
    assert StageBranch(when="Remind later", target="s1-remind") in mended.stages[0].branches


def test_an_owners_step_nothing_leads_to_is_left_for_them() -> None:
    """FAILS IF: the mend rewires a step the owner wrote."""
    script = _with_lost_step()
    assert reached(script, set()) == script


# --- 3. step numbers ----------------------------------------------------------------------


def test_broken_step_numbers_are_found_and_renumbered_in_call_order() -> None:
    """FAILS IF: a missing step number or two steps numbered alike out of order is accepted, or
    the renumbering loses an outcome's step."""
    script = _script(
        _stage("s1", "Purpose", step=2),
        _stage("s2", "Install", step=None),
        _stage("s3", "Language", step=2),
        _stage("s4", "Close", step=5),
        step_outcomes=[StepOutcome(step=5, outcome="Closed")],
    )
    assert step_number_problems(script)
    fixed = renumbered(script)
    assert [s.step for s in fixed.stages] == [1, 2, 3, 4]
    assert not step_number_problems(fixed)
    assert [(o.step, o.outcome) for o in fixed.step_outcomes] == [(4, "Closed")]


def test_two_alternatives_numbered_one_after_the_other_share_a_step() -> None:
    """FAILS IF: two ways the same moment goes (Android or iPhone) stay two steps in a row."""
    script = _script(
        _stage(
            "s1",
            "Which phone",
            step=1,
            branches=[
                StageBranch(when="Android", target="s2"),
                StageBranch(when="iPhone", target="s3"),
            ],
        ),
        _stage("s2", "Android", step=2, otherwise="s4"),
        _stage("s3", "iPhone", step=3, otherwise="s4"),
        _stage("s4", "Close", step=4),
    )
    assert [s.step for s in renumbered(script).stages] == [1, 2, 2, 3]


def test_right_step_numbers_are_kept() -> None:
    """FAILS IF: numbers that already follow the call are changed."""
    script = _script(
        _stage("s1", "A", step=1), _stage("s2", "B", step=1), _stage("s3", "C", step=2)
    )
    assert renumbered(script) == script


def test_an_outcome_for_a_missing_step_and_a_step_without_one_are_found() -> None:
    script = _script(
        _stage("s1", "A", step=1),
        _stage("s2", "B", step=2),
        step_outcomes=[StepOutcome(step=1, outcome="x"), StepOutcome(step=3, outcome="y")],
    )
    found = step_outcome_problems(script)
    assert any("step 3 has an outcome and no scenario" in p for p in found)
    assert any("step 2 has no outcome" in p for p in found)


# --- 6. a call-back time asked for and lost -----------------------------------------------


def test_a_step_asking_when_to_call_back_notes_the_time_and_goes_to_the_call_back() -> None:
    """FAILS IF: a "busy, call later" step asks for a better time and keeps nothing of it."""
    script = _script(
        _stage("s1", "Purpose", branches=[StageBranch(when="They are busy", target="s2")]),
        _stage("s2", "Busy", "Ask for a better time to call them.", otherwise=END_OF_CALL),
        _stage("s3", "Close"),
    )
    assert untaken_time_problems(script) == [untaken_time_problems(script)[0]]
    assert untaken_time_problems(script)[0].startswith("stages.1.collect:")
    mended = time_taken(script, {"s2"})
    assert mended.stages[1].collect == [CALL_BACK_TIME]
    assert mended.stages[1].branches[0].target == CALL_BACK
    assert not untaken_time_problems(mended)


# --- 7. a title said with no name ---------------------------------------------------------


def test_a_title_where_the_name_belongs_with_no_name_is_found_and_taken_out() -> None:
    """FAILS IF: "<greeting> <title>," with no name passes, or the mend drops the greeting."""
    assert empty_title("Namaskaram garu, how are you?") == "garu"
    assert without_empty_title("Namaskaram garu, how are you?") == "Namaskaram, how are you?"
    assert empty_title("Namaskaram {{lead_name}} garu, how are you?") is None
    assert empty_title("Hello sir, how are you?") is None
    assert empty_title("ji, tell me.") is None
    script = _script(
        _stage("s1", "Purpose", sounds_like="Namaskaram garu, we call about the app."),
        _stage("s2", "Close"),
        example_exchange=[ExampleLine(speaker="agent", text="Namaste ji, a quick question.")],
    )
    assert {p.partition(":")[0] for p in empty_title_problems(script)} == {
        "stages.0.sounds_like",
        "example_exchange.0.text",
    }
    mended = without_empty_titles(script, {"s1", "s2"})
    assert mended.stages[0].sounds_like == "Namaskaram, we call about the app."
    assert mended.example_exchange[0].text == "Namaste, a quick question."
    assert not empty_title_problems(mended)


# --- 8. every spelling of a taught name ---------------------------------------------------


def test_every_spelling_of_a_taught_name_the_agent_says_is_taught_the_same_sound() -> None:
    """FAILS IF: a pronunciation for "AcmeFarms" leaves "Acme farms" in the AI sentence
    unpronounced."""
    script = _script(
        _stage("s1", "Purpose", sounds_like="This is about AcmeFarms."),
        style=SpeakingStyle(
            pronunciations=[Pronunciation(word="AcmeFarms", say_as="ak-mee farms")]
        ),
    )
    context = LintContext(spoken_elsewhere=("I am the AI assistant of Acme farms.",))
    assert pronunciation_problems(script, context)
    mended = settled(script, context)
    # The AI sentence the agent says outside the script counts as much as the script's lines.
    unopened = script.model_copy(update={"opening_line": ""})
    assert not pronunciation_problems(unopened, LintContext())
    assert pronunciation_problems(unopened, context)
    # Spellings are compared without case: the voice reads "Acme Farms" and "Acme farms" alike.
    assert [(p.word.casefold(), p.say_as) for p in mended.style.pronunciations] == [
        ("acmefarms", "ak-mee farms"),
        ("acme farms", "ak-mee farms"),
    ]
    assert not pronunciation_problems(mended, context)


# --- 10. policies the job cannot back -----------------------------------------------------


def test_prices_and_bookings_the_job_cannot_back_are_switched_off() -> None:
    """FAILS IF: a free app-install job with no calendar keeps prices and bookings on, or a
    policy is ever switched on by the mend."""
    free = policies_for_job(
        ScriptPolicies(), sources="Help farmers install the app.", manifest=CapabilityManifest()
    )
    assert free == ScriptPolicies(share_prices=False, take_bookings=False, offer_call_backs=True)
    priced = policies_for_job(
        ScriptPolicies(),
        sources="The plan costs Rs 499 a year.",
        manifest=CapabilityManifest(booking_tool=True),
    )
    assert priced == ScriptPolicies()
    off = ScriptPolicies(share_prices=False)
    assert policies_for_job(off, sources="Rs 499", manifest=None).share_prices is False


# --- the whole mend on the shape that exposed it ------------------------------------------


def test_settled_mends_the_rytu_khata_shape_and_leaves_no_flow_finding_it_can_mend() -> None:
    """FAILS IF: the structural mend leaves a lost step, broken numbers, a lost call-back time
    or a nameless title on a script written whole."""
    script = _script(
        _stage(
            "s1", "Purpose", step=1, sounds_like="Namaskaram garu, about the app.", otherwise="s3"
        ),
        _stage("s1-remind", "Busy", "Ask for a better time to call.", step=2),
        _stage("s3", "Install", step=2),
        _stage("s4", "Close", step=None),
    )
    mended = settled(script, LintContext())
    left = flow_problems(mended)
    assert not [p for p in left if "never reaches" in p or "step numbers" in p]
    assert not untaken_time_problems(mended) and not empty_title_problems(mended)


# --- the review: coverage, dead ends, grounding --------------------------------------------


def test_the_review_reads_step_outcomes_ways_out_answers_and_the_example() -> None:
    """FAILS IF: the review cannot see which step covers which task, where a step goes, a
    step's answers, or the example call."""
    script = _script(
        _stage(
            "s1",
            "Purpose",
            step=1,
            branches=[StageBranch(when="Already installed", target=END_OF_CALL)],
            qa=[ScenarioQa(question="Is my data safe?", answer="Yes, very safe.")],
        ),
        step_outcomes=[StepOutcome(step=1, outcome="They know why we call")],
        example_exchange=[ExampleLine(speaker="agent", text="Hello.")],
    )
    parts = {part.key: part.text for part in ask.reviewed_parts(script, None)}
    assert parts["step_outcomes"] == "Step 1 (Purpose): They know why we call"
    assert "when Already installed -> end" in parts["stages.s1"]
    assert "Is my data safe? -> Yes, very safe." in parts["stages.s1"]
    assert parts["example_exchange"] == "agent: Hello."


def test_missing_tasks_and_dead_ends_are_kept_and_routed_to_what_a_repair_may_rewrite() -> None:
    """FAILS IF: a second missing task is dropped, a missing task is accepted on a step, or a
    dead end's repair may not rewrite where the step goes."""
    raw = {
        "notes": [{"part": "stages.s1", "why": "From the main task."}],
        "claims": [],
        "problems": [
            {"part": "step_outcomes", "kind": "missing_task", "detail": "record sales"},
            {"part": "step_outcomes", "kind": "missing_task", "detail": "dashboard summary"},
            {"part": "stages.s1", "kind": "missing_task", "detail": "not here"},
            {"part": "stages.s1", "kind": "dead_end", "detail": "already installed ends"},
        ],
    }
    review = ask.parsed_review(raw, ["stages.s1", "step_outcomes"])
    assert review is not None
    outcomes = review.problems("step_outcomes")
    assert (
        len(outcomes) == 2 and "record sales" in outcomes[0] and "dashboard summary" in outcomes[1]
    )
    assert review.weak_kinds["stages.s1"] == frozenset({"dead_end"})
    script = _script(
        _stage(
            "s1",
            "Purpose",
            sounds_like="About the app.",
            branches=[StageBranch(when="Done", target=END_OF_CALL)],
        ),
        step_outcomes=[StepOutcome(step=1, outcome="x")],
    )
    found = campaign_script.review_findings(review, script)
    assert "stages.0.branches" in {n.finding.partition(":")[0] for n in found.noted}
    assert [left.part for left, _ in found.warned] == ["step_outcomes", "step_outcomes"]


def test_a_promise_in_a_quick_fact_is_a_claim_the_repair_may_rewrite() -> None:
    """FAILS IF: an unsourced quick-fact answer can only be warned about, never repaired."""
    script = _script(
        _stage("s1", "Purpose"),
        faqs=[{"question": "Forgot password?", "answer": "Our team will message you a new one."}],  # type: ignore[list-item]
    )
    raw = {
        "notes": [{"part": "faqs", "why": "Callers ask."}],
        "claims": [
            {
                "part": "faqs",
                "claim": "team sends a password",
                "evidence": "",
                "about_person": False,
                "asked": False,
            }
        ],
        "problems": [],
    }
    review = ask.parsed_review(raw, ["faqs"], sources="MAIN TASK: help them use the app")
    assert review is not None and "faqs" in review.unsourced
    found = campaign_script.review_findings(review, script)
    assert [n.finding.partition(":")[0] for n in found.noted] == ["faqs.0.answer"]
    assert "promise of what the business or its team will do" in ask.REVIEW_INSTRUCTION


# --- a repair may rewrite where a step goes -------------------------------------------------


def test_a_fix_of_a_steps_ways_out_takes_them_and_its_otherwise_together() -> None:
    """FAILS IF: a dead end's repair cannot change where the step goes, or changes another
    step's ways out."""
    base = _script(
        _stage("s1", "Purpose", branches=[StageBranch(when="Done", target=END_OF_CALL)]),
        _stage("s2", "Install", branches=[StageBranch(when="Busy", target=CALL_BACK)]),
        _stage("s3", "Close"),
    )
    written = base.model_copy(
        update={
            "stages": [
                base.stages[0].model_copy(
                    update={"branches": [StageBranch(when="Done", target="s3")], "otherwise": "s2"}
                ),
                base.stages[1].model_copy(update={"branches": []}),
                base.stages[2],
            ]
        }
    )
    kept = script_proposals.kept_to_paths(written, base, ["stages.0.branches"])
    assert kept.stages[0].branches == [StageBranch(when="Done", target="s3")]
    assert kept.stages[0].otherwise == "s2"
    assert kept.stages[1].branches == base.stages[1].branches
    assert json.loads(text_at(kept, "stages.0.branches") or "[]")[0]["target"] == "s3"


def test_the_writers_rules_carry_the_founders_rules() -> None:
    """FAILS IF: the ask stops telling the writer to give each task a step outcome, to go on
    from the opening without greeting again, or to ground every answer."""
    assert ask.OUTCOMES_RULE in ask.CAMPAIGN_ASK and ask.OUTCOMES_RULE in ask.LINE_ASK
    assert "never greets" in ask.OUTCOMES_RULE
    assert "reassures" in ask.GROUNDING_RULE
    assert "step_outcomes" in ask.FLOW_ASK
