"""calling numbers: the client authorises, Calevate files (D-941 amended 30 Oct 2026)

Revision ID: c4e1a9b7d305
Revises: f2a9c4e7d613
Create Date: 2026-10-30 18:00:00.000000

The client cannot file with the telephone company behind a number it rents through us, so
it now confirms its calling numbers and authorises Calevate to declare them; we file. Two
changes follow:

* `a2p_number_filings`: OUR filing of a client's authorised numbers, append-only and
  tenant-scoped. Not our rows in `autodialer_notices`: the gate reads the latest row there
  as the client's own statement, and an operator's row would displace it.
* The D-941 announcement (inserted by `d941a2c7e5b3`, matched by its fixed id) gets the
  new wording and button. `platform_announcements` is platform-scoped with no RLS
  (`db/registry`), so the UPDATE needs no NO FORCE / FORCE bracket.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c4e1a9b7d305"
down_revision: str | None = "f2a9c4e7d613"
branch_labels: None = None
depends_on: None = None

TABLE = "a2p_number_filings"
POLICY = "tenant_isolation"
MUTATION_TRIGGER = f"{TABLE}_append_only"
TRUNCATE_TRIGGER = f"{TABLE}_forbid_truncate"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

ANNOUNCEMENTS = "platform_announcements"
ANNOUNCEMENT_ID = "019a33c0-d941-7000-8000-0000000d0941"
NEW_MESSAGE = (
    "From 17 Nov, the law needs the numbers your agent calls from to be registered. "
    "Confirm your calling numbers so your calls keep going."
)
NEW_LABEL = "Confirm numbers"
OLD_MESSAGE = (
    "From 17 Nov, automated calls may only come from numbers you have declared. "
    "Declare your calling numbers now so your calls keep going."
)
OLD_LABEL = "Declare numbers"


def _set_announcement(message: str, label: str) -> None:
    op.execute(
        sa.text(
            f"UPDATE {ANNOUNCEMENTS} SET message = :m, link_label = :l, updated_at = now() "
            f"WHERE id = '{ANNOUNCEMENT_ID}'"
        ).bindparams(m=message, l=label)
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("filed_clis", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("filed_on", sa.Date(), nullable=False),
        sa.Column("filing_reference", sa.Text(), nullable=False),
        sa.Column(
            "recorded_by_admin_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("cardinality(filed_clis) > 0", name="names_a_number"),
        sa.CheckConstraint("length(btrim(filing_reference)) > 0", name="reference_present"),
    )
    op.create_index(
        f"ix_{TABLE}_tenant_latest", TABLE, ["tenant_id", sa.text("created_at DESC")]
    )

    # Hard rule 1, in the same migration as the table.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    # Hard rule 4: a filing is evidence of when we declared a number; a correction is a new
    # row. TRUNCATE is refused separately (`a2e9f31c605d`), and both survive replica mode.
    op.execute(
        f"CREATE TRIGGER {MUTATION_TRIGGER} BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {TRUNCATE_TRIGGER} BEFORE TRUNCATE ON {TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {MUTATION_TRIGGER}")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TRUNCATE_TRIGGER}")

    _set_announcement(NEW_MESSAGE, NEW_LABEL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _set_announcement(OLD_MESSAGE, OLD_LABEL)

    # Bracketed: FORCE RLS and a fail-closed policy would hide every row from this check.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {TABLE}) THEN RAISE EXCEPTION "
        "'Calevate has recorded filings of clients'' calling numbers; the table is "
        "append-only evidence. Not downgraded.'; END IF; END $$"
    )
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP TRIGGER IF EXISTS {TRUNCATE_TRIGGER} ON {TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {MUTATION_TRIGGER} ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.drop_index(f"ix_{TABLE}_tenant_latest", table_name=TABLE)
    op.drop_table(TABLE)
