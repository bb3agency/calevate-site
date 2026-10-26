"""organizations: the client's own low-balance warning line

Revision ID: f1a6c3e9d204
Revises: e5c1a9d3f720
Create Date: 2026-10-26 20:00:00.000000

`organizations.low_balance_alert_inr` (D-893 lane L6): the rupee balance below which the
client is warned that credit is running low. NULL follows Calevate's line
(`billing.service.LOW_BALANCE_INR`, ₹200), so no row is backfilled and nobody's warning
moves until they choose. 0 switches the low warning off; the empty-wallet warning does not
read this column.

`organizations` already carries FORCEd row-level security; a column adds no policy. The
CHECK is added NOT VALID and then validated, so the brief ACCESS EXCLUSIVE does not wait on a
scan; `lock_timeout` bounds the wait. Downgrade drops the constraint and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a6c3e9d204"
down_revision: str | None = "e5c1a9d3f720"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from the models: a migration is a snapshot.
_CK = "ck_organizations_low_balance_alert_range"
_CK_SQL = (
    "low_balance_alert_inr IS NULL OR "
    "(low_balance_alert_inr >= 0 AND low_balance_alert_inr <= 100000.00)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column("low_balance_alert_inr", sa.Numeric(12, 2), nullable=True),
    )
    op.execute(f"ALTER TABLE organizations ADD CONSTRAINT {_CK} CHECK ({_CK_SQL}) NOT VALID")
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_CK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_CK}")
    op.drop_column("organizations", "low_balance_alert_inr")
