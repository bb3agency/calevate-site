"""the retained delivery body gets a clock the sweep can read

Revision ID: b3d61f0a97c4
Revises: c7e1a4b90d63
Create Date: 2026-08-14 09:10:00.000000

`webhook_deliveries.payload_ref` has existed since the core migration and nothing ever
wrote it (`scripts/check_wiring.UNWIRED_BASELINE` carried it: "the body is not retained
yet"). It now holds the object-storage key of the CRM payload we POSTed to a client's
endpoint, which makes it the first personal data this table points at — and personal data
needs a mechanism that expires it, not just a column that holds it.

`apps/workers/retention.py` gained that mechanism: the `lead` category's sweep selects
expired deliveries that still carry a reference, deletes the objects, and clears the
column. NO SCHEMA CHANGE IS NEEDED for that; the column and the FK to `outbound_webhooks`
(which is how a table with no RLS policy of its own gets tenant-scoped, see the model
docstring) were already there. What is needed is an INDEX, because that sweep runs
nightly for every tenant and its predicate — "rows with a reference, oldest first" — is
otherwise a sequential scan over a table that gains a row per delivered lead forever.

PARTIAL, on the predicate itself: rows with no retained body are the overwhelming
majority over time (every sweep clears one, and no row ever regains one), so an index
over all of them would be mostly dead weight and would have to be maintained on every
delivery write. `WHERE payload_ref IS NOT NULL` keeps only the rows the sweep can act on
— Postgres uses a partial index only when the query's predicate implies the index's, and
both the sweep's SELECT and the probe's EXISTS state exactly this one.

Reversible and content-free: an index create and drop touch no rows, so a downgrade
leaves every retained body and every reference exactly where it was.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d61f0a97c4"
down_revision: str | Sequence[str] | None = "c7e1a4b90d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_webhook_deliveries_retained_body"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "webhook_deliveries",
        ["created_at"],
        unique=False,
        # `created_at`, not `last_at`: the body is what we SENT, and a retry three days
        # later does not make the payload younger. The sweep orders by the same column.
        postgresql_where=sa.text("payload_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="webhook_deliveries")
