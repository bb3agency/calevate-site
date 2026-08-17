# Calevate — Legal Surface

**Version 1.0 · 17 August 2026.** Derived by reading the tree, not by recalling a template.
Every obligation below names the instrument it comes from and the code, schema, config or
blueprint line that creates it for us. Where we do not satisfy it, the row says so and
names what would.

> ⚠ **{{PENDING LEGAL REVIEW}}** — the public documents this analysis produced
> (`apps/web/src/lib/legal/`, served at `/legal/*`) have **not been reviewed by an advocate
> qualified in India**. They carry a visible draft banner that must be deliberately removed
> (`PENDING_LEGAL_REVIEW` in `apps/web/src/lib/legal/placeholders.ts`), and
> `tests/legal.test.tsx` fails if the banner is turned off without also deleting the
> assertion that guards it. Nothing on `/legal/*` may be shown to a client, a regulator or
> a payment gateway before that review.

---

## 0. What was audited, and what the audit is worth

Read in full or in relevant part: `docs/SECURITY-COMPLIANCE.md`, `docs/DATA-MODEL.md`,
`docs/DEPLOYMENT.md`, `docs/README.md`, `CLAUDE.md`; `apps/workers/retention.py`,
`apps/workers/notifications.py`, `apps/workers/storage.py`; `apps/api/compliance/*`
(deletion, deletion_proof, export, consent, dnc, disclosure, service, kyc, models);
`apps/api/core/rbac.py`, `apps/api/billing/{terms,gst,invoice,service,payments}.py`,
`apps/api/engine/{bolna,cartesia}.py`, `apps/api/tenancy/models.py`;
`packages/shared/src/calevate_shared/config.py`; `scripts/seed.py`, `scripts/check_*.py`;
the whole of `apps/web/src/app` and `apps/web/src/lib/auth`.

Law was researched on the web on **16–17 August 2026** — every source is listed in §9 with
its retrieval date, because Indian data-protection and telecom law moved substantially in
2025–2026 and a document written from memory would be wrong in specific, damaging ways.

**The single most important framing fact, and it changes how every row reads:** *nothing
is in production.* There is no legal entity decided, no DLT registration, no provisioned
host, no live client, and `ENGINE=fake` is the shipped default. Almost every "UNMET" below
is therefore either (a) waiting on a founder decision or an external registrar, or (b) a
real code gap that can be closed now. The rows say which.

---

## 1. The two role splits everything else hangs off

| Fact | Evidence |
|---|---|
| **Calevate is a Data Processor** for callers' personal data; the client business is the **Data Fiduciary**. | `apps/api/compliance/deletion_routes.py` docstring: *"A data principal asks the CLIENT to erase them; the client — the Data Fiduciary, we are their Processor — asks us."* Erasure is a **client-realm** surface requiring `org:manage`; there is no admin-realm route that erases one data principal on their own request. `docs/SECURITY-COMPLIANCE.md` §4. |
| **Calevate is the Data Fiduciary** for client-account data (users, org, billing, KYC). | `apps/api/tenancy/models.py` — `users(clerk_user_id, email, name, phone)`, `organizations(name, slug, billing_email, intake)`; `apps/api/compliance/models.py` `kyc_records`. Nothing treats these as processed on anyone's instruction. |
| **Calevate is the Telemarketer (TM); the client is the Principal Entity (PE).** | `docs/SECURITY-COMPLIANCE.md` §3 (*"DLT role model (corrected)"*); `platform_state.tm_id` and blocker `tm_registration_missing`; `dlt_registrations(tenant_id, pe_id, status, tm_link_status)` in `docs/DATA-MODEL.md` §9. |

**Consequence the public documents had to be written around:** the disclosure duty, the
consent basis and the notice to callers all attach to the **client**, and DPDP §8(1) makes
the Fiduciary responsible for processing carried out on its behalf — a liability it cannot
contract away. Calevate's own duties are contractual (DPA), plus rule 6 security safeguards
flowing through the s.8(2) contract.

---

## 2. Personal data inventory — derived from the schema

### 2.1 Callers (we are Processor)

| Data | Where it lives |
|---|---|
| Phone number, E.164 | `calls.from_e164/to_e164`, `leads.phone_e164`, `campaign_contacts.phone_e164`, `consent_ledger`, `dnc_list` |
| Call metadata (direction, times, duration, status, outcome, sentiment) | `calls` (`docs/DATA-MODEL.md` §4) |
| Audio recording | `calls.recording_url` → object storage; Cloudflare R2 in prod (`docs/DEPLOYMENT.md` §1) |
| Raw transcript **and** redacted transcript | `transcript_turns.text` / `.text_redacted` |
| Model-written summary | `calls.summary` |
| Extracted CRM fields (client-defined schema) | `call_extractions.data` JSONB, `leads.data` JSONB |
| Timestamped key moments, quoting the caller | `call_extractions.moments` (cleared with `data` — `apps/workers/retention.py::_EXTRACTION_SQL`) |
| Consent / opt-out evidence incl. transcript span | `consent_ledger` (append-only) |
| Uploaded contact rows + **every other CSV column the client pasted** | `campaign_contacts(phone_e164, name, custom JSONB, dedupe_hash)` |
| The exact body POSTed to a client's CRM | `webhook_deliveries.payload_ref` → object storage, ≤64 KiB (D-23) |
| The **raw vendor document** for each call — carries number and transcript | `calls.engine_payload_ref` → `engine-payloads/{tenant}/{call}/…` (D-126) |
| Disclosure evidence | `calls.disclosure_played`, `calls.consent_recording` |

### 2.2 Client users (we are Fiduciary)

`users(clerk_user_id, email, name, phone)`; `memberships.role`;
`organizations(name, slug, billing_email, intake JSONB)` — **`intake` contains staff names
and escalation numbers** and is flagged "never log it" in `apps/api/tenancy/models.py`;
`kyc_records(entity_type, document_kind, document_ref, signatory_name, evidence_ref)`;
`dlt_registrations`; `plans` (commercial terms); `audit_log(actor, tenant, action, ip)`;
`credit_ledger` / `usage_events`.

`kyc_records` carries `CHECK (document_ref !~ '^[0-9]{12}$')` — a deliberate backstop so an
Aadhaar number cannot be stored in a business-registry field. Good control; noted as such.

### 2.3 Website visitors

**Nothing beyond request logs.** `apps/web/src/app/layout.tsx` mounts no `ClerkProvider`,
no analytics and no third-party script; fonts are `next/font/local`. `ClerkProvider` is
mounted only under `app/admin/layout.tsx`, the client-realm layout and `(auth)/*`. Grep for
`gtag|googletagmanager|analytics|posthog` in `apps/web/src` returns one unrelated comment.
`langfuse_*` and `posthog_key` were **deleted** from `Settings` precisely because they were
credential-shaped fields with no client (`tests/observability_config_honesty_test.py`).

---

## 3. Obligations, and whether we meet them

Legend: **MET** · **PARTIAL** · **UNMET** · **EXTERNAL** (blocked on something outside the
repo — an entity, a registrar, a vendor contract, a founder decision).

### 3.1 DPDP Act 2023 + DPDP Rules 2025

The Rules were notified **14 November 2025** with phased commencement: Board framework Nov
2025, Consent Manager Nov 2026, **substantive obligations 13 May 2027**. Until then IT Act
s.43A + SPDI Rules 2011 remain operative (§3.3). Sources §9.

| # | Obligation | Source | Status | Evidence / what closes it |
|---|---|---|---|---|
| DP-1 | Notice with an **itemised** description of personal data, purposes, and how to withdraw consent / complain / reach the Board | DPDP §5, Rule 3 | **MET as far as it is ours** | `/legal/privacy` §3 itemises per data-subject class — that is **our** notice. The notice to *callers* is the client's, and since D-179 the product produces the itemisation they cannot: `GET /v1/compliance/caller-notice` drafts it from their extraction schemas, retention rows and announcement switches (F-8). The wording and the lawful basis stay theirs, and the draft says so. |
| DP-2 | Consent as the general lawful basis for caller data | DPDP §6 | **EXTERNAL / client's** | `consent_ledger` with purposes `recording|callback|marketing|messaging` (`apps/api/compliance/models.py:26`); `check_dispatch` refuses on any status ≠ `granted` (`DIAL_REFUSING_CONSENT_STATUSES`). The *basis for calling at all* is the client's; the product records provenance (`campaigns.consent_source`) and refuses `purchased_list`. |
| DP-3 | Withdrawal as easy as giving consent | DPDP §6(4)-(6) | **MET (voice)** | In-call opt-out tool + post-call transcript pass, one write path (`apps/api/compliance/optout.py`, D-56); propagates before the next dispatch tick (30s) against TRAI's 24h ceiling. |
| DP-4 | Right to access / summary of processing | DPDP §11 | **MET** | `apps/api/compliance/export.py` — keyed by phone, returns redacted transcripts, recordings as a boolean not a URL, foreign numbers masked in `summary`. Three good decisions documented at the top of the module. |
| DP-5 | Right to erasure, with proof | DPDP §12 | **MET, with disclosed limits** | `POST /v1/compliance/deletion-requests` → outbox → `execute_deletion_request`; reaches calls, turns, extractions, leads, campaign contacts, delivery bodies, engine payloads, recordings, and since D-179 SEARCHES the knowledge base and reports the count without changing the client's own content. Certificate enumerates limits (`ERASURE_LIMITATIONS`). |
| DP-6 | Right to correction | DPDP §12(1) | **PARTIAL** | A lead is editable by the client. There is **no correction path for a transcript or a recording**, and none is offered on the certificate. Arguably right (a recording is a record of an event, not an assertion) but it is undecided rather than reasoned. What closes it: a founder + counsel decision recorded in ROADMAP §6. |
| DP-7 | Right to nominate | DPDP §13 | **UNMET** | Nothing in the product models a nominee. Low urgency (substantive commencement May 2027) but it is a gap, and it is the client's obligation, not ours — so what closes it is a sentence in the client's notice, not code. |
| DP-8 | Grievance redressal within a published timeline, ≤90 days | Rule 14(3) | **PARTIAL** | `/legal/grievance` now publishes 2 business days to acknowledge, 15–30 days to resolve. There is **no grievance intake surface, no ticket record and no clock in the product** — it is an email address. What closes it: either a mailbox + a written procedure (sufficient at this size), or a `grievances` table. Say which; do not leave it implied. |
| DP-9 | Publish the business contact of the person answering data-principal questions, and repeat it in every reply | Rule 9 | **PARTIAL** | Published as `{{DATA_PROTECTION_CONTACT_NAME/EMAIL}}` on `/legal/privacy` §14 and `/legal/grievance` §1. The "repeat it in every reply" half is a process nobody has written. |
| DP-10 | Reasonable security safeguards: encryption/masking, access control, logs+monitoring, retained **one year**, continuity | Rule 6 | **PARTIAL** | Everything in §4 below is real. **The log-retention leg is not evidenced anywhere in the tree**: no retention period is configured for application logs or for `audit_log` (which is append-only and never expired — arguably ≥1 year by construction, but nothing states it). What closes it: a stated log-retention period in OPERATIONS and a lifecycle rule. |
| DP-11 | Data-processor contract imposing equivalent safeguards | §8(2), Rule 6(f) | **MET as text, UNMET as practice** | `/legal/dpa` is that contract, and Annex B is the equivalent-safeguards clause. **Downward**: we owe the same to *our* sub-processors, and **no vendor contract has been signed** — the Bolna residency commitment is an unrun pilot gate (`evidence/bolna-pilot-scorecard.md` is an empty template). |
| DP-12 | Breach notification: Board without delay, detailed report ≤72h, affected principals with no threshold | Rule 7 | **MET as procedure; one lookup outstanding** | D-179: `runbooks/data-breach-notification.md` (the three clocks, the role split, the scope walk, the sign-off), `apps/api/compliance/breach.py` (the Rule 7 content, refused if an element is missing or a phone number is present) and `scripts/breach_notice.py`. The 48-hour DPA promise is pinned by test across the DPA, the runbook and the notice. **Outstanding: the Board's own reporting channel** — a lookup nobody has done, recorded in the runbook's §7 rather than left to be discovered mid-incident — and counsel's review of the wording. |
| DP-13 | Retention limited to purpose; erase when purpose served | §8(7), Rule 8 | **PARTIAL** | Nightly sweep enforces per-tenant TTLs (`apps/workers/retention.py`). The two stores that escaped it are closed (F-2, F-3, D-179). **One store still has no clock: uploaded campaign contacts** — the category is deliberately absent because the period is a DPA commitment the founder must give, and `tests/dpdp_known_gaps_test.py` holds that open by probing the CHECK constraint. |
| DP-14 | Third Schedule erasure periods + 48h pre-erasure notice | Rule 8(3) | **NOT ENGAGED** | Correctly analysed already in SEC-COMP §4: they bind e-commerce/gaming/social-media fiduciaries above 2 crore / 50 lakh user thresholds. Calevate is none of those. |
| DP-15 | Children: verifiable parental consent, no tracking/behavioural ads | §9 | **PARTIAL** | We build no profiles and run no advertising, so the prohibition half is met by construction. **Nothing detects or handles a child caller**, and it is the client's duty. Disclosed in `/legal/privacy` §11 and `/legal/acceptable-use` §3. |
| DP-16 | Significant Data Fiduciary duties (DPO, DPIA, annual audit) | §10, Rule 12 | **NOT ENGAGED** | SDF status arises only on Government notification. None. Must be re-checked if the Government notifies a class covering voice/AI processors. Add to the OPERATIONS quarterly re-verify list. |
| DP-17 | Cross-border transfer: permitted except to notified countries; observe conditions | §16, Rule 15 | **MET, but see F-1** | No restricted-country list notified as at Aug 2026, so the transfers are lawful. The obligation that bites today is **disclosure**, and F-1 is where we were failing it. |

### 3.2 TRAI / TCCCPR 2018 (as amended) and the Telecommunications Act 2023

| # | Obligation | Status | Evidence / what closes it |
|---|---|---|---|
| T-1 | TM registration before any commercial call | **EXTERNAL** | Blocker `tm_registration_missing` from `platform_state`; blocks every tenant at once. Needs the legal entity → DLT registration (ROADMAP Milestone-0). |
| T-2 | PE registration + active TM link per client | **MET (as a gate)** | `pe_registration_missing` → `pe_registration_not_active` → `tm_link_not_active`, sequenced deliberately. |
| T-3 | Header + voice template registration, per classification | **MET (as a gate)** | `number_not_registered`, `dlt_template_missing/_not_approved/_mismatch`. |
| T-4 | 140 promotional / 160 transactional-service series | **MET (as a gate)** | `number_series_mismatch`, `number_missing`. |
| T-5 | National preference (DND) scrub before promotional dialling | **PARTIAL, honestly marked** | `preference_scrub_runs` + `national_dnd_scrub_missing/_expired/_incomplete`, re-checked on every dispatch tick because the verdict expires at 23:59:59 IST. **The reference is recorded from an operator and never queried back** — the gate proves an accountable assertion, not a performed scrub (`tests/national_dnd_test.py::UNVERIFIED_SCRUB_EVIDENCE`). Closes with a DLT platform login, i.e. with T-1. |
| T-6 | Tenant DNC honoured, opt-out propagated near-real-time | **MET** | Contacts marked `dnc_blocked` before CAS to `running`; `campaigns.dnc_scrubbed_at` stamped in the same statement. |
| T-7 | Calling hours | **MET** | `DEFAULT_WINDOW = (09:00, 21:00)` IST, `apps/api/compliance/service.py:75`; a campaign window may only narrow it (`campaigns/service.py::campaign_window_open`). |
| T-8 | No cross-selling on service calls | **PARTIAL** | Topic fencing is config + a regression scenario, not a runtime gate. Acceptable; state it rather than imply enforcement. |
| T-9 | Consent provenance for uploaded lists | **MET** | `consent_provenance_missing`, `consent_source_refused`; the enum deliberately includes `purchased_list` so the refusal is expressible. Excellent design and now quoted verbatim in `/legal/acceptable-use` §2.5. |
| T-10 | **AI identification on a commercial voice call** | **NO NOTIFIED RULE TODAY** | Researched 16 Aug 2026: the TCCCPR **Third Amendment 2026 is a draft** — consultation opened 13 March 2026 and it had not been notified as final. The IT (Intermediary Guidelines) Amendment Rules 2026 (notified 10 Feb 2026, in force 20 Feb 2026) impose synthetically-generated-information labelling on **intermediaries publishing content**, which a telephone call is not. **So the founder's per-agent toggle is not currently unlawful in India.** The exposures that remain are real and are named in F-4. |
| T-11 | Telecommunications Act 2023 s.28 — prior consent, DND registers | **Applies to licensees, flows to us via the client** | s.28 duties sit on the access provider; TCCCPR is the instrument that reaches a telemarketer. Recorded so nobody cites s.28 at Calevate directly. |

### 3.3 IT Act 2000 + SPDI Rules 2011 — **operative law today**

This is the row most likely to be got wrong, because DPDP is the headline. Substantive DPDP
obligations commence **13 May 2027**; until then s.43A and the SPDI Rules 2011 are in force.

| # | Obligation | Status | What closes it |
|---|---|---|---|
| S-1 | Publish a privacy policy on the website (Rule 4) | **MET as of this change** | `/legal/privacy`. There was no privacy policy on the site at all before it. |
| S-2 | Designate a Grievance Officer and **publish their name** and contact (Rule 5(9)); redress in one month | **PARTIAL** | Published as `{{GRIEVANCE_OFFICER_NAME}}`. **A placeholder is not a designation** — this is UNMET until a person is appointed. It is the single cheapest unmet obligation on this page. |
| S-3 | Reasonable security practices; ISO 27001 is the safe harbour (Rule 8) | **PARTIAL** | We hold **no certification of any kind**. Rule 8 also admits a "comprehensive documented information security programme"; `docs/SECURITY-COMPLIANCE.md` §5 plus DPA Annex B is the closest thing and is not yet a formal ISMS document. |
| S-4 | Consent before collecting sensitive personal data | **PARTIAL** | Health/financial detail volunteered on a call is SPDI. Disclosed in `/legal/privacy` §3.3 and DPA Annex A; the *consent* is the client's to obtain. |

### 3.4 Consumer Protection Act 2019 + E-Commerce Rules 2020

| # | Obligation | Status | Notes |
|---|---|---|---|
| C-1 | Display legal name, office address, website and customer-care + grievance-officer contact | **PARTIAL** | Now on `/legal/*` as placeholders. **The site footer carries none of it** — see FOLLOW-UP-1. |
| C-2 | Acknowledge a complaint in 48h, redress in one month | **MET as published, UNMET as process** | See DP-8. |
| C-3 | No misleading claims about the service | **BREACH TODAY** | See F-1. |
| C-4 | Applicability | Calevate sells B2B, and CPA excludes purchases for a "commercial purpose" — but a sole proprietor buying to earn a livelihood by self-employment is a consumer. Given the target market (Indian SMBs, many proprietorships) **assume the Act applies** and do not draft as if it does not. `/legal/terms` §16 carries an express carve-out. |

### 3.5 GST and payments

| # | Obligation | Status | Evidence |
|---|---|---|---|
| GST-1 | Tax invoice particulars (Rule 46, CGST Rules) | **MET in code** | `apps/api/billing/invoice.py` — supplier + recipient identity and GSTIN, serial, date, per-line SAC, taxable value, rate, tax head, place of supply; place of supply resolved per IGST s.12(2)(a). |
| GST-2 | 18% on SaaS, SAC 998315 | **MET** | `billing/invoice.py` header comment cites both; `gst_supply_sac` default. |
| GST-3 | Unregistered person must not collect tax (CGST s.32) | **MET** | The module refuses to render a tax invoice without a supplier GSTIN, and issues a proforma instead. |
| GST-4 | Corrections by credit/debit note under s.34 | **MET** | Explicit in `billing/invoice.py`; append-only ledgers make it the only available shape. |
| GST-5 | GST registration itself | **EXTERNAL** | `{{GSTIN}}`. Blocks GST-1..GST-4 from being anything but code. |
| GST-6 | e-invoicing (IRN) above ₹5 crore turnover | **NOT ENGAGED** | Re-check on crossing the threshold. Added to §8. |
| GST-7 | Payment aggregator onboarding requires published refund/cancellation policy, terms, privacy policy, and real contact details incl. a working phone | **MET as of this change** | `/legal/refunds`, `/legal/terms`, `/legal/privacy`, `{{CONTACT_PHONE}}`. **None of these existed before**, which would have failed Razorpay onboarding at the first review. |
| GST-8 | No raw card data stored | **MET** | `apps/api/billing/payments.py` — gateway-hosted; nothing in the schema holds a PAN. |

---

## 4. Security measures that actually exist

Stated so the DPA's Annex B is verifiable and so nobody has to trust a marketing list.

- **Tenant isolation**: forced RLS on every tenant table; app connects as
  `calevate_app: NOSUPERUSER NOBYPASSRLS` (`.env.example`); `scripts/check_rls_coverage.py`
  in `make guardrails`; cross-tenant zero-rows tests mandatory per hard rule 1.
- **Two realms, two Clerk apps**, cookies key-suffixed per publishable key
  (`apps/web/src/lib/auth/clerkRuntime.tsx`).
- **Admin MFA enforced server-side** in `apps/api/core/auth.py::verify_token` from Clerk's
  `fva` claim; unknown fails closed (`403 mfa_claim_missing`).
- **RBAC asserted at boot** in four directions (`core/rbac.py::assert_policy_registry_complete`);
  realm separation is also a CHECK constraint, not only a Python convention.
- **Impersonation is read-only**, needs a short-lived RFC-8693-shaped signed grant bound to
  operator *and* tenant, and writes two audit rows (`apps/api/core/impersonation.py`).
- **Append-only ledgers** enforced by DB trigger, verified by
  `scripts/check_ledger_immutability.py`; **audit hash chain** keyed with HMAC
  (`apps/api/compliance/audit.py`), with a Redis-serialised head (D-59).
- **Redaction**: Aadhaar (Verhoeff), PAN, card (Luhn), OTP + an LLM pass for spoken digits;
  `text_redacted` is the default in every response; raw text needs `calls:read_raw` **and**
  an `audit_log` write (`apps/api/crm/routes.py:162-175`). `scripts/check_redaction_exposure.py`
  guards it.
- **Log/trace/error redaction**: same `redact_text`/`redact_mapping` pair backs the JSON
  formatter, Sentry `scrub_event` **and** `scrub_breadcrumb`, and traces are redacted at the
  **exporter** (`_RedactingSpanExporter`) because the OTel SDK writes exception events that
  never reached the attribute allowlist (D-61).
- **Object storage**: `PRESIGN_TTL_S = 300` (`apps/workers/storage.py:48`); account-level
  public-access block; SSE + per-tenant envelope keys.
- **Secrets**: envelope encryption in Postgres with the KEK env-only
  (`PLATFORM_KEK`, `scripts/check_bootstrap_keys.py`); rotation with an overlap
  (`PLATFORM_KEK_RETIRED`).
- **Webhooks**: Bolna is unsigned, so source-IP allowlist + execution-id dedupe + poller as
  truth (TRD §5); outbound HMAC-signed with a bounded retry budget.
- **Model residency**: `scripts/check_model_residency.py` fails the build on a global Google
  host, on a non-`asia-south1` aiplatform literal, or on a region reachable from
  console-editable config. This is the one residency guarantee that is *enforced* rather
  than asserted, and the public documents say exactly that and no more.

**Not in place, and named in the documents rather than glossed:** no ISO 27001, no SOC 2,
no penetration test, no restore drill ever passed (`infra/backup/` "applied to nothing and
never run", D-50), no production deployment.

---

## 5. Findings — where we do NOT satisfy an obligation

These are ordered by how much damage they do. **This list is worth more than the policy
pages.**

### F-1 — The marketing page makes a data-residency claim the deployment blueprint contradicts. **BREACH TODAY.**

`apps/web/src/app/page.tsx` (§ "Your customers' data") states:

> **It stays in India** — "Calls, transcripts and recordings are processed and stored in
> Indian regions."

Against the tree:

- `docs/DEPLOYMENT.md` §0: the site stack — web, api, workers, **and PostgreSQL, which holds
  every transcript, lead and phone number** — hosts on a *"general-purpose VPS
  (Hetzner-class); **India co-location is NOT required for it**"*, and §0 goes on to cost a
  *"Hetzner-class **European** VPS"* at ~150 ms from a Bolna-India call.
- `docs/DEPLOYMENT.md` §1: *"Object storage: Cloudflare R2 (recordings, raw payloads,
  exports)"*, with `AWS_REGION=auto`. R2 chooses location automatically and offers no
  India-only jurisdiction.
- `docs/SECURITY-COMPLIANCE.md` §4 CAUTION: **Bolna call recordings observed on S3
  `us-east-1`**; the residency posture "must be pinned in the Bolna contract" and has not
  been.
- Clerk, Resend and Sentry are all operated outside India.

**This is also a documented internal conflict I am required to flag rather than silently
resolve** (CLAUDE.md: *"docs/ is authoritative … flag the conflict, don't silently pick"*):
root `CLAUDE.md` says *"a Hetzner-class VPS with an **India-resident data plane**"* while
`docs/DEPLOYMENT.md` §0 says India co-location is **not required** for that tier. Docs win,
so the honest position today is **the hosting region is undecided and nothing is
provisioned**.

Exposure: CPA 2019 misleading-claim; DPDP transparency; and a contractual misrepresentation
to any client who bought on that sentence.

**What closes it — pick one, and only one is cheap:**
1. Decide the host is in India (Bengaluru/Mumbai region), provision it, and the sentence
   becomes true for the database — but *not* for R2, Clerk, Resend, Sentry or Bolna, so the
   sentence still needs narrowing; **or**
2. Narrow the landing-page copy to the claim that is enforced: *"every model endpoint is
   pinned to an Indian region, and the build fails otherwise"* — which is a stronger claim
   than most competitors can make and is checkable (`scripts/check_model_residency.py`).

I did not edit `page.tsx` — it is outside my scope. **This is FOLLOW-UP-2 and it should be
done in the next change, not scheduled.** `/legal/privacy` §8 already carries a callout
saying that any such claim elsewhere is an intention and that §8 overrides it, and
`tests/legal.test.tsx` bans the claim from ever appearing in a legal document.

### F-2 — ~~The archived raw engine payload has no retention clock.~~ **CLOSED (D-179).**

The finding as recorded: `calls.engine_payload_ref` (D-126) holds the vendor's own document
per call — caller number and transcript — and `retention_policies.data_category` admitted
only `recording|transcript|lead|consent_log`, so **nothing expired it**. The only clock was
a 90-day `engine-payloads/` bucket lifecycle rule that `infra/README.md` §5 records as never
having been applied. An erasure request *did* reach it (`_erase_engine_payloads`), so the
gap belonged to everyone who never filed one — which, against DPDP §8(7), is a real defect
and not a tidiness issue.

**Closed by D-179.** Migration `c4d1f7b83e26` adds `engine_payload` to the category enum;
`scripts/seed.DEFAULT_RETENTION_POLICIES` installs it at 90 days, which is not a new number
— it is the period `infra/object-lifecycle/policy.json` already assigned that prefix, now
enforced by a mechanism that runs. The sweep arm pages expired calls into the SAME
`_erase_engine_payloads` the erasure uses, so there is one definition of destroying a
call's archived documents; a store that will not answer defers the arm instead of failing
the tick. `tests/engine_payload_retention_test.py` asserts against the BYTES, including the
cross-tenant zero-rows case.

**Still counsel's / the founder's:** the NUMBER, if 90 days is wrong for a client. It is a
per-tenant default like every other row in that table, so changing it is a settings change
rather than a code one.

### F-3 — ~~Knowledge-base content is never expired and never searched by an erasure.~~ **CLOSED (D-179), on the two halves that were ours.**

The finding as recorded: migration `842ba923796d`, `kb/models.py`, `kb/service.py`,
DATA-MODEL §7 and BUILD-LOG §18 all said provider-side ids in `kb_documents.meta` are "what
lets a DPDP erasure prove it removed both copies", and **no erasure removed either copy and
none ever had**. A client's uploaded content — which a "knowledge base" invites their staff
names and numbers into — was kept indefinitely, every version, with no TTL and no erasure
path.

**Closed by D-179, with two mechanisms rather than a rewording**, because the certificate
entry NARROWS as a result and SEC-COMP §4 does not permit narrowing the limitations text on
prose alone:

- **A clock.** `retention_policies.data_category` gained `kb` (365 days by default). The
  sweep deletes SUPERSEDED and REJECTED versions — never the live one, which is what the
  agent answers from, and never one still carrying an engine handle, because a handle
  recorded against an archived source means an incomplete detach and forgetting our row
  would strand the only record that can address the platform's copy.
- **A search.** `execute_deletion_request` looks for the subject's number in the tenant's
  knowledge documents, matching on digits because a client writes "98765 43210" and never
  an E.164 string, and records the count in the proof. `KB_OUTCOME` is now
  `searched_not_erased`, and the certificate hands the client a number and names the manual
  step.

**Deliberately NOT done, and stated on the certificate rather than left to inference:** the
erasure does not CHANGE that content. Editing a live price list changes what the agent says
on the next call, we cannot tell a caller's callback number from the shop's own landline,
and the voice platform holds its own copy of the live version — so removal is a manual step
on both copies. `tests/kb_retention_test.py` (which replaces the gap register
`kb_retention_gap_test.py`) holds all of it, and the AUP term at `/legal/acceptable-use` §3
still stands beside it.

**Still counsel's:** whether the client's own uploaded content should be editable by an
erasure at all is a judgement about their words, not a mechanism we are missing.

### F-4 — Making disclosure a per-agent toggle is lawful today and carries four named risks. **DECIDED; risks must be owned in writing.**

Researched position as at 16 Aug 2026: **no notified Indian rule requires a commercial voice
call to announce it is AI.** The TCCCPR Third Amendment 2026 was still a draft under
consultation, and the IT Amendment Rules 2026 SGI labelling reaches intermediaries
publishing content, not telephony. The founder's decision is therefore inside the law.

The residual risks, each of which the documents now allocate to the client:

1. **Recording without notice.** Delhi HC in the *Sanjay Pandey* bail order treated recording
   without the other party's consent as an interference with Art. 21 privacy; `docs/SECURITY-COMPLIANCE.md`
   §1 already flags criminal exposure. One-party-consent case law (*R. M. Malkani*, 1973)
   cuts the other way for a participant. **This is genuinely contested and it is the client's
   exposure, but it becomes ours if we are seen to have designed the concealment.**
2. **The draft TCCCPR amendment could be notified with an AI-identification duty**, at which
   point the toggle becomes a compliance switch that must default the other way.
3. **EU AI Act Art. 50** has applied since **2 August 2026** to AI systems interacting with
   natural persons. Not v1 scope, but a single EU caller puts it in scope.
4. **CPA 2019 misleading conduct** if a caller is left with the impression they spoke to a
   person.

**What the code must do, and the documents now promise it does:** the truthful answer when
asked must be enforced **server-side, above the tenant prompt**, and must not be a
configurable behaviour. `/legal/privacy` §5 and `/legal/acceptable-use` §2.6 state that in
identical words, and `tests/legal.test.tsx` asserts both documents carry it.

> ⚠ **This is a promise the code must keep, and I did not verify it in this worktree.** The
> toggle work is in flight in a parallel session; on this branch
> `agents.disclosure_line` is still `NOT NULL` with a non-empty CHECK
> (`apps/api/agents/models.py:64,138`) and `disclosure_spoken` still measures a single fixed
> line. **Whoever lands the toggle must (a) keep the truthful-answer floor unconditional and
> server-enforced, and (b) keep `calls.disclosure_played` meaningful when the announcement is
> off** — otherwise the QA compliance queue starts certifying a property it no longer
> measures, which is exactly the P3.3 defect that module was written to fix.

### F-5 — Retention: the documents and the seed disagree, and I published the seed's numbers. **OURS, founder's call.**

Already an open question in `docs/SECURITY-COMPLIANCE.md` §4, restated here because it is now
a *published* commitment:

| Category | SEC-COMP §4 says | `scripts/seed.DEFAULT_RETENTION_POLICIES` installs | What `/legal/privacy` §9 now publishes |
|---|---|---|---|
| Recording | 180 days (over a 90-day floor) | **90 days** | 90 days |
| Transcript | 24 months (730 d) | **365 days** | 365 days |
| Lead | 24 months (730 d) | **1095 days** | 1095 days |
| Consent log | — | 2555 days, never expired on a timer | retained |

I published **what the code enforces**, because a notice that states a period the sweep does
not honour is the worse of the two errors in both directions (a transcript deleted at half
the promised age, a lead kept at 1.5×). **The founder must now reconcile them in one
release**: SEC-COMP §4, `DEFAULT_RETENTION_POLICIES`, and `/legal/privacy` §9 all change
together, with a ROADMAP §6 entry. Existing tenants' agreed rows are their own decision.

### F-6 — ~~No breach-notification procedure behind the DPA's 48-hour promise.~~ **CLOSED (D-179).**

The finding as recorded: `/legal/dpa` §7 commits us to notifying a client within 48 hours —
deliberately shorter than their own 72-hour Board duty under Rule 7 — and behind it there
was OPERATIONS §7, `runbooks/`, and **no notification template, no Board route and no
mechanism**. It was named the highest-value unmet item on this list.

**Closed by D-179**, as the runbook this finding asked for plus the part a document cannot
be:

- `runbooks/data-breach-notification.md` — the three clocks and who each duty belongs to
  (the role split is what wastes the window when it is got backwards), the scope walk over
  the four personal-data stores outside Postgres, the incident file, who signs off and what
  happens when they cannot be reached, and where each notice is sent.
- `apps/api/compliance/breach.py` — the Rule 7 content as fields, so a notice cannot be sent
  at 3am with a required element missing. Rendering is REFUSED on a missing element or on
  anything shaped like a phone number, and the 48 hours is one constant pinned by test
  across the DPA, the runbook and the notice.
- `scripts/breach_notice.py` — `uv run python -m scripts.breach_notice incident.json`.

It **sends nothing**, deliberately: who signs off is a named human decision, and a tool that
could mail every client at once during an incident is a blast radius rather than a control.

**Rule cited with its date:** DPDP Rules 2025, **Rule 7**, notified **14 November 2025**,
substantive commencement 13 May 2027; re-read on **17 August 2026** for this work. As with
every citation in §9, the gazette text is unreachable from this environment and the standing
is a synthesis of concurring secondary sources.

**Still outside the repo, and named in the runbook's own §7 rather than discovered at 4am:**
(a) the Data Protection Board's reporting channel, which nobody has established — a lookup,
blocked on nothing; (b) counsel's review of the notice wording and of the rule summary. The
mechanism does not change either way, and neither is a reason to delay a notification.

### F-7 — ~~The erasure does not reach backups, and the certificate does not say so.~~ **CLOSED (D-164).**

The finding as recorded: both backup chains retain **35 days**, a point-in-time restore
un-erases people, and `ERASURE_LIMITATIONS` carried no backup clause while disclosing every
other limitation. Publishing `/legal/privacy` §9/§12.4 and the DPA sharpened it into a live
inconsistency — the public notice and the document a client hands to a data principal said
different things.

**Closed by D-164**, and the asymmetry is what closed it rather than a fresh legal judgement:
once the DPA stated the window to the client in writing, the commitment was already made, and
withholding the same fact from the *data principal* was the wrong way round. `ERASURE_LIMITATIONS`
now carries the clause, `ERASURE_EXCEPTIONS` its index-aligned `backup` entry, and
`BACKUP_WINDOW_DAYS` is pinned by test across the runbook, the DPA and the certificate.
SEC-COMP §4's open question is marked decided.

**Still counsel's:** the WORDING, not the disclosure. If counsel rewrites the clause the
finding stays closed — what was decided is that the fact is disclosed.

**What closes it:** add the backup clause to `ERASURE_LIMITATIONS`
(`apps/api/compliance/deletion.py`) in the same release that publishes these pages. It is one
tuple entry plus its `ErasureLimitation` twin and the pairing test. **I could not make it —
`apps/api` is outside my scope this session — and it should be the first Python change after
this one.** FOLLOW-UP-3.

### F-8 — ~~No mechanism helps a client produce their own privacy notice to callers.~~ **CLOSED (D-179).**

The finding as recorded: we are the Processor, the notice duty is the client's, and DPDP
Rule 3 requires an itemised description of the personal data — which for a Calevate client
is *whatever extraction schema they defined*, a thing only the product knows. A client could
not write that notice accurately without us, and nothing helped them.

**Closed by D-179.** `GET /v1/compliance/caller-notice` (`org:read`, client realm) generates
a DRAFT from the tenant's own configuration: the itemised list is what a phone call
inherently collects plus the union of every reachable agent's extraction fields, the periods
are their own `retention_policies` rows, and the announcement paragraph is written from the
D-163 per-agent switches — so an agent whose AI disclosure is OFF changes what the draft
says and adds a task, rather than being absorbed into a template that claims an
announcement their agent does not make. The truthful-ANSWER floor is stated as the platform
property it is.

It is marked DRAFT in the envelope **and** in the text (a disclaimer that lives only in the
response does not survive the copy-paste that is the whole point), every blank only the
client can fill is a visible `{{...}}`, and it carries no caller's data — field labels, never
values. `tests/caller_notice_test.py` holds the accuracy properties and the cross-tenant
zero-rows case.

**Still counsel's:** the wording, the client's lawful basis for outbound calling, and where
the notice must be displayed — each named in the draft's own "still to be completed by you"
list rather than guessed at. Rendering it on the onboarding wizard's last step is the web
surface's, not this change's.

### F-9 — No Grievance Officer, no data-protection contact, no entity. **EXTERNAL, and cheapest first.**

S-2 and DP-9 are unmet not for want of code but for want of a name. Appointing a person costs
nothing and closes two statutory obligations in two instruments.

### F-10 — Sub-processor contracts: none signed, downward flow-through unevidenced.

DP-11's downward leg. Bolna's residency and erasure commitments are unrun pilot gates
(`evidence/bolna-pilot-scorecard.md` is an empty template); no DPA has been executed with
Clerk, Resend, Sentry, Cloudflare or the hosting provider. Rule 6(f) requires the contract to
impose equivalent safeguards, and today we would be promising a client something we have not
obtained upstream. **What closes it:** sign the vendors' standard DPAs — all five publish
one — and record the Bolna residency term in the contract before flipping `ENGINE=bolna`.

---

## 6. What the public documents deliberately do NOT claim

Recorded so a later edit cannot quietly reinstate them, and each is asserted by
`tests/legal.test.tsx`:

- No ISO 27001, SOC 2 or PCI-DSS. (`claims no security certification anywhere`)
- No "all data stays in India". (`does not claim data never leaves India`)
- No uptime, latency, accuracy or answer-rate figure — `/legal/terms` §12 says there is no
  SLA and says why, matching the landing page's own refusal to print a latency tile.
- No GSTIN, CIN, PAN or PIN-coded address invented anywhere.
  (`invents no company identity anywhere in the prose`)
- No claim that the erasure reaches engine-side copies — reported as
  `unconfirmed_pending_vendor_api`, exactly as the certificate does.
- No always-on AI disclosure. The documents describe the toggle.

---

## 7. Placeholders the founder must fill

Declared in `apps/web/src/lib/legal/placeholders.ts`, each with what it is and where the
value comes from. `tests/legal.test.tsx` fails if a document uses an undeclared token or if a
declared token stops being used — so this list cannot silently drift.

`LEGAL_ENTITY_NAME` · `ENTITY_REGISTRATION_NUMBER` · `GSTIN` · `REGISTERED_ADDRESS` ·
`CONTACT_PHONE` · `SUPPORT_EMAIL` · `GRIEVANCE_OFFICER_NAME` ·
`GRIEVANCE_OFFICER_DESIGNATION` · `GRIEVANCE_OFFICER_EMAIL` ·
`DATA_PROTECTION_CONTACT_NAME` · `DATA_PROTECTION_CONTACT_EMAIL` · `SECURITY_CONTACT_EMAIL` ·
`JURISDICTION_CITY` · `EFFECTIVE_DATE` · `DLT_TELEMARKETER_ID` · `PRIMARY_HOSTING_LOCATION` ·
`REFUND_PROCESSING_DAYS` · `TERMINATION_NOTICE_DAYS` · `DATA_RETURN_WINDOW_DAYS`

`{{PRIMARY_HOSTING_LOCATION}}` is not an administrative blank: filling it in **is** the F-1
decision.

---

## 8. Additions to the OPERATIONS §7 compliance calendar

- **14 November 2026** — DPDP Consent Manager provisions commence. Re-check whether any
  Calevate flow needs a registered Consent Manager. (Assessment today: no — we collect no
  consent in our own right.)
- **13 May 2027** — DPDP substantive obligations commence; IT Act s.43A and the SPDI Rules
  2011 fall away. Until then §3.3 is the operative regime and the privacy notice must keep
  citing it.
- **16 October 2026** — `GEMINI_DEFAULT_LLM_RETIRES` (BRD R-04). Unrelated to law but on the
  same clock and already tracked.
- **Quarterly** — re-check: whether the TCCCPR Third Amendment has been notified (T-10);
  whether a restricted-country list has been notified under DPDP §16 (DP-17); whether any SDF
  class notification could reach us (DP-16); whether GST turnover has crossed the ₹5 crore
  e-invoicing threshold (GST-6).

---

## 9. Sources, with retrieval dates

All retrieved **16–17 August 2026**. Where the operative text could not be fetched directly
(the egress proxy refuses several Indian legal-publishing domains) the standing is a
**search-engine synthesis of multiple concurring secondary sources**, which is weaker than a
gazette read, and is marked. Counsel should verify every one against the gazette before
publication — that is the first thing §10 asks for.

**DPDP Act 2023 and DPDP Rules 2025**
- MeitY, *DPDP Rules 2025 Notified* (PIB) — https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf (16 Aug 2026; **fetch refused by egress proxy**, cited from concurring summaries)
- Shardul Amarchand Mangaldas, *Enforcement of the DPDP Act and notification of the DPDP rules* — https://www.amsshardul.com/insight/enforcement-of-the-dpdp-act-and-notification-of-the-dpdp-rules/ (16 Aug 2026) — phased commencement 14 Nov 2025 / 14 Nov 2026 / 13-14 May 2027
- EY India, *DPDP Rules 2025 Notified by MeitY* — https://www.ey.com/en_in/insights/cybersecurity/transforming-data-privacy-digital-personal-data-protection-rules-2025 (16 Aug 2026)
- SCC Online, *DPDP Rules 2025: Key Highlights* — https://www.scconline.com/blog/post/2025/12/26/digital-personal-data-protection-rules-2025-key-highlights/amp/ (16 Aug 2026) — Rule 9 contact publication
- Scrut, *India's DPDP Rules 2025: practical guide* — https://www.scrut.io/post/dpdp-rules (16 Aug 2026) — Rule 6 safeguards incl. one-year log retention; Rule 7 72-hour report
- Seclore, *DPDP Rules 2025 compliance guide* — https://www.seclore.com/fundamentals/dpdp-rules-2025-compliance-guide/ (16 Aug 2026) — Rule 14(3) ninety-day grievance limit
- SFLC.in, *DPDP Rules 2025: Significant Data Fiduciaries and Data Transfers* — https://sflc.in/dpdp-rules-2025-significant-data-fiduciaries-and-data-transfers/ (16 Aug 2026) — Rule 12 DPIA/audit, Rule 14/15 transfer
- ELP, *Cross-border data transfers under the DPDP Act* — https://elplaw.in/wp-content/uploads/2025/12/Cross-border-data-transfers-under-the-DPDP-Act-what-businesses-need-to-know.pdf (16 Aug 2026) — negative-list model; **no restricted-country list notified as at mid-2026**
- EY India, *How data fiduciaries should engage processors* — https://www.ey.com/en_in/insights/technology/how-data-fiduciaries-should-engage-processors-for-effective-compliance (16 Aug 2026) — §8(1) non-delegable, §8(2) contract, Rule 6(f) equivalent safeguards
- Consently, *Rule 3 Decoded: DPDP-compliant consent notice* — https://www.consently.in/blog/dpdp-rule-3-itemized-consent-notice-guide (16 Aug 2026) — itemised notice content

**TRAI / telecom**
- TRAI, *Draft TCCCP (Third Amendment) Regulations 2026 released for consultation* (PIB, PRID 2239885) — https://www.pib.gov.in/PressReleasePage.aspx?PRID=2239885 (16 Aug 2026; **fetch refused**, cited from concurring summaries) — consultation opened **13 March 2026**; **still draft, not notified, as at Aug 2026**
- The Policy Edge, *TRAI: Draft TCCCP (Third Amendment) Regulations, 2026* — https://www.policyedge.in/p/trai-draft-telecom-commercial-communications-customer-preference-third-amendment-regulations-2026 (16 Aug 2026)
- Chambers & Partners, *TRAI's Crackdown on Spam Calls and AI-Driven Telemarketing* — https://chambers.com/articles/trai-s-crackdown-on-spam-calls-and-ai-driven-telemarketing (16 Aug 2026)
- TRAI, *TCCCPR Second Amendment, 12 Feb 2025* (gazette) — https://www.trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf (16 Aug 2026)
- FreJun, *TRAI compliance for call centres* — https://frejun.com/trai-compliance-call-centers/ (16 Aug 2026) — 09:00–21:00 calling window; 140/160 series
- Message Central, *India SMS regulations, DLT & TRAI compliance 2026* — https://www.messagecentral.com/en-in/sms-guideline/india (16 Aug 2026) — header/template registration; penalty ladder
- Telecommunications Act 2023, s.28 — https://www.indiacode.nic.in/bitstream/123456789/20101/1/A2023-44.pdf (16 Aug 2026); S.S. Rana & Co. analysis — https://ssrana.in/articles/telecom-act-india-digital-privacy-data-protection-act-2023/ (16 Aug 2026)

**IT Act / SPDI**
- SPDI Rules 2011 (WIPO Lex copy) — https://www.wipo.int/edocs/lexdocs/laws/en/in/in098en.pdf (16 Aug 2026) — Rule 4 published policy, Rule 5(9) grievance officer + one month, Rule 8 ISO 27001 safe harbour
- Opsio, *Are the SPDI Rules still in force after DPDP Act 2023?* — https://opsiocloud.com/in/knowledge-base/are-spdi-rules-still-in-force/ (16 Aug 2026) — **s.43A and SPDI survive until 13 May 2027**
- S&R Associates, *India's DPDP regime takes effect* — https://www.snrlaw.in/indias-digital-personal-data-protection-regime-takes-effect/ (16 Aug 2026)

**AI content / disclosure**
- Khaitan & Co, *MeitY notifies the IT Amendment Rules 2026* — https://www.khaitanco.com/thought-leadership/MeitY-notifies-the-IT-Amendment-Rules-2026 (16 Aug 2026) — notified **10 Feb 2026**, in force **20 Feb 2026**; SGI labelling duties on **intermediaries**
- Freshfields, *India targets deepfakes and AI-generated content* — https://www.freshfields.com/en/our-thinking/blogs/technology-quotient/india-targets-deepfakes-and-ai-generated-content-key-changes-under-meitys-2026-102mjwn (16 Aug 2026)
- Cooley, *EU AI Act: Transparency Obligations Take Effect 2 August 2026* — https://www.cooley.com/news/insight/2026/2026-08-03-eu-ai-act-transparency-obligations-take-effect-2-august-2026 (16 Aug 2026)
- European Commission, *Transparency obligations under Article 50 of the AI Act* — https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act (16 Aug 2026)

**Call recording**
- LiveLaw, *Tapping phone lines or recording calls without consent violates right to privacy: Delhi HC (Sanjay Pandey)* — https://www.livelaw.in/news-updates/tapping-phone-lines-recording-calls-without-consent-breach-right-to-privacy-delhi-high-court-216173 (16 Aug 2026)
- Recording Law, *India recording laws* — https://recordinglaw.com/india-recording-laws/ (16 Aug 2026) — one-party consent line from *R.M. Malkani v State of Maharashtra* (1973); Telecommunications Act 2023 s.20 replaced the Telegraph Act on 26 June 2024

**Consumer protection**
- Trilegal, *Consumer Protection (E-Commerce) Rules, 2020 — analysis* — https://trilegal.com/wp-content/uploads/2021/11/Consumer-Protection-E-Commerce-Rules-2020.pdf (16 Aug 2026) — rule 4(6) grievance officer, 48h acknowledgement, one-month redress, display of legal name and address
- Khaitan & Co, *Stricter regulations on e-commerce* — https://www.khaitanco.com/thought-leaderships/Stricter-Regulations-on-E-Commerce-The-Consumer-Protection-E-Commerce-Rules-2020 (16 Aug 2026)

**GST and payments**
- Tax Garden, *GST on IT/software/SaaS services India 2026: SAC codes and rates* — https://taxgarden.in/blog/gst-on-software-it-services-saas-india-2026-sac-codes (16 Aug 2026) — SAC 998315, 18%
- Tax Garden, *GST invoice rules: mandatory fields, e-invoice (2026)* — https://taxgarden.in/blog/gst-invoice-rules-format-mandatory-fields-e-invoice-india-2026 (16 Aug 2026) — Rule 46 fields; e-invoicing above ₹5 crore from 1 Apr 2026
- Razorpay, *Payment gateway compliance in 2026* — https://razorpay.com/blog/payment-gateway-compliance/ (16 Aug 2026) — merchant website must publish privacy policy, terms, refund/cancellation policy, and real contact details incl. a working phone number
- Razorpay Docs, *Business onboarding* — https://razorpay.com/docs/payments/international-payments/accept-international-payments-from-indian-customers/s2s-integration/business-onboarding/ (16 Aug 2026)

---

## 10. What a lawyer should look at first

1. **F-1.** Is the landing page's residency sentence a misrepresentation as it stands, and
   which of the two fixes is required rather than merely advisable? This is the only item
   here that is arguably a live breach.
2. **F-4.** The disclosure/recording toggle. Confirm the position that no notified Indian
   rule requires AI identification on a voice call **as at the date of advice**, and advise
   on recording-notice exposure given the conflict between *R.M. Malkani* and the *Sanjay
   Pandey* line. Advise specifically on whether Calevate, as designer of the toggle,
   acquires exposure the client would otherwise carry alone.
3. **The liability allocation in `/legal/terms` §14** — the cap at twelve months' fees with
   an uncapped client indemnity for telecom and consent breaches. It is the commercially
   load-bearing clause and the one a client's counsel will push hardest on.
4. **F-5.** Which retention periods are we committing to? The answer must be one set of
   numbers in three places.
5. **The DPA's 48-hour breach clause** (`/legal/dpa` §7) against F-6: we have promised a
   timeline we have no procedure for. Advise whether to build the procedure or lengthen the
   clause. Do not leave both.
6. **Whether the Consumer Protection Act 2019 applies** to the SMB/proprietor customer base,
   and whether the arbitration clause in `/legal/terms` §16 survives it.
7. **F-7 (now a review, not a question).** The backup-retention window IS disclosed on the
   certificate as of D-164. What counsel should check is the clause's wording against DPDP
   §8(7), not whether to have one.
8. **Every citation in §9** against the gazette. Several were retrieved as secondary
   summaries because the primary sources are unreachable from this environment.

---

## 11. Required follow-ups outside this session's scope

| # | Action | Why it is not done here |
|---|---|---|
| FOLLOW-UP-1 | Add `/legal` links to the site footer in `apps/web/src/app/page.tsx` (its footer currently carries no links at all) and to the two realm shells. Also add legal-page links to the sign-up flow. **Nothing on the site links to `/legal` today, so the documents are unreachable except by typing the URL** — and a payment aggregator's reviewer will look for exactly those links. | `apps/web/src/app/page.tsx` and `apps/web/src/components/**` are outside this session's edit scope. |
| FOLLOW-UP-2 | Resolve F-1: either provision an Indian host or narrow the landing-page copy. | Same file, same reason. It should be the next change made. |
| FOLLOW-UP-3 | Add the 35-day backup clause to `ERASURE_LIMITATIONS` / `ERASURE_EXCEPTIONS` in `apps/api/compliance/deletion.py`, so the certificate and `/legal/privacy` §9 agree. | `apps/api` is outside this session's edit scope. |
| ~~FOLLOW-UP-4~~ | ~~F-2 and F-3: retention categories for the engine-payload archive and for KB content~~ — **DONE (D-179)**: migration `c4d1f7b83e26`, two sweep arms, and the erasure's knowledge-base search. | Was outside the audit session's edit scope; closed in the next one. |
| FOLLOW-UP-6 | **Two published callouts now UNDER-claim.** `/legal/privacy` §9 ("Two stores that no retention period reaches yet") and `/legal/dpa` §8 ("Two stores with no retention period yet") both state that the archived engine payload and knowledge content have no retention period, and privacy adds that the knowledge base "is not searched by an erasure request". D-179 made all three sentences false in the client's favour: `engine_payload` and `kb` are retention categories now, and the erasure searches and reports. Under-claiming is not a breach, which is why this is a follow-up and not a finding — but a public document that is wrong about our own controls is a defect, and the pair should be rewritten to say what the mechanisms do and what is still manual. | `apps/web/**` is outside this session's edit scope (a parallel session owns it). One callout each, in the same wording D-179 uses on the certificate. |
| ~~FOLLOW-UP-5~~ | ~~F-6: write the breach-notification runbook section.~~ — **DONE (D-179)**: `runbooks/data-breach-notification.md`, `apps/api/compliance/breach.py` and `scripts/breach_notice.py`. What remains is the Board's own reporting channel, which is a lookup and is recorded in that runbook's §7. | Was outside the audit session's ownership; closed in the next one. |
