"""the dial gate's consent read and the complaint-spike count get indexes

Revision ID: e95e0d780629
Revises: f39583a282fb
Create Date: 2026-09-26 12:00:00.000000

Two reads on `consent_ledger` ran as whole-table scans:

* `compliance.service._latest_call_consent` — the newest `callback` row for one
  (tenant, phone), read on every dial and every call-back booking. The `messaging` purpose
  has had this index since c2f7a91b4e63; `callback` never did. Ordered as the query orders
  (`captured_at DESC, id DESC`), so the `LIMIT 1` is a single index probe.
* `campaigns.complaint_spike` — "was this call followed by a withdrawal", an EXISTS per
  completed call, per running campaign, per dispatch tick. Partial on `withdrawn`, the only
  status it asks about, so the index holds opt-outs and nothing else.

Measured on 200k outbound calls and 502k ledger rows for one tenant: the per-dial lookup
went from 61 ms to 0.05 ms and the campaign-spike query from 463 ms to 79 ms.

Plain CREATE INDEX inside the migration's transaction rather than CONCURRENTLY: the ledger
holds no client rows yet, and CONCURRENTLY cannot run inside the transaction alembic opens.
"""

from alembic import op

revision: str = "e95e0d780629"
down_revision: str | None = "f39583a282fb"
branch_labels: None = None
depends_on: None = None

TABLE = "consent_ledger"
IX_CALL_CONSENT = "ix_consent_ledger_callback_lookup"
IX_WITHDRAWN_BY_CALL = "ix_consent_ledger_withdrawn_call"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        f"CREATE INDEX {IX_CALL_CONSENT} ON {TABLE} "
        "(tenant_id, phone_e164, captured_at DESC, id DESC) "
        "WHERE purpose = 'callback'"
    )
    op.execute(
        f"CREATE INDEX {IX_WITHDRAWN_BY_CALL} ON {TABLE} (call_id) "
        "WHERE status = 'withdrawn' AND call_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {IX_WITHDRAWN_BY_CALL}")
    op.execute(f"DROP INDEX IF EXISTS {IX_CALL_CONSENT}")
