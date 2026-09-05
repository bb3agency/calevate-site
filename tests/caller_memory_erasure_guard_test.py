"""Caller memory cannot become writable without the seams that make it forgettable.

**THE SCOPE THIS GUARDS.** `caller_chunks` (migration `c6b1f0d47e83`) declares four
`subject_kind` values, and three of them project something a call already produced — a
turn, a summary, a lead. The fourth, `caller_memory`, is different in the one way that
matters to a data principal: it is the scope whose whole PURPOSE is to outlive the call.
"The agent knows you asked about IVF pricing last month" is only a feature if the row is
still there next month, which means it is still there after the call it was learned on has
been scrubbed, after the transcript's own clock would have taken it, and after a DPDP §12
erasure that never deleted a single row.

**THE FEATURE IS NOW BUILT, AND THIS FILE STILL GUARDS THE SAME THING.** It was written
while the scope was a value in a CHECK and nothing else, and its first test pinned that
honest state: no source table, no writer, and `caller_memory` not a `DATA_CATEGORIES`
value. D-506 built the source and the writer and D-507 gave the scope its own retention
category, so both of those pins are facts about a past release. What is NOT superseded is
the property they existed to protect — that the scope cannot be LIVE without the two
declarations that make it forgettable — so the first test now asserts the closing
condition it used to name rather than the gap it used to describe.

**WHY IT IS WORTH A FILE.** This exact seam has been missed twice in this repository in
one week, both times by people who had read the erasure code:

* `insights/service.scrub_quotes_for_calls` exists because the knowledge-gap tables held
  the caller's own question, copied out of `transcript_turns.text_redacted`, and appeared
  in NO erasure path and in no `DERIVED_COPIES` entry. `knowledge_gap_occurrences.call_id`
  carried `ON DELETE CASCADE`, which reads like protection and is not.
* `c6b1f0d47e83`'s own docstring repeats the finding for vectors: a DPDP erasure SCRUBS a
  call in place and keeps the row (it is billing evidence under an FK RESTRICT from
  `usage_events`), so a cascade on `call_id` NEVER FIRES on the path that matters.

Both times the code was correct-looking and the declaration was missing. So this file
asserts the DECLARATIONS — `DERIVED_COPIES`, which `retention.py` itself calls "the
policy, expressed in the same vocabulary the DPA uses", and the presence of the projection
in the module that owns both erasure entry points. Declarations rather than statements of
SQL on purpose: a grep for a particular UPDATE would break the day somebody refactors it
correctly, and would pass the day somebody adds a fifth arm that forgets this one.

**NO DATABASE.** Every assertion here is about what the code declares, so the guard runs
in any environment and cannot be made to pass by a fixture.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from apps.api.compliance.models import DATA_CATEGORIES
from apps.api.retrieval.caller_erasure import MEMORY_RETENTION_CATEGORY
from apps.workers import retention
from scripts.seed import DEFAULT_RETENTION_POLICIES

#: The `subject_kind` value under guard. Spelled as a literal rather than imported from
#: the migration: a test that imports its subject from the thing it is testing cannot
#: notice the day that thing renames it, and a rename is exactly when the arms get lost.
CALLER_MEMORY_KIND = "caller_memory"

#: The projection table. Same reasoning — the literal is the contract.
PROJECTION_TABLE = "caller_chunks"

#: Where a writer would have to live to be part of the running product. `alembic/` is
#: excluded because the migration NAMES the scope in a CHECK without writing one, and
#: `tests/` because a fixture is not a writer.
_APPS = Path(__file__).resolve().parent.parent / "apps"

#: This module and the subject-key module are excluded from the writer scan: one is the
#: guard itself, the other derives the key a memory row WOULD be filed under and writes
#: nothing. Neither makes the scope live.
_NOT_A_WRITER = frozenset({"caller_ref.py"})


def _mentions_caller_memory() -> set[Path]:
    """Every file under `apps/` that names the caller-memory scope.

    A deliberately BROAD test of "is this scope live". It over-matches — a registry entry
    or a comment counts — and that direction is the safe one: the cost of a false positive
    is that somebody has to add the declarations this file asks for slightly early, and
    the cost of a false negative is a durable profile of a caller that no erasure reaches.
    """
    found: set[Path] = set()
    for path in _APPS.rglob("*.py"):
        if path.name in _NOT_A_WRITER or "__pycache__" in path.parts:
            continue
        if CALLER_MEMORY_KIND in path.read_text(encoding="utf-8"):
            found.add(path)
    return found


def test_a_live_caller_memory_scope_has_a_retention_category_with_an_arm() -> None:
    """THE CONDITION THIS TEST USED TO NAME AS THE THING THAT WOULD CLOSE THE GAP.

    It read, in the release before this one: "this test turns red the moment somebody adds
    `caller_memory` to `DATA_CATEGORIES`, which is the change that would put the scope on a
    clock of its own and quietly leave the transcript arm reaching nothing". D-507 made
    exactly that change deliberately — a memory whose whole purpose is to outlive the call
    must not inherit the call's period — so the assertion is inverted rather than deleted,
    and what it now demands is the half the old warning was actually about: a category with
    a real arm behind it, not a category on its own.

    THREE THINGS OR NONE. A `retention_policies` category nothing sweeps is worse than no
    category at all, because the row makes a promise the DPA prints and the sweep does not
    keep. So the value must exist in `DATA_CATEGORIES` (or no tenant can hold the row at
    all), it must be reachable in `_apply_one` through `MEMORY_RETENTION_CATEGORY` (or the
    sweep has no arm), and the seed must ship the row (or only tenants created by the
    migration ever get one).
    """
    if not _mentions_caller_memory():
        return
    assert CALLER_MEMORY_KIND in DATA_CATEGORIES, (
        "the caller-memory scope is live in apps/ and `caller_memory` is not a "
        "`DATA_CATEGORIES` value, so `retention_policies` cannot hold the row that expires "
        "it. Either file the scope on an existing clock in `models.SUBJECT_RETENTION`, or "
        "add the category here, to the seed defaults and to `_apply_one` in one change."
    )
    assert MEMORY_RETENTION_CATEGORY == CALLER_MEMORY_KIND, (
        "`caller_erasure.MEMORY_RETENTION_CATEGORY` names a different clock from the one "
        "the scope is filed under, so the arm that empties `caller_memories.fact` runs on "
        "a category whose chunks are somebody else's."
    )
    assert "MEMORY_RETENTION_CATEGORY" in inspect.getsource(retention._apply_one), (
        "no arm in `retention._apply_one` runs under the caller-memory category, so the "
        "tenant's policy row is a promise nothing keeps. Asserted on the CONSTANT rather "
        "than on the string, because the constant is what stops the arm and the category "
        "drifting apart."
    )
    assert CALLER_MEMORY_KIND in {
        str(policy["data_category"]) for policy in DEFAULT_RETENTION_POLICIES
    }, (
        "the seed ships no `caller_memory` retention policy, so a tenant onboarded after "
        "migration e1a4d70c9b52 holds remembered facts that no clock expires."
    )


def test_a_live_caller_memory_scope_is_named_in_derived_copies() -> None:
    """THE DECLARATION A COMPLIANCE REVIEWER READS, and the one both prior misses lacked.

    `DERIVED_COPIES` is where `retention.py` states which derived copy expires on which
    tenant-agreed clock. A copy of a caller's words that is not in it is a copy on no
    clock at all — `retention.py`'s own words: "a category nobody sets is a category that
    never expires". The knowledge-gap quotes were exactly that until August.

    Inert while nothing writes the scope, so it costs the sweep nothing today; it fires
    the moment the scope becomes live in `apps/`.
    """
    if not _mentions_caller_memory():
        return
    declared = {copy for copies in retention.DERIVED_COPIES.values() for copy in copies}
    assert any(PROJECTION_TABLE in copy for copy in declared), (
        f"the {CALLER_MEMORY_KIND} scope is live in apps/ and no `DERIVED_COPIES` entry "
        f"names a {PROJECTION_TABLE} projection. The scope's whole purpose is to outlive "
        "the call, so nothing else expires it: not the call row (an erasure scrubs it in "
        "place and keeps it), not the `ON DELETE CASCADE` on `call_id` (it never fires "
        "for that reason), and not the transcript sweep unless this declaration puts it "
        "there. Add the entry under 'caller_memory' — e1a4d70c9b52 files the scope on "
        "that clock (D-507) — in the same change that makes the scope live."
    )


def test_a_live_caller_memory_scope_is_reached_by_the_erasure_paths() -> None:
    """Both erasure entry points live in `workers/retention.py`, so the projection has to
    be reachable from that module — by an arm in it or by something it imports.

    Asserted on the MODULE rather than on either function's own source, deliberately:
    `execute_deletion_request` already discharges half its obligations through helpers
    (`_erase_delivery_bodies`, `_erase_recordings`, `scrub_quotes_for_calls`), so a guard
    that demanded the table name inside one function would fail a correct refactor and
    pass a wrong one that reached only the per-subject path. Both paths are here; the
    module is the honest unit.

    A DPDP §12 erasure holds a PHONE NUMBER and resolves it to calls and leads. Neither
    reaches a caller-memory row, whose subject is a person ACROSS calls — which is why
    `caller_chunks.subject_ref` exists and why this arm cannot be inherited from the
    transcript one.
    """
    if not _mentions_caller_memory():
        return
    assert PROJECTION_TABLE in inspect.getsource(retention), (
        f"the {CALLER_MEMORY_KIND} scope is live in apps/ and `workers/retention.py` — "
        "which owns BOTH `execute_deletion_request` and `execute_tenant_erasure` — never "
        f"mentions {PROJECTION_TABLE}. A remembered fact about a caller who asked to be "
        "forgotten would survive their erasure, and the certificate would say otherwise."
    )
