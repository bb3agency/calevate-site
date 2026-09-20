"""A client's recorded decision to dial outbound commercial calls from an ordinary DID.

Revision ID: b7e4c02fa519
Revises: a3f7d21c8b45
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e4c02fa519"
down_revision = "a3f7d21c8b45"
branch_labels = None
depends_on = None

TABLE = "outbound_sender_attestations"
POLICY = "tenant_isolation"

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT_OR_OPS = f"(tenant_id = ({_GUC})::uuid OR {_GUC} IS NULL)"

# Spelled here rather than imported from `agents.models`, for the reason every migration
# spells its constants: this file is a snapshot of the schema on the day it ran, and a
# constant that moves later must not change what this migration did.
_STATES = ("attested", "withdrawn")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "phone_number_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("phone_numbers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("statement_version", sa.Text(), nullable=False),
        sa.Column(
            "attested_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"state IN {_STATES!r}", name="state_enum"),
        sa.CheckConstraint(
            "length(btrim(statement_version)) > 0", name="statement_version_present"
        ),
    )
    op.create_index(op.f(f"ix_{TABLE}_tenant_id"), TABLE, ["tenant_id"])
    op.create_index(op.f(f"ix_{TABLE}_phone_number_id"), TABLE, ["phone_number_id"])
    # The gate's own predicate: the LATEST row for one number. Descending on created_at so
    # the lookup is an index scan of one row rather than a sort of a number's whole history.
    op.create_index(
        f"ix_{TABLE}_latest_for_number",
        TABLE,
        ["phone_number_id", sa.text("created_at DESC")],
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    # FORCE so the guarantee holds for the table owner too — without it the owner is exempt
    # and the policy is a suggestion (hard rule 1).
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT_OR_OPS} WITH CHECK {_OWN_TENANT_OR_OPS}"
    )
    # Hard rule 4. A withdrawal is a new row; an UPDATE would destroy the only evidence
    # that the earlier state ever existed, which is the whole value of the record.
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only "
        f"BEFORE UPDATE OR DELETE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_append_only ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.drop_index(f"ix_{TABLE}_latest_for_number", table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_phone_number_id"), table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_tenant_id"), table_name=TABLE)
    op.drop_table(TABLE)
