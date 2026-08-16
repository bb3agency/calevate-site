"""Negative controls for `scripts/check_coverage_ratchet.py` (D-29 `coverage:ratchet`).

Same doctrine as `tests/wiring_guard_test.py`, `docs_drift_guard_test.py` and
`guardrail_audit_test.py`: a guardrail that stays green while the violation it names is
present is worse than no guardrail, so every test here calls the guard's OWN functions,
applies ONE minimal mutation that is exactly the violation it claims to catch, and
asserts it is reported.

The mutations are the three ways a coverage ratchet dies:

1. **coverage falls** — new untested code lands in a hard-rule surface;
2. **somebody raises the number** — the "just this once" edit that turns a ratchet into
   a target. The gate is an EQUALITY, so a hand-raised budget cannot sit quietly above
   the measurement: it fails on the very next run, and the only sanctioned way up is a
   `RAISED_BUDGETS` waiver, which this file also proves is self-expiring;
3. **the gate scores a run it has no business scoring** — and the number it prints is an
   artefact of where it ran. Not hypothetical: two fictional regressions reached CI
   (`compliance-gate: budget 70, but only 68`, `voice-runtime-ack: 24 vs 22`), both
   "fixed" by editing the fixture, and the cause recorded in those commits (a dev
   database holding 31,527 leftover test organizations) turned out to be wrong — a
   freshly seeded database measured the same 70 and 24. The real causes were a WARM
   REDIS (the audit-head cache deletes a Postgres fallback from the measurement) and a
   machine fast enough never to breach the 500ms ack budget. A gate that reports a
   verdict it cannot support teaches the fixture edit; one that refuses teaches the
   diagnosis. `TestVouchingForTheRun` and `TestRefusalReachesTheExitCode` below are the
   controls for that third outcome — REFUSED TO SCORE — including the two that matter
   most: a partial run must refuse rather than report a regression, and must refuse
   rather than report an improvement.

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
fail.

The exception is `TestRefusalReachesTheExitCode`, which needs the real `main()` end to end
and therefore needs a real measurement to feed it. It builds one: a subprocess that imports
every guarded module under `coverage run`, into a scratch directory (~2s, once per module).
Not the repo's own `.coverage`, which does not exist on a fresh CI checkout — a negative
control that skips exactly where it matters is not a control.

`TestReportParsing` reads that same scratch measurement, and it did not always. It read
`REPO_ROOT/.coverage`, which is a mutable file at a well-known path that no test owns: any
partial `coverage run` left behind by anything failed it, twice in one session, on a
surface the change under test had never touched. That class's docstring records the
mechanism and `partial_coverage_at_the_repo_root` plants the poison to prove it is over.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import coverage
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


def _report(_excluded: dict[str, list[int]] | None = None, **overrides: Any) -> dict[str, Any]:
    """A coverage JSON report shaped like the real one, over the REAL guarded files.

    `_excluded` maps a repo-relative path to the line numbers coverage excluded there.
    It is a TOP-LEVEL key rather than a summary count because that is where the real
    report puts the numbers, and `_suppressed_lines` needs the numbers to read the source.
    """
    summary = {**PER_FILE, **overrides}
    planted = _excluded or {}
    return {
        "meta": {"branch_coverage": True, "format": 3},
        "files": {
            name: {"summary": dict(summary), "excluded_lines": planted.get(name, [])}
            for name in (
                path.relative_to(REPO_ROOT).as_posix() for path in ratchet._guarded_sources()
            )
        },
    }


#: A module whose every exclusion is one COVERAGE chose: a `...`-bodied Protocol method
#: and a `TYPE_CHECKING` import guard. Nobody wrote a suppression here, so the ratchet
#: must charge nothing for it.
_STRUCTURAL_SOURCE = """\
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from decimal import Decimal


class Recorder(Protocol):
    def __call__(self, ms: float, *, provider: str) -> None: ...


def rate() -> int:
    return 1
"""

#: The same shape plus ONE deliberate suppression. Exactly one unit is owed.
_SUPPRESSED_SOURCE = """\
from typing import Protocol


class Recorder(Protocol):
    def __call__(self, ms: float) -> None: ...


def rate(flag: bool) -> int:
    if flag:  # pragma: no cover
        return 0
    return 1
"""


_PROBE_NAME = "probe.py"


def _coverage_excluded(tmp_path: Path, source: str) -> set[int]:
    """Which lines COVERAGE excludes from `source`, measured by running it.

    A subprocess with this repo's own config, because the two structural defaults under
    test are version-dependent behaviour of the INSTALLED coverage — the thing a test may
    not take on faith from a changelog. The module is left on disk at `tmp_path` so the
    caller can point `_suppressed_lines` at the very file these numbers describe.
    """
    module = tmp_path / _PROBE_NAME
    module.write_text(source, encoding="utf-8")
    data = tmp_path / ".coverage"
    completed = subprocess.run(
        [sys.executable, "-m", "coverage", "run", "--data-file", str(data), str(module)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    cov = coverage.Coverage(data_file=str(data))
    cov.load()
    return set(cov._analyze(str(module)).excluded)


#: A manifest describing the run every trust test starts from: the whole suite, green,
#: both services up, and a database that held nothing before the first test. Each test
#: below moves exactly one of these, so the refusal it asserts can only come from that one.
_NOW = 1_780_000_000.0
_OUTCOMES = {"passed": 1197, "failed": 0, "errors": 0, "skipped": 3, "xfailed": 2}
_SELECTION = {
    "args": ["tests", "apps", "packages"],
    "args_source": "TESTPATHS",
    "keyword": "",
    "markexpr": "",
    "last_failed": False,
}
_SERVICES = {
    "postgres": {
        "env": "DATABASE_URL",
        "url": "postgresql+psycopg://localhost:5432/calevate",
        "reachable": True,
        "detail": "",
    },
    "redis": {
        "env": "REDIS_URL",
        "url": "redis://localhost:6379/0",
        "reachable": True,
        "detail": "",
    },
}
#: Both stores as CI provisions them: a database migrated and seeded a minute ago, and a
#: Redis container that has never served a suite.
_FRESH_STATE = {
    "postgres": {
        "probed": True,
        "why": "What the database HOLDS decides which branches execute",
        "remedy": "`make db-reset`",
        "detail": "",
        "held": {},
        "summary": "",
    },
    "redis": {
        "probed": True,
        "why": "A warm cache DELETES fallbacks from the measurement",
        "remedy": "`make down && make up` empties it",
        "detail": "",
        "held": {},
        "summary": "",
    },
}
_DEAD_REDIS = {
    "env": "REDIS_URL",
    "url": "redis://localhost:6379/0",
    "reachable": False,
    "detail": "ConnectionError: Error 111 connecting to localhost:6379. Connection refused.",
}


def _run_dict(**overrides: Any) -> dict[str, Any]:
    """The manifest as the plugin writes it (`TestTheRecorderRecordsWhatHappened` pins
    that this shape is the shape it writes, so these are not two independent fictions)."""
    return {
        "schema": ratchet.MANIFEST_SCHEMA,
        "finished_at": _NOW,
        "coverage_active": True,
        "exit_status": 0,
        "collected": 1202,
        "collection_errors": 0,
        "collection_skips": 0,
        "deselected": 0,
        "outcomes": dict(_OUTCOMES),
        "selection": dict(_SELECTION),
        "skip_reasons": {},
        "services": {name: dict(row) for name, row in _SERVICES.items()},
        "pre_suite_state": {name: dict(row) for name, row in _FRESH_STATE.items()},
    } | overrides


def _run(**overrides: Any) -> ratchet.RunManifest:
    return ratchet.RunManifest.parse(_run_dict(**overrides))


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

    def test_a_no_cover_comment_does_not_lower_the_number(self) -> None:
        """A no-cover comment deletes a line from coverage's numerator AND its
        denominator, so inside a guarded surface it is the quietest possible way to move
        this number — one comment, no baseline diff. Charging for suppressed lines is
        what closes that door, and this is the arithmetic that does it.

        The other half — that `suppressed` counts an author's comment and not coverage's
        own structural exclusions — is `TestOnlyAnAuthorsSuppressionIsCharged`.
        """
        row = ratchet.measure(_report(missing_lines=0, covered_lines=40))[0]
        assert replace(row, suppressed=row.suppressed + 3).uncovered == row.uncovered + 3


class TestOnlyAnAuthorsSuppressionIsCharged:
    """The line between "somebody chose to hide this" and "coverage does not consider
    this executable code", drawn against coverage's ACTUAL behaviour rather than a
    remembered version of it.

    It matters because `uncovered` charges for the first and must not charge for the
    second: coverage 7 excludes `...`-bodied stubs and `if TYPE_CHECKING:` blocks by
    default, and sweeps the blank lines around each excluded clause into the same set. A
    four-line `Protocol` — this repo's own typing idiom, the shape `VoiceEngine` is
    written in — cost four units in a hard rule 3 surface under a message naming a pragma
    that was not in the file. A guard that charges for good typing gets worked around.
    """

    def test_coverage_really_does_exclude_a_stub_and_a_type_checking_block(
        self, tmp_path: Path
    ) -> None:
        """READ AT SOURCE. Everything below rests on this being coverage's behaviour, so
        it is measured from a real run rather than asserted from the changelog."""
        excluded = _coverage_excluded(tmp_path, _STRUCTURAL_SOURCE)
        body = _STRUCTURAL_SOURCE.splitlines()
        hit = {body[n - 1].strip() for n in excluded}
        assert any(line.endswith("...") for line in hit), f"no stub excluded: {sorted(hit)}"
        assert any("TYPE_CHECKING" in line for line in hit), f"no guard excluded: {sorted(hit)}"
        assert "" in hit, "the blank lines around an excluded clause are swept in too"

    def test_none_of_those_lines_is_charged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point: the author of that file suppressed nothing, so it owes nothing."""
        excluded = _coverage_excluded(tmp_path, _STRUCTURAL_SOURCE)
        assert excluded, "the fixture must actually produce exclusions or this proves nothing"
        monkeypatch.setattr(ratchet, "REPO_ROOT", tmp_path)
        charged = ratchet._suppressed_lines(_PROBE_NAME, {"excluded_lines": sorted(excluded)})
        assert charged == 0, f"charged {charged} units for exclusions nobody asked for"

    def test_a_comment_in_the_same_file_still_is(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The precision control. A fix that charged nothing at all would be a hole, not a
        fix — so a file carrying one deliberate suppression owes exactly one, and the
        stub and blank lines beside it still owe nothing."""
        excluded = _coverage_excluded(tmp_path, _SUPPRESSED_SOURCE)
        assert len(excluded) > 1, "the fixture must also carry structural exclusions"
        monkeypatch.setattr(ratchet, "REPO_ROOT", tmp_path)
        charged = ratchet._suppressed_lines(_PROBE_NAME, {"excluded_lines": sorted(excluded)})
        assert charged == 1, f"expected exactly the one commented line, charged {charged}"

    def test_a_deleted_file_owes_nothing_rather_than_raising(self) -> None:
        """A report can outlive the file it describes; a missing source is not a
        suppression, and a guardrail that raises on one refuses every run after a delete."""
        assert ratchet._suppressed_lines("apps/api/gone.py", {"excluded_lines": [1, 2]}) == 0


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
        must fail loudly: a silent pass here is a green gate that never ran. It exits
        REFUSED rather than FAIL because "there is no run" is not a verdict about the
        code — the distinction the two codes exist to draw."""
        assert ratchet.main(["--data-file", str(tmp_path / "nope")]) == ratchet.EXIT_REFUSED
        assert "no measurement" in capsys.readouterr().out


# ============================================================================
# The parser, against the real artefact
# ============================================================================


class TestVouchingForTheRun:
    """`vouch()` — the rules, one doctored manifest at a time.

    Every test moves ONE field of a manifest that describes a whole, clean, freshly
    databased run, and asserts the refusal names that field. The first test is the
    does-not-cry-wolf control the other twelve are measured against: a guardrail that
    refuses a good run is one people route around, and routing around this one means
    editing the baseline.
    """

    def test_a_whole_clean_run_is_vouched_for(self) -> None:
        assert ratchet.vouch(_run(), _NOW + 1.0) == []

    def test_refuses_a_run_that_was_not_instrumented(self) -> None:
        """The `.coverage` beside an uninstrumented run belongs to some earlier one."""
        failures = ratchet.vouch(_run(coverage_active=False), _NOW + 1.0)
        assert any("NOT instrumented" in f for f in failures)

    def test_refuses_a_measurement_written_before_the_run_finished(self) -> None:
        """`coverage run` writes the data file when the PROCESS exits, so an older data
        file is an orphan from a previous invocation, not this run's output."""
        failures = ratchet.vouch(_run(), _NOW - 600.0)
        assert any("not from one run" in f and "BEFORE" in f for f in failures)

    def test_refuses_a_measurement_written_long_after_the_run(self) -> None:
        failures = ratchet.vouch(_run(), _NOW + 4000.0)
        assert any("not from one run" in f for f in failures)

    def test_refuses_a_failing_suite(self) -> None:
        """Coverage from a broken run measures the branches the failures never reached."""
        failures = ratchet.vouch(
            _run(exit_status=1, outcomes={**_OUTCOMES, "failed": 2}), _NOW + 1.0
        )
        assert any("did not pass" in f and "2 failed" in f for f in failures)

    def test_refuses_a_suite_with_setup_errors(self) -> None:
        failures = ratchet.vouch(_run(outcomes={**_OUTCOMES, "errors": 9}), _NOW + 1.0)
        assert any("9 errored" in f for f in failures)

    def test_refuses_a_keyword_filtered_run(self) -> None:
        """`pytest -k` then the gate: the exact invocation that reports a catastrophe."""
        failures = ratchet.vouch(
            _run(selection={**_SELECTION, "keyword": "compliance"}, deselected=1183), _NOW + 1.0
        )
        assert any("FILTERED" in f and "1183 test(s) deselected" in f for f in failures)

    def test_refuses_a_run_that_named_its_own_paths(self) -> None:
        """`testpaths` in pyproject IS the suite; a path on the command line is a subset,
        even when it looks like it contains everything."""
        failures = ratchet.vouch(
            _run(selection={**_SELECTION, "args_source": "ARGS", "args": ["tests"]}), _NOW + 1.0
        )
        assert any("explicit path arguments" in f for f in failures)

    def test_refuses_a_last_failed_rerun(self) -> None:
        failures = ratchet.vouch(_run(selection={**_SELECTION, "last_failed": True}), _NOW + 1.0)
        assert any("--last-failed" in f for f in failures)

    def test_refuses_a_run_where_a_module_never_collected(self) -> None:
        failures = ratchet.vouch(_run(collection_skips=2), _NOW + 1.0)
        assert any("skipped at COLLECTION" in f for f in failures)

    def test_refuses_a_run_with_a_service_down(self) -> None:
        """The ~91 Redis tests skip when nothing is listening, and their branches go
        missing from the measurement. "redis was not reachable" is the sentence a reader
        can act on; "91 skipped" is the symptom they would have to diagnose."""
        down = {
            **_SERVICES,
            "redis": {
                "env": "REDIS_URL",
                "url": "redis://localhost:6380/0",
                "reachable": False,
                "detail": "ConnectionError: Connection refused",
            },
        }
        failures = ratchet.vouch(_run(services=down), _NOW + 1.0)
        assert any("redis was NOT reachable" in f and "Connection refused" in f for f in failures)

    def test_refuses_a_run_against_a_database_that_was_not_fresh(self) -> None:
        """One of the three real causes: a laptop database carrying 31,527 leftover test
        organizations sends the dispatch tick down a different path from CI's freshly
        seeded one, and the difference lands as a two-unit regression on somebody's PR."""
        lived_in = {
            **_FRESH_STATE,
            "postgres": {
                **_FRESH_STATE["postgres"],
                "held": {"organizations": 31527, "leads": 900},
                "summary": "2 tenant-scoped table(s) still held rows (organizations ~31527…)",
            },
        }
        failures = ratchet.vouch(_run(pre_suite_state=lived_in), _NOW + 1.0)
        assert any("postgres was NOT in the state" in f and "~31527" in f for f in failures)
        assert any("make db-reset" in f for f in failures)

    def test_refuses_a_run_against_a_redis_that_was_not_empty(self) -> None:
        """The cause nobody suspected and `make db-reset` cannot reach: Redis outlives the
        database, and `audit.py:_current_head` queries Postgres only on a cache MISS — so a
        warm cache deletes that fallback from the measurement. Two units of
        `compliance-gate`, decided by the age of a key."""
        warm = {
            **_FRESH_STATE,
            "redis": {
                **_FRESH_STATE["redis"],
                "held": {"keys": 71984},
                "summary": "71984 key(s) were already cached before the first test",
            },
        }
        failures = ratchet.vouch(_run(pre_suite_state=warm), _NOW + 1.0)
        assert any("redis was NOT in the state" in f and "71984" in f for f in failures)
        assert any("flushdb" in f or "make down" in f for f in failures)

    def test_refuses_a_run_whose_starting_state_could_not_be_read(self) -> None:
        """A probe that failed is not a probe that passed — said once, at the point where
        it is still diagnosable."""
        unread = {
            **_FRESH_STATE,
            "postgres": {"probed": False, "detail": "OperationalError: refused"},
        }
        failures = ratchet.vouch(_run(pre_suite_state=unread), _NOW + 1.0)
        assert any("could not be read" in f for f in failures)

    def test_refuses_when_there_is_no_manifest_beside_the_measurement(self, tmp_path: Path) -> None:
        """A `.coverage` on its own: `make test` followed by the gate, or an artefact
        left over from a run nobody can describe."""
        data = tmp_path / ".coverage"
        data.write_bytes(b"")
        failures = ratchet.unvouched_run(data)
        assert any("no run manifest" in f for f in failures)
        assert any("-p scripts.check_coverage_ratchet" in f for f in failures)

    def test_refuses_a_manifest_from_another_version_of_this_script(self, tmp_path: Path) -> None:
        """Read leniently, a manifest missing a field is a fact that went unchecked, and
        an unchecked fact inside a trust check is the hole itself."""
        data = tmp_path / ".coverage"
        data.write_bytes(b"")
        ratchet.manifest_path(data).write_text(
            json.dumps({**_run_dict(), "schema": ratchet.MANIFEST_SCHEMA + 1}), encoding="utf-8"
        )
        assert any("unreadable" in f for f in ratchet.unvouched_run(data))

    def test_refuses_a_truncated_manifest(self, tmp_path: Path) -> None:
        data = tmp_path / ".coverage"
        data.write_bytes(b"")
        ratchet.manifest_path(data).write_text('{"schema": 1, "finish', encoding="utf-8")
        assert any("unreadable" in f for f in ratchet.unvouched_run(data))


# ============================================================================
# The real `main()`, against a real measurement: refusing beats guessing
# ============================================================================


@dataclass(frozen=True)
class _RealRun:
    """A genuine coverage measurement in a scratch directory, plus what it measured."""

    data: Path
    rows: list[ratchet.Measurement]

    @property
    def measured(self) -> dict[str, int]:
        return {row.area: row.uncovered for row in self.rows}

    def manifest(self, **overrides: Any) -> None:
        """Describe the run that produced it — truthfully by default.

        The data file's mtime is refreshed first so the manifest can be paired with it and
        so `blind_spots()`'s staleness rule (a different rule, with its own test) cannot be
        what these tests trip on.
        """
        os.utime(self.data, None)
        raw = _run_dict(**overrides)
        if "finished_at" not in overrides:
            # Half a second BEFORE the data file, which is the real order: pytest finishes,
            # then the process exits and coverage saves.
            raw["finished_at"] = self.data.stat().st_mtime - 0.5
        ratchet.manifest_path(self.data).write_text(json.dumps(raw), encoding="utf-8")

    def baseline(self, path: Path, **deltas: int) -> Path:
        budgets = {area: value + deltas.get(area, 0) for area, value in self.measured.items()}
        path.write_text(json.dumps({"areas": budgets}, indent=2), encoding="utf-8")
        return path


@pytest.fixture(scope="module")
def real_run(tmp_path_factory: pytest.TempPathFactory) -> _RealRun:
    """A real `.coverage`, built by importing every guarded module under `coverage run`.

    A subprocess, because the modules are already imported in THIS process and a
    re-import would record nothing (and reloading `db.session` for a fixture's
    convenience is not a trade worth making). What it produces is coverage.py's own data
    file with this repo's own `[tool.coverage.run]` config applied — arcs, branch data
    and all — so `main()` runs against the artefact it runs against in CI, not against a
    fixture's idea of one. The numbers themselves are arbitrary and never asserted; each
    test writes the baseline it needs relative to what this measured.
    """
    scratch = tmp_path_factory.mktemp("real-run")
    data = scratch / ".coverage"
    modules = sorted({_module_name(path) for path in ratchet._guarded_sources()})
    importer = scratch / "import_every_guarded_module.py"
    importer.write_text(
        "import importlib, sys\n"
        f"sys.path[:0] = [{str(REPO_ROOT)!r}, {str(REPO_ROOT / 'apps' / 'voice-runtime')!r}]\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-m", "coverage", "run", "--data-file", str(data), str(importer)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"could not build a measurement:\n{completed.stderr}"
    report = ratchet.load_report(data)
    rows = ratchet.measure(report)
    assert ratchet.blind_spots(report, rows, data) == [], (
        "the scratch measurement must itself be scoreable, or these controls prove nothing"
    )
    return _RealRun(data=data, rows=rows)


def _module_name(path: Path) -> str:
    """`apps/api/db/session.py` -> `apps.api.db.session`; voice-runtime is on sys.path."""
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    if relative.parts[:2] == ("apps", "voice-runtime"):
        return relative.name
    return ".".join(relative.parts)


@pytest.fixture
def partial_coverage_at_the_repo_root(tmp_path: Path) -> Iterator[Path]:
    """Plant the artefact that has broken this file twice, exactly where it broke it.

    A REAL one-module `coverage run` — the shape a developer measuring one file or an
    agent checking its own module leaves behind — copied over `REPO_ROOT/.coverage`, with
    whatever was there restored byte-for-byte (and mtime-for-mtime) afterwards. Real
    rather than a doctored file because the poison has to be poisonous in the way the
    original was: coverage's source walk skips directories with no `__init__.py`, and
    D-18 makes `apps/voice-runtime` hyphenated, so a partial run's data file contains no
    line of hard rule 3's service and `voice-runtime-ack` matches nothing.

    MUTATING THE REAL TREE, in the doctrine `test_catches_a_new_ledger_module_nobody_
    guarded` already uses: a control that plants the poison somewhere the code does not
    look proves only that the code does not look there. It is safe to do mid-suite even
    when the suite is itself under `coverage run`, and that was MEASURED rather than
    assumed: `coverage run` erases the data file at START and holds no handle on it until
    the process saves at exit, so a file written and removed in between is overwritten by
    that save and cannot reach the gate's own measurement.
    """
    poison = tmp_path / ".coverage"
    script = tmp_path / "measure_one_module.py"
    script.write_text(
        # REPO_ROOT only — deliberately NOT apps/voice-runtime, because a partial run is
        # exactly one that never reaches it. One guarded module, imported and called.
        f"import sys\nsys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from apps.workers.redaction import redact\n\n"
        'redact("call me back on 9876543210")\n',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-m", "coverage", "run", "--data-file", str(poison), str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"could not build a partial run:\n{completed.stderr}"

    # The control's own precondition. If a partial run stops being able to break the old
    # test, the control below is passing for the wrong reason and must say so HERE, where
    # the reason is visible, rather than by going quietly green.
    blinded = [row.area for row in ratchet.measure(ratchet.load_report(poison)) if not row.files]
    assert blinded, (
        "the planted measurement matches every guarded area, so it is not the poison this "
        "control exists to survive — rebuild it from a genuinely partial run"
    )

    live = ratchet.DATA_FILE
    before = live.read_bytes() if live.exists() else None
    stat = live.stat() if live.exists() else None
    try:
        live.write_bytes(poison.read_bytes())
        yield live
    finally:
        if before is None:
            live.unlink(missing_ok=True)
        else:
            live.write_bytes(before)
            if stat is not None:
                os.utime(live, (stat.st_atime, stat.st_mtime))


class TestRefusalReachesTheExitCode:
    """End to end: `main()`, a real measurement, and a manifest that says what happened.

    These four are the load-bearing ones. The first two are the whole argument for the
    third outcome — an untrustworthy run must not be reported as a regression OR as an
    improvement, because both readings are believable, actionable and wrong, and acting
    on either one moves the committed baseline. The third closes the door the wrong
    number actually walks through. The fourth is the does-not-cry-wolf control.
    """

    def _score(
        self, run: _RealRun, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str
    ) -> int:
        monkeypatch.setattr(ratchet, "BASELINE", tmp_path / "coverage_baseline.json")
        return ratchet.main(["--data-file", str(run.data), *args])

    def test_a_partial_run_refuses_instead_of_reporting_a_regression(
        self,
        real_run: _RealRun,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Redis down. The budgets say the tree is 3 units better than this run measured,
        so the ratchet WOULD cry regression — and the person reading it would go looking
        for untested code that does not exist."""
        real_run.baseline(tmp_path / "coverage_baseline.json", **{"compliance-gate": -3})
        real_run.manifest(services={**_SERVICES, "redis": _DEAD_REDIS})

        code = self._score(real_run, tmp_path, monkeypatch)
        out = capsys.readouterr().out

        assert code == ratchet.EXIT_REFUSED
        assert "REFUSED TO SCORE" in out and "redis was NOT reachable" in out
        assert "New untested code" not in out, "it must not name a regression it cannot see"

    def test_a_partial_run_refuses_instead_of_reporting_an_improvement(
        self,
        real_run: _RealRun,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The direction that actually happened twice, and the more dangerous one: an
        "improvement" is a thing you are INVITED to lock in, and locking it in writes the
        artefact of a filtered run into the file everybody else is measured against."""
        real_run.baseline(tmp_path / "coverage_baseline.json", **{"redaction": +7})
        real_run.manifest(selection={**_SELECTION, "keyword": "redaction"}, deselected=990)

        code = self._score(real_run, tmp_path, monkeypatch)
        out = capsys.readouterr().out

        assert code == ratchet.EXIT_REFUSED
        assert "FILTERED" in out and "990 test(s) deselected" in out
        assert "not at the floor" not in out, "an artefact must not be offered as a gain"
        assert "coverage-ratchet-accept" not in out, "and must not invite the write"

    def test_update_baseline_refuses_to_write_from_a_run_it_cannot_vouch_for(
        self,
        real_run: _RealRun,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The half that stops the drift. Every wrong number this gate has ever failed on
        entered through this command, run against a lived-in database."""
        baseline = real_run.baseline(tmp_path / "coverage_baseline.json", **{"redaction": +7})
        before = baseline.read_text(encoding="utf-8")
        real_run.manifest(
            pre_suite_state={
                **_FRESH_STATE,
                "postgres": {
                    **_FRESH_STATE["postgres"],
                    "held": {"organizations": 31527},
                    "summary": "1 tenant-scoped table(s) still held rows (organizations ~31527)",
                },
            }
        )

        code = self._score(real_run, tmp_path, monkeypatch, "--update-baseline")
        out = capsys.readouterr().out

        assert code == ratchet.EXIT_REFUSED
        assert "postgres was NOT in the state" in out and "~31527" in out
        assert baseline.read_text(encoding="utf-8") == before, "the floor must not have moved"

    def test_a_whole_clean_run_is_still_scored_normally(
        self,
        real_run: _RealRun,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Cry wolf once and the next refusal is read as noise. A run that says it was
        whole, green, serviced and freshly databased is scored exactly as before."""
        real_run.baseline(tmp_path / "coverage_baseline.json")
        real_run.manifest()

        code = self._score(real_run, tmp_path, monkeypatch)
        out = capsys.readouterr().out

        assert code == 0, out
        assert "REFUSED" not in out and "OK (" in out
        assert "run: " in out, "the run's shape is printed with the verdict, always"

    def test_a_vouched_run_still_reports_a_real_regression_and_says_where(
        self,
        real_run: _RealRun,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The control that keeps the other four honest. Everything above proves the gate
        can decline; this proves declining did not become its answer to everything — a run
        it CAN vouch for, three units over budget, still fails with a verdict (exit 1, not
        2) and now names the lines, because "70 vs 68" is a number and
        `webhook_routes.py:182` is a diagnosis."""
        real_run.baseline(tmp_path / "coverage_baseline.json", **{"compliance-gate": -3})
        real_run.manifest()

        code = self._score(real_run, tmp_path, monkeypatch)
        out = capsys.readouterr().out

        assert code == ratchet.EXIT_FAIL
        assert "New untested code" in out and "REFUSED" not in out
        assert "compliance-gate — where its" in out
        assert "apps/api/compliance/service.py:" in out, "the detail names files and lines"

    def test_a_whole_clean_run_can_still_lock_in_an_improvement(
        self,
        real_run: _RealRun,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The writer's does-not-cry-wolf control: refusing every write would be as
        useless as accepting every one — the ratchet has to still be able to click."""
        baseline = real_run.baseline(tmp_path / "coverage_baseline.json", **{"redaction": +7})
        real_run.manifest()

        code = self._score(real_run, tmp_path, monkeypatch, "--update-baseline")

        assert code == 0, capsys.readouterr().out
        assert ratchet.load_baseline(baseline) == real_run.measured


class TestTheRecorderRecordsWhatHappened:
    """The writer half, against a real pytest run — because a manifest nobody writes is a
    trust check that always refuses, and one written in a shape the reader does not parse
    is a trust check that always refuses two releases from now. The claim under test is
    the one the single-file design makes: what the plugin writes, `RunManifest.parse`
    reads."""

    def test_a_real_pytest_run_writes_a_manifest_the_gate_can_read(self, tmp_path: Path) -> None:
        suite = tmp_path / "recorder_probe_test.py"
        suite.write_text(
            "import pytest\n"
            "def test_one() -> None:\n    assert True\n"
            "@pytest.mark.skip(reason='no telephone line in the test rig')\n"
            "def test_two() -> None:\n    assert False\n",
            encoding="utf-8",
        )
        data = tmp_path / ".coverage"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--data-file",
                str(data),
                "-m",
                "pytest",
                "-q",
                "-p",
                "scripts.check_coverage_ratchet",
                str(suite),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

        raw = json.loads(ratchet.manifest_path(data).read_text(encoding="utf-8"))
        manifest = ratchet.RunManifest.parse(raw)

        assert manifest.coverage_active, "the plugin found the Coverage object tracing it"
        assert manifest.collected == 2 and manifest.passed == 1 and manifest.skipped == 1
        assert "no telephone line in the test rig" in " ".join(manifest.skip_reasons)
        assert set(manifest.services) == {"postgres", "redis"}
        assert set(manifest.pre_suite_state) == {"postgres", "redis"}
        assert "@" not in str(manifest.services["postgres"]["url"]), "no credentials in a log"
        redis_held: dict[str, Any] = dict(manifest.pre_suite_state["redis"].get("held", {}))
        assert set(redis_held) <= {"keys"}, (
            "a COUNT of keys, never the keys themselves: ARQ job keys carry execution ids "
            "and tenant slugs, and this artefact is printed into a build log (hard rule 6)"
        )
        # …and the gate refuses it, because two tests in a temp directory are not the suite.
        assert any("FILTERED" in f for f in ratchet.vouch(manifest, data.stat().st_mtime))


class TestTheRefusalCannotBeSkippedPast:
    """Wiring. A refusal is only a gate if the commands that produce measurements record
    them, and if nothing tolerates a non-zero exit — the `check_wiring` lesson, applied to
    this gate's own plumbing."""

    def test_every_command_that_measures_also_records(self) -> None:
        """Without `-p scripts.check_coverage_ratchet` there is no manifest, so the gate
        refuses — loudly, but on every push. Dropping the flag from one of these three is
        the quiet way to make the ratchet unusable, so all three are pinned."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        measuring = [
            line
            for text in (makefile, workflow)
            for line in text.splitlines()
            if "coverage run -m pytest" in line
        ]
        assert len(measuring) == 3, f"expected the two make targets and CI's step, got {measuring}"
        for line in measuring:
            assert "-p scripts.check_coverage_ratchet" in line, f"records nothing: {line.strip()}"

    def test_nothing_tolerates_the_ratchet_failing(self) -> None:
        """A refusal that CI is configured to ignore is a refusal that means nothing."""
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        # The YAML KEY, not the phrase — this file argues about it in a comment two steps up.
        assert not re.search(r"^\s*continue-on-error\s*:", workflow, re.MULTILINE)
        for line in (makefile + workflow).splitlines():
            if "scripts.check_coverage_ratchet" in line and not line.lstrip().startswith("#"):
                # `-command` and `command || true` are make's two ways to ignore an exit code.
                assert "||" not in line and not line.lstrip().startswith("-")

    def test_the_two_outcomes_are_distinguishable_and_both_red(self) -> None:
        """1 = a verdict about the code. 2 = no verdict at all. Neither is 0, and a
        reader (or a dashboard) can tell "cover the branch" from "fix your run"."""
        assert ratchet.EXIT_FAIL == 1
        assert ratchet.EXIT_REFUSED == 2


class TestReportParsing:
    """`measure()` against coverage.py's REAL output — and against nobody else's file.

    WHY A REAL ARTEFACT. The JSON shape `measure()` reads is coverage.py's
    (`meta.branch_coverage`, `files.<name>.summary.num_partial_branches`), and a
    hand-written fixture of that shape can drift from what `coverage` actually writes
    while every test here stays green. So these read a data file a genuine `coverage run`
    produced, with this repo's own `[tool.coverage.*]` config applied.

    WHY NOT THE TREE'S OWN `.coverage`, WHICH IS WHAT THIS USED TO READ. That path is
    mutable, well known, and owned by nobody: any partial `coverage run` replaces it, and
    a partial one carries no `apps/voice-runtime/*.py` at all — coverage's source walk
    skips directories without `__init__.py` and D-18 makes that directory hyphenated — so
    `voice-runtime-ack` matches nothing and this test failed on work it knew nothing
    about. It happened TWICE in one session (a 17-file run, then a single-test-file run),
    each time costing a full gate cycle and reading like a real regression in a hard-rule
    surface. The property worth keeping was "real coverage output"; the coupling to a path
    this test does not own was never part of it, and `real_run` already gives the first
    without the second — at no extra cost, since it is module-scoped and built anyway.

    The gate itself still reads that path, and is right to: it is scoring a RUN, and
    `unvouched_run()` makes it refuse one it cannot pair with a manifest. A TEST has no
    such evidence available — inside the suite the newest manifest describes the PREVIOUS
    run — which is the second reason the answer here is "bring your own measurement"
    rather than "learn to recognise a whole-suite `.coverage`".
    """

    def _assert_it_parses(self, report: dict[str, Any]) -> None:
        """The wiring claim, in one place so both callers below make the same one."""
        assert report["meta"]["branch_coverage"] is True, "pyproject sets branch = true"
        rows = ratchet.measure(report)
        assert {row.area for row in rows} == {area.name for area in ratchet.AREAS}
        assert all(row.files for row in rows), "every area must match measured files"

    def test_reads_real_coverage_output(self, real_run: _RealRun) -> None:
        """No skip, deliberately: this now runs on a fresh CI checkout too, where the old
        version skipped and therefore proved nothing exactly where nothing else did."""
        self._assert_it_parses(ratchet.load_report(real_run.data))

    def test_a_partial_coverage_at_the_repo_root_cannot_fail_it(
        self, real_run: _RealRun, partial_coverage_at_the_repo_root: Path
    ) -> None:
        """THE control for the fragility above: the poison is present and irrelevant.

        The fixture has already proved the planted file IS poisonous (an area matching no
        file), so this failing would mean the parser test had been re-coupled to the
        well-known path — by a `load_report()` with no argument, or by one naming
        `DATA_FILE` explicitly. Both are caught here; the first is also unrepresentable,
        which the structural test below pins.
        """
        assert partial_coverage_at_the_repo_root == ratchet.DATA_FILE, "planted off-target"
        self._assert_it_parses(ratchet.load_report(real_run.data))

    def test_no_reader_defaults_to_the_repo_root_data_file(self) -> None:
        """The structural half. `.coverage` is where `coverage run` writes, not a default
        any helper may quietly adopt: WHICH run is scored is one decision and it is
        `main()`'s argparse default. A reader that re-grows a `data_file=None` default
        re-grows the coupling for every future caller, silently."""
        for reader in (
            ratchet.load_report,
            ratchet.manifest_path,
            ratchet.unvouched_run,
            ratchet.blind_spots,
        ):
            parameter = inspect.signature(reader).parameters["data_file"]
            assert parameter.default is inspect.Parameter.empty, (
                f"{reader.__name__} defaults its data file to {parameter.default} — a "
                "reader that falls back to the repo-root `.coverage` scores whatever "
                "partial run last touched it"
            )
