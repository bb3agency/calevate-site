"""Every trade has a step plan for every job, and a plan is structure only (D-856, D-962).

The plans (`apps/api/agents/trade_playbooks.py`) feed the starters and the AI script writer.
They hold no spoken words: what a step sounds like is written per business.
"""

from __future__ import annotations

import pytest
from apps.api.agents.starters import CATALOGUE, STARTER_JOBS, TRADES, with_example_lines
from apps.api.agents.trade_playbooks import (
    JOB_SHAPES,
    TRADE_WORDS,
    playbook_for,
    playbook_guidance,
)
from calevate_shared.call_script import native_steps
from calevate_shared.spoken_guard import has_indic_letters


def test_every_trade_and_job_has_a_plan() -> None:
    assert set(TRADE_WORDS) == set(TRADES)
    assert set(STARTER_JOBS) <= set(JOB_SHAPES)
    for trade, basics in TRADES.items():
        for job in STARTER_JOBS:
            plan = playbook_for(trade, job, basics)
            assert plan.trade == trade and plan.job == job
            assert 4 <= len(plan.steps) <= 6, (trade, job)
            assert len(plan.objections) >= 3, (trade, job)
            for step in plan.steps:
                assert step.title and step.instruction and step.exit_when
                # English instructions only: no spoken line in any call language (D-962).
                assert not has_indic_letters(f"{step.instruction} {step.exit_when}")


def test_an_unknown_trade_gets_the_neutral_plan_and_an_unknown_job_is_refused() -> None:
    plan = playbook_for("bakery", "answer_calls", TRADES["custom"])
    assert plan.trade == "custom"
    with pytest.raises(KeyError):
        playbook_for("retail", "no_such_job", TRADES["retail"])


@pytest.mark.parametrize("language", ["te-IN", "hi-IN", "en-IN"])
def test_each_starter_is_built_from_its_plan_with_no_lines(language: str) -> None:
    for (trade, job), starter in CATALOGUE.items():
        plan = playbook_for(trade, job, TRADES[trade])
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
    assert [stage.sounds_like for stage in replaced.stages] == lines
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
    plan = playbook_for("real_estate", "call_leads", TRADES["real_estate"])
    for step in plan.steps:
        assert step.title in guide
    assert "answer calls" not in guide
    assert "Sounds like" not in guide and not has_indic_letters(guide)
    assert "Write each stage's example line yourself, for THIS business" in guide
    both = playbook_guidance("clinic", "both")
    assert "(answer calls)" in both and "(call leads)" in both
