"""a client can ask for more calls at once, and an operator raises or declines it

Revision ID: e3b8d1f6a924
Revises: e8b3d6a1f427
Create Date: 2026-11-05 12:00:00.000000

`call_line_requests`: one row per "Need more? Ask us." (`tenancy/call_line_requests`). Tenant
data, FORCEd `tenant_isolation` like every other tenant table. At most one request is open per
client: the unique partial index is what makes a second tap return the open one instead of a
second row, with no read-then-insert window.

No DML, so no NO FORCE / FORCE bracket. Reversible: `downgrade()` drops the policy, the
indexes and the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b8d1f6a924"
down_revision: str | None = "e8b3d6a1f427"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "call_line_requests"
# Literal copies of `tenancy/models.CALL_LINES_MIN/MAX` and `CALL_LINE_REQUEST_TEXT_MAX`: a
# migration states the schema it made, and `check_metadata_columns` compares the two.
_MIN, _MAX, _TEXT_MAX = 1, 50, 280


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("lines_at_request", sa.Integer(), nullable=False),
        sa.Column("wanted_lines", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("lines_granted", sa.Integer(), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_call_line_requests_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_call_line_requests_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["admin_users.id"],
            name=op.f("fk_call_line_requests_resolved_by_admin_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_line_requests")),
        sa.CheckConstraint(
            "status IN ('open', 'done', 'declined')", name=op.f("ck_call_line_requests_status_enum")
        ),
        sa.CheckConstraint(
            f"lines_at_request >= {_MIN} AND lines_at_request <= {_MAX}",
            name=op.f("ck_call_line_requests_lines_at_request_range"),
        ),
        sa.CheckConstraint(
            f"wanted_lines IS NULL OR (wanted_lines > lines_at_request AND wanted_lines <= {_MAX})",
            name=op.f("ck_call_line_requests_wanted_lines_range"),
        ),
        sa.CheckConstraint(
            f"note IS NULL OR char_length(note) BETWEEN 1 AND {_TEXT_MAX}",
            name=op.f("ck_call_line_requests_note_length"),
        ),
        sa.CheckConstraint(
            f"decline_reason IS NULL OR char_length(decline_reason) BETWEEN 1 AND {_TEXT_MAX}",
            name=op.f("ck_call_line_requests_decline_reason_length"),
        ),
        sa.CheckConstraint(
            "(status = 'open') = (resolved_at IS NULL)",
            name=op.f("ck_call_line_requests_resolved_when_closed"),
        ),
        sa.CheckConstraint(
            "(status = 'done') = (lines_granted IS NOT NULL)",
            name=op.f("ck_call_line_requests_granted_when_done"),
        ),
        sa.CheckConstraint(
            "(status = 'declined') = (decline_reason IS NOT NULL)",
            name=op.f("ck_call_line_requests_reason_when_declined"),
        ),
    )
    op.create_index(op.f("ix_call_line_requests_tenant_id"), _TABLE, ["tenant_id"], unique=False)
    op.create_index(
        "uq_call_line_requests_one_open",
        _TABLE,
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_TABLE} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
    op.drop_index("uq_call_line_requests_one_open", table_name=_TABLE)
    op.drop_index(op.f("ix_call_line_requests_tenant_id"), table_name=_TABLE)
    op.drop_table(_TABLE)
