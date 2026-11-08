"""An agent waits at least 10 seconds before asking whether the caller is still there

Revision ID: a7d3e9c1b5f2
Revises: f4b8c2e6a1d9
Create Date: 2026-11-08 12:00:00.000000

Founder's ruling, 6 Nov 2026: the agent must wait "at least 10 secs" before asking whether the
caller is still there. Calevate's own default was already 10-180 (`thinnest_nudge_after_seconds`),
but an agent's own `nudge_after_seconds` and an account's `default_nudge_after_seconds` could
still be 5-9 (the engine's own floor, migration e7c3a1f9d2b4).

- Every stored 1-9 is raised to 10. 0 ("never ask") and NULL (inherit) are untouched.
- The four CHECKs (`ck_agents_nudge_after_range`, `ck_organizations_default_nudge_after_range`)
  become `0 OR 10-180`, added NOT VALID and then validated, so the ACCESS EXCLUSIVE is brief.
- Each client with a live agent that the raise reaches (its own value, or an account default it
  may inherit) gets one tenant live-apply run (`agents/live_apply.py`), queued BEFORE the update
  from the same match, so its live agents carry the new wait from their next call — the way a
  save of the setting reaches them (`call_handling.set_*_call_handling`).

Both tables are FORCE-RLS'd, so the data statements run inside the FORCE bracket
(`f4a2c7e19d63`).

DOWNGRADE puts the 5-180 CHECKs back. The raised values stay 10, which the old range admits:
which rows held 5-9 is not recorded, so they cannot be put back.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "a7d3e9c1b5f2"
down_revision: str | None = "f4b8c2e6a1d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

REASON = "nudge_after_floor"
NEW_MIN = 10
OLD_MIN = 5

#: (table, column, constraint) — spelled out rather than imported: a migration is a snapshot.
_COLUMNS = (
    ("agents", "nudge_after_seconds", "ck_agents_nudge_after_range"),
    (
        "organizations",
        "default_nudge_after_seconds",
        "ck_organizations_default_nudge_after_range",
    ),
)


def _check(column: str, floor: int) -> str:
    return f"{column} IS NULL OR {column} = 0 OR ({column} >= {floor} AND {column} <= 180)"


def _below(column: str) -> str:
    return f"{column} BETWEEN 1 AND {NEW_MIN - 1}"


def _set_checks(floor: int) -> None:
    for table, column, name in _COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({_check(column, floor)}) NOT VALID"
        )
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    queued = execute_data_statement(
        sa.text(
            "WITH touched AS ("
            "SELECT DISTINCT a.tenant_id FROM agents a JOIN organizations o ON o.id = a.tenant_id "
            "WHERE a.deleted_at IS NULL AND a.status = 'live' AND a.engine_agent_ref IS NOT NULL "
            f"AND (a.{_below('nudge_after_seconds')} "
            f"OR (a.nudge_after_seconds IS NULL AND o.{_below('default_nudge_after_seconds')}))"
            "), runs AS ("
            "INSERT INTO live_apply_runs (id, scope, tenant_id, reasons) "
            f"SELECT gen_random_uuid(), 'tenant', tenant_id, '[\"{REASON}\"]'::jsonb "
            "FROM touched RETURNING id) "
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, min_revision, "
            "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
            "jsonb_build_object('run_id', id::text), 'pending', 0, :revision, now(), now() "
            "FROM runs"
        ).bindparams(revision=revision),
        note="Queued a live apply for each client whose live agent's wait is raised to 10 s.",
    )
    agents = execute_data_statement(
        sa.text(
            f"UPDATE agents SET nudge_after_seconds = {NEW_MIN}, updated_at = now() "
            f"WHERE {_below('nudge_after_seconds')}"
        ),
        note="Raised agents' own waits of 5-9 s to 10 s.",
    )
    accounts = execute_data_statement(
        sa.text(
            f"UPDATE organizations SET default_nudge_after_seconds = {NEW_MIN} "
            f"WHERE {_below('default_nudge_after_seconds')}"
        ),
        note="Raised account default waits of 5-9 s to 10 s.",
    )
    log.info(
        "nudge floor 10 s: %s agents and %s accounts raised, %s client live-apply runs queued",
        agents,
        accounts,
        queued,
    )
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    _set_checks(NEW_MIN)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _set_checks(OLD_MIN)
