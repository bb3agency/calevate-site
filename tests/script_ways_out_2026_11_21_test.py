"""Ways out in the scripts Pip writes, held to the Rytu Khata calls of 20-21 Nov 2026.

On those calls the person said they did not remember registering, or that there was nothing
for now and they would do it later, and the script had no way out for either: the agent
pushed on with its steps. The writer is now told which ways out the kind of call needs
(`script_assist.WAYS_OUT_RULE`), can draft them with platform targets (`ways_out`), and a
placed call's script lacking "not now" or an early end is sent back (`way_out_problems`).
"""

from __future__ import annotations

from typing import Any, cast

from apps.api.agents.script_lint import LintContext
from apps.workers import script_assist
from apps.workers.campaign_script_ask import CALL_KINDS
from apps.workers.script_assist import (
    EDIT_INSTRUCTION,
    NOT_INTERESTED_WAY_OUT,
    NOT_NOW_WAY_OUT,
    WAYS_OUT_RULE,
    ScriptBrief,
    language_problems,
    way_out_problems,
)
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    HAND_OVER,
    MAX_SCRIPT_STAGES,
    MAX_STAGE_BRANCHES,
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


def test_every_writer_of_steps_is_told_the_ways_out() -> None:
    """FAILS IF: a new script or an edit is written without the ways-out checklist."""
    system = cast(str, script_assist._SYSTEM_INSTRUCTION)
    assert WAYS_OUT_RULE in system
    assert WAYS_OUT_RULE in EDIT_INSTRUCTION


def test_the_checklist_routes_to_the_platform_rather_than_describing_it() -> None:
    """FAILS IF: "not now" is not sent to the call-back, the not-remembering person is not
    answered with who and why, or the writer is asked to branch on what the platform's rules
    already handle at any point (a person, do-not-call, AI, recording, off-topic)."""
    assert "busy now or later (to call_back" in WAYS_OUT_RULE
    assert "never push the steps on someone who said not now" in WAYS_OUT_RULE
    assert "who is calling and why" in WAYS_OUT_RULE
    assert "never insists they did something" in WAYS_OUT_RULE
    assert "wrong person or wrong number (to end)" in WAYS_OUT_RULE
    assert "Write no way out for asking for a person" in WAYS_OUT_RULE
    assert "never says call back or transfer" in WAYS_OUT_RULE


def test_the_checklist_follows_the_kind_of_call() -> None:
    """FAILS IF: the call-specific situations (an app set-up's already done, other phone,
    stuck; a sales call's bought elsewhere) are dropped for one template."""
    for words in (
        "already done",
        "different phone or device",
        "stuck on an action",
        "no time suiting them",
        "bought elsewhere",
    ):
        assert words in WAYS_OUT_RULE
    assert f"At most {MAX_STAGE_BRANCHES} ways out a stage" in WAYS_OUT_RULE
    assert f"{MAX_SCRIPT_STAGES} stages in all" in WAYS_OUT_RULE


def test_the_kinds_of_call_are_listed_once() -> None:
    """FAILS IF: the ways out a kind of call meets are written beside the rule again, so a
    kind added to the campaign writer's list (`CALL_KINDS`) is missing from the ways out."""
    for kind in CALL_KINDS:
        if kind.ways_out:
            assert kind.name in WAYS_OUT_RULE
            assert kind.ways_out in WAYS_OUT_RULE


def test_a_draft_can_name_a_platform_target() -> None:
    """FAILS IF: the strict draft schema has no way to send a step to the call-back."""
    stages = cast(dict[str, Any], script_assist._DRAFT_PROPERTIES["stages"])
    item = stages["items"]
    assert "ways_out" in item["required"]
    to = item["properties"]["ways_out"]["items"]["properties"]["to"]
    assert {CALL_BACK, END_OF_CALL, HAND_OVER, "1", str(MAX_SCRIPT_STAGES)} <= set(to["enum"])


# --- 2. reading a draft's ways out --------------------------------------------------------------


def _row(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "instruction": f"Do {name}.", "sounds_like": "", **extra}


def test_drafted_ways_out_become_branches_before_the_flow() -> None:
    """FAILS IF: a drafted way out is lost, sent to a stage the draft lacks, or listed after
    the plain go-on, where the compiled step would read it last."""
    raw = {
        "stages": [
            _row(
                "Check",
                next=[2],
                ways_out=[
                    {"when": BUSY, "to": CALL_BACK},
                    {"when": NOT_FOR_THEM, "to": END_OF_CALL},
                    {"when": "They already have it", "to": "3"},
                    {"when": "Loops", "to": "1"},
                    {"when": "Nowhere", "to": "9"},
                    {"when": "", "to": END_OF_CALL},
                ],
            ),
            _row("Install"),
            _row("Finalise the call"),
        ]
    }
    script = script_assist._script_from_model_json(raw)
    first = script.stages[0].branches
    assert [(b.when, b.target) for b in first] == [
        (BUSY, CALL_BACK),
        (NOT_FOR_THEM, END_OF_CALL),
        ("They already have it", "s3"),
        ("Install", "s2"),
    ]


def test_a_stage_keeps_at_most_six_ways_out() -> None:
    raw = {
        "stages": [
            _row(
                "Check",
                ways_out=[{"when": f"Case {n}", "to": END_OF_CALL} for n in range(8)],
                exit_when="They agree",
            ),
            _row("Finalise the call"),
        ]
    }
    script = script_assist._script_from_model_json(raw)
    assert len(script.stages[0].branches) == MAX_STAGE_BRANCHES


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
