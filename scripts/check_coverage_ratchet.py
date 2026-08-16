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

WHY IT REFUSES TO SCORE A RUN IT CANNOT VOUCH FOR
-------------------------------------------------
An equality gate is only as honest as the run underneath it, and coverage is a property of
the RUN, not of the tree: what the suite executed, and what its STORES held while it
executed, both move the number. This gate failed CI twice — `compliance-gate: budget 70,
but only 68 uncovered`, then `voice-runtime-ack: budget 24, but only 22` — and both times
the number was measured somewhere other than CI, and both times the "fix" was to copy CI's
number into the fixture. That is the failure mode this entire file was written against,
arriving through the one door it had left open: a gate that reports a verdict it has no
standing to reach teaches people to edit the baseline until it goes quiet, and a ratchet
whose baseline is edited is a target.

Diagnosing it properly (2026-08-13, and the diagnosis in those two commits was WRONG, so
the evidence is recorded here rather than the conclusion) turned up three distinct causes,
which is itself the argument for refusing rather than guessing:

1. **Postgres state.** A dev database carrying 31,527 accumulated test organizations sends
   the campaign dispatch tick down a different path from a freshly seeded one.
2. **Redis state**, which nobody had suspected and `make db-reset` does not touch. Any
   read-through cache does it: `core/loadshed.py:get_platform_status` serves the halt
   state from a Redis hash and queries Postgres only on a MISS, so on a laptop whose
   Redis holds 71,984 keys from previous runs the fallback never runs, and on CI's fresh
   container it always does. Units of a hard-rule surface, decided by the age of a cache.
   (The example originally cited here was the audit chain head, which was Redis-cached
   until D-59 moved it into the table. The failure MODE outlived the example — which is
   why this list is about the shape and not about one module.)
3. **Machine speed**, which is NOT detectable from inside the process — see below.

A freshly migrated and seeded database on this machine still measured 70 and 24, i.e. the
numbers the "31k organizations" commit blamed on the database. So the durable answer was
never going to be a better remembered rule about running `make db-reset` first; it is a
check that refuses to score what it cannot vouch for, and says which of these it is.

So there is a THIRD OUTCOME. `check_wiring` refuses when its scan matches nothing rather
than printing OK over an empty search; `blind_spots()` below already refused a measurement
older than the code it judges, "it cannot judge code it never ran". By exactly that
argument, a check that cannot see its subject must not print FAIL either. `unvouched_run()`
extends the doctrine to the run itself: the suite records what it did in a manifest beside
`.coverage` (`.coverage-run.json`, written by the pytest plugin at the bottom of THIS
file), and a measurement the manifest cannot vouch for is REFUSED — loud, named, and
neither "regression" nor "improvement".

WHAT IT CAN SEE, ON EVIDENCE — never on a flag somebody remembers to pass:

* **the suite did not pass** — any failure, error, collection error or non-zero exit.
  Coverage from a broken run measures the branches the failures never reached;
* **the suite was FILTERED** — `-k`, `-m`, `--last-failed`, explicit path arguments, or
  any deselection at all. A subset measures less code, and every unrun branch of it reads
  as new uncovered code;
* **a whole module was skipped at collection** (an `importorskip`, a module-level skip):
  a file's worth of branches gone, which is a blackout, not a regression;
* **a SERVICE the suite needs was down when it started** — Postgres or Redis, probed at
  `pytest_sessionstart` rather than inferred from the wreckage afterwards, because "91
  tests skipped" is a symptom and "nothing was listening on the Redis URL" is a sentence
  the reader can act on;
* **a store was not in the state a fresh run starts from** — tenant-scoped tables (off the
  live `TENANT_TABLES` registry, so it grows with the schema) already holding rows, or a
  Redis database already holding keys, before the first test ran. Both are checkable with
  no stored expectation and no threshold, which is the whole reason this shape was chosen:
  CI migrates and seeds a new database and boots a new Redis container, and
  `scripts/seed.py` writes exactly one GLOBAL table, so "empty before the first test" is a
  PROPERTY of the sequence rather than a number somebody has to remember — and a
  remembered number is precisely the thing that goes stale and gets edited;
* **the manifest and the `.coverage` are not from one run**, or that run was not under
  coverage at all — i.e. an orphaned data file left by some earlier invocation.

WHAT IT CANNOT SEE, SAID PLAINLY:

* **a branch whose execution depends on how FAST the machine is.** NOTHING in this process
  can distinguish one from a real change: there is no honest in-process signal for "the
  runner was slower today", and a duration compared against a remembered duration would cry
  wolf between any two machines. The instance this repo actually had is worth keeping,
  because of what it cost. `apps/voice-runtime/webhook_routes.py:182` raises
  `webhook_ack_slow` only when an ack exceeds the 500ms budget of hard rule 3 — never on an
  idle laptop, sometimes on a contended CI runner. That line plus the partial branch above
  it is 2 units, and since this gate is an EQUALITY it went red in BOTH directions across
  nine consecutive commits: first as an improvement nobody had locked in (a busy runner
  measured 22 against a budget of 24), then, once 22 was written into the baseline, eight
  times as a regression nobody had introduced (every runner since measured 24). Two
  sessions read that as a coverage change and edited the number — which is the failure mode
  this whole file exists to prevent, arriving through the one hole it could not see.
  **It is fixed in the CODE, where it belonged**: `test_breaching_the_budget_raises_the_
  incident_signal_and_still_acks` drives the slow path by lowering the THRESHOLD rather
  than faking the clock, so the branch is covered identically on every machine and both
  numbers are 22 by construction. There is now no known speed-dependent branch and no
  CI-is-the-authority carve-out; if a future one appears, the fix is another such test, not
  another edited number.
* a skip whose cause is not one of the probed services — an optional dependency, a
  platform guard, a fixture that gave up. Those change the number and, from inside this
  process, look exactly like a real change. The counts and the commonest reasons are
  recorded in the manifest and printed with every verdict so the divergence is at least
  VISIBLE; they are not gated on, because skip counts legitimately differ between a laptop
  and CI (a `@pytest.mark.skipif` on a service, a fixture that gave up), and a rule that
  fires on that would cry wolf on every push — which is how a guardrail gets ignored.
  (The example that used to stand here was this gate's OWN parser test skipping when no
  previous run had left a `.coverage`. It does not skip any more: it builds its own
  measurement, for the reason `DATA_FILE`'s comment gives.)
* a store that is empty but differs in some other way — a different migration head, a
  hand-edited global row. `alembic upgrade head` owns migration state and CI runs it
  immediately before the suite.
* a hand-written manifest. This is evidence, not proof: it defends against the accident
  that actually happens, not against an author determined to lie to their own gate — and
  such a lie is a visible diff, which the wrong number in the baseline never was.

Because of the first bullet, a FAILING (not refused) verdict now prints the uncovered
lines of the offending area. "compliance-gate: 70 vs 68" is unactionable; the same message
naming `webhook_routes.py:182` tells the reader in one glance whether they are looking at
their own diff or at a machine that ran the ack faster than CI's.

AND IT IS NOT A WAY TO SKIP THE GATE. A refusal exits 2 where a verdict-shaped failure
exits 1; both are non-zero, neither is tolerated anywhere (no `continue-on-error`, no
`|| true` — `tests/coverage_ratchet_guard_test.py` asserts that of the workflow and the
Makefile), and `--update-baseline` runs the same trust check BEFORE it writes. That last
half is the one that matters: the baseline file is where a wrong number ENTERS the repo,
and once in, it is what everybody else's PR is measured against.

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
* **It does not judge the RUN by its number.** Coverage is a property of the run, so a
  `pytest -k something` followed by this check would report a catastrophe, and a run
  against somebody's lived-in database reports a two-unit fiction in whichever direction
  the day's data pushes it. Neither is scored: `blind_spots()` refuses a measurement that
  is stale, line-only, or shows an entire area blacked out, and `unvouched_run()` refuses
  one whose own suite says it was partial, failing, unserviced or run against a database
  that was not fresh. See the section above for what that can and cannot see.

Run: `uv run python -m scripts.check_coverage_ratchet`   (see `make coverage-ratchet`)
     Exit 0 = at the floor. 1 = a verdict, and the verdict is bad. 2 = REFUSED to score.

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
* **`--junit-xml` / `pytest-reportlog`** — the two standard ways to get a machine-readable
  record of a pytest run, considered for the manifest and NOT adopted. Both report
  outcomes well and neither carries the two facts that actually broke this gate: JUnit's
  schema has no place for DESELECTION (a `-k` run and a whole run are the same document,
  only shorter), and nothing generic can know what the database held before the first
  test. A plugin in this file records outcomes, selection, service reachability and the
  pre-suite database state in one artefact, adds no dependency, and — the reason it is in
  THIS file rather than its own — keeps the writer of the schema next to its only reader,
  where they cannot drift into vouching for nothing.
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
import os
import sys
import tempfile
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "tests" / "fixtures" / "coverage_baseline.json"

#: Where `coverage run` writes by default, and therefore what this gate scores when the
#: CLI is given no `--data-file`. IT IS A DEFAULT, NOT A DESTINATION, and the difference
#: is enforced below: every READER in this module (`load_report`, `manifest_path`,
#: `unvouched_run`, `blind_spots`) takes the path as a REQUIRED argument, so this name is
#: reachable from exactly two places — `main()`'s argparse default, which is the one
#: decision about which run is being scored, and the plugin's fallback when coverage was
#: not tracing at all (`pytest_sessionfinish`, which must invalidate a stale file rather
#: than let it inherit credibility).
#:
#: WHY IT IS NOT A DEFAULT ARGUMENT ANY MORE. `.coverage` is a mutable file at a
#: well-known path that nothing here owns: any partial `coverage run` — an agent
#: measuring its own module, a developer measuring one file — overwrites it, and a
#: partial one has no `apps/voice-runtime/*.py` in it at all (coverage's source walk
#: skips directories with no `__init__.py`, and D-18 makes that directory hyphenated).
#: A helper that quietly read this path turned any such leftover into a failure of
#: whatever test called it, twice in one session, each time costing a full gate cycle and
#: reading exactly like a real regression. A caller that wants THIS file now has to say
#: so, which is the whole fix: the coupling is visible in the call rather than in a
#: default nobody sees.
DATA_FILE = REPO_ROOT / ".coverage"

#: 1 = the ratchet reached a verdict and the verdict is bad. 2 = it declined to reach one.
#: Both are non-zero, deliberately: a run this check cannot vouch for is not a pass. The
#: distinction is for the READER, because "cover the branch" and "fix your measurement"
#: are different jobs and the second one has no business being reported as the first.
EXIT_FAIL = 1
EXIT_REFUSED = 2

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
    Area(
        name="platform-credentials",
        rule="hard rules 4 and 6 (append-only `platform_secrets`, no secret in a log)",
        why=(
            "the envelope, the resolution order and the console's write paths. It is its "
            "own area rather than a few files bolted onto `ledgers-and-money`, because "
            "the failures are not that area's failures: a wrapped DEK that cannot be "
            "unwrapped is unrecoverable data loss, `env` losing to the store would let a "
            "database row override a credential the operator pinned, and a plaintext "
            "reaching a response body or a log line is the one defect this whole console "
            "was designed to be incapable of. Every one of those lives in a branch that "
            "only fires on the malformed, the rotated or the misconfigured — never on "
            "the path a demo walks"
        ),
        patterns=(
            "apps/api/core/envelope.py",
            "apps/api/core/platform_config.py",
            "apps/api/ops/models.py",
            "apps/api/ops/config_routes.py",
            "apps/api/ops/secret_routes.py",
            "apps/api/ops/secret_service.py",
            "apps/api/ops/secret_probes.py",
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


def load_report(data_file: Path) -> dict[str, Any]:
    """The coverage JSON report for the run recorded in `data_file`.

    Generated here rather than shelled out to `coverage json` so the check reads the same
    data file the suite wrote, with this repo's `[tool.coverage.*]` config applied, and so
    a missing measurement is one clear error instead of a subprocess exit code.

    The path is REQUIRED — see `DATA_FILE`. Which run is being scored is a decision, and
    it is made once, in `main()`.
    """
    import coverage

    path = data_file
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


# --- 1. is this a RUN the check can vouch for? --------------------------------
#
# Reader half. The writer — the pytest plugin that produces the manifest — is at the
# bottom of this same file, on purpose: a schema whose writer and reader live in two
# files drifts, and the first symptom of that drift is a gate that vouches for nothing
# while printing OK.


#: Bumped whenever the manifest's shape changes. A manifest from another version is
#: refused rather than read leniently: a field this code expects and does not find is a
#: fact it did not check, and an unchecked fact inside a trust check is the hole itself.
MANIFEST_SCHEMA = 1

#: `coverage run -m pytest` writes `.coverage` when the PROCESS exits — a moment AFTER
#: pytest's own `sessionfinish`, never before. So the data file may be somewhat newer than
#: the manifest (interpreter shutdown, a coarse filesystem clock, a slow `coverage.save()`
#: on a big tree) and may not be meaningfully older: an older data file is an orphan from
#: some earlier run, which this manifest says nothing about.
PAIRING_NEWER_SECONDS = 900.0
PAIRING_OLDER_SECONDS = 5.0

#: How many skip reasons the manifest keeps. Enough to name the cause of a mass skip in
#: the summary; not so many that the artefact becomes a transcript.
TOP_SKIP_REASONS = 5


def manifest_path(data_file: Path) -> Path:
    """Where the run that produced `data_file` recorded what it did.

    Derived from the data file rather than fixed at the repo root, so `--data-file`
    points the trust check at the same run it points the measurement at — including in
    the negative controls, which build both in a scratch directory.
    """
    return data_file.with_name(data_file.name + "-run.json")


@dataclass(frozen=True, slots=True)
class RunManifest:
    """What the suite says about itself: the evidence `vouch()` weighs.

    Everything here is recorded by the plugin at the bottom of this file, from pytest's
    own hooks and from two probes taken BEFORE the first test — never from a flag on the
    command line, because a flag records what the runner remembered, not what happened.
    """

    schema: int
    finished_at: float
    coverage_active: bool
    exit_status: int
    passed: int
    failed: int
    errors: int
    skipped: int
    xfailed: int
    collected: int
    collection_errors: int
    collection_skips: int
    deselected: int
    selection: Mapping[str, Any]
    skip_reasons: Mapping[str, int]
    services: Mapping[str, Mapping[str, Any]]
    pre_suite_state: Mapping[str, Mapping[str, Any]]

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> RunManifest:
        """Strictly. A missing key raises, and the caller turns that into a refusal."""
        schema = int(raw["schema"])
        if schema != MANIFEST_SCHEMA:
            raise ValueError(f"schema {schema}, but this check reads {MANIFEST_SCHEMA}")
        outcomes: Mapping[str, Any] = raw["outcomes"]
        return cls(
            schema=schema,
            finished_at=float(raw["finished_at"]),
            coverage_active=bool(raw["coverage_active"]),
            exit_status=int(raw["exit_status"]),
            passed=int(outcomes["passed"]),
            failed=int(outcomes["failed"]),
            errors=int(outcomes["errors"]),
            skipped=int(outcomes["skipped"]),
            xfailed=int(outcomes["xfailed"]),
            collected=int(raw["collected"]),
            collection_errors=int(raw["collection_errors"]),
            collection_skips=int(raw["collection_skips"]),
            deselected=int(raw["deselected"]),
            selection=dict(raw["selection"]),
            skip_reasons=dict(raw["skip_reasons"]),
            services=dict(raw["services"]),
            pre_suite_state=dict(raw["pre_suite_state"]),
        )

    @property
    def shape(self) -> str:
        """One line for humans: what this run actually consisted of."""
        parts = [
            f"{self.collected} collected",
            f"{self.passed} passed",
            f"{self.skipped} skipped",
            f"{self.xfailed} xfailed",
        ]
        if self.skip_reasons:
            top = max(self.skip_reasons.items(), key=lambda item: item[1])
            parts.append(f'commonest skip x{top[1]}: "{top[0]}"')
        return ", ".join(parts)


def _filters(manifest: RunManifest) -> list[str]:
    """Every reason to believe this run was not the whole suite."""
    selection = manifest.selection
    found: list[str] = []
    if selection.get("keyword"):
        found.append(f"-k {selection['keyword']!r}")
    if selection.get("markexpr"):
        found.append(f"-m {selection['markexpr']!r}")
    if selection.get("last_failed"):
        found.append("--last-failed")
    # `testpaths` in pyproject IS the whole suite; anything else on the command line is a
    # subset, even when it looks like a directory that contains everything.
    if selection.get("args_source") != "TESTPATHS":
        found.append(f"explicit path arguments {selection.get('args')}")
    if manifest.deselected:
        found.append(f"{manifest.deselected} test(s) deselected")
    return found


def vouch(manifest: RunManifest, measured_at: float) -> list[str]:
    """Reasons this run cannot stand behind the number measured from it.

    Pure — `measured_at` is the data file's mtime — so the negative controls can hand it
    a doctored run without a filesystem, and so every rule here is one `if` a reader can
    check against the docstring's list.
    """
    failures: list[str] = []

    if not manifest.coverage_active:
        failures.append(
            "the suite run recorded beside this measurement was NOT instrumented, so the "
            "measurement came from some other run. `make coverage-ratchet` measures and "
            "records in ONE process (`coverage run -m pytest -p scripts."
            "check_coverage_ratchet`), which is the only pairing this check accepts."
        )

    drift = measured_at - manifest.finished_at
    if not -PAIRING_OLDER_SECONDS <= drift <= PAIRING_NEWER_SECONDS:
        failures.append(
            f"the manifest and the measurement are not from one run: the data file was "
            f"written {abs(drift):.0f}s {'after' if drift > 0 else 'BEFORE'} the suite "
            "finished. Whatever produced that data file, this run cannot vouch for it — "
            "re-run `make coverage-ratchet`."
        )

    if manifest.exit_status or manifest.failed or manifest.errors or manifest.collection_errors:
        failures.append(
            f"the suite that produced this measurement did not pass: exit {manifest.exit_status}, "
            f"{manifest.failed} failed, {manifest.errors} errored, "
            f"{manifest.collection_errors} collection error(s). Coverage from a broken run "
            "measures the branches the failures never reached; fix the suite, then measure."
        )

    filters = _filters(manifest)
    if filters:
        failures.append(
            f"the suite was FILTERED ({'; '.join(filters)}) — a subset measures less code, "
            "and every branch it did not run reads here as new uncovered code. Budgets are "
            "a property of the WHOLE suite: re-run `make coverage-ratchet`, which runs it."
        )

    if manifest.collection_skips:
        failures.append(
            f"{manifest.collection_skips} module(s) were skipped at COLLECTION — a whole "
            "file's worth of branches is missing from this measurement, not untested. "
            "That is a blackout, not a regression, and this check will not score it."
        )

    for name, service in sorted(manifest.services.items()):
        if not service.get("reachable"):
            failures.append(
                f"{name} was NOT reachable when this suite started "
                f"({service.get('env')}={service.get('url') or 'unset'}: "
                f"{service.get('detail')}). Every test that needs it skipped or errored, so "
                "its branches are missing from this measurement rather than untested. "
                "`make up` starts the local services; then re-run."
            )
            continue
        failures += _stale_state(name, manifest.pre_suite_state.get(name, {}))
    return failures


def _stale_state(name: str, state: Mapping[str, Any]) -> list[str]:
    """Was this store EMPTY before the first test, the way CI's containers always are?

    Both stores get the same rule for the same reason, and the rule needs no stored
    expectation: CI migrates and seeds a new database and boots a new Redis container, so
    "nothing left over" is a property of the sequence rather than a number somebody has to
    remember. `scripts/seed.py` writes exactly one GLOBAL table, so a seeded database is
    genuinely empty of tenant rows; a Redis container that has never served a suite is
    genuinely empty of keys.
    """
    if not state.get("probed"):
        return [
            f"the state of {name} before the first test could not be read "
            f"({state.get('detail')}). What these stores HOLD decides which branches "
            "execute, so a measurement whose starting state is unknown is not scoreable."
        ]
    if not state.get("held"):
        return []
    # `summary` and `why` come from the probe, because what a leftover row MEANS is
    # specific to the store: the reader is owed the sentence that names the branch, not a
    # generic one covering both.
    return [
        f"{name} was NOT in the state a fresh run starts from: {state.get('summary')}. "
        f"{state.get('why')} — and the budgets in tests/fixtures/coverage_baseline.json "
        f"are measured from EMPTY stores, which is what CI provisions. "
        f"{state.get('remedy')}, then measure again."
    ]


def unvouched_run(data_file: Path) -> list[str]:
    """`vouch()` against the manifest on disk, plus the two ways it can be missing."""
    path = data_file
    where = manifest_path(path)
    if not where.exists():
        return [
            f"there is no run manifest at {where.name} beside this measurement. The only "
            "run this check can vouch for is one that recorded itself, which means the "
            "suite has to be started with `-p scripts.check_coverage_ratchet` — what `make "
            "coverage-ratchet` and CI's test step do. A `.coverage` with nothing beside it "
            "came from an unknown invocation against an unknown database, and this check "
            "will not turn that into a verdict."
        ]
    try:
        manifest = RunManifest.parse(json.loads(where.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [
            f"the run manifest at {where.name} is unreadable ({type(exc).__name__}: {exc}) — "
            "truncated, hand-edited, or written by a different version of this script. "
            "Re-run `make coverage-ratchet`."
        ]
    return vouch(manifest, path.stat().st_mtime if path.exists() else 0.0)


# --- 2. is this measurement worth scoring at all? -----------------------------


def blind_spots(
    report: Mapping[str, Any],
    measurements: Iterable[Measurement],
    data_file: Path,
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
    path = data_file

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


# --- 3. is every hard-rule surface inside some area? --------------------------


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


# --- 4. the ratchet -----------------------------------------------------------


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


#: How much of an area's detail a failure prints. `dial-path` carries 123 units and the
#: reader needs enough to recognise a line, not a transcript of the report.
DETAIL_MARKS = 24


def uncovered_detail(report: Mapping[str, Any], area: Area) -> list[str]:
    """`file: lines, a->b partial branches` for one area — WHERE its units are.

    A count tells you a budget moved; only the lines tell you WHY, and "why" is the
    question a two-unit delta always raises (my diff, or a machine that ran the ack
    faster than CI's?). Printed on a failing verdict, never stored: a stored line list
    would make every refactor a baseline diff, which is the same argument that keeps the
    budgets per-area instead of per-file.
    """
    files: Mapping[str, Any] = report.get("files", {})
    detail: list[str] = []
    for name, entry in sorted(files.items()):
        if not _matches(area, name.replace("\\", "/")):
            continue
        marks = [str(line) for line in entry.get("missing_lines", [])]
        marks += [f"{start}->{end}" for start, end in entry.get("missing_branches", [])]
        excluded = int(entry["summary"].get("excluded_lines", 0))
        if excluded:
            marks.append(f"{excluded} excluded by pragma")
        if marks:
            shown = ", ".join(marks[:DETAIL_MARKS])
            more = f" …+{len(marks) - DETAIL_MARKS}" if len(marks) > DETAIL_MARKS else ""
            detail.append(f"{name}: {shown}{more}")
    return detail


def _run_note(data_file: Path) -> str:
    """What the run behind these numbers consisted of, printed with every verdict.

    The skip count is the one divergence this check records but does not gate on (see the
    module docstring), so it has to be VISIBLE: a reader comparing their two-unit failure
    against CI's run needs to be able to see that theirs skipped ninety more tests.
    """
    try:
        raw = json.loads(manifest_path(data_file).read_text(encoding="utf-8"))
        return f"  run: {RunManifest.parse(raw).shape}"
    except (OSError, ValueError, KeyError, TypeError):  # pragma: no cover - vouched first
        return ""


def _refuse(reasons: Iterable[str]) -> int:
    """The third outcome: no verdict, and not a pass either."""
    print("COVERAGE RATCHET: REFUSED TO SCORE — this measurement is not one it can vouch for")
    for reason in reasons:
        print(f"  - {reason}")
    print(
        f"\nThis is neither a regression nor an improvement, so it is reported as neither. "
        f"It exits {EXIT_REFUSED}: CI stays red, and `--update-baseline` will not write a "
        "baseline from a run in this state. Fix what is named above and measure again — "
        "editing tests/fixtures/coverage_baseline.json to make this quiet is the one "
        "response that makes the next person's PR fail instead."
    )
    return EXIT_REFUSED


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
        return _refuse(
            [
                f"there is no measurement at {args.data_file}. This check scores a RUN, so "
                "it needs one: `make coverage-ratchet` runs the whole suite under "
                "`coverage run` and then scores what it produced."
            ]
        )

    rows = measure(report)
    # Both halves refuse for the same reason in two registers — the RUN cannot be vouched
    # for, or the REPORT cannot be read — so they print under one banner and share the one
    # exit code. Ordered run-first: "redis was down" explains "this area never executed",
    # and a reader who is told the cause does not have to guess it from the symptom.
    refusals = unvouched_run(args.data_file) + blind_spots(report, rows, args.data_file)
    if refusals:
        return _refuse(refusals)

    if args.update_baseline:
        refused = save_baseline(rows)
        print(_summary(rows))
        print(_run_note(args.data_file))
        if refused:
            print("\nREFUSED to raise a budget (a ratchet only turns one way):")
            for failure in refused:
                print(f"  - {failure}")
            return EXIT_FAIL
        # Relative when it is the committed fixture, absolute when a test has pointed it
        # at a scratch directory — a print statement is not worth raising over.
        inside = BASELINE.is_relative_to(REPO_ROOT)
        print(f"\nbaseline written to {BASELINE.relative_to(REPO_ROOT) if inside else BASELINE}")
        return 0

    budgets = load_baseline()
    sections = (
        ("a hard-rule surface no area guards", unguarded_surfaces(None)),
        ("the ratchet", evaluate(rows, budgets)),
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
        for row in rows:
            if budgets.get(row.area, row.uncovered) == row.uncovered:
                continue
            area = next(candidate for candidate in AREAS if candidate.name == row.area)
            print(f"\n  {row.area} — where its {row.uncovered} units are:")
            for line in uncovered_detail(report, area):
                print(f"    {line}")
        print(f"\n{_run_note(args.data_file)}")
        print(
            "\nD-29: coverage ratchets, not targets. The number is a count of UNCOVERED "
            "units per hard-rule surface, and it only goes down. This run WAS vouched for "
            "(whole suite, green, services up, both stores fresh), and no branch guarded "
            "here is known to depend on machine speed any more — so the difference is the "
            "code. If you believe you have found a new speed-dependent branch, the fix is "
            "a test that drives it deterministically (see the one for webhook_ack_slow), "
            "never an edit to the number below."
        )
        return EXIT_FAIL

    print(f"COVERAGE RATCHET: OK ({len(AREAS)} guarded surfaces, all at their floor)")
    print(_summary(rows))
    print(_run_note(args.data_file))
    return 0


# --- the recorder: the writer half of the manifest ----------------------------
#
# A pytest plugin, loaded with `-p scripts.check_coverage_ratchet` by the two commands
# that produce a scorable measurement (`make coverage-ratchet`, `coverage-ratchet-accept`)
# and by CI's test step — `tests/coverage_ratchet_guard_test.py` asserts all three, so the
# gate cannot survive somebody quietly dropping the plugin from one of them.
#
# The hooks below are duck-typed (`Any`) rather than annotated with pytest's classes ON
# PURPOSE: this module also runs as a plain script inside CI, and a top-level `import
# pytest` would make the gate itself depend on the test framework being installed.
#
# Nothing here can influence what the suite measures: it reads pytest's reports, takes two
# read-only probes BEFORE the first test, and writes one JSON file after the last one.


_RECORD: dict[str, Any] = {
    "passed": 0,
    "failed": 0,
    "errors": 0,
    "skipped": 0,
    "xfailed": 0,
    "deselected": 0,
    "collected": 0,
    "collection_errors": 0,
    "collection_skips": 0,
    "skip_reasons": {},
    "services": {},
    "pre_suite_state": {},
}


def _service_url(variable: str) -> str:
    """The URL the SUITE will use, resolved the way the suite resolves it.

    `.env` is read WITHOUT `load_dotenv`: this module is imported into the process that
    is about to run the tests, and a guardrail that mutates the environment of the thing
    it is measuring is no longer measuring it.
    """
    value = os.environ.get(variable)
    if value:
        return value
    from dotenv import dotenv_values

    return str(dotenv_values(REPO_ROOT / ".env").get(variable) or "")


def _safe_url(url: str) -> str:
    """The URL with any `user:password@` removed.

    The manifest is printed verbatim by a refusal, and a refusal is printed into CI logs.
    Hard rule 6 is about PII, but a database password in a build log is the same class of
    mistake, and the host and database name are the whole diagnostic value anyway.
    """
    scheme, separator, rest = url.partition("://")
    if not separator:
        return url
    return f"{scheme}://{rest.rpartition('@')[2]}"


def _probe_postgres() -> tuple[dict[str, Any], dict[str, Any]]:
    """Is the database up, and was it FRESH when the suite started? `(service, state)`.

    Row counts come from `pg_stat_user_tables`, not `count(*)`, for a reason worth
    knowing: every tenant table carries FORCEd RLS keyed on the `app.tenant_id` GUC, so a
    `count(*)` over one — as the app role, as the owner, with no GUC set — returns 0 no
    matter what the table holds. A guardrail that reads 0 from a full table is worse than
    no guardrail. `n_live_tup` is maintained by the stats collector, needs no privilege
    and is not row-filtered; it is an ESTIMATE, which is why the refusal prints `~`. The
    estimate cannot invent rows into an empty table, and "empty" is the only claim this
    check makes on it.
    """
    url = _service_url("DATABASE_URL")
    service: dict[str, Any] = {
        "env": "DATABASE_URL",
        "url": _safe_url(url),
        "reachable": False,
        "detail": "",
    }
    state: dict[str, Any] = {
        "probed": False,
        "why": (
            "What the database HOLDS decides which branches execute — a dispatch tick "
            "over thousands of leftover organizations takes a path it never takes over "
            "none"
        ),
        "remedy": "`make db-reset` (or migrate and seed a new database)",
        "detail": "",
    }
    if not url:
        service["detail"] = "unset in the environment and in .env"
        state["detail"] = "DATABASE_URL is unset"
        return service, state
    try:
        from apps.api.db.registry import TENANT_TABLES
        from sqlalchemy import create_engine, text

        engine = create_engine(url.replace("+asyncpg", "+psycopg"))
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT relname, n_live_tup FROM pg_stat_user_tables "
                        "WHERE schemaname = 'public' AND n_live_tup > 0"
                    )
                ).all()
        finally:
            engine.dispose()
    # Any failure to reach it IS unreachable — the reason is recorded, never swallowed.
    except Exception as exc:
        service["detail"] = f"{type(exc).__name__}: {exc}"
        state["detail"] = f"{type(exc).__name__}: {exc}"
        return service, state

    # `organizations` is the tenant table the registry does not list — its RLS policy
    # matches on `id`, not `tenant_id` (db/registry.py) — and it is the one the dispatch
    # tick's shape depends on, so it is named explicitly rather than assumed.
    tenant_tables = set(TENANT_TABLES) | {"organizations"}
    held = {str(name): int(live) for name, live in rows if str(name) in tenant_tables}
    service["reachable"] = True
    state["probed"] = True
    state["held"] = dict(sorted(held.items(), key=lambda item: -item[1]))
    worst = ", ".join(f"{table} ~{rows}" for table, rows in list(state["held"].items())[:3])
    state["summary"] = (
        f"{len(held)} tenant-scoped table(s) still held rows before the first test "
        f"({worst}{'…' if len(held) > 3 else ''})"
    )
    return service, state


def _probe_redis() -> tuple[dict[str, Any], dict[str, Any]]:
    """Is Redis up, and was it EMPTY when the suite started? `(service, state)`.

    The second half is not decoration, and it is the half that took a measurement to
    find. `core/loadshed.py:get_platform_status` serves the platform halt state from a
    Redis hash and falls back to a Postgres read only on a MISS — so on a laptop whose
    Redis has served fifty previous suites the fallback never executes, while on CI's
    fresh container it always does on the first read. That is units of a hard-rule
    surface moving with nothing but the age of a cache, and no amount of `make db-reset`
    reaches it: Redis outlives the database.

    `DBSIZE` on the URL's own database index, so a developer keeping something else on
    another index is not judged for it.
    """
    url = _service_url("REDIS_URL")
    service: dict[str, Any] = {
        "env": "REDIS_URL",
        "url": _safe_url(url),
        "reachable": False,
        "detail": "",
    }
    state: dict[str, Any] = {
        "probed": False,
        "why": (
            "A warm cache DELETES fallbacks from the measurement: "
            "`core/loadshed.py:get_platform_status` queries Postgres only on a MISS, so "
            "on a Redis that has served earlier suites that query never runs at all"
        ),
        "remedy": "`make down && make up` (or `redis-cli -n <db> flushdb`) empties it",
        "detail": "",
    }
    if not url:
        service["detail"] = "unset in the environment and in .env"
        state["detail"] = "REDIS_URL is unset"
        return service, state
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=2.0, socket_timeout=2.0)
        try:
            client.ping()
            # redis-py's `Redis` class serves both the sync and async clients, so every
            # method is typed `Any | Awaitable[Any]`. This is the sync one.
            keys = int(cast(int, client.dbsize()))
        finally:
            client.close()
    # Any failure to reach it IS unreachable — the reason is recorded, never swallowed.
    except Exception as exc:
        service["detail"] = f"{type(exc).__name__}: {exc}"
        state["detail"] = f"{type(exc).__name__}: {exc}"
        return service, state
    service["reachable"] = True
    state["probed"] = True
    # A COUNT, never the keys themselves: ARQ job keys carry execution ids and tenant
    # slugs, and this artefact is printed into a build log (hard rule 6).
    state["held"] = {"keys": keys} if keys else {}
    state["summary"] = f"{keys} key(s) were already cached before the first test"
    return service, state


def pytest_sessionstart(session: Any) -> None:
    """Both probes, BEFORE the first test — the only moment either fact is observable.

    Afterwards the suite has filled both stores itself, so "were they fresh?" stops being
    answerable, and a service that died mid-run has already done its damage.
    """
    postgres, postgres_state = _probe_postgres()
    redis_service, redis_state = _probe_redis()
    _RECORD["services"] = {"postgres": postgres, "redis": redis_service}
    _RECORD["pre_suite_state"] = {"postgres": postgres_state, "redis": redis_state}


def pytest_deselected(items: list[Any]) -> None:
    _RECORD["deselected"] += len(items)


def pytest_collection_finish(session: Any) -> None:
    _RECORD["collected"] = len(session.items)


def pytest_collectreport(report: Any) -> None:
    """A module that failed or SKIPPED at collection took its whole file with it."""
    if report.failed:
        _RECORD["collection_errors"] += 1
    elif report.skipped:
        _RECORD["collection_skips"] += 1


def pytest_runtest_logreport(report: Any) -> None:
    if report.when == "call":
        if report.passed:
            _RECORD["passed"] += 1
        elif report.failed:
            _RECORD["failed"] += 1
        elif hasattr(report, "wasxfail"):
            _RECORD["xfailed"] += 1
        else:
            _RECORD["skipped"] += 1
            _note_skip(report)
    elif report.failed:  # a setup/teardown error is not a failing test, it is a broken one
        _RECORD["errors"] += 1
    elif report.skipped and report.when == "setup":
        _RECORD["skipped"] += 1
        _note_skip(report)


def _note_skip(report: Any) -> None:
    """Keep WHY, not just how many: "redis" in the reason is the actionable half."""
    longrepr = getattr(report, "longrepr", None)
    reason = str(longrepr[2]) if isinstance(longrepr, tuple) and len(longrepr) == 3 else "unknown"
    reasons: dict[str, int] = _RECORD["skip_reasons"]
    reasons[reason[:160]] = reasons.get(reason[:160], 0) + 1


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """Write the manifest beside the data file coverage is actually recording into.

    Beside it, and named after it, so `--data-file` moves both together. When coverage is
    NOT tracing, the manifest still gets written (marked `coverage_active: false`) next to
    the default data file: an uninstrumented run that leaves a stale `.coverage` in place
    must invalidate it, not inherit its credibility.
    """
    import coverage

    current = coverage.Coverage.current()
    data_file = DATA_FILE
    if current is not None:
        configured = getattr(current.config, "data_file", None)
        if configured:
            data_file = Path(str(configured)).resolve()

    option = session.config.option
    skip_reasons: dict[str, int] = _RECORD["skip_reasons"]
    manifest = {
        "_doc": (
            "What the suite that produced the coverage data beside this file actually did. "
            "Written by the pytest plugin in scripts/check_coverage_ratchet.py and read by "
            "the gate in the same file, which REFUSES to score (and refuses to write a "
            "baseline from) a run it cannot vouch for. Not committed; not an input anybody "
            "edits."
        ),
        "schema": MANIFEST_SCHEMA,
        "finished_at": time.time(),
        "coverage_active": current is not None,
        "exit_status": int(exitstatus),
        "collected": _RECORD["collected"],
        "collection_errors": _RECORD["collection_errors"],
        "collection_skips": _RECORD["collection_skips"],
        "deselected": _RECORD["deselected"],
        "outcomes": {
            key: _RECORD[key] for key in ("passed", "failed", "errors", "skipped", "xfailed")
        },
        "selection": {
            "args": list(session.config.args),
            # `Config.args_source` is TESTPATHS only when pytest fell back to pyproject's
            # `testpaths` — i.e. when nobody named a subset on the command line.
            "args_source": str(getattr(session.config, "args_source", "?")).rsplit(".", 1)[-1],
            "keyword": str(getattr(option, "keyword", "") or ""),
            "markexpr": str(getattr(option, "markexpr", "") or ""),
            "last_failed": bool(getattr(option, "lf", False)),
        },
        "skip_reasons": dict(
            sorted(skip_reasons.items(), key=lambda item: -item[1])[:TOP_SKIP_REASONS]
        ),
        "services": _RECORD["services"],
        "pre_suite_state": _RECORD["pre_suite_state"],
    }
    manifest_path(data_file).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
