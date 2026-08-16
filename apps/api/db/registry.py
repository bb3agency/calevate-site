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
from apps.api.ops import models as ops_models
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
    "ops_models",
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
    # The CLIENT-side WhatsApp opt-in (migration e6b2d94f31a7): our own customer's owner
    # agreeing to receive hot-lead alerts from the Calevate WABA. Tenant data — it names
    # a person at one client and the number they opted in on — and the read that decides
    # whether `notify_hot_lead_whatsapp` may send runs inside `tenant_session`.
    "whatsapp_alert_optin_ledger",
    # dnc_list is listed but its policy is HAND-WRITTEN (asymmetric read/write): the
    # standard tenant_id = GUC form would hide global entries from every tenant, and a
    # nationally suppressed number would keep getting dialled. Migration a1c8e40f27b9
    # widened WITH CHECK by one branch so an UNTENANTED (ops) session can write a
    # `scope='global'` row; a tenant session still cannot, which is the property the
    # asymmetry exists for.
    "dnc_list",
    # One national-DND scrub of one campaign's list (SEC-COMP §3, migration
    # a1c8e40f27b9). Tenant data in the sense that matters: it is evidence about one
    # client's contact list, read by that client's launch gate and by every dispatch
    # tick. Carries counts and a provider reference and no phone number at all.
    "preference_scrub_runs",
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
    # The END of an engagement, executed and certified (migration f3a71c9e26b4): the
    # request that erases one client's caller data and is the only thing in this product
    # that writes `organizations.deleted_at`. Tenant data — it names one client and
    # carries the certificate they are handed — and RLS'd like every other row here.
    # NOT append-only: `completed_at` and `proof` are stamped on completion, exactly as
    # on `deletion_requests`.
    "tenant_erasure_requests",
    # One recording whose destruction an erasure OWES but could not lawfully perform yet
    # (migration 9c1d3e7a05f4). Tenant data: it names one of this client's calls and the
    # object key of its audio. NOT append-only — `erased_at` is stamped when the bytes
    # go, and the append-only artifact of an erasure is `deletion_requests.proof`.
    "recording_erasure_holds",
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

# Tables deliberately OUTSIDE tenant isolation, with reasons — the RLS coverage
# guardrail requires every exception to be listed here.
#
# Two shapes live in one dict, and the name is now narrower than the contents:
# `audit_log` and `engine_agent_routes` CARRY a tenant_id and are not policied on it,
# while the `platform_*` tables carry no tenant_id at all because they are platform
# state. They share the only property that matters to a reviewer — "this table is
# deliberately not tenant-isolated, and here is why" — so they share one list rather
# than growing a second one nobody would think to read. `check_rls_coverage` judges
# both: an entry must still name a table this repo actually has, whichever shape it is.
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
        "inbound routing table, and the exemption is now for READS ONLY. An engine "
        "webhook arrives with only the VENDOR agent id and no session, so resolving it "
        "to a tenant is inherently cross-tenant, and `engine_agent_routes_global_read` "
        "(FOR SELECT USING (true)) is what keeps that working. WRITES are policied: "
        "migration c4b70e928a1f added a FORCEd `tenant_isolation` policy covering "
        "INSERT/UPDATE/DELETE, because until it landed a session scoped to tenant A "
        "could DELETE, deactivate or RE-TENANT tenant B's inbound route — the same bug "
        "e4f2a86b13d7 fixed on `dnc_list`, where a widened read had quietly widened the "
        "writes. The table stays listed here rather than in TENANT_TABLES because its "
        "read genuinely is global and cannot satisfy the GUC rule; `rls_sweep_test` "
        "carries the behavioural pin for the write half. "
        "Keeping "
        "this two-id lookup in its own global table is what lets `agents` stay FORCE-RLS'd "
        "(hard rule 1) instead of needing an exemption. Carries no PII and no call data. "
        "It is also the row that STANDS FOR one vendor-side agent object, which is why "
        "the drift sweep's record lives here (`drift_state`, `drift_checked_at`, "
        "`drift_detected_at`; migration d4b8e1c73f05): a global work queue ordered by "
        "staleness and a cross-tenant ops summary are both unaskable from a tenant "
        "session, and the alternative was an exemption on `agents` itself. Those three "
        "columns hold a verdict from a fixed five-value vocabulary and two timestamps — "
        "no prompt, no disclosure line, no detail sentence, which is why the operator-"
        "readable sentence stays on the tenant-scoped per-agent endpoint."
    ),
    "platform_settings": (
        "platform-scoped, admin realm only (PLATFORM-CONFIG §5). One engine selection, "
        "one calling window, for every client at the same instant — there is no tenant "
        "whose row this could be, so it carries no tenant_id rather than a decorative "
        "one that would make it LOOK tenant-scoped to every column-driven sweep. "
        "Reachable only behind `platform:config` in the admin realm; every write is "
        "step-up confirmed and lands an audit_log row in the same transaction. Holds no "
        "PII and no credential — a key whose NAME marks it as a credential is refused "
        "at the boundary and lives encrypted in platform_secrets instead."
    ),
    "platform_secrets": (
        "platform-scoped, admin realm only (PLATFORM-CONFIG §5). Vendor credentials for "
        "the whole deployment — one Bolna key, one Sarvam key — so there is no tenant "
        "whose row this could be and it carries no tenant_id. Reachable only behind "
        "`platform:secrets` in the admin realm, and NO route returns plaintext on any "
        "surface: a session gives write access, never read access. What stops PII "
        "leaking is that nothing here is PII and nothing here is readable — the only "
        "plaintext fragment on disk is `last_four`. Per-TENANT credentials are a "
        "different table (§11) and that one carries tenant_id + FORCEd RLS."
    ),
    "platform_config_version": (
        "platform-scoped, admin realm only (PLATFORM-CONFIG §6). One integer that every "
        "process polls to learn whether the config changed; it is bumped by a trigger on "
        "platform_settings rather than by any application write. No tenant_id, because "
        "the fact it carries is 'the platform's configuration moved' — there is no "
        "per-tenant version of that. Holds no PII, no credential and no tenant data."
    ),
}

# INSERT-only ledgers (hard rule 4): immutability triggers in the migration.
APPEND_ONLY_TABLES = [
    "usage_events",
    "consent_ledger",
    "audit_log",
    "credit_ledger",
    "one_time_charges",
    # A withdrawn WhatsApp alert opt-in is a NEW row, never an edit of the grant it
    # supersedes: DPDP §6(6) requires withdrawal to be as easy as consent, not that it
    # erase the evidence of the consent that was live when we sent last month's alerts.
    "whatsapp_alert_optin_ledger",
    # A national-DND scrub is evidence that a list was clean at an instant. An UPDATE
    # that moved `scrubbed_at` forward would launder a stale scrub into a fresh one and
    # a DELETE would erase the basis for calls already placed; a correction is a new run
    # under the provider's new reference.
    "preference_scrub_runs",
    # Vendor credentials, versioned (PLATFORM-CONFIG §5). A new value is a new VERSION so
    # that "which key was live when this call was billed?" stays answerable a year later.
    # Its trigger is NOT the blanket `calevate_forbid_mutation` the others carry: a KEK
    # rotation must re-wrap historical DEKs in place, or the retired KEK could never be
    # removed from the environment. The trigger permits exactly `dek_wrapped`,
    # `dek_nonce`, `kek_version` and `retired_at` to change and RAISEs on everything else
    # including every DELETE — migration b8e3f2a71c04 argues it and records the rejected
    # alternative.
    "platform_secrets",
]
