"""platform_voice_catalog: curation state, and a withdrawal that is not a delete

Revision ID: e4b7a10c92d6
Revises: d7a4c2e91b83
Create Date: 2026-09-11

**WHY (D-588).** The founder asked for a Voices section in the admin console where they
"add, delete and archive voices end to end", and where only the voices they add there are
selectable by clients and by admins. Half of that cannot be built: **Bolna's voice API is
READ-ONLY** — two GET routes and nothing else (VERIFIED-VENDOR-DOCS, hash-pinned mirror,
`bolna-findings/mirror/pages/api-reference/voice/overview.md:17-18`, every documented method
in `pages/api-reference/` enumerated 11 Sep 2026) — so ADDING a voice happens in their
Playground, by import or by clone (`pages/import-voices.md`, `pages/clone-voices.md`).

What IS buildable, and what these columns are, is the CURATION layer over the sync D-585
already built: every voice the engine account offers is synced, and an operator decides
which of them anybody may be put on.

**`curation_state` DEFAULTS TO `disabled`, AND THAT IS THE REQUIREMENT ITSELF.** A voice
arriving `enabled` would mean the vendor adding a persona to their platform silently puts
it in front of every client of every tenant with no operator in the loop. The default is
the safe direction, and it is the literal reading of "only the voices they enable are
selectable".

**EXISTING ROWS ARE BACKFILLED TO `enabled`, WHICH IS NOT A CONTRADICTION OF THAT.** A
deployment that has already synced is OFFERING those voices today, and a client's agent may
already be speaking one. A migration that withdrew every voice on the picker in the name of
"nobody enabled these yet" would be a schema change that silently un-offers a live product
— the two-step rule in hard rule 8 applied to behaviour rather than to a column. So the
column's DEFAULT governs everything that arrives after this migration, and the BACKFILL
preserves what the deployment already does. An operator disables what they do not want, on
the screen this migration exists for.

**`withdrawn_at` REPLACES A DELETE.** The sync used to `DELETE` rows a COMPLETE listing no
longer named. Every other column is re-derivable by re-running the sync; `curation_state` is
not, so a delete threw away the only operator decision in the row — and a voice that
vanished from one listing and came back returned as a fresh, un-curated row. It is a
separate column from `curation_state` on purpose: "the voice platform no longer lists this"
is the VENDOR's statement and "an operator switched this off" is ours, and an operator
reading one of those goes somewhere different from an operator reading the other.

REVERSIBLE, and the downgrade loses only what this migration added. It restores the
delete-on-prune behaviour implicitly: rows marked withdrawn simply become ordinary rows
again, and the next complete sync removes the ones the vendor no longer lists.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4b7a10c92d6"
down_revision = "d7a4c2e91b83"
branch_labels = None
depends_on = None

TABLE = "platform_voice_catalog"

#: The three states, spelled once here and once in `agents/voices.CurationState`. The
#: constraint is what stops a typo in a route becoming a voice nothing can classify — the
#: same argument the `provider` check on this table already makes.
STATES = ("enabled", "disabled", "archived")


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "curation_state",
            sa.Text(),
            # DISABLED for anything that arrives AFTER this migration — see the docstring.
            server_default=sa.text("'disabled'"),
            nullable=False,
        ),
    )
    op.add_column(TABLE, sa.Column("curated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))

    # WHAT THE DEPLOYMENT ALREADY OFFERS KEEPS BEING OFFERED. `curated_at` stays NULL on
    # these rows deliberately: nobody has actually looked at them, and the console must be
    # able to say "never reviewed" rather than claim an operator decision that was really a
    # migration's default.
    op.execute(sa.text(f"UPDATE {TABLE} SET curation_state = 'enabled'"))  # noqa: S608

    op.create_check_constraint(
        op.f(f"ck_{TABLE}_curation_state"),
        TABLE,
        f"curation_state IN {STATES!r}",
    )
    # The working list is "everything the platform still lists", and the console's default
    # view and `read_cached_catalogue` both ask for exactly that. A partial index rather
    # than one over the whole column: the rows it excludes are the ones nobody queries.
    op.create_index(
        op.f(f"ix_{TABLE}_live"),
        TABLE,
        ["curation_state"],
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(op.f(f"ix_{TABLE}_live"), table_name=TABLE)
    op.drop_constraint(op.f(f"ck_{TABLE}_curation_state"), TABLE, type_="check")
    op.drop_column(TABLE, "withdrawn_at")
    op.drop_column(TABLE, "curated_at")
    op.drop_column(TABLE, "curation_state")
