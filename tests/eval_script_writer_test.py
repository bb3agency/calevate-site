"""The script writer evaluation (`scripts/eval_script_writer`).

1. Every case has a recorded output, and the recorded set scores exactly as `baseline.json`
   holds it: a count that moved either way fails until the baseline is rewritten.
2. The production Rytu Khata script of 25 Nov 2026 (stand-in form) is caught on every defect
   the founder's evidence lists, and its case-neutral outcomes are not.
3. The clean control has no structural finding; a list without names may ask the name.
4. A lint the writer's checks grow is used or scored without an edit here.
5. The rubric judge's scores must cite a line they quote word for word, and the judge sits
   outside the deterministic score.
6. `--live` writes as the campaign writer does and refuses to spend unasked.

The model is never called.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_lint
from apps.workers import script_assist
from apps.workers.script_assist import UnusableAnswerError
from calevate_shared.call_script import CallScript, ConversationStage, StageBranch, StepOutcome
from scripts import eval_script_writer as ev

CASES = {case.id: case for case in ev.load_cases()}


def _result(case_id: str) -> ev.CaseResult:
    case = CASES[case_id]
    return ev.score(ev.load_recorded(case), case)


def _paths(found: list[str]) -> list[str]:
    return [f.partition(": ")[0] for f in found]


def test_the_case_set_covers_the_trades_directions_and_languages() -> None:
    """FAILS IF: the set shrinks below ten holders or loses a direction or a language."""
    assert 10 <= len(CASES) <= 12
    assert {c.holder for c in CASES.values()} == {"campaign", "line"}
    assert {c.language for c in CASES.values()} >= {"en-IN", "te-IN", "hi-IN"}
    assert any(c.known for c in CASES.values()) and any(not c.known for c in CASES.values())
    for case in CASES.values():
        rec = ev.load_recorded(case)
        assert rec.case_id == case.id and rec.script.stages


def test_the_recorded_outputs_score_as_the_baseline_holds() -> None:
    """FAILS IF: a check or a lint finds more (a regression) or fewer (progress to lock in)
    on the recorded outputs than `baseline.json` holds. Rewrite it with
    `python -m scripts.eval_script_writer --write-baseline` once the change is understood."""
    results = [ev.score(ev.load_recorded(case), case) for case in CASES.values()]
    baseline = json.loads(ev.BASELINE.read_text(encoding="utf-8"))
    assert ev.baseline_drift(results, baseline) == []


def test_every_defect_of_the_25_nov_script_is_caught() -> None:
    r = _result("rytu_khata_install")
    s = r.structural
    judged = " ".join(s["judged_field_asked"])
    for label in ("Campaign goal met", "Technical comfort level", "Primary usage interest"):
        assert f'"{label}"' in judged
    # Asked in step 1's instruction and its line, never in a collect list.
    assert set(_paths(s["judged_field_asked"])) == {
        "stages.0.instruction",
        "stages.0.scripts.en-IN",
    }
    assert set(_paths(s["known_value_asked"])) == {"stages.0.instruction", "stages.0.scripts.en-IN"}
    # Five asks under one question mark.
    assert _paths(s["multi_question_line"]) == ["stages.0.scripts.en-IN"]
    # Step 1's check + go to + press; step 2's open + log in (25 Nov call, turn 16).
    assert _paths(s["multi_action_line"]) == ["stages.0.scripts.en-IN", "stages.1.scripts.en-IN"]
    fakes = _paths(s["fake_branch"])
    for i in range(1, 6):  # Add Farms, Enter Expenses, Enter Sales, Dashboard, Finalise
        assert f"stages.{i}.branches" in fakes
    assert _paths(s["steps_after_close"]) == ["stages.7"]
    assert _paths(s["agent_claims_caller_action"]) == [
        "stages.2.scripts.en-IN",
        "stages.4.scripts.en-IN",
    ]
    # Its English "details note" is ordinary Telugu-English code-mixing by the register data:
    # "details" is a word callers say in English, and "note" has no listed spoken word.
    assert s["register_in_line"] == []
    uncovered = {p.removeprefix("main_task.") for p in _paths(s["main_task_uncovered"])}
    assert {"why_install", "install_android", "install_iphone", "set_language"} <= uncovered
    assert s["no_purpose_line"]
    # The evidence calls Pip's outcomes case-neutral: no finding.
    assert s["outcome_tailored"] == []


def test_the_writers_lints_catch_the_25_nov_script_and_make_those_checks() -> None:
    """The defects the repo's lints missed when this eval was written are the writer's own
    lints' to find now, and the eval scores those lints rather than a copy of its own.
    FAILS IF a lint stops naming a defect's place, or a check stops being the lint's."""
    script = ev.load_recorded(CASES["rytu_khata_install"]).script
    assert _paths(script_lint.multi_action_line_problems(script)) == [
        "stages.0.scripts.en-IN",
        "stages.1.scripts.en-IN",
    ]
    assert _paths(script_lint.agent_claims_caller_action_problems(script)) == [
        "stages.2.scripts.en-IN",
        "stages.4.scripts.en-IN",
    ]
    assert _paths(script_lint.steps_after_close_problems(script)) == ["stages.7"]
    fakes = set(_paths(script_lint.fake_branch_problems(script)))
    assert {f"stages.{i}.branches" for i in range(1, 6)} <= fakes
    r = _result("rytu_khata_install")
    for name in (
        "multi_question_line",
        "multi_action_line",
        "agent_claims_caller_action",
        "steps_after_close",
    ):
        assert r.origin[name] == f"script_lint.{name}_problems"
        assert f"{name}_problems" not in r.lints  # one count per problem
    for name in ev.EXTENDS:
        assert r.origin[name] == f"script_lint.{name}_problems + eval"


def test_the_clean_control_has_no_structural_finding() -> None:
    r = _result("school_admission")
    assert {k: v for k, v in r.structural.items() if v} == {}


def test_a_list_without_names_may_ask_the_name() -> None:
    assert "known_value_asked" not in _result("solar_lead").structural


def test_a_tailored_outcome_and_a_known_value_are_found_elsewhere() -> None:
    assert _paths(_result("bank_app_kyc").structural["outcome_tailored"]) == ["step_outcomes.1"]
    assert _paths(_result("insurance_renewal").structural["known_value_asked"]) == [
        "stages.0.instruction",
        "stages.0.scripts.en-IN",
    ]
    # The vehicle number the list gives is the case's to know: the lint, reading the script
    # alone, cannot see it, which is why the eval adds to it (`EXTENDS`).
    insurance = ev.load_recorded(CASES["insurance_renewal"]).script
    assert script_lint.known_value_asked_problems(insurance) == []


def _bare(*stages: ConversationStage, **parts: Any) -> ev.Recorded:
    return ev.Recorded("x", "live", CallScript(schema_version=2, stages=list(stages), **parts))


def test_a_real_condition_to_the_next_step_is_not_a_fake_branch() -> None:
    rec = _bare(
        ConversationStage(
            id="a",
            name="Ask",
            instruction="Ask.",
            branches=[StageBranch(when="They already have it", target="b")],
        ),
        ConversationStage(id="b", name="Next", instruction="Go on."),
    )
    assert ev.structural(rec, CASES["clinic_reminder"])[0]["fake_branch"] == []


def test_a_telugu_line_is_faulted_for_a_bracket_and_a_register_word_not_for_code_mixing() -> None:
    """Telugu-English code-mixing is ordinary speech (research of 25 Nov 2026, A4): only a
    bracketed double and an English word the register data gives a spoken word for count."""
    # Letters of the Telugu block (no word), so the line reads as one in Telugu letters.
    letters = "".join(chr(c) for c in range(0x0C05, 0x0C0A))
    meaning = next(m for m in sorted(ev.spoken_meanings("te-IN")) if " " not in m)
    line = f"{letters} My Farms details note {meaning} {letters} (Add to Home screen) {letters}?"
    rec = _bare(
        ConversationStage(
            id="a", name="Farms", instruction="Ask them to add a farm.", scripts={"te-IN": line}
        )
    )
    found = ev.register_in_line(rec, CASES["rytu_khata_install"])
    assert found == [
        'stages.0.scripts.te-IN: says "(Add to Home screen)" again in brackets.',
        f'stages.0.scripts.te-IN: says "{meaning}" in English, where callers say the word of '
        "their own.",
    ]
    assert "details" not in ev.spoken_meanings("te-IN")


def test_a_lint_the_writer_grows_is_used_in_place_of_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_branch_problems(script: CallScript) -> list[str]:
        return ["stages.0.branches.0: from the writer's own lint."]

    fake_branch_problems.__module__ = script_lint.__name__
    monkeypatch.setattr(script_lint, "fake_branch_problems", fake_branch_problems, raising=False)
    case = CASES["rytu_khata_install"]
    found, origin = ev.structural(ev.load_recorded(case), case)
    assert found["fake_branch"] == ["stages.0.branches.0: from the writer's own lint."]
    assert origin["fake_branch"] == "script_lint.fake_branch_problems"
    assert "fake_branch_problems" in ev.one_argument_lints()
    assert "fake_branch_problems" not in ev.lints(ev.load_recorded(case), case)


def _parts() -> dict[str, str]:
    return {"stages.0.scripts.en-IN": "Please open the app. Tell me when it is open."}


def _row(
    criterion: str, quote: str = "Please open the app", path: str = "stages.0.scripts.en-IN"
) -> dict[str, Any]:
    return {
        "criterion": criterion,
        "score": 4,
        "reason": "  One action,  then a wait. ",
        "cites": [{"path": path, "quote": quote}],
    }


def test_the_judge_must_cite_a_line_it_quotes() -> None:
    graded = ev.parsed_judgement({"scores": [_row(k) for k in ev.RUBRIC]}, _parts())
    assert set(graded) == set(ev.RUBRIC)
    assert graded["natural_spoken_flow"].reason == "One action, then a wait."
    wrong_quote = _row("natural_spoken_flow", quote="Please install the app now")
    with pytest.raises(UnusableAnswerError) as refused:
        ev.parsed_judgement({"scores": [wrong_quote]}, _parts())
    problems = refused.value.problems
    assert "natural_spoken_flow: cite" in problems
    assert "everyday_register: not scored" in problems
    no_line = _row("everyday_register", path="stages.9.scripts.en-IN")
    with pytest.raises(UnusableAnswerError) as refused:
        ev.parsed_judgement({"scores": [_row("natural_spoken_flow"), no_line]}, _parts())
    assert (
        refused.value.problems
        == "everyday_register: cite a line by its path with a quote copied from it"
    )


def test_the_judge_reads_naturalness_only_with_evidence_first() -> None:
    assert set(ev.RUBRIC) == {"natural_spoken_flow", "everyday_register"}
    assert ev.JUDGE_INSTRUCTION.index('"cites"') < ev.JUDGE_INSTRUCTION.index('"score"')


def test_a_comparison_runs_both_orders_and_a_flip_is_a_split() -> None:
    assert ev.settle_pair("first", "second") == "new"
    assert ev.settle_pair("second", "first") == "old"
    assert ev.settle_pair("tie", "tie") == "tie"
    # The first script won in both orders: the order decided it, not the script.
    assert ev.settle_pair("first", "first") == "split"
    parts = {"first.opening_line": "Hello there.", "second.opening_line": "Good morning."}
    cites = [
        {"path": "first.opening_line", "quote": "Hello there"},
        {"path": "second.opening_line", "quote": "Good morning"},
    ]
    assert ev.parsed_pair({"cites": cites, "better": "second"}, parts) == "second"
    with pytest.raises(UnusableAnswerError) as refused:
        ev.parsed_pair({"cites": cites[:1], "better": "best"}, parts)
    assert "second script" in refused.value.problems and "better:" in refused.value.problems


def test_the_judge_is_reported_apart_and_never_in_the_score() -> None:
    r = _result("school_admission")
    graded = ev.parsed_judgement({"scores": [_row(k) for k in ev.RUBRIC]}, _parts())
    judged = [ev.JudgeResult("school_admission", graded)]
    paired = [ev.PairResult("school_admission", "split", ("first", "first"))]
    text = ev.report_markdown([r], mode="recorded", when="2026-11-25", judged=judged, paired=paired)
    assert text.index("## Rubric judge (separate; never gates CI)") > text.index("## Summary")
    assert "| school_admission | split | first, first |" in text
    assert "UNCALIBRATED" in text and "## The research scorecard's deterministic checks" in text
    assert ev.summary([r]) == ev.report_json([r], judged)["summary"]
    assert not any(k.startswith("judge") for k in r.counts())


async def test_live_writes_as_the_campaign_writer_does(monkeypatch: pytest.MonkeyPatch) -> None:
    case = CASES["rytu_khata_install"]
    written = ev.load_recorded(CASES["school_admission"]).script
    calls: list[dict[str, Any]] = []

    async def fake_draft(brief: script_assist.ScriptBrief, **kwargs: Any) -> Any:
        calls.append({"brief": brief, **kwargs})
        usage = SimpleNamespace(prompt_tokens=100, output_tokens=50)
        return SimpleNamespace(script=written, usage=usage, model="gemini-test")

    monkeypatch.setattr(script_assist, "draft_script", fake_draft)
    monkeypatch.setattr("apps.api.agents.assist_leg.google_assist_leg", lambda: "leg")
    spend = ev.Spend()
    script = await ev.write_live(case, spend)
    first, refine = calls
    assert "MAIN TASK:" in first["brief"].description and first["brief"].placed_calls
    assert first["brief"].language == "te-IN" and first["tenant_leg"] == "leg"
    # A judgement its label gives away never reaches the writer, as job_details keeps it.
    assert not any("Installation status" in c for c in first["brief"].collect)
    assert refine["edit_of"] == written and refine["brief"].description == case.description
    assert first["standby_after_answer"] is False
    assert spend.tokens == 300 and spend.models == {"gemini-test"}
    assert isinstance(script, CallScript)


def test_live_and_judge_refuse_to_spend_unasked() -> None:
    assert ev.main(["--live"]) == 2
    assert ev.main(["--judge", "--cases", "school_admission"]) == 2


def test_a_live_run_is_recorded_in_place_of_the_stand_in(tmp_path: Path) -> None:
    (tmp_path / "recorded").mkdir()
    script = CallScript(
        schema_version=2,
        stages=[ConversationStage(id="a", name="Ask", instruction="Ask.")],
        step_outcomes=[StepOutcome(step=1, outcome="Done.")],
    )
    rec = ev.Recorded("school_admission", "live", script, model="m", recorded_at="t")
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"outputs": [ev.recorded_json(rec)]}), encoding="utf-8")
    assert ev.import_live(run, root=tmp_path) == ["school_admission"]
    back = ev.recorded_from(
        json.loads((tmp_path / "recorded" / "school_admission.json").read_text())
    )
    assert back.source == "live" and back.script == script and not back.stands_for


def test_drift_names_the_direction() -> None:
    r = _result("school_admission")
    held = ev.baseline_of([r])
    assert ev.baseline_drift([r], held) == []
    held["counts"]["school_admission"]["check.fake_branch"] = 2
    held["counts"]["school_admission"]["lint.script_problems"] = 0
    drift = ev.baseline_drift([r], held)
    assert "school_admission check.fake_branch: 2 -> 0 (improvement)" in drift
    assert any("lint.script_problems: 0 ->" in d and "REGRESSION" in d for d in drift)
    assert ev.baseline_drift([r], {"counts": {}}) == ["school_admission: not in the baseline"]
