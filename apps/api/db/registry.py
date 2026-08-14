"""Imports every model module so Base.metadata is complete.

Alembic's env.py and the RLS coverage guardrail import from here — a model module
missing from this list silently escapes migrations AND the guardrail, so keep it
exhaustive. TENANT_TABLES drives RLS policy creation and the coverage check.
"""

from apps.api.agents import models as agents_models
from apps.api.billing import models as billing_models
from apps.api.campaigns import models as campaigns_models
from apps.api.compliance import models as compliance_models
from apps.api.crm import models as crm_models
from apps.api.db.base import Base
from apps.api.flags import models as flags_models
from apps.api.integrations import models as integrations_models
from apps.api.kb import models as kb_models
from apps.api.quality import models as quality_models
from apps.api.reliability import models as reliability_models
from apps.api.tenancy import models as tenancy_models

__all__ = [
    "APPEND_ONLY_TABLES",
    "TENANT_TABLES",
    "Base",
    "agents_models",
    "billing_models",
    "campaigns_models",
    "compliance_models",
    "crm_models",
    "flags_models",
    "integrations_models",
    "kb_models",
    "quality_models",
    "reliability_models",
    "tenancy_models",
]

# Every table that carries tenant_id and gets the FORCEd tenant_isolation policy.
# organizations is special-cased (policy matches on id).
TENANT_TABLES = [
    "memberships",
    "invitations",
    "agents",
    "campaigns",
    "campaign_contacts",
    "dlt_templates",
    "prompt_versions",
    # A/B script testing (ROADMAP M3, migration b3c8f27d41ae): the experiment, its two
    # arms, and the arm each call actually ran.
    "prompt_experiments",
    "prompt_experiment_variants",
    "call_variant_assignments",
    "extraction_schemas",
    "phone_numbers",
    "calls",
    "transcript_turns",
    "call_extractions",
    "leads",
    "lead_events",
    # Per-user-per-tenant Leads-table state (SURFACES §2 saved views, migration
    # a7e2c40d9b53). Tenant-isolated like every other row here; the per-USER half is an
    # explicit `user_id` predicate in `crm.saved_views`, because RLS answers "which
    # tenant" and never "which person".
    "lead_saved_views",
    "usage_events",
    "plans",
    "credit_ledger",
    # One-time charges (the onboarding setup fee, migration c7e1a4b90d63). Tenant money:
    # what this client was billed once, read by the invoice.
    "one_time_charges",
    "spend_state",
    "consent_ledger",
    # dnc_list is listed but its policy is HAND-WRITTEN (asymmetric read/write): the
    # standard tenant_id = GUC form would hide global entries from every tenant, and a
    # nationally suppressed number would keep getting dialled.
    "dnc_list",
    # The client's DLT Principal Entity registration + its Calevate TM link. Tenant
    # data (their registrar ids), read by the campaign launch gate (SEC-COMP §3).
    "dlt_registrations",
    # Subscriber KYC for a telecom connection (R-11's last mitigation). Tenant data —
    # the business's own registry identifiers — read by the number-provisioning gate and
    # by the dispatch gate for self-serve tenants.
    "kyc_records",
    # The human release of a self-serve account's first campaign (R-11's last
    # mitigation). Tenant data — what a reviewer decided about this account — read by
    # the campaign launch gate and by every dispatch tick.
    "first_campaign_reviews",
    # One row per tenant per feature flag they are OFF the platform default for
    # (SURFACES §1, migration 3a91c7e04d58). Tenant data in the sense that matters here:
    # it is OUR configuration decision ABOUT one client, readable only through the admin
    # surface, and no other tenant may see it. Absence is the default, so most tenants
    # have no rows at all.
    "tenant_feature_flags",
    "retention_policies",
    "deletion_requests",
    "inbound_webhooks",
    "outbound_webhooks",
    "kb_sources",
    "kb_documents",
    "kb_retrieval_logs",
    # The stored monthly QA report (SURFACES §2) and the weekly 5% spot-check queue
    # (SURFACES §1), migration d5b8a2c60e17. Both are tenant data: the report is the
    # client's own document and the sample names the client's own calls.
    "qa_reports",
    "qa_call_samples",
]

# Tables carrying tenant_id that are deliberately NOT tenant-RLS'd, with reasons —
# the RLS coverage guardrail requires every exception to be listed here.
#
# This dict is the cheapest way to smuggle a tenant table past hard rule 1, so it is
# fenced on three sides: `check_rls_coverage` rejects an entry whose table no longer
# exists (a stale exemption hides the next real gap) and one whose reason is too thin
# to review, and `tests/guardrail_audit_test.py` pins the exact key set — adding an
# exemption costs a visible diff in a test, not one line here.
RLS_EXEMPT_TENANT_COLUMNS = {
    "audit_log": (
        "the hash chain is GLOBAL: every insert reads the previous entry_hash with "
        "`ORDER BY at DESC LIMIT 1` across all tenants (compliance/audit.py), so a "
        "tenant policy would silently fork the chain per tenant and make the whole "
        "ledger unverifiable. Admin-realm surfaces also read it cross-tenant, and "
        "every such read is itself audited."
    ),
    "engine_agent_routes": (
        "inbound routing table: an engine webhook arrives with only the VENDOR agent id "
        "and no session, so resolving it to a tenant is inherently cross-tenant. Keeping "
        "this two-id lookup in its own global table is what lets `agents` stay FORCE-RLS'd "
        "(hard rule 1) instead of needing an exemption. Carries no PII and no call data."
    ),
}

# INSERT-only ledgers (hard rule 4): immutability triggers in the migration.
APPEND_ONLY_TABLES = [
    "usage_events",
    "consent_ledger",
    "audit_log",
    "credit_ledger",
    "one_time_charges",
]
