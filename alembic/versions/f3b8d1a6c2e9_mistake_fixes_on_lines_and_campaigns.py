"""A mistake on real calls is fixed as a Pip draft on the line or campaign the call was on (D-1005)

Revision ID: f3b8d1a6c2e9
Revises: e2a7c9d4b6f1
Create Date: 2026-11-16 21:00:00.000000

An agent has no script of its own (D-997, D-1000), so the healer no longer writes a fix into
one and puts it live. It writes Pip's fix as a draft on the Inbound line or campaign whose
call showed the mistake, for the owner to review there:

* `agent_mistake_fixes.inbound_line_id` / `campaign_id`: where the fix's draft was written.
  Nullable, `ON DELETE SET NULL`; the table already carries FORCEd RLS and its policy reads
  `tenant_id`, so adding columns changes no policy.
* `agent_mistake_fixes.state` gains `proposed` (settled: the draft waits for the owner) and
  `ended_because` gains `no_job` (the call was on neither, so there is no script to fix).
* `heal_client_incidents.kind` gains `script_fix_proposed`, the owner's notice of that draft.

The agent script suggestion (`draft_script_proposal`) and the details drafted from its
written script (`draft_agent_fields`) are retired; so was `suggest_scripts_from_document` by
D-1002. A message for one of them still in the outbox is marked done here, so it does not
wait out `OUTBOX_UNKNOWN_JOB_GRACE` and reach the dead-letter queue as a fault.

`downgrade()` turns `proposed` fixes into `fixed`, `no_job` into `no_script_cause` and the
new notice into `script_fixed`, then restores the constraints and drops the columns. The
outbox messages marked done stay done: their jobs wrote suggestions no screen shows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from apps.api.db.migration_offline import execute_data_statement

revision: str = "f3b8d1a6c2e9"
down_revision: str | None = "e2a7c9d4b6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIXES = "agent_mistake_fixes"
CLIENT = "heal_client_incidents"

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
_OLD_STATES = ("fixing", "live", "fixed", "rolled_back", "needs_person")
_NEW_STATES = (*_OLD_STATES, "proposed")
_OLD_SETTLED = ("fixed", "rolled_back", "needs_person")
_NEW_SETTLED = (*_OLD_SETTLED, "proposed")
_OLD_ENDINGS = (
    "came_back",
    "worse",
    "owner",
    "no_script_cause",
    "waited_too_long",
    "attempts_spent",
    "script_changed",
    "agent_gone",
)
_NEW_ENDINGS = (*_OLD_ENDINGS, "no_job")
_OLD_KINDS = (
    "agent_unwell",
    "line_protected",
    "platform_outage",
    "script_fixed",
    "script_fix_waiting",
    "script_check_fixed",
    "script_check_waiting",
    "voice_switched",
)
_NEW_KINDS = (*_OLD_KINDS, "script_fix_proposed")
_RETIRED_JOBS = ("draft_script_proposal", "draft_agent_fields", "suggest_scripts_from_document")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _settled_iff(settled: tuple[str, ...]) -> str:
    return f"({_in('state', settled)}) = (settled_at IS NOT NULL)"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column, target in (("inbound_line_id", "inbound_lines"), ("campaign_id", "campaigns")):
        op.add_column(
            FIXES,
            sa.Column(
                column,
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(f"{target}.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    _replace_check(FIXES, "state_enum", _in("state", _NEW_STATES))
    _replace_check(FIXES, "settled_iff", _settled_iff(_NEW_SETTLED))
    _replace_check(
        FIXES, "ended_because_enum", f"ended_because IS NULL OR {_in('ended_because', _NEW_ENDINGS)}"
    )
    _replace_check(CLIENT, "kind_enum", _in("kind", _NEW_KINDS))
    op.execute("ALTER TABLE outbox_messages NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(
        sa.text(
            "UPDATE outbox_messages SET status = 'published', "
            "published_at = COALESCE(published_at, now()), consumed_at = now(), "
            "payload = '{}'::jsonb, locked_until = NULL, consume_by = NULL, updated_at = now() "
            f"WHERE {_in('job', _RETIRED_JOBS)} AND consumed_at IS NULL "
            "AND status IN ('pending', 'published')"
        ),
        note="Marked the retired agent-script jobs' outbox messages done.",
    )
    op.execute("ALTER TABLE outbox_messages FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {FIXES} NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(
        sa.text(
            f"UPDATE {FIXES} SET state = CASE state WHEN 'proposed' THEN 'fixed' ELSE state END, "
            "ended_because = CASE ended_because WHEN 'no_job' THEN 'no_script_cause' "
            "ELSE ended_because END, updated_at = now() "
            "WHERE state = 'proposed' OR ended_because = 'no_job'"
        ),
        note="Turned proposed fixes into fixed ones and no_job endings into no_script_cause.",
    )
    op.execute(f"ALTER TABLE {FIXES} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {CLIENT} NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(
        sa.text(
            f"UPDATE {CLIENT} SET kind = 'script_fixed', updated_at = now() "
            "WHERE kind = 'script_fix_proposed'"
        ),
        note="Turned the proposed-fix notices into script-fixed notices.",
    )
    op.execute(f"ALTER TABLE {CLIENT} FORCE ROW LEVEL SECURITY")
    _replace_check(CLIENT, "kind_enum", _in("kind", _OLD_KINDS))
    _replace_check(
        FIXES, "ended_because_enum", f"ended_because IS NULL OR {_in('ended_because', _OLD_ENDINGS)}"
    )
    _replace_check(FIXES, "settled_iff", _settled_iff(_OLD_SETTLED))
    _replace_check(FIXES, "state_enum", _in("state", _OLD_STATES))
    op.drop_column(FIXES, "campaign_id")
    op.drop_column(FIXES, "inbound_line_id")
