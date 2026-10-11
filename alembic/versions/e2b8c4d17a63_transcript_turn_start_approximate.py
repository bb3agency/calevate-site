"""Mark a transcript turn's start time as approximate (key moments, 11 Oct 2026)

Revision ID: e2b8c4d17a63
Revises: d7a3c91e5b20
Create Date: 2026-10-11 18:00:00.000000

ThinnestAI's turn time is "when it was written down, not where it falls in the audio"
(thinnest-findings get-call-transcript.md:7), so a turn's `start_ms` on that engine is a
rough position. The screens show such times as "~0:21" and seek a little early; this column
is how they know. Existing rows are exact or have no time at all, so the default is false.

`transcript_turns` already carries FORCEd RLS; a column needs no new policy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2b8c4d17a63"
down_revision: str | None = "d7a3c91e5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcript_turns",
        sa.Column(
            "start_approximate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("transcript_turns", "start_approximate")
