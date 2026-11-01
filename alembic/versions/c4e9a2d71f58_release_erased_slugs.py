"""Release an erased account's slug (D-954, amends D-922)

Revision ID: c4e9a2d71f58
Revises: b5e1d7c3a906
Create Date: 2026-11-01 22:00:00.000000

An erased organization keeps its row, because the append-only ledgers (audit, money,
consent) reference it, but it no longer needs its web address. Until now the address was
spent for good: `organizations_slug_immutable` refused every slug change, so a client
erased and signed up again could not have its old address back.

UPGRADE

* `calevate_forbid_slug_change()` now permits ONE change: to `erased-` plus all 32
  hex characters of the id (39 characters, unique because the id is; the first 12 alone
  are a uuid7's creation millisecond and could collide), on a row whose `deleted_at` is
  set (by that UPDATE or an earlier one). The tenant erasure writes it in the same statement as `deleted_at`
  (`workers/retention._MARK_ERASED_SQL`). Any other change still raises, so a slug in a
  live account's URLs still never moves.
* Every organization already erased is renamed to its tombstone. A row whose slug already
  starts with `erased-` is skipped, so a rename run by hand before this shipped is left as
  it is. Bracketed in NO FORCE ... FORCE because `tenant_isolation` on `organizations` is
  fail-closed for the owner on an unset `app.tenant_id`.

DOWNGRADE restores the original trigger function. It cannot restore the released slugs:
the old values are not kept anywhere this migration can read, and one may by then belong to
a new account. Take a `pg_dump` first if the old slugs matter.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e9a2d71f58"
down_revision: str | None = "b5e1d7c3a906"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRIGGER = "organizations_slug_immutable"
_FUNCTION = "calevate_forbid_slug_change"

_RELEASING_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {_FUNCTION}() RETURNS trigger AS $$
BEGIN
    IF NEW.slug IS DISTINCT FROM OLD.slug
       AND NOT (
           NEW.deleted_at IS NOT NULL
           AND NEW.slug = 'erased-' || replace(NEW.id::text, '-', '')
       ) THEN
        RAISE EXCEPTION 'organizations.slug is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

#: 05bba2f3c19c's body, frozen here so the downgrade puts back exactly what it replaced.
_ORIGINAL_FUNCTION_SQL = f"""
CREATE FUNCTION {_FUNCTION}() RETURNS trigger AS $$
BEGIN
    IF NEW.slug IS DISTINCT FROM OLD.slug THEN
        RAISE EXCEPTION 'organizations.slug is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_RELEASING_FUNCTION_SQL)
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE organizations "
        "SET slug = 'erased-' || replace(id::text, '-', ''), updated_at = now() "
        "WHERE deleted_at IS NOT NULL AND slug NOT LIKE 'erased-%'"
    )
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON organizations")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}()")
    op.execute(_ORIGINAL_FUNCTION_SQL)
    op.execute(
        f"CREATE TRIGGER {_TRIGGER} BEFORE UPDATE ON organizations "
        f"FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}()"
    )
