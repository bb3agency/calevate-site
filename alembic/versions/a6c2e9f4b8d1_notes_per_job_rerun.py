"""re-run the per-job "What it notes" and lead-suggestion copies with `organizations` readable

`e2a7c4f9b1d3` (D-1028) and `f3b8d2a6c1e4` (D-1029) each walked tenants one at a time under
that tenant's `app.tenant_id`, which is right for the writes, but listed the tenants with
`SELECT id FROM organizations` BEFORE any tenant was set. `organizations` is FORCE-RLS'd and
fail-closed on an unset tenant, so where the owner role is bound by RLS (production) the list
was empty and neither copy ran: production showed an inbound line whose "What it notes" list
stayed empty while its agent's list had fields, so its calls noted nothing.

The same copies, with only the tenant list read under a `NO FORCE` bracket on
`organizations`; every write runs under its own tenant's policy and names its tenant.

* What it notes: only a campaign or line whose list is still empty, from its agent's current
  list, as `e2a7c4f9b1d3` did. A list the owner has set since is left alone.
* Suggestions: only a job that has none of its own yet (no suggestions, no pass state and
  nothing dismissed), so a pass that has run on the job since is never overwritten.

DOWNGRADE changes no data: the copies cannot be told apart from lists the owner saved
afterwards.

Revision ID: a6c2e9f4b8d1
Revises: e8a3c5f1b927
Create Date: 2026-11-23 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "a6c2e9f4b8d1"
down_revision: str | None = "e8a3c5f1b927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

_FIELDS = {
    table: sa.text(
        f"UPDATE {table} j SET extraction_fields = es.fields "
        "FROM agents a JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
        "WHERE j.tenant_id = :t AND a.id = j.agent_id AND j.archived_at IS NULL "
        "AND jsonb_array_length(j.extraction_fields) = 0 "
        "AND jsonb_typeof(es.fields) = 'array' AND jsonb_array_length(es.fields) > 0"
    )
    for table in ("campaigns", "inbound_lines")
}

_SUGGESTIONS = {
    table: sa.text(
        f"UPDATE {table} j SET field_suggestions = a.field_suggestions, "
        "field_suggestions_dismissed = a.field_suggestions_dismissed, "
        "field_suggestions_state = CASE WHEN a.field_suggestions IS NULL THEN NULL "
        "ELSE 'done' END, "
        "field_suggestions_at = a.field_suggestions_at "
        "FROM agents a "
        "WHERE j.tenant_id = :t AND a.id = j.agent_id AND j.archived_at IS NULL "
        "AND j.field_suggestions IS NULL AND j.field_suggestions_state IS NULL "
        "AND jsonb_array_length(j.field_suggestions_dismissed) = 0 "
        "AND (a.field_suggestions IS NOT NULL "
        "OR jsonb_array_length(a.field_suggestions_dismissed) > 0)"
    )
    for table in ("campaigns", "inbound_lines")
}


def _tenants(bind: sa.Connection) -> list[object]:
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    try:
        return list(bind.execute(sa.text("SELECT id FROM organizations ORDER BY id")).scalars())
    finally:
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    if probe_skipped_offline(
        "a6c2e9f4b8d1: the per-job notes and suggestion copies were NOT re-run (needs a "
        "connection); upgrade online to run them"
    ):
        return
    op.execute("SET LOCAL lock_timeout = '3s'")
    bind = op.get_bind()
    entry = bind.execute(sa.text("SELECT current_setting('app.tenant_id', true)")).scalar()
    fields = suggestions = 0
    try:
        for tenant_id in _tenants(bind):
            bind.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            for statement in _FIELDS.values():
                fields += bind.execute(statement, {"t": tenant_id}).rowcount
            for statement in _SUGGESTIONS.values():
                suggestions += bind.execute(statement, {"t": tenant_id}).rowcount
    finally:
        bind.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": entry or ""})
    log.info("per-job copies under RLS: %s lists, %s suggestion sets", fields, suggestions)


def downgrade() -> None:
    """Deliberately empty; see the docstring."""
