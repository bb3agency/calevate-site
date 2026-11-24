"""The owner's "Give callers time" choice on each campaign and inbound line (25 Nov 2026)

Revision ID: a7c3e9f1d2b4
Revises: e5b9c3a7d1f4
Create Date: 2026-11-25 10:00:00.000000

`campaigns.give_callers_time` and `inbound_lines.give_callers_time`, both nullable booleans.
NULL lets the holder's script decide: its engine agent carries the preset when the script
asks the caller to act on their phone (`agents/give_callers_time.holder_gives_time`). True or
false is the owner's choice for that holder, which the script never overrides.

Every existing row starts NULL, so live holders whose scripts ask the caller to act get the
preset at the platform-revision republish this release triggers (`live_apply.
platform_prompt_revision`).

NO NEW TABLE, SO NO NEW POLICY: both tables keep their FORCEd `tenant_isolation`.
Reversible: `downgrade()` drops both columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9f1d2b4"
down_revision: str | None = "e5b9c3a7d1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("campaigns", "inbound_lines")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.add_column(table, sa.Column("give_callers_time", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in reversed(_TABLES):
        op.drop_column(table, "give_callers_time")
