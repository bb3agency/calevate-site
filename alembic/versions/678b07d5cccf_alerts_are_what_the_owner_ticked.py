"""an agent's alert rule names its Hot outcomes instead of assuming them

Revision ID: 678b07d5cccf
Revises: e8b3d6a1f427
Create Date: 2026-11-05 12:00:00.000000

Until now an outcome that moves a lead to Hot alerted whatever the agent's saved rule said,
so a rule row seldom listed it (the screen showed it ticked and fixed). The rule is now
exactly what is ticked (`team_alerts.service`), so every saved rule gets the keys of its
agent's Hot outcomes written in; without this, those agents would silently stop alerting on
their best outcome. An agent with no saved rule needs nothing: its default is every positive
outcome, which includes the Hot ones.

DOWNGRADE takes the Hot keys back out. The earlier code alerts on a Hot outcome whether or not
its key is listed, so this changes no alert there, and the next upgrade writes them in again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "678b07d5cccf"
down_revision: str | None = "e8b3d6a1f427"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: One agent's Hot outcome keys as jsonb strings, from `a.business_outcomes`. An agent whose
#: outcomes are NULL reads the starting set, which has no Hot outcome.
_HOT_KEYS = (
    "SELECT e -> 'key' FROM jsonb_array_elements(a.business_outcomes) e "
    "WHERE jsonb_typeof(e) = 'object' AND e ->> 'lead_status' = 'hot' "
    "AND jsonb_typeof(e -> 'key') = 'string'"
)

_ADD_HOT = f"""
UPDATE team_alert_rules r
SET on_outcomes = r.on_outcomes || (
        SELECT jsonb_agg(k) FROM ({_HOT_KEYS}) AS hot(k)
        WHERE NOT r.on_outcomes @> jsonb_build_array(k)
    ),
    updated_at = now()
FROM agents a
WHERE a.id = r.agent_id
  AND jsonb_typeof(a.business_outcomes) = 'array'
  AND EXISTS (SELECT 1 FROM ({_HOT_KEYS}) AS hot(k) WHERE NOT r.on_outcomes @> jsonb_build_array(k))
"""

_REMOVE_HOT = f"""
UPDATE team_alert_rules r
SET on_outcomes = COALESCE((
        SELECT jsonb_agg(item ORDER BY pos)
        FROM jsonb_array_elements(r.on_outcomes) WITH ORDINALITY AS listed(item, pos)
        WHERE item NOT IN ({_HOT_KEYS})
    ), '[]'::jsonb),
    updated_at = now()
FROM agents a
WHERE a.id = r.agent_id
  AND jsonb_typeof(a.business_outcomes) = 'array'
  AND EXISTS (SELECT 1 FROM ({_HOT_KEYS}) AS hot(k) WHERE r.on_outcomes @> jsonb_build_array(k))
"""


def _bracketed(statement: str, note: str) -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The bracket (d3b71c9a5e08): both tables are FORCE-RLS'd and the migration role is
    # subject to `tenant_isolation`, so without it the statement matches no rows.
    op.execute("ALTER TABLE team_alert_rules NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(sa.text(statement), note=note)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE team_alert_rules FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _bracketed(_ADD_HOT, note="Wrote each agent's Hot outcomes into its saved alert rule.")


def downgrade() -> None:
    _bracketed(_REMOVE_HOT, note="Took each agent's Hot outcomes back out of its alert rule.")
