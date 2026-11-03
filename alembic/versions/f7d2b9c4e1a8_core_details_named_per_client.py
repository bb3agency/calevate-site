"""organizations: each client's own names for the core lead details

Revision ID: f7d2b9c4e1a8
Revises: e3c7a1f9b542
Create Date: 2026-11-03

Every lead carries the same six core details (`calevate_shared.lead_fields.CORE_LEAD_FIELDS`)
so the caller notice, the one phone-holding field and every reader share one meaning. What a
client READS them as is now theirs: `core_field_labels` maps a core key to the name shown on
that client's screens ("What they want" may read "Crop issue"). The key and the instruction
the extraction model reads never change. The names are drafted once for the business
(`workers/core_labels.name_core_details`) and the owner may change any of them.

`core_labels_drafted_at` records that the one draft was taken, so it is never asked again.

`organizations` already carries FORCEd row-level security; columns add no policy. The CHECK
is added NOT VALID and then validated, so the brief ACCESS EXCLUSIVE does not wait on a scan.

Data: one `name_core_details` outbox message per live account whose business profile lists
what it sells, so existing clients get names drafted too; the worker does nothing for an
account whose owner has already named any detail. DOWNGRADE drops both columns; the names
are display only, so nothing captured is lost.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from apps.api.db.migration_offline import execute_data_statement

revision: str = "f7d2b9c4e1a8"
down_revision: str | None = "e3c7a1f9b542"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

# Spelled out rather than imported: a migration is a snapshot.
JOB = "name_core_details"
_CK = "ck_organizations_core_field_labels_is_object"

QUEUE = (
    "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, created_at, "
    "updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object('tenant_id', o.id::text), "
    "'pending', 0, now(), now() FROM organizations o JOIN business_profiles bp "
    "ON bp.tenant_id = o.id WHERE o.deleted_at IS NULL "
    "AND jsonb_array_length(bp.services) > 0"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column(
            "core_field_labels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("core_labels_drafted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {_CK} "
        "CHECK (jsonb_typeof(core_field_labels) = 'object') NOT VALID"
    )
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_CK}")
    # The FORCE bracket (`f4a2c7e19d63`): both tables are FORCE-RLS'd, so without it the
    # owner's read matches no rows and nothing is queued.
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE business_profiles NO FORCE ROW LEVEL SECURITY")
    queued = execute_data_statement(
        sa.text(QUEUE).bindparams(job=JOB),
        note="Queued the core-detail naming job for accounts with a business profile.",
    )
    log.info("core detail names: %s account(s) queued", queued)
    op.execute("ALTER TABLE business_profiles FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_CK}")
    op.drop_column("organizations", "core_labels_drafted_at")
    op.drop_column("organizations", "core_field_labels")
