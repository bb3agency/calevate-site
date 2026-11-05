"""business_copies: an operator's override of the AI's capability judgement

Revision ID: a9d3f6c2e8b1
Revises: f4c2a8e1b7d3
Create Date: 2026-11-05 21:00:00.000000

The capability profile (takes bookings, sells, health business, ...) is judged by the AI copy
run and read by every screen and plan that adapts to the business. When the AI judged wrongly
an operator could only regenerate and hope (audit finding A7-08).

`capability_overrides` holds `{"set": {capability: true|false}, "ai": {capability: verdict}}`:
what an operator decided, and the AI verdict it replaced so clearing the override restores
it. The decided value is also written into `generated.capabilities`, so every reader keeps
reading one place. `business_copies` already carries FORCEd row-level security; a column
adds no policy. ADD COLUMN with a constant default is a catalog change. Downgrade drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9d3f6c2e8b1"
down_revision: str | None = "f4c2a8e1b7d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "business_copies",
        sa.Column(
            "capability_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("business_copies", "capability_overrides")
