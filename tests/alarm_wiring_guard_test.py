"""Negative controls for `scripts/check_alarm_wiring.py` — the guard's own guard.

A guardrail that has never been seen to go RED is a guardrail nobody can trust, and this
one is easy to break silently: every question it asks is a regex or an AST walk over a
tree that moves under it. The tests here drive DOCTORED trees through the same functions
CI runs and assert the specific failure, so a scan that quietly stops matching fails here
rather than reporting a clean sweep of an empty set.

The last two are the ones that matter most. `test_it_refuses_when_the_scan_matches_nothing`
is `check_wiring`'s doctrine applied here: a broken scanner and a healthy tree must not
look alike. And `test_the_exemption_reverifies_itself` is what stops `DYNAMIC_ALERT_SITES`
becoming a hiding place — an exemption claiming an alarm the file no longer raises would
otherwise keep an index row alive for a page nobody can receive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scripts import check_alarm_wiring as guard

INDEX_HEADER = (
    "## Alarm codes\n\n| Code | Stage | What it means | What to do |\n| --- | --- | --- | --- |\n"
)
METRIC_HEADER = (
    "## Metric names\n\n| Name | What it measures | Read it when |\n| --- | --- | --- |\n"
)


def _tree(tmp_path: Path, *, alarms: str, index_rows: str, metrics: str = "") -> None:
    """A miniature repo, and every root the guard reads pointed at it."""
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "mod.py").write_text(alarms)
    (tmp_path / "runbooks").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "OPERATIONS.md").write_text("## 4. Observability & Alerting\n\nnothing\n")
    (tmp_path / "runbooks" / "alarm-index.md").write_text(
        INDEX_HEADER + index_rows + "\n" + METRIC_HEADER + metrics
    )
    (tmp_path / "shell").mkdir()
    (tmp_path / "shell" / "notify.sh").write_text("alert host_thing 'a host alarm'\n")


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Repoint every path constant at `tmp_path`. Nothing here touches the real tree."""

    def _use() -> None:
        monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(guard, "PY_ROOTS", (tmp_path / "apps",))
        monkeypatch.setattr(guard, "SHELL_ROOT", tmp_path / "shell")
        monkeypatch.setattr(guard, "INDEX", tmp_path / "runbooks" / "alarm-index.md")
        monkeypatch.setattr(guard, "OPERATIONS", tmp_path / "docs" / "OPERATIONS.md")
        monkeypatch.setattr(guard, "RUNBOOKS", tmp_path / "runbooks")
        monkeypatch.setattr(guard, "CODE_ROOTS", (tmp_path / "apps",))
        monkeypatch.setattr(guard, "DYNAMIC_ALERT_SITES", {})

    return _use


_ONE_ALARM = 'from x import alert\n\n\ndef go() -> None:\n    alert("CORE_LOGIC", "thing_broke")\n'
_ROW = "| `thing_broke` | CORE_LOGIC | it broke | fix it |\n"
_HOST_ROW = "| `host_thing` | HOST_BACKUP | a host alarm | look at the host |\n"
_METRIC = 'def _record(name: str, value: float) -> None:\n    pass\n\n\n_record("things", 1)\n'
_METRIC_ROW = "| `things` | how many things | always |\n"


def test_a_clean_tree_passes(sandbox: Any, tmp_path: Path) -> None:
    """The positive control. Without it every assertion below could be passing because
    the sandbox is broken rather than because the guard works."""
    sandbox()
    _tree(
        tmp_path,
        alarms=_ONE_ALARM + _METRIC,
        index_rows=_ROW + _HOST_ROW,
        metrics=_METRIC_ROW,
    )
    assert guard.evaluate() == []


def test_a_documented_alarm_with_no_call_site_fails(sandbox: Any, tmp_path: Path) -> None:
    """The defect the register named: an operator reads the runbook and believes they
    will be paged."""
    sandbox()
    _tree(
        tmp_path,
        alarms=_ONE_ALARM + _METRIC,
        index_rows=_ROW + _HOST_ROW + "| `never_fires` | CORE_LOGIC | nothing | nothing |\n",
        metrics=_METRIC_ROW,
    )
    failures = guard.evaluate()
    assert any("DOCUMENTED, NEVER RAISED: `never_fires`" in f for f in failures)


def test_a_raised_alarm_with_no_row_fails(sandbox: Any, tmp_path: Path) -> None:
    """The larger half nobody had counted: a page at 3am with nothing to look it up in."""
    sandbox()
    _tree(tmp_path, alarms=_ONE_ALARM + _METRIC, index_rows=_HOST_ROW, metrics=_METRIC_ROW)
    failures = guard.evaluate()
    assert any("RAISED, UNDOCUMENTED: `thing_broke`" in f for f in failures)


def test_a_problem_error_that_pages_is_treated_as_an_alarm(sandbox: Any, tmp_path: Path) -> None:
    """The shape a reader misses. `core/errors.py` relays any `ProblemError` carrying a
    `failure_stage` straight into `alert()`, so its code IS an alarm code — a hundred
    lines from any `alert(` a grep would find."""
    sandbox()
    _tree(
        tmp_path,
        alarms=_ONE_ALARM
        + _METRIC
        + '\n\nProblemError(code="vendor_said_no", failure_stage="CORE_LOGIC")\n',
        index_rows=_ROW + _HOST_ROW,
        metrics=_METRIC_ROW,
    )
    failures = guard.evaluate()
    assert any("RAISED, UNDOCUMENTED: `vendor_said_no`" in f for f in failures)


def test_a_host_shell_alarm_counts(sandbox: Any, tmp_path: Path) -> None:
    """The backup chain reaches the same inbox by a different road. An operator cannot
    tell the two apart when the mail arrives, so neither may this guard."""
    sandbox()
    _tree(tmp_path, alarms=_ONE_ALARM + _METRIC, index_rows=_ROW, metrics=_METRIC_ROW)
    failures = guard.evaluate()
    assert any("RAISED, UNDOCUMENTED: `host_thing`" in f for f in failures)


def test_an_ad_hoc_metric_fails(sandbox: Any, tmp_path: Path) -> None:
    """`core/alerting.py`'s own docstring: metrics are named recorders and ad-hoc
    counters are not accepted. Three modules were emitting them directly."""
    sandbox()
    _tree(
        tmp_path,
        alarms=_ONE_ALARM + _METRIC + '\nlog.info("metric", extra={"metric": "sneaky"})\n',
        index_rows=_ROW + _HOST_ROW,
        metrics=_METRIC_ROW,
    )
    failures = guard.evaluate()
    assert any("emits the metric 'sneaky' directly" in f for f in failures)


def test_an_unresolvable_alert_code_fails_rather_than_being_skipped(
    sandbox: Any, tmp_path: Path
) -> None:
    """A code the scan cannot name is a code the index cannot cover. Guessing would be
    the same as not checking, so it is a failure with a named remedy."""
    sandbox()
    _tree(
        tmp_path,
        alarms=_ONE_ALARM + _METRIC + "\nalert('CORE_LOGIC', whatever_it_is)\n",
        index_rows=_ROW + _HOST_ROW,
        metrics=_METRIC_ROW,
    )
    failures = guard.evaluate()
    assert any("cannot resolve" in f for f in failures)


def test_a_dangling_name_in_a_runbook_fails(sandbox: Any, tmp_path: Path) -> None:
    """The shape "documented but never raised" takes when the doc talks in prose."""
    sandbox()
    _tree(tmp_path, alarms=_ONE_ALARM + _METRIC, index_rows=_ROW + _HOST_ROW, metrics=_METRIC_ROW)
    (tmp_path / "runbooks" / "extra.md").write_text(
        "Check the `imaginary_switch_name` before escalating.\n"
    )
    failures = guard.evaluate()
    assert any("`imaginary_switch_name`" in f for f in failures)


def test_a_name_a_runbooks_own_query_defines_is_not_dangling(sandbox: Any, tmp_path: Path) -> None:
    """Precision, and it is not a nicety: a guard that cried wolf about a SQL column alias
    would be muted long before it caught a real dangling alarm."""
    sandbox()
    _tree(tmp_path, alarms=_ONE_ALARM + _METRIC, index_rows=_ROW + _HOST_ROW, metrics=_METRIC_ROW)
    (tmp_path / "runbooks" / "extra.md").write_text(
        "```sql\nSELECT count(*) AS waiting_on_backoff FROM t;\n```\n"
        "All rows with `waiting_on_backoff` = count means nothing is due.\n"
    )
    assert guard.evaluate() == []


def test_a_broken_runbook_pointer_fails(sandbox: Any, tmp_path: Path) -> None:
    sandbox()
    _tree(
        tmp_path,
        alarms=_ONE_ALARM + _METRIC,
        index_rows="| `thing_broke` | CORE_LOGIC | it broke | see runbooks/nowhere.md |\n"
        + _HOST_ROW,
        metrics=_METRIC_ROW,
    )
    failures = guard.evaluate()
    assert any("runbooks/nowhere.md" in f for f in failures)


def test_it_refuses_when_the_scan_matches_nothing(sandbox: Any, tmp_path: Path) -> None:
    """`check_wiring`'s doctrine. A scanner that stopped matching and a tree with no
    alarms must not look alike — the first is an emergency and the second is impossible.
    """
    sandbox()
    _tree(tmp_path, alarms="x = 1\n", index_rows="", metrics="")
    # The shell half is emptied too, so "the scan found nothing" is the whole tree's
    # answer rather than one road into it still working.
    (tmp_path / "shell" / "notify.sh").write_text("echo quiet\n")
    failures = guard.evaluate()
    assert any("found NO alert() call sites" in f for f in failures)
    assert any("no rows under" in f for f in failures)


def test_it_refuses_when_the_host_scan_goes_blind(sandbox: Any, tmp_path: Path) -> None:
    """The shell half has its own refusal, because it is the half most likely to rot: it
    matches a CALL SHAPE, and a shell refactor changes call shapes."""
    sandbox()
    _tree(tmp_path, alarms=_ONE_ALARM + _METRIC, index_rows=_ROW, metrics=_METRIC_ROW)
    (tmp_path / "shell" / "notify.sh").write_text("echo nothing that looks like an alarm\n")
    failures = guard.evaluate()
    assert any("host-alarm scan matched NOTHING" in f for f in failures)


def test_a_row_whose_stage_disagrees_with_the_call_fails(sandbox: Any, tmp_path: Path) -> None:
    """The index's own first instruction is "read the stage first", and until this check
    existed nothing compared that cell to anything. `calls_never_finished` was documented
    `WORKER_TERMINAL` and raised `WORKER_STALL` — a row that told an operator retries were
    exhausted about an alarm meaning work was stuck.
    """
    sandbox()
    _tree(
        tmp_path,
        alarms=_ONE_ALARM + _METRIC,
        index_rows="| `thing_broke` | WORKER_STALL | it broke | fix it |\n" + _HOST_ROW,
        metrics=_METRIC_ROW,
    )
    failures = guard.evaluate()
    assert any("WRONG STAGE" in f and "thing_broke" in f and "CORE_LOGIC" in f for f in failures), (
        failures
    )


def test_one_code_raised_at_two_stages_fails(sandbox: Any, tmp_path: Path) -> None:
    """A row carries ONE stage cell, so two call sites disagreeing about the stage make
    the row false whichever value it holds. Caught here rather than picking a winner: the
    fix is a decision (one stage, or two codes) and not something a guard may make."""
    sandbox()
    _tree(
        tmp_path,
        alarms=(
            "from x import alert\n\n\ndef go() -> None:\n"
            '    alert("CORE_LOGIC", "thing_broke")\n'
            '    alert("WORKER_STALL", "thing_broke")\n' + _METRIC
        ),
        index_rows=_ROW + _HOST_ROW,
        metrics=_METRIC_ROW,
    )
    failures = guard.evaluate()
    assert any("TWO STAGES, ONE ROW" in f and "thing_broke" in f for f in failures), failures


def test_a_row_with_no_readable_stage_fails(sandbox: Any, tmp_path: Path) -> None:
    """The blank-cell case, which the comparison above cannot reach: with nothing in
    column 2 there is nothing to disagree with, and the row would otherwise pass every
    question this guard asks while telling an operator nothing about where to start."""
    sandbox()
    _tree(
        tmp_path,
        alarms=_ONE_ALARM + _METRIC,
        index_rows="| `thing_broke` |  | it broke | fix it |\n" + _HOST_ROW,
        metrics=_METRIC_ROW,
    )
    failures = guard.evaluate()
    assert any("NO STAGE" in f and "thing_broke" in f for f in failures), failures


def test_the_stage_scan_still_reads_the_real_tree(sandbox: Any, tmp_path: Path) -> None:
    """The wiring half. Every assertion above is about a doctored tree, so a stage scan
    that had stopped resolving anything would satisfy all three by finding nothing to
    disagree with. This one asserts against the REAL repo that the scan still resolves a
    stage for most codes — and names the shapes it legitimately cannot."""
    _, stages, failures = guard.raised_codes()
    assert failures == []
    assert len(stages) > 50, (
        "the stage scan resolves a stage for almost nothing — `alert(stage, code)` or "
        "`ProblemError(failure_stage=...)` changed shape and the comparison went blind"
    )
    assert set(stages) <= set(guard.documented_codes())


def test_the_exemption_reverifies_itself(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`DYNAMIC_ALERT_SITES` is the one place this guard could be lied to. An entry
    claiming a code the file no longer contains would keep an index row alive for a page
    nobody can receive, so every claimed code must still be a literal in that file."""
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "mod.py").write_text('alert("CORE_LOGIC", code)\n')
    monkeypatch.setattr(
        guard,
        "DYNAMIC_ALERT_SITES",
        {
            "apps/mod.py": (
                ("renamed_away",),
                "a reason long enough for a reviewer to weigh it properly, as required",
            )
        },
    )
    failures = guard.dynamic_site_failures()
    assert any("'renamed_away'" in f and "no longer in the file" in f for f in failures)


def test_a_thin_exemption_reason_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "mod.py").write_text('x = "code_a"\n')
    monkeypatch.setattr(guard, "DYNAMIC_ALERT_SITES", {"apps/mod.py": (("code_a",), "TODO")})
    assert any("no reason a reviewer can weigh" in f for f in guard.dynamic_site_failures())


def test_the_real_tree_is_clean() -> None:
    """The live assertion, not a sandbox: this repo's alarms and its index agree right
    now. It is the same call `make guardrails` and CI make, kept here so a targeted test
    run cannot pass while the gate is red."""
    assert guard.evaluate() == []
