"""extraction field hint renamed `description` -> `reason` (data migration)

Revision ID: f4b1e9a2c7d0
Revises: d3a7c81f45be
Create Date: 2026-08-24 00:00:00.000000

WHY. The per-field free-text hint on `ExtractionField` (stored inside the
`extraction_schemas.fields` JSONB array) was named `description` while it doubled as the
model's extraction instruction. When the field list became client-editable (D-460), the
field was renamed to `reason` — a client filling one in is answering "why do you want
this?", which extracts better than a bare restatement of the label, and the model now
carries `extra="forbid"`, so a stored element still keyed `description` would fail to
validate on read. This migration rewrites every existing row's `fields` array, renaming the
`description` key to `reason` on each element that has it, IN PLACE, order preserved.

NO DDL. `fields` is a single JSONB column; the shape lives in the value, not the schema, so
there is nothing to alter — only data to rewrite. `extraction_schemas` is a tenant table
but NOT append-only (`db/registry`), so this UPDATE is permitted; it touches only the
schema-definition metadata, never a caller's extracted VALUES (those live in `leads.data`,
keyed by `field.key`, and are untouched).

ORDER IS LOAD-BEARING and preserved: field order is the display order and the order the
extraction prompt lists fields in, so the rewrite uses `WITH ORDINALITY` + `ORDER BY` rather
than `jsonb_object_keys`-style reshuffling. Rows whose fields carry no `description` (a fresh
seed already writes `reason`) are left untouched by the `WHERE EXISTS` guard, so re-running
is a no-op.

REVERSIBLE. `downgrade` performs the exact inverse (`reason` -> `description`), so a rollback
restores the pre-D-460 shape a pinned older process would expect.

LOCKING. One `UPDATE` over one small, per-agent table; `lock_timeout` bounds the wait.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b1e9a2c7d0"
down_revision: str | None = "d3a7c81f45be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename_key(old: str, new: str) -> str:
    """SQL that rewrites `extraction_schemas.fields`, renaming JSONB key `old` -> `new` on
    every array element that has it, order preserved, other elements untouched."""
    return f"""
        UPDATE extraction_schemas
        SET fields = COALESCE(
            (
                SELECT jsonb_agg(
                    CASE
                        WHEN elem ? '{old}'
                        THEN (elem - '{old}') || jsonb_build_object('{new}', elem -> '{old}')
                        ELSE elem
                    END
                    ORDER BY ord
                )
                FROM jsonb_array_elements(fields) WITH ORDINALITY AS t(elem, ord)
            ),
            fields
        )
        WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements(fields) AS e WHERE e ? '{old}'
        )
    """


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_rename_key("description", "reason"))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_rename_key("reason", "description"))
