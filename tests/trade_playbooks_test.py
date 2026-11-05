"""Every trade has a step plan for every job, and a plan is structure only (D-856, D-962).

The plans (`apps/api/agents/trade_playbooks.py`) feed the starters and the AI script writer.
They hold no spoken words: what a step sounds like is written per business.
"""

from __future__ import annotations

import pytest
from apps.api.agents.business_fit import BusinessFit
from apps.api.agents.starters import CATALOGUE, STARTER_JOBS, TRADES, with_example_lines
from apps.api.agents.trade_playbooks import (
    JOB_SHAPES,
    NEXT_STEP_TITLE,
    VALUE_STEP_TITLE,
    playbook_for,
    playbook_guidance,
)
from apps.api.tenancy.business_copy import StarterWords
from calevate_shared.call_script import native_steps
from calevate_shared.spoken_guard import has_indic_letters


def test_every_trade_and_job_has_a_plan() -> None:
    assert set(STARTER_JOBS) <= set(JOB_SHAPES)
    for trade, basics in TRADES.items():
        for job in STARTER_JOBS:
            plan = playbook_for(job, basics)
            assert plan.job == job
            assert 4 <= len(plan.steps) <= 6, (trade, job)
            # Not judged yet: no price or sale objection (G2-3).
            assert len(plan.objections) >= 1, (trade, job)
            for step in plan.steps:
                assert step.title and step.instruction and step.exit_when
                # English instructions only: no spoken line in any call language (D-962).
                assert not has_indic_letters(f"{step.instruction} {step.exit_when}")


def test_an_unknown_job_is_refused() -> None:
    with pytest.raises(KeyError):
        playbook_for("no_such_job", TRADES["retail"])


def test_objections_and_value_topics_come_from_the_business_not_its_type() -> None:
    """A-18: a fixed table by business type put a clinic's medicine question, a property
    office's "prices are too high" and its "possession date" into the plan of any business
    filed under that type."""
    unjudged = {
        guide
        for trade in TRADES
        for guide in (playbook_guidance(trade, "outbound"), playbook_guidance(trade, "both"))
    }
    for guide in unjudged:
        for trade_only in (
            "what medicine to take",
            "possession date",
            "I already have a policy",
            "cheaper somewhere else",
            "The prices are too high",
            "The fees are too high",
            "a particular person",
            "the repair cost",
        ):
            assert trade_only not in guide, trade_only
    # A copy's own topics and objections are what the writer reads, whatever the type.
    own = BusinessFit(
        sells=True,
        objections=(("Is the app free to use?", "Say what the facts say about cost."),),
        words=StarterWords(
            answer_name="Help desk",
            calling_name="User follow-up",
            topics="the app, payments or account set-up",
            capture="their name and what they need help with",
            caution="Never ask for a password.",
        ),
    )
    for trade in ("clinic", "real_estate", "retail"):
        plan = playbook_for("call_leads", TRADES[trade], own)
        value = next(s for s in plan.steps if s.title == VALUE_STEP_TITLE)
        assert "the app, payments or account set-up" in value.instruction
        assert plan.objections[-1] == (
            "Is the app free to use?",
            "Say what the facts say about cost.",
        )


@pytest.mark.parametrize("language", ["te-IN", "hi-IN", "en-IN"])
def test_each_starter_is_built_from_its_plan_with_no_lines(language: str) -> None:
    for (trade, job), starter in CATALOGUE.items():
        plan = playbook_for(job, TRADES[trade])
        assert [s.title for s in starter.steps] == [s.title for s in plan.steps]
        assert starter.objections == plan.objections
        script = starter.call_script(business="Acme", language=language)
        assert all(not stage.sounds_like for stage in script.stages)
        # Each step fits the engine's step and branches to the next, the last to the end.
        steps = native_steps(script)
        assert len(steps) == len(plan.steps)
        assert all(step.branches for step in steps)


def test_a_business_line_fills_an_empty_step_but_never_a_persons() -> None:
    starter = CATALOGUE[("retail", "answer_calls")]
    script = starter.call_script(business="Acme", language="te-IN")
    lines = [f"Acme line {i}" for i in range(len(script.stages))]
    replaced = with_example_lines(script, lines)
    # The step that agrees the next step has no line of the business's (D-962).
    assert [stage.sounds_like for stage in replaced.stages] == [
        "" if stage.name == NEXT_STEP_TITLE else line
        for stage, line in zip(script.stages, lines, strict=True)
    ]
    edited = script.model_copy(
        update={
            "stages": [
                script.stages[0].model_copy(update={"sounds_like": "the owner's own line"}),
                *script.stages[1:],
            ]
        }
    )
    kept = with_example_lines(edited, lines)
    assert kept.stages[0].sounds_like == "the owner's own line"


def test_the_writer_reads_the_plan_for_its_trade_and_direction_with_no_words() -> None:
    guide = playbook_guidance("real_estate", "outbound")
    plan = playbook_for("call_leads", TRADES["real_estate"])
    for step in plan.steps:
        assert step.title in guide
    assert "answer calls" not in guide
    assert "Sounds like" not in guide and not has_indic_letters(guide)
    assert "Write each stage's example line yourself, for THIS business" in guide
    both = playbook_guidance("clinic", "both")
    assert "(answer calls)" in both and "(call leads)" in both
