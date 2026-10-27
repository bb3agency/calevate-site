"""team alerts (contacts, per-agent rules, deliveries); saved tests up to 20 caller lines

Revision ID: c4e9a2f7d816
Revises: d8f3a6c1e924
Create Date: 2026-10-27 23:30:00.000000

D-904 (founder, 27 Oct 2026).

* `team_alert_contacts`: the business's own team addresses, verified once by an emailed code.
* `team_alert_rules`: one row per agent: which outcomes and choice values tell the team, and
  whether the agent may tell the team during the call.
* `team_alerts`: one row per (call, address), the delivery record and the idempotency key.

All three are tenant tables, so each gets FORCEd `tenant_isolation` here (hard rule 1); the
cross-tenant zero-rows proof is `tests/team_alerts_test.py`.

* `agent_test_cases.caller_lines` may hold up to 20 lines (was 6), so a guided procedure can be
  rehearsed as a saved test.

Reversible. The downgrade drops the three tables and restores the six-line CHECK, first
cutting any longer saved test to its first six lines (the count is printed).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from apps.api.db.migration_offline import execute_data_statement

revision: str = "c4e9a2f7d816"
down_revision: str | None = "d8f3a6c1e924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
TABLES = ("team_alert_contacts", "team_alert_rules", "team_alerts")

CASES = "agent_test_cases"
LINES_CHECK = "ck_agent_test_cases_caller_lines_shape"


def _lines_check(most: int) -> str:
    return (
        "jsonb_typeof(caller_lines) = 'array' "
        f"AND jsonb_array_length(caller_lines) BETWEEN 1 AND {most}"
    )


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


def _force_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "team_alert_contacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(), server_default="email", nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("whatsapp_credential_id", sa.UUID(), nullable=True),
        sa.Column("whatsapp_template", sa.Text(), nullable=True),
        sa.Column("whatsapp_language", sa.String(), nullable=True),
        sa.Column("whatsapp_number_id", sa.String(), nullable=True),
        sa.Column("whatsapp_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_hash", sa.LargeBinary(), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "channel IN ('email', 'whatsapp')", name=op.f("ck_team_alert_contacts_channel_enum")
        ),
        sa.CheckConstraint(
            "channel = 'email' OR (whatsapp_template IS NOT NULL "
            "AND jsonb_typeof(whatsapp_values) = 'array')",
            name=op.f("ck_team_alert_contacts_whatsapp_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["whatsapp_credential_id"],
            ["integration_credentials.id"],
            name=op.f("fk_team_alert_contacts_wa_credential"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "char_length(address) BETWEEN 3 AND 254",
            name=op.f("ck_team_alert_contacts_address_length"),
        ),
        sa.CheckConstraint(
            "code_attempts >= 0", name=op.f("ck_team_alert_contacts_code_attempts_not_negative")
        ),
        _tenant_fk("team_alert_contacts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_alert_contacts")),
    )
    op.create_index(
        op.f("ix_team_alert_contacts_tenant_id"), "team_alert_contacts", ["tenant_id"]
    )
    op.create_index(
        "uq_team_alert_contacts_live_address",
        "team_alert_contacts",
        ["tenant_id", "channel", "address"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "uq_team_alert_contacts_one_default",
        "team_alert_contacts",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND removed_at IS NULL"),
    )

    op.create_table(
        "team_alert_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column(
            "on_outcomes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "on_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("in_call", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "jsonb_typeof(on_outcomes) = 'array'",
            name=op.f("ck_team_alert_rules_on_outcomes_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(on_fields) = 'array'", name=op.f("ck_team_alert_rules_on_fields_is_array")
        ),
        _tenant_fk("team_alert_rules"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_team_alert_rules_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["team_alert_contacts.id"],
            name=op.f("fk_team_alert_rules_contact_id_team_alert_contacts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_alert_rules")),
        sa.UniqueConstraint("agent_id", name="uq_team_alert_rules_agent_id"),
    )
    op.create_index(op.f("ix_team_alert_rules_tenant_id"), "team_alert_rules", ["tenant_id"])

    op.create_table(
        "team_alerts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "trigger IN ('after_call', 'in_call')", name=op.f("ck_team_alerts_trigger_enum")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'cancelled')",
            name=op.f("ck_team_alerts_status_enum"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reasons) = 'array'", name=op.f("ck_team_alerts_reasons_is_array")
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_team_alerts_attempts_not_negative")),
        _tenant_fk("team_alerts"),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_team_alerts_agent_id_agents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name=op.f("fk_team_alerts_call_id_calls"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["team_alert_contacts.id"],
            name=op.f("fk_team_alerts_contact_id_team_alert_contacts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_alerts")),
        sa.UniqueConstraint("call_id", "contact_id", name="uq_team_alerts_call_contact"),
    )
    op.create_index(op.f("ix_team_alerts_tenant_id"), "team_alerts", ["tenant_id"])
    op.create_index(op.f("ix_team_alerts_agent_id"), "team_alerts", ["agent_id"])

    for table in TABLES:
        _force_rls(table)

    op.drop_constraint(op.f(LINES_CHECK), CASES, type_="check")
    op.create_check_constraint(op.f(LINES_CHECK), CASES, _lines_check(20))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    cut = (
        f"UPDATE {CASES} SET caller_lines = (SELECT jsonb_agg(e ORDER BY i) FROM "
        "jsonb_array_elements(caller_lines) WITH ORDINALITY AS t(e, i) WHERE i <= 6), "
        "updated_at = now() WHERE jsonb_array_length(caller_lines) > 6"
    )
    note = "saved tests longer than six caller lines are cut to their first six"
    count = execute_data_statement(sa.text(cut), note=note)
    if count is not None:
        print(f"saved tests cut to six caller lines: {count}")
    op.drop_constraint(op.f(LINES_CHECK), CASES, type_="check")
    op.create_check_constraint(op.f(LINES_CHECK), CASES, _lines_check(6))

    op.drop_table("team_alerts")
    op.drop_table("team_alert_rules")
    op.drop_table("team_alert_contacts")
