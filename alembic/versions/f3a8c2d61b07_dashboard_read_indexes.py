"""indexes for the dashboard reads that scanned a tenant's whole call or lead history

Each serves one query measured on a 60k-call / 15k-lead tenant (29 Oct 2026 API lane):
- `ix_calls_tenant_call_at`: the call log's page order and date filters, which sort on
  `crm/lens.CALL_AT` = COALESCE(started_at, created_at), an expression no existing index has.
- `ix_calls_needs_you`: `tenancy/setup_nudges._NEEDS_YOU_SQL`, behind `/v1/business-profile`.
- `ix_leads_tenant_created`: analytics' `_LEADS_IN_RANGE` and the dashboard's new-lead counts.
- `ix_calls_lead_id`: `crm/captured.py` reads a lead's calls by `lead_id`.

Plain CREATE INDEX, not CONCURRENTLY: no migration here runs outside a transaction and the
tables are small before launch; `lock_timeout` stops a busy table from stalling the deploy.

Revision ID: f3a8c2d61b07
Revises: e6b2d9f4a718
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f3a8c2d61b07"
down_revision: str | None = "e6b2d9f4a718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_calls_tenant_call_at",
        "CREATE INDEX ix_calls_tenant_call_at ON calls "
        "(tenant_id, (COALESCE(started_at, created_at)) DESC, id DESC)",
    ),
    (
        "ix_calls_needs_you",
        "CREATE INDEX ix_calls_needs_you ON calls "
        "(tenant_id, (COALESCE(ended_at, created_at))) WHERE outcome_tag = 'needs_you'",
    ),
    (
        "ix_leads_tenant_created",
        "CREATE INDEX ix_leads_tenant_created ON leads (tenant_id, created_at) "
        "WHERE deleted_at IS NULL",
    ),
    (
        "ix_calls_lead_id",
        "CREATE INDEX ix_calls_lead_id ON calls (lead_id) WHERE lead_id IS NOT NULL",
    ),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for _name, ddl in _INDEXES:
        op.execute(ddl)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name, _ddl in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
