"""D-166's two properties: the evidence expires, and the validator cannot forge it.

The second is the one the decision exists to record, so it is tested three ways that fail
independently — an AST property re-derived HERE rather than borrowed from the check, a
detection test that plants a writer and requires the check's own audit to see it, and a
runtime test that runs the real check against the real directory and proves not one byte
moved. A check that only asserted its own opinion of itself would be the same closed loop
`dr-stale-drill-check.js` and `dr-ephemeral-pack.js` form.
"""

from __future__ import annotations

import ast
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import check_drill_freshness as guard
from scripts.check_drill_freshness import DrillRecord, Evidence

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_SOURCE = REPO_ROOT / "scripts" / "check_drill_freshness.py"

NOW_2026_Q3 = datetime(2026, 8, 17, tzinfo=UTC)


def _record(
    year: int,
    quarter: int,
    verdict: str | None = "PASS",
    *,
    unfilled: bool = False,
) -> DrillRecord:
    return DrillRecord(
        name=f"restore-drill-{year}-Q{quarter}.md",
        year=year,
        quarter=quarter,
        verdict=verdict,
        unfilled=unfilled,
    )


def _evidence(*records: DrillRecord, local: tuple[str, ...] = ()) -> Evidence:
    return Evidence(quarterly=records, local=local, unrecognised=())


# ============================================================================
# THE VALIDATOR REFUSES TO BE THE GENERATOR (D-166's finding)
# ============================================================================


class TestCannotGenerateItsOwnEvidence:
    def test_the_real_module_passes_its_own_audit(self) -> None:
        assert guard.check_this_module_cannot_write() == []

    def test_imports_are_re_derived_here_rather_than_taken_on_trust(self) -> None:
        """The one rule this file deliberately re-implements.

        Everywhere else in this repo a guardrail test calls the guardrail's own functions,
        because a test that re-implements the rule proves only that two copies agree. This
        is the exception and the reason is the subject: the property is "the checker cannot
        write", and asking the checker whether it can write is precisely the closed loop
        D-166 is about. So the import set is walked here, independently, and this test
        still fails if `check_this_module_cannot_write` is deleted outright.
        """
        tree = ast.parse(GUARD_SOURCE.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        assert not imported - {
            "__future__",
            "argparse",
            "ast",
            "dataclasses",
            "datetime",
            "pathlib",
            "re",
            "sys",
        }, "the drill validator imported something that can write, or reach a producer"
        assert "scripts" not in imported, (
            "the validator must not be able to reach `scripts.restore_drill`, which is the "
            "program that produces drill records"
        )

    @pytest.mark.parametrize(
        "planted",
        [
            pytest.param("import subprocess\n", id="import-subprocess"),
            pytest.param("import os\n", id="import-os"),
            pytest.param("from scripts import restore_drill\n", id="import-the-producer"),
            pytest.param("import tempfile\n", id="import-tempfile"),
        ],
    )
    def test_the_audit_catches_a_planted_import(self, planted: str) -> None:
        source = planted + GUARD_SOURCE.read_text(encoding="utf-8")
        failures = guard.check_this_module_cannot_write(source)
        assert any("ALLOWED_IMPORTS" in failure for failure in failures), failures

    @pytest.mark.parametrize(
        "planted",
        [
            pytest.param(
                'def _forge() -> None:\n    Path("x.md").write_text("PASS")\n',
                id="write_text",
            ),
            pytest.param('def _forge() -> None:\n    Path("x.md").touch()\n', id="touch"),
            pytest.param(
                "def _forge() -> None:\n    EVIDENCE_DIR.mkdir(parents=True)\n", id="mkdir"
            ),
            pytest.param('def _forge() -> None:\n    handle = open("x.md", "w")\n', id="open"),
        ],
    )
    def test_the_audit_catches_a_planted_writer(self, planted: str) -> None:
        source = GUARD_SOURCE.read_text(encoding="utf-8") + "\n\n" + planted
        failures = guard.check_this_module_cannot_write(source)
        assert any("create or refresh a file" in failure for failure in failures), failures

    def test_main_runs_the_audit_before_it_reports_anything(self) -> None:
        """Not decoration: the audit has to be on the path CI takes, not only in pytest."""
        tree = ast.parse(GUARD_SOURCE.read_text(encoding="utf-8"))
        main = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        called = {
            node.func.id
            for node in ast.walk(main)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "check_this_module_cannot_write" in called

    def test_a_real_run_changes_nothing_in_the_evidence_directory(self) -> None:
        """The runtime half. Names, sizes and mtimes, before and after the real check."""

        def snapshot() -> dict[str, tuple[int, int]]:
            return {
                entry.name: (entry.stat().st_size, entry.stat().st_mtime_ns)
                for entry in os.scandir(guard.EVIDENCE_DIR)
            }

        before = snapshot()
        assert guard.main([]) in (0, 1)
        assert snapshot() == before

    def test_it_does_not_conjure_a_directory_it_was_pointed_at(self, tmp_path: Path) -> None:
        """The reference's generator starts with `fs.mkdirSync(..., {recursive: true})`.

        Pointed at a directory that does not exist, this must report NOT RUN and leave the
        filesystem exactly as it found it — an evidence directory that appears because a
        CHECK ran is the first step of the shortcut.
        """
        missing = tmp_path / "no-such-evidence"
        assert guard.main(["--evidence-dir", str(missing)]) == 0
        assert not missing.exists()

        empty = tmp_path / "evidence"
        empty.mkdir()
        assert guard.main(["--evidence-dir", str(empty)]) == 0
        assert list(empty.iterdir()) == []


# ============================================================================
# THE EXPIRY ITSELF
# ============================================================================


class TestFreshness:
    def test_the_current_quarter_passes(self) -> None:
        assert guard.evaluate(_evidence(_record(2026, 3)), NOW_2026_Q3) == []

    def test_one_quarter_behind_is_still_evidence(self) -> None:
        """The drill is quarterly, so last quarter's record is the current proof."""
        assert guard.evaluate(_evidence(_record(2026, 2)), NOW_2026_Q3) == []

    def test_two_quarters_behind_is_refused(self) -> None:
        failures = guard.evaluate(_evidence(_record(2026, 1)), NOW_2026_Q3)
        assert any("skipped" in failure and "2026 Q1" in failure for failure in failures)

    def test_a_year_old_record_is_refused(self) -> None:
        failures = guard.evaluate(_evidence(_record(2025, 3)), NOW_2026_Q3)
        assert any("quarters" in failure for failure in failures)

    def test_the_newest_record_is_the_one_judged(self) -> None:
        """An ancient record sitting beside a current one must not fail the check, and a
        current one must not be hidden by an ancient one."""
        evidence = _evidence(_record(2024, 1), _record(2026, 3), _record(2025, 2))
        assert guard.evaluate(evidence, NOW_2026_Q3) == []

    def test_a_post_dated_record_is_refused(self) -> None:
        failures = guard.evaluate(_evidence(_record(2027, 1)), NOW_2026_Q3)
        assert any("has not happened yet" in failure for failure in failures)

    def test_two_records_for_one_quarter_are_refused(self) -> None:
        duplicate = DrillRecord(
            name="restore-drill-2026-Q3.md",
            year=2026,
            quarter=3,
            verdict="PARTIAL",
            unfilled=False,
        )
        other = DrillRecord(
            name="restore-drill-2026-Q3.md",
            year=2026,
            quarter=3,
            verdict="PASS",
            unfilled=False,
        )
        failures = guard.evaluate(_evidence(duplicate, other), NOW_2026_Q3)
        assert any("two records claim" in failure for failure in failures)


class TestVerdict:
    def test_partial_is_accepted(self) -> None:
        """Runbook §9: 'a PARTIAL with a named follow-up is a good drill'."""
        assert guard.evaluate(_evidence(_record(2026, 3, "PARTIAL")), NOW_2026_Q3) == []

    def test_a_failed_drill_does_not_reset_the_clock(self) -> None:
        failures = guard.evaluate(_evidence(_record(2026, 3, "FAIL")), NOW_2026_Q3)
        assert any("did not demonstrate a recovery" in failure for failure in failures)

    def test_a_record_with_no_verdict_is_refused(self) -> None:
        failures = guard.evaluate(_evidence(_record(2026, 3, None)), NOW_2026_Q3)
        assert any("no `**PASS**`" in failure for failure in failures)

    def test_the_unfilled_template_is_refused(self) -> None:
        record = _record(2026, 3, None, unfilled=True)
        failures = guard.evaluate(_evidence(record), NOW_2026_Q3)
        assert any("unfilled verdict line" in failure for failure in failures)


class TestWhatCountsAsARecord:
    """The distinction the reference implementation did not have, and the one that keeps
    `make restore-drill` from refreshing the gate that judges it."""

    def _write(self, directory: Path, name: str, body: str) -> None:
        (directory / name).write_text(body, encoding="utf-8")

    def test_a_local_harness_record_is_counted_and_is_not_evidence(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "restore-drill-local-20260817t101500z.md",
            "# Local restore drill\n- **Verdict: GREEN (local scope)**\n",
        )
        evidence = guard.read_evidence(tmp_path)
        assert evidence.quarterly == ()
        assert evidence.local == ("restore-drill-local-20260817t101500z.md",)
        assert guard.evaluate(evidence, NOW_2026_Q3) == []

    def test_a_pile_of_local_records_never_becomes_a_drill(self, tmp_path: Path) -> None:
        """`make restore-drill` writes into `docs/evidence/` and can be run in a loop.

        If that could satisfy this check, the gate would be the reference's: a generator
        that writes a pass and a validator that reads it, in one job.
        """
        for index in range(5):
            self._write(
                tmp_path,
                f"restore-drill-local-2026081{index}t101500z.md",
                "**Verdict: GREEN (local scope)**\n",
            )
        evidence = guard.read_evidence(tmp_path)
        assert evidence.quarterly == ()
        assert len(evidence.local) == 5

    def test_a_sabotage_run_record_is_not_evidence_either(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "restore-drill-local-20260817t101500z-drop-rls-policy.md",
            "**Verdict: RED**\n",
        )
        assert guard.read_evidence(tmp_path).quarterly == ()

    def test_a_misnamed_quarterly_record_is_reported_rather_than_ignored(
        self, tmp_path: Path
    ) -> None:
        self._write(tmp_path, "restore-drill-2026-q3.md", "**PASS** — lowercase q\n")
        evidence = guard.read_evidence(tmp_path)
        assert evidence.unrecognised == ("restore-drill-2026-q3.md",)
        failures = guard.evaluate(evidence, NOW_2026_Q3)
        assert any("matches neither" in failure for failure in failures)

    def test_the_verdict_is_read_out_of_the_real_template(self, tmp_path: Path) -> None:
        """Wiring: parsed against runbook §9's actual shape, not an invented one."""
        runbook = (REPO_ROOT / "runbooks" / "backup-restore-drill.md").read_text(encoding="utf-8")
        template = runbook.split("# Restore drill — <YYYY> Q<N>", 1)[1].split("```", 1)[0]
        self._write(tmp_path, "restore-drill-2026-Q3.md", template)
        record = guard.read_evidence(tmp_path).quarterly[0]
        assert record.unfilled, "the committed template must never read as a drill result"

        self._write(
            tmp_path,
            "restore-drill-2026-Q3.md",
            template.replace("**PASS | PARTIAL | FAIL**", "**PASS**"),
        )
        assert guard.read_evidence(tmp_path).quarterly[0].verdict == "PASS"

    def test_the_quarter_comes_from_the_name_and_not_from_the_mtime(self, tmp_path: Path) -> None:
        """`touch` is how the reference's clock is reset. Here it changes nothing."""
        path = tmp_path / "restore-drill-2024-Q1.md"
        path.write_text("**PASS** — ancient\n", encoding="utf-8")
        os.utime(path, None)
        failures = guard.evaluate(guard.read_evidence(tmp_path), NOW_2026_Q3)
        assert any("quarters" in failure for failure in failures)


class TestWiring:
    def test_it_reads_the_real_evidence_directory(self) -> None:
        """A check pointed at a directory that does not exist would pass forever."""
        assert guard.EVIDENCE_DIR.exists()
        assert guard.EVIDENCE_DIR == REPO_ROOT / "docs" / "evidence"
        guard.read_evidence()  # must not raise on the real tree

    def test_the_local_harness_writes_where_this_check_looks(self) -> None:
        """The two halves must be pointed at one directory, or the exclusion above is
        excluding nothing. Read off `restore_drill`'s own constant, never restated."""
        from scripts.restore_drill import DEFAULT_RECORD_DIR

        assert DEFAULT_RECORD_DIR == guard.EVIDENCE_DIR

    def test_the_local_record_filename_still_matches_the_exclusion(self) -> None:
        """If `write_record` is renamed, the local records stop being excluded and start
        counting as drills — silently, and in the direction that manufactures confidence."""
        import inspect

        from scripts import restore_drill

        source = inspect.getsource(restore_drill.write_record)
        assert "restore-drill-local-" in source
        assert guard.LOCAL_RECORD.match("restore-drill-local-20260817t101500z.md")

    def test_the_current_quarter_is_computed_the_way_a_calendar_does(self) -> None:
        assert guard.current_quarter(datetime(2026, 1, 1, tzinfo=UTC)) == (2026, 1)
        assert guard.current_quarter(datetime(2026, 3, 31, tzinfo=UTC)) == (2026, 1)
        assert guard.current_quarter(datetime(2026, 4, 1, tzinfo=UTC)) == (2026, 2)
        assert guard.current_quarter(datetime(2026, 12, 31, tzinfo=UTC)) == (2026, 4)
