"""lead-source connectors: IndiaMART, property portals and LeadSquared (D-942)

Revision ID: e4a7c2d9f816
Revises: f7b3e9a1c254
Create Date: 2026-10-30 10:00:00.000000

Four CHECK widenings and nothing else:

1. `inbound_webhooks.source` gains `indiamart`, `99acres`, `magicbricks`, `housing` and
   `leadsquared`: senders that post to a URL and cannot be asked to set our header.
2. `outbound_webhooks.kind` gains `leadsquared`: captured leads and call outcomes written
   into the client's own LeadSquared through its Lead.Capture API.
3. `integration_credentials.kind` gains `leadsquared`: the client's access key and secret
   key, sealed as one credential.
4. `consent_ledger.consent_source` gains `portal_enquiry`: the person's own enquiry to this
   business on a listing portal, which supports calls for seven days (TCCCPR "relationship",
   cl.2(bb)(ii)). A grant from it must carry evidence like every other grant; the existing
   evidence CHECK already requires that of any source not named in it.

DOWNGRADE refuses while any row uses a new value: the ledger is append-only and the other
three are client configuration, so narrowing under them would either fail or orphan a
client's integration silently.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e4a7c2d9f816"
down_revision: str | None = "f7b3e9a1c254"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported: a migration is a snapshot of the day it ran.
_SOURCES_BEFORE = ("meta_lead_ads", "website_form", "zoho", "sheets", "custom")
_NEW_SOURCES = ("indiamart", "99acres", "magicbricks", "housing", "leadsquared")
_SOURCES_AFTER = (*_SOURCES_BEFORE, *_NEW_SOURCES)

_OUT_KINDS_BEFORE = ("webhook", "google_sheets")
_OUT_KINDS_AFTER = (*_OUT_KINDS_BEFORE, "leadsquared")

_CRED_KINDS_BEFORE = (
    "aisensy",
    "meta_cloud",
    "interakt",
    "custom_api",
    "google_calendar",
    "razorpay",
    "zoho_crm",
    "hubspot",
    "google_sheets",
)
_CRED_KINDS_AFTER = (*_CRED_KINDS_BEFORE, "leadsquared")

_CONSENT_BEFORE = (
    "'inbound_call_verbal', 'web_form_optin', 'offline_form_optin', "
    "'whatsapp_inbound_message', 'staff_recorded_request', 'in_call_recording_notice', "
    "'in_call_agent_question'"
)
_CONSENT_AFTER = f"{_CONSENT_BEFORE}, 'portal_enquiry'"


def _replace(table: str, name: str, expression: str) -> None:
    """NOT VALID then VALIDATE, so the widening holds no long lock on a busy table."""
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    _replace("inbound_webhooks", "ck_inbound_webhooks_source_enum", _in("source", _SOURCES_AFTER))
    _replace("outbound_webhooks", "ck_outbound_webhooks_kind_enum", _in("kind", _OUT_KINDS_AFTER))
    _replace(
        "integration_credentials",
        "ck_integration_credentials_kind_enum",
        _in("kind", _CRED_KINDS_AFTER),
    )
    _replace(
        "consent_ledger",
        "ck_consent_ledger_source_enum",
        f"consent_source IS NULL OR consent_source IN ({_CONSENT_AFTER})",
    )


_GUARDED = ("inbound_webhooks", "outbound_webhooks", "integration_credentials", "consent_ledger")


def downgrade() -> None:
    new_sources = ", ".join(repr(v) for v in _NEW_SOURCES)
    # Bracketed: the four tables are FORCE RLS and fail-closed on an unset `app.tenant_id`,
    # so an unbracketed check reads zero rows and the named refusal never fires (the
    # VALIDATE below would still refuse, naming only a constraint). DDL is transactional,
    # so FORCE is back before commit.
    for table in _GUARDED:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN IF "
        f"EXISTS (SELECT 1 FROM inbound_webhooks WHERE source IN ({new_sources})) "
        "OR EXISTS (SELECT 1 FROM outbound_webhooks WHERE kind = 'leadsquared') "
        "OR EXISTS (SELECT 1 FROM integration_credentials WHERE kind = 'leadsquared') "
        "OR EXISTS (SELECT 1 FROM consent_ledger WHERE consent_source = 'portal_enquiry') "
        "THEN RAISE EXCEPTION 'portal lead sources, LeadSquared connections or portal-enquiry "
        "consent rows exist; remove the configuration deliberately (the ledger rows are "
        "append-only) before downgrading'; END IF; END $$"
    )
    for table in _GUARDED:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    _replace(
        "consent_ledger",
        "ck_consent_ledger_source_enum",
        f"consent_source IS NULL OR consent_source IN ({_CONSENT_BEFORE})",
    )
    _replace(
        "integration_credentials",
        "ck_integration_credentials_kind_enum",
        _in("kind", _CRED_KINDS_BEFORE),
    )
    _replace("outbound_webhooks", "ck_outbound_webhooks_kind_enum", _in("kind", _OUT_KINDS_BEFORE))
    _replace("inbound_webhooks", "ck_inbound_webhooks_source_enum", _in("source", _SOURCES_BEFORE))
