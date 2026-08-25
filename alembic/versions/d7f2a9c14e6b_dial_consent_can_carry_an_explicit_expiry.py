"""dial consent can carry an explicit expiry

Revision ID: d7f2a9c14e6b
Revises: f4b1e9a2c7d0
Create Date: 2026-08-24 00:00:00.000000

`compliance/service.check_dispatch` read the latest `callback` consent and refused only on
its STATUS, never on any expiry — while the messaging leg (`compliance/consent.py`) already
honours an expiry. This adds the column the dial gate needs to close that asymmetry: a
NULLABLE `expires_at` on `consent_ledger` carrying an EXPLICIT end-date the capturing record
set.

Nullable, and that is the whole design: an absent value means "no stated expiry", NOT
"expired", so every consent row written before this migration keeps working unchanged and
the gate imposes no default validity window on them (a default window for voice consent is
counsel's call — LEGAL-OPS-PLAYBOOK §10.7/§20, hard rule 11). The gate refuses only a
consent whose row carries an `expires_at` already in the past.

`consent_ledger` is append-only (hard rule 4): this is an additive DDL column, no row is
updated, and the `consent_ledger_append_only` trigger and the table's RLS are untouched
(both are table-level, unaffected by an ADD COLUMN). Reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7f2a9c14e6b"
down_revision: str | None = "f4b1e9a2c7d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consent_ledger",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("consent_ledger", "expires_at")
