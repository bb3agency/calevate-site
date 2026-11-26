"""One press of "Fix them first" clears every warning it was pressed for (founder, 10 Nov
2026): the put-live dialog said "2 lines to fix first" — a step saying nearly what an earlier
step says, and a detail no step asks for — and the fix it offered left one of them.

The fix is checked again with the check that named the lines; what is still there is
repaired, a detail no step asks for may be added to one step's details (so it is fixable in
any call language), and anything still left is told to the owner by name."""

from __future__ import annotations

import time
from typing import Any

from apps.api.agents import script_proposals
from apps.api.agents.script_lint import LintContext, script_problems
from apps.api.core.queue import WORKER_JOB_TIMEOUT_S
from apps.workers import script_proposal as worker
from apps.workers.extraction import ASSIST_LADDER_LEGS
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
FIXED_LINE = "Signing up takes two minutes: open the link we send you."


def test_the_founders_two_warnings_are_both_found() -> None:
    problems = script_problems(FLAGGED, LINT)
    assert [p.partition(": ")[0] for p in problems] == ["stages.1.sounds_like", "script"]


def test_a_detail_no_step_asks_for_may_be_added_to_one_steps_details() -> None:
    """FAILS IF: a fix cannot add the missing detail to a step's `collect`, the one way to ask
    for it that the check reads in any language, or takes any other detail with it."""
    written = _script(FIXED_LINE, collect=[DETAIL, "Their crop"])
    kept = script_proposals.kept_to_paths(
        written, FLAGGED, ["script", "stages.1.sounds_like"], unasked=(DETAIL,)
    )
    assert kept.stages[1].collect == [DETAIL]
    assert [s.collect for s in kept.stages if s.id != "signup"] == [[], []]
    assert script_problems(kept, LINT) == []
    # Without the finding about the whole script, no detail is taken.
    alone = script_proposals.kept_to_paths(written, FLAGGED, ["stages.1.sounds_like"])
    assert alone.stages[1].collect == []


def test_the_writer_is_told_the_real_place_of_each_finding() -> None:
    """FAILS IF: the writer reads the owner's "Step 2" against a JSON list counted from 0,
    and so is pointed at the step after the one the check named."""
    change = script_proposals.fix_change(script_problems(FLAGGED, LINT), FLAGGED)
    assert 'stages.1.sounds_like (step id "signup", named "Signup")' in change
    assert '"collect"' in change


def test_a_repair_is_started_only_with_time_for_it_inside_the_job() -> None:
    """FAILS IF: a repair can start so late that arq's `job_timeout` kills it after the model
    was paid and before the meter row is written."""
    assert worker._repair_timeout(time.monotonic()) == worker.PROPOSAL_REQUEST_TIMEOUT_S
    assert worker._repair_timeout(time.monotonic() - 150) is None
    late = worker._repair_timeout(time.monotonic() - 100)
    assert late is not None
    used = 100 + ASSIST_LADDER_LEGS * late + worker._OPENINGS_BUDGET_S
    assert used + worker._JOB_MARGIN_S <= WORKER_JOB_TIMEOUT_S
