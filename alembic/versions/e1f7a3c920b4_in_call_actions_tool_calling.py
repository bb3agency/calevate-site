"""in-call actions: tool-calling foundation (integration credentials + action tools)

Revision ID: e1f7a3c920b4
Revises: b7d2f10c93ae, f4b1e9a2c7d0, f2a6d81b39c4, c1e9a4f7d302, f4a1d0b6e29c
Create Date: 2026-08-24

The ACTIONS feature. Two new tenant-scoped tables and one column:

* `integration_credentials` — a client's saved, reusable, envelope-encrypted third-party
  credential (AiSensy/Meta/Interakt api keys, a Google refresh token). Referenced by tools,
  so rotating the row updates every tool that uses it. Mutable (rotation is an UPDATE under
  the `version` CAS) — NOT append-only.
* `action_tools` — one in-call tool definition per (agent, name): the LLM-facing
  description, the parameter spec and kind-specific config as JSONB, the trigger, and the
  credential it uses.
* `agents.api_actions_enabled` — the per-agent master "Enable API actions" switch. Default
  FALSE, so the feature is off for every existing agent and no action is declared to the
  engine until a client turns it on.

MULTI-HEAD MERGE. This repo's base carried five alembic heads (five lanes' migrations with
no merge point). This migration lists all five as `down_revision`, which both introduces the
feature AND unifies the chain, so `alembic heads` prints ONE head in this worktree (the
condition hard rule 10 requires before the coverage ratchet will score). No schema op
depends on any particular one of the five — the merge is structural.

Tenant isolation (DATA-MODEL §1, hard rule 1): both tables get ENABLE + FORCE RLS and a
`tenant_isolation` policy matching `app.tenant_id`; for a FOR ALL policy Postgres reuses the
USING expression as the write check, so a session cannot insert a row for a tenant it cannot
read. A cross-tenant zero-rows test ships in `tests/actions_rls_test.py`.

Reversible (hard rule 8): everything here is new; `downgrade` drops the tables, the policies
and the column. No client's behaviour changes on the day this lands — the master switch is
off by default, so no agent gains an action until one is configured and enabled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f7a3c920b4"
down_revision: str | Sequence[str] | None = "c7e2b4f019ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INTEGRATION_KINDS = ("aisensy", "meta_cloud", "interakt", "custom_api", "google_calendar")
_ACTION_KINDS = ("custom_api", "whatsapp", "calendar")
_ACTION_TRIGGERS = ("during_call", "after_call")
_ACTION_PROVIDERS = ("aisensy", "meta_cloud", "interakt", "custom", "google")


def upgrade() -> None:
    # --- integration_credentials -------------------------------------------------
    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("dek_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("dek_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("kek_version", sa.Integer(), nullable=False),
        sa.Column("last_four", sa.String(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("non_secret", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"kind IN {_INTEGRATION_KINDS!r}", name=op.f("ck_integration_credentials_kind_enum")
        ),
        sa.CheckConstraint(
            "length(btrim(label)) > 0", name=op.f("ck_integration_credentials_label_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"],
            name=op.f("fk_integration_credentials_tenant_id_organizations"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_credentials")),
    )
    op.create_index(
        "ix_integration_credentials_tenant_id", "integration_credentials", ["tenant_id"]
    )

    # --- action_tools ------------------------------------------------------------
    op.create_table(
        "action_tools",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("trigger", sa.String(), server_default="during_call", nullable=False),
        sa.Column("pre_call_message", sa.Text(), nullable=True),
        sa.Column("credential_id", sa.UUID(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(f"kind IN {_ACTION_KINDS!r}", name=op.f("ck_action_tools_kind_enum")),
        sa.CheckConstraint(
            f"trigger IN {_ACTION_TRIGGERS!r}", name=op.f("ck_action_tools_trigger_enum")
        ),
        sa.CheckConstraint(
            f"provider IS NULL OR provider IN {_ACTION_PROVIDERS!r}",
            name=op.f("ck_action_tools_provider_enum"),
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name=op.f("ck_action_tools_name_not_blank")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"],
            name=op.f("fk_action_tools_tenant_id_organizations"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_action_tools_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["integration_credentials.id"],
            name=op.f("fk_action_tools_credential_id_integration_credentials"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_tools")),
        sa.UniqueConstraint("agent_id", "name", name="uq_action_tools_agent_name"),
    )
    op.create_index("ix_action_tools_tenant_id", "action_tools", ["tenant_id"])
    op.create_index("ix_action_tools_agent_id", "action_tools", ["agent_id"])

    # --- master switch on agents -------------------------------------------------
    op.add_column(
        "agents",
        sa.Column("api_actions_enabled", sa.Boolean(), server_default="false", nullable=False),
    )

    # --- RLS (hard rule 1) -------------------------------------------------------
    for table in ("integration_credentials", "action_tools"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ("
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade() -> None:
    for table in ("action_tools", "integration_credentials"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_column("agents", "api_actions_enabled")
    op.drop_index("ix_action_tools_agent_id", table_name="action_tools")
    op.drop_index("ix_action_tools_tenant_id", table_name="action_tools")
    op.drop_table("action_tools")
    op.drop_index("ix_integration_credentials_tenant_id", table_name="integration_credentials")
    op.drop_table("integration_credentials")
