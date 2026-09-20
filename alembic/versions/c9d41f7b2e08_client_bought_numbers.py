"""A number a client buys: which legs it is for, when it became usable, what it costs them.

Revision ID: c9d41f7b2e08
Revises: b7e4c02fa519
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9d41f7b2e08"
down_revision = "b7e4c02fa519"
branch_labels = None
depends_on = None

HOLDERS = "number_holders"
PRICES = "number_price_attestations"
POLICY = "tenant_isolation"

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
# NO `OR <guc> IS NULL` ESCAPE ARM, unlike the sibling table this was drafted from. On a
# FOR ALL policy that arm hands an UNTENANTED session the WRITE — it can insert a row
# naming any tenant it likes — which is what `check_rls_coverage._check_untenanted_write`
# refuses by name. Nothing needs to read a holder across tenants: every caller here opens
# a `tenant_session`, and an operator's own read of a client's numbers does too.
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

# Spelled here rather than imported, for the reason every migration spells its constants:
# this file is a snapshot of the schema on the day it ran.
_DIRECTIONS = ("inbound", "outbound", "both")
_HOLDER_TYPES = ("individual", "business")


def _make_immutable(table: str) -> None:
    """Both triggers, both ALWAYS — hard rule 4's full shape (migration a2e9f31c605d).

    A row trigger never fires on TRUNCATE, which removes rows without producing any, so a
    ledger with only the row trigger is emptiable by one word. And the default ORIGIN
    enablement is skipped entirely by a session in `session_replication_role = replica`,
    which protects the ledger from the wrong attacker.
    """
    op.execute(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_forbid_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_append_only")
    op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_forbid_truncate")


def upgrade() -> None:
    op.add_column(
        "phone_numbers",
        sa.Column("direction", sa.String(), nullable=False, server_default="inbound"),
    )
    # Spelled as DDL rather than `op.create_check_constraint`, so the constraint's name is
    # this file's and not whatever naming convention is configured on the day it runs —
    # `downgrade()` has to drop it by that exact name.
    op.execute(
        "ALTER TABLE phone_numbers ADD CONSTRAINT ck_phone_numbers_direction_enum "
        f"CHECK (direction IN {_DIRECTIONS!r})"
    )
    op.add_column(
        "phone_numbers", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "phone_numbers", sa.Column("client_inr_per_month", sa.Numeric(12, 2), nullable=True)
    )
    # EVERY NUMBER THAT ALREADY EXISTS IS ACTIVE, and leaving them NULL would be the
    # expensive kind of wrong: `activated_at IS NULL` is what refuses to bind a number to
    # an agent, so a backfill-free upgrade would unbind — on the next attach — every
    # connection this platform already answers. They predate the rule; they are not
    # evidence that nobody verified.
    #
    # BRACKETED IN `NO FORCE`, because without it the statement matches ZERO rows and
    # reports success: the owner is subject to `tenant_isolation`, which is fail-closed on
    # an unset `app.tenant_id`, and a migration has no tenant. `d3b71c9a5e08` argues why
    # the bracket is safe — it lifts RLS for the OWNER only, `calevate_app` is NOSUPERUSER
    # NOBYPASSRLS and keeps every policy, and DDL is transactional so FORCE is back before
    # commit.
    op.execute("ALTER TABLE phone_numbers NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE phone_numbers SET activated_at = created_at WHERE activated_at IS NULL")
    op.execute("ALTER TABLE phone_numbers FORCE ROW LEVEL SECURITY")

    op.create_table(
        HOLDERS,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("holder_type", sa.String(), nullable=False),
        sa.Column("holder_name", sa.Text(), nullable=False),
        sa.Column("holder_email", sa.Text(), nullable=False),
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
        sa.CheckConstraint(f"holder_type IN {_HOLDER_TYPES!r}", name="holder_type_enum"),
        sa.CheckConstraint("length(btrim(holder_name)) > 0", name="holder_name_present"),
        sa.CheckConstraint("length(btrim(holder_email)) > 0", name="holder_email_present"),
    )
    op.execute(f"ALTER TABLE {HOLDERS} ENABLE ROW LEVEL SECURITY")
    # FORCE so the guarantee holds for the table owner too — without it the owner is exempt
    # and the policy is a suggestion (hard rule 1).
    op.execute(f"ALTER TABLE {HOLDERS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {HOLDERS} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    _make_immutable(HOLDERS)

    # PLATFORM-SCOPED: one attested rate for every client, so no tenant_id and no policy.
    op.create_table(
        PRICES,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("inr_per_month", sa.Numeric(12, 2), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
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
        sa.CheckConstraint("inr_per_month > 0", name="inr_per_month_positive"),
        sa.CheckConstraint("length(btrim(source)) > 0", name="source_present"),
    )
    # The read is always "the newest one". Descending, so it is a one-row index scan
    # rather than a sort of the rate's whole history.
    op.create_index(f"ix_{PRICES}_latest", PRICES, [sa.text("created_at DESC")])
    _make_immutable(PRICES)


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {PRICES}_forbid_truncate ON {PRICES}")
    op.execute(f"DROP TRIGGER IF EXISTS {PRICES}_append_only ON {PRICES}")
    op.drop_index(f"ix_{PRICES}_latest", table_name=PRICES)
    op.drop_table(PRICES)
    op.execute(f"DROP TRIGGER IF EXISTS {HOLDERS}_forbid_truncate ON {HOLDERS}")
    op.execute(f"DROP TRIGGER IF EXISTS {HOLDERS}_append_only ON {HOLDERS}")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {HOLDERS}")
    op.drop_table(HOLDERS)
    op.drop_column("phone_numbers", "client_inr_per_month")
    op.drop_column("phone_numbers", "activated_at")
    # Raw DDL both ways: `op.drop_constraint` re-applies the naming convention to a name
    # that already carries its prefix, and asks the database for
    # `ck_phone_numbers_ck_phone_numbers_direction_enum`.
    op.execute("ALTER TABLE phone_numbers DROP CONSTRAINT ck_phone_numbers_direction_enum")
    op.drop_column("phone_numbers", "direction")
