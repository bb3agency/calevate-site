"""Ways out in the scripts Pip writes, held to the Rytu Khata calls of 20-21 Nov 2026.

On those calls the person said they did not remember registering, or that there was nothing
for now and they would do it later, and the script had no way out for either: the agent
pushed on with its steps. The writer is now told which ways out the kind of call needs
(`script_assist.WAYS_OUT_RULE`), can draft them with platform targets (`ways_out`), and a
placed call's script lacking "not now" or an early end is sent back (`way_out_problems`).
"""

from __future__ import annotations

from typing import Any

from apps.api.agents.script_lint import LintContext
from apps.workers.script_assist import (
    NOT_INTERESTED_WAY_OUT,
    NOT_NOW_WAY_OUT,
    ScriptBrief,
    language_problems,
    way_out_problems,
)
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    CallScript,
    ConversationStage,
    StageBranch,
    compile_call_script,
)

BUSY = "They are busy now or say they will do it later"
NOT_FOR_THEM = "They are not interested or it is not for them"


def _stage(sid: str, *branches: StageBranch, otherwise: str = "") -> ConversationStage:
    return ConversationStage(
        id=sid,
        name=f"Step {sid}",
        instruction="Ask whether they have the app on this phone.",
        branches=list(branches),
        otherwise=otherwise,
    )


def _script(*stages: ConversationStage) -> CallScript:
    return CallScript(schema_version=2, stages=list(stages))


COVERED = _script(
    _stage(
        "s1",
        StageBranch(when=BUSY, target=CALL_BACK),
        StageBranch(when=NOT_FOR_THEM, target=END_OF_CALL),
    ),
    _stage("s2"),
    _stage("s3"),
)
BARE = _script(_stage("s1"), _stage("s2"), _stage("s3", otherwise=END_OF_CALL))


# --- 1. what the writer is told ---------------------------------------------------------------


# --- 2. reading a draft's ways out --------------------------------------------------------------


def _row(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "instruction": f"Do {name}.", "sounds_like": "", **extra}


def test_a_way_out_compiles_to_what_the_account_can_do() -> None:
    """FAILS IF: a "not now" way out reaches the call as anything but the platform's own
    call-back action."""
    text = compile_call_script(COVERED)
    assert f"When {BUSY}: Offer a call back." in text
    assert f"When {NOT_FOR_THEM}: End the call politely." in text


# --- 3. the writer check --------------------------------------------------------------------------


def test_a_placed_script_with_no_ways_out_is_sent_back() -> None:
    """FAILS IF: a script for placed calls passes with no "not now" and no early end, the
    shape of the 20-21 Nov 2026 script."""
    assert way_out_problems(BARE) == [NOT_NOW_WAY_OUT, NOT_INTERESTED_WAY_OUT]
    assert way_out_problems(COVERED) == []


def test_only_an_end_before_the_close_counts() -> None:
    """FAILS IF: the close's own end reads as a way out for someone not interested."""
    script = _script(
        _stage("s1", StageBranch(when=BUSY, target=CALL_BACK)),
        _stage("s2", otherwise=END_OF_CALL),
    )
    assert way_out_problems(script) == [NOT_INTERESTED_WAY_OUT]


def test_an_otherwise_counts_as_a_way_out() -> None:
    script = _script(_stage("s1", otherwise=CALL_BACK), _stage("s2", otherwise=END_OF_CALL))
    assert way_out_problems(script) == [NOT_INTERESTED_WAY_OUT]


def test_an_edit_is_held_only_to_what_it_removed() -> None:
    """FAILS IF: a one-part edit of the owner's script is refused for ways out the owner
    never had, or one that deletes a way out the owner had passes."""
    assert way_out_problems(BARE, before=BARE) == []
    assert way_out_problems(BARE, before=COVERED) == [NOT_NOW_WAY_OUT, NOT_INTERESTED_WAY_OUT]
    assert way_out_problems(COVERED, before=BARE) == []


def test_the_check_runs_only_for_placed_calls() -> None:
    """FAILS IF: an inbound line's script is held to "not now", or a placed one is not."""
    placed = language_problems(BARE, "en-IN", lint=LintContext(places_calls=True))
    answered = language_problems(BARE, "en-IN", lint=LintContext())
    assert NOT_NOW_WAY_OUT in placed
    assert NOT_INTERESTED_WAY_OUT in placed
    assert NOT_NOW_WAY_OUT not in answered


def test_who_places_the_calls() -> None:
    """FAILS IF: a "both" agent's own script (which also answers calls) is held to it, or a
    campaign's script for such an agent is not."""
    assert ScriptBrief(direction="outbound").lint_context().places_calls
    assert not ScriptBrief(direction="both").lint_context().places_calls
    assert ScriptBrief(direction="both", placed_calls=True).lint_context().places_calls
    assert not ScriptBrief(direction="outbound", placed_calls=False).places_calls()
