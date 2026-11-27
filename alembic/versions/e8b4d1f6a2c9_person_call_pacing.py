"""how often one person is rung: the calls index and a campaign's recent-call skip (D-1046)

Revision ID: e8b4d1f6a2c9
Revises: a3c8e5f1d742
Create Date: 2026-11-28

The dial gate now counts one account's outbound calls to one number over the last 24 hours on
every call (`compliance/pacing`), and a campaign dispatcher reads the last call that reached a
number in the last N days. Neither had an index to do it with: `ix_calls_to_e164` holds the
number alone, across every tenant and both directions. The new index is partial over outbound
rows, where both reads live, and keyed `(tenant_id, to_e164, created_at)` so each read is one
range scan.

`campaigns.skip_recent_days` is the campaign's "skip people called in the last N days", 1 to 30,
NULL for off. The server default of 7 also fills every existing campaign: a running campaign
skips, from its next tick, people other campaigns reached in the last week. Its own retries are
never held by it (`pacing._REACHED` excludes the campaign's own calls).

Existing tables, existing RLS policies: nothing new to scope. Reversible: `downgrade()` drops
the index, the constraint and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b4d1f6a2c9"
down_revision: str | Sequence[str] | None = "a3c8e5f1d742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_campaigns_skip_recent_days_range"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "campaigns",
        sa.Column("skip_recent_days", sa.Integer(), server_default="7", nullable=True),
    )
    op.execute(
        f"ALTER TABLE campaigns ADD CONSTRAINT {_CHECK} "
        "CHECK (skip_recent_days IS NULL OR skip_recent_days BETWEEN 1 AND 30) NOT VALID"
    )
    op.execute(f"ALTER TABLE campaigns VALIDATE CONSTRAINT {_CHECK}")
    op.create_index(
        "ix_calls_outbound_to_person",
        "calls",
        ["tenant_id", "to_e164", "created_at"],
        postgresql_where=sa.text("direction = 'outbound' AND to_e164 IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index("ix_calls_outbound_to_person", table_name="calls")
    op.execute(f"ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("campaigns", "skip_recent_days")
