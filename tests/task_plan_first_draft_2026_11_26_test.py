"""A first script is held to the main task's numbered list as exactly as to an owner's own
step list (founder, 26 Nov 2026).

A main task written as plain numbered sentences ("1. Find out whether it is installed ...")
gives `owner_plan` no names or outcomes, so the first draft at creation had only the items as
guidance and no check. One small pass now reads the list as steps, one per item:

1. The answer becomes a plan only when it keeps one step per item, in order.
2. A first draft is written and checked against that plan, and the owner reads how Pip read
   their main task beside the step outcomes; the main task itself is unchanged.
3. An answer that changes the count, or that cannot be read, leaves the draft as it was.
4. No pass runs when the main task already lays out a plan, or for an edit of a script.

The model is never called: the writer and the reading are replaced.
"""

from __future__ import annotations

from typing import Any

from apps.api.agents.owner_plan import numbered_items, owner_plan
from apps.workers.campaign_script_ask import (
    task_steps_note,
    task_steps_text,
)
from scripts import eval_script_writer as ev

RYTU = ev.load_cases(["rytu_khata_install"])[0]

#: Six steps for the case's six numbered items, in their order.
SIX: list[dict[str, Any]] = [
    {
        "name": "Check the app",
        "does": "Ask whether it is installed as an app; if not, explain why the app is better.",
        "outcome": "They say whether the app is installed.",
        "ways_out": [{"when": "Already installed", "to": "Set up farms"}],
    },
    {
        "name": "Install the app",
        "does": "Help them install it on Android or iPhone, screen by screen, and set the "
        "language.",
        "outcome": "The app is installed in their language.",
        "ways_out": [{"when": "Cannot install it", "to": "call_back"}],
    },
    {
        "name": "Open the dashboard",
        "does": "Confirm it is installed and take them to the dashboard.",
        "outcome": "They see the dashboard.",
        "ways_out": [],
    },
    {
        "name": "Set up farms",
        "does": "Help them set up their farms.",
        "outcome": "Their farm is added.",
        "ways_out": [],
    },
    {
        "name": "Enter expenses",
        "does": "Help them enter their expenses.",
        "outcome": "An expense is entered.",
        "ways_out": [],
    },
    {
        "name": "Enter sales",
        "does": "Help them enter their sales and show the dashboard totals.",
        "outcome": "A sale is entered and they saw the totals.",
        "ways_out": [],
    },
]


def test_the_answer_becomes_a_plan_with_one_step_per_item_and_its_ways_out() -> None:
    items = numbered_items(RYTU.main_task)
    assert len(items) == 6 and items[0].startswith("Find out whether it is installed")
    # Plain numbered sentences are not a plan of their own.
    assert owner_plan(RYTU.main_task) is None
    text = task_steps_text({"steps": SIX})
    assert text is not None
    plan = owner_plan(text)
    assert plan is not None
    assert [s.name for s in plan.steps] == [step["name"] for step in SIX]
    assert plan.steps[0].outcome == "They say whether the app is installed."
    assert [(b.when, b.goes_to) for b in plan.steps[0].branches] == [
        ("Already installed", "Set up farms")
    ]
    assert [(b.when, b.goes_to) for b in plan.steps[1].branches] == [
        ("Cannot install it", "call_back")
    ]
    assert task_steps_note(plan).startswith(
        "Pip read your main task as these steps: 1. Check the app: They say whether"
    )
    # A colon in the model's words cannot start a label of its own.
    odd = task_steps_text({"steps": [{**SIX[0], "does": "Ask: is it installed?"}, *SIX[1:]]})
    assert odd is not None and len(owner_plan(odd).steps) == 6  # type: ignore[union-attr]
    assert task_steps_text({"steps": []}) is None
    assert task_steps_text({"steps": [{"name": "A", "does": "", "outcome": "x"}]}) is None
