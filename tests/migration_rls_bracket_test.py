"""A data migration on a FORCE-RLS table must lift RLS, or it silently touches nothing.

**THIS CLASS HAS NOW SHIPPED TWICE**, and the second time reached production.

Every table in `db/registry.TENANT_TABLES` carries FORCE ROW LEVEL SECURITY, which
subjects the TABLE OWNER to its policy too — and `tenant_isolation` is fail-closed on an
unset `app.tenant_id`. A migration therefore runs its `UPDATE`, `DELETE` or
`INSERT ... SELECT` against ZERO visible rows, reports success, and advances the revision.
Nothing errors. The damage lands later and somewhere else:

* `d3b71c9a5e08` (Aug 2026) — a dedupe DELETE matched nothing and the UNIQUE constraint
  behind it failed on data the migration believed it had cleaned. Caught in review; the
  `NO FORCE` / `FORCE` bracket and its reasoning were written down there.
* `e1a4d70c9b52` (Sep 2026) — a backfill matched nothing and the `SET NOT NULL` behind it
  failed IN PRODUCTION. It had passed locally because the development database had no
  agents in it, which is the worst way for a data migration to pass: vacuously.
* `d4a9c17e6b02` — seeds a retention policy row per organisation with an unbracketed
  `INSERT ... SELECT FROM organizations`. There is no constraint behind it, so it did not
  fail anywhere; it just did not happen, and every organisation predating it holds copilot
  memories nothing expires. That is the shape this guard exists for — the one that leaves
  no trace at all.

So the rule is checked mechanically rather than remembered. It reads the migration SOURCE
and not the database: a migration is a historical artefact that must keep meaning what it
meant, and the point is to fail in CI before the statement ever runs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from apps.api.db.registry import TENANT_TABLES

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS = REPO_ROOT / "alembic" / "versions"

#: `INSERT INTO x`, `UPDATE x`, `DELETE FROM x` — the three statements RLS filters. DDL is
#: not affected (the policy applies to rows, not to the table definition), which is why
#: `ALTER TABLE` and `CREATE INDEX` are absent here.
DML = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:ONLY\s+)?([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

#: A migration that predates this guard, shipped the defect, and CANNOT be repaired by
#: editing it — it has already run everywhere, so its revision will never be applied again.
#: The repair belongs in a LATER migration, and the value here names the one that carries
#: it. An entry is a debt with a payer, not a permission: a new migration may not join this
#: list, which is what the test below asserts by pinning it to exactly these keys.
ALREADY_RUN_AND_REPAIRED_ELSEWHERE = {
    "d4a9c17e6b02_copilot_memory.py": "e1a4d70c9b52 (_REPAIR)",
}

#: Migrations that carry this defect, have ALREADY RUN EVERYWHERE, and have NOT been
#: audited against production data. Editing them is not available — their revisions will
#: never be applied again — so the only questions are whether each one's statement mattered
#: and, where it did, which later migration repairs it.
#:
#: **THIS LIST IS DEBT, NOT PERMISSION.** It is pinned as an equality below so a NEW
#: migration cannot join it: the fix for anything written from today is the bracket. Each
#: entry carries what the statement was for and how much it costs if it silently did
#: nothing, because that is the judgement the audit needs and it is cheaper to record now
#: than to reconstruct later.
#:
#: ⚠ NONE OF THESE HAS BEEN CHECKED AGAINST THE PRODUCTION DATABASE. The symptom is
#: invisible from the migration: a statement that matched nothing and one that had nothing
#: to match are the same success. Whether each mattered depends on whether rows existed at
#: the time, which only the data can answer.
UNAUDITED_PRE_EXISTING = {
    # HIGH — hard rule 5. Splits the legacy bundled `disclosure_line` into the two D-163
    # columns. If it matched nothing, those columns were filled by some other path and the
    # split this migration argues for did not happen on the rows it was written for. It is
    # the one on this list worth checking first.
    "f4a1d0b6e29c_two_notices_two_toggles.py": "agents",
    # MEDIUM — renames a key inside `extraction_schemas.fields`. A schema still carrying
    # the old key renders a column the registry cannot resolve.
    "f4b1e9a2c7d0_extraction_field_description_to_reason.py": "extraction_schemas",
    # MEDIUM — backfills a flag on `calls` that the outbox probe reads.
    "e83b5d1a4c07_outbox_probes_stop_scanning.py": "calls",
    # LOW — writes recording holds for erasures already in flight; a miss leaves audio on
    # the ordinary clock rather than the hold, which the sweep still expires.
    "f3a71c9e26b4_tenant_erasure_requests.py": "recording_erasure_holds",
    # LOW — projection backfill. The ingestion sweep DISCOVERS un-projected rows, so a miss
    # costs one tick, not data.
    "dc1aaeeeff02_kb_chunks_the_retrieval_projection.py": "kb_chunks",
    # LOW — cleanups of rows a later release stopped writing. A miss leaves stale rows that
    # nothing reads.
    "c4d1f7b83e26_two_stores_get_a_retention_clock.py": "retention_policies",
    "d2b6f04a17c9_lead_ownership_assignment_and_timeline.py": "lead_events",
}


def _migrations() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")


def _sql_literals(source: str) -> list[tuple[int, str]]:
    """(line, text) for every string literal that is NOT a docstring.

    THE GUARD READS CODE, NOT PROSE, and reading the raw file text got this wrong: these
    migrations explain themselves at length, and `e4f2a86b13d7`'s docstring contains a
    worked example — `DELETE FROM dnc_list WHERE ...` — written precisely to show what the
    policy refuses. Flagging that is not a false alarm in a small way; it is the guard
    reporting a bug in a sentence about a bug, which trains a reader to disbelieve it.

    Docstrings are dropped by position (the first statement of a module, class or
    function), which is exactly what a docstring IS. Comments never appear in the AST at
    all, so they need no handling.
    """
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _unbracketed(source: str) -> set[str]:
    """Tables this migration writes rows to while RLS is in force and unlifted.

    POSITION MATTERS. A migration that CREATES a table, fills it, and enables FORCE ROW
    LEVEL SECURITY afterwards is safe by construction: the policy is not on the table when
    the rows are written, and there were no rows before it to miss. The failure this guard
    is about is a write against a table whose RLS is ALREADY live, where the owner sees
    nothing and the statement is a silent no-op.

    Line numbers rather than character offsets, because the unit is a string literal and a
    literal has one. Still deliberately single-pass and textual within that: modelling real
    execution order through `op.execute` would be a bigger machine than the thing it
    checks, and the limit is stated rather than left to be discovered — a migration that
    brackets one statement and forgets a second later one passes this test.
    """
    literals = _sql_literals(source)
    tenant = set(TENANT_TABLES)

    def lines_matching(pattern: str) -> list[int]:
        return [line for line, sql in literals if re.search(pattern, sql, re.IGNORECASE)]

    guarded = {
        table.lower()
        for _, sql in literals
        for table in re.findall(
            r"ALTER\s+TABLE\s+([a-z_][a-z0-9_]*)\s+NO\s+FORCE\s+ROW\s+LEVEL\s+SECURITY",
            sql,
            re.IGNORECASE,
        )
    }
    offenders: set[str] = set()
    for line, sql in literals:
        for table in {t.lower() for t in DML.findall(sql)}:
            if table not in tenant or table in guarded:
                continue
            forced = lines_matching(rf"ALTER\s+TABLE\s+{table}\s+FORCE\s+ROW\s+LEVEL\s+SECURITY")
            created = lines_matching(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{table}\b")
            if re.search(rf"create_table\(\s*[\"']{table}[\"']", source):
                created = created or [0]
            if created and (not forced or line < min(forced)):
                continue
            offenders.add(table)
    return offenders


def test_no_migration_writes_rows_to_a_forced_table_without_lifting_rls() -> None:
    """FAILS IF: a migration's DML would silently match zero rows in production.

    The failure message names the file and the table, because the fix is one line and the
    diagnosis is the whole difficulty — a migration that touches nothing looks exactly like
    a migration that had nothing to touch.
    """
    offenders = {
        path.name: sorted(tables)
        for path in _migrations()
        if path.name not in ALREADY_RUN_AND_REPAIRED_ELSEWHERE
        and path.name not in UNAUDITED_PRE_EXISTING
        and (tables := _unbracketed(path.read_text(encoding="utf-8")))
    }
    assert not offenders, (
        f"{offenders}: these migrations write rows to FORCE-RLS tables without an "
        "`ALTER TABLE <t> NO FORCE ROW LEVEL SECURITY` ... `FORCE` bracket. The owner is "
        "subject to `tenant_isolation`, which is fail-closed on an unset `app.tenant_id`, "
        "so the statement matches ZERO rows and reports success. See `d3b71c9a5e08` for "
        "the bracket and why it is safe (it lifts RLS for the OWNER only; `calevate_app` "
        "is NOSUPERUSER NOBYPASSRLS and keeps every policy; DDL is transactional so FORCE "
        "is restored before commit)."
    )


def test_every_bracket_that_opens_is_closed_again() -> None:
    """A migration that lifts RLS and does not restore it leaves a table unprotected.

    The bracket is safe because it is a bracket. Half of one is a tenancy hole (hard rule
    1) that no RLS coverage check would see afterwards, because the table's `relrowsecurity`
    is still true — only FORCE is gone, and only for the owner.
    """
    unclosed: dict[str, list[str]] = {}
    for path in _migrations():
        source = path.read_text(encoding="utf-8")
        opened = re.findall(
            r"ALTER\s+TABLE\s+([a-z_][a-z0-9_]*)\s+NO\s+FORCE\s+ROW\s+LEVEL\s+SECURITY",
            source,
            re.IGNORECASE,
        )
        closed = re.findall(
            r"ALTER\s+TABLE\s+([a-z_][a-z0-9_]*)\s+FORCE\s+ROW\s+LEVEL\s+SECURITY",
            source,
            re.IGNORECASE,
        )
        # `NO FORCE` does NOT match the close pattern — the table name is followed by "NO",
        # not by "FORCE" — so these two counts are directly comparable.
        missing = [t for t in set(opened) if closed.count(t) < opened.count(t)]
        if missing:
            unclosed[path.name] = sorted(missing)
    assert not unclosed, (
        f"{unclosed}: RLS was lifted and not restored. Add the matching "
        "`ALTER TABLE <t> FORCE ROW LEVEL SECURITY` after the statement it protects."
    )


def test_the_exception_list_is_closed_and_names_who_pays_the_debt() -> None:
    """An entry here is a migration that already ran, so it can only be repaired later.

    Pinned as an EQUALITY so a new migration cannot be waived into it. If a fourth one
    appears the answer is the bracket, not a fourth key — and if a repair lands for the
    existing entry, this test is where the removal gets noticed.
    """
    assert set(ALREADY_RUN_AND_REPAIRED_ELSEWHERE) == {"d4a9c17e6b02_copilot_memory.py"}
    # Pinned as an equality for the same reason: seven is the number that existed when this
    # guard was written, and a migration authored afterwards has no excuse to be the eighth.
    assert len(UNAUDITED_PRE_EXISTING) == 7
    assert not (set(UNAUDITED_PRE_EXISTING) & set(ALREADY_RUN_AND_REPAIRED_ELSEWHERE)), (
        "a migration is either repaired or unaudited, never filed as both"
    )
    for name, table in UNAUDITED_PRE_EXISTING.items():
        assert (VERSIONS / name).exists(), f"{name} no longer exists; drop its entry"
        assert table in set(TENANT_TABLES), f"{name} names {table}, which is not RLS'd"
    for name, payer in ALREADY_RUN_AND_REPAIRED_ELSEWHERE.items():
        assert (VERSIONS / name).exists(), f"{name} no longer exists; drop its entry"
        revision = payer.split()[0]
        assert list(VERSIONS.glob(f"{revision}_*.py")), (
            f"{name} names {revision} as its repair and that migration is not in the tree"
        )


def test_the_repair_migration_actually_seeds_the_row_the_broken_one_missed() -> None:
    """The debt is paid where it says it is, not just pointed at.

    Reads the repair's source for the category it re-seeds. A pointer that names a
    migration which does not carry the repair is worse than no pointer: it closes the
    question while leaving the rows missing.
    """
    repair = next(VERSIONS.glob("e1a4d70c9b52_*.py")).read_text(encoding="utf-8")
    assert "_REPAIR" in repair
    assert "copilot_memory" in repair, "the repair no longer names the category it restores"
    assert "ON CONFLICT" in repair, (
        "the repair must be a no-op where the original seed did work — it runs on every "
        "deployment, including the ones that were never broken"
    )
