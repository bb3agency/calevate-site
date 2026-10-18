"""a custom business's drafted lead details wait for the owner's review

Revision ID: d5b1e8c4a7f2
Revises: e6a2d94c3b17
Create Date: 2026-10-19 09:00:00.000000

D-821 (founder, 18 Oct 2026). The one AI draft of a custom business's lead details used to
be written straight onto every agent with no fields of its own. It now waits on the Lead
details screen until the owner keeps it field by field (`agents/lead_fields.review_draft`).
`lead_field_drafts.reviewed_at` records when; NULL on a `done` draft means it has reached
no agent. A nullable addition to a table that already carries its RLS policy.

**Backfill.** Every draft already `done` was applied when it finished, so it is marked
reviewed at its own `completed_at`: nothing already on an agent is offered again.

**Downgrade** drops the column. A draft that is `done` and unreviewed at that point has
reached no agent, and the old code would treat it as applied; downgrade is refused while
one exists rather than lose that distinction silently.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5b1e8c4a7f2"
down_revision: str | None = "e6a2d94c3b17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "lead_field_drafts", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    # FORCEd RLS: without an `app.tenant_id` the owner's own statements see no row, so the
    # backfill (and the downgrade's check) run inside a NO FORCE / FORCE bracket
    # (c7a41e8b52d9's reason). Without it the backfill matched nothing and every applied
    # draft read as waiting for review.
    op.execute("ALTER TABLE lead_field_drafts NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE lead_field_drafts SET reviewed_at = COALESCE(completed_at, updated_at) "
        "WHERE status = 'done'"
    )
    op.execute("ALTER TABLE lead_field_drafts FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE lead_field_drafts NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM lead_field_drafts "
        "WHERE status = 'done' AND reviewed_at IS NULL) THEN RAISE EXCEPTION "
        "'a drafted set of lead details waits for review; it would read as applied'; "
        "END IF; END $$"
    )
    op.execute("ALTER TABLE lead_field_drafts FORCE ROW LEVEL SECURITY")
    op.drop_column("lead_field_drafts", "reviewed_at")
