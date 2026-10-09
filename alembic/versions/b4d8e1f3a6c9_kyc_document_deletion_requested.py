"""A KYC file's deletion is requested before it is done (D-692 follow-up)

Revision ID: b4d8e1f3a6c9
Revises: d93b6f2a4c18
Create Date: 2026-10-09 12:00:00.000000

`kyc_documents.purged_at` used to be stamped in the transaction that DECIDED a file should
go (a reviewer's approve/reject, a replacement upload), and the object was deleted
afterwards by a background task that only logged a failure. A failed delete therefore left
a row reading "deleted" over a file still in the bucket, and the nightly purge, which
selects `purged_at IS NULL`, never saw it again.

`delete_requested_at` is the decision; `purged_at` is now only ever written after the
object delete succeeded. A row with the first and not the second is a file we have
promised to delete and have not yet: `workers/kyc_owner_id_purge` retries it every night,
whatever its age, and alarms when a night's attempts give up.

The backfill stamps `delete_requested_at = purged_at` on rows already marked purged, so the
CHECK "purged implies requested" holds for every row. The `NO FORCE` / `FORCE` bracket is
`a4f7d20c81be`'s: `kyc_documents` is FORCE RLS and the owner would otherwise update nothing.

The untenanted read arm the purge uses widens from "held owner-ID rows" to "held rows that
are owner IDs or whose deletion was requested", so a superseded business certificate whose
delete failed is retried too. Writes stay strict.

DOWNGRADE drops the column and restores the narrower read arm. A row requested and not yet
purged is then a held file the downgraded sweep no longer retries (an owner ID is still
caught by its 30-day hold; a superseded business certificate is not until the account is
erased).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d8e1f3a6c9"
down_revision: str | None = "d93b6f2a4c18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNTENANTED = "NULLIF(current_setting('app.tenant_id', true), '') IS NULL"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "kyc_documents",
        sa.Column("delete_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("ALTER TABLE kyc_documents NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE kyc_documents SET delete_requested_at = purged_at "
            "WHERE purged_at IS NOT NULL AND delete_requested_at IS NULL"
        )
    finally:
        op.execute("ALTER TABLE kyc_documents FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE kyc_documents ADD CONSTRAINT ck_kyc_documents_purged_after_requested "
        "CHECK (purged_at IS NULL OR delete_requested_at IS NOT NULL) NOT VALID"
    )
    op.execute(
        "ALTER TABLE kyc_documents VALIDATE CONSTRAINT ck_kyc_documents_purged_after_requested"
    )
    op.execute("DROP POLICY kyc_documents_owner_id_purge_read ON kyc_documents")
    op.execute(
        f"CREATE POLICY kyc_documents_owner_id_purge_read ON kyc_documents FOR SELECT "
        f"USING ({_UNTENANTED} AND purged_at IS NULL "
        f"AND (slot = 'owner_id' OR delete_requested_at IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY kyc_documents_owner_id_purge_read ON kyc_documents")
    op.execute(
        f"CREATE POLICY kyc_documents_owner_id_purge_read ON kyc_documents FOR SELECT "
        f"USING ({_UNTENANTED} AND slot = 'owner_id' AND purged_at IS NULL)"
    )
    op.execute(
        "ALTER TABLE kyc_documents DROP CONSTRAINT ck_kyc_documents_purged_after_requested"
    )
    op.drop_column("kyc_documents", "delete_requested_at")
