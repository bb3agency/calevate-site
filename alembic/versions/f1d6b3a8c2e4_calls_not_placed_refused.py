"""a dial refused before anything rang is recorded as refused

`agents.service._close_unplaced_dial` closes a dial `failed` when a failure proves nothing
rang (`dial_was_not_placed`). Only every-line-busy carried a reason; every other refusal (a
number that could not be lent to the agent, a throttle, the voice platform's do-not-call
list) left `not_placed_reason` NULL, so the daily test-call caps, which count
`not_placed_reason IS NULL`, spent a test call on a dial that never rang.

Downgrade folds `refused` into `unstated`, the code the old constraint allows for a call that
was not placed for a reason it does not name.

Revision ID: f1d6b3a8c2e4
Revises: d7e2a9c4f1b6
Create Date: 2026-11-19 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f1d6b3a8c2e4"
down_revision: str | None = "d7e2a9c4f1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_calls_not_placed_reason_enum"), "calls", type_="check")
    op.create_check_constraint(
        op.f("ck_calls_not_placed_reason_enum"),
        "calls",
        "not_placed_reason IS NULL OR not_placed_reason IN "
        "('from_number_withdrawn', 'unstated', 'lines_full', 'dial_lost', 'refused')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The owner is subject to `calls`' FORCEd policy, which matches no row with no tenant
    # set; lifted for this one statement and restored in the same transaction (the
    # `d3b71c9a5e08` bracket).
    op.execute("ALTER TABLE calls NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE calls SET not_placed_reason = 'unstated' WHERE not_placed_reason = 'refused'")
    op.execute("ALTER TABLE calls FORCE ROW LEVEL SECURITY")
    op.drop_constraint(op.f("ck_calls_not_placed_reason_enum"), "calls", type_="check")
    op.create_check_constraint(
        op.f("ck_calls_not_placed_reason_enum"),
        "calls",
        "not_placed_reason IS NULL OR "
        "not_placed_reason IN ('from_number_withdrawn', 'unstated', 'lines_full', 'dial_lost')",
    )
