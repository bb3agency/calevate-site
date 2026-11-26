"""One check registry, run the same way on every path (script rebuild DESIGN §3.4).

1. Every check is registered once, with its fields, languages, severity and repair message;
   every call-mistake kind a script line causes has a check, and the kinds are the lessons the
   call review stores.
2. Examples (`ConversationStage.examples`) are lines the checks read, at their own paths.
3. The 26 Nov 2026 Rytu Khata call's failures that a script line causes are caught at write
   time (rememory d980cc9b; the call's lines are only in the production database, so these
   are its recorded phrases); one-action lines pass.
4. The same script gives the same findings on every path: the writer's repair rounds, the
   heal pass, the healer's VERIFY, the owner's checks read and the Put it live gate.
5. Put it live refuses a `block` finding; Save and Keep keep the script and only warn.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import call_mistakes, script_checks, script_gate, script_heal, turn_checks
from apps.api.agents.script_lint import LintContext, line_language
from apps.api.core.errors import ProblemError
from apps.workers.script_proposal import _Fix
from calevate_shared.call_script import CallScript, ConversationStage, StepExamples

TE = "te-IN"
OPENING = "Hello {{lead_name}}, this is Rytu Khata. ఇప్పుడు మాట్లాడటానికి సమయం ఉందా?"
LINT = LintContext(language=TE)


def _stage(sid: str, turns: list[str], **extra: Any) -> ConversationStage:
    return ConversationStage.model_validate(
        {
            "id": sid,
            "name": sid,
            "instruction": "Help them install the app.",
            "examples": {TE: StepExamples(turns=turns).model_dump()},
            **extra,
        }
    )


def _script(*stages: ConversationStage) -> CallScript:
    close = ConversationStage(
        id="close", name="Close", instruction="Thank them and say goodbye.", mode="say"
    )
    return CallScript(schema_version=2, opening_line=OPENING, stages=[*stages, close])


#: The lines of the 26 Nov 2026 call (d980cc9b): every turn opened with a rotating reaction
#: and ended "... అయ్యాక నాకు చెప్తారా?", and the agent asked again whether now was a good time.
CALL_26_NOV = _script(
    _stage(
        "install",
        [
            "సరే అండి. ప్లే స్టోర్ ఓపెన్ చేసి సెర్చ్ చేయండి, అయ్యాక నాకు చెప్తారా?",
            "చాలా మంచిది అండి. ఇన్‌స్టాల్ నొక్కండి, అయ్యాక నాకు చెప్తారా?",
        ],
    ),
    _stage(
        "open",
        [
            "ఇప్పుడు మాట్లాడటానికి సమయం ఉందా?",
            "సరే అండి. యాప్ ఓపెన్ చేయండి, అయ్యాక నాకు చెప్తారా?",
        ],
    ),
)
#: The same steps, one action a turn: no reaction first, no request to say when it is done.
ONE_ACTION = _script(
    _stage("install", ["ప్లే స్టోర్ ఓపెన్ చేయండి.", "సెర్చ్ చేయండి."]),
    _stage("open", ["యాప్ ఓపెన్ చేయండి."]),
)


def _ids(script: CallScript) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for f in script_checks.run(script, LINT):
        found.setdefault(f.check, []).append(f.path)
    return found


# --- 1. the registry -------------------------------------------------------------------------


def test_every_check_is_registered_once_with_what_it_reads_and_a_repair() -> None:
    assert len(script_checks.BY_ID) == len(script_checks.CHECKS)
    for check in script_checks.CHECKS:
        assert check.reads and check.languages and check.letters and check.repair.strip()
        assert check.severity in {"block", "warn"}
        assert check.languages <= script_checks.ANY_LANGUAGE


def test_no_repair_message_asks_the_agent_to_request_a_done() -> None:
    """FAILS IF: a check's repair tells the writer to end on "tell me when it is done", the
    ending every turn of the 26 Nov call copied (DESIGN §1.4)."""
    for check in script_checks.CHECKS:
        assert "invitation to say" not in check.repair
        assert "ask them to say" not in check.repair.lower()


def test_every_mistake_kind_a_line_causes_has_a_check_and_is_a_stored_lesson() -> None:
    kinds = script_checks.SCRIPT_FIXABLE_KINDS
    assert kinds <= set(call_mistakes.LESSONS)
    assert kinds.isdisjoint(turn_checks.IN_CALL_KINDS)
    assert set(script_checks.MISTAKE_CHECKS["opened_again"]) == {
        "opening_redone",
        "opening_redone_line",
    }
    assert set(script_checks.MISTAKE_CHECKS["same_opening"]) == {"same_opener", "reacted_line"}


def test_the_lints_no_production_path_ran_are_registered() -> None:
    """`step_numbers`, `untaken_time`, `unwired_way_out` and `pronunciation` ran only in the
    eval (01 §3); they are now owner-save warnings, never blocks."""
    for name in ("step_numbers", "untaken_time", "unwired_way_out", "pronunciation"):
        assert script_checks.BY_ID[name].severity == "warn"


# --- 2. examples are lines -------------------------------------------------------------------


def test_example_turns_are_read_at_their_own_paths_in_their_own_language() -> None:
    script = _script(_stage("install", ["Tap Install (Install) now."]))
    found = script_checks.run(script, LINT, ids=["brackets"])
    assert [f.path for f in found] == [f"stages.0.examples.{TE}.turns.0"]
    assert found[0].line == "Tap Install (Install) now."
    assert line_language(found[0].path, "hi-IN") == TE


def test_a_busy_example_may_talk_about_a_later_time() -> None:
    stage = _stage("install", ["ప్లే స్టోర్ ఓపెన్ చేయండి."])
    stage.examples[TE].busy = "ఇప్పుడు మాట్లాడటానికి సమయం ఉందా?"
    found = script_checks.run(_script(stage), LINT, ids=["opening_redone_line"])
    assert found == []


# --- 3. the 26 Nov call ----------------------------------------------------------------------


def test_the_26_nov_lines_are_caught_when_written() -> None:
    found = _ids(CALL_26_NOV)
    # #5: permission asked again after the opening asked it; blocks Put it live.
    assert found["opening_redone_line"] == [f"stages.1.examples.{TE}.turns.0"]
    # #1: lines opening with a stock reaction.
    assert set(found["reacted_line"]) >= {
        f"stages.0.examples.{TE}.turns.0",
        f"stages.0.examples.{TE}.turns.1",
        f"stages.1.examples.{TE}.turns.1",
    }
    # #2: three lines ending "... అయ్యాక నాకు చెప్తారా?".
    assert len(found["same_ending"]) == 2
    assert script_checks.blocking(script_checks.run(CALL_26_NOV, LINT))


def test_one_action_lines_pass() -> None:
    found = _ids(ONE_ACTION)
    for check in ("opening_redone_line", "reacted_line", "same_ending", "brackets"):
        assert check not in found, found
    assert not script_checks.blocking(script_checks.run(ONE_ACTION, LINT))


# --- 4. the same result on every path ----------------------------------------------------------


Path = Callable[[CallScript, LintContext], list[str]]
PATHS: dict[str, Path] = {
    "writer repair": lambda s, lint: _Fix(lint, [], frozenset()).problems(s),
    "heal": script_heal.heal_findings,
    "registry": lambda s, lint: script_checks.repairs(s, lint),
}


@pytest.mark.parametrize("path", sorted(PATHS))
@pytest.mark.parametrize("script", [CALL_26_NOV, ONE_ACTION], ids=["26 Nov", "one action"])
def test_every_path_reads_one_script_the_same_way(path: str, script: CallScript) -> None:
    assert PATHS[path](script, LINT) == script_checks.repairs(script, LINT)


@pytest.mark.parametrize("kind", sorted(script_checks.SCRIPT_FIXABLE_KINDS))
def test_the_healers_verify_reads_a_kind_as_the_heal_pass_does(kind: str) -> None:
    """FAILS IF: VERIFY (`script_heal.kind_findings`) faults a line the heal pass would not
    repair, which spent a fix's attempts on a script heal reports clean (01 §1 P9)."""
    heal = set(script_heal.heal_findings(CALL_26_NOV, LINT))
    ids = set(script_checks.MISTAKE_CHECKS[kind])
    wanted = [
        f.text for f in script_checks.run(CALL_26_NOV, LINT) if f.check in ids and f.text in heal
    ]
    assert script_heal.kind_findings(CALL_26_NOV, LINT, kind) == wanted


def test_the_owners_read_shows_every_finding_with_its_line_and_severity() -> None:
    found = script_checks.run(CALL_26_NOV, LINT)
    out = script_gate.checks_out(found, CALL_26_NOV)
    assert [(c.path, c.severity) for c in out.findings] == [(f.path, f.severity) for f in found]
    assert out.blocks_live
    first = out.findings[0]
    assert first.stage_id == CALL_26_NOV.stages[int(first.path.split(".")[1])].id
    assert all(c.message.startswith("Step ") for c in out.findings if c.path.startswith("stages."))


# --- 5. Put it live refuses a block; Save and Keep warn ----------------------------------------


@pytest.mark.parametrize("kind", ["campaign", "line"])
async def test_put_it_live_refuses_a_block_and_names_the_line(
    kind: script_heal.HolderKind, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def findings(*_args: Any) -> list[script_checks.Finding]:
        return script_checks.run(CALL_26_NOV, LINT)

    monkeypatch.setattr(script_gate, "holder_findings", findings)
    with pytest.raises(ProblemError) as refused:
        await script_gate.refuse_if_blocked(None, kind, UUID(int=1))  # type: ignore[arg-type]
    assert refused.value.code == script_gate.SCRIPT_NEEDS_FIX
    assert "Step 2" in str(refused.value.detail)


async def test_put_it_live_lets_warnings_through(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _script(_stage("install", ["సరే అండి. ప్లే స్టోర్ ఓపెన్ చేయండి."]))
    warned = script_checks.run(script, LINT)
    assert warned and not script_checks.blocking(warned)

    async def findings(*_args: Any) -> list[script_checks.Finding]:
        return warned

    monkeypatch.setattr(script_gate, "holder_findings", findings)
    await script_gate.refuse_if_blocked(None, "line", UUID(int=1))  # type: ignore[arg-type]


@pytest.mark.rls
async def test_a_line_save_keeps_a_blocked_script_and_put_it_live_refuses_it() -> None:
    """Through the routes: Save keeps the script and warns ("Saved, but not live yet"), the
    checks read names the line, Put it live refuses by name, and a fixed script goes live."""
    from tests.inbound_lines_test import _call, _fresh_engine, _line, _live_agent

    _fresh_engine()
    tenant_id, agent_id, token = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    bracketed = CallScript(
        schema_version=2,
        opening_line="Namaste, Lifecycle Clinic. How can I help you today?",
        stages=[
            ConversationStage(
                id="help", name="Help", instruction="Help them.", sounds_like="Tap Book (Book)."
            )
        ],
    )
    code, saved = await _call(
        token, "PUT", f"/{line_id}/script", json={"script": bracketed.model_dump(mode="json")}
    )
    assert code == 422, saved
    assert saved["type"].endswith(f"/{script_gate.SCRIPT_NEEDS_FIX}")
    assert saved["title"] == "Saved, but not live yet"
    code, checks = await _call(token, "GET", f"/{line_id}/script/checks")
    assert code == 200, checks
    assert checks["blocks_live"] is True
    (blocked,) = [c for c in checks["findings"] if c["severity"] == "block"]
    assert (blocked["path"], blocked["line"]) == ("stages.0.sounds_like", "Tap Book (Book).")
    code, refused = await _call(token, "POST", f"/{line_id}/publish")
    assert code == 422, refused
    assert refused["type"].endswith(f"/{script_gate.SCRIPT_NEEDS_FIX}")

    fixed = bracketed.model_copy(
        update={"stages": [bracketed.stages[0].model_copy(update={"sounds_like": "Tap Book."})]}
    )
    code, live = await _call(
        token, "PUT", f"/{line_id}/script", json={"script": fixed.model_dump(mode="json")}
    )
    assert code == 200, live
    assert live["live"] is True
