"""agents may be stored in the staged languages (D-855)

Revision ID: d6f1a8c3e925
Revises: b7e2d4f9a613
Create Date: 2026-10-23 12:00:00.000000

Tamil, Kannada, Malayalam and Marathi are built and held back from clients (founder,
23 Oct 2026). The two CHECK constraints on `agents` widen to admit them, so switching one on
in the console (`staged_agent_languages_enabled`) needs no migration. Which languages a
client may choose is decided by the application at run time
(`apps/api/agents/languages.client_language_tags`), not by these constraints.

Each constraint is replaced by a wider one, added NOT VALID and validated inside a
`NO FORCE ROW LEVEL SECURITY` bracket (c7a41e8b52d9's reason: the owner is subject to the
FORCEd policy, so an unbracketed scan sees no row and proves nothing). Every existing row
satisfies the narrower predicate and therefore the wider one.

RLS: no new table or column; `agents` keeps its policy.

Downgrade restores the three-language constraints. It fails, by design, while any agent
holds a staged language: those rows must be moved to another language first, because
narrowing the constraint over them would leave a CHECK that existing data breaks.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d6f1a8c3e925"
down_revision: str | None = "b7e2d4f9a613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agents"
CK_PRIMARY = "ck_agents_language_primary_offered"
CK_EXTRA = "ck_agents_languages_extra_offered"

# Spelled out, not imported, for c7a41e8b52d9's reason: a migration is the schema on the day
# it ran.
_THREE = ("te-IN", "hi-IN", "en-IN")
_SEVEN = (*_THREE, "ta-IN", "kn-IN", "ml-IN", "mr-IN")


def _primary_sql(tags: tuple[str, ...]) -> str:
    return "language_primary IN (" + ", ".join(f"'{tag}'" for tag in tags) + ")"


def _extra_sql(tags: tuple[str, ...]) -> str:
    array = "ARRAY[" + ", ".join(f"'{tag}'" for tag in tags) + "]::text[]"
    return (
        f"languages_extra <@ {array} AND cardinality(languages_extra) <= 3 "
        "AND NOT (language_primary = ANY (languages_extra))"
    )


def _replace(tags: tuple[str, ...]) -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name, predicate in ((CK_PRIMARY, _primary_sql(tags)), (CK_EXTRA, _extra_sql(tags))):
        op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {name} CHECK ({predicate}) NOT VALID")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_PRIMARY}")
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_EXTRA}")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _replace(_SEVEN)


def downgrade() -> None:
    _replace(_THREE)
