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

#: The READ side of a write, which is the half this guard originally missed.
#:
#: `INSERT INTO x SELECT ... FROM tenant_table` and `UPDATE x ... FROM tenant_table` are
#: filtered by the policy on the table being READ, not only on the one being written — so a
#: reach-backwards can be perfectly correct about its target and still write nothing,
#: because its SELECT saw no rows. `dc1aaeeeff02` is the worked example: it inserts into
#: `kb_chunks` BEFORE that table's policy exists (deliberate, and its docstring says so), so
#: the write side is genuinely safe — while selecting from `kb_documents` and `kb_sources`,
#: both FORCE-RLS, which is not. Checking only the target called that migration an offender
#: for the wrong reason and would have cleared a `SELECT FROM organizations` that mattered.
READ_SIDE = re.compile(r"\b(?:FROM|JOIN)\s+(?:ONLY\s+)?([a-z_][a-z0-9_]*)", re.IGNORECASE)

#: A migration that predates this guard, shipped the defect, and CANNOT be repaired by
#: editing it — it has already run everywhere, so its revision will never be applied again.
#: The repair belongs in a LATER migration, and the value here names the one that carries
#: it. An entry is a debt with a payer, not a permission: a new migration may not join this
#: list, which is what the test below asserts by pinning it to exactly these keys.
ALREADY_RUN_AND_REPAIRED_ELSEWHERE = {
    # The retention policy row every organisation should have and does not.
    "d4a9c17e6b02_copilot_memory.py": "e1a4d70c9b52 (_REPAIR)",
    # The D-163 disclosure split. Hard rule 5: an agent left unsplit has no AI sentence on
    # file and the dial gate refuses it.
    "f4a1d0b6e29c_two_notices_two_toggles.py": "b7e35c2f81da",
    # `description` -> `reason` inside `extraction_schemas.fields`.
    "f4b1e9a2c7d0_extraction_field_description_to_reason.py": "b7e35c2f81da",
    # `calls.crm_notified_at`, so the CRM probe stops rescanning delivered calls.
    "e83b5d1a4c07_outbox_probes_stop_scanning.py": "b7e35c2f81da",
}

#: ⚠ EMPTY, AND KEPT AS A NAMED EMPTY RATHER THAN DELETED.
#:
#: It held seven migrations for one day. Six were resolved by looking rather than by
#: waiving, and the split is worth recording because it is the same split any future entry
#: will have:
#:
#: * FOUR were `downgrade()`-only (`c4d1f7b83e26`, `d2b6f04a17c9`, `f3a71c9e26b4`, and one
#:   arm of `d4a9c17e6b02`). A downgrade has never run in production, so those were fixed
#:   IN PLACE — correcting a statement that never executed rewrites no history, and it
#:   matters for any fresh install that migrates the whole chain from base.
#: * ONE (`dc1aaeeeff02`) was never a defect. It inserts into `kb_chunks` BEFORE that
#:   table's policy exists and says so in its own docstring; the guard had been reading only
#:   the write target and flagged it for the wrong reason. Reading it is what produced
#:   `READ_SIDE` above, which is a real class the guard had been missing entirely.
#: * THREE were real and are repaired by `b7e35c2f81da`, listed above.
#:
#: A new entry here would mean a migration that has already run, carries the defect, and has
#: no repair yet. That is a legitimate state to be in for as long as it takes to write the
#: repair — and no longer.
UNAUDITED_PRE_EXISTING: dict[str, str] = {}


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
        # A FUNCTION BODY IS NOT RUN BY THIS MIGRATION. `CREATE FUNCTION` stores the text;
        # the statements inside execute later, in whatever session fires the trigger — the
        # app's, with `app.tenant_id` set and the policy doing exactly its job. Bracketing
        # there would be wrong, not merely unnecessary. `d4a9c17e6b02` defines a worklist
        # trigger whose body inserts into `retention_worklist`, and counting that as a
        # migration-time write reported a defect in code that has none.
        if re.search(r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION", sql, re.IGNORECASE):
            continue
        written = {t.lower() for t in DML.findall(sql)}
        # The read side counts only for a statement that WRITES. A bare SELECT in a
        # migration is a question, and one that sees no rows answers "none" without
        # corrupting anything; it is the WRITE that acts on the answer.
        read = ({t.lower() for t in READ_SIDE.findall(sql)} if written else set()) - written
        for table in written | read:
            if table not in tenant or table in guarded:
                continue
            forced = lines_matching(rf"ALTER\s+TABLE\s+{table}\s+FORCE\s+ROW\s+LEVEL\s+SECURITY")
            if table in read:
                # Read side: the only question is whether ITS policy is already live, since
                # no statement creates the table it selects from and fills it in one breath.
                if not forced or line < min(forced):
                    continue
                offenders.add(table)
                continue
            if _created_before(source, table, line, forced):
                continue
            offenders.add(table)
    return offenders


def _created_before(source: str, table: str, line: int, forced: list[int]) -> bool:
    """Did THIS migration create `table` and write to it before its policy went on?

    The `create_table(TABLE, ...)` spelling — the table name held in a module constant
    rather than written as a literal — is why this is a function and not one regex.
    `dc1aaeeeff02` creates `kb_chunks` that way and its docstring states the ordering
    outright ("The backfill runs BEFORE the policy exists, deliberately"); a literal-only
    check called it an offender, which is the guard contradicting a correct migration.
    """
    if re.search(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{table}\b", source, re.IGNORECASE):
        return not forced or line < min(forced)
    if re.search(rf"""create_table\(\s*["']{table}["']""", source):
        return not forced or line < min(forced)
    # `op.create_table(TABLE, ...)` with `TABLE = "<name>"` a module constant.
    if re.search(
        rf"""^TABLE\s*(?::[^=]+)?=\s*["']{table}["']""", source, re.MULTILINE
    ) and re.search(r"create_table\(\s*TABLE\b", source):
        return not forced or line < min(forced)
    return False


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
    """An entry is a migration that already ran, so it can only be repaired later.

    Pinned as an EQUALITY so a new migration cannot be waived in: the fix for anything
    written from today is the bracket, and a fifth key would mean somebody chose the list
    over the one-line change. It is also where a removal gets noticed — if a repair is
    deleted, the entry pointing at it must go too, and this is what forces that pairing.
    """
    assert set(ALREADY_RUN_AND_REPAIRED_ELSEWHERE) == {
        "d4a9c17e6b02_copilot_memory.py",
        "f4a1d0b6e29c_two_notices_two_toggles.py",
        "f4b1e9a2c7d0_extraction_field_description_to_reason.py",
        "e83b5d1a4c07_outbox_probes_stop_scanning.py",
    }
    assert not UNAUDITED_PRE_EXISTING, (
        "an unaudited entry is a defect that has run in production with no repair written "
        "yet — legitimate only while the repair is being written"
    )
    assert not (set(UNAUDITED_PRE_EXISTING) & set(ALREADY_RUN_AND_REPAIRED_ELSEWHERE)), (
        "a migration is either repaired or unaudited, never filed as both"
    )
    for name, payer in ALREADY_RUN_AND_REPAIRED_ELSEWHERE.items():
        assert (VERSIONS / name).exists(), f"{name} no longer exists; drop its entry"
        revision = payer.split()[0]
        assert list(VERSIONS.glob(f"{revision}_*.py")), (
            f"{name} names {revision} as its repair and that migration is not in the tree"
        )


def test_each_repair_names_the_migration_it_repairs() -> None:
    """A pointer is only worth as much as what it points AT.

    A repair migration that does not mention the revision it heals is a pointer nobody can
    follow back — and the failure mode is specific: a later reader deletes what looks like a
    redundant backfill, because nothing in the file says which historical bug it exists for.
    """
    for name, payer in ALREADY_RUN_AND_REPAIRED_ELSEWHERE.items():
        revision = payer.split()[0]
        repair = next(VERSIONS.glob(f"{revision}_*.py")).read_text(encoding="utf-8")
        broken = name.split("_")[0]
        assert broken in repair, (
            f"{revision} is named as the repair for {broken} and never mentions it"
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
