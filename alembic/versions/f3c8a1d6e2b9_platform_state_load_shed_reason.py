"""platform_state keeps why the platform was slowed

Revision ID: f3c8a1d6e2b9
Revises: d9a4e7c2b1f6
Create Date: 2026-11-10 12:00:00.000000

The protective-slowdown control requires a reason and tells the operator that whoever
finds the platform slowed reads it, but the reason went only into the audit summary,
which reaches the log stream and no column. `load_shed_reason` is written with
`load_shed_mode` in one statement (`core.loadshed.set_platform_status`) and cleared on a
return to normal, the same contract `halt_reason` has with `outbound_halted`.

`platform_state` is global and not RLS'd (one row, no tenant), so there is no policy to add.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3c8a1d6e2b9"
down_revision: str | None = "d9a4e7c2b1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("platform_state", sa.Column("load_shed_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("platform_state", "load_shed_reason")
