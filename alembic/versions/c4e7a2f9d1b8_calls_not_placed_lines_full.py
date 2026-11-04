"""a dial the account's lines refused is recorded as not placed: lines_full

Revision ID: c4e7a2f9d1b8
Revises: f2c8a6d4b1e9
Create Date: 2026-11-04 19:00:00.000000

A campaign dial past the account's call lines is refused by the voice platform with
`concurrent_calls` (place-call.md:674-702, snapshot 2026-10-29) and nothing rings. The
intent row was closed as a bare `failed`, which the owner's attention list reports as "a
call to a caller failed" for a call that never left. `lines_full` says what happened, so
the list can leave it out and the call page can say it in the owner's words.

Downgrade folds `lines_full` into `unstated`, the code the old constraint allows for a call
that was not placed for a reason it does not name.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c4e7a2f9d1b8"
down_revision: str | None = "f2c8a6d4b1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_calls_not_placed_reason_enum"), "calls", type_="check")
    op.create_check_constraint(
        op.f("ck_calls_not_placed_reason_enum"),
        "calls",
        "not_placed_reason IS NULL OR "
        "not_placed_reason IN ('from_number_withdrawn', 'unstated', 'lines_full')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The owner is subject to `calls`' FORCEd policy, which matches no row with no tenant
    # set; lifted for this one statement and restored in the same transaction (the
    # `d3b71c9a5e08` bracket).
    op.execute("ALTER TABLE calls NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE calls SET not_placed_reason = 'unstated' WHERE not_placed_reason = 'lines_full'")
    op.execute("ALTER TABLE calls FORCE ROW LEVEL SECURITY")
    op.drop_constraint(op.f("ck_calls_not_placed_reason_enum"), "calls", type_="check")
    op.create_check_constraint(
        op.f("ck_calls_not_placed_reason_enum"),
        "calls",
        "not_placed_reason IS NULL OR not_placed_reason IN ('from_number_withdrawn', 'unstated')",
    )
