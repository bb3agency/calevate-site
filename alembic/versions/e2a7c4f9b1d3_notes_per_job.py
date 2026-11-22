"""What a call notes belongs to its job: every campaign and inbound line gets its own list (D-1028)

Revision ID: e2a7c4f9b1d3
Revises: c4f81a9d2e67
Create Date: 2026-11-22 12:00:00.000000

Founder, 22 Nov 2026: "What it notes" belongs to the job a call does, not to the agent, which
is only the voice. Until now an empty `campaigns.extraction_fields` or
`inbound_lines.extraction_fields` meant "note what the agent notes"; that fallback is removed
in the same release, so each campaign and line whose list is empty gets a copy of its
agent's current list (`agents.extraction_schema_id`, the version the post-call pipeline
read). Nothing notes less than it did. A list already set is left alone.

The copy walks one tenant at a time under that tenant's `app.tenant_id`, because all three
tables are FORCE-RLS'd. No schema changes: `extraction_schemas` stays until a later release
drops it (hard rule 8).

`downgrade()` changes no data. A copied list is indistinguishable from one the owner saved
afterwards, so emptying lists here could erase an owner's edit; and an older release reads a
non-empty list exactly as it reads an owner's own, so the copies are safe to leave.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e2a7c4f9b1d3"
down_revision: str | None = "c4f81a9d2e67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COPY = """
DO $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
BEGIN
    FOR t IN SELECT id FROM organizations ORDER BY id LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE campaigns g SET extraction_fields = es.fields
          FROM agents a JOIN extraction_schemas es ON es.id = a.extraction_schema_id
         WHERE g.tenant_id = t AND a.id = g.agent_id
           AND jsonb_array_length(g.extraction_fields) = 0
           AND jsonb_typeof(es.fields) = 'array' AND jsonb_array_length(es.fields) > 0;
        UPDATE inbound_lines l SET extraction_fields = es.fields
          FROM agents a JOIN extraction_schemas es ON es.id = a.extraction_schema_id
         WHERE l.tenant_id = t AND a.id = l.agent_id
           AND jsonb_array_length(l.extraction_fields) = 0
           AND jsonb_typeof(es.fields) = 'array' AND jsonb_array_length(es.fields) > 0;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_COPY)


def downgrade() -> None:
    # Deliberately no data change; the module docstring says why.
    pass
