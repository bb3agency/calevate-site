"""`calls.latency` is gone, and the four places it could come back from are watched.

Migration `f1a7c39d5be2` drops it. The argument is in that migration's docstring; this
file is the part that keeps the argument true after everyone has forgotten it.

A dropped column is not one deletion, it is four, and each one on its own silently
restores the defect:

1. **The SQL column.** Obvious, and the only one a migration does by itself.
2. **The MODEL attribute.** `Mapped[...]` left behind means the next
   `alembic revision --autogenerate` proposes ADD COLUMN latency — a deprecation that
   undoes itself on somebody else's unrelated migration. (Exactly the failure
   `credit_ledger_index_prune_test.py` names for the dropped prefix index.)
3. **The `UNWIRED_BASELINE` entry.** `stale_baseline()` already fails on an entry
   naming no column, so this is belt and braces — but the registry may only shrink, and
   an entry re-added for a column that no longer exists is a hole the next column landing
   on that name would fall into.
4. **Prose that still promises it.** A comment or docstring in `apps/` or `packages/`
   saying `calls.latency` is where the next reader learns the column exists, goes
   looking, and writes the dashboard this drop exists to prevent.

WHY NOT A "the pipeline writes it" TEST INSTEAD: because nothing can write it honestly.
`ExecutionSnapshot` (packages/shared/src/calevate_shared/engine.py) carries no timing
below `duration_s`, and the two summary numbers the column's name promised — turn_p50 /
turn_p95, i.e. voice-to-voice — are not a field any engine hands us; they would be OUR
arithmetic over unvalidated component timings, with no PSTN stopwatch to check it
against (D-39(b): zero real-PSTN measurements). See the migration for what Bolna DOES
publish and why it is a pilot gate rather than a mapper.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from apps.api.crm.models import Call
from apps.api.db.session import untenanted_session
from scripts.check_wiring import UNWIRED_BASELINE, stale_baseline
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOTS = (REPO_ROOT / "apps", REPO_ROOT / "packages")

# `calls.latency` and `Call.latency`, in prose or in code. Not the bare word "latency":
# this repo talks about latency constantly and correctly (the ack budget, the trace
# stages, TRD §4's target), and a check that flagged the word would be deleted within a
# week. What is forbidden is naming THE COLUMN.
_COLUMN_MENTION = re.compile(r"\b(calls|Call)\.latency\b")

#: A mention that is ABOUT the removal is not a promise — it is the evidence the next
#: reader inherits instead of re-deriving, which CLAUDE.md asks for in as many words
#: ("a comment that records the rejected alternative is worth more than the code it sits
#: above"). The first version of this guard forbade the name outright and went red on
#: `flags/registry.py` explaining WHY the column is gone, i.e. it punished exactly the
#: comment that stops somebody adding it back.
#:
#: Deliberately narrow: the line must say so itself. "Dropped", "removed", or the
#: revision that did it. A mention that merely sits near such a word in the same file
#: does not qualify — the file is the wrong unit, because a module can explain the
#: removal in its docstring and still promise the column two hundred lines below.
_REMOVAL_CONTEXT = re.compile(r"\b(dropped|removed|deleted|no longer|stopped being)\b|f1a7c39d5be2")


def test_model_declares_no_latency_column() -> None:
    """Nothing named `latency` is mapped on `Call` — the autogenerate guard."""
    assert not hasattr(Call, "latency")
    assert "latency" not in Call.__table__.columns


async def test_database_has_no_latency_column() -> None:
    """The migration actually ran here. Asked of `information_schema` rather than of the
    ORM, because the ORM is the thing being checked against."""
    async with untenanted_session() as session:
        found = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'calls' AND column_name = 'latency'"
            )
        )
        assert found.scalars().all() == []


async def test_calls_table_still_exists_and_keeps_its_real_duration() -> None:
    """A negative test that cannot pass by the table having vanished.

    `duration_s` is the column `latency` was NOT a duplicate of — end-to-end call length,
    which the pipeline does write — so its presence is both the sanity check that the
    query above looked at a real table and the record of what survives the drop.
    """
    async with untenanted_session() as session:
        found = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'calls' AND column_name IN ('duration_s', 'latency') "
                "ORDER BY column_name"
            )
        )
        assert found.scalars().all() == ["duration_s"]


def test_unwired_baseline_no_longer_records_it() -> None:
    """The registry shrank, and shrank consistently."""
    assert "Call.latency" not in UNWIRED_BASELINE
    assert stale_baseline() == []


@pytest.mark.parametrize("root", SOURCE_ROOTS, ids=lambda path: path.name)
def test_no_source_file_still_promises_the_column(root: Path) -> None:
    """No module in `apps/` or `packages/` names the column — including in prose.

    The adapter docstring in `apps/api/engine/bolna.py` said "`calls.latency` stays null
    for Bolna calls", which was true and is now a pointer to nothing. Doc references
    (TRD §4, DATA-MODEL §4) are out of this file's reach and are handled in the
    migration's docstring.
    """
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _COLUMN_MENTION.search(line) and not _REMOVAL_CONTEXT.search(line)
    ]
    assert offenders == []


def test_a_line_that_promises_the_column_is_still_an_offender() -> None:
    """The narrowing above must not have turned the guard off.

    Without this, `_REMOVAL_CONTEXT` could be widened until every mention slips past and
    the guard reports a clean sweep of nothing — the failure mode `check_wiring`'s
    `blind_spots()` exists for, arriving through an exemption instead of an empty scan.
    """
    promises = "        # `calls.latency` holds the vendor's first-audio number."
    explains = "        # `calls.latency` was dropped in migration f1a7c39d5be2."
    assert _COLUMN_MENTION.search(promises) and not _REMOVAL_CONTEXT.search(promises)
    assert _COLUMN_MENTION.search(explains) and _REMOVAL_CONTEXT.search(explains)
