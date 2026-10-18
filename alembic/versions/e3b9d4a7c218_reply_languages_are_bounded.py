"""each agent's reply languages are its own, bounded

Revision ID: e3b9d4a7c218
Revises: d8e3a5c71f42
Create Date: 2026-10-18 14:00:00.000000

D-815 (founder, 18 Oct 2026): an agent replies in up to four languages, its main one first.
`agents.language_primary` holds the first; `agents.languages_extra` holds the rest, in order.
Since D-695 the extra languages were the BUSINESS's (`business_profiles.languages`, one list
for every agent of a client) and `agents.languages_extra` was neither read nor written.

1. **The data move.** Every agent's `languages_extra` is set from its business's list, as
   the publish path read it until now: offered languages only, never the agent's main one,
   each once, in order, at most three. An agent of a business with no list gets NULL (no
   extra language). So no published agent changes; from here the agent's own list is read.
   `business_profiles.languages` stays: it is now the starting list of an agent created
   after this revision, and saving it no longer changes existing agents.
2. **One CHECK** on `languages_extra`: only the languages the product sells, at most three
   (four with the main one, the voice platform's ceiling), never the main language again.
   NULL stays allowed and means "no extra language".

RLS: no new table or column. The UPDATE reads `business_profiles` and writes `agents`, both
FORCEd, so both run inside a `NO FORCE` / `FORCE` bracket (c7a41e8b52d9's reason: without an
`app.tenant_id` the owner's own statements see no row).

Downgrade drops the constraint. The data move is not undone: the code before this revision
reads `business_profiles.languages`, which this migration leaves as it was.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3b9d4a7c218"
down_revision: str | None = "d8e3a5c71f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CK_EXTRA = "ck_agents_languages_extra_offered"

# Spelled out, not imported, for c7a41e8b52d9's reason: a migration is the schema on the day
# it ran.
_OFFERED = "ARRAY['te-IN', 'hi-IN', 'en-IN']::text[]"
_EXTRA_SQL = (
    f"languages_extra <@ {_OFFERED} AND cardinality(languages_extra) <= 3 "
    "AND NOT (language_primary = ANY (languages_extra))"
)
_MOVE_SQL = (
    "UPDATE agents a SET languages_extra = ("
    "SELECT (array_agg(s.tag ORDER BY s.ord))[1:3] FROM ("
    "SELECT DISTINCT ON (u.tag) u.tag, u.ord "
    "FROM business_profiles bp, unnest(bp.languages) WITH ORDINALITY AS u(tag, ord) "
    f"WHERE bp.tenant_id = a.tenant_id AND u.tag = ANY ({_OFFERED}) "
    "AND u.tag <> a.language_primary "
    "ORDER BY u.tag, u.ord) s)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE agents ADD CONSTRAINT {CK_EXTRA} CHECK ({_EXTRA_SQL}) NOT VALID")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE business_profiles NO FORCE ROW LEVEL SECURITY")
    op.execute(_MOVE_SQL)
    op.execute(f"ALTER TABLE agents VALIDATE CONSTRAINT {CK_EXTRA}")
    op.execute("ALTER TABLE business_profiles FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {CK_EXTRA}")
