"""What the voice platform charged for each call (D-690)

Revision ID: f3b8d1e5a7c2
Revises: e6b2d9f4a1c3
Create Date: 2026-10-08 22:00:00.000000

ThinnestAI states what each call cost the workspace (`costMicro`, millionths of the currency)
on `call.analysed` and on `GET /calls/{id}`. It was compared hourly and never kept, so a call's
vendor charge could not be read back after the sweep's one-day window.

`calls.engine_charged_inr` holds it in rupees, exactly: NUMERIC(14,6) carries every micro-unit
the vendor sends, so no conversion rounds. It is written once per call (NULL until the vendor
settles the call) and is a reconciliation input only; `usage_events.unit_cost_paid` stays the
operator-attested cost (hard rule 7). `calls` is not an append-only table, and the first value
written is never overwritten (`workers/engine_charges.record_engine_charge`).

Downgrade drops the column; the figure is still in the vendor's call log.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d1e5a7c2"
down_revision: str | None = "e6b2d9f4a1c3"
branch_labels: str | None = None
depends_on: str | None = None

_CK = "ck_calls_engine_charged_inr_not_negative"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("calls", sa.Column("engine_charged_inr", sa.Numeric(14, 6), nullable=True))
    op.create_check_constraint(
        op.f(_CK), "calls", "engine_charged_inr IS NULL OR engine_charged_inr >= 0"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(_CK), "calls", type_="check")
    op.drop_column("calls", "engine_charged_inr")
