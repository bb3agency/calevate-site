"""One ThinnestAI customer workspace per client (D-693)

Revision ID: d93b6f2a4c18
Revises: a7c3e91d5f20
Create Date: 2026-10-09 09:00:00.000000

Every client gets its own ThinnestAI customer workspace (`POST /customers`, reached with the
`Thinnest-Workspace: org_…` header, `thinnest-findings/mirror/snapshots/2026-10-08/pages/
api-reference/customers.md:18-91`), so its agents, numbers, contacts and do-not-call list
are its own and its numbers are rented in its own business name.

`tenant_engine_workspaces` maps a tenant to that workspace: our reference for it (the
customer's `externalId`, which is how provisioning finds a workspace it already made), the
`org_` id once it exists, where provisioning stands, and the workspace's business-details
application as last read (`phone-numbers/get-business-details.md`). One row per tenant.

`engine_number_purchases` is one number-purchase request, keyed by the caller's idempotency
key so a double-click buys one number: the intent is committed before the vendor is asked to
rent, and the outcome is written after, so a lost response is finished rather than repeated.

`engine_voice_clone_copies` maps one of our cloned voices to its copy in a client's
workspace: clones are per workspace, so a client speaking a clone needs its own.

`platform_voice_catalog.sample_object_key` points at the sealed recording a clone was made
from, kept so the clone can be made again in a client's workspace.

All three new tables carry `tenant_id` with the standard FORCEd `tenant_isolation` policy
(hard rule 1); the cross-tenant proofs are in `tests/engine_workspace_test.py`. The workspace
table also has the untenanted READ arm `c3f7b21a94e8` introduced (`<guc> IS NULL`, never
`true`): the provisioning and reconciliation sweeps list every tenant's workspace from the
directory session, and a session scoped to tenant A still sees nothing of B. Writes stay
strict.

DOWNGRADE drops the three tables and the column. It loses which workspace each client was
given (the workspaces themselves stay at the vendor and are found again by their
`externalId`), every purchase request record (the numbers stay recorded in `phone_numbers`),
the clone copies' ids (re-made on the next publish) and the pointer to each stored clone
sample (the objects stay in the bucket under `voice-clone-samples/`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d93b6f2a4c18"
down_revision: str | None = "a7c3e91d5f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY = (
    "CREATE POLICY tenant_isolation ON {table} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

_UNTENANTED = "NULLIF(current_setting('app.tenant_id', true), '') IS NULL"

_WORKSPACE_STATUSES = "'pending', 'active', 'plan_limit', 'failed', 'offboarding', 'deleted'"
_BUSINESS_STATUSES = (
    "'none', 'draft', 'submitted', 'accepted', 'rejected', 'suspended', 'expired', 'unknown'"
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "tenant_engine_workspaces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("business_status", sa.Text(), nullable=True),
        sa.Column(
            "business_can_rent", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("business_review_note", sa.Text(), nullable=True),
        sa.Column("business_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("business_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("business_document_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            f"status IN ({_WORKSPACE_STATUSES})",
            name=op.f("ck_tenant_engine_workspaces_status_enum"),
        ),
        sa.CheckConstraint(
            f"business_status IS NULL OR business_status IN ({_BUSINESS_STATUSES})",
            name=op.f("ck_tenant_engine_workspaces_business_status_enum"),
        ),
        sa.CheckConstraint(
            "workspace_id IS NULL OR workspace_id ~ '^org_[^@[:space:]]{1,120}$'",
            name=op.f("ck_tenant_engine_workspaces_workspace_id_shape"),
        ),
        sa.CheckConstraint(
            "status <> 'active' OR workspace_id IS NOT NULL",
            name=op.f("ck_tenant_engine_workspaces_active_has_workspace"),
        ),
        sa.CheckConstraint(
            "external_ref ~ '^[A-Za-z0-9._:-]{1,128}$'",
            name=op.f("ck_tenant_engine_workspaces_external_ref_shape"),
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL OR char_length(last_error_code) <= 64",
            name=op.f("ck_tenant_engine_workspaces_error_code_bounded"),
        ),
        sa.CheckConstraint(
            "business_review_note IS NULL OR char_length(business_review_note) <= 2000",
            name=op.f("ck_tenant_engine_workspaces_review_note_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_tenant_engine_workspaces_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_engine_workspaces")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_tenant_engine_workspaces_tenant_id")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_tenant_engine_workspaces_external_ref")),
        sa.UniqueConstraint("workspace_id", name=op.f("uq_tenant_engine_workspaces_workspace_id")),
    )
    op.execute("ALTER TABLE tenant_engine_workspaces ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_engine_workspaces FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY.format(table="tenant_engine_workspaces"))
    op.execute(
        "CREATE POLICY tenant_engine_workspaces_directory_read ON tenant_engine_workspaces "
        f"FOR SELECT USING ({_UNTENANTED})"
    )

    op.create_table(
        "engine_number_purchases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("vendor_number", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'renting'"), nullable=False),
        sa.Column("number_id", sa.UUID(), nullable=True),
        sa.Column("refusal_code", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('renting', 'recorded', 'refused', 'failed')",
            name=op.f("ck_engine_number_purchases_status_enum"),
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound', 'both')",
            name=op.f("ck_engine_number_purchases_direction_enum"),
        ),
        sa.CheckConstraint(
            "requested_by IN ('client', 'admin')",
            name=op.f("ck_engine_number_purchases_requested_by_enum"),
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9_-]{8,100}$'",
            name=op.f("ck_engine_number_purchases_idempotency_key_shape"),
        ),
        sa.CheckConstraint(
            "vendor_number ~ '^[0-9]{8,15}$'",
            name=op.f("ck_engine_number_purchases_vendor_number_digits"),
        ),
        sa.CheckConstraint(
            "status <> 'recorded' OR number_id IS NOT NULL",
            name=op.f("ck_engine_number_purchases_recorded_has_number"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_engine_number_purchases_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["number_id"],
            ["phone_numbers.id"],
            name=op.f("fk_engine_number_purchases_number_id_phone_numbers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engine_number_purchases")),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name=op.f("uq_engine_number_purchases_tenant_id_idempotency_key"),
        ),
    )
    op.execute("ALTER TABLE engine_number_purchases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE engine_number_purchases FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY.format(table="engine_number_purchases"))

    op.create_table(
        "engine_voice_clone_copies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("voice_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("vendor_voice_id", sa.Text(), nullable=False),
        sa.Column("vendor_clone_id", sa.Text(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_engine_voice_clone_copies_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engine_voice_clone_copies")),
        sa.UniqueConstraint(
            "tenant_id",
            "voice_id",
            "workspace_id",
            name=op.f("uq_engine_voice_clone_copies_tenant_id_voice_id_workspace_id"),
        ),
    )
    op.execute("ALTER TABLE engine_voice_clone_copies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE engine_voice_clone_copies FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY.format(table="engine_voice_clone_copies"))

    op.add_column(
        "platform_voice_catalog", sa.Column("sample_object_key", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("platform_voice_catalog", "sample_object_key")
    op.drop_table("engine_voice_clone_copies")
    op.drop_table("engine_number_purchases")
    op.drop_table("tenant_engine_workspaces")
