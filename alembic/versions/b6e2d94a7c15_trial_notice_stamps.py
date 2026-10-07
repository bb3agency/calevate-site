"""`tenant_trials` records when each trial email was sent

Revision ID: b6e2d94a7c15
Revises: a3d9e6f1c204
Create Date: 2026-10-07 23:45:00.000000

Two nullable stamps, one per email (D-685): `start_notice_sent_at` for "your trial has
started" and `ending_notice_sent_at` for "your trial ends in about a day". Each job claims
its stamp with `UPDATE … WHERE <stamp> IS NULL` before it sends, so a retried outbox
delivery or a second worker cannot mail the same client twice; a send that fails releases
the claim for the retry.

Columns on the trial row rather than a deduped outbox key alone, because the ending notice
is decided by an hourly sweep over the trial, not by an event, and "has this trial been
told" is a fact about the trial. They inherit `tenant_trials`' FORCEd tenant policy, so RLS
is unchanged. NULL on every existing row: an open trial at deploy time still gets its
ending notice, and none gets a start notice for a start that has already happened.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b6e2d94a7c15"
down_revision: str | None = "a3d9e6f1c204"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "tenant_trials",
        sa.Column("start_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_trials",
        sa.Column("ending_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Losing the stamps is safe in one direction only: a re-upgrade would let the hourly
    # sweep send an ending notice again to a trial already inside its last day. That is one
    # repeated email, not a money or data effect.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("tenant_trials", "ending_notice_sent_at")
    op.drop_column("tenant_trials", "start_notice_sent_at")
