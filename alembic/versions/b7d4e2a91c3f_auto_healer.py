"""The auto-healer: incidents, its ledger, per-agent health, line protection (D-701)

Revision ID: b7d4e2a91c3f
Revises: f8b3d6a2c917
Create Date: 2026-10-09 23:30:00.000000

1. `heal_incidents`: one row per problem the healer is working on. Platform machinery read
   only by operators, so no RLS (`db/registry.RLS_EXEMPT_TENANT_COLUMNS`), like
   `platform_alerts`; `uq_heal_incidents_open_key` holds one unresolved incident per key.
2. `heal_actions`: every step any playbook took, append-only under
   `calevate_forbid_mutation`, like `audit_log`.
3. `heal_client_incidents`: the client's side of an incident, FORCE-RLS'd, with a
   `FOR SELECT` read for an untenanted session so the notice sweep can find which clients
   are owed a notice.
4. `heal_fallback_phones`: the owner-set phone callers are handed to while an agent is
   held (one per client, an Indian mobile).
5. `agent_health_windows`: fifteen-minute health windows of real calls per agent.
6. `heal_proposals`: behaviour changes waiting for a person.
7. `agents.inbound_silence_reason` gains `healer`; `campaigns.paused_by_heal_id` marks the
   pauses the healer must undo.

DOWNGRADE lifts every healer silence (its agents answer normally after their next publish
or the credit reconciler's next pass) and drops the tables: the incident history, the
ledger, the health windows, the proposals and the fallback phones are lost.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d4e2a91c3f"
down_revision: str | None = "f8b3d6a2c917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INCIDENTS = "heal_incidents"
ACTIONS = "heal_actions"
CLIENT = "heal_client_incidents"
PHONES = "heal_fallback_phones"
WINDOWS = "agent_health_windows"
PROPOSALS = "heal_proposals"
TENANT_TABLES = (CLIENT, PHONES, WINDOWS, PROPOSALS)

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
_UNTENANTED = f"({_GUC} IS NULL)"

SILENCE_CHECK = "ck_agents_inbound_silence_reason"
REASONS = ("credits", "truthful_answer_missing", "healer")
REASONS_BEFORE = ("credits", "truthful_answer_missing")


def _ts(*names: str) -> list[sa.Column[object]]:
    return [
        sa.Column(n, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
        for n in names
    ]


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _silence_check(reasons: Sequence[str]) -> str:
    return (
        "(inbound_silenced_at IS NULL) = (inbound_silence_reason IS NULL) "
        "AND (inbound_silence_reason IS NULL OR inbound_silence_reason IN ("
        + ", ".join(f"'{r}'" for r in reasons)
        + "))"
    )


def _tenant_fk(table: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_tenant_id_organizations")


def _rls(table: str, *, ops_read: bool = False) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    if ops_read:
        op.execute(f"CREATE POLICY {table}_ops_read ON {table} FOR SELECT USING {_UNTENANTED}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        INCIDENTS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("playbook", sa.String(length=64), nullable=False),
        sa.Column("trigger_code", sa.String(length=96), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("component", sa.String(length=16), nullable=True),
        sa.Column("public", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("public_title", sa.String(length=120), nullable=True),
        sa.Column("last_outcome", sa.String(length=64), nullable=True),
        *_ts("opened_at"),
        sa.Column("mitigated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint(
            _in("scope", ("agent", "tenant", "platform")), name=op.f(f"ck_{INCIDENTS}_scope_enum")
        ),
        sa.CheckConstraint(
            _in("state", ("open", "mitigated", "escalated", "resolved")),
            name=op.f(f"ck_{INCIDENTS}_state_enum"),
        ),
        sa.CheckConstraint(
            "component IS NULL OR "
            + _in("component", ("calls", "dashboard", "numbers", "assistant")),
            name=op.f(f"ck_{INCIDENTS}_component_enum"),
        ),
        sa.CheckConstraint(
            "NOT public OR public_title IS NOT NULL", name=op.f(f"ck_{INCIDENTS}_public_has_title")
        ),
        sa.CheckConstraint(
            "(state = 'resolved') = (resolved_at IS NOT NULL)",
            name=op.f(f"ck_{INCIDENTS}_resolved_iff"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f(f"ck_{INCIDENTS}_attempts_nonnegative")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{INCIDENTS}_tenant_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{INCIDENTS}_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{INCIDENTS}")),
    )
    op.create_index(
        "uq_heal_incidents_open_key",
        INCIDENTS,
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "ix_heal_incidents_due",
        INCIDENTS,
        ["next_attempt_at"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index("ix_heal_incidents_opened", INCIDENTS, [sa.text("opened_at DESC")])

    op.create_table(
        ACTIONS,
        sa.Column("id", sa.UUID(), nullable=False),
        *_ts("at"),
        sa.Column("incident_id", sa.UUID(), nullable=True),
        sa.Column("playbook", sa.String(length=64), nullable=False),
        sa.Column("step", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("alarm_code", sa.String(length=96), nullable=True),
        sa.Column("alert_id", sa.UUID(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(length=16), server_default="healer", nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            _in(
                "step",
                (
                    "schedule",
                    "act",
                    "verify",
                    "undo",
                    "escalate",
                    "protect",
                    "restore",
                    "notify",
                    "propose",
                    "decide",
                ),
            ),
            name=op.f(f"ck_{ACTIONS}_step_enum"),
        ),
        sa.CheckConstraint(
            _in("outcome", ("ok", "failed", "skipped", "refused")),
            name=op.f(f"ck_{ACTIONS}_outcome_enum"),
        ),
        sa.CheckConstraint(
            _in("actor_type", ("healer", "admin", "user")),
            name=op.f(f"ck_{ACTIONS}_actor_type_enum"),
        ),
        sa.CheckConstraint(
            "detail IS NULL OR length(detail) <= 500", name=op.f(f"ck_{ACTIONS}_detail_cap")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["heal_incidents.id"], name=op.f(f"fk_{ACTIONS}_incident_id_heal_incidents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ACTIONS}")),
    )
    op.create_index("ix_heal_actions_at", ACTIONS, [sa.text("at DESC")])
    op.create_index("ix_heal_actions_incident", ACTIONS, ["incident_id", "at"])
    op.create_index("ix_heal_actions_playbook_at", ACTIONS, ["playbook", sa.text("at DESC")])
    op.create_index(
        "ix_heal_actions_alert",
        ACTIONS,
        ["alert_id"],
        postgresql_where=sa.text("alert_id IS NOT NULL"),
    )
    op.execute(
        f"CREATE TRIGGER {ACTIONS}_append_only BEFORE UPDATE OR DELETE ON {ACTIONS} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {ACTIONS}_forbid_truncate BEFORE TRUNCATE ON {ACTIONS} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {ACTIONS} ENABLE ALWAYS TRIGGER {ACTIONS}_append_only")
    op.execute(f"ALTER TABLE {ACTIONS} ENABLE ALWAYS TRIGGER {ACTIONS}_forbid_truncate")

    op.create_table(
        CLIENT,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("protection", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("state", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("campaigns_paused", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requeued", sa.Integer(), server_default="0", nullable=False),
        sa.Column("missed_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("must_act", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_ts("opened_at"),
        sa.Column("protected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_by", sa.String(length=32), nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint(
            _in("kind", ("agent_unwell", "line_protected", "platform_outage")),
            name=op.f(f"ck_{CLIENT}_kind_enum"),
        ),
        sa.CheckConstraint(
            _in("protection", ("none", "paused", "forwarded")),
            name=op.f(f"ck_{CLIENT}_protection_enum"),
        ),
        sa.CheckConstraint("state IN ('open', 'resolved')", name=op.f(f"ck_{CLIENT}_state_enum")),
        sa.CheckConstraint(
            "(state = 'resolved') = (resolved_at IS NOT NULL)",
            name=op.f(f"ck_{CLIENT}_resolved_iff"),
        ),
        sa.CheckConstraint(
            "campaigns_paused >= 0 AND requeued >= 0 AND missed_calls >= 0",
            name=op.f(f"ck_{CLIENT}_counts_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["heal_incidents.id"],
            name=op.f(f"fk_{CLIENT}_incident_id_heal_incidents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f(f"fk_{CLIENT}_agent_id_agents"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{CLIENT}")),
        sa.UniqueConstraint(
            "incident_id",
            "tenant_id",
            "agent_id",
            name=op.f(f"uq_{CLIENT}_incident_id_tenant_id_agent_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_heal_client_incidents_tenant_recent", CLIENT, ["tenant_id", sa.text("opened_at DESC")]
    )
    op.create_index(
        "ix_heal_client_incidents_open_agent",
        CLIENT,
        ["agent_id"],
        postgresql_where=sa.text("state = 'open'"),
    )
    _tenant_fk(CLIENT)
    _rls(CLIENT, ops_read=True)

    op.create_table(
        PHONES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint(
            r"phone_e164 ~ '^\+91[6-9][0-9]{9}$'", name=op.f(f"ck_{PHONES}_phone_india_mobile")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PHONES}")),
        sa.UniqueConstraint("tenant_id", name=op.f(f"uq_{PHONES}_tenant_id")),
    )
    _tenant_fk(PHONES)
    _rls(PHONES)

    op.create_table(
        WINDOWS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in (
                "calls",
                "short_calls",
                "failed_calls",
                "slow_starts",
                "escalations",
                "knowledge_misses",
                "action_failures",
                "language_misses",
            )
        ],
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("baseline", sa.Numeric(5, 2), nullable=True),
        sa.Column("deviating", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint(
            "calls >= 0 AND short_calls >= 0 AND failed_calls >= 0 AND slow_starts >= 0 "
            "AND escalations >= 0 AND knowledge_misses >= 0 AND action_failures >= 0 "
            "AND language_misses >= 0",
            name=op.f(f"ck_{WINDOWS}_counts_nonnegative"),
        ),
        sa.CheckConstraint("score >= 0 AND score <= 100", name=op.f(f"ck_{WINDOWS}_score_range")),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f(f"fk_{WINDOWS}_agent_id_agents"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{WINDOWS}")),
        sa.UniqueConstraint(
            "agent_id", "window_start", name=op.f(f"uq_{WINDOWS}_agent_id_window_start")
        ),
    )
    op.create_index(
        "ix_agent_health_windows_tenant_recent", WINDOWS, ["tenant_id", sa.text("window_start DESC")]
    )
    _tenant_fk(WINDOWS)
    _rls(WINDOWS)

    op.create_table(
        PROPOSALS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("incident_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint(
            _in("kind", ("rollback_prompt", "review_knowledge", "review_languages")),
            name=op.f(f"ck_{PROPOSALS}_kind_enum"),
        ),
        sa.CheckConstraint(
            _in("status", ("pending", "applied", "dismissed", "expired")),
            name=op.f(f"ck_{PROPOSALS}_status_enum"),
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)",
            name=op.f(f"ck_{PROPOSALS}_decided_iff_not_pending"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f(f"fk_{PROPOSALS}_agent_id_agents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["heal_incidents.id"],
            name=op.f(f"fk_{PROPOSALS}_incident_id_heal_incidents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PROPOSALS}")),
    )
    op.create_index(
        "uq_heal_proposals_one_pending",
        PROPOSALS,
        ["agent_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_heal_proposals_tenant_recent", PROPOSALS, ["tenant_id", sa.text("created_at DESC")]
    )
    _tenant_fk(PROPOSALS)
    _rls(PROPOSALS)

    op.drop_constraint(op.f(SILENCE_CHECK), "agents", type_="check")
    op.create_check_constraint(op.f(SILENCE_CHECK), "agents", _silence_check(REASONS))

    op.add_column("campaigns", sa.Column("paused_by_heal_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_campaigns_paused_by_heal_id_heal_incidents"),
        "campaigns",
        INCIDENTS,
        ["paused_by_heal_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(
        "fk_campaigns_paused_by_heal_id_heal_incidents", "campaigns", type_="foreignkey"
    )
    op.drop_column("campaigns", "paused_by_heal_id")
    # The FORCE bracket (`f4a2c7e19d63`): `agents` is FORCE-RLS'd, so without it this
    # UPDATE matches no rows and the narrower CHECK below cannot validate.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE agents SET inbound_silenced_at = NULL, inbound_silence_reason = NULL "
        "WHERE inbound_silence_reason = 'healer'"
    )
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    op.drop_constraint(op.f(SILENCE_CHECK), "agents", type_="check")
    op.create_check_constraint(op.f(SILENCE_CHECK), "agents", _silence_check(REASONS_BEFORE))
    for table in (PROPOSALS, WINDOWS, PHONES, CLIENT):
        op.execute(f"DROP POLICY IF EXISTS {table}_ops_read ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
    op.execute(f"DROP TRIGGER IF EXISTS {ACTIONS}_append_only ON {ACTIONS}")
    op.execute(f"DROP TRIGGER IF EXISTS {ACTIONS}_forbid_truncate ON {ACTIONS}")
    op.drop_table(ACTIONS)
    op.drop_table(INCIDENTS)
