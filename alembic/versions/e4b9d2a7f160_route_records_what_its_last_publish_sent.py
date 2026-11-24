"""each engine agent's route records what its last publish sent

Revision ID: e4b9d2a7f160
Revises: b7e2c4a91d06
Create Date: 2026-11-24 18:00:00.000000

The admin "What it is told" screen compares what a holder's engine agent was last published
with against what a publish would send now (`agents/prompt_anatomy`). Nothing recorded the
first half, so this adds it to the row that stands for that engine agent:

* `published_digest`: sha256 of the adapter's publish view of the holder's config
  (`engine/publish_view.publish_digest`), lower-case hex;
* `published_instructions_chars`, `published_greeting_chars`, `published_payload_bytes`:
  the sizes of what was sent;
* `published_training_cut_chars`: how much of the company training gave way so the
  instructions fit (0 when none did);
* `published_at`: when that publish committed.

A digest and counts, never the payload: the vendor's shapes stay out of typed columns (hard
rule 2), and the row stays free of anything a tenant wrote, as its global read requires.
The digest and the timestamp are set together or not at all (CHECK). A route published
before this revision reads as never recorded until its holder's next publish.

No new table, so no new policy: the row keeps its strict `tenant_isolation` write policy and
its global read. Reversible: `downgrade()` drops the CHECKs and the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b9d2a7f160"
down_revision: str | None = "b7e2c4a91d06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "engine_agent_routes"
_COUNTS = (
    "published_instructions_chars",
    "published_greeting_chars",
    "published_payload_bytes",
    "published_training_cut_chars",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(_TABLE, sa.Column("published_digest", sa.Text(), nullable=True))
    for column in _COUNTS:
        op.add_column(_TABLE, sa.Column(column, sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_engine_agent_routes_published_digest_hex"),
        _TABLE,
        "published_digest IS NULL OR published_digest ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        op.f("ck_engine_agent_routes_published_together"),
        _TABLE,
        "(published_digest IS NULL) = (published_at IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_engine_agent_routes_published_counts_nonneg"),
        _TABLE,
        " AND ".join(f"({c} IS NULL OR {c} >= 0)" for c in _COUNTS),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name in ("published_counts_nonneg", "published_together", "published_digest_hex"):
        op.drop_constraint(op.f(f"ck_engine_agent_routes_{name}"), _TABLE, type_="check")
    op.drop_column(_TABLE, "published_at")
    for column in reversed(_COUNTS):
        op.drop_column(_TABLE, column)
    op.drop_column(_TABLE, "published_digest")
