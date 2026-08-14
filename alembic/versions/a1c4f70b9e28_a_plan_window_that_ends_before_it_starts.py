"""a plan window that ends before it starts is in effect never

Revision ID: a1c4f70b9e28
Revises: e3f9c2a71d84
Create Date: 2026-08-14 12:10:00.000000

`plans.effective_from` / `effective_to` are the row's VALID TIME, half-open
`[from, to)` (DATA-MODEL §8, `apps/api/billing/plans.py`). The resolver asks
`effective_from <= t AND t < effective_to`, so a row whose `effective_to` is at or
before its `effective_from` matches at NO instant: it is an agreement that prices
nothing, silently, and the symptom is a client whose ceiling and rate stopped binding
with no error anywhere. Nothing refused it until now.

`apps/api/admin/routes.py::CommercialTermsIn` refuses it at the boundary too, and that
duplication is deliberate — the route exists so an operator gets a problem+json naming
the field instead of a 500 out of an IntegrityError, and the constraint exists because
the route is not the only thing that will ever write this table (every plan row in
production today was inserted by hand).

**NOT an EXCLUDE constraint, and not a non-negative money check.** `billing/plans.py`
argues at length why `EXCLUDE USING gist (tenant_id WITH =, tstzrange(...) WITH &&)`
cannot be added here: every existing row is windowless, any two windowless rows overlap,
and the constraint would refuse the table's own contents. Overlap is resolved by a total
order instead, on purpose. A `setup_fee >= 0` check was also considered and rejected:
`billing/charges.py` treats NULL, zero and negative alike as "there is nothing to
charge" and `tests/setup_fee_test.py` pins that a negative fee never reaches a client's
statement, so the reader is already the enforcement and a constraint would only move
where the same outcome is decided.

Verified against the development database before writing: zero rows violate it.

NO NEW TABLE, so no new RLS policy (hard rule 1 is untouched — `plans` keeps its
FORCEd `tenant_isolation` policy). Reversible: `downgrade()` drops the constraint.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1c4f70b9e28"
down_revision: str | Sequence[str] | None = "e3f9c2a71d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "plans"
CONSTRAINT = "ck_plans_window_ordered"

# Mirrors nothing in Python on purpose — a migration is a snapshot of the schema on the
# day it ran, and importing today's constants would rewrite history the next time
# somebody changes the rule (the convention b1d5c8e73f04 and a4e7b2c95d18 record).
_WINDOW_SQL = "effective_from IS NULL OR effective_to IS NULL OR effective_to > effective_from"


def upgrade() -> None:
    # `NOT VALID` then `VALIDATE`, copied from b1d5c8e73f04 on the same table and for
    # the same reason: adding a validated CHECK takes ACCESS EXCLUSIVE for the length of
    # a full scan, while `NOT VALID` takes it only to record the constraint and
    # `VALIDATE` then runs under SHARE UPDATE EXCLUSIVE, which readers and writers pass.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} CHECK ({_WINDOW_SQL}) NOT VALID")
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CONSTRAINT}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
