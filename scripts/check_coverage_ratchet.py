"""Guardrail: the coverage RATCHET (D-29 `coverage:ratchet`, BACKEND-PATTERNS §9).

D-29's own words are "coverage ratchets not targets", and BACKEND-PATTERNS §9 says where:
"Coverage ratchet scoped to the HIGH-RISK surfaces (tenancy, billing, compliance,
pipeline) rather than a repo-wide number." This file is both of those sentences made
executable, and every design choice below follows from them.

WHY NOT A PERCENTAGE, AND WHY NOT ONE NUMBER FOR THE REPO
---------------------------------------------------------
1. **The unit is UNCOVERED CODE, not a ratio.** "The number of bugs is not a function of
   the *percentage* of uncovered code, but rather the *amount* of uncovered code…
   Saying I've got 98% coverage might impress my friends, but if that means I've got
   20kLoC of untested code then it's somewhat meaningless" (jml, coveragepy issue #815 —
   github.com/nedbat/coveragepy/issues/815). A percentage also moves for reasons that
   have nothing to do with tests: delete a well-covered helper and the percentage falls;
   add 400 covered lines beside an untested branch and it rises. A COUNT of uncovered
   units moves one-for-one with the thing we actually care about, so every new untested
   branch is visible even in a large area.
2. **Per AREA, because these surfaces are not interchangeable.** An untested branch in
   the dispatch gate is a call placed to a DNC number; an untested branch in a serializer
   is a wrong label on a screen. A single repo-wide number lets the first hide behind the
   second — coverage bought cheaply in low-risk code pays for coverage lost in the
   compliance path, and the aggregate never moves. The areas below are the hard-rule
   surfaces (CLAUDE.md rules 1, 3, 4, 5, 6, 7), one budget each, and a budget blown in
   one area cannot be repaid from another.
3. **The list stays honest by DERIVING what must be guarded** (`unguarded_surfaces()`).
   A hand-kept list of important directories is a list that stops being true the week
   somebody adds a module — the failure mode `check_wiring` and `check_docs_drift` were
   written to avoid. So the areas are checked against live facts: the ledger tables in
   `db/registry.py`, the modules that set the tenancy GUC, the modules that declare money
   columns, the dial sites `check_compliance_invariants` finds, the redaction primitives
   resolved by import, and every file in `apps/voice-runtime`. A new hard-rule surface
   outside every area FAILS this check until it is either guarded or argued away.

WHY BRANCH COVERAGE
-------------------
Line coverage is satisfied by executing an `if` once: "to achieve full line coverage, you
only need to run the code with one input, which would execute the if branch and cover all
lines" (about.codecov.io/blog/line-or-branch-coverage-which-type-is-right-for-you/). Every
rule this file guards is a rule about the branch NOT taken — the tenant that does not
match, the consent that is absent, the cap that is exceeded, the ack that arrives twice.
So the measurement runs with `branch = true` (pyproject `[tool.coverage.run]`) and the
unit counted is `missing_lines + num_partial_branches`: statements never executed, plus
decisions where only one direction was. A run recorded WITHOUT branch data is refused
rather than scored — an easier number silently substituted for the one the budgets mean.

HOW THE BUDGET IS SHRINK-ONLY
-----------------------------
`tests/fixtures/coverage_baseline.json` holds one integer per area, and the gate is an
EQUALITY, not a ceiling:

* measured > budget → **regression**. New uncovered code in a hard-rule surface.
* measured < budget → **the ratchet clicks**: fails, and `--update-baseline` writes the
  lower number. This is the half that makes it a ratchet rather than a target, and it is
  the shape issue #815 asks for: "contributors will have to update the number of
  uncovered lines in the build scripts to lock in the newer, lower number". Without it
  the budget silently accumulates headroom, and headroom is exactly where a regression
  hides — the next person can delete a test and stay green.

Because green means budget == measured, a budget that is merely EDITED UPWARD fails on
the next run all by itself. Raising one is possible, and it is deliberately expensive:
`--update-baseline` refuses to write a number bigger than the one it read unless
`RAISED_BUDGETS` in THIS file authorizes it with a reason and a ceiling, `stale_waivers()`
deletes the waiver the moment the area improves past it, and
`tests/coverage_ratchet_guard_test.py` pins the waiver set so the diff shows up in a test
too (the same doctrine as `check_redaction_exposure.KNOWN_SAFE_FIELDS` and
`check_rls_coverage`'s exemptions: an exemption must cost an argument, not a keystroke).

WHAT THIS DELIBERATELY DOES NOT DO, AND WHY
-------------------------------------------
* **It does not judge whether a test ASSERTS anything.** No coverage tool can: a test
  that calls a function and asserts nothing covers exactly as much as one that checks the
  answer. That is why this guardrail is never the reason to write a test — the ratchet
  is a floor under suites that already exist, and it NEVER demands a number the tree has
  not already earned (the initial budgets are simply what the suite measures today, so
  its first act rewards nobody). The check that a test is worth having is review, and
  `tests/guardrail_audit_test.py`'s doctrine — mutate the real artefact, assert the guard
  screams — is the standard those tests are held to.
* **No repo-wide floor, and no percentage anywhere in the gate.** Percentages are
  printed for humans only.
* **No per-file budgets.** A budget per file makes every refactor a baseline edit, and
  the ratchet would be re-blessed so often that nobody would read the diff. The area is
  the unit somebody owns.
* **No coverage gate on `apps/web`.** The frontend has its own gate (`make web-check`,
  D-53) and vitest measures a different thing; two ratchets in two languages with one
  baseline file would be a shared number nobody can reason about.
* **Not the engine adapters (hard rule 2).** Their floor is the conformance suite, which
  both adapters must pass — a stronger statement than any line count, and `lint-imports`
  guards the boundary structurally. A coverage budget on top would be a second, weaker
  way to say the same thing (CLAUDE.md: one way per problem).
* **It cannot tell a partial suite run from a regression.** Coverage is a property of the
  RUN, so a `pytest -k something` followed by this check reports a catastrophe. Two
  defences, both loud rather than clever: `make coverage-ratchet` runs the whole suite
  itself, and `blind_spots()` refuses to score a measurement that is older than the code,
  that has no branch data, or that shows an entire area never executed (the shape a
  missing database produces).

Run: `uv run python -m scripts.check_coverage_ratchet`   (see `make coverage-ratchet`)

WHY NOT IN `make guardrails`. Every other guardrail answers a question about the SHAPE of
the tree and needs no suite; this one is a question about a RUN, and the only honest input
is a full instrumented suite. Wiring it into that sweep would score whatever `.coverage`
happened to be lying around. So CI's existing test step runs under `coverage run` — one
suite run, not two, so the gate costs only the instrumentation overhead — and the ratchet
reads what it produced. `make coverage-ratchet` is the same thing locally, and `make
check` calls it INSTEAD OF `make test` for the same one-run reason. `make test` stays
uninstrumented, because the loop a developer runs fifty times a day should not pay for a
gate that only has to be right once per push.

Research note (2026-08, before writing any of this), so the next reader inherits the
evidence rather than the conclusion:

* **`--cov-fail-under` / `[report] fail_under`** (coverage.py's own gate, and what
  pytest-cov exposes). REJECTED as the mechanism, adopted as nothing: it is a percentage
  threshold, i.e. exactly the "target" D-29 rules out, and it ratchets in neither
  direction — a team that dips below edits the number down, which is the failure mode
  this file exists to make expensive. It is also whole-run: no per-area statement is
  expressible.
* **coveragepy issue #815** (github.com/nedbat/coveragepy/issues/815). The absolute
  uncovered-line ratchet, including the "fail when it gets BETTER" half. ADOPTED whole,
  per area instead of per repo. Not implemented upstream, hence this file.
* **`diff-cover` / Codecov "patch" status / "coverage on changed lines"** — the other
  mainstream ratchet (docs.codecov.com/docs/commit-status). Genuinely good, and NOT
  adopted here, for a reason worth knowing: it judges the diff, so it says nothing when a
  change DELETES a test elsewhere, and it needs a base ref plus a coverage service. This
  repo already runs its quality gate as a committed baseline (`scripts/eval.py`,
  `tests/fixtures/eval_baseline.json`), reviewed in the same PR as the code — one way per
  problem, and the way this repo already chose.
* **`pytest-cov`** — the usual pytest plugin. Not adopted: it is a convenience wrapper
  around `coverage run -m pytest`, which is one line in a Makefile, and it would add a
  second dependency (plus its own `--cov*` flag surface) for nothing this needs.
  `coverage` itself has no runtime dependencies on 3.12.
* **`COVERAGE_CORE=sysmon`** — the low-overhead `sys.monitoring` core. Measured and NOT
  usable here: "In Python 3.12 and 3.13, it does not support branch coverage"
  (coveragepy `doc/config.rst`, `[run] core`). This repo is pinned to 3.12
  (`requires-python = ">=3.12,<3.13"`), so the C trace core is what runs; the measured
  cost of that is recorded in ENGINEERING-PRACTICES §2. It becomes a one-line change on
  3.14, where sysmon is the default.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import sys
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "tests" / "fixtures" / "coverage_baseline.json"
DATA_FILE = REPO_ROOT / ".coverage"

#: The minimum argument a raised budget has to make. Length is a crude proxy and it is
#: the same one `check_rls_coverage` uses for RLS exemptions ("too thin"): a reviewer
#: cannot weigh "TODO", and the point of the waiver is that somebody had to write a
#: sentence a reviewer can disagree with.
MIN_REASON_CHARS = 80


@dataclass(frozen=True, slots=True)
class Area:
    """A hard-rule surface with one budget.

    `patterns` are repo-relative globs. They are DIRECTORY-shaped wherever the whole
    package is the surface, so a new file in `apps/api/compliance/` is guarded the day
    it lands rather than the day somebody remembers to list it.
    """

    name: str
    rule: str
    patterns: tuple[str, ...]
    why: str


AREAS: tuple[Area, ...] = (
    Area(
        name="tenancy-session",
        rule="hard rule 1 (tenancy/RLS)",
        patterns=("apps/api/db/*.py", "apps/api/core/context.py"),
        why=(
            "the session factory is where the tenant GUC is set and where RLS therefore "
            "becomes real; every tenant-scoped query in the product is isolated by these "
            "few branches, and the failure they guard is a client reading another "
            "client's leads"
        ),
    ),
    Area(
        name="compliance-gate",
        rule="hard rule 5 (compliance invariants)",
        patterns=("apps/api/compliance/*.py",),
        why=(
            "the campaign-launch and dial-time gates, DNC, consent, KYC, the first-"
            "campaign review and the erasure path. An untested branch here is a TRAI or "
            "DPDP failure, not a wrong screen — and the branch that goes untested is "
            "always the refusal, because the happy path is what the demo exercises"
        ),
    ),
    Area(
        name="dial-path",
        rule="hard rule 5 (no dial skips the gate)",
        patterns=(
            "apps/api/agents/service.py",
            "apps/workers/campaign_dispatch.py",
            "apps/workers/dispatcher.py",
            # The other two dial surfaces, added because the derivation found them: the
            # D-21 single-lead button and callback (crm/routes) and the instant-lead
            # webhook (ingest/service). Neither was in the first draft of this list,
            # which is the argument for deriving it rather than writing it down.
            "apps/api/crm/routes.py",
            "apps/api/ingest/service.py",
        ),
        why=(
            "the chokepoint `dispatch_call` and every surface that reaches it — the two "
            "workers, the D-21 lead button and the instant-lead webhook. "
            "`check_compliance_invariants` proves the gate is ON this path and obeyed; "
            "what it cannot prove is that the obeying branch was ever executed"
        ),
    ),
    Area(
        name="ledgers-and-money",
        rule="hard rules 4 and 7 (append-only ledgers, NUMERIC money)",
        patterns=("apps/api/billing/*.py",),
        why=(
            "metering, credits, caps, rating and invoicing. Money arithmetic fails "
            "quietly — a wrong paise is a wrong invoice that nobody notices until a "
            "client reconciles — and ledger writes are compensating entries whose "
            "error paths are, by construction, the ones no manual test reaches"
        ),
    ),
    Area(
        name="redaction",
        rule="hard rules 5 and 6 (redaction, no PII in logs)",
        patterns=("apps/workers/redaction.py", "apps/api/core/logging.py"),
        why=(
            "the two places that decide whether a phone number leaves the system in "
            "clear text. Small, pure, and the single highest-consequence-per-line code "
            "in the repo: an unexercised branch is a spoken digit run that survives "
            "into `text_redacted` or into a log line"
        ),
    ),
    Area(
        name="voice-runtime-ack",
        rule="hard rule 3 (voice-runtime discipline)",
        patterns=("apps/voice-runtime/*.py",),
        why=(
            "the whole service. It is small on purpose, it is the only externally "
            "reachable unauthenticated surface, and its rules (verify, dedupe, ack "
            "< 500ms, defer everything) live entirely in branches that only fire on the "
            "malformed, replayed or hostile request"
        ),
    ),
)

#: Budgets that were RAISED, with the ceiling authorized and the argument for it. Empty,
#: and the point is that it is expensive to make non-empty: `--update-baseline` refuses
#: to write a bigger number without an entry here, `stale_waivers()` fails once the area
#: improves past the ceiling, and `tests/coverage_ratchet_guard_test.py` pins the set so a
#: new entry costs a diff in a test as well as a diff here. Raising a budget is allowed;
#: it is just never quiet.
RAISED_BUDGETS: dict[str, tuple[int, str]] = {}


# --- the measurement ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Measurement:
    """What one area measured on one run. `uncovered` is the ratcheted number."""

    area: str
    files: int
    statements: int
    executed: int
    missing_lines: int
    partial_branches: int
    branches: int
    excluded: int

    @property
    def uncovered(self) -> int:
        """Statements never run, decisions taken in only one direction, and exclusions.

        Not `missing_branches`: an arc out of a line that never executed is already
        counted by that line, and counting both would weight a dead function by its
        shape. `num_partial_branches` is exactly the increment branch coverage adds over
        line coverage, and it is the column coverage.py itself prints as "BrPart".

        EXCLUDED lines are counted as uncovered, which is not what coverage.py does and
        is the point: `# pragma: no cover` deletes a line from both the numerator and the
        denominator, so inside a guarded surface it is the quietest possible way to lower
        this number — one comment, no baseline diff, no reviewer prompt. Counting it
        keeps the only route downward the one this file is built around: cover the
        branch, or argue the raise in `RAISED_BUDGETS`.
        """
        return self.missing_lines + self.partial_branches + self.excluded

    @property
    def percent(self) -> float:
        """For humans reading the summary line. Never compared against anything."""
        total = self.statements + self.branches
        covered = total - self.uncovered
        return 100.0 * covered / total if total else 100.0


def load_report(data_file: Path | None = None) -> dict[str, Any]:
    """The coverage JSON report for the run recorded in `.coverage`.

    Generated here rather than shelled out to `coverage json` so the check reads the same
    data file the suite wrote, with this repo's `[tool.coverage.*]` config applied, and so
    a missing measurement is one clear error instead of a subprocess exit code.
    """
    import coverage

    path = DATA_FILE if data_file is None else data_file
    if not path.exists():
        raise FileNotFoundError(path)

    cov = coverage.Coverage(data_file=str(path), config_file=str(REPO_ROOT / "pyproject.toml"))
    cov.load()
    with tempfile.TemporaryDirectory() as directory:
        # `json_report` takes a PATH, not a stream (coverage/control.py: "`outfile` is
        # the path to write the file to"), and the report is a build artefact — writing
        # it into a temp directory keeps it out of the tree entirely, so there is no
        # second file anybody could mistake for the baseline.
        out = Path(directory) / "coverage.json"
        cov.json_report(outfile=str(out))
        return dict(json.loads(out.read_text(encoding="utf-8")))


def _matches(area: Area, path: str) -> bool:
    return any(PurePosixPath(path).match(pattern) for pattern in area.patterns)


def measure(report: Mapping[str, Any], areas: Iterable[Area] | None = None) -> list[Measurement]:
    """Fold the per-file report into one row per area."""
    files: Mapping[str, Any] = report.get("files", {})
    rows: list[Measurement] = []
    for area in AREAS if areas is None else areas:
        matched = [
            entry["summary"]
            for name, entry in files.items()
            if _matches(area, name.replace("\\", "/"))
        ]

        def total(key: str, summaries: list[Any] = matched) -> int:
            return sum(int(summary.get(key, 0)) for summary in summaries)

        rows.append(
            Measurement(
                area=area.name,
                files=len(matched),
                statements=total("num_statements"),
                executed=total("covered_lines"),
                missing_lines=total("missing_lines"),
                partial_branches=total("num_partial_branches"),
                branches=total("num_branches"),
                excluded=total("excluded_lines"),
            )
        )
    return rows


# --- 1. is this measurement worth scoring at all? -----------------------------


def blind_spots(
    report: Mapping[str, Any],
    measurements: Iterable[Measurement],
    data_file: Path | None = None,
) -> list[str]:
    """Reasons to refuse to score, loudly, instead of reporting a number.

    A coverage number is a property of a RUN, and four kinds of bad run produce a
    plausible-looking number: one measured without branch data (the easy number), one
    that predates the code it is being compared against, one where an area's patterns
    match nothing at all, and one where whole areas never executed because the suite was
    filtered or the database was down. Every one of those reads as a spectacular
    regression, and a guardrail that cries wolf is a guardrail people learn to
    re-baseline past — so it says which of the four it is and scores nothing.
    """
    failures: list[str] = []
    path = DATA_FILE if data_file is None else data_file

    if not report.get("meta", {}).get("branch_coverage"):
        failures.append(
            "the run was recorded WITHOUT branch coverage — every budget here counts "
            "partial branches, so scoring this would compare two different numbers. "
            "`[tool.coverage.run] branch = true` in pyproject.toml is what sets it."
        )

    measured_at = path.stat().st_mtime if path.exists() else 0.0
    stale = [
        source.relative_to(REPO_ROOT).as_posix()
        for source in _guarded_sources()
        if source.stat().st_mtime > measured_at
    ]
    if stale:
        failures.append(
            f"the measurement is older than {len(stale)} guarded source file(s) "
            f"({', '.join(sorted(stale)[:3])}…) — it cannot judge code it never ran. "
            "Re-run `make coverage-ratchet`."
        )

    for row in measurements:
        if row.files == 0:
            failures.append(
                f"area {row.area!r} matched no file in the report — its patterns name "
                "nothing that exists. A renamed or moved surface must move the area with "
                "it, not silently empty it."
            )
        elif row.executed == 0:
            failures.append(
                f"area {row.area!r} has {row.statements} statements and NONE of them "
                "executed. That is what a filtered suite or a missing database looks "
                "like, not a coverage regression — this check refuses to score it."
            )
    return failures


def _guarded_sources(areas: Iterable[Area] | None = None) -> list[Path]:
    return sorted(
        {
            path
            for area in (AREAS if areas is None else areas)
            for pattern in area.patterns
            for path in REPO_ROOT.glob(pattern)
            if path.is_file()
        }
    )


# --- 2. is every hard-rule surface inside some area? --------------------------


def _python_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" not in path.parts and not path.name.endswith("_test.py"):
            yield path


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _defining_file(target: str) -> Path:
    """Where `module:attribute` is actually defined, resolved by import.

    A live fact, not a remembered path: if `redact` moves house, this follows it and the
    new home has to be guarded. If it is DELETED, the import raises and the check dies
    loudly rather than quietly guarding nothing — the same bargain
    `check_compliance_invariants.gate_registry()` makes.
    """
    module_name, _, attribute = target.partition(":")
    module = importlib.import_module(module_name)
    source = inspect.getsourcefile(getattr(module, attribute))
    if source is None:  # pragma: no cover - a builtin cannot be one of ours
        raise RuntimeError(f"{target} has no source file")
    return Path(source).resolve()


def _ledger_model_files() -> dict[str, str]:
    """Modules declaring an ORM model whose table is append-only (hard rule 4)."""
    from apps.api.db.registry import APPEND_ONLY_TABLES

    found: dict[str, str] = {}
    for root in (REPO_ROOT / "apps", REPO_ROOT / "packages"):
        for path in _python_files(root):
            if path.name != "models.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                names = {t.id for t in node.targets if isinstance(t, ast.Name)}
                if "__tablename__" not in names or not isinstance(node.value, ast.Constant):
                    continue
                if node.value.value in APPEND_ONLY_TABLES:
                    found[_rel(path)] = f"declares the append-only table {node.value.value!r}"
    return found


def _money_files() -> dict[str, str]:
    """Modules declaring NUMERIC columns — where hard rule 7 lives in the schema."""
    found: dict[str, str] = {}
    for root in (REPO_ROOT / "apps", REPO_ROOT / "packages"):
        for path in _python_files(root):
            source = path.read_text(encoding="utf-8")
            if "Numeric(" in source:
                found[_rel(path)] = "declares NUMERIC money columns (hard rule 7)"
    return found


def _tenancy_guc_files() -> dict[str, str]:
    """Modules that SET the tenancy GUC — where hard rule 1 stops being a migration.

    Off the AST, with docstrings excluded, rather than a substring scan of the file. A
    grep for `app.tenant_id` matches four modules whose only mention of it is a comment
    explaining that their session already carries it — prose about the rule, satisfying a
    check about the rule, which is the exact failure `check_docs_drift`'s research note
    and `check_wiring._referenced_names` both call out. What makes a module part of hard
    rule 1's machinery is EXECUTING the GUC, so that is what is looked for.
    """
    from scripts.check_rls_coverage import TENANT_GUC

    found: dict[str, str] = {}
    for path in _python_files(REPO_ROOT / "apps"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and TENANT_GUC in node.value
                and id(node) not in docstrings
            ):
                found[_rel(path)] = f"sets the tenancy GUC {TENANT_GUC!r} (hard rule 1)"
                break
    return found


def required_surfaces() -> dict[str, str]:
    """`{repo-relative file: why it must be guarded}`, derived from live registries.

    This is the answer to "how does the area list stay honest as the tree grows". Every
    entry comes from a fact the repo already maintains for another reason — the ledger
    table list, the model declarations, the dial-site scan, the redaction primitives, the
    hyphenated service directory — so a new hard-rule surface enrolls itself.
    """
    from scripts.check_compliance_invariants import dial_sites

    required: dict[str, str] = {
        _rel(path): "hard rule 3: every line of voice-runtime is the ack path"
        for path in _python_files(REPO_ROOT / "apps" / "voice-runtime")
    }
    required |= _ledger_model_files()
    required |= _money_files()
    required |= _tenancy_guc_files()
    for site in dial_sites():
        required[site.path] = "hard rule 5: calls the dial chokepoint"
    for target, reason in (
        ("apps.workers.redaction:redact", "hard rule 5/6: the redaction primitive"),
        ("apps.api.core.logging:configure_logging", "hard rule 6: the logging redaction hook"),
        ("apps.api.compliance.service:check_dispatch", "hard rule 5: the dial-time gate"),
    ):
        required[_rel(_defining_file(target))] = reason
    return required


def unguarded_surfaces(areas: Iterable[Area] | None = None) -> list[str]:
    """Hard-rule surfaces that no area covers.

    `areas` is injectable for the reason `check_redaction_exposure`'s allowlist is: a
    registry nobody can take away in a test is one nobody can prove still sees anything.
    """
    guarded = {_rel(path) for path in _guarded_sources(areas)}
    return [
        f"{path} — {reason}, and it is in no guarded area. Add it to an existing "
        "`Area` (or add an area with its own budget); a hard-rule surface with no "
        "floor under it is the one that quietly loses its tests."
        for path, reason in sorted(required_surfaces().items())
        if path not in guarded
    ]


# --- 3. the ratchet -----------------------------------------------------------


def load_baseline(path: Path | None = None) -> dict[str, int]:
    file = BASELINE if path is None else path
    if not file.exists():
        return {}
    data = json.loads(file.read_text(encoding="utf-8"))
    return {k: int(v) for k, v in data.get("areas", {}).items()}


def evaluate(measurements: Iterable[Measurement], budgets: Mapping[str, int]) -> list[str]:
    """The gate: measured == budget, in both directions.

    The `<` direction is the ratchet click, and it is the half people leave out. Coverage
    that improved and was not locked in is headroom, and headroom means the next change
    can delete a test and still pass — which is how a ratchet decays into a target.
    """
    failures: list[str] = []
    rows = list(measurements)
    known = {row.area for row in rows}

    for row in rows:
        if row.area not in budgets:
            failures.append(
                f"{row.area}: no budget recorded. It measures {row.uncovered} uncovered "
                "unit(s) today — run `make coverage-ratchet-accept` to record that as "
                "the floor."
            )
            continue
        budget = budgets[row.area]
        if row.uncovered > budget:
            failures.append(
                f"{row.area}: {row.uncovered} uncovered unit(s), budget {budget} "
                f"(+{row.uncovered - budget}). New untested code in a {_rule_of(row.area)} "
                "surface: cover the new branches, or — if it genuinely cannot be covered "
                "yet — raise the budget through RAISED_BUDGETS in "
                "scripts/check_coverage_ratchet.py, which needs a reason a reviewer can "
                "weigh."
            )
        elif row.uncovered < budget:
            # One message for both readings, because from here they are the same fact and
            # only the author knows which it is. Leaving this direction green is what
            # turns a ratchet back into a target: an unclaimed gain is headroom, and
            # headroom is where the next deleted test hides.
            failures.append(
                f"{row.area}: budget {budget}, but only {row.uncovered} uncovered "
                f"unit(s) — the budget is not at the floor ({budget - row.uncovered} "
                "unit(s) of slack). Either coverage IMPROVED and the gain was never "
                "locked in (`make coverage-ratchet-accept`, a one-line diff), or the "
                "budget was EDITED UPWARD, which is the one edit a ratchet does not "
                "accept: a bigger number needs a RAISED_BUDGETS waiver in "
                "scripts/check_coverage_ratchet.py naming what forced it and what "
                "closes it."
            )

    for area in sorted(set(budgets) - known):
        failures.append(
            f"baseline has a budget for {area!r}, which is not an area any more — "
            "remove it. A budget for nothing is a hole the next area can be named into."
        )
    return failures


def _rule_of(name: str) -> str:
    return next((area.rule for area in AREAS if area.name == name), "hard-rule")


def stale_waivers(budgets: Mapping[str, int] | None = None) -> list[str]:
    """A raised budget that is no longer the budget has done its job — delete it.

    Same shape as `check_wiring.stale_baseline()`: a waiver kept past its usefulness is a
    standing permission, and standing permissions are how an exemption list becomes a
    hiding place.
    """
    recorded = load_baseline() if budgets is None else budgets
    names = {area.name for area in AREAS}
    failures: list[str] = []
    for area, (ceiling, reason) in sorted(RAISED_BUDGETS.items()):
        if area not in names:
            failures.append(f"RAISED_BUDGETS entry {area!r} names no area — remove it")
        elif len(reason.strip()) < MIN_REASON_CHARS:
            failures.append(
                f"RAISED_BUDGETS entry {area!r} is too thin to review — say what forced "
                "the raise and what closes it"
            )
        elif recorded.get(area, 0) < ceiling:
            failures.append(
                f"RAISED_BUDGETS entry {area!r} authorized {ceiling} and the budget is "
                f"now {recorded.get(area, 0)} — the raise is spent. Delete the entry so "
                "the next raise has to be argued on its own."
            )
    return failures


def save_baseline(measurements: Iterable[Measurement], path: Path | None = None) -> list[str]:
    """Write the measured numbers as the new floor. Returns the refusals.

    Shrinking is free and silent — that is the ratchet working. GROWING is refused unless
    `RAISED_BUDGETS` authorizes it, because this is the one automated path that could
    move the bar the wrong way, and a tired reviewer skimming a one-line JSON diff is
    exactly who it would move it past. (`scripts/eval.py:save_baseline` makes the same
    refusal for the same reason, about wrong extraction values.)
    """
    file = BASELINE if path is None else path
    current = load_baseline(file)
    rows = list(measurements)
    refused: list[str] = []
    accepted: dict[str, int] = {}

    for row in rows:
        previous = current.get(row.area)
        ceiling, reason = RAISED_BUDGETS.get(row.area, (0, ""))
        # The reason is checked HERE as well as in `stale_waivers()`, so a one-word
        # waiver cannot buy the write and be argued about afterwards.
        authorized = row.uncovered <= ceiling and len(reason.strip()) >= MIN_REASON_CHARS
        if previous is None or row.uncovered <= previous or authorized:
            accepted[row.area] = row.uncovered
            continue
        refused.append(
            f"{row.area}: {row.uncovered} uncovered vs budget {previous}. A budget only "
            "grows through RAISED_BUDGETS in scripts/check_coverage_ratchet.py, with a "
            f"ceiling of at least {row.uncovered} and a reason of at least "
            f"{MIN_REASON_CHARS} characters saying what closes it."
        )
        accepted[row.area] = previous

    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(
            {
                "_doc": (
                    "Uncovered units (statements never executed + branches taken in only "
                    "one direction + lines excluded by a `# pragma: no cover`) per "
                    "hard-rule surface, as measured by the FULL suite "
                    "under `coverage run`. The gate is an EQUALITY: more is a regression, "
                    "less is an improvement that must be locked in here. Written only by "
                    "`make coverage-ratchet-accept`, which refuses to grow a number "
                    "without a RAISED_BUDGETS waiver in scripts/check_coverage_ratchet.py. "
                    "See that file's docstring for why this is a count per area and not a "
                    "repo-wide percentage."
                ),
                "areas": dict(sorted(accepted.items())),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return refused


# --- gate ---------------------------------------------------------------------


def _summary(rows: Iterable[Measurement]) -> str:
    return "\n".join(
        f"  {row.area:<20} {row.uncovered:>5} uncovered  "
        f"({row.statements} stmt, {row.branches} branch, {row.percent:.1f}% covered)"
        for row in rows
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--data-file", type=Path, default=DATA_FILE)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record the measured numbers as the new floor (shrink-only)",
    )
    args = parser.parse_args(argv)

    try:
        report = load_report(args.data_file)
    except FileNotFoundError:
        print(
            f"COVERAGE RATCHET: FAIL — no measurement at {args.data_file}. This check "
            "scores a RUN, so it needs one: `make coverage-ratchet` runs the whole suite "
            "under `coverage run` and then scores it."
        )
        return 1

    rows = measure(report)
    blind = blind_spots(report, rows, args.data_file)
    if blind:
        print("COVERAGE RATCHET: FAIL — this measurement cannot be scored")
        for failure in blind:
            print(f"  - {failure}")
        return 1

    if args.update_baseline:
        refused = save_baseline(rows)
        print(_summary(rows))
        if refused:
            print("\nREFUSED to raise a budget (a ratchet only turns one way):")
            for failure in refused:
                print(f"  - {failure}")
            return 1
        print(f"\nbaseline written to {BASELINE.relative_to(REPO_ROOT)}")
        return 0

    sections = (
        ("a hard-rule surface no area guards", unguarded_surfaces(None)),
        ("the ratchet", evaluate(rows, load_baseline())),
        ("a raised budget that no longer holds", stale_waivers()),
    )
    failed = False
    for title, offenders in sections:
        if offenders:
            failed = True
            print(f"COVERAGE RATCHET: FAIL — {title}")
            for offender in offenders:
                print(f"  - {offender}")
    if failed:
        print(
            "\nD-29: coverage ratchets, not targets. The number is a count of UNCOVERED "
            "units per hard-rule surface, and it only goes down."
        )
        return 1

    print(f"COVERAGE RATCHET: OK ({len(AREAS)} guarded surfaces, all at their floor)")
    print(_summary(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
