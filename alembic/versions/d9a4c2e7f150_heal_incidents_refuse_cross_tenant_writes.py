"""heal_incidents: no session may rewrite another client's incident, re-tenant one, or delete one

Revision ID: d9a4c2e7f150
Revises: c3e8f1a7b952
Create Date: 2026-10-10 12:00:00.000000

`heal_incidents` is RLS-exempt (registry: a tenant policy would hide the platform
incidents and let a client read the operator's history), and until now it had no write
guard at all. That allowed two things:
- a session scoped to tenant A could UPDATE or DELETE tenant B's incident;
- an untenanted session could re-address an incident to another client.
`tests/rls_sweep_test.py` asserts both are refused on every exempt table.

Why a trigger, not a policy:
- The healer's own writes are untenanted and legitimately touch client incidents: the
  lease claim, state changes and resolution, all keyed on id.
- An untenanted write policy cannot say "but never change tenant_id", because WITH CHECK
  sees only the NEW row.
- Adding any `tenant_isolation` policy would also make the healer's untenanted INSERT of
  a client's incident a 42501.
The trigger compares OLD with NEW, which a policy cannot:

- UPDATE: refused if tenant_id changes to another client (to NULL stays allowed: it is
  the FK's SET NULL when an organization is deleted); refused from a tenant session
  unless the row is that tenant's own (the client "restored by person" route resolves
  its own incident in its own session).
- DELETE: always refused. Nothing deletes an incident: `heal_actions` points at it ON
  DELETE RESTRICT, and the history is the record.

Raises P0001, the code the append-only triggers use.

DOWNGRADE: drops the trigger and its function, returning to no write guard.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d9a4c2e7f150"
down_revision: str | None = "c3e8f1a7b952"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "heal_incidents"
FUNCTION = "heal_incidents_write_guard"
TRIGGER = "heal_incidents_write_guard"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            guc uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'heal_incidents rows are never deleted'
                    USING ERRCODE = 'P0001';
            END IF;
            -- To NULL is allowed: it is the FK's ON DELETE SET NULL when a client's
            -- organization row goes, and detaching moves the incident to nobody.
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id AND NEW.tenant_id IS NOT NULL THEN
                RAISE EXCEPTION 'an incident cannot move to another client'
                    USING ERRCODE = 'P0001';
            END IF;
            IF guc IS NOT NULL AND OLD.tenant_id IS DISTINCT FROM guc THEN
                RAISE EXCEPTION 'a client session can change only its own incidents'
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER {TRIGGER} BEFORE UPDATE OR DELETE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()"
    )
    # ALWAYS: a session_replication_role of replica must not switch the guard off.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TRIGGER}")


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON {TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")
