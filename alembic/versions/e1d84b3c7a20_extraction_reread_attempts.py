"""how many times a failed call reading has been retried, and when last

Revision ID: e1d84b3c7a20
Revises: c4e9a2f7b183
Create Date: 2026-10-20 23:00:00.000000

D-841 (founder, 20 Oct 2026). A call whose extraction came back as a provider failure
(`call_extractions.errors` carries `_model`) is read again by `workers/extraction_reread`,
at most a fixed number of times within a day of the call:

* `call_extractions.reread_attempts` — re-reads claimed so far, 0 for every existing row;
* `call_extractions.reread_at` — when the last one was claimed, NULL until then.

Additive only. RLS is unchanged: `call_extractions` already carries its FORCEd policy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1d84b3c7a20"
down_revision: str | None = "c4e9a2f7b183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "call_extractions",
        sa.Column("reread_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "call_extractions",
        sa.Column("reread_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_call_extractions_reread_attempts_nonnegative"),
        "call_extractions",
        "reread_attempts >= 0",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(
        op.f("ck_call_extractions_reread_attempts_nonnegative"), "call_extractions", type_="check"
    )
    op.drop_column("call_extractions", "reread_at")
    op.drop_column("call_extractions", "reread_attempts")
