"""the erasure sweep and the KYC purge try the rows they keep failing on last

Revision ID: c7e4a9d2f513
Revises: e3b9d5f1a827
Create Date: 2026-10-26 12:00:00.000000

Both sweeps read a bounded batch ordered by due date, so a batch-full of rows that fail on
every run (an account the erasure filing refuses, a file whose delete storage refuses) was
the whole batch for ever and nothing behind it was ever tried.

`organizations.erasure_sweep_attempted_at` / `erasure_sweep_failures` stamp each hourly
attempt to file an account's erasure; `tenancy/closure.due_erasures` orders by the stamp
(untried first), and three failed ticks in a row raise `closure_erasure_stuck`.
`kyc_documents.purge_failures` / `purge_failed_at` count failed deletes;
`workers/kyc_owner_id_purge` takes never-failed files first and raises `kyc_purge_stuck`.

Constant defaults, so adding the NOT NULL counters rewrites no table. Both tables keep
their existing RLS policies: the counters are written under the owning tenant's session,
like every other write to these rows. DOWNGRADE drops the four columns; the sweeps of that
revision order by due date again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e4a9d2f513"
down_revision: str | None = "e3b9d5f1a827"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column("erasure_sweep_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("erasure_sweep_failures", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "kyc_documents",
        sa.Column("purge_failures", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "kyc_documents",
        sa.Column("purge_failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("kyc_documents", "purge_failed_at")
    op.drop_column("kyc_documents", "purge_failures")
    op.drop_column("organizations", "erasure_sweep_failures")
    op.drop_column("organizations", "erasure_sweep_attempted_at")
