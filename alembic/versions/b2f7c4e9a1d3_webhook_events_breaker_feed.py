"""webhook failure events, the breaker that holds and replays, test deliveries, events feed (D-1049)

Revision ID: b2f7c4e9a1d3
Revises: e8b4d1f6a2c9
Create Date: 2026-11-28

`outbound_webhooks` gains four columns:

* `auto_subscribe_new_events` — an endpoint registered with `*` also receives event types
  added after it was registered. Off by default: `*` alone is expanded to the events that
  exist at registration, because every event is a payload promise a receiver has to be
  ready for.
* `paused_at` / `failing_since` — the breaker. An endpoint whose every delivery has failed
  for 72 hours is paused, not deactivated: new deliveries are held (`webhook_deliveries.
  status = 'held'`) and replayed in order on Resume. `failing_since` is the first failure
  of the streak, so Resume can also replay what failed inside it.
* `managed_by_key_id` — the API key that created the endpoint through `/api/v1`, NULL for
  one a person created. No foreign key: the keys table is added by a sibling migration.

`webhook_deliveries.is_test` marks a test delivery (`POST …/endpoints/{id}/test`), which
the log shows as a test and the breaker never counts.

Two new tenant tables, FORCEd RLS in this migration (hard rule 1):

* `integration_events` — one row per event at fan-out, the pull feed's source. Rows are
  never updated (trigger) but ARE deleted: by the 30-day sweep and by a data principal's
  erasure. That is why the table is not in `APPEND_ONLY_TABLES`, whose trigger cover must
  refuse DELETE. `txid` is the inserting transaction's id: the feed serves only rows whose
  transaction is older than every transaction still running, so a consumer's cursor never
  passes an event that commits later with an earlier position.
* `integration_event_cursors` — one durable position per consumer (an API key).

Reversible: `downgrade()` drops both tables and the five columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2f7c4e9a1d3"
down_revision: str | Sequence[str] | None = "e8b4d1f6a2c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENTS = "integration_events"
CURSORS = "integration_event_cursors"
_TXID = "(pg_current_xact_id()::text)::bigint"


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "outbound_webhooks",
        sa.Column(
            "auto_subscribe_new_events", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column("outbound_webhooks", sa.Column("paused_at", sa.DateTime(timezone=True)))
    op.add_column("outbound_webhooks", sa.Column("failing_since", sa.DateTime(timezone=True)))
    op.add_column("outbound_webhooks", sa.Column("managed_by_key_id", sa.UUID()))
    op.add_column(
        "webhook_deliveries",
        sa.Column("is_test", sa.Boolean(), server_default="false", nullable=False),
    )
    # The breaker's per-endpoint read uses `ix_webhook_deliveries_endpoint_recent`.

    op.create_table(
        EVENTS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=True),
        sa.Column("call_id", sa.UUID(), nullable=True),
        sa.Column("txid", sa.BigInteger(), server_default=sa.text(_TXID), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{EVENTS}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{EVENTS}")),
    )
    op.create_index(f"ix_{EVENTS}_feed", EVENTS, ["tenant_id", "txid", "id"])
    op.create_index(f"ix_{EVENTS}_created_at", EVENTS, ["created_at"])
    op.create_index(
        f"ix_{EVENTS}_lead_id", EVENTS, ["lead_id"], postgresql_where=sa.text("lead_id IS NOT NULL")
    )
    op.create_index(
        f"ix_{EVENTS}_call_id", EVENTS, ["call_id"], postgresql_where=sa.text("call_id IS NOT NULL")
    )
    _tenant_policy(EVENTS)
    # Never rewritten: what an event said is what every consumer of it was told.
    op.execute(
        f"CREATE TRIGGER {EVENTS}_no_update BEFORE UPDATE ON {EVENTS} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(f"ALTER TABLE {EVENTS} ENABLE ALWAYS TRIGGER {EVENTS}_no_update")

    op.create_table(
        CURSORS,
        sa.Column("consumer_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("after_txid", sa.BigInteger(), nullable=True),
        sa.Column("after_event_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "(after_txid IS NULL) = (after_event_id IS NULL)",
            name=op.f(f"ck_{CURSORS}_position_paired"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{CURSORS}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("consumer_id", name=op.f(f"pk_{CURSORS}")),
    )
    op.create_index(f"ix_{CURSORS}_tenant_id", CURSORS, ["tenant_id"])
    _tenant_policy(CURSORS)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(CURSORS)
    op.drop_table(EVENTS)
    op.drop_column("webhook_deliveries", "is_test")
    op.drop_column("outbound_webhooks", "managed_by_key_id")
    op.drop_column("outbound_webhooks", "failing_since")
    op.drop_column("outbound_webhooks", "paused_at")
    op.drop_column("outbound_webhooks", "auto_subscribe_new_events")
