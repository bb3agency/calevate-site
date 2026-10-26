"""outbound webhook deliveries retry on a persisted schedule; endpoint secrets rotate in place

Revision ID: d5f1a3c7e902
Revises: e5b1d9c3a7f2
Create Date: 2026-10-26 17:00:00.000000

1. `webhook_deliveries.next_attempt_at` and `outbox_message_id`: a webhook delivery that
   failed transiently waits as `status = 'retrying'` until `next_attempt_at`, when the
   `retry_outbound_deliveries` sweep re-enqueues it from the outbox message that still
   holds its body. A schedule of about a day cannot live in arq's queue (a ten-hour
   deferred job is lost with Redis and blocks nothing), so the wait is a row.
2. `outbound_webhooks.previous_secret_ref` and `previous_secret_expires_at`: during a
   rotation window both secrets sign every delivery, as `inbound_webhooks` already holds
   its retiring secret. Both NULL or both set.

No RLS change: `outbound_webhooks` keeps its FORCEd tenant policy, and `webhook_deliveries`
stays scoped through it (migration 4be32bf3d12c). Nullable, no backfill: NULL means "not
waiting" and "no retiring secret", which is what every existing row would say.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5f1a3c7e902"
down_revision: str | None = "e5b1d9c3a7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "webhook_deliveries",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("outbox_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_webhook_deliveries_retry_due",
        "webhook_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'retrying'"),
    )
    op.add_column("outbound_webhooks", sa.Column("previous_secret_ref", sa.Text(), nullable=True))
    op.add_column(
        "outbound_webhooks",
        sa.Column("previous_secret_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_outbound_webhooks_previous_secret_paired"),
        "outbound_webhooks",
        "(previous_secret_ref IS NULL) = (previous_secret_expires_at IS NULL)",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(
        op.f("ck_outbound_webhooks_previous_secret_paired"), "outbound_webhooks", type_="check"
    )
    op.drop_column("outbound_webhooks", "previous_secret_expires_at")
    op.drop_column("outbound_webhooks", "previous_secret_ref")
    op.drop_index("ix_webhook_deliveries_retry_due", table_name="webhook_deliveries")
    op.drop_column("webhook_deliveries", "outbox_message_id")
    op.drop_column("webhook_deliveries", "next_attempt_at")
