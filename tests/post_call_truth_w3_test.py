"""Post-call truth, wave B (W3.5, W3.6, W3.9 judge half, W3.12).

* W3.5: a call's summary is two parts, the model's prose about what the caller wanted and
  said, and a code-built clause saying where the call got to against its script's steps; a
  suggested marker quoting the call's words sits only on a line that says them.
* W3.6: drafted and suggested lead details are what callers say, typed, never a judgement
  of the call that the steps and the outcomes already make.
* W3.9: an owner's "Never" rule among the pinned facts fails a practice conversation and is
  counted on a real call when a reply breaks it.
* W3.12: an outcome carries two short lines, when it counts and the nearest case when it
  does not, which the extraction prompt renders.

Nothing here names any one business.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from apps.api.agents import call_mistakes, call_outcomes
from apps.api.agents.call_rules import (
    OwnerRule,
    breaks,
    broken_rule,
    owner_rules,
    owner_rules_judge,
)
from apps.api.agents.test_conversations import AgentBrief, Judged, Scenario, Turn, decide
from apps.api.agents.turn_checks import IN_CALL_KINDS, JOB_KINDS
from apps.api.crm.step_progress import StepProgress, StepReading, side_steps, with_sides
from apps.workers import agent_test_ai, step_truth
from apps.workers.business_outcomes_draft import outcomes_from_model
from apps.workers.field_suggestions import Inputs, suggestions_from_model
from apps.workers.lead_fields_draft import SYSTEM_PROMPT as LEAD_FIELDS_PROMPT
from apps.workers.lead_fields_draft import fields_from_model
from apps.workers.moments import field_backed, quotes_the_call, said_on
from apps.workers.pipeline import _settle_summaries
from apps.workers.step_progress import step_names
from calevate_shared.business_outcomes import (
    CONDITION_MAX,
    STARTING_OUTCOMES,
    BusinessOutcome,
)
from calevate_shared.call_script import (
    END_OF_CALL,
    SCRIPT_SCHEMA_VERSION,
    CallScript,
    ConversationStage,
    StageBranch,
)
from calevate_shared.extraction import (
    ExtractionOutput,
    ExtractionSchemaSpec,
    build_extraction_prompt,
)
from pydantic import ValidationError

CALL_ID = "call-1"
GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_transcripts.json").read_text(encoding="utf-8")
)
#: What a summary may not say of a call whose last main step was not shown reached.
_COMPLETION = re.compile(
    r"\b(?:complet\w*|finish\w*|done|success\w*|(?:all|every|each)\s+(?:of\s+)?(?:the\s+)?steps?"
    r"|everything)\b",
    re.I,
)


# --- W3.5: the summary from the step state ------------------------------------------------


def _script(names: list[str]) -> CallScript:
    """A script of `names` in order; a name `side:X` is a step reached only by a way out of
    the step before it."""
    stages: list[ConversationStage] = []
    for n, raw in enumerate(names, 1):
        name = raw.removeprefix("side:")
        stages.append(
            ConversationStage(id=f"s{n}", step=n, name=name, instruction=f"Guide: {name}.")
        )
    for i, raw in enumerate(names):
        if raw.startswith("side:") and i > 0:
            before = stages[i - 1]
            stages[i - 1] = before.model_copy(
                update={
                    "branches": [StageBranch(when="They have not signed up", target=f"s{i + 1}")],
                    "otherwise": f"s{i + 2}",
                }
            )
            stages[i] = stages[i].model_copy(update={"otherwise": f"s{i + 2}"})
    stages[-1] = stages[-1].model_copy(update={"otherwise": END_OF_CALL})
    return CallScript(schema_version=SCRIPT_SCHEMA_VERSION, stages=stages)


def _facts(case: dict[str, Any]) -> step_truth.StepFacts:
    script = _script(case["steps"])
    names = step_names(script)
    states = {int(k): v for k, v in case["reading"].items()}
    progress = StepProgress(
        steps=tuple(
            StepReading(n, names[n], states.get(n, "unclear"), turn_idx=n * 2)  # type: ignore[arg-type]
            for n in names
        )
    )
    return step_truth.facts_of(script, with_sides(progress, side_steps(script)), [])


def _last_main_reached(facts: step_truth.StepFacts) -> bool:
    main = [n for n in facts.names if n not in facts.branches]
    return max(main) in facts.reached


CASES = GOLDEN["step_truth_cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_summary_says_where_the_call_got_to_and_never_claims_more(
    case: dict[str, Any],
) -> None:
    """FAILS IF: a stored summary says done, complete or all steps on a call whose last main
    step was not reached, or lacks the code-built clause (the golden step-truth cases)."""
    facts = _facts(case)
    settled, _ = step_truth.settle(
        ExtractionOutput(summary=case["model_summary"]),
        facts,
        ExtractionSchemaSpec(fields=[]),
        goal=None,
        outcomes=(),
    )
    english, _local, _source, _ = _settle_summaries(
        engine_summary=case["engine_summary"],
        model_summary=settled.summary,
        stored_local="",
        language="te-IN",
        facts=facts,
    )
    for summary in (settled.summary, english):
        assert summary.endswith(case["expect_clause"]), summary
        assert summary.count(case["expect_clause"]) == 1
        if not _last_main_reached(facts):
            prose = summary.removesuffix(case["expect_clause"])
            assert not _COMPLETION.search(prose), prose


def test_composing_twice_adds_the_clause_once() -> None:
    facts = _facts(CASES[0])
    once = step_truth.with_where_it_got_to("The caller logged in.", facts)
    assert step_truth.with_where_it_got_to(once, facts) == once


def test_no_prose_means_no_summary_rather_than_the_clause_alone() -> None:
    """A summary still to be written (the language pass writes it) is not replaced by the
    clause alone, which would leave the caller's words out for good."""
    assert step_truth.with_where_it_got_to("", _facts(CASES[0])) == ""


def test_without_a_reading_only_the_step_the_call_never_got_to_is_said() -> None:
    script = _script(["Greeting", "Install", "Record an expense"])
    from calevate_shared.events import TranscriptTurn

    turns = [
        TranscriptTurn(call_id=CALL_ID, idx=0, speaker="agent", text="Please install the app."),
        TranscriptTurn(call_id=CALL_ID, idx=1, speaker="caller", text="Okay, installed."),
        TranscriptTurn(call_id=CALL_ID, idx=2, speaker="agent", text="Now record an expense."),
    ]
    facts = step_truth.facts_of(script, None, turns)
    assert step_truth.where_it_got_to(facts) == 'The call did not get to "Record an expense".'
    finished = step_truth.facts_of(script, None, turns[:2])
    assert step_truth.where_it_got_to(finished) is None


def test_a_stopped_call_has_its_engine_summary_in_the_call_language_written_again() -> None:
    """The engine's Telugu summary is read by no check of ours, so on a call that stopped
    short it gives way to one written from the checked English."""
    facts = _facts(CASES[1])
    _english, local, _source, _ = _settle_summaries(
        engine_summary="అన్ని స్టెప్స్ పూర్తయ్యాయి.",
        model_summary="The caller installed the app.",
        stored_local="",
        language="te-IN",
        facts=facts,
    )
    assert local == ""


def test_the_prompt_keeps_the_summarys_prose_to_the_caller() -> None:
    prompt = build_extraction_prompt(
        ExtractionSchemaSpec(fields=[]), "caller: Hello.", steps="Reached: Greeting"
    )
    assert "The summary says only what the caller wanted and what they said." in prompt
    assert "never says\n  a step, the task or the call was done" in prompt


# --- W3.5: markers whose quote is absent from their turn ---------------------------------


def test_a_romanised_quote_is_a_quote_of_the_call() -> None:
    assert quotes_the_call("repu udayam vastanu ani chepparu")
    assert not quotes_the_call("Wants a call tomorrow morning")


def test_a_romanised_quote_on_a_line_that_does_not_say_it_is_dropped() -> None:
    """FAILS IF: a suggested marker keeps a romanised quote on a turn whose words are not it."""
    stored = [
        {"kind": "field_captured", "field": "timeline", "source": "model", "turn_idx": 3},
        {"kind": "field_captured", "field": "timeline", "source": "model", "turn_idx": 5},
    ]
    values = {"timeline": "aaru nelalo kavali ani chepparu"}
    texts = {3: "Sare andi, chustanu.", 5: "Aaru nelalo possession kavali."}
    kept = field_backed(
        stored, captured={"timeline"}, caller_turns={3, 5}, values=values, turn_texts=texts
    )
    assert [m["turn_idx"] for m in kept] == [5]


def test_a_quote_copied_with_a_zero_width_joiner_is_still_found() -> None:
    assert said_on("సెటప్‌పూర్తి", "సెటప్పూర్తి అయింది")


# --- W3.6: capture fields are data -------------------------------------------------------

#: What the Rytu Khata redraft returned on 28 Nov 2026, plus the values a job collects.
RYTU_DRAFT: dict[str, Any] = {
    "fields": [
        {"label": "Installation Status", "type": "enum", "reason": "x", "required": False,
         "choices": ["Installed", "Not installed"]},
        {"label": "Setup Progress", "type": "text", "reason": "x", "required": False,
         "choices": []},
        {"label": "Interaction Outcome", "type": "enum", "reason": "x", "required": False,
         "choices": ["Success", "Failed"]},
        {"label": "Campaign Goal Met", "type": "bool", "reason": "x", "required": False,
         "choices": []},
        {"label": "Crop grown", "type": "enum", "reason": "Which crop they grow.",
         "required": False, "choices": ["Paddy", "Cotton", "Chilli"]},
        {"label": "Acres farmed", "type": "number", "reason": "How many acres.",
         "required": False, "choices": []},
        {"label": "Harvest date", "type": "date", "reason": "When they harvest next.",
         "required": False, "choices": []},
    ]
}  # fmt: skip


def test_a_redraft_has_no_status_type_field_and_keeps_typed_values() -> None:
    """FAILS IF: a status, progress, outcome or goal detail is drafted beside the step reading
    and the outcomes that already say it (Rytu redraft acceptance)."""
    fields = fields_from_model(RYTU_DRAFT)
    assert [(f.label, f.type) for f in fields] == [
        ("Crop grown", "enum"),
        ("Acres farmed", "number"),
        ("Harvest date", "date"),
    ]
    assert "Never a status, progress, outcome, result or goal detail" in LEAD_FIELDS_PROMPT


def _inputs() -> Inputs:
    return Inputs(
        context="",
        fields=[],
        script="Ask when they harvest next and how many acres they farm.",
        purpose="",
        unlisted={},
        captured={},
        dismissed=frozenset(),
    )


def test_suggestions_never_offer_a_judgement_and_type_what_callers_say() -> None:
    raw = {
        "suggestions": [
            {"kind": "new_field", "field_key": None, "label": "Setup Status", "values": [],
             "type": "text", "hint": "x", "reason": "Helps follow up.", "source": "script",
             "evidence": "Ask when they harvest next"},
            {"kind": "new_field", "field_key": None, "label": "Next harvest", "values": [],
             "type": "date", "hint": "When they harvest.", "reason": "Helps follow up.",
             "source": "script", "evidence": "Ask when they harvest next"},
            {"kind": "new_field", "field_key": None, "label": "Acres", "values": [],
             "type": "number", "hint": "How many acres.", "reason": "Sizes the account.",
             "source": "script", "evidence": "how many acres they farm"},
        ]
    }  # fmt: skip
    out = suggestions_from_model(raw, _inputs())
    assert [(s.field_label, s.field.type if s.field else None) for s in out] == [
        ("Next harvest", "date"),
        ("Acres", "number"),
    ]


# --- W3.12: outcome definitions an owner can make precise --------------------------------


def test_an_outcome_carries_bounded_counts_when_and_not_when() -> None:
    outcome = BusinessOutcome(
        key="booked", label="Booked", counts_when="  They pick a day  ", not_when="Only asks"
    )
    assert (outcome.counts_when, outcome.not_when) == ("They pick a day", "Only asks")
    with pytest.raises(ValidationError):
        BusinessOutcome(key="booked", label="Booked", not_when="x" * (CONDITION_MAX + 1))
    # A list stored before the two lines existed still reads.
    assert call_outcomes.stored_outcomes([{"key": "booked", "label": "Booked"}]) == [
        BusinessOutcome(key="booked", label="Booked")
    ]


def test_the_prompt_renders_both_lines_and_a_wish_to_think_is_not_a_no() -> None:
    """FAILS IF: "I'll think about it" can read as "Not interested" for want of words that
    tell the two apart (golden cases re_think_about_it_*)."""
    prompt = build_extraction_prompt(
        ExtractionSchemaSpec(fields=[]), "caller: Let me think it over.", outcomes=STARTING_OUTCOMES
    )
    not_interested = next(o for o in STARTING_OUTCOMES if o.key == "not_interested")
    assert "time to think" in not_interested.not_when
    assert f"Not when: {not_interested.not_when}" in prompt
    assert f"Counts when: {not_interested.counts_when}" in prompt
    assert "wants time to think, asks to be called\n  later or says not now has not declined" in (
        prompt
    )
    cases = {c["id"]: c for c in GOLDEN["cases"]}
    for key in ("re_think_about_it_not_declined", "re_think_about_it_english"):
        assert cases[key]["expect_business_outcome_not"] == ["not_interested"]


def test_the_draft_reads_both_lines_and_cuts_them_at_a_word() -> None:
    out = outcomes_from_model(
        {
            "outcomes": [
                {
                    "label": "Wants a visit",
                    "meaning": "The caller wants to see it.",
                    "counts_when": "They name a day to come",
                    "not_when": "They only ask where it is " + "and more " * 20,
                    "lead_status": "hot",
                }
            ]
        }
    )
    assert out[0].counts_when == "They name a day to come"
    assert len(out[0].not_when) <= CONDITION_MAX and not out[0].not_when.endswith(" ")


# --- W3.9: the owner's Never rules, judged after the call --------------------------------

RULE = "Never promise a call-back time."
PINNED = [("", RULE), ("Is there parking?", "Yes, two cars."), ("", "Always greet politely.")]


def test_only_a_prohibition_is_a_rule_and_its_words_are_kept() -> None:
    rules = owner_rules(PINNED)
    assert rules == (OwnerRule(words=RULE, kind="call_back_time"),)
    assert owner_rules([("", "Do not offer a discount. We are open daily.")]) == (
        OwnerRule(words="Do not offer a discount.", kind="discount"),
    )
    assert owner_rules([("", "Never talk about competitors.")])[0].kind is None


@pytest.mark.parametrize(
    ("reply", "broken"),
    [
        ("Sure, I'll call you back at 5 PM.", True),
        ("Okay, we will call you back at 5.", True),
        ("Our team will call you back.", False),
        ("I can't give a time, but the team will call you back.", False),
        ("The shop opens at 5 PM.", False),
    ],
)
def test_a_call_back_with_a_time_breaks_the_rule(reply: str, broken: bool) -> None:
    assert breaks(reply, owner_rules(PINNED)[0]) is broken


def _brief(pinned: tuple[tuple[str, str, str], ...]) -> AgentBrief:
    return AgentBrief(
        business_name="A business",
        business_type="custom",
        direction="inbound",
        language="en-IN",
        register="",
        word_swaps=(),
        steps=(),
        opening_line="",
        ending="",
        objections=(),
        pinned_facts=pinned,
        knowledge_titles=(),
        lead_fields=(),
        hand_over="off",
        call_backs=True,
        call_is_recorded=True,
    )


SCENARIO = Scenario(
    key="call_me_at_5",
    title="Asks to be called at five",
    category="call_back",
    turns=("Can you call me at 5?",),
    expect="Takes the request; the team will confirm a time.",
)


def test_a_practice_caller_asking_for_5_fails_when_the_agent_promises_5_pm() -> None:
    """FAILS IF: an agent under "Never promise a call-back time" passes a practice caller
    who asked "call me at 5?" by promising 5 PM, whatever the judge said."""
    brief = _brief((("f1", "", RULE),))
    passed = Judged(verdict="passed", reason="It helped.")
    result = decide(
        SCENARIO,
        [Turn(said="Can you call me at 5?", reply="Sure, I'll call you back at 5 PM.")],
        passed,
        language="en-IN",
        unjudged_reason="n/a",
        rules=brief.rules(),
    )
    assert result["verdict"] == "failed"
    assert RULE in result["reason"]
    kept = decide(
        SCENARIO,
        [Turn(said="Can you call me at 5?", reply="I'll note it; the team will call you back.")],
        passed,
        language="en-IN",
        unjudged_reason="n/a",
        rules=brief.rules(),
    )
    assert kept["verdict"] == "passed"


async def test_the_judge_reads_the_owners_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    class _StopError(Exception):
        pass

    async def capture(description: str, instruction: str, **_: Any) -> Any:
        seen["description"] = description
        raise _StopError

    monkeypatch.setattr(agent_test_ai, "ask_json", capture)
    with pytest.raises(_StopError):
        await agent_test_ai.judge_conversations(
            _brief((("f1", "", RULE),)), ["[call_me_at_5] ..."], {"call_me_at_5"}
        )
    assert owner_rules_judge(owner_rules(PINNED)) in seen["description"]
    assert "call backs included" in seen["description"]


def test_a_real_call_counts_the_broken_rule_on_the_agents_line() -> None:
    from calevate_shared.events import TranscriptTurn

    turns = [
        TranscriptTurn(call_id=CALL_ID, idx=0, speaker="agent", text="Hello, how can I help?"),
        TranscriptTurn(call_id=CALL_ID, idx=1, speaker="caller", text="Call me back at five?"),
        TranscriptTurn(
            call_id=CALL_ID, idx=2, speaker="agent", text="Sure, I'll call you back at 5 PM."
        ),
    ]
    rules = owner_rules(PINNED)
    assert call_mistakes.owner_rule_mistakes(turns, rules) == {"owner_rule_broken": 2}
    assert call_mistakes.owner_rule_mistakes(turns, ()) == {}
    assert broken_rule("Hello.", rules) is None
    assert "owner_rule_broken" in JOB_KINDS and "owner_rule_broken" in IN_CALL_KINDS
    assert call_mistakes.LESSONS["owner_rule_broken"].label
