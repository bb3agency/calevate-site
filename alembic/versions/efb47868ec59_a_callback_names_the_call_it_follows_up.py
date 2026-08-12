"""a callback names the call it follows up

Revision ID: efb47868ec59
Revises: 4be32bf3d12c
Create Date: 2026-08-11 01:35:00.000000

D-21's M2 half — "trigger an AI callback on needs-follow-up calls" — creates a call
whose reason for existing is another call. `callback_of_call_id` records that, and it
is not decoration: it is the only way to bound the chain.

Without it, nothing stops a callback whose own outcome is `needs_follow_up` from being
called back, forever, by an AI talking to a customer who has stopped answering. With
it, the depth is a query, and the service refuses past `MAX_CALLBACK_DEPTH`. A person
being rung by a robot every day because each call ended inconclusively is exactly the
harm TRAI's rules exist to prevent, and "we did not think about it" is not a defence.

Self-referential FK on a tenant-RLS'd table needs no new policy: both rows are the
tenant's own, and the existing `calls` policy covers the join.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "efb47868ec59"
down_revision: str | None = "4be32bf3d12c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("callback_of_call_id", sa.Uuid(), nullable=True))
    # RESTRICT, not CASCADE: a call row is billing evidence (usage_events reference it),
    # so deleting the parent must fail loudly rather than quietly removing the follow-up
    # that explains a charge.
    op.create_foreign_key(
        "fk_calls_callback_of_call_id_calls",
        "calls",
        "calls",
        ["callback_of_call_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_calls_callback_of_call_id", "calls", ["callback_of_call_id"])


def downgrade() -> None:
    op.drop_index("ix_calls_callback_of_call_id", table_name="calls")
    op.drop_constraint("fk_calls_callback_of_call_id_calls", "calls", type_="foreignkey")
    op.drop_column("calls", "callback_of_call_id")
