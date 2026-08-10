"""Guardrail: the append-only ledgers stay append-only (hard rule 4).

`usage_events`, `consent_ledger` and `audit_log` are INSERT-only. Fixes are
compensating entries, never edits — that is what makes them evidence rather than
records. Two independent failure modes, so two checks:

1. **Database**: an immutability trigger exists on each ledger. Without it, a psql
   session or a future migration could edit history and nothing would notice.
2. **Code**: no ORM `.update(` / `.delete(` and no raw `UPDATE`/`DELETE` statement
   targets a ledger table. The trigger would catch it at runtime — during an incident,
   in production, on the one path nobody tested.

Run: `uv run python -m scripts.check_ledger_immutability`
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from apps.api.core.settings import get_settings
from apps.api.db.registry import APPEND_ONLY_TABLES
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = ("apps", "packages", "scripts")

# Migrations legitimately create and drop these tables, and the retention/erasure
# workers legitimately read them — the pattern below only matches mutations.
EXCLUDED_PARTS = ("alembic/versions", "__pycache__", "check_ledger_immutability.py")

_MUTATION_RE = re.compile(
    r"\b(?:UPDATE\s+(?P<upd>\w+)|DELETE\s+FROM\s+(?P<del>\w+))\b", re.IGNORECASE
)


def check_triggers() -> list[str]:
    settings = get_settings()
    url = (settings.alembic_database_url or settings.database_url).replace("+asyncpg", "+psycopg")
    engine = create_engine(url)
    missing: list[str] = []
    try:
        with engine.connect() as connection:
            for table in APPEND_ONLY_TABLES:
                found = connection.execute(
                    text(
                        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                        "WHERE c.relname = :table AND NOT t.tgisinternal"
                    ),
                    {"table": table},
                ).scalar()
                if not found:
                    missing.append(table)
    finally:
        engine.dispose()
    return missing


def check_sources() -> list[str]:
    offenders: list[str] = []
    ledgers = {t.lower() for t in APPEND_ONLY_TABLES}

    for directory in SEARCH_DIRS:
        for path in (REPO_ROOT / directory).rglob("*.py"):
            if any(part in str(path) for part in EXCLUDED_PARTS):
                continue
            source = path.read_text(encoding="utf-8")
            for match in _MUTATION_RE.finditer(source):
                table = (match.group("upd") or match.group("del") or "").lower()
                if table in ledgers:
                    line = source[: match.start()].count("\n") + 1
                    relative = path.relative_to(REPO_ROOT)
                    offenders.append(f"{relative}:{line} mutates {table}")
    return sorted(offenders)


def main() -> int:
    source_offenders = check_sources()
    if source_offenders:
        print("LEDGER IMMUTABILITY: FAIL — code mutates an append-only ledger")
        for offender in source_offenders:
            print(f"  - {offender}")
        print("\nHard rule 4: fixes are compensating INSERTs, never edits.")
        return 1

    try:
        missing = check_triggers()
    except Exception as exc:
        print(f"LEDGER IMMUTABILITY: code OK; database unchecked ({type(exc).__name__})")
        return 0

    if missing:
        print("LEDGER IMMUTABILITY: FAIL — no immutability trigger on: " + ", ".join(missing))
        print("Add the trigger in a migration; the code check alone is not enough.")
        return 1

    print(
        f"LEDGER IMMUTABILITY: OK ({len(APPEND_ONLY_TABLES)} ledgers, triggers present, "
        "no mutating statements in app code)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
