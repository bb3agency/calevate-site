"""a lead's WhatsApp timeline rows keep a digest of Meta's message id, not the id

Revision ID: d9a4e7c2b1f6
Revises: c3f8a1d6e4b9
Create Date: 2026-11-09 22:00:00.000000

A `wamid.` message id is base64 of a record holding the recipient's number in clear, so
the `message_id` the lead timeline stored for a client's WhatsApp follow-up was that
person's number, in a table no erasure reaches. `crm/swipe.message_ref` now stores the
SHA-256 hex digest under `message_ref`; this rewrites the rows written before it, with the
same digest Python computes (`encode(sha256(convert_to(id, 'UTF8')), 'hex')`), so a
failed-delivery report for an older send still finds its row.

Downgrade moves the digest back under `message_id`. The ids themselves cannot come back,
and an old build reading the digest only fails to match a late failure report.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d9a4e7c2b1f6"
down_revision: str | None = "c3f8a1d6e4b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = (
    "UPDATE lead_events SET payload = (payload - 'message_id') || jsonb_build_object("
    "'message_ref', encode(sha256(convert_to(payload->>'message_id', 'UTF8')), 'hex')) "
    "WHERE type = 'notification' AND payload ? 'message_id'"
)

_DOWNGRADE = (
    "UPDATE lead_events SET payload = (payload - 'message_ref') || jsonb_build_object("
    "'message_id', payload->>'message_ref') "
    "WHERE type = 'notification' AND payload ? 'message_ref'"
)


def _rewrite(statement: str) -> None:
    # The owner is subject to `lead_events`' FORCEd policy, which matches no row with no
    # tenant set; lifted for this one statement and restored in the same transaction (the
    # `d3b71c9a5e08` bracket).
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE lead_events NO FORCE ROW LEVEL SECURITY")
    op.execute(statement)
    op.execute("ALTER TABLE lead_events FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rewrite(_UPGRADE)


def downgrade() -> None:
    _rewrite(_DOWNGRADE)
