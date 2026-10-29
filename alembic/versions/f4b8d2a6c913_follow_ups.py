"""follow-ups: journeys, frozen versions, runs and run events; Call new leads for every client

Revision ID: f4b8d2a6c913
Revises: c9d4e7a2b815
Create Date: 2026-10-30 12:00:00.000000

D-940 (founder, 30 Oct 2026), docs/FOLLOW-UPS.md.

* `follow_ups`, `follow_up_versions` (INSERT-only), `follow_up_runs`, `follow_up_run_events`
  (INSERT-only). Four tenant tables, each with FORCEd `tenant_isolation` here (hard rule 1);
  the two ledgers get `calevate_forbid_mutation` and `calevate_forbid_truncate`, ENABLE ALWAYS
  (hard rule 4). The cross-tenant zero-rows proof is `tests/follow_ups_rls_test.py`.
* `follow_up_scan(stale_s)`: the minute tick's worklist, one statement. A SECURITY INVOKER
  loop that binds `app.tenant_id` to one tenant per query (`call_reply_scan`'s shape); the
  tenant list comes from `organizations`, which only an `admin_session()` can enumerate.
* `team_alerts.trigger` admits `follow_up` (a Follow-up's "tell the team" step).
* THE DATA: every organisation gets a live "Call new leads" Follow-up, version 1, whose one
  call step carries its `lead_call_policies` agent, wait and retries (an organisation with
  no plan row: call at once with the lead source's agent, no retries — the default plan).
  `wait_minutes` is the wait rounded up to a minute and `wait_seconds` keeps it exactly.
  A NULL `agent_id` means the lead's own agent, which is what a plan with no calling agent
  did. `lead_call_policies.calling_agent_id`, `wait_seconds`, `retry_attempts` and
  `retry_interval_minutes` stop being written in this release and are dropped in a later
  one (hard rule 8).

Reversible. The downgrade writes each live "Call new leads" call step back into
`lead_call_policies` (so the old code calls new leads as the Follow-up did), turns
`follow_up` team alerts back into `after_call` ones, and drops the four tables and the
function.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4b8d2a6c913"
down_revision: str | None = "c9d4e7a2b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
TABLES = ("follow_ups", "follow_up_versions", "follow_up_runs", "follow_up_run_events")
LEDGERS = ("follow_up_versions", "follow_up_run_events")
FUNCTION = "follow_up_scan"

#: Frozen at this migration: what `definition.Settings()` and a new-lead trigger dump to.
_SETTINGS = (
    '{"goal": null, "stop_on_reply": true, "stop_on_won_lost": true, '
    '"again": "after_last", "max_days": 14, "starts_per_hour": null}'
)
_TRIGGER = '{"kind": "new_lead", "source_ids": null, "only_if": null}'


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_tenant_id_organizations"),
        ondelete="RESTRICT",
    )


def _jsonb(name: str, *, nullable: bool = False, default: str | None = None) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=nullable,
        server_default=sa.text(default) if default else None,
    )


def _force_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def _append_only(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_forbid_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_append_only")
    op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_forbid_truncate")


_SCAN_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(stale_s double precision)
RETURNS TABLE (
    scanned_tenant_id uuid,
    has_due boolean,
    has_dates boolean,
    has_open boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
BEGIN
    FOR t IN SELECT o.id FROM organizations o WHERE o.deleted_at IS NULL ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT t, x.due, x.dates, x.open FROM (
                SELECT
                    EXISTS (
                        SELECT 1 FROM follow_up_runs r JOIN follow_ups f ON f.id = r.follow_up_id
                        WHERE f.status = 'live' AND (
                            (r.status = 'waiting' AND r.wake_at <= now())
                            OR (r.status = 'running'
                                AND r.updated_at < now() - make_interval(secs => stale_s)))
                    ) AS due,
                    EXISTS (
                        SELECT 1 FROM follow_ups f
                        JOIN follow_up_versions v ON v.id = f.live_version_id
                        WHERE f.status = 'live' AND v.trigger->>'kind' = 'lead_date'
                    ) AS dates,
                    EXISTS (
                        SELECT 1 FROM follow_up_runs r WHERE r.status IN ('running', 'waiting')
                    ) AS open
            ) x
            WHERE x.due OR x.dates OR x.open;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""

_SEED_FOLLOW_UPS = f"""
INSERT INTO follow_ups (id, tenant_id, name, status, trigger, settings, starter)
SELECT gen_random_uuid(), o.id, 'Call new leads', 'draft', '{_TRIGGER}'::jsonb,
       '{_SETTINGS}'::jsonb, 'call_new_leads'
FROM organizations o
WHERE NOT EXISTS (
    SELECT 1 FROM follow_ups f WHERE f.tenant_id = o.id AND f.starter = 'call_new_leads'
)
"""

_SEED_VERSIONS = """
INSERT INTO follow_up_versions (id, tenant_id, follow_up_id, number, steps, trigger, settings)
SELECT gen_random_uuid(), f.tenant_id, f.id, 1,
       jsonb_build_array(jsonb_build_object(
           'id', 's1',
           'kind', 'call',
           'agent_id', p.calling_agent_id,
           'wait_minutes', ceil(coalesce(p.wait_seconds, 0) / 60.0)::int,
           'wait_seconds', coalesce(p.wait_seconds, 0),
           'retries', coalesce(p.retry_attempts, 0),
           'retry_minutes', coalesce(p.retry_interval_minutes, 60),
           'next', jsonb_build_object('answered', NULL, 'not_reached', NULL)
       )),
       f.trigger, f.settings
FROM follow_ups f
LEFT JOIN lead_call_policies p ON p.tenant_id = f.tenant_id
WHERE f.starter = 'call_new_leads' AND f.live_version_id IS NULL
"""

_GO_LIVE = """
UPDATE follow_ups f SET live_version_id = v.id, status = 'live', updated_at = now()
FROM follow_up_versions v
WHERE v.follow_up_id = f.id AND v.number = 1 AND f.live_version_id IS NULL
  AND f.starter = 'call_new_leads'
"""

_WRITE_BACK = """
UPDATE lead_call_policies p
SET calling_agent_id = (s.step->>'agent_id')::uuid,
    wait_seconds = coalesce((s.step->>'wait_seconds')::int, (s.step->>'wait_minutes')::int * 60),
    retry_attempts = (s.step->>'retries')::int,
    retry_interval_minutes = (s.step->>'retry_minutes')::int,
    updated_at = now()
FROM (
    SELECT f.tenant_id, v.steps->0 AS step FROM follow_ups f
    JOIN follow_up_versions v ON v.id = f.live_version_id
    WHERE f.starter = 'call_new_leads' AND f.status = 'live' AND v.steps->0->>'kind' = 'call'
) s
WHERE p.tenant_id = s.tenant_id
  AND coalesce((s.step->>'wait_seconds')::int, (s.step->>'wait_minutes')::int * 60) <= 3600
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "follow_ups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="draft", nullable=False),
        _jsonb("trigger"),
        _jsonb("settings", default="'{}'::jsonb"),
        _jsonb("draft", nullable=True),
        sa.Column("live_version_id", sa.UUID(), nullable=True),
        sa.Column("starter", sa.String(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('draft', 'live', 'paused', 'off')", name=op.f("ck_follow_ups_status_enum")
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 80", name=op.f("ck_follow_ups_name_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(trigger) = 'object'", name=op.f("ck_follow_ups_trigger_is_object")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(settings) = 'object'", name=op.f("ck_follow_ups_settings_is_object")
        ),
        sa.CheckConstraint(
            "draft IS NULL OR jsonb_typeof(draft) = 'array'", name=op.f("ck_follow_ups_draft_is_array")
        ),
        sa.CheckConstraint(
            "status NOT IN ('live', 'paused') OR live_version_id IS NOT NULL",
            name=op.f("ck_follow_ups_live_has_version"),
        ),
        sa.CheckConstraint(
            "starter IS NULL OR starter IN ('call_new_leads', 'qualify_new_leads', "
            "'missed_call_callback', 'appointment_reminder', 'payment_reminder', 'win_back')",
            name=op.f("ck_follow_ups_starter_enum"),
        ),
        _tenant_fk("follow_ups"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_follow_ups_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_ups")),
    )
    op.create_index(op.f("ix_follow_ups_tenant_id"), "follow_ups", ["tenant_id"])
    op.create_index(
        "uq_follow_ups_call_new_leads",
        "follow_ups",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("starter = 'call_new_leads'"),
    )

    op.create_table(
        "follow_up_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("follow_up_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        _jsonb("steps"),
        _jsonb("trigger"),
        _jsonb("settings"),
        sa.Column("published_by", sa.UUID(), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("number >= 1", name=op.f("ck_follow_up_versions_number_positive")),
        sa.CheckConstraint(
            "jsonb_typeof(steps) = 'array'", name=op.f("ck_follow_up_versions_steps_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(trigger) = 'object'",
            name=op.f("ck_follow_up_versions_trigger_is_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(settings) = 'object'",
            name=op.f("ck_follow_up_versions_settings_is_object"),
        ),
        _tenant_fk("follow_up_versions"),
        sa.ForeignKeyConstraint(
            ["follow_up_id"],
            ["follow_ups.id"],
            name=op.f("fk_follow_up_versions_follow_up_id_follow_ups"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_up_versions")),
        sa.UniqueConstraint("follow_up_id", "number", name="uq_follow_up_versions_number"),
    )
    op.create_index(op.f("ix_follow_up_versions_tenant_id"), "follow_up_versions", ["tenant_id"])
    op.create_foreign_key(
        "fk_follow_ups_live_version_id_follow_up_versions",
        "follow_ups",
        "follow_up_versions",
        ["live_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "follow_up_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("follow_up_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=True),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="waiting", nullable=False),
        sa.Column("step_id", sa.String(), nullable=False),
        sa.Column("wake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waiting_call_id", sa.UUID(), nullable=True),
        sa.Column("last_call_id", sa.UUID(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("trigger_ref", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(), nullable=True),
        sa.Column("goal_reached", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('running', 'waiting', 'done', 'stopped')",
            name=op.f("ck_follow_up_runs_status_enum"),
        ),
        sa.CheckConstraint("attempt >= 0", name=op.f("ck_follow_up_runs_attempt_not_negative")),
        sa.CheckConstraint(
            "(status IN ('done', 'stopped')) = (ended_at IS NOT NULL)",
            name=op.f("ck_follow_up_runs_ended_when_over"),
        ),
        sa.CheckConstraint(
            "end_reason IS NULL OR char_length(end_reason) <= 64",
            name=op.f("ck_follow_up_runs_end_reason_length"),
        ),
        _tenant_fk("follow_up_runs"),
        sa.ForeignKeyConstraint(
            ["follow_up_id"],
            ["follow_ups.id"],
            name=op.f("fk_follow_up_runs_follow_up_id_follow_ups"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["follow_up_versions.id"],
            name=op.f("fk_follow_up_runs_version_id_follow_up_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_follow_up_runs_lead_id_leads"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["waiting_call_id"],
            ["calls.id"],
            name=op.f("fk_follow_up_runs_waiting_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_call_id"],
            ["calls.id"],
            name=op.f("fk_follow_up_runs_last_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_up_runs")),
    )
    op.create_index(op.f("ix_follow_up_runs_tenant_id"), "follow_up_runs", ["tenant_id"])
    op.create_index(
        "uq_follow_up_runs_one_live",
        "follow_up_runs",
        ["follow_up_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('running', 'waiting') AND lead_id IS NOT NULL"),
    )
    op.create_index(
        "uq_follow_up_runs_trigger",
        "follow_up_runs",
        ["follow_up_id", "lead_id", "trigger_ref"],
        unique=True,
        postgresql_where=sa.text("lead_id IS NOT NULL"),
    )
    op.create_index(
        "uq_follow_up_runs_trigger_no_lead",
        "follow_up_runs",
        ["follow_up_id", "phone_e164", "trigger_ref"],
        unique=True,
        postgresql_where=sa.text("lead_id IS NULL"),
    )
    op.create_index(
        "ix_follow_up_runs_due",
        "follow_up_runs",
        ["tenant_id", "wake_at"],
        postgresql_where=sa.text("status = 'waiting' AND wake_at IS NOT NULL"),
    )
    op.create_index(
        "ix_follow_up_runs_follow_up",
        "follow_up_runs",
        ["follow_up_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_follow_up_runs_phone_live",
        "follow_up_runs",
        ["tenant_id", "phone_e164"],
        postgresql_where=sa.text("status IN ('running', 'waiting')"),
    )
    op.create_index(
        "ix_follow_up_runs_waiting_call",
        "follow_up_runs",
        ["waiting_call_id"],
        postgresql_where=sa.text("waiting_call_id IS NOT NULL"),
    )
    op.create_index(
        "ix_follow_up_runs_lead",
        "follow_up_runs",
        ["lead_id"],
        postgresql_where=sa.text("lead_id IS NOT NULL"),
    )

    op.create_table(
        "follow_up_run_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "char_length(result) <= 64", name=op.f("ck_follow_up_run_events_result_length")
        ),
        sa.CheckConstraint("char_length(kind) <= 32", name=op.f("ck_follow_up_run_events_kind_length")),
        _tenant_fk("follow_up_run_events"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["follow_up_runs.id"],
            name=op.f("fk_follow_up_run_events_run_id_follow_up_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_up_run_events")),
    )
    op.create_index(
        op.f("ix_follow_up_run_events_tenant_id"), "follow_up_run_events", ["tenant_id"]
    )
    op.create_index("ix_follow_up_run_events_run", "follow_up_run_events", ["run_id", "at"])
    op.create_index(
        "uq_follow_up_run_events_step",
        "follow_up_run_events",
        ["run_id", "step_id", "attempt", "kind"],
        unique=True,
    )

    # The data, before the new tables are policied; the two existing tables it reads are
    # FORCE-RLS'd, so they are opened for this statement only (`a4f7d20c81be`'s bracket).
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lead_call_policies NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_SEED_FOLLOW_UPS)
        op.execute(_SEED_VERSIONS)
        op.execute(_GO_LIVE)
    finally:
        op.execute("ALTER TABLE lead_call_policies FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")

    for table in TABLES:
        _force_rls(table)
    for table in LEDGERS:
        _append_only(table)

    op.execute(_SCAN_SQL)

    op.drop_constraint(op.f("ck_team_alerts_trigger_enum"), "team_alerts", type_="check")
    op.create_check_constraint(
        op.f("ck_team_alerts_trigger_enum"),
        "team_alerts",
        "trigger IN ('after_call', 'in_call', 'follow_up')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE team_alerts NO FORCE ROW LEVEL SECURITY; "
        "UPDATE team_alerts SET trigger = 'after_call' WHERE trigger = 'follow_up'; "
        "ALTER TABLE team_alerts FORCE ROW LEVEL SECURITY"
    )
    op.drop_constraint(op.f("ck_team_alerts_trigger_enum"), "team_alerts", type_="check")
    op.create_check_constraint(
        op.f("ck_team_alerts_trigger_enum"), "team_alerts", "trigger IN ('after_call', 'in_call')"
    )

    for table in ("follow_ups", "follow_up_versions", "lead_call_policies"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_WRITE_BACK)
    finally:
        for table in ("lead_call_policies", "follow_up_versions", "follow_ups"):
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(double precision)")
    for table in LEDGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_forbid_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_table("follow_up_run_events")
    op.drop_table("follow_up_runs")
    op.drop_constraint(
        "fk_follow_ups_live_version_id_follow_up_versions", "follow_ups", type_="foreignkey"
    )
    op.drop_table("follow_up_versions")
    op.drop_table("follow_ups")
