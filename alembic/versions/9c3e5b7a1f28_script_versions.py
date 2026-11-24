"""Every saved version of a campaign's or inbound line's script (D-1039)

Revision ID: 9c3e5b7a1f28
Revises: f7a3c9d1b5e2
Create Date: 2026-11-24 22:00:00.000000

`script_versions`: one row per write of a holder's script (`campaigns/script_history`), with
who wrote it (`author`), whether it is the owner's own (`owner_made`), a short reason and
when. "Put back the flow from before Pip" restores the newest owner-made row. It replaces
`campaigns.script_before_pip` / `script_before_pip_at`, the single switch-back copy every
automatic pass overwrote; the code stops reading and writing them in this release and a later
release drops them (hard rule 8).

Exactly one of `campaign_id` / `inbound_line_id` is set; both CASCADE, so a holder's history
goes with it. Tenant data (the business's own script), FORCEd RLS in this migration
(hard rule 1).

BACKFILL, one tenant at a time under its own `app.tenant_id`: each campaign's switch-back
copy, when it differs from the script, and each campaign's and line's current script, as
`earlier` rows that are not owner-made, because who wrote them was never recorded. The owner
can restore either from the Versions list; "put back" waits for a version they save.

REVERSIBILITY. `downgrade()` drops the table; `script_before_pip` is untouched by this
migration, so the release before this one reads exactly what it wrote.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c3e5b7a1f28"
down_revision: str | None = "f7a3c9d1b5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "script_versions"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
AUTHORS = (
    "owner",
    "pip_draft",
    "pip_repair",
    "pip_outcomes",
    "pip_notices",
    "system",
    "restored",
    "copied",
    "earlier",
)

#: A uuid v7 in SQL, as `d8b2f5a7c3e1` builds it (Postgres 16 has none built in).
_UUID7 = (
    "encode(set_bit(set_bit(overlay(uuid_send(gen_random_uuid()) placing "
    "substring(int8send(floor(extract(epoch from clock_timestamp()) * 1000)::bigint) "
    "from 3) from 1 for 6), 52, 1), 53, 1), 'hex')::uuid"
)

_BACKFILL = f"""
DO $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
BEGIN
    FOR t IN SELECT id FROM organizations ORDER BY id LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        INSERT INTO {TABLE} (id, tenant_id, campaign_id, script, author, owner_made, reason,
                             created_at)
        SELECT {_UUID7}, c.tenant_id, c.id, c.script_before_pip, 'earlier', false,
               'The copy kept before Pip''s last change.',
               coalesce(c.script_before_pip_at, c.updated_at) - interval '1 millisecond'
          FROM campaigns c
         WHERE c.tenant_id = t AND c.script_before_pip IS NOT NULL
           AND c.script_before_pip IS DISTINCT FROM c.script;
        INSERT INTO {TABLE} (id, tenant_id, campaign_id, script, author, owner_made, reason,
                             created_at)
        SELECT {_UUID7}, c.tenant_id, c.id, c.script, 'earlier', false,
               'The script as it was when versions began.', c.updated_at
          FROM campaigns c
         WHERE c.tenant_id = t AND c.script IS NOT NULL;
        INSERT INTO {TABLE} (id, tenant_id, inbound_line_id, script, author, owner_made, reason,
                             created_at)
        SELECT {_UUID7}, l.tenant_id, l.id, l.script, 'earlier', false,
               'The script as it was when versions began.', l.updated_at
          FROM inbound_lines l
         WHERE l.tenant_id = t AND l.script IS NOT NULL;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    authors = ", ".join(f"'{a}'" for a in AUTHORS)
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
            "campaign_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "inbound_line_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("inbound_lines.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("script", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("owner_made", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("made_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("restored_from", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "num_nonnulls(campaign_id, inbound_line_id) = 1", name="one_holder"
        ),
        sa.CheckConstraint(f"author IN ({authors})", name="author_known"),
        sa.CheckConstraint("length(reason) <= 200", name="reason_short"),
    )
    op.create_index(
        "ix_script_versions_campaign",
        TABLE,
        ["campaign_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("campaign_id IS NOT NULL"),
    )
    op.create_index(
        "ix_script_versions_line",
        TABLE,
        ["inbound_line_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("inbound_line_id IS NOT NULL"),
    )
    op.create_index("ix_script_versions_tenant_id", TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    # The tenant list the walk loops over is read before any tenant is set, so under FORCE it
    # would be empty and the backfill would write nothing; the bracket lifts RLS for the
    # owner only and is restored before commit (`d3b71c9a5e08`).
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute(_BACKFILL)
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.drop_index("ix_script_versions_tenant_id", table_name=TABLE)
    op.drop_index("ix_script_versions_line", table_name=TABLE)
    op.drop_index("ix_script_versions_campaign", table_name=TABLE)
    op.drop_table(TABLE)
