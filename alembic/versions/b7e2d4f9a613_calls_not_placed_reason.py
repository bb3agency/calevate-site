"""why a booked call was never placed, in our words (D-842)

Revision ID: b7e2d4f9a613
Revises: a3d8f1c6e092
Create Date: 2026-10-21 12:00:00.000000

ThinnestAI's call record carries `error`, "Why a booked call could not be placed, in words.
Null otherwise" (snapshots/2026-10-19/pages/api-reference/calls/get-call.md:1027-1031). The
adapter maps it to `calevate_shared.events.NotPlacedReason`, and this column keeps that code
so the client's call page can say why the call never rang. The vendor's sentence is never
stored: it may name a number (hard rule 6) and it is not our wording (D-679).

`calls` keeps its RLS policy; a column adds no policy. The CHECK names the codes the model
declares.

Downgrade drops the column; the engine's call record still holds its own reason.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2d4f9a613"
down_revision: str | None = "a3d8f1c6e092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("calls", sa.Column("not_placed_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_calls_not_placed_reason_enum"),
        "calls",
        "not_placed_reason IS NULL OR not_placed_reason IN ('from_number_withdrawn', 'unstated')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_calls_not_placed_reason_enum"), "calls", type_="check")
    op.drop_column("calls", "not_placed_reason")
