"""Every trade has a step plan for every job, and every line in it passes the call checks (D-856).

The plans (`apps/api/agents/trade_playbooks.py`) feed the starters and the AI script writer,
so a line here is a line an agent learns to say. Each one is held to the checks the practice
tests run on a live reply (`agents/turn_checks.turn_problems`), to the textbook-word list
(`spoken_guard.textbook_words`) and to the writer's own rules (`call_rules.said_line_problem`):
a line the plan teaches can never be a line the tests then fail.
"""

from __future__ import annotations

import re

import pytest
from apps.api.agents.call_rules import said_line_problem
from apps.api.agents.starters import CATALOGUE, STARTER_JOBS, TRADES, with_example_lines
from apps.api.agents.trade_playbooks import (
    ALL_LINES,
    JOB_SHAPES,
    PLAYBOOK_LANGUAGES,
    TRADE_WORDS,
    VALUE_STEP_TITLE,
    is_playbook_line,
    playbook_for,
    playbook_guidance,
)
from apps.api.agents.turn_checks import turn_problems
from calevate_shared.call_script import SOUNDS_LIKE_MAX, native_steps
from calevate_shared.spoken_guard import has_indic_letters, textbook_words

_SCRIPT: dict[str, re.Pattern[str]] = {
    "te-IN": re.compile("[ఀ-౿]"),
    "hi-IN": re.compile("[ऀ-ॿ]"),
}


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
                # The value step has no example line: what it says is a fact (D-945).
                assert set(step.say) == set(PLAYBOOK_LANGUAGES) or (
                    not step.say and step.title == VALUE_STEP_TITLE
                ), (trade, job, step.title)


def test_an_unknown_trade_gets_the_neutral_plan_and_an_unknown_job_is_refused() -> None:
    plan = playbook_for("bakery", "answer_calls", TRADES["custom"])
    assert plan.trade == "custom"
    with pytest.raises(KeyError):
        playbook_for("retail", "no_such_job", TRADES["retail"])


@pytest.mark.parametrize("language", PLAYBOOK_LANGUAGES)
def test_every_example_line_passes_the_call_checks(language: str) -> None:
    for said in ALL_LINES:
        line = said[language]
        assert line.strip() and len(line) <= SOUNDS_LIKE_MAX, line
        assert not re.search(r"\d", line), line
        assert textbook_words(line, language) == [], line
        assert turn_problems(line, language=language) == [], (
            line,
            turn_problems(line, language=language),
        )
        assert said_line_problem("line", line) is None, line
        if language in _SCRIPT:
            assert _SCRIPT[language].search(line), line
        else:
            assert not has_indic_letters(line), line


def test_each_starter_is_built_from_its_plan_with_its_lines() -> None:
    for (trade, job), starter in CATALOGUE.items():
        plan = playbook_for(trade, job, TRADES[trade])
        assert [s.title for s in starter.steps] == [s.title for s in plan.steps]
        assert starter.objections == plan.objections
        for language in PLAYBOOK_LANGUAGES:
            script = starter.call_script(business="Acme", language=language)
            assert [stage.sounds_like for stage in script.stages] == [
                step.say.get(language, "") for step in plan.steps
            ]
            # Each step fits the engine's step and branches to the next, the last to the end.
            steps = native_steps(script)
            assert len(steps) == len(plan.steps)
            assert all(step.branches for step in steps)


def test_a_business_line_replaces_a_plan_line_but_never_a_persons() -> None:
    starter = CATALOGUE[("retail", "answer_calls")]
    script = starter.call_script(business="Acme", language="te-IN")
    assert all(is_playbook_line(stage.sounds_like) for stage in script.stages)
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
    assert not is_playbook_line("the owner's own line")


def test_the_writer_reads_the_plan_for_its_trade_direction_and_language() -> None:
    guide = playbook_guidance("real_estate", "outbound", "te-IN")
    plan = playbook_for("real_estate", "call_leads", TRADES["real_estate"])
    for step in plan.steps:
        assert step.title in guide and step.say.get("te-IN", "") in guide
    assert "answer calls" not in guide
    both = playbook_guidance("clinic", "both", "hi-IN")
    assert "(answer calls)" in both and "(call leads)" in both
    # A business type with no plan of its own reads the neutral one; a language with no lines
    # reads the plan without example lines.
    assert playbook_guidance("bakery", "inbound", "ta-IN").count("Sounds like") == 0
