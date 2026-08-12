"""outbound webhook deliveries name their endpoint

Revision ID: 4be32bf3d12c
Revises: e16c96e68bc5
Create Date: 2026-08-11 01:14:44.806142

`webhook_deliveries` is deliberately NOT tenant-RLS'd: engine webhooks land before the
tenant is resolved, so a policy keyed on `app.tenant_id` would reject exactly the rows
that exist to prove an unresolvable event arrived (see the model docstring).

That leaves the D-23 delivery screen — "did my CRM get it?" — with no way to scope
outbound rows to the asking tenant. `endpoint_id` is that way, and it is the honest
one: the client's query filters `endpoint_id IN (SELECT id FROM outbound_webhooks)`,
and `outbound_webhooks` IS tenant-RLS'd, so the isolation is enforced by an existing
policy rather than by a new column anyone must remember to filter on. Nullable, because
inbound rows have no endpoint and never will.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4be32bf3d12c"
down_revision: str | None = "e16c96e68bc5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column("endpoint_id", sa.Uuid(), nullable=True),
    )
    # ondelete SET NULL, not CASCADE: deleting a config row must not erase the record
    # that we attempted deliveries against it (SEC-COMP §5's forensic half).
    op.create_foreign_key(
        "fk_webhook_deliveries_endpoint_id_outbound_webhooks",
        "webhook_deliveries",
        "outbound_webhooks",
        ["endpoint_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # The delivery screen reads newest-first for one tenant's endpoints.
    op.create_index(
        "ix_webhook_deliveries_endpoint_recent",
        "webhook_deliveries",
        ["endpoint_id", sa.text("last_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_endpoint_recent", table_name="webhook_deliveries")
    op.drop_constraint(
        "fk_webhook_deliveries_endpoint_id_outbound_webhooks",
        "webhook_deliveries",
        type_="foreignkey",
    )
    op.drop_column("webhook_deliveries", "endpoint_id")
