"""A campaign tests a second opening line against its script's own (D-992)

Revision ID: f3c8d1a6b2e4
Revises: e2b7c4d9a1f3
Create Date: 2026-11-15 18:00:00.000000

* `campaigns.opening_b`: the second opening line, or NULL when no test runs.
* `campaign_contacts.opening_variant`: which opening this person's calls used (`a`, the
  script's own, or `b`), so goals reached can be counted per opening.

Additive. `downgrade()` drops both columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c8d1a6b2e4"
down_revision: str | None = "e2b7c4d9a1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("campaigns", sa.Column("opening_b", sa.Text(), nullable=True))
    op.add_column(
        "campaign_contacts", sa.Column("opening_variant", sa.String(1), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_campaign_contacts_opening_variant_enum"),
        "campaign_contacts",
        "opening_variant IS NULL OR opening_variant IN ('a', 'b')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(
        op.f("ck_campaign_contacts_opening_variant_enum"), "campaign_contacts", type_="check"
    )
    op.drop_column("campaign_contacts", "opening_variant")
    op.drop_column("campaigns", "opening_b")
