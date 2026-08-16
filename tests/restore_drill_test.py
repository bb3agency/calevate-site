"""The pure parts of `scripts/restore_drill.py` — the ones that decide what it may touch.

`scripts/restore_drill.py`'s module docstring has always ended *"tests/restore_drill_test.py
pins the pure parts; the sabotage modes are how the wet parts are proved."* **This file did
not exist.** It was the third thing that harness named and the repository did not have —
alongside `make restore-drill` (no such target) and `runbooks/backup-restore-drill.md` §0a
(no such section), both of which now exist. A committed 1500-line harness reachable from
nothing, citing three artefacts that were not there, is the terraform class of defect: it
looks like coverage on a screen.

WHAT IS PINNED HERE, and why these and not others:

1. **`assert_scratch`** — the guard every destructive statement in that module passes
   through. The drill deliberately UPDATEs and DELETEs append-only ledgers (that is how it
   proves the triggers still raise), so the only thing between it and a real database is a
   name check. That check is worth a negative control per failure mode.
2. **Parity with `dump-offsite.sh`** — the drill reads the production flags out of the
   shell script at drill time rather than hardcoding them, so that a change to production's
   backup invocation cannot leave a drill quietly testing an invocation nobody performs.
   The failure modes (command gone, load-bearing option gone) must raise rather than
   degrade, because both degrade into a green run.
3. **The coverage list** — `NOT_COVERED` is the deliverable that stops a local green run
   being read as a quarterly PASS, so it has to be non-empty, unique, and complete in the
   sense that every id maps to a step of the runbook that does cover it.

The wet parts (dump → age → S3 → restore → verify, and the four `--sabotage` modes) need
Postgres, MinIO and `age`, and they are `make restore-drill`. They are deliberately not
pytest: the suite must not depend on an object store, and a drill is a rehearsal you read
the output of, not an assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from scripts.restore_drill import (
    NOT_COVERED,
    SCRATCH_DB_PATTERN,
    DrillError,
    apply_options,
    assert_scratch,
    production_age_options,
    production_dump_options,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DRILL_RUNBOOK = REPO_ROOT / "runbooks" / "backup-restore-drill.md"

PROTECTED = frozenset({"gate71", "calevate"})


def test_a_scratch_name_of_the_right_shape_is_accepted() -> None:
    assert_scratch("calevate_drill_src_20260816t120000z", PROTECTED)
    assert_scratch("calevate_drill_restore_20260816t120000z", PROTECTED)


@pytest.mark.parametrize(
    "name",
    [
        "gate71",  # a database named in .env
        "calevate",  # ditto
        "postgres",  # right shape for a real database, wrong shape for a scratch one
        "calevate_drill",  # the prefix alone is not the pattern
        "calevate_drill_src_2026",  # truncated stamp
        "calevate_drill_other_20260816t120000z",  # neither src nor restore
        "",
    ],
)
def test_anything_that_is_not_a_scratch_database_is_refused(name: str) -> None:
    """The drill's worst plausible bug is pointing itself at a database that matters.

    Its destructive statements are not incidental — it UPDATEs and DELETEs every ledger in
    `APPEND_ONLY_TABLES` on purpose, to prove the triggers still refuse. So this guard is
    the safety property, and a guard with no negative control is a comment.
    """
    with pytest.raises(DrillError):
        assert_scratch(name, PROTECTED)


def test_the_scratch_pattern_is_anchored_at_both_ends() -> None:
    """`re.match` alone would accept a suffix; a prefix-only pattern would accept
    `calevate_drill_src_20260816t120000z_but_actually_production`."""
    assert SCRATCH_DB_PATTERN.pattern.startswith("^")
    assert SCRATCH_DB_PATTERN.pattern.endswith("$")


def test_the_drill_reads_the_production_dump_flags_rather_than_restating_them() -> None:
    options = production_dump_options()
    assert "--format=custom" in options, (
        "the drill requires the custom format because `pg_restore --table` — the "
        "single-table recovery runbooks/database-restore.md §10 documents — needs it"
    )
    # Host-specific options keep their NAME and lose their value, so the drill can bind
    # its own path while still failing if production stops passing the option at all.
    assert "--file" in options
    assert not any(option.startswith("--file=") for option in options)


def test_the_drill_reads_the_production_age_flags_rather_than_restating_them() -> None:
    options = production_age_options()
    assert "--encrypt" in options
    assert "--recipients-file" in options, (
        "asymmetric encryption is the property: with a passphrase, the host that writes "
        "the backup can also read every backup it ever wrote"
    )


def test_a_missing_production_command_stops_the_drill() -> None:
    """Not 'falls back to a default'. A drill that cannot find the command it is
    mirroring has nothing to claim parity with, and saying so is the whole value."""
    with pytest.raises(DrillError, match="pg_dump"):
        production_dump_options("#!/usr/bin/env bash\necho no dump here\n")
    with pytest.raises(DrillError, match="age"):
        production_age_options("#!/usr/bin/env bash\necho no age here\n")


def test_dropping_a_load_bearing_option_from_production_stops_the_drill() -> None:
    """A plain dump still restores, so nothing else in the system would notice."""
    with pytest.raises(DrillError, match="--format=custom"):
        production_dump_options('pg_dump --file="$OUT" --dbname="$DSN"\n')
    with pytest.raises(DrillError, match="--recipients-file"):
        production_age_options('age --encrypt --passphrase --output="$OUT"\n')


def test_binding_host_paths_leaves_every_other_option_exactly_as_production_passes_it() -> None:
    bound = apply_options(["--format=custom", "--compress=6", "--file"], {"--file": "/tmp/x"})
    assert bound == ["--format=custom", "--compress=6", "--file=/tmp/x"]


def test_the_coverage_list_is_a_deliverable_and_not_a_disclaimer() -> None:
    identifiers = [identifier for identifier, _, _ in NOT_COVERED]
    assert identifiers, "a local drill that claims to cover everything is the failure mode"
    assert len(identifiers) == len(set(identifiers)), f"duplicate ids: {identifiers}"
    for identifier, what, needs in NOT_COVERED:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", identifier), identifier
        assert what.strip() and needs.strip(), (
            f"{identifier} must say what is untested AND what would be needed to test it — "
            "the second half is what makes it an external blocker rather than a shrug"
        )


def test_every_uncovered_id_is_mapped_onto_the_quarterly_drill_that_does_cover_it() -> None:
    """§0a of the runbook is the map, and `scripts/restore_drill.py` cites it by name.

    Both citations were dangling until this stage: the harness told its reader to run
    `make restore-drill` and to read §0a, and neither existed. A new entry in
    `NOT_COVERED` with no row in that table would put the document back in that state.
    """
    runbook = DRILL_RUNBOOK.read_text(encoding="utf-8")
    assert "## 0a." in runbook, "runbooks/backup-restore-drill.md lost §0a"
    missing = [identifier for identifier, _, _ in NOT_COVERED if f"`{identifier}`" not in runbook]
    assert not missing, (
        "these are printed by every local drill run as NOT tested, and §0a of "
        f"runbooks/backup-restore-drill.md does not say who covers them: {missing}"
    )
