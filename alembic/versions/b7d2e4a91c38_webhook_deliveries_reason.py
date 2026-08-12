"""webhook_deliveries.reason — a failed delivery says what a client can fix

Revision ID: b7d2e4a91c38
Revises: f1a7c39d5be2
Create Date: 2026-08-12 18:00:00.000000

`webhook_deliveries` recorded WHETHER a delivery failed and, through `source`, the HTTP
status when there was one. For the webhook half of D-23 that is nearly enough:
`http_404` on the client's own delivery screen points at their endpoint.

For the Google Sheets half it says nothing. A sheets append has no status code, so
`source` is the bare string `sheets` for every failure — a missing service-account
credential, a document the client never shared with us, a tab they renamed, and a Google
outage all land as the same word. The needs-attention queue could therefore only tell a
client "your endpoint answered an error", which is not actionable and, for a sheet, is
not even true: nothing answered, we refused before calling.

This column carries the reason in OUR vocabulary — the authored codes in
`apps/workers/sheets_sync.py` and `apps/workers/google_sheets.py`, or an exception type.
NEVER vendor prose: a provider's error string is untrusted text that may quote the row
we just handed it, and this column is read by a client-facing screen (hard rule 6).

NO RLS POLICY, deliberately and consistently with the rest of this table. Migration
4be32bf3d12c records the argument: engine webhooks arrive before a tenant is resolved,
so `webhook_deliveries` carries no `tenant_id`, and every client-facing read of it is
scoped THROUGH `outbound_webhooks` — which IS tenant-RLS'd — rather than by policy. This
column changes nothing about that: `apps/api/crm/attention.py` and
`apps/api/integrations/routes.py` both reach it via a join to `outbound_webhooks`, and
`tests/sheets_adapter_test.py` holds a cross-tenant zero-rows test on exactly that path.

Reversible, and safe in both directions: a nullable TEXT add takes no table rewrite on
PG16, and the downgrade drops a column nothing else references.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2e4a91c38"
down_revision: str | None = "f1a7c39d5be2"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("webhook_deliveries", sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("webhook_deliveries", "reason")
