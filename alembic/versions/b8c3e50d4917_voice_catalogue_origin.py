"""platform_voice_catalog: where a row came from — a sync, or an operator who typed it

Revision ID: b8c3e50d4917
Revises: a3f7d21c60b9
Create Date: 2026-09-11

**WHY (D-590, superseding the console half of D-588).** D-588 made the Voices page a
CURATION screen over everything the voice platform lists: 418 rows, of which 414 had to be
switched off one by one. The founder's answer was that the catalogue is not the product —
*"we will not actually be using any voices provided by either sarvam or cartesia and will
only be using cloned voices"* — and that what they want is to ADD the handful of voices
they have cloned, by providing the facts.

D-588 concluded the "add" half could not be built because **Bolna's voice API is read-only**
(VERIFIED-VENDOR-DOCS, hash-pinned mirror,
`bolna-findings/mirror/pages/api-reference/voice/overview.md:10-18` — two GET routes and no
create anywhere in `pages/api-reference/`). That premise is still true and the conclusion
was still wrong: adding a voice *to Bolna* is their Playground's job, but adding a voice *to
this product's catalogue* is ours, and it needs nothing from them but a read. So an operator
types the four facts the synthesizer block needs, we VERIFY them against the platform's own
list before accepting the row, and the row is ours.

**THIS COLUMN IS THE ONE THING THAT MAKES THE TWO KINDS OF ROW TELLABLE APART.** Everything
else about an operator-added row and a synced row is identical by design — one shape, one
`Voice`, one picker — but only one of them is a DECISION. `origin` is what lets the console
open with the voices somebody added instead of with the vendor's whole list, and what stops
the hourly sync from quietly reclassifying a typed row as a cache line it may overwrite.

**EXISTING ROWS ARE `synced`, INCLUDING ENABLED ONES.** They are: every row in this table
today was written by `sync_voice_catalogue`. A backfill that called the enabled ones
"operator" would be inventing a provenance for a click — an operator enabled that row, they
did not attest its facts, and the console says different things about the two.

REVERSIBLE. The downgrade drops the column and loses only the provenance; an added row stays
a perfectly good catalogue row, because that was the point of giving it the same shape.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8c3e50d4917"
# CHAINED ONTO THE ALERTS MIGRATION RATHER THAN ONTO `e4b7a10c92d6`, which is its parent and
# was this tree's head when the work started. Two siblings on one parent fork the chain and
# `alembic upgrade head` then refuses to choose (hard rule 8, and the ratchet's "dirty or
# stale store" refusal). `alembic heads` printed exactly one head before this file was
# written and prints exactly one after it.
down_revision = "a3f7d21c60b9"
branch_labels = None
depends_on = None

TABLE = "platform_voice_catalog"

#: The two provenances, spelled once here and once in `agents/voices.VoiceOrigin`. A CHECK
#: rather than an enum type for the reason every other vocabulary on this table uses one:
#: adding a third value is a one-line constraint swap rather than a type rewrite.
ORIGINS = ("synced", "operator")


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "origin",
            sa.Text(),
            # SYNCED for anything that arrives without saying otherwise — the sync's upsert
            # names every column it writes and this is deliberately not among them, so the
            # default is what a re-read of the vendor's list produces.
            server_default=sa.text("'synced'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_origin"),
        TABLE,
        f"origin IN {ORIGINS!r}",
    )
    # The console's default view is "rows somebody decided about" — operator-added, or
    # synced and not left at the arrival state. A partial index over the two columns that
    # answer it, excluding the withdrawn rows nobody queries by state.
    op.create_index(
        op.f(f"ix_{TABLE}_decided"),
        TABLE,
        ["origin", "curation_state"],
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(op.f(f"ix_{TABLE}_decided"), table_name=TABLE)
    op.drop_constraint(op.f(f"ck_{TABLE}_origin"), TABLE, type_="check")
    op.drop_column(TABLE, "origin")
