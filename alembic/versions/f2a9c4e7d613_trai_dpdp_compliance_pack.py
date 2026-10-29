"""TRAI and DPDP compliance pack: application consent basis and the rights desk (D-943)

Revision ID: f2a9c4e7d613
Revises: c9d4e7a2b815
Create Date: 2026-10-30 12:00:00.000000

Two changes.

1. `inbound_webhooks.consent_basis` — what a submission to a lead source IS: an `inquiry`
   (the default, every source today) or an `application`. It picks the window a form
   consent stays valid for: seven days for an inquiry, three months for an application
   (TCCCPR Third Amendment 2026 cl.2(bb)(ii)/(iii)). NOT NULL with a constant default, so
   PostgreSQL adds it without rewriting the table.

2. `data_rights_requests` — a client's log of the rights requests its own customers make
   (DPDP §11-§14), each with a 90-day deadline fixed from when the person asked. A tenant
   table: FORCEd RLS on the usual `tenant_isolation` policy. It names the person by
   `subject_ref` only, never a number.

REVERSIBILITY. `downgrade()` drops the table and the column. The column is a client
setting with a default every row can return to; the table's rows are the client's log, and
dropping it loses them, which is why a downgrade past this revision is a decision, not a
routine step.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a9c4e7d613"
down_revision: str | None = "c9d4e7a2b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DESK = "data_rights_requests"

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

_KINDS = ("access", "correction", "erasure", "nomination", "grievance")
_CHANNELS = ("phone", "email", "whatsapp", "letter", "in_person", "other")
_STATUSES = ("open", "answered", "refused")
_OUTCOMES = (
    "exported",
    "erased",
    "corrected",
    "nominated",
    "explained",
    "identity_not_confirmed",
    "not_held",
)


def _fk(table: str, column: str, referred: str, on_delete: str) -> None:
    """NOT VALID then VALIDATE — `d5b8a2c60e17`'s locking shape, on an empty new table."""
    name = f"fk_{table}_{column}_{referred}"
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) "
        f"REFERENCES {referred} (id) ON DELETE {on_delete} NOT VALID"
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.add_column(
        "inbound_webhooks",
        sa.Column(
            "consent_basis", sa.String(length=16), server_default="inquiry", nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_inbound_webhooks_consent_basis_enum"),
        "inbound_webhooks",
        "consent_basis IN ('inquiry', 'application')",
    )

    op.create_table(
        DESK,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_request_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("closed_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(f"kind IN {_KINDS!r}", name=op.f(f"ck_{DESK}_kind_enum")),
        sa.CheckConstraint(f"channel IN {_CHANNELS!r}", name=op.f(f"ck_{DESK}_channel_enum")),
        sa.CheckConstraint(f"status IN {_STATUSES!r}", name=op.f(f"ck_{DESK}_status_enum")),
        sa.CheckConstraint(
            f"outcome IS NULL OR outcome IN {_OUTCOMES!r}", name=op.f(f"ck_{DESK}_outcome_enum")
        ),
        sa.CheckConstraint(
            "due_at = received_at + interval '90 days'",
            name=op.f(f"ck_{DESK}_due_after_response_days"),
        ),
        sa.CheckConstraint(
            "((status = 'open') = (closed_at IS NULL)) AND ((status = 'open') = (outcome IS NULL))",
            name=op.f(f"ck_{DESK}_closed_is_complete"),
        ),
        sa.CheckConstraint(
            "subject_ref ~ '^[0-9a-f]{32}$'", name=op.f(f"ck_{DESK}_subject_ref_shape")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{DESK}")),
    )
    op.create_index(
        "ix_data_rights_requests_open_due",
        DESK,
        ["tenant_id", "due_at"],
        postgresql_where=sa.text("status = 'open'"),
    )
    _fk(DESK, "tenant_id", "organizations", "RESTRICT")
    _fk(DESK, "deletion_request_id", "deletion_requests", "SET NULL")
    _fk(DESK, "created_by", "users", "SET NULL")
    _fk(DESK, "closed_by", "users", "SET NULL")
    op.execute(f"ALTER TABLE {DESK} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {DESK} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {DESK} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {DESK}")
    op.drop_table(DESK)
    op.drop_constraint(
        op.f("ck_inbound_webhooks_consent_basis_enum"), "inbound_webhooks", type_="check"
    )
    op.drop_column("inbound_webhooks", "consent_basis")
