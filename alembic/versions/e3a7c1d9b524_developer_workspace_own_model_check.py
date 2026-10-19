"""the developer workspace's own-model check is recorded

Revision ID: e3a7c1d9b524
Revises: b7e4c2d9f1a3
Create Date: 2026-10-19 18:00:00.000000

D-834 (founder, 19 Oct 2026): free-trial agents, which live in our developer workspace, answer
on our Google key like a paying client's. `platform_state` records what that workspace last
answered about our key, the same three facts `tenant_engine_workspaces.own_model_*` hold for
a client workspace (D-764):

* `own_model_developer_enabled_at` — first time our Google key read back checked and in use
  there; the hourly sweep repairs the workspace only once this is set;
* `own_model_developer_checked_at` — the last time it read back so;
* `own_model_developer_error_code` — the last failure's code, cleared by the next pass.

All NULL until the operator's "Set up developer workspace" act or the first passing check.
RLS is unchanged: `platform_state` has none.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a7c1d9b524"
down_revision: str | None = "b7e4c2d9f1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "platform_state"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        _TABLE,
        sa.Column("own_model_developer_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column("own_model_developer_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(_TABLE, sa.Column("own_model_developer_error_code", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column(_TABLE, "own_model_developer_error_code")
    op.drop_column(_TABLE, "own_model_developer_checked_at")
    op.drop_column(_TABLE, "own_model_developer_enabled_at")
