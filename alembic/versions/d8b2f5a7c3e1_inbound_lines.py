"""Inbound lines: what a phone number says when it is called, in one agent's voice (D-997)

Revision ID: d8b2f5a7c3e1
Revises: d7e3a9b2c4f1
Create Date: 2026-11-16 12:00:00.000000

Founder, 16 Nov 2026: the work owns the script and the agent is the voice. An inbound line is
the work of answering one or more of the business's numbers.

* `inbound_lines`: name, the agent whose voice answers, the owner's main task, the line's own
  call script (a `CallScript` as JSON, as `campaigns.script`), Pip's pending draft, what the
  line notes from each call, the agent's actions it switches off, and the line's own engine
  agent (`engine_agent_ref`). Archived, never deleted.
* `inbound_line_sources`: the sources from What your agents know a line was written from.
* `phone_numbers.inbound_line_id`: the line that answers the number. Several numbers may share
  one line.
* `engine_agent_routes.inbound_line_id` and `calls.inbound_line_id`: which line an engine agent
  and a call belong to, so intake can stamp the call.
* `engine_kb_routes.inbound_line_id`: a line's engine agent holds its own copy of each of the
  client's published sources (D-689), so a claim names that holder as it names an arm
  (`variant_id`) or a test copy (`test_copy`). No foreign key, as no column of that table has
  one: a claim must outlive the rows it names so the orphan sweep can still find the vendor
  object. UNIQUE `(source_id, agent_id, variant_id, test_copy, inbound_line_id) NULLS NOT
  DISTINCT` replaces the four-column holder index, because that is what `ON CONFLICT` on the
  five columns infers against.

EVERY NUMBER HAS A LINE (founder, 16 Nov 2026). Each agent that answers a number gets one line
in its voice, named after it, carrying the script it has live, and its numbers are put on it.
The lines are drafts: nothing on the calling platform changes, so callers hear exactly what
they heard, and a line answers with its own engine agent only once the owner puts it live.
The backfill walks one tenant at a time under that tenant's `app.tenant_id`, because every
table it touches is FORCE-RLS'd.

Both new tables are tenant data with FORCEd RLS in this migration (hard rule 1).
`downgrade()` reverses it, and refuses while a line holds a knowledge claim: the
narrower index would collide with the agent's own claim on the same source, and dropping the
claims would lose the only record of the vendor documents.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8b2f5a7c3e1"
down_revision: str | None = "d7e3a9b2c4f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LINES = "inbound_lines"
SOURCES = "inbound_line_sources"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
KB_ROUTES = "engine_kb_routes"
KB_HOLDER = "ux_engine_kb_routes_holder_kind"
KB_LINE_HOLDER = "ux_engine_kb_routes_holder_line"


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    ]


def _tenant() -> sa.Column[object]:
    return sa.Column(
        "tenant_id",
        sa.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _isolate(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {table} FOR ALL USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def _line_fk(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.UUID(as_uuid=True),
        sa.ForeignKey(f"{LINES}.id", ondelete="SET NULL"),
        nullable=True,
    )


#: A uuid v7 in SQL (Postgres 16 has no built-in): the millisecond clock in the first 48
#: bits, version 7 and the RFC 4122 variant set, the rest random. IDs are uuid v7 everywhere.
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
        INSERT INTO inbound_lines (id, tenant_id, name, agent_id, script, created_at, updated_at)
        SELECT {_UUID7}, a.tenant_id, left(a.name, 80), a.id, pv.structured_script, now(), now()
          FROM agents a
          LEFT JOIN prompt_versions pv ON pv.id = a.live_prompt_id
         WHERE a.tenant_id = t AND a.deleted_at IS NULL
           AND EXISTS (SELECT 1 FROM phone_numbers n WHERE n.agent_id = a.id
                        AND n.released_at IS NULL AND n.inbound_line_id IS NULL);
        UPDATE phone_numbers n SET inbound_line_id = l.id
          FROM inbound_lines l
         WHERE l.tenant_id = t AND n.tenant_id = t AND l.agent_id = n.agent_id
           AND n.released_at IS NULL AND n.inbound_line_id IS NULL;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        LINES,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "agent_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("main_task", sa.Text(), nullable=True),
        sa.Column("script", postgresql.JSONB(), nullable=True),
        sa.Column("script_proposal", postgresql.JSONB(), nullable=True),
        sa.Column(
            "extraction_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "actions_off",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("engine_agent_ref", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index(f"ix_{LINES}_tenant_id", LINES, ["tenant_id"])
    op.create_index(f"ix_{LINES}_agent", LINES, ["agent_id"])
    _isolate(LINES)

    op.create_table(
        SOURCES,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "inbound_line_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey(f"{LINES}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kb_source_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("kb_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "inbound_line_id", "kb_source_id", name=op.f(f"uq_{SOURCES}_line_source")
        ),
    )
    op.create_index(f"ix_{SOURCES}_tenant_id", SOURCES, ["tenant_id"])
    _isolate(SOURCES)

    op.add_column("phone_numbers", _line_fk("inbound_line_id"))
    op.create_index("ix_phone_numbers_inbound_line_id", "phone_numbers", ["inbound_line_id"])
    op.add_column("engine_agent_routes", sa.Column("inbound_line_id", sa.UUID(as_uuid=True)))
    op.add_column("calls", _line_fk("inbound_line_id"))
    op.create_index("ix_calls_inbound_line", "calls", ["inbound_line_id", "started_at"])

    op.add_column(KB_ROUTES, sa.Column("inbound_line_id", sa.UUID(as_uuid=True), nullable=True))
    op.execute(
        f"CREATE UNIQUE INDEX {KB_LINE_HOLDER} ON {KB_ROUTES} "
        "(source_id, agent_id, variant_id, test_copy, inbound_line_id) NULLS NOT DISTINCT"
    )
    op.execute(f"DROP INDEX {KB_HOLDER}")
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {KB_ROUTES} WHERE inbound_line_id IS NOT NULL) "
        "THEN RAISE EXCEPTION 'inbound lines hold knowledge claims in engine_kb_routes; retire "
        "the lines'' engine agents before downgrading'; END IF; END $$"
    )
    op.execute(
        f"CREATE UNIQUE INDEX {KB_HOLDER} ON {KB_ROUTES} "
        "(source_id, agent_id, variant_id, test_copy) NULLS NOT DISTINCT"
    )
    op.execute(f"DROP INDEX IF EXISTS {KB_LINE_HOLDER}")
    op.drop_column(KB_ROUTES, "inbound_line_id")
    op.drop_index("ix_calls_inbound_line", table_name="calls")
    op.drop_column("calls", "inbound_line_id")
    op.drop_column("engine_agent_routes", "inbound_line_id")
    op.drop_index("ix_phone_numbers_inbound_line_id", table_name="phone_numbers")
    op.drop_column("phone_numbers", "inbound_line_id")
    op.drop_table(SOURCES)
    op.drop_table(LINES)
