"""an account a super admin made paid without a payment

Revision ID: e3b9d5f1a827
Revises: d1a7c3e9f246
Create Date: 2026-10-26 02:00:00.000000

D-890 (founder, 26 Oct 2026): a super admin may make any client account paid with no
payment behind it, whatever state its trial is in. `organizations.first_paid_via` gains
`complimentary` beside `operator_conversion` (a trial converted for an account invoiced
outside the wallet), so the two stay distinguishable on every report, and
`organizations.first_paid_reason` keeps the super admin's own words: `audit_log` records who
and what, never the words.

The constraint is re-added NOT VALID, as `b5d8f2a9c741` did: every existing value is in
the old set, so there is nothing to validate and no reason to scan `organizations` under a
lock. The downgrade restores the old list the same way; a `complimentary` row written in
between is left as it is rather than rewritten as something it was not.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b9d5f1a827"
down_revision: str | None = "d1a7c3e9f246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `tenancy.models.FIRST_PAID_VIA`, frozen at this revision.
_BEFORE = ("wallet_topup", "manual_topup", "before_d697", "operator_conversion")
_AFTER = (*_BEFORE, "complimentary")
_CK = "ck_organizations_first_paid_via_enum"


def _paid_via(values: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {_CK} "
        f"CHECK (first_paid_via IS NULL OR first_paid_via IN ({listed})) NOT VALID"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _paid_via(_AFTER)
    op.add_column("organizations", sa.Column("first_paid_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("organizations", "first_paid_reason")
    _paid_via(_BEFORE)
