"""A sender's record that it gave its access provider advance written notice of autodialling.

TCCCPR Regulation 4 (as amended) is relayed as requiring every Sender to notify the
Originating Access Provider, in advance and in writing, of the use of an Auto Dialer or
Robo-Calls and the intended objective of the calls. The obligation is the client's; this
table is our record that they say they met it, and the thing the outbound gate reads.

Revision ID: e5c1a70b93f4
Revises: d8a05e4c7b13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5c1a70b93f4"
down_revision = "d8a05e4c7b13"
branch_labels = None
depends_on = None

TABLE = "autodialer_notices"
POLICY = "tenant_isolation"
MUTATION_TRIGGER = f"{TABLE}_append_only"
TRUNCATE_TRIGGER = f"{TABLE}_forbid_truncate"

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
#: The canonical predicate (`05bba2f3c19c`), with NO `OR <guc> IS NULL` arm: that arm lets
#: an untenanted session read every tenant's rows and INSERT naming any tenant, which is
#: the hole `d8a05e4c7b13` closed on the table next door. Every reader here is
#: tenant-scoped.
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

# Spelled here rather than imported from `compliance.autodialer`, for the reason every
# migration spells its constants: this file is a snapshot of the schema on the day it ran,
# and a constant that moves later must not change what this migration did.
_STATES = ("notified", "withdrawn")


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
        sa.Column("state", sa.String(), nullable=False),
        # WHICH access provider was told. Free text and not a foreign key to anything of
        # ours: this is the client's own carrier relationship, which we do not model and
        # may never see — Model B holds no carrier account at all.
        sa.Column("access_provider", sa.Text(), nullable=False),
        # "the intended objective of such calls", which the regulation names as part of
        # the notice. Stored because it is half of what was notified; NOT matched against
        # a campaign, because whether the obligation is per objective is not stated in the
        # text we have.
        sa.Column("objective", sa.Text(), nullable=False),
        # A DATE, not a timestamp: what a letter is dated, in the client's own calendar.
        # An instant would invite a timezone question that the evidence cannot answer.
        sa.Column("notified_on", sa.Date(), nullable=False),
        sa.Column("notice_reference", sa.Text(), nullable=True),
        sa.Column(
            "recorded_by",
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
        sa.CheckConstraint("length(btrim(access_provider)) > 0", name="access_provider_present"),
        sa.CheckConstraint("length(btrim(objective)) > 0", name="objective_present"),
    )
    # The gate's own predicate: the LATEST row for one tenant. Descending on created_at so
    # the lookup is an index scan of one row rather than a sort of the tenant's history.
    op.create_index(
        f"ix_{TABLE}_latest_for_tenant",
        TABLE,
        ["tenant_id", sa.text("created_at DESC")],
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    # FORCE so the guarantee holds for the table owner too — without it the owner is exempt
    # and the policy is a suggestion (hard rule 1).
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    # Hard rule 4. A withdrawal is a new row; an UPDATE would destroy the only evidence
    # that the notice was live while last month's calls were placed, which is the whole
    # value of the record.
    op.execute(
        f"CREATE TRIGGER {MUTATION_TRIGGER} "
        f"BEFORE UPDATE OR DELETE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    # TRUNCATE is neither an UPDATE nor a DELETE, so the trigger above never sees it and
    # one statement would empty the evidence (`a2e9f31c605d`).
    op.execute(
        f"CREATE TRIGGER {TRUNCATE_TRIGGER} "
        f"BEFORE TRUNCATE ON {TABLE} "
        f"FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    # ENABLE ALWAYS so neither survives a session in replica mode.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {MUTATION_TRIGGER}")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TRUNCATE_TRIGGER}")


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TRUNCATE_TRIGGER} ON {TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {MUTATION_TRIGGER} ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.drop_index(f"ix_{TABLE}_latest_for_tenant", table_name=TABLE)
    op.drop_table(TABLE)
