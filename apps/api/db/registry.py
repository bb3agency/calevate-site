"""Imports every model module so Base.metadata is complete.

Alembic's env.py and the RLS coverage guardrail import from here — a model module
missing from this list silently escapes migrations AND the guardrail, so keep it
exhaustive. TENANT_TABLES drives RLS policy creation and the coverage check.
"""

from apps.api.actions import models as actions_models
from apps.api.agents import models as agents_models
from apps.api.authn import models as authn_models
from apps.api.billing import models as billing_models
from apps.api.campaigns import models as campaigns_models
from apps.api.compliance import models as compliance_models
from apps.api.crm import models as crm_models
from apps.api.db.base import Base
from apps.api.flags import models as flags_models
from apps.api.insights import models as insights_models
from apps.api.integrations import models as integrations_models
from apps.api.kb import models as kb_models
from apps.api.legal import models as legal_models
from apps.api.ops import models as ops_models
from apps.api.quality import models as quality_models
from apps.api.reliability import models as reliability_models
from apps.api.tenancy import models as tenancy_models

__all__ = [
    "APPEND_ONLY_TABLES",
    "TENANT_TABLES",
    "Base",
    "actions_models",
    "agents_models",
    "authn_models",
    "billing_models",
    "campaigns_models",
    "compliance_models",
    "crm_models",
    "flags_models",
    "insights_models",
    "integrations_models",
    "kb_models",
    "legal_models",
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
    # ACTIONS feature: a client's saved integration credentials and their agents' in-call
    # tool definitions. Both carry tenant_id and get the FORCEd tenant_isolation policy.
    "integration_credentials",
    "action_tools",
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
    # What the ENGINE reported its own pipeline cost on one call, per turn (migration
    # b7d3e91c4a05). Numbers and a region code, no text — but derived from a tenant's call,
    # so it is isolated like everything else derived from one.
    "call_engine_latency",
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
    # The client's acceptance of the published legal documents (migration a9d4e70c31b8).
    # Tenant data: it names one client's owner and what they agreed to, and it is read by
    # that client's own readiness screen and by every outbound gate. Append-only — see
    # APPEND_ONLY_TABLES below.
    "legal_acceptances",
    "retention_policies",
    # Which tenants the nightly retention sweep must visit that the engine bridge cannot
    # name (D-368, migration b2e6f10c94d7). Its policy is HAND-WRITTEN like `dnc_list`'s
    # and asymmetric the other way: `tenant_isolation` is the strict own-tenant form for
    # every verb, and a second `FOR SELECT` policy lets an UNTENANTED session — the
    # retention worker, which has none — read across tenants. Both USING clauses consult
    # the GUC, so this is an ordinary tenant table and NOT an
    # `RLS_EXEMPT_TENANT_COLUMNS` entry; the alternative closures both needed one (on
    # `kb_sources` itself, which holds client content) and that is the price this shape
    # exists to avoid.
    "retention_worklist",
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
    # One erasure obligation at a SUB-PROCESSOR that no API of ours can discharge
    # (migration c9f4a2e17b83, D-433). Tenant data: it names one of this client's
    # erasures and the vendor-side ids an operator must quote to get the copy deleted.
    # NOT append-only, deliberately — the row's whole purpose is to move
    # `open -> requested -> confirmed|refused`, and an append-only version would need a
    # second table to answer the one question it exists to answer. The immutable trail
    # of the transitions is `audit_log`.
    "processor_erasure_tasks",
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
    # Knowledge gaps (D-Knowledge-Gaps): the per-(agent, topic) roll-up a client acts on
    # and the per-call occurrences behind its counts. Both are tenant data derived from a
    # client's own calls — the quotes are that client's callers' redacted words — and both
    # get the FORCEd tenant_isolation policy. NOT append-only: both hold derived data
    # (re-computable from the transcript), and the aggregate is a running tally the client
    # mutates; the immutable trail of dismiss/teach is `audit_log`.
    "knowledge_gaps",
    "knowledge_gap_occurrences",
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
        "readable sentence stays on the tenant-scoped per-agent endpoint. The KNOWLEDGE "
        "sweep's record lives here for identical reasons (`kb_drift_state`, "
        "`kb_drift_checked_at`, `kb_drift_detected_at`; migration a7c31e05b8d4): its unit "
        "of observation is one `list_kb(agent_ref)` round trip — an AGENT, not a source — "
        "and the engine-side copy no row of ours names has no `kb_sources` row to be "
        "written on at all, while `kb_sources` is FORCE-RLS'd and so can answer neither "
        "the global staleness queue nor the cross-tenant ops summary. Those three hold a "
        "verdict from a fixed six-value vocabulary and two timestamps: no source name, no "
        "chunk, and no engine handle."
    ),
    "fx_rate_observations": (
        "platform-scoped. The published USD/INR rate this deployment pulls every five "
        "minutes (migration b6f21d9c4e07). There is ONE exchange rate for the whole "
        "platform at an instant — no tenant whose row this could be — so it carries no "
        "tenant_id rather than a decorative one that would make it LOOK tenant-scoped to "
        "every column-driven sweep. No client-realm route names it: the conversion reads "
        "the rate from memory (`core/fx.py`) and the console reads the history behind "
        "`platform:config` in the admin realm. Holds a currency pair, a NUMERIC rate, two "
        "dates and a source URL — no PII, no credential, no tenant data. Append-only (see "
        "APPEND_ONLY_TABLES): it is the evidence behind `usage_events.meta.fx_rate`."
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
    "platform_state": (
        "platform-scoped, admin realm only. The big red switch and the telemarketer "
        "registration: one halt for every client at the same instant, and one TM "
        "registration for Calevate as an entity — the same shape as platform_settings "
        "above and listed for the same reason. No tenant_id, because there is no tenant "
        "whose row this could be; a decorative one would make it LOOK tenant-scoped to "
        "every column-driven sweep and invite a policy that would let one client's "
        "session see, or worse clear, the global halt. Holds no PII."
    ),
    "platform_engine_health": (
        "platform-scoped. One row per (engine, minute) counting the voice engine's "
        "server-side failures, which is the state behind the `engine_error_spike` alarm "
        "(OPERATIONS §4). The vendor is either answering or it is not — that is one fact "
        "for the whole platform and there is no tenant whose row it could be. Holds an "
        "engine name, a minute and two integers: no tenant id, no call, no number."
    ),
    "platform_model_prices": (
        "platform-scoped, admin realm only (PLATFORM-CONFIG §5). Operator-attested vendor "
        "list prices per LLM model, effective-dated — one Azure/OpenAI/Google subscription "
        "for the whole deployment, one price per model at an instant, so there is no tenant "
        "whose row this could be and it carries no tenant_id. Reachable only behind "
        "`platform:config` in the admin realm; every attestation is step-up confirmed and "
        "lands an audit_log row in the same transaction. Holds a model identifier, two "
        "NUMERIC USD-per-Mtok figures, an attester id and a source note — no PII, no "
        "credential, no tenant data. Append-only (see APPEND_ONLY_TABLES): a correction is "
        "a new effective-dated row, never an edit, so a re-rendered invoice resolves the "
        "price that was live in the month it is re-rendering."
    ),
    "platform_ai_spend": (
        "platform-scoped, admin realm only. The dashboard AI's monthly spend against the "
        "platform ceiling (D-127) — OUR bill to Google, not a client's, so there is no "
        "tenant whose row it could be. Its own migration (e1a7c93d5b02) already asserted "
        "the equivalence with platform_settings that this registry did not honour until "
        "now. Holds a month key and NUMERIC totals: no prompt, no answer text, no PII."
    ),
    "webhook_deliveries": (
        "THE ONE THAT WAS MISSING AND MATTERED (P4.6). Forensic trail for every webhook "
        "in and out (SEC-COMP §4). No tenant_id and no policy, and both are deliberate: "
        "an INBOUND engine webhook is recorded BEFORE tenant resolution — that is the "
        "whole point of the record, since a delivery we could not attribute is exactly "
        "the one a breach investigation needs — so there is no tenant to scope it to at "
        "write time.\n\n"
        "WHAT KEEPS IT FROM BEING A LEAK, stated here rather than only in a model "
        "docstring no guardrail reads: it carries `payload_ref`, an OBJECT-STORAGE KEY, "
        "never a payload, and the bytes behind that key are reachable only through "
        "`workers/storage`, which no client-facing route calls for this table. The "
        "OUTBOUND half IS client-visible, and it is scoped THROUGH `outbound_webhooks` "
        "— which is tenant-RLS'd — by joining on `endpoint_id` rather than by a policy "
        "here (migration 4be32bf3d12c). `reason` is an authored refusal code or an "
        "exception TYPE, never vendor prose, because vendor prose can quote the payload "
        "(hard rule 6, and the column's own comment argues it).\n\n"
        "It was absent from this list for the reason absences here are dangerous: it has "
        "no `tenant_id`, so the column-driven sweep never asked about it, and a reviewer "
        "looking for 'what is deliberately not tenant-isolated' would not have found the "
        "table holding references to every lead payload we have ever sent."
    ),
    "auth_credentials": (
        "D-165's first-party password store, and it is listed here because it is NOT "
        "tenant-scoped rather than because it is unpoliced — it is the most tightly "
        "policied table in this schema. Identity crosses tenants (one person, several "
        "`memberships`), so a `tenant_id` here would be duplicated or wrong, exactly as "
        "it would be on `users`. What replaces tenant isolation is DENY-BY-DEFAULT: "
        "migration e9a4c1d70b52 gives it FORCEd RLS whose USING and WITH CHECK are both "
        "`current_setting('app.auth', true) = 'on'`, a GUC only "
        "`db/session.credential_session()` sets. A tenant session — including tenant A "
        "asking about tenant B's owner — sees zero rows, which is the cross-tenant "
        "property hard rule 1 asks for, arrived at from the other direction. Holds an "
        "Argon2id hash and no plaintext; the pepper it is hashed under is derived from "
        "PLATFORM_KEK and never touches this database."
    ),
    "auth_sessions": (
        "D-165's opaque server-side sessions, same shape and same reason as "
        "`auth_credentials` above: not tenant-scoped because a session belongs to a "
        "PERSON across every tenant they are a member of, and protected by the same "
        "deny-by-default `app.auth` policy rather than by a tenant predicate. Holds a "
        "SHA-256 fingerprint of the bearer token, never the token, so a database dump is "
        "not a drawer of live cookies; carries ids and instants only — no IP, no "
        "user-agent, no PII."
    ),
    "auth_email_tokens": (
        "D-170's single-use emailed secrets — email verification, password reset, "
        "invitation set-password, and the first-administrator bootstrap (D-171). Not "
        "tenant-scoped for the same reason as the two above: it names a SUBJECT (a person "
        "across every tenant they belong to) or an `invitations` row, never a tenant. "
        "Migration b3d9f6a2c815 gives it the identical FORCEd deny-by-default policy on "
        "`app.auth`, so a tenant session — including tenant A asking about tenant B's "
        "owner — sees zero rows. Holds an HMAC of the token under a PLATFORM_KEK-derived "
        "key that never touches this database, so a dump is not a drawer of live reset "
        "links; the plaintext exists only in the email. The `purpose` is inside that "
        "MAC's domain, so a verification token cannot be redeemed as a password reset."
    ),
    "auth_otp_challenges": (
        "D-170's one-time codes — and since the second factor IS the emailed code rather "
        "than TOTP, this is the table the admin realm's MFA rests on. Not tenant-scoped "
        "for the same reason as its three siblings above (it names a subject, not a "
        "tenant) and carries the same FORCEd deny-by-default `app.auth` policy. It is "
        "the most sensitive of the four relative to its entropy: a six-digit code is ~20 "
        "bits, which is why `code_hash` is an HMAC under a key outside this database "
        "rather than a bare digest — 900,000 candidates is a rainbow table an attacker "
        "builds in a second, and that is precisely the defect this design was written to "
        "avoid. Carries no address and no PII: a subject id, a purpose, a MAC, two "
        "instants and an attempt count."
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
    # Operator-attested model prices, effective-dated (PLATFORM-CONFIG §5). A correction is
    # a NEW effective-dated row so that "which price was live when this month's minutes ran"
    # stays answerable for a re-rendered invoice. Unlike platform_secrets there is NO
    # rewrap exception: the blanket `calevate_forbid_mutation` applies, so every column is
    # immutable once written and there is no UPDATE this table ever needs.
    "platform_model_prices",
    # Acceptance of a legal document is CONTRACT FORMATION, not consent: there is no
    # withdrawal row and no status column, because a client who ends the engagement does
    # not un-accept the terms they operated under last month. An UPDATE could only ever
    # rewrite which version somebody agreed to, which is the one fact the row exists to
    # fix in place; a DELETE erases the evidence for the period it covers.
    # The pulled USD/INR rate (migration b6f21d9c4e07). `usage_events.meta.fx_rate` records
    # what a call was costed at; this table is the only thing that can say where that
    # number came from. An UPDATE would let today's correction rewrite the input to a bill
    # rendered and paid last quarter, which is not a correction but a rewrite of the
    # evidence — a superseding observation is a NEW row, and the newest publication wins.
    "fx_rate_observations",
    "legal_acceptances",
]
