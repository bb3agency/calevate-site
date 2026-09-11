"""audit_log.via_grant_id: which view-as session an act came through

Revision ID: d7a4c2e91b83
Revises: c3d91f0a5b74
Create Date: 2026-09-11

**WHY THIS COLUMN EXISTS (D-587, supersedes D-22).** D-22 made "view as client"
READ-ONLY, and its stated reason was the audit trail: no acting-as, so no dual
attribution, so every row in `audit_log` unambiguously names who decided. D-587 reverses
the read-only half — an operator on a support call must be able to fix the account they
are looking at — which means the ambiguity D-22 designed around is now reachable and has
to be closed by RECORDING rather than by refusing.

Two of the three facts were already in the row and always had been: `actor_id` is
`Principal.user_id`, which is an `admin_users.id` for an operator, and `actor_type` is
`admin`. What was missing is the third — that the act was performed INSIDE a client's
session rather than from the operator console — and, with it, WHICH session. This column
is the grant's `jti`, so an investigator joins the write to the one
`admin.impersonation_started` row naming who entered that tenant, when, and from what
address.

**NULLABLE, AND NO BACKFILL IS POSSIBLE OR WANTED.** Every existing row was written when
no impersonated write could happen, so NULL is not "unknown" here — it is the true and
complete statement "this act did not come through a view-as session". A default would
have invented a session for a decade of rows.

**NOT AN FK.** A grant is a signed token and there is no `impersonation_grants` table;
`apps/api/core/impersonation.py` argues at length why adding one would close nothing
(authority is re-read from `admin_users` on every request, so revocation is already
instant). A foreign key needs a referent, and the referent here is a log line plus a
hash-chained row, not a parent table.

**WHY ADDING IT DOES NOT DISTURB THE HASH CHAIN.** `audit_log` is INSERT-only (hard rule
4, `db/registry.APPEND_ONLY_TABLES`) with a trigger that raises on UPDATE and DELETE;
`ALTER TABLE ... ADD COLUMN` is neither, so the trigger is untouched and no existing row
is rewritten. `write_audit` puts `via_grant_id` into the hashed payload ONLY when it is
set, so a row with NULL hashes the exact payload shape it was signed with and
`verify_chain` keeps verifying the whole history unchanged.

**NO RLS.** `audit_log` is deliberately not tenant-RLS'd (`compliance/models.py`): the
admin realm reads it across tenants and that read is itself audited. This column changes
neither half, and `scripts/check_rls_coverage` reads the same exemption it already read.

**REVERSIBLE.** `downgrade` drops the column. That loses the attribution on any rows
written while it existed, which is the honest cost of the reversal and the reason the
code half must go with it — a deployment running D-587's `write_audit` against a table
without this column fails its INSERT, which is the correct direction (hard rule 5: an act
we cannot record is an act we do not perform).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d7a4c2e91b83"
down_revision = "c3d91f0a5b74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("via_grant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # The investigator's query is "everything that happened inside view-as session G", and
    # a partial index is the right shape for it: the overwhelming majority of rows are NULL
    # and an index that skipped them costs nothing to maintain on the ordinary write path.
    op.create_index(
        "ix_audit_log_via_grant",
        "audit_log",
        ["via_grant_id"],
        postgresql_where=sa.text("via_grant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_via_grant", table_name="audit_log")
    op.drop_column("audit_log", "via_grant_id")
