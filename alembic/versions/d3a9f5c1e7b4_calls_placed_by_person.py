"""a call says whether a person placed it (Make a call)

Revision ID: d3a9f5c1e7b4
Revises: c7e1a4d9b2f6
Create Date: 2026-11-06 10:00:00.000000

The Make a call screen lists the one-off calls people placed (Make a call, a lead's or a call's
Call, Pip's `call_place`). Nothing on `calls` told them apart from a follow-up step's or a new
lead's first call, which also have no campaign; the audit log records the act but is a ledger,
not a list a screen should page through. So `crm/lead_dial` marks its intent row in the intent
transaction, before the dial.

`NOT NULL DEFAULT false` is a catalogue-only change on Postgres 11+ (no table rewrite). The
partial index holds only the marked rows. Existing table, existing RLS policy: nothing new to
scope. Reversible: `downgrade()` drops both.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a9f5c1e7b4"
down_revision: str | Sequence[str] | None = "c7e1a4d9b2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column("placed_by_person", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_calls_placed_by_person",
        "calls",
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("placed_by_person"),
    )


def downgrade() -> None:
    op.drop_index("ix_calls_placed_by_person", table_name="calls")
    op.drop_column("calls", "placed_by_person")
