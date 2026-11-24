"""Which calls alert after they end belongs to the job: each campaign and inbound line gets its own rule (D-1040)

Revision ID: b8e3f1c6d2a4
Revises: c4f1a8d2e7b3
Create Date: 2026-11-24 12:00:00.000000

What a call notes is its job's list (D-1028), so the answers worth telling the team about are
that job's. Each campaign and inbound line gets `team_alert_rule`: NULL until the owner saves
(every positive outcome of its agent), else `{on_outcomes, on_fields: [{key, values}]}`.

Data: every agent with a saved rule (`team_alert_rules`) has it copied onto each of its
campaigns and lines that has none yet, so nothing ticked is lost:

* the agent's outcomes, as they are (outcomes are the agent's, and each job's calls end on
  them);
* an agent-level answer, onto every job whose own list has that choice detail, keeping only
  the values that detail still offers (no other value can be noted);
* an answer that named this campaign or line (D-1007), onto that job alone, merged with the
  agent-level one of the same key.

The three tables are FORCE-RLS'd and the copy reads and writes across tenants in one pass, so
it runs inside a `NO FORCE` bracket (`d3b71c9a5e08`): it lifts RLS for the owner role only,
and DDL is transactional, so FORCE is back before commit.

`team_alert_rules.on_outcomes` and `on_fields` are left as they were and stop being read; a
later release drops them (hard rule 8). `downgrade()` drops the new columns, so an older
release reads exactly what it read before.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "b8e3f1c6d2a4"
down_revision: str | None = "c4f1a8d2e7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, the key a D-1007 trigger named it by).
_JOBS = (("campaigns", "campaign_id"), ("inbound_lines", "inbound_line_id"))
#: `team_alerts/service.MAX_FIELD_TRIGGERS`, frozen at this revision.
_MAX_FIELD_TRIGGERS = 10

_RULES = sa.text("SELECT agent_id, on_outcomes, on_fields FROM team_alert_rules")
_CAMPAIGNS = sa.text(
    "SELECT id, agent_id, extraction_fields FROM campaigns WHERE team_alert_rule IS NULL"
)
_LINES = sa.text(
    "SELECT id, agent_id, extraction_fields FROM inbound_lines WHERE team_alert_rule IS NULL"
)
_SET_CAMPAIGN = sa.text(
    "UPDATE campaigns SET team_alert_rule = CAST(:rule AS jsonb) WHERE id = :id"
)
_SET_LINE = sa.text(
    "UPDATE inbound_lines SET team_alert_rule = CAST(:rule AS jsonb) WHERE id = :id"
)


def job_rule(
    job_id: str, holder_key: str, fields: Any, outcomes: Any, triggers: Any
) -> dict[str, Any]:
    """The agent's saved rule as it applies to one of its jobs."""
    offered = {
        str(f["key"]): [str(v) for v in f.get("enum_values") or []]
        for f in fields or []
        if isinstance(f, dict) and f.get("type") == "enum" and f.get("key")
    }
    merged: dict[str, list[str]] = {}
    for trigger in triggers or []:
        if not isinstance(trigger, dict) or not trigger.get("key"):
            continue
        named = trigger.get("campaign_id") or trigger.get("inbound_line_id")
        if named and str(trigger.get(holder_key) or "") != job_id:
            continue
        key = str(trigger["key"])
        if key not in offered:
            continue
        kept = merged.setdefault(key, [])
        for value in trigger.get("values") or []:
            if str(value) in offered[key] and str(value) not in kept:
                kept.append(str(value))
    on_fields = [{"key": k, "values": v} for k, v in merged.items() if v]
    return {
        "on_outcomes": [str(k) for k in outcomes or []],
        "on_fields": on_fields[:_MAX_FIELD_TRIGGERS],
    }


def planned(rules: Any, jobs: Any, holder_key: str) -> list[tuple[Any, dict[str, Any]]]:
    """(job id, its rule) for each job, rows of `_CAMPAIGNS` or `_LINES`, whose agent has a
    saved rule, from rows of `_RULES`."""
    by_agent = {str(r[0]): (r[1], r[2]) for r in rules}
    out: list[tuple[Any, dict[str, Any]]] = []
    for job_id, agent_id, fields in jobs:
        saved = by_agent.get(str(agent_id))
        if saved is not None:
            out.append((job_id, job_rule(str(job_id), holder_key, fields, saved[0], saved[1])))
    return out


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, _key in _JOBS:
        op.add_column(
            table,
            sa.Column("team_alert_rule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_team_alert_rule_shape"),
            table,
            "team_alert_rule IS NULL OR (jsonb_typeof(team_alert_rule) = 'object' "
            "AND jsonb_typeof(team_alert_rule -> 'on_outcomes') = 'array' "
            "AND jsonb_typeof(team_alert_rule -> 'on_fields') = 'array')",
        )
    if probe_skipped_offline(
        "b8e3f1c6d2a4: the agents' saved alert rules were NOT copied onto their campaigns "
        "and lines (needs a connection); upgrade online to copy them"
    ):
        return
    bind = op.get_bind()
    op.execute("ALTER TABLE team_alert_rules NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE campaigns NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE inbound_lines NO FORCE ROW LEVEL SECURITY")
    try:
        rules = bind.execute(_RULES).all()
        for key, read, write in (
            ("campaign_id", _CAMPAIGNS, _SET_CAMPAIGN),
            ("inbound_line_id", _LINES, _SET_LINE),
        ):
            for job_id, rule in planned(rules, bind.execute(read).all(), key):
                bind.execute(write, {"rule": json.dumps(rule), "id": job_id})
    finally:
        op.execute("ALTER TABLE inbound_lines FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE campaigns FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE team_alert_rules FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, _key in _JOBS:
        op.drop_constraint(op.f(f"ck_{table}_team_alert_rule_shape"), table, type_="check")
        op.drop_column(table, "team_alert_rule")
