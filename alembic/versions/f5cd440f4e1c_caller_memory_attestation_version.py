"""organizations.caller_memory_attestation_version: which caller-memory statement was accepted

Revision ID: f5cd440f4e1c
Revises: d7c2e9a4f6b1
Create Date: 2026-10-27 20:00:00.000000

The statement an owner accepts to switch caller memory on said the agents tell callers "at
the start of every call"; since D-865 the agent says it as it says goodbye, and the founder
changed the statement to say so (27 Oct 2026). The text is versioned like the outbound
pledge: every account that accepted before this revision accepted version 1 and keeps it,
and new acceptances record version 2 (`agents/publishing.CALLER_MEMORY_ATTESTATIONS`).

Nullable: NULL means nobody has accepted. `organizations` carries FORCEd row-level security,
so the backfill runs inside a NO FORCE / FORCE bracket. Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "f5cd440f4e1c"
down_revision: str | None = "d7c2e9a4f6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_organizations_caller_memory_attestation_version"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column("caller_memory_attestation_version", sa.SmallInteger(), nullable=True),
    )
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {_CHECK} CHECK "
        "(caller_memory_attestation_version IS NULL OR caller_memory_attestation_version >= 1) "
        "NOT VALID"
    )
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    try:
        execute_data_statement(
            sa.text(
                "UPDATE organizations SET caller_memory_attestation_version = 1 "
                "WHERE caller_memory_attested_at IS NOT NULL"
            ),
            note="accounts that accepted the caller-memory statement are marked version 1",
        )
    finally:
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_CHECK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("organizations", "caller_memory_attestation_version")
