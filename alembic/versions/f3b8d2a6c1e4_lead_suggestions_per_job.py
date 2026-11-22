"""Lead-detail suggestions belong to the job: each campaign and inbound line gets its own (D-1029)

Revision ID: f3b8d2a6c1e4
Revises: e2a7c4f9b1d3
Create Date: 2026-11-22 18:00:00.000000

D-1028 moved "What it notes" from the agent to the job a call does; the suggested changes to
that list (D-889) follow it. Each campaign and inbound line gets the five columns the agent
carried: the suggestions, the pass state, the hash of what the last pass read, the dismissed
fingerprints and when the pass last ended.

Data: the suggestions waiting on an agent and the ones its owner turned down are copied onto
each of that agent's open campaigns and lines, so nothing waiting disappears and nothing
turned down comes back. The inputs hash is not copied, so each job's first pass reads its own
calls afresh. The copy walks one tenant at a time under that tenant's `app.tenant_id`, because
all three tables are FORCE-RLS'd.

The agent columns stay until a later release drops them (hard rule 8). `downgrade()` drops
the new columns; the agent's own copies were never changed, so an older release reads exactly
what it read before.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3b8d2a6c1e4"
down_revision: str | None = "e2a7c4f9b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `agents.models.FIELD_SUGGESTION_STATES`, frozen at this revision.
_STATES = ("queued", "running", "done", "failed", "skipped")
#: `agents.models.MAX_FIELD_SUGGESTIONS` and `MAX_DISMISSED_SUGGESTIONS`, frozen.
_MAX_SUGGESTIONS = 6
_MAX_DISMISSED = 200
_TABLES = ("campaigns", "inbound_lines")

_COPY = """
DO $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
BEGIN
    FOR t IN SELECT id FROM organizations ORDER BY id LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE campaigns g SET field_suggestions = a.field_suggestions,
               field_suggestions_dismissed = a.field_suggestions_dismissed,
               field_suggestions_state = CASE WHEN a.field_suggestions IS NULL THEN NULL
                                              ELSE 'done' END,
               field_suggestions_at = a.field_suggestions_at
          FROM agents a
         WHERE g.tenant_id = t AND a.id = g.agent_id AND g.archived_at IS NULL
           AND (a.field_suggestions IS NOT NULL
                OR jsonb_array_length(a.field_suggestions_dismissed) > 0);
        UPDATE inbound_lines l SET field_suggestions = a.field_suggestions,
               field_suggestions_dismissed = a.field_suggestions_dismissed,
               field_suggestions_state = CASE WHEN a.field_suggestions IS NULL THEN NULL
                                              ELSE 'done' END,
               field_suggestions_at = a.field_suggestions_at
          FROM agents a
         WHERE l.tenant_id = t AND a.id = l.agent_id AND l.archived_at IS NULL
           AND (a.field_suggestions IS NOT NULL
                OR jsonb_array_length(a.field_suggestions_dismissed) > 0);
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("field_suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
        op.add_column(table, sa.Column("field_suggestions_state", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("field_suggestions_inputs", sa.Text(), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "field_suggestions_dismissed",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
        )
        op.add_column(
            table, sa.Column("field_suggestions_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_field_suggestions_shape"),
            table,
            "field_suggestions IS NULL OR (jsonb_typeof(field_suggestions) = 'array' "
            f"AND jsonb_array_length(field_suggestions) <= {_MAX_SUGGESTIONS})",
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_field_suggestions_dismissed_shape"),
            table,
            "jsonb_typeof(field_suggestions_dismissed) = 'array' "
            f"AND jsonb_array_length(field_suggestions_dismissed) <= {_MAX_DISMISSED}",
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_field_suggestions_state_enum"),
            table,
            f"field_suggestions_state IS NULL OR field_suggestions_state IN {_STATES!r}",
        )
    op.execute(_COPY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.drop_constraint(op.f(f"ck_{table}_field_suggestions_state_enum"), table, type_="check")
        op.drop_constraint(
            op.f(f"ck_{table}_field_suggestions_dismissed_shape"), table, type_="check"
        )
        op.drop_constraint(op.f(f"ck_{table}_field_suggestions_shape"), table, type_="check")
        op.drop_column(table, "field_suggestions_at")
        op.drop_column(table, "field_suggestions_dismissed")
        op.drop_column(table, "field_suggestions_inputs")
        op.drop_column(table, "field_suggestions_state")
        op.drop_column(table, "field_suggestions")
