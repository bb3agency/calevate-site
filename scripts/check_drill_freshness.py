"""Guardrail (D-166): the restore drill's evidence EXPIRES, and this refuses stale proof.

OPERATIONS §6 puts the restore drill on the quarterly calendar and §8 makes it a
pre-launch gate: *"**Backups verified** = `runbooks/backup-restore-drill.md` has PASSED
once, with the record committed to `docs/evidence/`."* Nothing read those records. A drill
run in Q1 and never repeated leaves a document that still says PASS in Q4, and a document
that says PASS is exactly as reassuring on the day it stops being true as on the day it
was written. Evidence of a recovery is a MEASUREMENT WITH A DATE ON IT, and this is the
thing that reads the date.

THE PROPERTY THAT MATTERS MORE THAN THE EXPIRY: THIS FILE CANNOT WRITE
---------------------------------------------------------------------
The reference implementation this idea came from has the check and does not have the
property. `dr-stale-drill-check.js` demands a "production-like" drill artifact; that
artifact is produced by `dr-ephemeral-pack.js:35-45`, which writes `status: 'ok'` into a
JSON file and touches no database; and their CI runs the generator and the validator back
to back in one job. The gate is structurally incapable of failing, and every green run is
a fresh green run — which is worse than having no gate, because the artifact accumulates
as a record that a drill happened.

So this file is built so that the same shortcut cannot be taken here, and the guarantee is
STRUCTURAL rather than a promise in a comment:

1. **It may import nothing that can write.** `ALLOWED_IMPORTS` is the whole permitted set,
   and `os`, `shutil`, `subprocess`, `tempfile` and `scripts.restore_drill` are all
   outside it. With those unavailable the only remaining writers are `open()` and the
   mutating `pathlib` methods, which is what rule 2 removes.
2. **It may not call a writer.** `FORBIDDEN_CALLS` names them, and `check_this_module_
   cannot_write` walks THIS FILE'S OWN AST on every run and fails the guardrail if one
   appears. Deleting that self-audit is a visible diff in a guardrail, and
   `tests/drill_freshness_guard_test.py` re-derives the same property independently, so
   removing the audit does not remove the proof.
3. **It reads the quarter off the FILENAME, never the mtime.** `dr-stale-drill-check.js`
   sorts by `fs.statSync(...).mtimeMs`, and an mtime is refreshed by `touch`, by a
   checkout, by a reformat, and by any generator that rewrites the file. A quarter written
   into a name cannot be renewed except by writing a new record for a new quarter — which
   is the drill.

The producer is `scripts/restore_drill.py` plus a human working through
`runbooks/backup-restore-drill.md`, and it stays a different program. There is no flag
here that runs it, no import that reaches it, and nothing here would be improved by one.

WHAT COUNTS AS EVIDENCE, AND WHAT LOOKS LIKE IT
-----------------------------------------------
`docs/evidence/` holds two kinds of file whose names both begin `restore-drill-`:

* `restore-drill-<YYYY>-Q<N>.md` — the QUARTERLY record (runbook §9). Real infrastructure,
  a real restore, a human's verdict. **This is the only thing that resets the clock.**
* `restore-drill-local-<stamp>.md` — written by `make restore-drill` on a laptop against
  MinIO and a scratch database. Its own verdict vocabulary is `GREEN (local scope)`
  precisely so it can never be read as the runbook's PASS, and §0a says in as many words
  that a green run there does NOT tick OPERATIONS §8.

That distinction is the second half of rule 3 above. The local harness IS a generator and
it writes into this very directory, so a check that took the newest `restore-drill-*.md`
by date would be refreshed by `make restore-drill` — the reference's defect, arrived at by
a different road. Local records are counted here and named, and they are never evidence.

THE THREE STATES
----------------
* **NOT RUN** — no quarterly record exists. Nothing has expired, because nothing was ever
  claimed: OPERATIONS §8's "backups verified" is untick and every document in this repo
  says so. Exit 0, and the sentence is printed on every run rather than kept quiet.
* **OK** — the newest record names this quarter or the one before it, and its verdict is
  one a restore can be argued from.
* **FAIL** — a whole quarter was skipped, the newest record is post-dated, its verdict is
  FAIL or missing, or the runbook template was committed with the verdict line unfilled.

Run: `uv run python -m scripts.check_drill_freshness`   (also in `make guardrails`)
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: The same directory `scripts/restore_drill.py` writes its local records into, and the
#: one OPERATIONS §6 and runbook §9 both name. Read-only from here, always.
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"

#: Runbook §9's filename: `docs/evidence/restore-drill-<YYYY>-Q<N>.md`.
QUARTERLY_RECORD = re.compile(r"^restore-drill-(?P<year>\d{4})-Q(?P<quarter>[1-4])\.md$")
#: `scripts/restore_drill.write_record`'s filename. Counted, never evidence.
LOCAL_RECORD = re.compile(r"^restore-drill-local-")
#: Anything else beginning `restore-drill-` is a record nobody can classify — most likely
#: a quarterly record that was misnamed, which is a drill that silently does not count.
ANY_RECORD = re.compile(r"^restore-drill-.*\.md$")

#: Runbook §9's `## Result` line: `**PASS | PARTIAL | FAIL** — <one sentence>`.
VERDICT_LINE = re.compile(r"^\*\*(?P<verdict>[A-Z |]+)\*\*", re.MULTILINE)
#: Verdicts a restore can be argued from. A PARTIAL with a named follow-up is a good drill
#: (runbook §9's own words); a FAIL is a drill that proved the opposite of the claim, so it
#: does not reset a clock that measures how long ago recovery last worked.
ACCEPTED_VERDICTS = frozenset({"PASS", "PARTIAL"})

#: How many quarters a record may be behind the current one before it stops being
#: evidence. 1, because the calendar is quarterly (OPERATIONS §6): a Q1 record is the
#: current proof through Q2, and by Q3 an entire quarter's drill was skipped.
MAX_QUARTERS_BEHIND = 1

# --- the anti-generator audit ---------------------------------------------------
#
# Everything this module is allowed to reach. Nothing here can create a file, and the
# absence of `os`, `shutil`, `subprocess`, `tempfile` and `scripts.restore_drill` is the
# point rather than an accident of what happened to be needed.
ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {"__future__", "argparse", "ast", "dataclasses", "datetime", "pathlib", "re", "sys"}
)

#: Callables that create, refresh or destroy a file. `replace` is on the list because
#: `Path.replace` is a rename; that also rules out `str.replace` in this module, and the
#: ambiguity is resolved in favour of the stronger property on purpose — a guardrail whose
#: no-write proof depends on knowing the type of a receiver is not a proof.
FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {
        "open",
        "write",
        "writelines",
        "write_text",
        "write_bytes",
        "touch",
        "mkdir",
        "makedirs",
        "unlink",
        "remove",
        "rmdir",
        "rmtree",
        "rename",
        "replace",
        "utime",
        "chmod",
        "symlink_to",
        "hardlink_to",
        "copy",
        "copyfile",
        "copy2",
        "copytree",
        "move",
        "run",
        "Popen",
        "system",
        "mkstemp",
        "mkdtemp",
        "NamedTemporaryFile",
        "TemporaryDirectory",
    }
)


def check_this_module_cannot_write(source: str | None = None) -> list[str]:
    """D-166's structural half: prove, from the AST, that this file creates nothing.

    Runs as part of `main`, so the property is enforced by the same gate that enforces the
    expiry rather than only by a test somebody can mark xfail.
    """
    text = source if source is not None else Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)
    failures: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            if module.split(".")[0] not in ALLOWED_IMPORTS:
                failures.append(
                    f"line {node.lineno}: imports {module!r}, which is outside "
                    "ALLOWED_IMPORTS. D-166's whole point is that the validator of the "
                    "drill evidence cannot also be its generator, and an import this "
                    "check does not need is a writer it did not need either. If the "
                    "import is genuinely required, the decision to widen the set belongs "
                    "in the decision log, not in this line."
                )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        spelled = (
            function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
        )
        if spelled in FORBIDDEN_CALLS:
            failures.append(
                f"line {node.lineno}: calls {spelled!r}, which can create or refresh a "
                "file. This check must be structurally incapable of producing the "
                "evidence it reads (D-166) — the reference implementation's gate could "
                "not fail because its own CI ran the generator immediately before it."
            )
    return failures


# --- reading the evidence -------------------------------------------------------


@dataclass(frozen=True)
class DrillRecord:
    """One quarterly record, identified by the quarter its NAME claims."""

    name: str
    year: int
    quarter: int
    verdict: str | None
    #: The runbook template's own `**PASS | PARTIAL | FAIL**` line, committed unfilled.
    unfilled: bool

    @property
    def index(self) -> int:
        """A sortable quarter number. Comparing these is the entire freshness rule."""
        return self.year * 4 + (self.quarter - 1)

    @property
    def label(self) -> str:
        return f"{self.year} Q{self.quarter}"


@dataclass(frozen=True)
class Evidence:
    quarterly: tuple[DrillRecord, ...]
    #: Local-harness records. Named so an operator can see that they exist and that they
    #: are not being counted — the trap this check is shaped around.
    local: tuple[str, ...]
    #: `restore-drill-*` files matching neither shape.
    unrecognised: tuple[str, ...]


def _verdict(text: str) -> tuple[str | None, bool]:
    match = VERDICT_LINE.search(text)
    if match is None:
        return None, False
    raw = " ".join(match.group("verdict").split())
    if "|" in raw:
        return None, True  # the template's own line, never filled in
    return raw, False


def read_evidence(directory: Path | None = None) -> Evidence:
    """Everything in `docs/evidence/` whose name begins `restore-drill-`.

    Reads. Only reads. A missing directory is not an error here — it is the NOT RUN state,
    and creating it to make the next run tidier is precisely the move this check forbids
    itself.
    """
    root = directory or EVIDENCE_DIR
    quarterly: list[DrillRecord] = []
    local: list[str] = []
    unrecognised: list[str] = []
    if not root.exists():
        return Evidence((), (), ())
    for path in sorted(root.glob("restore-drill-*")):
        name = path.name
        if LOCAL_RECORD.match(name):
            local.append(name)
            continue
        match = QUARTERLY_RECORD.match(name)
        if match is None:
            if ANY_RECORD.match(name):
                unrecognised.append(name)
            continue
        verdict, unfilled = _verdict(path.read_text(encoding="utf-8", errors="ignore"))
        quarterly.append(
            DrillRecord(
                name=name,
                year=int(match.group("year")),
                quarter=int(match.group("quarter")),
                verdict=verdict,
                unfilled=unfilled,
            )
        )
    return Evidence(tuple(quarterly), tuple(local), tuple(unrecognised))


def current_quarter(now: datetime | None = None) -> tuple[int, int]:
    """Today's quarter, in UTC.

    UTC rather than IST — which the record template dates its drills in — so that a laptop
    and a CI runner reach the same verdict for the same tree. The two differ for five and
    a half hours once a quarter, and nobody schedules a quarterly drill to that precision.
    """
    moment = now or datetime.now(UTC)
    return moment.year, (moment.month - 1) // 3 + 1


def evaluate(evidence: Evidence, now: datetime | None = None) -> list[str]:
    """Failures. An empty list with no quarterly records is NOT RUN, not a pass — `main`
    tells those apart and says which."""
    failures: list[str] = []
    failures += [
        f"docs/evidence/{name} begins `restore-drill-` and matches neither the quarterly "
        "record's name (`restore-drill-<YYYY>-Q<N>.md`, runbook §9) nor the local "
        "harness's. A misnamed quarterly record is a drill that was performed and does "
        "not count — rename it, or move it out of the way."
        for name in evidence.unrecognised
    ]
    if not evidence.quarterly:
        return failures

    year, quarter = current_quarter(now)
    today = year * 4 + (quarter - 1)
    newest = max(evidence.quarterly, key=lambda record: record.index)
    duplicates = [record.name for record in evidence.quarterly if record.index == newest.index]
    if len(duplicates) > 1:
        failures.append(
            f"two records claim {newest.label}: {', '.join(sorted(duplicates))}. One "
            "quarter has one drill; a second file for it means the quarter a reader "
            "believes was covered depends on which file they opened."
        )
    behind = today - newest.index
    if behind < 0:
        failures.append(
            f"the newest restore-drill record is {newest.name}, which claims "
            f"{newest.label} — a quarter that has not happened yet (today is {year} "
            f"Q{quarter}). A post-dated record is the cheapest way to silence this check "
            "and it is evidence of nothing. Correct the filename to the quarter the "
            "drill was actually run in."
        )
    elif behind > MAX_QUARTERS_BEHIND:
        failures.append(
            f"the newest restore-drill record is {newest.name} ({newest.label}) and today "
            f"is {year} Q{quarter} — {behind} quarters, so at least one quarterly drill "
            "was skipped. OPERATIONS §6 puts the drill on the quarterly calendar and §8 "
            "makes a current record the evidence behind 'backups verified'; a record this "
            "old is a claim about infrastructure that has since been rebuilt, migrated "
            "and re-credentialed. Run `runbooks/backup-restore-drill.md` (start with "
            "`make restore-drill`, §0a) and commit the record."
        )
    if newest.unfilled:
        failures.append(
            f"{newest.name} still carries the runbook's unfilled verdict line "
            "(`**PASS | PARTIAL | FAIL**`). The template was committed rather than the "
            "result — which reads as a completed drill in every listing of this "
            "directory."
        )
    elif newest.verdict is None:
        failures.append(
            f"{newest.name} has no `**PASS**`/`**PARTIAL**`/`**FAIL**` verdict line under "
            "`## Result`. The verdict is the one line of that document a reader acts on; "
            "without it the record cannot say whether the restore worked."
        )
    elif newest.verdict not in ACCEPTED_VERDICTS:
        failures.append(
            f"{newest.name} records **{newest.verdict}**, so the most recent drill did not "
            "demonstrate a recovery. A failed drill is a finding, not a fresh clock — the "
            "next successful drill is what makes this green, and until then 'backups "
            "verified' (OPERATIONS §8) is not tickable."
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_drill_freshness",
        description=(
            "Refuse restore-drill evidence older than one quarter. Reads only: this "
            "check can neither run a drill nor write a record (D-166)."
        ),
    )
    parser.add_argument(
        "--evidence-dir",
        default=str(EVIDENCE_DIR),
        help="directory of committed drill records (read-only)",
    )
    arguments = parser.parse_args(argv)

    failures = check_this_module_cannot_write()
    if failures:
        print("DRILL FRESHNESS: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    evidence = read_evidence(Path(arguments.evidence_dir))
    failures = evaluate(evidence)
    local_note = (
        f"{len(evidence.local)} local-harness record(s) present and deliberately not "
        "counted (`make restore-drill` writes them; runbook §0a)"
    )
    if failures:
        print("DRILL FRESHNESS: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(f"  ({local_note})")
        return 1
    if not evidence.quarterly:
        year, quarter = current_quarter()
        print(
            "DRILL FRESHNESS: NOT RUN — no quarterly restore-drill record exists in "
            f"{arguments.evidence_dir}, so there is nothing to expire. This is not a "
            "pass: OPERATIONS §8's 'backups verified' gate is untick, the §5 RPO is a "
            "design intent rather than a measurement, and this line is printed on every "
            f"run so that stays said out loud. First record due: {year} Q{quarter} "
            "(`runbooks/backup-restore-drill.md`)."
        )
        print(f"  ({local_note})")
        return 0
    newest = max(evidence.quarterly, key=lambda record: record.index)
    year, quarter = current_quarter()
    print(
        f"DRILL FRESHNESS: OK (newest record {newest.name}, verdict {newest.verdict}, "
        f"{year * 4 + quarter - 1 - newest.index} quarter(s) behind {year} Q{quarter}; "
        f"{local_note})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
