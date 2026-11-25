"""A step list the person wrote reaches the script writer in their words, not the model's."""

from __future__ import annotations

import json
from pathlib import Path

from apps.api.agents.owner_plan import owner_plan
from apps.api.copilot.script_actions import _with_owners_steps

CASE = Path(__file__).resolve().parents[3] / (
    "tests/fixtures/script_writer_cases/cases/rytu_khata_owner_steps.json"
)
STEPS = json.loads(CASE.read_text(encoding="utf-8"))["instruction"]
FOLDED = " ".join(STEPS.split())

# What the model passed on, 25 Nov 2026 22:56 IST, for that list.
SUMMARY = (
    "Rewrite the introduction part of the script in Telugu. Right after the opening, state who "
    "is calling and from Rytu Khata. Only include this introduction step."
)


def test_the_persons_step_list_replaces_the_models_summary_of_it() -> None:
    ask = _with_owners_steps({"tone": "warm", "instruction": SUMMARY}, (STEPS,))
    assert ask == {"tone": "warm", "instruction": FOLDED}
    assert owner_plan(ask["instruction"]) is not None


def test_a_short_go_ahead_after_the_list_still_sends_the_list() -> None:
    ask = _with_owners_steps({"instruction": SUMMARY}, (STEPS, "yes, do it"))
    assert ask["instruction"] == FOLDED


def test_an_older_list_never_overrides_a_later_different_request() -> None:
    later = "Make the closing line warmer and mention they can call us any time with a doubt."
    ask = _with_owners_steps({"instruction": later}, (STEPS, "ok", later))
    assert ask["instruction"] == later


def test_a_request_with_no_step_list_is_passed_on_as_the_model_wrote_it() -> None:
    ask = _with_owners_steps({"instruction": SUMMARY}, ("Please make the intro warmer.",))
    assert ask["instruction"] == SUMMARY
    assert _with_owners_steps({}, ()) == {}


def test_a_model_request_that_already_keeps_the_plan_is_left_alone() -> None:
    ask = _with_owners_steps({"instruction": FOLDED}, ("unrelated",))
    assert ask["instruction"] == FOLDED
