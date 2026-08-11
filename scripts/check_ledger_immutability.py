"""Guardrail: the append-only ledgers stay append-only (hard rule 4).

`usage_events`, `consent_ledger`, `credit_ledger` and `audit_log` are INSERT-only.
Fixes are compensating entries, never edits — that is what makes them evidence rather
than records. Three independent failure modes, so three checks:

1. **Raw SQL**: no `UPDATE <ledger>` / `DELETE FROM <ledger>` / `TRUNCATE <ledger>`
   statement anywhere in app code. Scanned over the file text AND over every parsed
   string literal, so implicit concatenation (`"UPDATE " "usage_events"`), schema
   qualification (`public.usage_events`) and quoted identifiers do not hide it.
2. **ORM**: no `update(UsageEvent)` / `delete(AuditLogEntry)` /
   `session.query(...).delete()` / `Model.__table__.update()`, and no
   `ondelete="CASCADE"` or cascading relationship that would delete ledger rows as a
   side effect of deleting something else. AST, not grep — the docstring of the old
   version claimed ORM coverage that the regex never had.
3. **Database**: each ledger carries a trigger that ACTUALLY BLOCKS — enabled,
   row-level, covering both UPDATE and DELETE, running a function that raises. A
   trigger that merely exists (or exists and is DISABLEd) is decoration.

What it deliberately does NOT catch, so nobody reads a green run as total coverage:
`session.delete(obj)` on an already-loaded instance, and SQL assembled at runtime from
variables — neither is resolvable without running the program. Check 3 is the backstop
for exactly those, which is why it verifies blocking rather than existence.

Run: `uv run python -m scripts.check_ledger_immutability`
"""

from __future__ import annotations

import ast
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from apps.api.core.settings import get_settings
from apps.api.db.registry import APPEND_ONLY_TABLES, Base
from sqlalchemy import Engine, create_engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = ("apps", "packages", "scripts")

# Migrations legitimately create and drop these tables, and the retention/erasure
# workers legitimately read them — the checks below only match mutations.
EXCLUDED_PARTS = ("alembic/versions", "__pycache__", "check_ledger_immutability.py")

# Optional schema qualifier and/or quoting around the table name: `public."usage_events"`
# is the same table as `usage_events`, and a guardrail that only knows the bare form is
# a guardrail with a documented bypass.
_TABLE = r"""(?:["'`]?\w+["'`]?\s*\.\s*)?["'`]?(?P<t{n}>\w+)["'`]?"""
_MUTATION_RE = re.compile(
    r"\b(?:UPDATE\s+(?:ONLY\s+)?" + _TABLE.format(n=1) + r"|"
    r"DELETE\s+FROM\s+(?:ONLY\s+)?" + _TABLE.format(n=2) + r"|"
    r"TRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?" + _TABLE.format(n=3) + r")\b",
    re.IGNORECASE | re.VERBOSE,
)

# Trigger type bits (see pg_trigger.tgtype in the PostgreSQL catalogs). BEFORE vs AFTER
# is deliberately not required: either aborts the transaction when the function raises.
_TG_ROW, _TG_DELETE, _TG_UPDATE = 1 << 0, 1 << 3, 1 << 4


def ledger_model_classes(tables: list[str] | None = None) -> dict[str, str]:
    """Map ORM class name -> ledger table, so the AST scan can name the offender."""
    wanted = set(tables or APPEND_ONLY_TABLES)
    return {
        mapper.class_.__name__: mapper.local_table.name
        for mapper in Base.registry.mappers
        if mapper.local_table is not None and mapper.local_table.name in wanted
    }


# --- 1 + 2: source scanning ---------------------------------------------------


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _string_literals(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Every string constant with its line.

    Python joins adjacent string literals at parse time, so scanning constants is what
    closes the `"UPDATE " "usage_events"` split-literal hole that a text-only regex has.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):  # f-string: check the literal fragments
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    yield node.lineno, part.value


def _sql_hits(source: str, tree: ast.AST | None, ledgers: set[str]) -> set[tuple[int, str]]:
    hits: set[tuple[int, str]] = set()
    for match in _MUTATION_RE.finditer(source):
        table = _matched_table(match)
        if table in ledgers:
            hits.add((source[: match.start()].count("\n") + 1, table))
    if tree is not None:
        for lineno, literal in _string_literals(tree):
            for match in _MUTATION_RE.finditer(literal):
                table = _matched_table(match)
                if table in ledgers:
                    hits.add((lineno, table))
    return hits


def _matched_table(match: re.Match[str]) -> str:
    for group in ("t1", "t2", "t3"):
        value = match.group(group)
        if value:
            return value.lower()
    return ""


def _orm_hits(tree: ast.AST, classes: dict[str, str]) -> set[tuple[int, str]]:
    """`update(UsageEvent)`, `session.query(UsageEvent).delete()`, `X.__table__.delete()`.

    Exact class-name matching keeps `payload.update(usage_row)` — a dict update — out of
    the results: a guardrail that fires on legitimate code gets deleted, which is the
    same outcome as not having one.
    """
    hits: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            verb, receiver_names = func.id, set()
        elif isinstance(func, ast.Attribute):
            verb, receiver_names = func.attr, _names_in(func.value)
        else:
            continue
        if verb not in ("update", "delete"):
            continue
        touched = receiver_names | {n for arg in node.args for n in _names_in(arg)}
        for name in sorted(touched & set(classes)):
            hits.add((node.lineno, classes[name]))
    return hits


def _cascade_hits(tree: ast.AST, classes: dict[str, str]) -> set[tuple[int, str]]:
    """A cascade is a DELETE nobody wrote: `ondelete="CASCADE"` on a ledger's own FK, or
    a `relationship(..., cascade="all, delete")` pointing at a ledger model."""
    hits: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            table = _tablename_of(node)
            if table in set(classes.values()):
                for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
                    for kw in call.keywords:
                        if kw.arg == "ondelete" and _const_str(kw.value).upper() == "CASCADE":
                            hits.add((call.lineno, table))
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "relationship":
                continue
            targets = {_const_str(a) for a in node.args} | _names_in(node)
            cascade = next((_const_str(k.value) for k in node.keywords if k.arg == "cascade"), "")
            if "delete" in cascade.lower():
                for target in sorted(targets & set(classes)):
                    hits.add((node.lineno, classes[target]))
    return hits


def _tablename_of(node: ast.ClassDef) -> str:
    for stmt in node.body:
        targets = (
            stmt.targets
            if isinstance(stmt, ast.Assign)
            else [stmt.target]
            if isinstance(stmt, ast.AnnAssign)
            else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__tablename__":
                return _const_str(stmt.value) if stmt.value is not None else ""
    return ""


def _const_str(node: ast.AST | None) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def scan_source(path: Path, source: str, *, classes: dict[str, str] | None = None) -> list[str]:
    """All ledger mutations in one file. Pure: no filesystem, no database."""
    classes = ledger_model_classes() if classes is None else classes
    ledgers = set(classes.values()) | {t.lower() for t in APPEND_ONLY_TABLES}
    try:
        tree: ast.AST | None = ast.parse(source)
    except SyntaxError:
        tree = None
    findings: set[tuple[int, str, str]] = set()
    for lineno, table in _sql_hits(source, tree, ledgers):
        findings.add((lineno, table, "raw SQL mutates"))
    if tree is not None:
        for lineno, table in _orm_hits(tree, classes):
            findings.add((lineno, table, "ORM mutation targets"))
        for lineno, table in _cascade_hits(tree, classes):
            findings.add((lineno, table, "cascade delete reaches"))
    return [f"{path}:{line} {why} {table}" for line, table, why in sorted(findings)]


def check_sources(root: Path | None = None, dirs: tuple[str, ...] = SEARCH_DIRS) -> list[str]:
    root = root or REPO_ROOT
    classes = ledger_model_classes()
    offenders: list[str] = []
    for directory in dirs:
        for path in (root / directory).rglob("*.py"):
            if any(part in str(path) for part in EXCLUDED_PARTS):
                continue
            offenders += scan_source(
                path.relative_to(root), path.read_text(encoding="utf-8"), classes=classes
            )
    return sorted(offenders)


# --- 3: the database actually blocks ------------------------------------------


@dataclass(frozen=True)
class TriggerFacts:
    """One non-internal trigger, reduced to what "does it block?" depends on."""

    table: str
    name: str
    enabled: bool
    row_level: bool
    on_update: bool
    on_delete: bool
    function: str
    raises: bool

    @classmethod
    def from_row(
        cls, table: str, name: str, enabled: str, tgtype: int, fn: str, src: str
    ) -> TriggerFacts:
        return cls(
            table=table,
            name=name,
            enabled=enabled in ("O", "A"),
            row_level=bool(tgtype & _TG_ROW),
            on_update=bool(tgtype & _TG_UPDATE),
            on_delete=bool(tgtype & _TG_DELETE),
            function=fn,
            raises="RAISE EXCEPTION" in (src or "").upper(),
        )


_TRIGGER_SQL = text(
    "SELECT c.relname, t.tgname, t.tgenabled, t.tgtype, p.proname, p.prosrc "
    "FROM pg_trigger t "
    "JOIN pg_class c ON c.oid = t.tgrelid "
    "JOIN pg_proc p ON p.oid = t.tgfoid "
    "WHERE NOT t.tgisinternal AND c.relname = ANY(:tables)"
)


def fetch_triggers(engine: Engine, tables: list[str] | None = None) -> list[TriggerFacts]:
    wanted = list(tables or APPEND_ONLY_TABLES)
    with engine.connect() as connection:
        rows = connection.execute(_TRIGGER_SQL, {"tables": wanted}).all()
    return [TriggerFacts.from_row(r[0], r[1], r[2], int(r[3]), r[4], r[5]) for r in rows]


def evaluate_triggers(triggers: list[TriggerFacts], tables: list[str] | None = None) -> list[str]:
    """A ledger is protected only if some ENABLED, row-level, RAISEing trigger covers
    UPDATE and some covers DELETE. Presence alone proved nothing."""
    failures: list[str] = []
    for table in tables or APPEND_ONLY_TABLES:
        candidates = [t for t in triggers if t.table == table]
        if not candidates:
            failures.append(f"{table}: no immutability trigger at all")
            continue
        blocking = [t for t in candidates if t.enabled and t.row_level and t.raises]
        if not blocking:
            reasons = ", ".join(
                f"{t.name}(enabled={t.enabled}, row_level={t.row_level}, raises={t.raises})"
                for t in candidates
            )
            failures.append(f"{table}: trigger present but does not block — {reasons}")
            continue
        uncovered = [
            verb
            for verb, covered in (
                ("UPDATE", any(t.on_update for t in blocking)),
                ("DELETE", any(t.on_delete for t in blocking)),
            )
            if not covered
        ]
        if uncovered:
            verbs = ", ".join(uncovered)
            failures.append(f"{table}: immutability trigger does not fire on {verbs}")
    return failures


def check_triggers() -> list[str]:
    settings = get_settings()
    url = (settings.alembic_database_url or settings.database_url).replace("+asyncpg", "+psycopg")
    engine = create_engine(url)
    try:
        return evaluate_triggers(fetch_triggers(engine))
    finally:
        engine.dispose()


def main() -> int:
    source_offenders = check_sources()
    if source_offenders:
        print("LEDGER IMMUTABILITY: FAIL — code mutates an append-only ledger")
        for offender in source_offenders:
            print(f"  - {offender}")
        print("\nHard rule 4: fixes are compensating INSERTs, never edits.")
        return 1

    try:
        failures = check_triggers()
    except Exception as exc:
        # Unverified is not the same as verified-good. Locally (no docker) that is a
        # warning; in CI the database is a service container, so an unreachable one is
        # a broken check pretending to be a green one.
        if os.environ.get("CI"):
            print(f"LEDGER IMMUTABILITY: FAIL — database unreachable in CI ({exc!r})")
            print("The trigger half of this guardrail must run where a database exists.")
            return 1
        print(f"LEDGER IMMUTABILITY: code OK; database unchecked ({type(exc).__name__})")
        print("Start the database (`make up`) to verify the triggers actually block.")
        return 0

    if failures:
        print("LEDGER IMMUTABILITY: FAIL — a ledger is not protected by a blocking trigger")
        for failure in failures:
            print(f"  - {failure}")
        print("Add/repair the trigger in a migration; the code check alone is not enough.")
        return 1

    print(
        f"LEDGER IMMUTABILITY: OK ({len(APPEND_ONLY_TABLES)} ledgers, triggers verified "
        "enabled+raising on UPDATE and DELETE, no mutating statements in app code)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
