"""Blind voice comparison rounds (D-946): Cartesia and Sarvam own-key voices, rated blind

Revision ID: d946a1b2c3e4
Revises: a8d3f1c6e2b9
Create Date: 2026-11-01 12:00:00.000000

Two platform tables, no `tenant_id` and no policy: the voices are our own provider accounts'
and the listener is an operator, so no client's row could be here
(`db/registry.RLS_EXEMPT_TENANT_COLUMNS` carries the reason `check_rls_coverage` reads).
Trials go with their round (`ON DELETE CASCADE`); nothing deletes a round today.

REVERSIBILITY. `downgrade()` drops both tables, and with them every rating. They are a
listening test's results, exported as CSV from the page, not a ledger.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d946a1b2c3e4"
down_revision: str | None = "a8d3f1c6e2b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROUNDS = "platform_voice_comparison_rounds"
TRIALS = "platform_voice_comparison_trials"


def upgrade() -> None:
    op.create_table(
        ROUNDS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("voices", postgresql.JSONB(), nullable=False),
        sa.Column("sentences", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cartesia_chars", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("sarvam_chars", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["admin_users.id"], name=op.f(f"fk_{ROUNDS}_created_by_admin_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ROUNDS}")),
        sa.CheckConstraint(
            "cartesia_chars >= 0 AND sarvam_chars >= 0",
            name=op.f("ck_platform_voice_comparison_rounds_chars"),
        ),
    )
    op.create_index(
        "ix_platform_voice_comparison_rounds_created", ROUNDS, [sa.text("created_at DESC")]
    )
    op.create_table(
        TRIALS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("sentence_index", sa.Integer(), nullable=False),
        sa.Column("voice_a", sa.Integer(), nullable=False),
        sa.Column("voice_b", sa.Integer(), nullable=False),
        sa.Column("rating_a", sa.Integer(), nullable=True),
        sa.Column("rating_b", sa.Integer(), nullable=True),
        sa.Column("preference", sa.Text(), nullable=True),
        sa.Column("rated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["round_id"],
            [f"{ROUNDS}.id"],
            name=op.f(f"fk_{TRIALS}_round_id_{ROUNDS}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rated_by"], ["admin_users.id"], name=op.f(f"fk_{TRIALS}_rated_by_admin_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TRIALS}")),
        sa.CheckConstraint(
            "rating_a BETWEEN 1 AND 5 AND rating_b BETWEEN 1 AND 5",
            name=op.f("ck_platform_voice_comparison_trials_ratings"),
        ),
        sa.CheckConstraint(
            "preference IN ('a', 'b', 'none')",
            name=op.f("ck_platform_voice_comparison_trials_preference"),
        ),
        sa.CheckConstraint(
            "(rated_at IS NULL) = (preference IS NULL)",
            name=op.f("ck_platform_voice_comparison_trials_rated_whole"),
        ),
    )
    op.create_index(
        "uq_platform_voice_comparison_trials_position",
        TRIALS,
        ["round_id", "position"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_platform_voice_comparison_trials_position", table_name=TRIALS)
    op.drop_table(TRIALS)
    op.drop_index("ix_platform_voice_comparison_rounds_created", table_name=ROUNDS)
    op.drop_table(ROUNDS)
