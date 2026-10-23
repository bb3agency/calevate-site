"""re-run the first_runs.jobs backfill row-level security swallowed

Revision ID: cdd375802099
Revises: b9e4d2a7c513
Create Date: 2026-10-24

`a7d3e9c2f416` (D-863) copied each run's single `job` into the new `jobs` array with an
UPDATE on `first_runs`, a FORCE-RLS table, without lifting RLS. The migration role is
subject to `tenant_isolation`, which is fail-closed on an unset `app.tenant_id`, so the
statement matched no rows wherever the owner is not a superuser. A run left with `job`
set and `jobs` empty reads as unstarted to `first_run/service` (`if not row.jobs`), so
the owner of an onboarding that predates D-863 is sent back to pick a job they already
picked.

That revision has already run and will not run again, so the repair is this later one.
The predicate is the original's verbatim and is false once the work is done, so this is
a no-op where the first run did take effect (a superuser-owned development database).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "cdd375802099"
down_revision: str | None = "b9e4d2a7c513"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Lifted for the owner only, so the backfill sees every tenant's rows (d3b71c9a5e08).
    op.execute("ALTER TABLE first_runs NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE first_runs SET jobs = ARRAY[job] WHERE job IS NOT NULL AND jobs = '{}'")
    op.execute("ALTER TABLE first_runs FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Nothing to undo: the rows this fills are the ones `a7d3e9c2f416` meant to fill, and
    # its own downgrade writes `job` back from `jobs` before dropping the column.
    pass
