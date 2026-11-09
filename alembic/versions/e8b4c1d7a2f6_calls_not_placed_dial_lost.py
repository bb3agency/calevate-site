"""a dial whose answer was lost and that the engine never placed is recorded as dial_lost

Revision ID: e8b4c1d7a2f6
Revises: a7d3e9c1b5f2
Create Date: 2026-11-09 18:00:00.000000

A dial whose answer never reached us keeps our placeholder id and `queued` until the
engine's record of the call adopts it. When the engine, asked by the reference we placed
the call under, holds no such call, the row is closed `failed` with `dial_lost`, so the call
log says the call did not go through instead of showing it dialling for ever.

Downgrade folds `dial_lost` into `unstated`, the code the old constraint allows for a call
that was not placed for a reason it does not name.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e8b4c1d7a2f6"
down_revision: str | None = "a7d3e9c1b5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_calls_not_placed_reason_enum"), "calls", type_="check")
    op.create_check_constraint(
        op.f("ck_calls_not_placed_reason_enum"),
        "calls",
        "not_placed_reason IS NULL OR "
        "not_placed_reason IN ('from_number_withdrawn', 'unstated', 'lines_full', 'dial_lost')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The owner is subject to `calls`' FORCEd policy, which matches no row with no tenant
    # set; lifted for this one statement and restored in the same transaction (the
    # `d3b71c9a5e08` bracket).
    op.execute("ALTER TABLE calls NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE calls SET not_placed_reason = 'unstated' WHERE not_placed_reason = 'dial_lost'")
    op.execute("ALTER TABLE calls FORCE ROW LEVEL SECURITY")
    op.drop_constraint(op.f("ck_calls_not_placed_reason_enum"), "calls", type_="check")
    op.create_check_constraint(
        op.f("ck_calls_not_placed_reason_enum"),
        "calls",
        "not_placed_reason IS NULL OR "
        "not_placed_reason IN ('from_number_withdrawn', 'unstated', 'lines_full')",
    )
