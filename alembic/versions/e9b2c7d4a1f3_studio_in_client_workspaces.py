"""Studio runs in each client's own workspace: record where it is on (D-717)

Revision ID: e9b2c7d4a1f3
Revises: c2f7e8a4d1b6
Create Date: 2026-10-10 18:00:00.000000

Our Cartesia key is installed and switched on (voice-only BYOK) in the ThinnestAI customer
workspace of each client that publishes a Studio agent, and nowhere else; the developer
workspace's switch stays off so no client inherits it. These three columns on the client's
existing workspace row say where that was done, so a key rotation reaches every such
workspace, the hourly check knows which workspaces must answer `using: own`, and the
catalogue knows where Studio voices can be listed.

* `studio_enabled_at` — when our key was first confirmed on in this workspace.
* `studio_checked_at` — the last time its `GET /byok` was read and found as expected.
* `studio_error_code` — our code for the last failure to install, switch on or verify, or
  NULL.

`tenant_engine_workspaces` already carries `tenant_id` with the FORCEd `tenant_isolation`
policy and the untenanted directory read (`d93b6f2a4c18`); new nullable columns change
neither, so no policy is touched.

DOWNGRADE drops the columns. The vendor state is untouched: each workspace keeps our key
and its switch, and the record of which ones is lost until a Studio publish or the hourly
check writes it again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9b2c7d4a1f3"
down_revision: str | None = "c2f7e8a4d1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "tenant_engine_workspaces",
        sa.Column("studio_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_engine_workspaces",
        sa.Column("studio_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_engine_workspaces",
        sa.Column("studio_error_code", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_tenant_engine_workspaces_studio_error_code_bounded"),
        "tenant_engine_workspaces",
        "studio_error_code IS NULL OR char_length(studio_error_code) <= 64",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(
        op.f("ck_tenant_engine_workspaces_studio_error_code_bounded"),
        "tenant_engine_workspaces",
        type_="check",
    )
    op.drop_column("tenant_engine_workspaces", "studio_error_code")
    op.drop_column("tenant_engine_workspaces", "studio_checked_at")
    op.drop_column("tenant_engine_workspaces", "studio_enabled_at")
