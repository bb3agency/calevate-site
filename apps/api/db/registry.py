"""Imports every model module so Base.metadata is complete.

Alembic's env.py and the RLS coverage guardrail import from here — a model module
missing from this list silently escapes migrations AND the guardrail, so keep it
exhaustive. TENANT_TABLES drives RLS policy creation and the coverage check.
"""

from apps.api.agents import models as agents_models
from apps.api.billing import models as billing_models
from apps.api.compliance import models as compliance_models
from apps.api.crm import models as crm_models
from apps.api.db.base import Base
from apps.api.integrations import models as integrations_models
from apps.api.reliability import models as reliability_models
from apps.api.tenancy import models as tenancy_models

__all__ = [
    "APPEND_ONLY_TABLES",
    "TENANT_TABLES",
    "Base",
    "agents_models",
    "billing_models",
    "compliance_models",
    "crm_models",
    "integrations_models",
    "reliability_models",
    "tenancy_models",
]

# Every table that carries tenant_id and gets the FORCEd tenant_isolation policy.
# organizations is special-cased (policy matches on id).
TENANT_TABLES = [
    "memberships",
    "invitations",
    "agents",
    "prompt_versions",
    "extraction_schemas",
    "phone_numbers",
    "calls",
    "transcript_turns",
    "call_extractions",
    "leads",
    "lead_events",
    "usage_events",
    "plans",
    "spend_state",
    "consent_ledger",
    "retention_policies",
    "deletion_requests",
    "inbound_webhooks",
    "outbound_webhooks",
]

# Tables carrying tenant_id that are deliberately NOT tenant-RLS'd, with reasons —
# the RLS coverage guardrail requires every exception to be listed here.
RLS_EXEMPT_TENANT_COLUMNS = {
    "audit_log": "admin-realm surface reads cross-tenant; itself always audited",
    "engine_agent_routes": (
        "inbound routing table: an engine webhook arrives with only the VENDOR agent id "
        "and no session, so resolving it to a tenant is inherently cross-tenant. Keeping "
        "this two-id lookup in its own global table is what lets `agents` stay FORCE-RLS'd "
        "(hard rule 1) instead of needing an exemption. Carries no PII and no call data."
    ),
}

# INSERT-only ledgers (hard rule 4): immutability triggers in the migration.
APPEND_ONLY_TABLES = ["usage_events", "consent_ledger", "audit_log"]
