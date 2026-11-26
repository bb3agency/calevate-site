"""One press of "Fix them first" clears every warning it was pressed for (founder, 10 Nov
2026): the put-live dialog said "2 lines to fix first" — a step saying nearly what an earlier
step says, and a detail no step asks for — and the fix it offered left one of them.

The fix is checked again with the check that named the lines; what is still there is
repaired, a detail no step asks for may be added to one step's details (so it is fixable in
any call language), and anything still left is told to the owner by name."""

from __future__ import annotations

from typing import Any

from apps.api.agents.script_lint import LintContext, script_problems
from calevate_shared.call_script import CallScript, ConversationStage

DETAIL = "Is currently using the app?"
SAID_BEFORE = "Rytu Khata app lets you keep your farm accounts on your phone easily."
LINT = LintContext(collect=(DETAIL,), promo=False)


def _stage(stage_id: str, instruction: str, line: str, collect: list[str] | None = None) -> Any:
    return ConversationStage(
        id=stage_id, name=stage_id.title(), instruction=instruction, sounds_like=line,
        collect=collect or [],
    )  # fmt: skip


def _script(second_line: str = SAID_BEFORE, collect: list[str] | None = None) -> CallScript:
    return CallScript(
        schema_version=2,
        stages=[
            _stage("intro", "Tell them what the Rytu Khata app does for farmers.", SAID_BEFORE),
            _stage("signup", "Explain how they can sign up.", second_line, collect),
            _stage("close", "Thank them and end the call.", "Thank you, have a good day."),
        ],
    )


FLAGGED = _script()
FIXED_LINE = "Signing up takes two minutes: open the link we send and enter your village."


def test_the_founders_two_warnings_are_both_found() -> None:
    problems = script_problems(FLAGGED, LINT)
    assert [p.partition(": ")[0] for p in problems] == ["stages.1.sounds_like", "script"]
