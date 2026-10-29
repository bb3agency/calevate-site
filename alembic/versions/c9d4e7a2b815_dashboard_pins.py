"""dashboard pins — Pip's charts kept on the client home and the admin home (D-934)

Revision ID: c9d4e7a2b815
Revises: e5b9d3f7a248
Create Date: 2026-10-29 16:00:00.000000

A pin stores the QUERY that drew a chart — the chart's name and its arguments — and never
its figures, so a pinned card re-runs under the viewer's own session and permissions.

`dashboard_pins` is a tenant table: one account's cards, shared by everyone on the account,
FORCEd RLS on the usual `tenant_isolation` policy. `created_by` is SET NULL when the person
leaves: the card belongs to the account. `admin_dashboard_pins` is the operators' twin on the
admin home: platform-scoped, no tenant, no policy (`db/registry.RLS_EXEMPT_TENANT_COLUMNS`).

`args` is a small JSON object of the chart's own arguments (`{"days": 30}`), checked by the
application against `copilot/chart_spec.ChartArgs`; it never holds a caller's data.

REVERSIBILITY. `downgrade()` drops both tables; a pin is a shortcut, not a record.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d4e7a2b815"
down_revision: str | None = "e5b9d3f7a248"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PINS = "dashboard_pins"
ADMIN_PINS = "admin_dashboard_pins"

_MAX_CHART = 40
_MAX_TITLE = 80

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def _columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("chart", sa.String(length=_MAX_CHART), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("title", sa.String(length=_MAX_TITLE), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _checks(table: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("length(btrim(title)) > 0", name=op.f(f"ck_{table}_title_not_blank")),
        sa.CheckConstraint("jsonb_typeof(args) = 'object'", name=op.f(f"ck_{table}_args_object")),
        sa.CheckConstraint("position BETWEEN 0 AND 99", name=op.f(f"ck_{table}_position_range")),
    ]


def _fk(table: str, column: str, referred: str, on_delete: str) -> None:
    """NOT VALID then VALIDATE — `d5b8a2c60e17`'s locking shape, on empty new tables."""
    name = f"fk_{table}_{column}_{referred}"
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) "
        f"REFERENCES {referred} (id) ON DELETE {on_delete} NOT VALID"
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        PINS,
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        *_columns(),
        *_checks(PINS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PINS}")),
    )
    op.create_index(op.f(f"ix_{PINS}_tenant_position"), PINS, ["tenant_id", "position"])
    _fk(PINS, "tenant_id", "organizations", "RESTRICT")
    _fk(PINS, "created_by", "users", "SET NULL")
    op.execute(f"ALTER TABLE {PINS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {PINS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {PINS} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    # No tenant_id, no policy: the operators' shared cards about the whole platform.
    op.create_table(
        ADMIN_PINS,
        *_columns(),
        *_checks(ADMIN_PINS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ADMIN_PINS}")),
    )
    op.create_index(op.f(f"ix_{ADMIN_PINS}_position"), ADMIN_PINS, ["position"])
    _fk(ADMIN_PINS, "created_by", "admin_users", "SET NULL")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(ADMIN_PINS)
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {PINS}")
    op.drop_table(PINS)
