"""admin_users.stay_signed_in: an operator's own "Stay signed in" switch (D-766)

Revision ID: b6d2f8a41c97
Revises: e7c3a1f9d2b4
Create Date: 2026-10-13 12:00:00.000000

One boolean on the operator's own row. Off (the default) keeps the admin realm's session
bounds, 30 minutes idle and 8 hours absolute, and a browser-session cookie. On gives that
operator's second-factor-complete sessions the client realm's bounds, 12 hours idle and 14
days absolute, and a cookie that survives the browser closing
(`authn/sessions.session_policy`). Only the operator may switch it on, behind a fresh second
factor; a superadmin may switch it off for another operator.

`admin_users` is a global table with no row-level security (it is not tenant-scoped and is
read by the sign-in path before any tenant exists); a column adds no policy and needs none.

NOT NULL with a constant default is a catalog-only change on Postgres 11+, so no row is
rewritten and every existing operator reads as off. `lock_timeout` bounds the wait for the
brief ACCESS EXCLUSIVE. Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d2f8a41c97"
down_revision: str | None = "e7c3a1f9d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "admin_users",
        sa.Column("stay_signed_in", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("admin_users", "stay_signed_in")
