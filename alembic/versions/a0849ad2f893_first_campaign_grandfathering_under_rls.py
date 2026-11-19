"""re-run c4d9e18a72b6's first-campaign grandfathering inside the RLS bracket

`c4d9e18a72b6` created `first_campaign_reviews` and, before its policy existed, inserted an
approved row for every self-serve or trial account that had already launched a campaign. The
INSERT read `organizations` and `campaigns`, both FORCE-RLS'd, so wherever the owner role is
subject to RLS (production, DEPLOYMENT §9.3a) it read no rows and inserted none: those accounts
were sent to a first-campaign review their earlier launches should have spared them.

The same statement, bracketed. `ON CONFLICT (tenant_id) DO NOTHING` keeps every row written
since (a review asked for, approved or refused stays as it is), and on a deployment where the
original ran (a superuser owner) every grandfathered row already exists, so this is a no-op
there.

DOWNGRADE deletes nothing: which rows the original would have written cannot be told apart
from these, and removing one would send that account back to a review it was spared.

Revision ID: a0849ad2f893
Revises: f2477c8d623d
Create Date: 2026-11-19 22:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "a0849ad2f893"
down_revision: str | None = "f2477c8d623d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: `c4d9e18a72b6`'s own values, copied: a migration is a snapshot.
_SELF_SERVE_TIERS = "('self_serve', 'trial')"
_GRANDFATHERED = (
    "Grandfathered by migration c4d9e18a72b6: this account launched a campaign before "
    "the first-campaign review existed, so its first campaign cannot be reviewed now."
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE campaigns NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE first_campaign_reviews NO FORCE ROW LEVEL SECURITY")
    try:
        inserted = execute_data_statement(
            sa.text(
                "INSERT INTO first_campaign_reviews (id, tenant_id, status, decision_note, "
                "  decision_source, decided_by_admin_id, decided_at, created_at, updated_at) "
                "SELECT gen_random_uuid(), o.id, 'approved', :note, 'migration_backfill', NULL, "
                "  now(), now(), now() "
                "FROM organizations o "
                f"WHERE o.plan_tier IN {_SELF_SERVE_TIERS} AND EXISTS ("
                "  SELECT 1 FROM campaigns c WHERE c.tenant_id = o.id "
                "  AND c.launched_at IS NOT NULL"
                ") ON CONFLICT (tenant_id) DO NOTHING"
            ).bindparams(note=_GRANDFATHERED),
            note="Grandfathered the accounts c4d9e18a72b6's backfill missed.",
        )
        log.info("first campaign grandfathering under RLS: %s accounts", inserted)
    finally:
        op.execute("ALTER TABLE first_campaign_reviews FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE campaigns FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Deliberately empty; see the docstring."""
