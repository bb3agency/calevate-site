"""Negative controls for `scripts/check_coverage_ratchet.py` (D-29 `coverage:ratchet`).

Same doctrine as `tests/wiring_guard_test.py`, `docs_drift_guard_test.py` and
`guardrail_audit_test.py`: a guardrail that stays green while the violation it names is
present is worse than no guardrail, so every test here calls the guard's OWN functions,
applies ONE minimal mutation that is exactly the violation it claims to catch, and
asserts it is reported.

The mutations are the two ways a coverage ratchet dies:

1. **coverage falls** — new untested code lands in a hard-rule surface;
2. **somebody raises the number** — the "just this once" edit that turns a ratchet into
   a target. The gate is an EQUALITY, so a hand-raised budget cannot sit quietly above
   the measurement: it fails on the very next run, and the only sanctioned way up is a
   `RAISED_BUDGETS` waiver, which this file also proves is self-expiring.

ONE THING IS DELIBERATELY NOT ASSERTED HERE: that the tree is currently AT its floor.
These tests run inside the very suite whose execution produces the measurement, so the
newest `.coverage` they could read is the PREVIOUS run's — and on a CI checkout there is
none at all. Asserting the live number from in here would be circular where it worked and
skipped where it mattered. That assertion belongs to the gate itself, which runs
immediately after the suite (`make coverage-ratchet`, and the CI step of the same name).
What this file proves is the part the gate cannot prove about itself: that it can still
SEE each violation.

So the reports below are built from the REAL guarded file list (`_guarded_sources()`) with
numbers chosen per test. The tie to reality is the file list: if an area stops matching
real files, or the areas stop covering the hard-rule surfaces the registries name, these
fail. The one test that reads a real `.coverage` is the parser wiring test, and it skips
when there is nothing to read.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from scripts import check_coverage_ratchet as ratchet

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Per-file numbers for the synthetic reports. Arbitrary, and identical for every file so
#: that a mutation of one area is the only thing that can move that area's total.
PER_FILE = {
    "num_statements": 40,
    "covered_lines": 34,
    "missing_lines": 6,
    "num_branches": 12,
    "num_partial_branches": 2,
    "excluded_lines": 0,
}


def _report(**overrides: Any) -> dict[str, Any]:
    """A coverage JSON report shaped like the real one, over the REAL guarded files."""
    summary = {**PER_FILE, **overrides}
    return {
        "meta": {"branch_coverage": True, "format": 3},
        "files": {
            path.relative_to(REPO_ROOT).as_posix(): {"summary": dict(summary)}
            for path in ratchet._guarded_sources()
        },
    }


@pytest.fixture
def measurements() -> list[ratchet.Measurement]:
    return ratchet.measure(_report())


@pytest.fixture
def budgets(measurements: list[ratchet.Measurement]) -> dict[str, int]:
    """The baseline this tree would have if it were blessed right now — so every test
    below starts from a green gate and moves exactly one thing."""
    return {row.area: row.uncovered for row in measurements}


def _bumped(rows: list[ratchet.Measurement], area: str, delta: int) -> list[ratchet.Measurement]:
    """The measurement with ONE area's missing lines moved by `delta`."""
    return [
        replace(row, missing_lines=row.missing_lines + delta) if row.area == area else row
        for row in rows
    ]


# ============================================================================
# The areas are real, and they cover what the registries say they must
# ============================================================================


class TestAreasAreReal:
    def test_every_area_names_files_that_exist(self) -> None:
        """An area whose patterns match nothing is a budget guarding air."""
        for area in ratchet.AREAS:
            assert ratchet._guarded_sources([area]), f"area {area.name!r} matches no file"

    def test_every_area_says_which_hard_rule_and_why(self) -> None:
        """Budgets are per-area precisely because the areas are not interchangeable; an
        area that cannot say which rule it protects is a repo-wide number wearing a
        name."""
        for area in ratchet.AREAS:
            assert "hard rule" in area.rule
            assert len(area.why) >= ratchet.MIN_REASON_CHARS

    def test_the_derivation_is_live_not_remembered(self) -> None:
        """`required_surfaces()` must come off registries that grow with the tree — the
        append-only table list, the tenancy GUC, the dial-site scan, the redaction
        primitive resolved by import."""
        required = ratchet.required_surfaces()
        assert "apps/voice-runtime/webhook_routes.py" in required
        assert "apps/api/db/session.py" in required
        assert "apps/api/billing/models.py" in required
        assert "apps/workers/redaction.py" in required
        assert any("dial chokepoint" in reason for reason in required.values())

    def test_the_real_tree_leaves_no_hard_rule_surface_unguarded(self) -> None:
        assert ratchet.unguarded_surfaces() == []

    def test_catches_a_hard_rule_surface_that_fell_out_of_every_area(self) -> None:
        """The mutation is the AREA list, not the tree: drop the voice-runtime area and
        hard rule 3's whole service must reappear as unguarded. This is the failure the
        derivation exists for — a surface that is real, risky, and in nobody's budget."""
        without_voice = tuple(a for a in ratchet.AREAS if a.name != "voice-runtime-ack")
        offenders = ratchet.unguarded_surfaces(without_voice)
        assert any("apps/voice-runtime/webhook_routes.py" in o for o in offenders)
        assert all("in no guarded area" in o for o in offenders)

    def test_catches_a_new_ledger_module_nobody_guarded(self) -> None:
        """Simulating the growth this design is judged on: somebody adds a module that
        declares an append-only table, in a package no area names.

        The mutation is the REAL tree (a new package, removed again in `finally`) rather
        than a fixture, because a fixture would prove only that the fixture parses.
        `_ledger_model_files()` reads the LIVE `APPEND_ONLY_TABLES` from
        `apps/api/db/registry.py`, so a new ledger surface enrols itself the day it
        lands — which is the whole answer to "how does the area list stay honest".
        """
        from apps.api.db.registry import APPEND_ONLY_TABLES

        ledger = next(iter(APPEND_ONLY_TABLES))
        package = REPO_ROOT / "apps" / "api" / "_ratchet_probe"
        probe = package / "models.py"
        assert not package.exists(), "the probe package must not collide with real code"
        package.mkdir()
        try:
            probe.write_text(
                "class Probe:\n"
                f'    __tablename__ = "{ledger}"\n'
                "    # a second writer of an append-only ledger, in an unguarded package\n",
                encoding="utf-8",
            )
            offenders = ratchet.unguarded_surfaces()
            assert any(
                "apps/api/_ratchet_probe/models.py" in o and "append-only" in o for o in offenders
            )
        finally:
            probe.unlink(missing_ok=True)
            package.rmdir()


# ============================================================================
# The ratchet
# ============================================================================


class TestRatchet:
    def test_a_measurement_at_its_budget_passes(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int]
    ) -> None:
        """Without this the detection tests below could pass for the wrong reason."""
        assert ratchet.evaluate(measurements, budgets) == []

    def test_catches_coverage_falling(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int]
    ) -> None:
        """ONE more uncovered line in the compliance gate — the smallest regression the
        guard has to see, because the branch that goes untested is always the refusal."""
        failures = ratchet.evaluate(_bumped(measurements, "compliance-gate", +1), budgets)
        assert any("compliance-gate" in f and "New untested code" in f for f in failures)

    def test_a_regression_in_one_area_cannot_be_paid_for_by_another(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int]
    ) -> None:
        """The reason there is no repo-wide number. Twenty lines newly covered in the
        billing package must not buy one uncovered branch in the dial path — under a
        single aggregate it would, and the aggregate would not move."""
        rows = _bumped(_bumped(measurements, "ledgers-and-money", -20), "dial-path", +1)
        failures = ratchet.evaluate(rows, budgets)
        assert any("dial-path" in f and "New untested code" in f for f in failures)

    def test_catches_an_improvement_that_was_never_locked_in(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int]
    ) -> None:
        """The half people leave out: unclaimed slack is where the next deleted test
        hides (coveragepy#815)."""
        failures = ratchet.evaluate(_bumped(measurements, "redaction", -1), budgets)
        assert any("redaction" in f and "not at the floor" in f for f in failures)

    def test_catches_someone_raising_the_budget_by_hand(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int]
    ) -> None:
        """ "Just this once." The gate is an equality, so the edit does not survive one
        run, and the message names the reading the author will not have written down."""
        budgets["ledgers-and-money"] += 40
        failures = ratchet.evaluate(measurements, budgets)
        assert any("ledgers-and-money" in f and "EDITED UPWARD" in f for f in failures)

    def test_catches_a_budget_for_an_area_that_no_longer_exists(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int]
    ) -> None:
        failures = ratchet.evaluate(measurements, {**budgets, "surface_deleted_last_year": 7})
        assert any("not an area any more" in f for f in failures)

    def test_catches_a_new_area_with_no_budget(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int]
    ) -> None:
        failures = ratchet.evaluate(
            measurements, {k: v for k, v in budgets.items() if k != "dial-path"}
        )
        assert any("dial-path" in f and "no budget recorded" in f for f in failures)

    def test_a_pragma_no_cover_does_not_lower_the_number(self) -> None:
        """`# pragma: no cover` deletes a line from coverage's numerator AND its
        denominator, so inside a guarded surface it is the quietest possible way to move
        this number — one comment, no baseline diff. Counting excluded lines as uncovered
        is what closes that door."""
        excluded = ratchet.measure(_report(missing_lines=0, excluded_lines=3, covered_lines=40))
        plain = ratchet.measure(_report(missing_lines=0, excluded_lines=0, covered_lines=40))
        by_area = {row.area: row.uncovered for row in excluded}
        for row in plain:
            assert by_area[row.area] > row.uncovered


# ============================================================================
# Writing the baseline: the one automated path that could move the bar
# ============================================================================


class TestBaselineWriter:
    def _file(self, tmp_path: Path, budgets: dict[str, int]) -> Path:
        path = tmp_path / "coverage_baseline.json"
        path.write_text(json.dumps({"areas": budgets}), encoding="utf-8")
        return path

    def test_an_improvement_is_written_silently(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int], tmp_path: Path
    ) -> None:
        path = self._file(tmp_path, {area: value + 5 for area, value in budgets.items()})
        assert ratchet.save_baseline(measurements, path) == []
        assert ratchet.load_baseline(path) == budgets

    def test_refuses_to_write_a_bigger_number(
        self, measurements: list[ratchet.Measurement], budgets: dict[str, int], tmp_path: Path
    ) -> None:
        """`--update-baseline` is the one automated step that could bless a regression,
        so it refuses — exactly as `scripts/eval.py:save_baseline` refuses to waive a
        wrong extraction value. The bar moves in a script diff a reviewer can argue with,
        never in a JSON number nobody reads."""
        path = self._file(tmp_path, budgets)
        refused = ratchet.save_baseline(_bumped(measurements, "compliance-gate", +9), path)
        assert any("compliance-gate" in message for message in refused)
        assert ratchet.load_baseline(path) == budgets, "the floor did not move"

    def test_a_waiver_authorizes_the_raise_and_then_expires(
        self,
        measurements: list[ratchet.Measurement],
        budgets: dict[str, int],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The sanctioned way up, and its expiry. A waiver that outlives the raise it
        bought is a standing permission — the shape `check_wiring.stale_baseline()`
        refuses, for the same reason."""
        raised = budgets["dial-path"] + 9
        reason = (
            "the D-21 callback surface landed with an engine path that cannot be "
            "exercised until pilot gate 5 hands us a staging clone; closes when the "
            "fake adapter can replay it"
        )
        monkeypatch.setattr(ratchet, "RAISED_BUDGETS", {"dial-path": (raised, reason)})
        path = self._file(tmp_path, budgets)

        assert ratchet.save_baseline(_bumped(measurements, "dial-path", +9), path) == []
        assert ratchet.load_baseline(path)["dial-path"] == raised
        assert ratchet.stale_waivers(ratchet.load_baseline(path)) == []

        # …and once the area is covered again, the waiver has to go.
        assert ratchet.save_baseline(measurements, path) == []
        assert any("spent" in f for f in ratchet.stale_waivers(ratchet.load_baseline(path)))

    def test_a_waiver_too_thin_to_review_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ratchet, "RAISED_BUDGETS", {"redaction": (999, "TODO")})
        assert any("too thin" in f for f in ratchet.stale_waivers({"redaction": 999}))

    def test_a_waiver_for_a_dead_area_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ratchet, "RAISED_BUDGETS", {"gone": (1, "x" * 200)})
        assert any("names no area" in f for f in ratchet.stale_waivers({"gone": 1}))

    def test_the_waiver_set_is_pinned(self) -> None:
        """Raising a budget must cost a visible diff in a TEST as well as in the script —
        the pin `check_rls_coverage`'s exemptions and
        `check_redaction_exposure.KNOWN_SAFE_FIELDS` carry, for the same reason. If this
        fails, review the new waiver on its merits (what forced it, what closes it)."""
        assert set(ratchet.RAISED_BUDGETS) == set()

    def test_the_live_waivers_all_still_hold(self) -> None:
        assert ratchet.stale_waivers() == []


# ============================================================================
# Refusing to score a run it cannot trust
# ============================================================================


class TestBlindSpots:
    def test_a_fresh_full_measurement_is_scorable(
        self, measurements: list[ratchet.Measurement], tmp_path: Path
    ) -> None:
        data = tmp_path / ".coverage"
        data.write_bytes(b"")
        assert ratchet.blind_spots(_report(), measurements, data) == []

    def test_refuses_a_run_with_no_branch_data(
        self, measurements: list[ratchet.Measurement], tmp_path: Path
    ) -> None:
        """Every budget counts partial branches. Scoring a line-only run would compare
        two different numbers and call the difference progress."""
        data = tmp_path / ".coverage"
        data.write_bytes(b"")
        report = _report()
        report["meta"]["branch_coverage"] = False
        assert any("WITHOUT branch coverage" in f for f in ratchet.blind_spots(report, [], data))

    def test_refuses_a_run_where_a_whole_area_never_executed(
        self, measurements: list[ratchet.Measurement], tmp_path: Path
    ) -> None:
        """What a filtered suite or a missing database looks like. Reporting that as a
        regression is how a guardrail teaches people to re-baseline past it."""
        data = tmp_path / ".coverage"
        data.write_bytes(b"")
        blinded = [
            replace(row, executed=0) if row.area == "compliance-gate" else row
            for row in measurements
        ]
        failures = ratchet.blind_spots(_report(), blinded, data)
        assert any("NONE of them executed" in f for f in failures)

    def test_refuses_an_area_that_matched_nothing(
        self, measurements: list[ratchet.Measurement], tmp_path: Path
    ) -> None:
        data = tmp_path / ".coverage"
        data.write_bytes(b"")
        emptied = [
            replace(row, files=0) if row.area == "redaction" else row for row in measurements
        ]
        assert any("matched no file" in f for f in ratchet.blind_spots(_report(), emptied, data))

    def test_refuses_a_measurement_older_than_the_code(
        self, measurements: list[ratchet.Measurement], tmp_path: Path
    ) -> None:
        """A stale `.coverage` scores code it never ran, and every line it never ran
        looks like a regression. The mutation is the data file's mtime, not the report."""
        stale = tmp_path / ".coverage"
        stale.write_bytes(b"")
        os.utime(stale, (0, 0))
        failures = ratchet.blind_spots(_report(), measurements, stale)
        assert any("older than" in f for f in failures)

    def test_main_says_so_when_there_is_no_measurement_at_all(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The real `main()`, pointed at nothing. A coverage gate with no measurement
        must fail loudly: a silent pass here is a green gate that never ran."""
        assert ratchet.main(["--data-file", str(tmp_path / "nope")]) == 1
        assert "no measurement" in capsys.readouterr().out


# ============================================================================
# The parser, against the real artefact
# ============================================================================


class TestReportParsing:
    def test_reads_the_real_coverage_data(self) -> None:
        """Wiring: coverage.py's JSON shape is what `measure()` reads, so read the real
        one. Skips on a fresh checkout, where no run has happened yet — the gate itself
        covers that case, and it runs one step after the suite."""
        try:
            report = ratchet.load_report()
        except FileNotFoundError:
            pytest.skip("no .coverage in the tree — `make coverage-ratchet` writes one")

        assert report["meta"]["branch_coverage"] is True, "pyproject sets branch = true"
        rows = ratchet.measure(report)
        assert {row.area for row in rows} == {area.name for area in ratchet.AREAS}
        assert all(row.files for row in rows), "every area must match measured files"
