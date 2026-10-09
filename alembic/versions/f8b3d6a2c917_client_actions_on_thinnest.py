"""client in-call actions on ThinnestAI: four new action kinds, three new connections (D-700)

Revision ID: f8b3d6a2c917
Revises: e1a7c93b5d24
Create Date: 2026-10-09 23:30:00.000000

Widens the two CHECK-pinned vocabularies the ACTIONS feature (D-615, migration
`e1f7a3c920b4`) keeps:

* `integration_credentials.kind` gains `razorpay` (the CLIENT's own key pair, never
  Calevate's billing keys), `zoho_crm` and `hubspot` (OAuth refresh tokens).
* `action_tools.kind` gains `sheets`, `payment_link`, `crm` and `caller_lookup`.
* `action_tools.provider` gains `zoho`, `hubspot`, `razorpay`, `sheet` and `api` (the
  caller lookup's sources).

And one new table, `action_invocations`: one row per run of a client action (in-call,
background, test), written by the audit job beside its `audit_log` row, for the per-action
call log on the Actions screen. `audit_log` carries no outcome column (its summary goes to
the log stream only), so the log cannot be read back from it. Ids, a kind, an outcome code
and a duration: no number, no message, no payload (hard rule 6). Tenant-scoped with FORCEd
RLS; CASCADE with its action; pruned to 90 days by the audit job as rows arrive.

DOWNGRADE restores the narrower CHECKs and REFUSES while any row uses a new value:
dropping a client's configured action or connection to make a CHECK fit would destroy
their configuration silently. Delete those rows deliberately first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8b3d6a2c917"
down_revision: str | None = "e1a7c93b5d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_INTEGRATION_KINDS = ("aisensy", "meta_cloud", "interakt", "custom_api", "google_calendar")
_NEW_INTEGRATION_KINDS = (*_OLD_INTEGRATION_KINDS, "razorpay", "zoho_crm", "hubspot")
_OLD_ACTION_KINDS = ("custom_api", "whatsapp", "calendar")
_NEW_ACTION_KINDS = (*_OLD_ACTION_KINDS, "sheets", "payment_link", "crm", "caller_lookup")
_OLD_PROVIDERS = ("aisensy", "meta_cloud", "interakt", "custom", "google")
_NEW_PROVIDERS = (*_OLD_PROVIDERS, "zoho", "hubspot", "razorpay", "sheet", "api")


def _replace_check(table: str, name: str, predicate: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, predicate)


def _apply(integration: tuple[str, ...], kinds: tuple[str, ...], providers: tuple[str, ...]) -> None:
    _replace_check("integration_credentials", "kind_enum", f"kind IN {integration!r}")
    _replace_check("action_tools", "kind_enum", f"kind IN {kinds!r}")
    _replace_check(
        "action_tools", "provider_enum", f"provider IS NULL OR provider IN {providers!r}"
    )


def upgrade() -> None:
    _apply(_NEW_INTEGRATION_KINDS, _NEW_ACTION_KINDS, _NEW_PROVIDERS)
    op.create_table(
        "action_invocations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("call_ref", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('in_call', 'background', 'after_call', 'test')",
            name=op.f("ck_action_invocations_source_enum"),
        ),
        sa.CheckConstraint(
            "length(status) BETWEEN 1 AND 64", name=op.f("ck_action_invocations_status_len")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_action_invocations_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"],
            ["action_tools.id"],
            name=op.f("fk_action_invocations_tool_id_action_tools"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_invocations")),
    )
    op.create_index("ix_action_invocations_tenant_id", "action_invocations", ["tenant_id"])
    op.create_index(
        "ix_action_invocations_tool_created", "action_invocations", ["tool_id", "created_at"]
    )
    op.execute("ALTER TABLE action_invocations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE action_invocations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON action_invocations FOR ALL USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM integration_credentials
                     WHERE kind NOT IN {_OLD_INTEGRATION_KINDS!r})
             OR EXISTS (SELECT 1 FROM action_tools
                        WHERE kind NOT IN {_OLD_ACTION_KINDS!r}
                           OR (provider IS NOT NULL AND provider NOT IN {_OLD_PROVIDERS!r}))
          THEN
            RAISE EXCEPTION 'client actions or connections of a D-700 kind exist; '
              'delete them deliberately before downgrading';
          END IF;
        END $$;
        """
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON action_invocations")
    op.drop_index("ix_action_invocations_tool_created", table_name="action_invocations")
    op.drop_index("ix_action_invocations_tenant_id", table_name="action_invocations")
    op.drop_table("action_invocations")
    _apply(_OLD_INTEGRATION_KINDS, _OLD_ACTION_KINDS, _OLD_PROVIDERS)
