"""a refund claim records the provider refund it became, and fails instead of vanishing

Revision ID: e5c1a9d3f720
Revises: d5f1a3c7e902
Create Date: 2026-10-26 18:00:00.000000

A refund attempt that failed definitively was DELETEd from `refund_intents`, so the next
attempt of the same amount derived the same `X-Refund-Idempotency` key and Razorpay could
answer it with the failed refund. `failed_at` keeps the failed attempt (excluded from the
refund ceiling) and lets the next attempt count it and derive a new key. `refund_ref` is the
provider refund id the claim became, so a `refund.failed` webhook fails exactly that claim
and a late redelivery for an older attempt cannot fail a newer one.

Both nullable, no backfill: existing rows are live claims with no recorded refund id. No RLS
change: the table's tenant policy already covers every column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5c1a9d3f720"
down_revision: str | None = "d5f1a3c7e902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "refund_intents", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("refund_intents", sa.Column("refund_ref", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("refund_intents", "refund_ref")
    op.drop_column("refund_intents", "failed_at")
