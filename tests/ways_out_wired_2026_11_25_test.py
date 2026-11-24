"""A way out a step states only in words becomes that step's branch (founder, 25 Nov 2026: after
a Pip rewrite of the Rytu Khata flow every scenario said "If they cannot, offer to call back" in
its instruction, and the call flow showed no way out of any of them).

The detection and the mend are pure. The repair of an existing script runs against a real
database with Pip's writer replaced at its seam and made to fail if asked: the mend is code's.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents import script_heal
from apps.api.agents.script_lint import (
    CapabilityManifest,
    LintContext,
    script_problems,
    stated_ways_out,
    unwired_way_out_problems,
)
from apps.api.agents.script_structure import settled, ways_out_wired
from apps.workers import campaign_script_ask, script_assist
from apps.workers import script_heal as heal_job
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    HAND_OVER,
    MAX_STAGE_BRANCHES,
    CallScript,
    ConversationStage,
    StageBranch,
)
from tests.script_heal_2026_11_24_test import (
    OPENING,
    PLAIN,
    _account,
    _campaign,
    _payload,
    _queue,
    _row,
    _writer,
)

CANNOT = "Help them log in to the app. If they cannot, offer to call back."
CLOSE_LINE = "Thank you for your time, have a good day."


def _stage(sid: str, instruction: str, **extra: Any) -> ConversationStage:
    return ConversationStage.model_validate(
        {"id": sid, "name": sid, "instruction": instruction, **extra}
    )


def _ways(instruction: str, *, last: bool = False, **extra: Any) -> list[tuple[str, str]]:
    found = stated_ways_out(
        _stage("s", instruction, **extra), last_step=last, manifest=CapabilityManifest()
    )
    return [(b.when, b.target) for b in found]


def _script(*stages: ConversationStage) -> CallScript:
    return CallScript(schema_version=2, opening_line=OPENING, stages=list(stages))


# --- what counts as a stated way out -------------------------------------------------------


def test_the_founders_call_back_in_words_is_a_way_out() -> None:
    assert _ways(CANNOT) == [("They cannot", CALL_BACK)]


def test_ending_and_handing_over_are_read_either_way_round() -> None:
    assert _ways("If not interested, end politely.") == [("Not interested", END_OF_CALL)]
    assert _ways("End the call politely if they are the wrong person.") == [
        ("They are the wrong person", END_OF_CALL)
    ]
    on = CapabilityManifest(hand_over=True)
    found = stated_ways_out(
        _stage("s", "When they want a person, hand them over."), last_step=False, manifest=on
    )
    assert [(b.when, b.target) for b in found] == [("They want a person", HAND_OVER)]


def test_two_ways_out_in_one_instruction_are_both_read() -> None:
    assert _ways("If they are busy, offer a call back; if not interested, end politely.") == [
        ("They are busy", CALL_BACK),
        ("Not interested", END_OF_CALL),
    ]


def test_what_is_not_a_way_out_is_left_alone() -> None:
    # Unconditional, negated, or two conditions where the way out could hang on either.
    assert _ways("Thank them and end the call.") == []
    assert _ways("If they are busy, do not end the call; offer to call back.") == []
    assert _ways("If they agree, explain the steps and end politely when they are done.") == []
    # An end in the call's last step: the call ends there anyway.
    assert _ways("If they have no questions, end politely.", last=True) == []


def test_a_way_out_the_step_has_or_cannot_hold_is_not_added() -> None:
    had = [StageBranch(when="They are busy", target=CALL_BACK)]
    assert _ways(CANNOT, branches=had) == []
    assert _ways(CANNOT, otherwise=CALL_BACK) == []
    full = [StageBranch(when=f"Case {n}", target=END_OF_CALL) for n in range(MAX_STAGE_BRANCHES)]
    assert _ways(CANNOT, branches=full) == []


def test_a_hand_over_is_not_wired_where_hand_over_is_off() -> None:
    off = stated_ways_out(
        _stage("s", "If they want a person, hand them over."),
        last_step=False,
        manifest=CapabilityManifest(hand_over=False),
    )
    assert off == []


# --- the lint, and the mend ----------------------------------------------------------------


def test_the_lint_names_a_way_out_left_in_words() -> None:
    script = _script(_stage("login", CANNOT, step=1), _stage("close", "Thank them.", step=2))
    problems = unwired_way_out_problems(script)
    assert len(problems) == 1
    assert problems[0].startswith("stages.0.branches:")
    assert "call_back" in problems[0]
    assert any(p.startswith("stages.0.branches:") for p in script_problems(script, LintContext()))


def test_the_mend_adds_the_branch_and_keeps_the_words() -> None:
    script = _script(_stage("login", CANNOT, step=1), _stage("close", "Thank them.", step=2))
    mended = ways_out_wired(script, {"login", "close"}, None)
    assert mended.stages[0].branches == [StageBranch(when="They cannot", target=CALL_BACK)]
    assert mended.stages[0].instruction == CANNOT
    assert unwired_way_out_problems(mended) == []
    # Nothing to wire: the same object back.
    assert ways_out_wired(mended, {"login", "close"}, None) is mended


def test_the_writer_turns_a_way_out_in_words_into_a_branch() -> None:
    draft = _script(_stage("login", CANNOT, step=1), _stage("close", "Thank them.", step=2))
    written = settled(draft, LintContext())
    assert written.stages[0].branches == [StageBranch(when="They cannot", target=CALL_BACK)]
    # In an edit, the owner's untouched step keeps its shape.
    edited = settled(draft, LintContext(), base=draft)
    assert edited.stages[0].branches == []


def test_the_writers_are_told_a_way_out_is_never_only_words() -> None:
    assert "never only words in its instruction" in campaign_script_ask.OUTCOMES_RULE
    assert "has that as a way out too" in script_assist.WAYS_OUT_RULE


# --- the repair of an existing script ------------------------------------------------------


def test_the_repair_wires_every_step_of_an_existing_script() -> None:
    script = _script(_stage("login", CANNOT, step=1), _stage("close", "Thank them.", step=2))
    wired = script_heal.wired_ways_out(script, LintContext())
    assert wired.stages[0].branches == [StageBranch(when="They cannot", target=CALL_BACK)]


async def test_an_existing_campaign_is_wired_with_no_model_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _account("ways")
    script = _script(
        _stage("login", CANNOT, sounds_like=PLAIN),
        _stage("close", "Help them.", sounds_like=CLOSE_LINE, mode="say"),
    )
    campaign_id = await _campaign(tenant_id, agent_id, script)
    _writer(monkeypatch, None)
    await _queue(tenant_id, "campaign", campaign_id)

    outcome = await heal_job.repair_holder_script({}, _payload(tenant_id, "campaign", campaign_id))

    assert outcome == "repaired"
    row = await _row(tenant_id, "campaigns", campaign_id)
    saved = CallScript.model_validate(row.script)
    assert saved.stages[0].branches == [StageBranch(when="They cannot", target=CALL_BACK)]
    assert saved.stages[0].instruction == CANNOT
    assert row.script_heal_state == "done"
