"""Guardrail: `Base.metadata` and the migrated schema agree about COLUMNS, both ways.

`alembic/env.py` sets `target_metadata = Base.metadata` and CLAUDE.md's workflow is
"autogenerate + hand-review diff". That makes the ORM models the reference the next
migration is generated against — so a live column absent from a model is not a cosmetic
gap, it is `alembic revision --autogenerate` proposing to DROP it, in a diff a human is
asked to skim.

THE DEFECT THIS EXISTS FOR (P4.3), and the reason it is a check rather than a list.
Eight live columns were missing from their models:

    campaigns.dnc_scrubbed_at                  compliance evidence (SEC-COMP §3)
    engine_agent_routes.drift_state/_checked_at/_detected_at        the D-121 sweep
    engine_agent_routes.kb_drift_state/_checked_at/_detected_at     the D-158 sweep
    spend_state.billed_inr                     what the client owes (P1.3)

Every one is written and read by production code. Three of them are the columns the RLS
exemption for `engine_agent_routes` spends fourteen lines justifying, one is the record of
when our own DNC scrub ran, and one is the money figure the compliance gate compares a
client's cap against. An unreviewed autogenerate accept would have deleted the lot.

**The eighth was created while the finding was being fixed.** `spend_state.billed_inr`
shipped in migration `c4f18a6b90e2` in the same session that declared the other seven, and
was missed — which is the whole argument for this file. A rule kept by remembering is a
rule that fails on the next migration; this one failed on the migration being written at
the time.

WHY COLUMNS ONLY, AND NOT THE WHOLE `compare_metadata` DIFF
------------------------------------------------------------
Run against the live schema today, `compare_metadata` reports ~39 differences, and 38 of
them are indexes and constraints. That is EXPECTED and not drift: migrations create
partial indexes, `CONCURRENTLY`-built indexes and named constraints that the ORM
deliberately does not declare, because declaring them would mean the model dictating a
`CREATE INDEX` strategy that has to be chosen per migration (`b1d5c8e73f04` and the
credit-ledger index work both argue this). A guard that failed on all 39 would be a guard
somebody turns off in a week.

Columns are different in kind: there is no legitimate reason for a column to exist in one
place and not the other, in either direction, and the failure is data loss rather than a
slower query. So the scope is exactly `add_column` / `remove_column`, which is precise
enough to be believed and narrow enough to stay green.

BOTH DIRECTIONS, and the second one is the one nothing else covers. This repo has caught
the autogenerate round-trip hazard three times — `call_latency_column_test`,
`prefix_index_audit_test`, `credit_ledger_index_prune_test` — and every one of them checks
that a REMOVED thing stays removed. The opposite direction, a live column the models never
learned about, had no guard at all and eight instances.

Run: uv run python -m scripts.check_metadata_columns   (needs a migrated DB; owner URL)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from apps.api.db.registry import Base
from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

#: The two diff kinds that mean a column exists on one side only. `compare_metadata`
#: yields these as `(op, schema, table, Column)` tuples; everything else it emits is an
#: index or a constraint, which this check deliberately does not judge (module docstring).
COLUMN_OPS = ("add_column", "remove_column")


def column_differences(url: str, metadata: MetaData | None = None) -> list[str]:
    """Every column the model set and the live schema disagree about, as sentences.

    `compare_type` and `compare_server_default` are OFF. Both produce false positives
    against a real Postgres — a `Numeric(12, 4)` model column against a live
    `numeric(12,4)` reports as a type change on some dialect/driver pairs, and a
    server default rendered by the migration never matches the Python-side text — and
    neither is the failure this file is about. What is being asked is only "does this
    column EXIST on both sides".

    `metadata` defaults to the real `Base.metadata` and is a parameter only so the
    negative controls can hand in a DOCTORED COPY of it — mutating the real one would
    leak a missing column into every other test sharing the process.
    """
    engine = create_engine(url.replace("+asyncpg", "+psycopg"))
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn, opts={"compare_type": False, "compare_server_default": False}
            )
            diffs = compare_metadata(context, Base.metadata if metadata is None else metadata)
    finally:
        engine.dispose()

    failures: list[str] = []
    for diff in diffs:
        # Nested lists appear for multi-op diffs (a modified column arrives as a list of
        # its component changes); flatten one level so those cannot hide a column op.
        for entry in diff if isinstance(diff, list) else [diff]:
            if not isinstance(entry, tuple) or entry[0] not in COLUMN_OPS:
                continue
            op, _schema, table, column = entry[0], entry[1], entry[2], entry[3]
            if op == "remove_column":
                failures.append(
                    f"{table}.{column.name}: EXISTS in the database and is missing from "
                    "the ORM model. The next `alembic revision --autogenerate` will "
                    "propose DROPPING it — declare it on the model (P4.3)."
                )
            else:
                failures.append(
                    f"{table}.{column.name}: declared on the ORM model and ABSENT from "
                    "the database. Either the migration that adds it has not been "
                    "written, or it has not been applied to this database."
                )
    return failures


def main() -> int:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url:
        print("METADATA COLUMNS: FAIL — no ALEMBIC_DATABASE_URL or DATABASE_URL to read")
        return 1
    failures = column_differences(url)
    if failures:
        print("METADATA COLUMNS: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nThe models are what `alembic/env.py` generates the next migration AGAINST, "
            "so a column only the database knows about is a proposed DROP in a diff "
            "somebody is asked to skim. Declaring it is the fix; suppressing this check "
            "is how the next eight get in."
        )
        return 1
    print(f"METADATA COLUMNS: OK ({len(Base.metadata.tables)} tables agree in both directions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
