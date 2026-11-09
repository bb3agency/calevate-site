"""One press of "Fix them first" clears every warning it was pressed for (founder, 10 Nov
2026): the put-live dialog said "2 lines to fix first" — a step saying nearly what an earlier
step says, and a detail no step asks for — and the fix it offered left one of them.

The fix is checked again with the check that named the lines; what is still there is
repaired, a detail no step asks for may be added to one step's details (so it is fixable in
any call language), and anything still left is told to the owner by name."""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_builder, script_proposals
from apps.api.agents.script_lint import LintContext, script_problems
from apps.api.core.queue import WORKER_JOB_TIMEOUT_S
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers import script_proposal as worker
from apps.workers.extraction import ASSIST_LADDER_LEGS
from calevate_shared.call_script import CallScript, ConversationStage
from tests.conftest import create_org_with_receptionist

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


async def _fix_requested(script: CallScript) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Rytu Khata",
        slug=f"fixall-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    problems = script_problems(script, LINT)
    async with tenant_session(tenant_id) as session:
        await script_builder.save_draft(session, agent_id, script)
        proposal = await script_proposals.request_proposal(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            mode="change",
            change="Fix only these problems the script check found.",
            answers={},
            requested_by=uuid.uuid4(),
            paths=sorted({p.partition(": ")[0] for p in problems}),
        )
    return tenant_id, agent_id, proposal.id


def _answer(script: CallScript) -> Any:
    return SimpleNamespace(
        script=script,
        capability=SimpleNamespace(disclosure=None),
        usage=None,
        model="gemini-2.5-flash-lite",
        earlier=(),
        left_out=(),
    )


async def _run(
    monkeypatch: pytest.MonkeyPatch, answers: list[CallScript]
) -> tuple[script_proposals.ScriptProposal, list[str], list[str]]:
    tenant_id, agent_id, proposal_id = await _fix_requested(FLAGGED)
    changes: list[str] = []
    metered: list[str] = []

    async def write(_brief: Any, **kwargs: Any) -> Any:
        changes.append(kwargs["change"])
        return _answer(answers[min(len(changes), len(answers)) - 1])

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LINT

    async def meter_assist(_session: Any, **kwargs: Any) -> None:
        metered.append(kwargs["model"])

    async def meter_earlier(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "draft_script", write)
    monkeypatch.setattr(worker, "lint_context_for", lint_context)
    monkeypatch.setattr(crm_assist, "meter_assist", meter_assist)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter_earlier)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal_id),
    }
    assert await worker.draft_script_proposal({}, payload) == "ready"
    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.read_proposal(session, agent_id)
    assert stored is not None and stored.status == "ready" and stored.script is not None
    return stored, changes, metered


@pytest.mark.rls
async def test_one_fix_clears_both_warnings_it_was_pressed_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the fix keeps the reworded line but drops the detail the writer added to the
    step, leaving "no step asks for" on the script the owner is offered (founder's report)."""
    stored, changes, metered = await _run(monkeypatch, [_script(FIXED_LINE, collect=[DETAIL])])
    assert stored.script is not None
    assert script_problems(stored.script, LINT) == []
    assert len(changes) == 1 and len(metered) == 1
    assert stored.left_out == []


@pytest.mark.rls
async def test_a_warning_the_first_pass_left_is_repaired_and_each_pass_is_charged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a finding still on the fix after its one pass is offered to the owner as
    fixed, or a repair pass is not metered (hard rule 7)."""
    still_said = "Rytu Khata app lets you keep farm accounts on your phone easily."
    stored, changes, metered = await _run(
        monkeypatch,
        [_script(still_said, collect=[DETAIL]), _script(FIXED_LINE, collect=[DETAIL])],
    )
    assert stored.script is not None
    assert script_problems(stored.script, LINT) == []
    assert len(changes) == 2 and len(metered) == 2
    # The repair names only what was still there, at its real place.
    assert "stages.1.sounds_like" in changes[1] and '"collect"' not in changes[1]
    assert stored.left_out == []


@pytest.mark.rls
async def test_a_warning_no_pass_could_fix_is_told_to_the_owner_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a warning still there after the repairs is left out of the proposal without
    a word, so the owner reads the same warning again after using the fix."""
    stored, changes, _metered = await _run(monkeypatch, [_script(FIXED_LINE)])
    assert stored.script is not None
    assert [p.partition(": ")[0] for p in script_problems(stored.script, LINT)] == ["script"]
    # The second pass changed nothing, so no third was asked for.
    assert len(changes) == 2
    [left] = stored.left_out
    assert left.part == "script"
    assert script_proposals.part_label(left) == "The script"
    assert DETAIL in left.rule and left.rule.startswith("Still to fix:")


def test_a_repair_is_started_only_with_time_for_it_inside_the_job() -> None:
    """FAILS IF: a repair can start so late that arq's `job_timeout` kills it after the model
    was paid and before the meter row is written."""
    assert worker._repair_timeout(time.monotonic()) == worker.PROPOSAL_REQUEST_TIMEOUT_S
    assert worker._repair_timeout(time.monotonic() - 150) is None
    late = worker._repair_timeout(time.monotonic() - 100)
    assert late is not None
    used = 100 + ASSIST_LADDER_LEGS * late + worker._OPENINGS_BUDGET_S
    assert used + worker._JOB_MARGIN_S <= WORKER_JOB_TIMEOUT_S
