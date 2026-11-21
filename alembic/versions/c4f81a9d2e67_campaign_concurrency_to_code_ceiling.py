"""ck_campaigns_concurrency_range admits the code ceiling (20), not the old fixed 10

How many calls one campaign may ask for at once became a console setting,
`campaign_max_concurrency` (default 10), under a code ceiling,
`calevate_shared.config.CAMPAIGN_CONCURRENCY_CEILING` (20, the concurrent calls ThinnestAI
last stated for our account). The CHECK is the absolute sanity bound, so it moves to the
ceiling; the console value is enforced by the API on every write.

Drop and add, because Postgres cannot alter a CHECK's expression. Widening needs no
validation of existing rows. The downgrade narrows back to 10 and lets Postgres refuse it
while any campaign is set above 10, rather than rewriting a client's setting.

The predicate is spelled out rather than built from the constant, so this file keeps
describing the schema it produced.

Revision ID: c4f81a9d2e67
Revises: bd9b4b153d5a
Create Date: 2026-11-21 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f81a9d2e67"
down_revision: str | None = "bd9b4b153d5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_campaigns_concurrency_range"
WIDENED = "concurrency BETWEEN 1 AND 20"
ORIGINAL = "concurrency BETWEEN 1 AND 10"


def upgrade() -> None:
    # `op.f` inside the function: the name is already conventionalised, and the Operations
    # proxy exists only during a run (see `d7b1c48a2e93`).
    op.drop_constraint(op.f(CONSTRAINT), "campaigns", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "campaigns", WIDENED)


def downgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "campaigns", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "campaigns", ORIGINAL)
