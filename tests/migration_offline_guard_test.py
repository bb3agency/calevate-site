"""`alembic upgrade head --sql` must keep completing: no unguarded `op.get_bind()`.

Offline mode renders SQL for a human to review and apply (`docs/DEPLOYMENT.md`) and holds
**no connection at all** — `op.get_bind()` returns `None` there. A migration that queries
the database dies with `AttributeError: 'NoneType' object has no attribute 'first'`, and
because alembic renders revisions in order, ONE such call makes every revision after it
unreachable offline. That is not a hypothetical: twelve migrations read this way and the
`--sql` path had never completed once, which is the state this guard exists to keep closed.

WHY A STRUCTURAL GUARD RATHER THAN A RENDER
-------------------------------------------
Rendering the whole chain in a test is the stronger check and was rejected: it needs a
`ALEMBIC_DATABASE_URL` (offline still builds one to pick a dialect), it re-parses 140
modules on every run, and its failure names an `AttributeError` in alembic's runtime rather
than the line somebody just wrote. This scans the source instead, so a NEW migration that
reads the database fails at the call site, in the diff that introduced it.

WHAT COUNTS AS GUARDED
----------------------
`op.get_bind()` may appear only in a function that has ALREADY consulted the mode — one of
`apps.api.db.migration_offline`'s gates, evaluated earlier in the source than the read. The
ordering is the whole point: a gate BELOW the read guards nothing, and "the function
mentions the helper somewhere" is exactly the kind of assertion that passes while the bug
ships. What each gate does offline, and why a probe may be skipped where a data statement
may not, is stated once in that module's docstring rather than restated here.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS = REPO_ROOT / "alembic" / "versions"
HELPER = REPO_ROOT / "apps" / "api" / "db" / "migration_offline.py"

#: The gates a migration may consult before reading. `is_offline` is the raw question;
#: `probe_skipped_offline` answers it and records a note in the rendered script; and
#: `execute_data_statement` takes the whole decision, so a function that only calls it
#: never reaches `op.get_bind()` itself.
GATES = ("probe_skipped_offline", "is_offline", "execute_data_statement")

#: A floor, not a target. This scan is worthless if it silently stops finding call sites —
#: a rename of `op` to something else, or a migration style that binds through
#: `context.get_bind()`, would make every assertion below vacuously true. Twelve migrations
#: held sixteen reads when this guard was written; the floor is set well under that so
#: deleting a migration does not fail the suite, and only wholesale discovery breakage does.
MINIMUM_KNOWN_READS = 8


def _migrations() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")


def _position(node: ast.AST) -> tuple[int, int]:
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))


def _is_get_bind(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_bind"
    )


def _called_name(node: ast.AST) -> str | None:
    """The bare name a call uses, for `f(...)` and `mod.f(...)` alike."""
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _unguarded_reads(source: str) -> list[tuple[str, int]]:
    """Every `op.get_bind()` with no gate evaluated before it, as (function, line)."""
    findings: list[tuple[str, int]] = []
    tree = ast.parse(source)
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = [node for statement in function.body for node in ast.walk(statement)]
        gates = [_position(n) for n in body if _called_name(n) in GATES]
        earliest = min(gates, default=None)
        for node in body:
            if _is_get_bind(node) and (earliest is None or earliest > _position(node)):
                findings.append((function.name, node.lineno))
    return findings


def test_no_migration_reads_the_database_without_asking_whether_one_is_there() -> None:
    reads = 0
    problems: list[str] = []
    for path in _migrations():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        reads += sum(1 for node in ast.walk(tree) if _is_get_bind(node))
        problems.extend(
            f"{path.name}:{line} in {function}()" for function, line in _unguarded_reads(source)
        )

    assert reads >= MINIMUM_KNOWN_READS, (
        f"found only {reads} `op.get_bind()` call(s) across {len(_migrations())} migrations, "
        f"below the floor of {MINIMUM_KNOWN_READS}. This scan has stopped finding call sites "
        "— fix the discovery rather than believing the clean report."
    )
    assert not problems, (
        "these migrations query the database with nothing to check first that a database "
        "is there, which breaks `alembic upgrade head --sql` at that revision and makes "
        "every revision after it unreachable offline:\n  - "
        + "\n  - ".join(problems)
        + "\n\n  Gate the read with one of "
        + ", ".join(f"`{gate}`" for gate in GATES)
        + " from `apps.api.db.migration_offline`, and say in the comment what the offline "
        "emit does and what it deliberately does not do. A probe may be skipped; a data "
        "statement may NOT — emit it, and drop only the row count."
    )


def test_the_gates_this_guard_names_still_exist() -> None:
    """A guard whose vocabulary has drifted passes while the property it names is gone."""
    helper = ast.parse(HELPER.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in helper.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    missing = sorted(set(GATES) - defined)
    assert not missing, (
        f"{', '.join(missing)} no longer exist in apps/api/db/migration_offline.py, so this "
        "guard would accept a migration that gates on nothing. Re-point GATES at whatever "
        "replaced them."
    )
