"""Hard rule 8's "reversible", checked on every revision rather than on the new one.

The full proof is a WALK — `upgrade head`, step down to base one revision at a time,
step back up — and it was run over EVERY revision in the tree on a scratch database while
writing this file. The count is not written down, for `check_ledger_immutability`'s
reason: this file once said "all 62 revisions" when there were 65, and a number in prose
beside a directory that grows every week is a claim that is wrong by default.

The walk is not in the suite: it takes about ninety seconds and needs a database of
its own, and a test that slow gets skipped, which is worse than a test that is narrower
and always runs. What IS here is the two defect CLASSES the walk exists to catch, both
of which are decidable from the source, plus the one cluster-level hazard the walk found.

1. **A downgrade that does nothing.** `pass`, or a body that is only a docstring. Such a
   revision passes `alembic downgrade` and leaves the schema where it was, so the next
   `upgrade` re-runs an already-applied change. A downgrade that RAISES is a different
   thing and is allowed here: `d7b1c48a2e93` and `e1a7c93d5b02` both count the rows the
   reversal would destroy FIRST and refuse before touching any DDL. That is hard rule 8
   done right, not skipped — the schema is left exactly as found and the message says
   what to do — so this file requires the refusal to be conditional rather than
   unconditional.

2. **A function created on the way up and left behind on the way down.** This is the one
   that shipped: a downgrade dropped a trigger and not its function, the object survived
   the downgrade, and the next `upgrade` died on `DuplicateFunction` — a revision that
   goes down and cannot come back up. Only a re-upgrade finds it, and only if somebody
   walks; a source rule finds it on the first CI run after the mistake.

3. **A ROLE is cluster-wide and a migration is not.** `05bba2f3c19c` creates
   `calevate_app`; its downgrade used to `DROP ROLE` it unconditionally. On a cluster
   hosting a second database that also uses the role, PostgreSQL refuses ("cannot be
   dropped because some objects depend on it: N objects in database X") and the whole
   downgrade rolls back — `alembic downgrade base` simply cannot complete. On a cluster
   where the sibling database happens to be idle at that instant, it succeeds and takes
   the app role out from under it. The downgrade now drops the role only when
   `pg_shdepend` says nothing outside this database depends on it.

Run: uv run pytest tests/migration_reversibility_test.py -q
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from calevate_shared.config import Settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSIONS = REPO_ROOT / "alembic" / "versions"

CORE_REVISION = "05bba2f3c19c"
APP_ROLE = "calevate_app"

#: A migration may name a function through an f-string over a module constant
#: (`f"DROP FUNCTION IF EXISTS {TRUNCATE_FN}()"`). Matching the literal name would then
#: report a false positive, so a templated DROP counts as covering everything the
#: revision created — the revision that writes one is saying "drop what I made".
_TEMPLATED_DROP = re.compile(r"DROP\s+FUNCTION[^\"']*\{", re.IGNORECASE)
_CREATE_FN = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(\w+)", re.IGNORECASE)
_DROP_FN = re.compile(r"DROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?(\w+)", re.IGNORECASE)


def _revisions() -> list[Path]:
    found = sorted(p for p in VERSIONS.glob("*.py") if not p.name.startswith("__"))
    assert len(found) > 50, f"revision discovery broke — found only {len(found)} files"
    return found


def _function(source: str, tree: ast.AST, name: str) -> tuple[ast.FunctionDef | None, str]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node, ast.get_source_segment(source, node) or ""
    return None, ""


#: Revisions whose `downgrade()` is EMPTY ON PURPOSE, with the reason each one is.
#:
#: The rule above exists because a no-op downgrade reports success, leaves the schema where
#: it was, and lets the next `upgrade` re-apply an already-applied change. That harm needs
#: a change to re-apply. A revision that alters NO SCHEMA and only REPAIRS DATA an earlier
#: migration failed to write has nothing to undo: "reversing" it would mean re-breaking
#: rows on purpose, and for one of these the reversal is not even expressible
#: (`ai_disclosure_line` is NOT NULL with a non-blank CHECK, so there is no empty to
#: restore). Re-applying is the safe direction and is what these are built for — every
#: statement carries a predicate that is false once its work is done, and
#: `tests/migration_repair_test.py` proves both halves against real rows: it repairs, and
#: it leaves an already-correct row untouched.
#:
#: A SCHEMA change may never appear here. The entry names the revision, and the assertion
#: below re-derives whether it is really data-only rather than trusting the listing — an
#: exemption that took the author's word for it would be a hole with a comment over it.
DATA_ONLY_REPAIRS: dict[str, str] = {
    "b7e35c2f81da": (
        "re-runs three backfills that FORCE-RLS swallowed; no DDL, every statement "
        "idempotent, and the disclosure column's reversal is not expressible"
    ),
}

#: What a schema change looks like in a migration's source. A revision claiming to be a
#: data-only repair may contain none of these.
_SCHEMA_VERBS = (
    "create_table",
    "drop_table",
    "add_column",
    "drop_column",
    "alter_column",
    "create_index",
    "drop_index",
    "ALTER TABLE",
    "CREATE TABLE",
    "DROP TABLE",
    "CREATE INDEX",
    "CREATE TYPE",
)


def _string_constants(node: ast.AST) -> list[str]:
    """Every string literal under `node`, f-string fragments included."""
    return [
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]


@pytest.mark.parametrize("path", _revisions(), ids=lambda p: p.name[:13])
def test_every_revision_has_a_downgrade_that_does_something(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    node, _ = _function(source, ast.parse(source), "downgrade")
    assert node is not None, f"{path.name}: no downgrade() at all (hard rule 8)"

    revision = path.name.split("_")[0]
    if revision in DATA_ONLY_REPAIRS:
        # VERIFIED, NOT TAKEN ON TRUST. The exemption is only available to a migration that
        # really changes no schema, and the one on this list DOES issue `ALTER TABLE` — the
        # RLS bracket. That is the exception to the exception: lifting and restoring a
        # policy leaves the schema exactly as found, so it is checked for symmetry instead.
        upgrade, _ = _function(source, ast.parse(source), "upgrade")
        assert upgrade is not None
        schema_statements = [
            literal
            for literal in _string_constants(upgrade)
            if any(verb in literal for verb in _SCHEMA_VERBS)
            and "ROW LEVEL SECURITY" not in literal
        ]
        assert not schema_statements, (
            f"{path.name} is listed as a data-only repair and changes schema: "
            f"{schema_statements[:2]}. Give it a real downgrade or drop the exemption."
        )
        opened = sum(
            "NO FORCE ROW LEVEL SECURITY" in literal for literal in _string_constants(upgrade)
        )
        closed = sum(
            "FORCE ROW LEVEL SECURITY" in literal and "NO FORCE" not in literal
            for literal in _string_constants(upgrade)
        )
        assert opened == closed, (
            f"{path.name} lifts RLS {opened} times and restores it {closed}; a half-open "
            "bracket leaves a table unprotected for every session after it (hard rule 1)"
        )
        return

    body = [
        statement
        for statement in node.body
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
    ]
    assert body and not all(isinstance(s, ast.Pass) for s in body), (
        f"{path.name}: downgrade() is empty. `alembic downgrade` would report success "
        "and change nothing, so the next upgrade re-applies an applied change."
    )

    # A refusal is allowed, but only a CONDITIONAL one — see §1 of the module docstring.
    unconditional = [
        s
        for s in body
        if isinstance(s, ast.Raise)  # a bare top-level raise, outside any if/try
    ]
    assert not unconditional, (
        f"{path.name}: downgrade() raises unconditionally, which is 'not reversible' "
        "spelled with more characters. Refuse only on the data that would be destroyed, "
        "counted before any DDL runs (see d7b1c48a2e93)."
    )


@pytest.mark.parametrize("path", _revisions(), ids=lambda p: p.name[:13])
def test_a_function_created_on_the_way_up_is_dropped_on_the_way_down(path: Path) -> None:
    """The `DuplicateFunction`-on-re-upgrade class, caught without walking the chain."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    _, up = _function(source, tree, "upgrade")
    _, down = _function(source, tree, "downgrade")
    created = set(_CREATE_FN.findall(up))
    if not created or _TEMPLATED_DROP.search(down):
        return
    orphans = sorted(created - set(_DROP_FN.findall(down)))
    assert not orphans, (
        f"{path.name}: upgrade() creates {orphans} and downgrade() never drops "
        f"{'them' if len(orphans) > 1 else 'it'}. The object survives the downgrade and "
        "the next `alembic upgrade` dies on DuplicateFunction — a revision that goes "
        "down and cannot come back up."
    )


def test_the_core_revision_does_not_drop_a_role_out_from_under_another_database() -> None:
    """A ROLE is cluster-wide; this migration is not. Source-level half."""
    source = (next(VERSIONS.glob(f"{CORE_REVISION}_*.py"))).read_text(encoding="utf-8")
    _, down = _function(source, ast.parse(source), "downgrade")
    assert f"DROP ROLE {APP_ROLE}" in down, "the downgrade no longer manages the role at all"
    assert "pg_shdepend" in down, (
        f"{CORE_REVISION}'s downgrade drops {APP_ROLE} without asking whether another "
        "database in the cluster still depends on it. Either the drop fails and the "
        "whole downgrade rolls back, or it succeeds and the sibling database loses its "
        "app role."
    )
    guarded = re.search(r"IF\s+elsewhere\s*=\s*0\s+THEN\s*\n\s*DROP ROLE", down)
    assert guarded, (
        "the DROP ROLE is no longer inside the `elsewhere = 0` branch — the guard is "
        "present but no longer guards anything"
    )


#: The exact predicate the migration's downgrade runs. Duplicated here on purpose: the
#: test below executes it AND then proves PostgreSQL agrees with its verdict, so the two
#: copies drifting apart is caught by the assertion rather than hidden by it.
_ELSEWHERE_SQL = text(
    "SELECT count(*) FROM pg_shdepend s "
    "WHERE s.refobjid = (SELECT oid FROM pg_roles WHERE rolname = :role) "
    "AND s.dbid <> (SELECT oid FROM pg_database WHERE datname = current_database())"
)


async def test_postgres_really_refuses_the_unguarded_drop_when_a_sibling_exists() -> None:
    """The behavioural half: replay the OLD downgrade and watch the cluster refuse it.

    `DROP OWNED BY` then `DROP ROLE`, exactly as `05bba2f3c19c` used to, inside a
    transaction that is always rolled back. The `DROP OWNED BY` matters: without it the
    refusal could come from THIS database's own grants and would prove nothing about the
    sibling. With it, the only remaining dependencies are the ones in other databases,
    which is precisely what the guard is for.

    Skips on a single-database cluster (CI), where the count is zero, the drop would
    legitimately succeed, and running it would delete the role the rest of the run
    needs — a test that destroys its own environment to make a point is not a test.
    """
    url = Settings().alembic_database_url
    if not url:
        pytest.skip("ALEMBIC_DATABASE_URL (owner role) required: DROP OWNED BY needs it")
    engine = create_async_engine(url)
    try:
        # One transaction for the whole probe, rolled back unconditionally: the DROP
        # OWNED BY below revokes this database's grants and must not survive the test.
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                elsewhere = (await conn.execute(_ELSEWHERE_SQL, {"role": APP_ROLE})).scalar_one()
                if not elsewhere:
                    pytest.skip(
                        "single-database cluster: nothing outside this database depends "
                        f"on {APP_ROLE}, so the unguarded DROP ROLE would succeed here "
                        "and would take the role with it. The guard is proven on any "
                        "cluster that has a sibling database — the only place it matters."
                    )
                await conn.execute(text(f"DROP OWNED BY {APP_ROLE}"))
                with pytest.raises(DBAPIError) as caught:
                    await conn.execute(text(f"DROP ROLE {APP_ROLE}"))
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()

    message = str(caught.value)
    assert "depend" in message, (
        f"expected a dependency refusal from DROP ROLE {APP_ROLE} with "
        f"{elsewhere} sibling dependencies, got: {message}"
    )
