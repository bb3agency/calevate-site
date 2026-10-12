"""agents and organizations: silence prompt, filler lines, background sound; call lines per client

Revision ID: e7c3a1f9d2b4
Revises: c2e7a9d4f6b1
Create Date: 2026-10-12 12:00:00.000000

The client's voice settings of founder decisions F3 and F9 (12 Oct 2026), on the D-751 pattern:
seven nullable columns on `agents` (NULL inherits the account's value) and the same seven as
`default_*` on `organizations` (NULL follows Calevate's, `agents/call_handling`), so no row is
backfilled and no live agent changes until somebody chooses.

- `nudge_after_seconds`: ask "are you still there?" after this many seconds, 5-180, or 0 for
  never; `nudge_count` 1-5; `nudge_phrase` up to 120 characters, '' for the platform's own.
- `end_after_silence_seconds`: hang up after this many seconds of silence, 5-180.
- `filler_lines`: up to 8 lines ('{}' for the platform's own). The 60-character limit per line
  is the writer's; a CHECK cannot read an array's elements without a subquery.
- `ambience`: 'off', 'office' or 'office-quiet'; `ambience_volume_pct` 5-100.

Ranges are ThinnestAI's `voice` fields (ThinnestAI email of 12 Oct 2026, VENDOR-STATED).

And `organizations.call_lines` (F7): how many calls one client may have at once, 1-50; NULL is
Calevate's default (2 for a paying client, 1 on a free trial, `tenancy/call_lines`).

Both tables already carry FORCEd row-level security on `tenant_id` / `id`; a column adds no
policy. Locking: ADD COLUMN without a default is a catalog change; each CHECK is added NOT VALID
and then validated, so the brief ACCESS EXCLUSIVE does not wait on a scan. `lock_timeout`
bounds the wait. Downgrade drops the constraints and the columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c3a1f9d2b4"
down_revision: str | None = "c2e7a9d4f6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from the models: a migration is a snapshot.
_SETTINGS: tuple[tuple[str, sa.types.TypeEngine[object], str, str], ...] = (
    (
        "nudge_after_seconds",
        sa.Integer(),
        "nudge_after_range",
        "{c} IS NULL OR {c} = 0 OR ({c} >= 5 AND {c} <= 180)",
    ),
    ("nudge_count", sa.Integer(), "nudge_count_range", "{c} IS NULL OR ({c} >= 1 AND {c} <= 5)"),
    ("nudge_phrase", sa.Text(), "nudge_phrase_length", "{c} IS NULL OR char_length({c}) <= 120"),
    (
        "end_after_silence_seconds",
        sa.Integer(),
        "end_after_silence_range",
        "{c} IS NULL OR ({c} >= 5 AND {c} <= 180)",
    ),
    (
        "filler_lines",
        postgresql.ARRAY(sa.Text()),
        "filler_lines_count",
        "{c} IS NULL OR cardinality({c}) <= 8",
    ),
    (
        "ambience",
        sa.Text(),
        "ambience_enum",
        "{c} IS NULL OR {c} IN ('off', 'office', 'office-quiet')",
    ),
    (
        "ambience_volume_pct",
        sa.Integer(),
        "ambience_volume_range",
        "{c} IS NULL OR ({c} >= 5 AND {c} <= 100)",
    ),
)
_CALL_LINES_CK = "ck_organizations_call_lines_range"
_CALL_LINES_SQL = "call_lines IS NULL OR (call_lines >= 1 AND call_lines <= 50)"


def _columns() -> list[tuple[str, str, sa.types.TypeEngine[object], str, str]]:
    """(table, column, type, constraint name, CHECK) for both tables."""
    out = []
    for column, kind, name, check in _SETTINGS:
        out.append(("agents", column, kind, f"ck_agents_{name}", check.format(c=column)))
        org_column = f"default_{column}"
        out.append(
            (
                "organizations",
                org_column,
                kind,
                f"ck_organizations_default_{name}",
                check.format(c=org_column),
            )
        )
    return out


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, column, kind, _name, _check in _columns():
        op.add_column(table, sa.Column(column, kind, nullable=True))
    op.add_column("organizations", sa.Column("call_lines", sa.Integer(), nullable=True))
    for table, _column, _kind, name, check in _columns():
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check}) NOT VALID")
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {_CALL_LINES_CK} CHECK ({_CALL_LINES_SQL}) "
        "NOT VALID"
    )
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_CALL_LINES_CK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_CALL_LINES_CK}")
    for table, _column, _kind, name, _check in reversed(_columns()):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.drop_column("organizations", "call_lines")
    for table, column, _kind, _name, _check in reversed(_columns()):
        op.drop_column(table, column)
