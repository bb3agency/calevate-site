"""WhatsApp accounts a client connects through Meta's Embedded Signup, their templates, and
the in-call WhatsApp opt-in source (D-784)

Revision ID: c8e5a2f7d914
Revises: e7a3c5d9b1f4
Create Date: 2026-10-15 12:00:00.000000

1. `whatsapp_accounts` (tenant, FORCE-RLS): one WhatsApp Business Account (WABA) and its
   sending number, connected by the client through Embedded Signup with Calevate as the
   Meta Tech Provider. The business token is NOT here: it is an `integration_credentials`
   row (kind `meta_cloud`, sealed per tenant) that `credential_id` points at.
   Meta's webhooks arrive for ONE app and name only the WABA, so the read policy also admits
   the single row whose `waba_id` a session names in `app.whatsapp_waba_id`
   (`db/session.whatsapp_waba_session`). That is `ingest_config_session`'s doctrine
   (d41f88a2c6e9): the receiver sets it only after the delivery's `X-Hub-Signature-256`
   verified under OUR app secret, so the id is Meta's statement, not a stranger's guess.
   Writes are never widened. A WABA can be connected to one client at a time: a partial
   unique index over live rows enforces it across tenants (unique indexes ignore RLS).
2. `whatsapp_templates` (tenant, FORCE-RLS): Calevate's standard UTILITY templates and the
   client's own, as submitted to the client's WABA, with the review status Meta reports.
3. `consent_ledger` gains the source `in_call_agent_question`: the voice agent asked the
   caller during the call and the caller said yes or no. Like `inbound_call_verbal`, a grant
   from it must name the call.

Downgrade refuses while any consent row uses the new source (`consent_ledger` is
append-only, hard rule 4); otherwise it restores both CHECKs and drops the two tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8e5a2f7d914"
down_revision: str | None = "e7a3c5d9b1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTS = "whatsapp_accounts"
TEMPLATES = "whatsapp_templates"

_TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_WABA_GUC = "NULLIF(current_setting('app.whatsapp_waba_id', true), '')"
_OWN_TENANT = f"(tenant_id = {_TENANT_GUC})"

_ACCOUNT_STATUSES = ("connecting", "connected", "needs_attention", "disconnected")
_ONBOARDINGS = ("new", "business_app", "grant_access")
_ORIGINS = ("calevate", "client")
_CATEGORIES = ("UTILITY", "MARKETING")
_TEMPLATE_STATUSES = (
    "draft",
    "pending",
    "approved",
    "rejected",
    "paused",
    "disabled",
    "deleted",
    "submit_failed",
)

# Spelled out rather than imported (a migration is a snapshot of the day it ran).
_SOURCES_BEFORE = (
    "'inbound_call_verbal', 'web_form_optin', 'offline_form_optin', "
    "'whatsapp_inbound_message', 'staff_recorded_request', 'in_call_recording_notice'"
)
_SOURCES_AFTER = f"{_SOURCES_BEFORE}, 'in_call_agent_question'"
CK_SOURCE = "ck_consent_ledger_source_enum"
CK_GRANT_EVIDENCE = "ck_consent_ledger_granted_consent_carries_evidence"
_GRANT_EVIDENCE_BEFORE = (
    "consent_source IS NULL OR status <> 'granted' OR ("
    "evidence IS NOT NULL "
    "AND consent_source <> 'staff_recorded_request' "
    "AND (consent_source <> 'inbound_call_verbal' OR call_id IS NOT NULL))"
)
_GRANT_EVIDENCE_AFTER = (
    "consent_source IS NULL OR status <> 'granted' OR ("
    "evidence IS NOT NULL "
    "AND consent_source <> 'staff_recorded_request' "
    "AND (consent_source NOT IN ('inbound_call_verbal', 'in_call_agent_question') "
    "OR call_id IS NOT NULL))"
)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _digits(column: str, *, nullable: bool) -> str:
    check = f"{column} ~ '^[0-9]{{1,64}}$'"
    return f"{column} IS NULL OR {check}" if nullable else check


def _ts(*names: str) -> list[sa.Column[object]]:
    return [
        sa.Column(n, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
        for n in names
    ]


def _ck(table: str, name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=op.f(f"ck_{table}_{name}"))


def _replace_check(name: str, expression: str) -> None:
    op.execute(f"ALTER TABLE consent_ledger DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE consent_ledger ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
    op.execute(f"ALTER TABLE consent_ledger VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        ACCOUNTS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("credential_id", sa.UUID(), nullable=True),
        sa.Column("waba_id", sa.String(length=64), nullable=False),
        sa.Column("phone_number_id", sa.String(length=64), nullable=True),
        sa.Column("business_id", sa.String(length=64), nullable=True),
        sa.Column("display_phone_number", sa.String(length=32), nullable=True),
        sa.Column("verified_name", sa.Text(), nullable=True),
        sa.Column("name_status", sa.String(length=32), nullable=True),
        sa.Column("quality_rating", sa.String(length=16), nullable=True),
        sa.Column("messaging_limit", sa.String(length=32), nullable=True),
        sa.Column("onboarding", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="connecting", nullable=False),
        sa.Column("registered", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("webhooks_subscribed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("setup_error", sa.String(length=64), nullable=True),
        sa.Column("templates_seeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_alert", sa.String(length=64), nullable=True),
        sa.Column("account_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_send_error", sa.String(length=64), nullable=True),
        sa.Column("last_send_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        _ck(ACCOUNTS, "waba_id_digits", _digits("waba_id", nullable=False)),
        _ck(ACCOUNTS, "phone_number_id_digits", _digits("phone_number_id", nullable=True)),
        _ck(ACCOUNTS, "business_id_digits", _digits("business_id", nullable=True)),
        _ck(ACCOUNTS, "onboarding_enum", _in("onboarding", _ONBOARDINGS)),
        _ck(ACCOUNTS, "status_enum", _in("status", _ACCOUNT_STATUSES)),
        _ck(
            ACCOUNTS,
            "disconnected_iff",
            "(status = 'disconnected') = (disconnected_at IS NOT NULL)",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_whatsapp_accounts_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["integration_credentials.id"],
            name=op.f("fk_whatsapp_accounts_credential_id_integration_credentials"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_accounts")),
    )
    op.create_index(op.f("ix_whatsapp_accounts_tenant_id"), ACCOUNTS, ["tenant_id"])
    op.create_index(
        "ux_whatsapp_accounts_live_waba",
        ACCOUNTS,
        ["waba_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'disconnected'"),
    )

    op.create_table(
        TEMPLATES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("meta_status", sa.String(length=32), nullable=True),
        sa.Column("meta_template_id", sa.String(length=64), nullable=True),
        sa.Column("rejection_code", sa.String(length=128), nullable=True),
        sa.Column("category_changed_to", sa.String(length=32), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        _ck(TEMPLATES, "name_shape", r"name ~ '^[a-z0-9_]+$'"),
        _ck(TEMPLATES, "language_shape", r"language ~ '^[a-z]{2,3}(_[A-Z]{2})?$'"),
        _ck(TEMPLATES, "category_enum", _in("category", _CATEGORIES)),
        _ck(TEMPLATES, "origin_enum", _in("origin", _ORIGINS)),
        _ck(TEMPLATES, "status_enum", _in("status", _TEMPLATE_STATUSES)),
        _ck(TEMPLATES, "body_length", "length(body) BETWEEN 1 AND 1024"),
        _ck(
            TEMPLATES,
            "meta_template_id_digits",
            _digits("meta_template_id", nullable=True),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_whatsapp_templates_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            [f"{ACCOUNTS}.id"],
            name=op.f("fk_whatsapp_templates_account_id_whatsapp_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_templates")),
        sa.UniqueConstraint(
            "account_id",
            "name",
            "language",
            name=op.f("uq_whatsapp_templates_account_id_name_language"),
        ),
    )
    op.create_index(op.f("ix_whatsapp_templates_tenant_id"), TEMPLATES, ["tenant_id"])

    for table in (ACCOUNTS, TEMPLATES):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {ACCOUNTS} FOR ALL "
        f"USING ({_OWN_TENANT} OR waba_id = {_WABA_GUC}) WITH CHECK {_OWN_TENANT}"
    )
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TEMPLATES} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    _replace_check(CK_SOURCE, f"consent_source IS NULL OR consent_source IN ({_SOURCES_AFTER})")
    _replace_check(CK_GRANT_EVIDENCE, _GRANT_EVIDENCE_AFTER)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM consent_ledger "
        "WHERE consent_source = 'in_call_agent_question') THEN RAISE EXCEPTION "
        "'consent_ledger holds in_call_agent_question rows, which are append-only: this "
        "revision cannot be downgraded'; END IF; END $$"
    )
    _replace_check(CK_GRANT_EVIDENCE, _GRANT_EVIDENCE_BEFORE)
    _replace_check(CK_SOURCE, f"consent_source IS NULL OR consent_source IN ({_SOURCES_BEFORE})")
    for table in (TEMPLATES, ACCOUNTS):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table(TEMPLATES)
    op.drop_table(ACCOUNTS)
