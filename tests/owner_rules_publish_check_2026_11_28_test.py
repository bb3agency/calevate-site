"""The owner's "Never" rules, enforced at publish (W3.9, publish half).

A rule stays a pinned fact (D-1017); it is recognised by its wording, and a script line that
breaks it is a `block` finding with the step named, so Put it live and Start refuse it while
Save keeps it. A line that says it will NOT do the forbidden thing keeps the rule.
"""

from __future__ import annotations

from apps.api.agents import script_checks
from apps.api.agents.script_lint import LintContext, OwnerRule, owner_prohibitions
from calevate_shared.call_script import CallScript, ConversationStage, StepExamples

EN = "en-IN"
NO_CALL_BACK_TIME = "Never promise a call-back time."


def _script(*turns: str, instruction: str = "Answer what they ask.") -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line="Hello {{lead_name}}, this is Asha from Acme Farms. Is now a good time?",
        stages=[
            ConversationStage(
                id="help",
                name="Help",
                instruction=instruction,
                examples={EN: StepExamples(turns=list(turns))},
            )
        ],
    )


def _found(script: CallScript, *facts: str) -> list[script_checks.Finding]:
    lint = LintContext(language=EN, owner_rules=owner_prohibitions(facts))
    return [f for f in script_checks.run(script, lint) if f.check == "owner_rule"]


def test_never_rules_are_read_from_the_pinned_facts_in_the_owners_words() -> None:
    rules = owner_prohibitions(
        [
            NO_CALL_BACK_TIME,
            "Do not offer discounts",
            "We are open 9 to 6.",
            "Never talk about politics.",
            "never promise a call-back time.",
        ]
    )
    assert rules == (
        OwnerRule(NO_CALL_BACK_TIME, "call_back_time"),
        OwnerRule("Do not offer discounts", "discount"),
    )


def test_a_script_offering_a_call_back_time_is_refused_at_publish_with_the_step_named() -> None:
    script = _script("Sure, we will call you back at 5 PM today.")
    found = _found(script, NO_CALL_BACK_TIME)
    assert [f.path for f in found] == ["stages.0.examples.en-IN.turns.0"]
    assert found[0].severity == "block"
    assert NO_CALL_BACK_TIME in found[0].problem
    assert script_checks.blocking(
        script_checks.run(
            script, LintContext(language=EN, owner_rules=owner_prohibitions([NO_CALL_BACK_TIME]))
        )
    )


def test_an_instruction_that_has_the_agent_promise_the_time_breaks_it_too() -> None:
    script = _script(
        "I will note that for the team.",
        instruction="Offer a call back and agree the exact time with them.",
    )
    assert [f.path for f in _found(script, NO_CALL_BACK_TIME)] == ["stages.0.instruction"]


def test_a_call_back_with_no_time_and_a_refusal_both_keep_the_rule() -> None:
    script = _script(
        "The team will call you back.",
        "I can't give you a time for the call back, the team will confirm it.",
    )
    assert _found(script, NO_CALL_BACK_TIME) == []


def test_a_discount_rule_refuses_a_discount_and_keeps_a_no() -> None:
    offered = _script("You get ten percent off today, a special discount.")
    assert len(_found(offered, "Do not offer discounts")) == 1
    refused = _script("We do not give a discount, but the price includes delivery.")
    assert _found(refused, "Do not offer discounts") == []


def test_with_no_rules_the_check_reads_nothing() -> None:
    assert _found(_script("We will call you back at 5 PM.")) == []
