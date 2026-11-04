"""organizations: the business profile's labels, hints and examples for each business

Revision ID: c3f8a1d6e9b4
Revises: b7e3d9a2c5f1
Create Date: 2026-11-04

`profile_wording` holds what the business profile's form says for this business: what it
calls what it offers, whether a price applies and what it is called, how a caller goes
ahead, and the example inside each empty field (`tenancy/profile_wording`), with the digest
of the description it was written from. Written by `workers/profile_wording`; `{}` shows the
neutral wording.

`organizations` already carries FORCEd row-level security; a column adds no policy. The
CHECK is added NOT VALID and then validated, so the brief ACCESS EXCLUSIVE does not wait on
a scan.

No data: an account gets its draft queued the first time its profile is read
(`profile_wording.read_wording`). DOWNGRADE drops the column; it is display only, and the
profile itself is untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3f8a1d6e9b4"
down_revision: str | None = "b7e3d9a2c5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = "ck_organizations_profile_wording_is_object"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column(
            "profile_wording",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {_CK} "
        "CHECK (jsonb_typeof(profile_wording) = 'object') NOT VALID"
    )
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_CK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_CK}")
    op.drop_column("organizations", "profile_wording")
