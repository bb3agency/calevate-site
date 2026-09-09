"""plans.overage_rate_second: the second overage-rate slot, named for the rate it is

Revision ID: c72b9e40af15
Revises: a3f81c2e6d94
Create Date: 2026-09-09

**STEP 1 OF A TWO-STEP DEPRECATION (hard rule 8). NOTHING IS DROPPED HERE.**

`plans.overage_rate_value` is the plan's SECOND overage-rate slot — a founder pricing
lever paired with `plans.overage_rate` — and the word `value` in its name claimed a
voice-quality tier this product does not have. `billing/service.py` above the rung
constants, `apps/workers/pipeline.py` beside the `meta.tts_tier` stamp and
`agents/voices.py` all say so in prose; the column name said the opposite. An earlier
change fixed the words a human READS (the screens and `invoice._RUNG_WORDING`); this is
D-558, the identifier half, and the column is the part of it hard rule 8 governs.

WHAT THIS MIGRATION DOES, AND WHY EACH HALF IS SEPARATE FROM THE OTHER:

1. Adds `overage_rate_second`, nullable NUMERIC(12,4) with no default — catalog-only
   since PG11, so no rewrite and no scan on a table every money reader touches. The
   precision is `MONEY`'s, matching the column beside it, because two rupee columns on
   one row at two precisions is a rounding argument waiting to happen (hard rule 7).
2. Backfills it from `overage_rate_value`. Both columns then hold the same number on
   every existing row, so a reader that prefers the new one and a reader that has not
   moved yet cannot price a month differently. NULL is preserved as NULL: NULL means
   "this plan quotes no separate second rate" and is not zero, and `COALESCE` on a
   NULL-to-NULL copy changes nothing.
3. Adds the same non-negative CHECK the old column carries, under its own name. A
   negative rate is not a discount.

**`overage_rate_value` IS LEFT IN PLACE, STILL WRITTEN AND STILL READ.** `billing/
terms.py::record_terms` inserts the operator's figure into BOTH columns, and
`billing/plans.py::OVERAGE_RATE_SECOND_SQL` reads `COALESCE(new, old)`, so a plan row
written by a process that has not been redeployed yet still prices correctly. Dropping
it in the same release that stopped writing it is precisely what hard rule 8 forbids.

STEP 2, which is NOT this migration, removes: the `overage_rate_value` column, its
check constraint `ck_plans_overage_rate_value_nonnegative`, the legacy half of
`terms._INSERT`, the `COALESCE` in `OVERAGE_RATE_SECOND_SQL`, and `Plan.
overage_rate_value`. It may run only once no deployed process writes the old column.

The constraint mirrors nothing in Python on purpose (the rule b1d5c8e73f04 states): a
migration is a snapshot of the schema on the day it ran.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c72b9e40af15"
down_revision: str | None = "a3f81c2e6d94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "plans"
NEW_COLUMN = "overage_rate_second"
OLD_COLUMN = "overage_rate_value"
CK_SECOND_RATE = "ck_plans_overage_rate_second_nonnegative"

_SECOND_RATE_SQL = f"{NEW_COLUMN} IS NULL OR {NEW_COLUMN} >= 0"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column(NEW_COLUMN, sa.Numeric(12, 4), nullable=True))
    # Runs as the table OWNER and so is not subject to RLS: every tenant's rows are
    # copied in one statement, which is the one thing a migration can do that the
    # application cannot. `overage_rate_value` is NULL on every plan in this database
    # today, so this is expected to touch nothing — it is here because "expected to"
    # is not "did", and a row that does carry a second rate must not lose it.
    op.execute(f"UPDATE {TABLE} SET {NEW_COLUMN} = {OLD_COLUMN} WHERE {OLD_COLUMN} IS NOT NULL")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_SECOND_RATE} CHECK ({_SECOND_RATE_SQL}) NOT VALID"
    )
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_SECOND_RATE}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Reversible with no loss: `record_terms` writes both columns with one figure, so
    # anything written since the upgrade is already in `overage_rate_value`. The copy
    # back is kept anyway for a row written by some other hand — dropping a money
    # column that might hold the only copy of an agreed rate is not a downgrade, it is
    # a data loss with a rollback's name on it.
    op.execute(f"UPDATE {TABLE} SET {OLD_COLUMN} = {NEW_COLUMN} WHERE {OLD_COLUMN} IS NULL")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_SECOND_RATE}")
    op.drop_column(TABLE, NEW_COLUMN)
