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
the whole of `apps/web/src/app` and `apps/web/src/lib/auth`. *(That last path is the
17-Aug spelling. D-177 deleted `lib/auth/`; the successor is `apps/web/src/lib/authn/`, and
the sub-processor and cookie copy this audit read now lives in `apps/web/src/lib/legal/` —
see F-11, which is what re-reading them in August 2026 found.)*

Law was researched on the web on **16–17 August 2026** — every source is listed in §9 with
its retrieval date, because Indian data-protection and telecom law moved substantially in
2025–2026 and a document written from memory would be wrong in specific, damaging ways.

**The single most important framing fact, and it changes how every row reads:** *nothing
is in production.* No DLT registration, no provisioned host, no live client, and
`ENGINE=fake` is the shipped default. Almost every "UNMET" below is therefore either (a)
waiting on a founder decision or an external registrar, or (b) a real code gap that can be
closed now. The rows say which.

**The legal entity IS now decided — this line said "no legal entity decided" and the 24
Aug 2026 playbook settles it.** Per `docs/legal/LEGAL-OPS-PLAYBOOK.md` §0 and §3 (the
playbook is the legal source of truth and wins over this document), the entity is a **sole
proprietor / trade name under the founder's PAN** — "Calevate is a product operated by
[legal name], sole proprietor", not a separate company. That decision changes what several
EXTERNAL rows are blocked ON — they wait on the registrars a sole proprietor uses (Udyam,
then DLT TM-ID, GST only on a trigger), not on an entity choice that has not been made — but
it does NOT move anything into production: the registrations themselves are unfiled, and the
`{{LEGAL_ENTITY_NAME}}` / `{{GSTIN}}` / entity-number placeholders in §7 are still blank
because the sole proprietorship, though decided, has not been registered anywhere yet. So
the "nothing is in production" framing stands unchanged; what is retired is the false
premise that the shape of the legal person is still open.

---

## 1. The two role splits everything else hangs off

| Fact | Evidence |
|---|---|
| **Calevate is a Data Processor** for callers' personal data; the client business is the **Data Fiduciary**. | `apps/api/compliance/deletion_routes.py` docstring: *"A data principal asks the CLIENT to erase them; the client — the Data Fiduciary, we are their Processor — asks us."* Erasure is a **client-realm** surface requiring `org:manage`; there is no admin-realm route that erases one data principal on their own request. `docs/SECURITY-COMPLIANCE.md` §4. |
| **Calevate is the Data Fiduciary** for client-account data (users, org, billing, KYC). | `apps/api/tenancy/models.py` — `users(email, name, phone)`, `organizations(name, slug, billing_email, intake)`; `apps/api/compliance/models.py` `kyc_records`; and since D-170 the CREDENTIAL itself, `auth_credentials` (Argon2id hash + KEK-derived pepper) and `auth_sessions`, which Clerk used to hold outside India. Nothing treats these as processed on anyone's instruction. |
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

`users(email, name, phone)`; `memberships.role`; **and, since D-170/D-177 brought
authentication in-house, the sign-in material itself** — `auth_credentials` (Argon2id hash,
peppered from the KEK; never a reversible secret), `auth_sessions` (opaque token
fingerprint, `mfa_verified_at`, idle/absolute bounds) and the one-time codes that back the
second factor. This is the category that used to sit with a US vendor and now sits in our
Postgres, which is the whole of D-165's residency argument. *(`users.clerk_user_id` is
still a COLUMN — unwritten and unread since D-177, kept one release under hard rule 8's
two-step deprecation and recorded in `scripts/check_wiring.UNWIRED_BASELINE`. It holds no
new data and AUTH-MIGRATION §11 names the DROP that closes it.)*

`organizations(name, slug, billing_email, intake JSONB)` — **`intake` contains staff names
and escalation numbers** and is flagged "never log it" in `apps/api/tenancy/models.py`;
`kyc_records(entity_type, document_kind, document_ref, signatory_name, evidence_ref)`;
`dlt_registrations`; `plans` (commercial terms); `audit_log(actor, tenant, action, ip)`;
`credit_ledger` / `usage_events`.

`kyc_records` carries `CHECK (document_ref !~ '^[0-9]{12}$')` — a deliberate backstop so an
Aadhaar number cannot be stored in a business-registry field. Good control; noted as such.

### 2.3 Website visitors

**Nothing beyond request logs.** `apps/web/src/app/layout.tsx` mounts no analytics and no
third-party script; fonts are `next/font/local`. **There is no third-party auth provider
mounted anywhere any more** — D-177 removed the vendor, `@clerk/*` is not a dependency of
`apps/web`, and the only session providers are ours (`lib/authn/adminSession.tsx`,
`lib/authn/clientSession.tsx`), mounted under the two realm layouts. A visitor who never
signs in is therefore served no cookie from anyone. Grep for
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
| DP-10 | Reasonable security safeguards: encryption/masking, access control, logs+monitoring, retained **one year**, continuity | Rule 6 | **CLOSED (stated policy), 24 Aug 2026** | Everything in §4 below is real, and the one leg that was unevidenced — log retention — is now a stated policy in `docs/OPERATIONS.md` §4.1. Two record classes, governed separately: **`audit_log`** (and every append-only ledger in `db/registry.APPEND_ONLY_TABLES`) is INSERT-only under a DB trigger with no sweep row against it, so it is **retained indefinitely, never expired — ≥1 year by construction** and now stated as such rather than inferred; **application logs** (structured JSON on stdout + Sentry events) carry a **365-day** period set at the host log sink (journald / shipper index / Sentry project retention). Application logs are NOT written to object storage — there is no `logs/` prefix in `infra/object-lifecycle/policy.json` and nothing in the app puts them there — so this closes as an OPERATIONS-stated policy, **not** a lifecycle rule (a lifecycle rule over a bucket that holds no logs would be theatre). The 365-day floor is DPDP Rule 6's "one year"; CERT-In's shorter-but-stricter 180-days-in-India log rule (S-7) is satisfied within it on days, with its Indian-jurisdiction condition flagged in §4.1 for when a host is provisioned. |
| DP-11 | Data-processor contract imposing equivalent safeguards | §8(2), Rule 6(f) | **MET as text, UNMET as practice** | `/legal/dpa` is that contract, and Annex B is the equivalent-safeguards clause. **Downward**: we owe the same to *our* sub-processors, and **no vendor contract has been signed** — the Bolna residency commitment is an unrun pilot gate (`evidence/bolna-pilot-scorecard.md` is an empty template). |
| DP-12 | Breach notification: Board without delay, detailed report ≤72h, affected principals with no threshold | Rule 7 | **MET as procedure; one lookup outstanding** | D-179: `runbooks/data-breach-notification.md` (the three clocks, the role split, the scope walk, the sign-off), `apps/api/compliance/breach.py` (the Rule 7 content, refused if an element is missing or a phone number is present) and `scripts/breach_notice.py`. The 48-hour DPA promise is pinned by test across the DPA, the runbook and the notice. **Outstanding: the Board's own reporting channel** — a lookup nobody has done, recorded in the runbook's §7 rather than left to be discovered mid-incident — and counsel's review of the wording. |
| DP-13 | Retention limited to purpose; erase when purpose served | §8(7), Rule 8 | **PARTIAL** | Nightly sweep enforces per-tenant TTLs (`apps/workers/retention.py`). The two stores that escaped it are closed (F-2, F-3, D-179). **One store still has no clock: uploaded campaign contacts** — the category is deliberately absent because the period is a DPA commitment the founder must give, and `tests/dpdp_known_gaps_test.py` holds that open by probing the CHECK constraint. |
| DP-14 | Third Schedule erasure periods + 48h pre-erasure notice | Rule 8(3) | **NOT ENGAGED** | Correctly analysed already in SEC-COMP §4: they bind e-commerce/gaming/social-media fiduciaries above 2 crore / 50 lakh user thresholds. Calevate is none of those. |
| DP-15 | Children: verifiable parental consent, no tracking/behavioural ads | §9 | **PARTIAL** | We build no profiles and run no advertising, so the prohibition half is met by construction. **Nothing detects or handles a child caller**, and it is the client's duty. Disclosed in `/legal/privacy` §11 and `/legal/acceptable-use` §3. |
| DP-16 | Significant Data Fiduciary duties (DPO, DPIA, annual audit) | §10, Rule 12 | **NOT ENGAGED** | SDF status arises only on Government notification. None. Must be re-checked if the Government notifies a class covering voice/AI processors. Add to the OPERATIONS quarterly re-verify list. |
| DP-17 | Cross-border transfer: permitted except to notified countries; observe conditions | §16, Rule 15, **Rule 13(4)** | **NOT ENGAGED YET — this row said MET, and "met" was the wrong word for a section that is not in force** | §16 sits in sections 3–17 and **commences 13 May 2027**. No restricted-country list is notified, which is an ABSENCE OF NOTIFICATION and not a permission you can cite; the operative transfer test today is SPDI rule 7 (§3.3, S-5). **Rule 15** affirms permission and hooks only making data available to a foreign State or a State-controlled entity — nothing imposed on us. **Rule 13(4)** — the real localisation power over a Significant Data Fiduciary, reaching specified categories *and the traffic data pertaining to their flow* — is dormant on three unmet conditions (no SDF notification of us, no class covering voice-AI processors, no category specified) and is what DP-16's quarterly re-check actually arms. The obligation that bites today is **disclosure**, and that is F-1. Corrected in `/legal/dpa` clause 9 and `/legal/privacy` §8 on 22 Aug 2026 — both previously stated the §16 permission with no commencement date. |

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
| S-5 | **Transfer of SPDI outside India (rule 7): comparable protection at the destination, PLUS consent or necessity for performance of a contract** | **MET on the necessity leg; UNEVIDENCED on the protection leg** | This is the transfer test that is ACTUALLY IN FORCE, and the tree cited DPDP §16 instead — a section that commences 13 May 2027 (DP-17). Necessity is straightforward: the service IS the calls, and the calls run on these suppliers. Comparable protection is a judgement per vendor against its own published terms, and **F-10 records that no sub-processor agreement has been signed**, so the leg has no evidence behind it beyond those terms. What closes it: F-10, and counsel confirming the judgement is one we may make ourselves. Stated to clients in `/legal/dpa` clause 9 since 22 Aug 2026. |
| S-6 | **Is a call recording "biometric information"? The 2011 definition of biometrics includes VOICE PATTERNS** | **UNDECIDED, AND LIVE UNTIL 13 MAY 2027 — the single most consequential open question on this page** | If YES, every call recording is SPDI: S-4's consent duty and S-5's transfer test bind the whole product, including the voice platform's own copy of the recording in the **United States** (F-12). If NO, the position is what the published documents already describe. **No Indian court or regulator has decided it**, and the definition reads as though drafted for authentication rather than for a call recording. DPDP abolishes the sensitive tier on 13 May 2027 — i.e. the question expires exactly after the window in which client #1 goes live. **Nothing in this tree may answer it.** What we do instead is right under either answer: treat call audio as though it may be SPDI, name every place it goes, and ask counsel a yes/no — OPERATIONS §2 **gate 37** (the advocate gate). Asked of clients in `/legal/dpa` clause 9 and pointed at from `/legal/privacy` §8. |
| S-7 | **CERT-In 2022 directions (s.70B, IT Act): report a notified cyber incident within 6 hours; enable ICT-system logs and keep them for a rolling 180 days *within Indian jurisdiction*** | **PARTIAL — procedure exists; the 6-hour clock and the log-place are the gaps, and scope is an advocate question** | This is live law TODAY, under s.70B of the IT Act (not the DPDP staging), and the playbook §12.1 names it as binding "if in scope … do not invent 'we're too small'". Two operative facts, both from the direction itself (No. 20(3)/2022-CERT-In, 28 April 2022): **(a) 6-hour reporting** — a notified cyber incident must be reported to CERT-In within 6 hours of noticing it; **(b) 180-day logs in India** — logs of all ICT systems enabled and "maintained within the Indian jurisdiction" for a rolling 180 days (source in §9, retrieved 2026-08-24). Where we stand: the breach *procedure* is built (see **DP-12**: `runbooks/data-breach-notification.md`, `apps/api/compliance/breach.py`), but it is written around the **DPDP Rule 7** clocks (Board without delay, ≤72h report); **CERT-In's 6-hour clock to a DIFFERENT authority is not in that runbook** and must be added, and the runbook's outstanding "establish the Board's reporting channel" lookup has a CERT-In sibling — the CERT-In reporting channel — that belongs beside it. The **180-day log leg** is now covered on days by the 365-day application-log period stated in OPERATIONS §4.1 (DP-10), but the **Indian-jurisdiction condition on the log store is not satisfied by anything automatic** — it becomes real only when a host and log sink are provisioned, and if CERT-In is in scope the sink must sit in India. **Whether a solo India-only SaaS is even "in scope"** (as a "service provider" / "body corporate" under the direction) is itself the advocate question — playbook §20 routes it to the telecom/IT advocate; do not self-answer it either way. What closes it: (i) add the 6-hour CERT-In leg + its reporting channel to `runbooks/data-breach-notification.md`; (ii) counsel's scope determination; (iii) at provisioning, an India-resident log sink. |

### 3.4 Consumer Protection Act 2019 + E-Commerce Rules 2020

| # | Obligation | Status | Notes |
|---|---|---|---|
| C-1 | Display legal name, office address, website and customer-care + grievance-officer contact | **PARTIAL** | Now on `/legal/*` as placeholders. **The site footer carries none of it** — see FOLLOW-UP-1. |
| C-2 | Acknowledge a complaint in 48h, redress in one month | **MET as published, UNMET as process** | See DP-8. |
| C-3 | No misleading claims about the service | **CLOSED** | See F-1 — the claim was removed and `publicLanding.test.tsx` bans its return. |
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
- **Two realms, separated four independent ways** — and the vendor that used to do this is
  gone (D-177), so the separation is now built out of our own materials and each mechanism
  is auditable here rather than in someone's dashboard. `apps/api/authn/` is the only thing
  in this product that mints a credential. (1) The realm is INSIDE the stored session
  hash — `authn/sessions.token_fingerprint(token, realm)` domain-separates on it, so a
  client token looked up under the admin realm matches no row; cross-realm confusion is
  arithmetic, not a forgotten `WHERE`. (2) The `realm` column is in the `WHERE` clause
  anyway. (3) Two `__Host-` cookie names, one per realm
  (`authn/cookies.COOKIE_NAMES`) — an addressing convention, **not** the boundary, and
  AUTH-MIGRATION §3 says so plainly because both realms' browsers talk to one API host.
  (4) Per-realm `Origin` enforcement, because `admin.` and `app.` are different origins on
  the same registrable domain and `SameSite` therefore does not separate them
  (`core/middleware.CookieCsrfMiddleware`).
- **Admin MFA enforced server-side** in `apps/api/core/auth.py::verify_token`, from
  `auth_sessions.mfa_verified_at` — a column, not a vendor claim.
  `authn/service.MFA_REQUIRED_REALMS` is the frozen constant `{"admin"}` with no setting
  behind it, so the admin second factor is on in every deployment and cannot be switched
  off; `tests/authn_mfa_test.py` asserts the sign-in path and the verifier read the same
  set. The refusal is one code, `401 second_factor_required`. **The factor is a six-digit
  code emailed to the address on file and nothing else** — no authenticator app, no shared
  secret, no recovery codes (D-170; AUTH-MIGRATION §2.3 and §7 carry what that costs). It is
  minted and checked in `apps/api/authn/otp.py`, and what is STORED is an HMAC of the code
  under a key derived from `PLATFORM_KEK` — which is not in this database — rather than a
  bare digest: 900,000 precomputed hashes would otherwise turn one read of that table into
  every live code. The guess budget counts wrong ANSWERS, not requests: each challenge carries
its own `OTP_MAX_ATTEMPTS` ceiling **on the row**, so it survives a Redis flush and an
attacker who can reset the caller-keyed limiter still cannot spend more guesses against one
code. Ten-minute validity. Two independent rate limits is what NIST SP 800-63B's
requirement for a sub-64-bit authenticator looks like when it is taken seriously.
  Session lifetimes are enforced on the row, per realm: admin 30 min idle / 8 h absolute,
  client 12 h idle / 14 d absolute (`authn/sessions.REALM_TIMEOUTS`).
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
- **Model residency**: `scripts/check_model_residency.py` fails the build if the region is
  spelled anywhere but the single frozen `AZURE_LOCATION`, if any `Settings` field could
  carry a region or an endpoint, if an Azure endpoint is constructed anywhere but
  `azure_openai_base_url()`, or if that builder could emit a region at all.

  **⚠ THIS PARAGRAPH USED TO CLAIM THE OPPOSITE OF THE TRUTH AND THE CORRECTION MATTERS
  MORE HERE THAN ANYWHERE ELSE IN THIS TREE.** It said model residency was *"the one
  residency guarantee that is enforced rather than asserted"*. Under D-127 that was
  accurate: a Vertex URL carried `asia-south1` in the host **and** the path, so the guard
  read the region off the literal and proved where traffic went. Under D-410 it is
  **backwards**. `https://<resource>.openai.azure.com/openai/v1` names no region — the
  region is a property of the Azure RESOURCE — so what the build proves is narrower and
  must be stated narrowly: *there is no code path that can change where the traffic goes
  without editing one frozen constant.* Where it actually goes is **asserted by
  configuration and attested by a human** in the Azure portal (OPERATIONS §2 gates 20 and
  20c), filed in `docs/evidence/`.

  ⚠ **AND SINCE D-449 (22 Aug 2026) THE STATEMENT IS NOT AN INDIA STATEMENT AT ALL.** The
  region is `eastus2`. The client-facing India warranty is WITHDRAWN across `/legal/dpa`,
  `/legal/privacy`, `/legal/subprocessors` and the public landing page; the speech legs
  remain SARVAM, and the caller's transcript reaches a US model on every turn as
  it is spoken. ⚠ **This sentence used to end "the speech legs remain Sarvam and Indian" —
  see the 27 Aug 2026 correction immediately below: that was a claim about the VENDOR, and
  the vendor's own policy permits it to process outside India.** Read everything below as a claim about a NAMED REGION and an accurate
  sub-processor disclosure, never as localisation.

  ⚠ **AND ON 27 AUG 2026 THE SPEECH LEG STOPPED BEING AN INDIA CLAIM AS WELL.** Everything
  in this document that read *"the speech legs remain Sarvam and Indian"* was a claim about
  the VENDOR being Indian, written in places where a reader takes it as a claim about where
  the data is processed. Sarvam's own privacy policy says personal data *"may be transferred
  to and processed in countries outside India"*, naming US cloud infrastructure (AWS, GCP,
  Azure) and analytics providers and EU model and security vendors, under SCCs, adequacy
  decisions and DPAs; the *"Data Localization (Indian Users)"* carve-out storing voice
  biometric data in India reads as scoped to Content Studio, not Voice Agents / API traffic.
  **So the AUDIO may leave India on the speech leg, not only the transcript on the language
  leg.** A second finding lands on the training promise rather than on residency: **ToS
  s.17.5** permits Sarvam to use Inputs, Outputs and usage data to train its models (subject
  to its Privacy Policy, applicable law and, where required, a declinable consent, with some
  Offerings possibly restricted if declined), it does **not vary by tier**, and **s.6.2**
  makes a signed order form the only instrument that can displace it — **we hold none**, so
  the client-facing "no vendor trains on your data" sentence was NARROWED to our own conduct
  rather than softened (`/legal/dpa` cl.2, `/legal/privacy` §6, `/legal/terms` §§7-8,
  `/legal/subprocessors` §3.4 — new). VENDOR-PUBLISHED (Sarvam Privacy Policy "Cross-Border Data Transfers"; ToS v2.0 eff. 29 Jul 2026 ss.6.2/17.5 — read by the founder 27 Aug 2026 and relayed; `sarvam.ai` remains egress-blocked here).

  Two consequences a lawyer reading this should have in front of them. **(1)** The
  strongest residency statement this product can make about its LLM legs is an attestation
  about a US region, not a build artifact and not an India guarantee — so a client document
  must not describe it as machine-enforced and must not describe it as Indian. ⚠ **AND NOT
  AS UNREACHABLE BY CONFIGURATION EITHER (F-13, 22 Aug 2026):** `azure_openai_resource` is
  a console field, the region is a property of the resource, and this repository says so
  twice in its own code (`config.py:425`, `platform_config.py:418`). The list of four
  things the guard proves is a list about the SOURCE; gate 20 is the reading that covers
  the setting. **(2)** Gate
  20c is not a formality: Azure's DEFAULT deployment type is *Global*, which processes
  worldwide, and a Global deployment satisfies every automated check in this repository
  while making the region the DPA names unenforceable.
  The guard prints both caveats on every run, pass or fail, so this cannot silently drift
  back to the old claim.

**Not in place, and named in the documents rather than glossed:** no ISO 27001, no SOC 2,
no penetration test, no restore drill ever passed (`infra/backup/` "applied to nothing and
never run", D-50), no production deployment.

---

## 5. Findings — where we do NOT satisfy an obligation

These are ordered by how much damage they do — **except F-11, which is appended rather
than inserted so that every existing citation of F-1…F-10 still resolves.** By that
ordering rule it belonged at the top on the day it was found: it was the only finding about
a document that would be *handed to a client* naming vendors we do not use. Its copy half
is now closed; its mechanism half is not. **This list is worth more than the policy
pages.**

### F-1 — ~~The marketing page makes a data-residency claim the deployment blueprint contradicts.~~ **CLOSED as to the page; the HOSTING DECISION is still open.**

**The sentence is gone.** `apps/web/src/app/page.tsx` no longer carries it and
`apps/web/tests/publicLanding.test.tsx` fails if it returns — so the misrepresentation this
finding was about is closed, and C-3 with it. The 17 Aug audit found the same claim
surviving in `docs/BRD.md` and `docs/README.md`, where a salesperson would read it after
engineering had removed it from what a customer reads; both are now corrected too.

**The host WAS chosen — D-180, a Hostinger VPS in India — and that does not reopen the
claim.** This paragraph used to read "no host is chosen, so the claim could not be made
truthfully even if someone wanted to make it", which invited the reading that choosing one
would make it true. It would not: the host is one of at least five places tenant personal
data lives, and the two that matter most are unmoved — R2 offers no India-only
jurisdiction, and the voice platform runs the call itself on US infrastructure with our
BYOK posture foreclosing its India routing (F-12, D-415). **So the ban stands: nothing in
this repository may assert residency**, and the decision is a fact for the sub-processor
register rather than a differentiator for a card.

**22 Aug 2026 — the omission half.** Every ban above stops the page SAYING something
false; none stopped it implying it. The card headed "The AI runs on Indian endpoints",
inside a section headed "Your customers' data", reads to a prospect as "the call is
handled in India". One clause was added — the models are the Indian part, the platform
that carries the call runs it on US infrastructure today — and `publicLanding.test.tsx`
now pins that clause the same way it pins "checked, not proved by a build". This is the
consumer-law axis rather than the DPDP one: a residency claim on a marketing page is a
promise to a prospect. The competitor teardown is the reason to bother getting it right
rather than merely legal — Outpero admits offshore processing in a privacy policy nobody
reads (`docs/evidence/outpero-teardown-aug2026.md` §9b), and a differentiator that only
survives because the buyer did not check is not one.

The finding as recorded:

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
- `docs/SECURITY-COMPLIANCE.md` §4 CAUTION, **restated Aug 2026 from Bolna's own docs
  and materially worse than the line it replaced (F-12 below)**: the observation used to
  be "call recordings on S3 `us-east-1`", i.e. storage. Their documentation says the
  whole platform runs on US infrastructure by default, that India is an Enterprise
  purchase, and that connecting our own model keys — which is what BYOK IS — routes
  calls through US servers whatever else is configured. The residency posture "must be
  pinned in the Bolna contract" and has not been, and a contract alone would not fix it.
- Resend and Sentry are operated outside India. *(**Clerk** stood in this list until
  D-177 and no longer does: authentication, the credential and the session are ours and
  live in our Postgres — see §2.2. That is one sub-processor fewer outside India, and it
  is the single largest improvement to this finding since it was written.)*

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
   becomes true for the database — but *not* for R2, Resend, Sentry or Bolna, so the
   sentence still needs narrowing; **or**
2. Narrow the landing-page copy to the claim that is enforced. **D-410 narrowed what that
   sentence may say, and this is the one place it matters legally.** Until 19 Aug 2026 the
   claim was *"every model endpoint is pinned to an Indian region, and the build fails
   otherwise"* — true because `asia-south1` sat in the Vertex URL and the residency guard
   `scripts/check_model_residency.py` could read it from the AST. Azure's endpoint carries
   no region, so D-410's narrowing was *"no model endpoint can be built in this codebase
   except through one function that cannot emit a non-Indian region, and the build fails
   otherwise"*. ⚠ **THAT REPLACEMENT IS ITSELF WITHDRAWN AND MUST NOT BE SHIPPED**: D-449
   moved the declared posture to Azure OpenAI **East US 2**, so there is no Indian language
   endpoint for the sentence to point at and the India warranty is **withdrawn, not
   narrowed a third time**. What is still both true and machine-checked is a claim about
   SINGULARITY rather than about India: *"the language model runs on one account in one
   declared region; no code path in this codebase can point it anywhere else without a
   reviewed commit, and the build fails if the code and that declaration ever disagree"* —
   still checkable (D-432/D-444/D-453), still more than most competitors can say, and it
   asserts nothing about where the resource physically is. **The resource's region and its
   deployment type are attested by a human (OPERATIONS §2 gates 20 and 20c), not proved by
   the build**, and any public copy that implies otherwise is the misrepresentation this
   finding is about. Speech (Sarvam) and the first post-call extraction pass remain Indian
   SERVICES in the sense that the vendor is an Indian company — ⚠ and since 27 Aug 2026 that
   is the ONLY sense in which they may be described as such: the vendor's own policy permits
   processing outside India, so "Indian service" may not be written where a reader will take
   it for residency (see the correction in §4 above).

**⚠ AND THE NARROWED REPLACEMENT ON THE LANDING PAGE IS NOW WRONG TOO, IN TWO WAYS. Read
this before quoting anything above as closed.** `apps/web/src/app/page.tsx` (the residency
tile, ~line 546) currently reads:

> **"The AI runs on Indian endpoints"** — "Speech, language and the reading of your
> transcripts are Indian services. **The one model endpoint that is not is pinned to
> Mumbai by a check that fails our build if a line of code ever points somewhere else.**"

That sentence was written for Vertex on 17 Aug and D-410 falsified both halves of it two
days later, and D-449 has since falsified it a second time. **(1) The region is wrong,
twice over**: `asia-south1` (Mumbai) went with Vertex; the deployment was Azure OpenAI in
**South India** and is now **East US 2** (D-449), so the sentence is not repairable by
swapping a city name — there is no Indian language endpoint to point at. **(2) It makes the machine-enforced claim
this document has withdrawn**, on the marketing page — the exact surface F-1 exists about,
where it is a CPA 2019 representation rather than an internal note. The build cannot fail
on a region it cannot see in the endpoint. It has also lost its arithmetic: with D-410 the
LANGUAGE leg is Microsoft's on BOTH surfaces, so "the one model endpoint that is not
[Indian]" now carries every word the caller speaks rather than a redacted dashboard query.

**What the page may truthfully say** — narrower again, and after D-449 it may not claim
India for the language leg at all, nor (after the 27 Aug 2026 correction in §4) India
PROCESSING for the speech leg: speech (Sarvam) and the first post-call extraction pass run
on an Indian company whose own policy permits it to process outside India, and the landing
page now says both halves in one sentence; the language model runs on a Microsoft Azure OpenAI account
**configured for East US 2**, no code path can send it anywhere else without editing one
frozen constant, **and the account's region and deployment type are confirmed by a person
against the provider's console and filed as evidence** — checked, not proved by a build.
**Anything of the form "your callers' words stay in India" is now false and must not
appear.** `apps/web/tests/publicLanding.test.tsx:87`
asserts the current wording verbatim, so the test moves in the same change; that is the
guard working, not an obstacle.

I did not edit `page.tsx` — it is outside my scope. **FOLLOW-UP-2 is now CLOSED (verified by
reading the file 24 Aug 2026), not pending.** The residency tile in
`apps/web/src/app/page.tsx` no longer carries the old Vertex/Mumbai sentence; it now reads
that speech and the first reading of the transcript are Indian services *"on every call"*
— ⚠ **qualified on 27 Aug 2026**: the card now says in the same sentence that this names an
Indian COMPANY and not a place, because that vendor's published privacy policy permits it to
process personal data outside India (US cloud infrastructure; EU model and security
vendors); the pinned substring is unchanged and the qualification follows it —
that the language model *"is not: it runs on a Microsoft Azure OpenAI account in the United
States, in the East US 2 region"*, that until 22 August 2026 the account was in South India
and the card said so, that the only thing the code still does is *"pin the model to that one
region … the account's own region is confirmed by a person against Microsoft's console and
filed: checked, not proved by a build"*, and that the platform carrying the call *"runs it on
US infrastructure today"*. That is exactly the narrowed, non-India, non-build-proved claim
this finding prescribed above. **The guard moved with it and now enforces the new shape in
both directions**: `apps/web/tests/publicLanding.test.tsx` asserts the text still contains
`"Speech and the first reading of your transcript are Indian"` AND
`"Microsoft Azure OpenAI account in the United States"`, and bans any India-residency claim
by shape (`expect(text).not.toMatch(/data residency|data sovereignty|sovereign/i)` and the
banned-phrase list including the old `The AI runs on Indian endpoints`). So the
misrepresentation this follow-up was about cannot return without a red test. `/legal/privacy`
§8 already carries a callout saying any such claim elsewhere is an intention and that §8
overrides it, and `tests/legal.test.tsx` bans the claim from ever appearing in a legal
document.

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
the promised age, a lead kept at 1.5×).

**The conflict is now RESOLVED as to which numbers are authoritative — conservatively, and
without inventing a fourth set.** The **`scripts/seed.DEFAULT_RETENTION_POLICIES` figures
(90 / 365 / 1095) are the enforced source of truth**, because they are the numbers the
nightly sweep actually applies (`apps/workers/retention.py` reads the seeded
`retention_policies` rows) AND the numbers `/legal/privacy` §9 publishes to callers — the
enforced-and-published pair is the only one a data principal or a regulator can hold us to.

**⚠ THE CITATION THAT SAT HERE WAS FALSE, AND IS WITHDRAWN (27 Aug 2026).** This sentence
justified the 90-day floor as "consistent with the playbook's '90-day minimum recording
retention' (`docs/legal/LEGAL-OPS-PLAYBOOK.md` §12.3 / stop-list)". **The playbook
contains no such sentence.** `grep -n "90" docs/legal/LEGAL-OPS-PLAYBOOK.md` returns three
lines and all three are the ₹5,900 DLT registration fee; §12.3 is a list of documents to
ship and says nothing about a retention period. A repo-internal number was cited to a
source that does not carry it, and from here it propagated into three client- and
caller-facing surfaces as a LEGAL REQUIREMENT — the generated caller notice ("kept longer
where the law requires it"), the DPDP erasure certificate ("the 90-day period Indian
telecom rules require call recordings to be retained for") and `/legal/privacy` ("the
90-day telecom retention floor"). All three are reworded, and the floor is now described
everywhere as what `docs/SECURITY-COMPLIANCE.md` §4 actually supports: **a conservative
Calevate platform floor whose statutory basis is with counsel.** That section records why
— TRAI's 90-day figure in the TCCCPR framework is the opt-out cooling period before a
sender may seek fresh consent, and the two-year commercial-records archive is Unified
Licence clause 39.20, which binds LICENSEES and not a telemarketer — and it records the
cost of getting it wrong in this direction: retaining personal data on a legal basis that
does not exist is itself the DPDP §8(7) storage-limitation breach. The FLOOR is unchanged
(90 / 365 / 1095 still enforced and still published); only the asserted authority for it
is. This is hard rule 11's own worked example: a value already in this repo is not
evidence of itself. **`docs/SECURITY-COMPLIANCE.md` §4's
older 180 / 730 numbers are STALE and are superseded** — they are a design note that the
seed and the public notice both moved past, and nothing enforces or publishes them. I have
not edited SEC-COMP §4 here (it is the founder's + counsel's to reconcile in one release,
per the row below and OPERATIONS-tracked ROADMAP §6); this finding is corrected only to
record which set of numbers is real, so a reader does not treat the three-way disagreement
as unsettled. **The founder must still fold SEC-COMP §4 into line** — SEC-COMP §4,
`DEFAULT_RETENTION_POLICIES`, and `/legal/privacy` §9 should read one set of numbers, and
the change is a one-line correction to SEC-COMP §4 (down to 90 / 365 / 1095), not a code
change, with a ROADMAP §6 entry.

**Caveat that survives the resolution:** the seed figures are *defaults*, and the FINAL
retention periods for any given client are a **per-tenant DPA commitment to confirm with
counsel** (`docs/legal/LEGAL-OPS-PLAYBOOK.md` §20 routes retention/DPA terms to the
advocate). A tenant may negotiate a different row; existing tenants' agreed rows are their
own decision. So "90 / 365 / 1095 is authoritative" means *authoritative as the enforced and
published default*, not *legally final for every tenant forever*.

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

~~**What closes it:** add the backup clause to `ERASURE_LIMITATIONS`~~ — **done.** The
instruction is struck rather than deleted so the next reader can see that the thing asked
for is the thing that shipped: `apps/api/compliance/deletion.py` carries
`BACKUP_WINDOW_DAYS`, the ninth `ERASURE_LIMITATIONS` entry and its index-aligned
`backup` exception. FOLLOW-UP-3 is discharged.

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
Resend, Sentry, Cloudflare or the hosting provider. *(Clerk was on this list until D-177
and is not a sub-processor any more — one contract fewer to obtain, and the only entry on
it that closed by deletion rather than by signature.)* **D-410 adds a sub-processor that
holds the most sensitive input this system has: Microsoft (Azure OpenAI — South India at
D-410, **East US 2 since D-449**) now carries BOTH LLM surfaces, so the in-call leg means
raw caller speech reaches it in real time, and since D-449 it does so ACROSS THE BORDER.
That makes gate 37(a) — whether a call recording is SPDI biometric data — a question about
the live conversation rather than only the archive, and SPDI rule 7's comparable-protection
leg is unevidenced while zero sub-processor DPAs are signed.** Microsoft publishes a standard DPA and the Azure OpenAI service terms carry the
data-handling commitments this depends on; neither has been executed, and until one is, the
strongest statement available about that leg is the region it is configured for. Rule 6(f)
requires the contract to impose equivalent safeguards, and today we would be promising a
client something we have not obtained upstream. **What closes it:** sign the vendors' standard
DPAs — Microsoft, Google (for Sheets lead delivery, D-23), Resend, Sentry, Cloudflare and the
hosting provider all publish one — and record the Bolna residency term in the contract before
flipping `ENGINE=bolna`.

### F-11 — ~~The published sub-processor list and cookie table named vendors we do not use, and repeated a residency claim §4 had withdrawn.~~ **CLOSED on the copy, 20 Aug 2026. The MECHANISM that let it happen is still open.**

**The finding as recorded.** Everything else in this document described the sub-processors
correctly; the documents a client would actually be handed did not, and those are the ones
that carry legal weight. `apps/web/src/lib/legal/subprocessors.ts` (served at
`/legal/subprocessors`, and the list the DPA points at) carried a row for **"Google Cloud —
Vertex AI"** located *"India — Mumbai (asia-south1) only"*; inside it, the sentence *"The
region is a frozen constant in the code and a build check fails the release if any model
endpoint names a global or non-Indian host"* — **§4's withdrawn claim, verbatim, in the one
place it is a representation to a client rather than an internal note**; **no row at all
for Microsoft**, the sub-processor that now receives live caller speech on the in-call leg;
a **Sarvam** row calling it *"the language model that runs the conversation"*; and a
**Clerk** row, *"United States"*, *"Core"*. `apps/web/src/lib/legal/cookies.ts` attributed
all three of its cookies to *"Clerk, our authentication provider"*, described a
`__client_uat_…` suffix derived from a publishable key, and stated client sessions "refresh
for up to 7 days".

**Closed by the parallel `apps/web` session on 20 Aug 2026, and verified by reading the
files rather than taking the report.** `subprocessors.ts` carried, as of that date, **"Microsoft — Azure
OpenAI"**, "India — South India, **by configuration**", with the caution that the account's
region and its deployment type are read by a human and filed as evidence — ⚠ **the region
half of that entry is superseded by D-449 and now reads East US 2; the India warranty is
withdrawn, not restated**; the Vertex row is
gone and its history is stated in place; there is no Clerk row anywhere in
`apps/web/src/lib/legal/`. `cookies.ts` names the two real cookies —
`__Host-calevate_client_session` and `__Host-calevate_admin_session` — attributes them to
us, and states the real lifetimes (`authn/sessions.REALM_TIMEOUTS`: client 12 h idle /
14 d absolute, admin 30 min / 8 h). `privacy.ts` and `dpa.ts` say the region is *"attested
in evidence, not proved by a build check"*. **If that change is abandoned before it lands,
this finding returns exactly as written above.**

**⚠ AND THE ONE TEST OVER THIS SURFACE CURRENTLY REQUIRES THE FALSE DISCLOSURE.**
`apps/web/tests/legal.test.tsx` ("keeps the sub-processor register as the only copy of the
vendor list") loops over `["Bolna", "Sarvam", "Clerk", "Cloudflare", "Resend", "Razorpay"]`
and asserts the register **contains** each one. With Clerk correctly removed from
`subprocessors.ts`, that assertion fails — so the guard is red on the fix rather than on
the defect, which is the worst orientation a guard can have. The same list contains **no
Microsoft entry**, so nothing asserts that the sub-processor receiving raw caller speech is
disclosed at all. Both halves move in the same change: drop `Clerk`, add `Microsoft`, and
see FOLLOW-UP-8 for binding the list to a constant instead of a literal.

**The mechanism half is now CLOSED (27 Aug 2026), and this paragraph is retired.** It said
the published sub-processor list was "derived from **no constant**" and asked for "a single
exported list of sub-processor identities that both the page and a test read". That list
exists: `SUBPROCESSOR_NAMES` (`apps/web/src/lib/legal/subprocessors.ts:392`) is derived
from the same rows the page renders, and `apps/web/tests/legal.test.tsx` imports it and
loops over it — asserting the register exports a non-empty inventory, that every name in it
reaches the rendered document, and by name that the US language-model vendor is on it. So
adding or removing a vendor in the tree now fails a test that names the document it did not
reach, which is exactly what was asked for. Nothing outstanding; no external dependency.

### F-12 — The published documents placed the voice platform in India. Bolna's own documentation says the United States. **CLOSED on the client-facing copy, 20 Aug 2026; the ENGINE decision it reopens is not ours to close.**

**What was wrong.** `/legal/subprocessors` gave the voice platform's Location as *"India for
the platform"* and confined the United States to a footnote about recording storage;
`/legal/privacy` §8 and the DPA §9 said the same, narrower thing (*"the voice platform's own
copies of recordings have been observed outside India"*). Every one of those sentences was
written from an OBSERVATION — recording URLs on `s3.us-east-1` — rather than from the
vendor's documentation, which nobody in this repository had been able to reach.

**What their documentation says**, now mirrored at `bolna-findings/mirror/pages/`:

- *"By default, all Bolna AI services operate in United States (US)-hosted infrastructure,
  but customers on enterprise plans can choose to have their data processed exclusively in
  India."* — `enterprise/data-residency.md`
- *"By default, Bolna processes calls on infrastructure in the US (AWS us-east-1)."* —
  `concepts/security.md`
- *"Data residency is an Enterprise feature."* — `enterprise/data-residency.md`
- And the one that decides it: *"If you connect your own API keys for any provider
  (transcriber, synthesizer, or LLM), calls will automatically route through US servers
  regardless of other configuration settings."* — `enterprise/indian-server-configuration.md`

**Why the last quote is the finding rather than a footnote.** This product is BYOK on all
three legs by design (D-31/D-36/D-410). So the residency option is not something we have
merely failed to buy — it is something our architecture currently forecloses. A DPA that
told a client their calls are handled in India would be a misstatement in a contract, and
it would stay one after any amount of procurement.

**What was fixed, in the same change.** The sub-processor register's Location cell now
reads United States and its §3.1 caution states both halves (the default and the BYOK
exclusion); `/legal/privacy` §8 widens from recordings to the live audio, the transcript
and the platform's copy; the DPA §9 transfer clause says the same in the operative text
rather than in a notice. `tests/legal.test.tsx::does not place the voice platform in India,
and says where it actually is` asserts it on the ROW — the sentence a buyer's counsel reads
— so the old copy cannot come back. `docs/SECURITY-COMPLIANCE.md` §4's cross-border row
carries the quotes and drops the sentence *"Everything the caller says is processed in
India"*, which was false at the orchestration layer.

**What is NOT fixed and is not ours.** Whether to keep BYOK and accept US orchestration,
or move to Bolna's own provider integrations (losing BYOK's cost control, its named-model
transparency and the Azure region pinning D-410 exists for) and buy the Enterprise
residency, is an engine-level decision with a commercial half — OPERATIONS §2 gates 9 and
12. `docs/evidence/bolna-compliance-residency.md` §5 lays out the fork and what each arm
costs. **Nothing in the client-facing copy waits on it**: the documents now describe what
is true today.

**What survived of the residency story on 20 Aug 2026, and what D-449 then withdrew:** the
MODEL legs were Indian — Sarvam sovereign by vendor, Azure OpenAI region-pinned to South
India — so the inference did not leave the country while the ORCHESTRATION did. **Since
D-449 only the SPEECH legs were Indian — and since 27 Aug 2026 not even those, because that
was a fact about the VENDOR and its own policy permits processing outside India.** The
language model is `eastus2`, so the caller's transcript crosses the border on every turn,
and the audio may cross it too. §4's model-residency paragraph is re-aimed,
not deleted: the gates survive, the guarantee does not.

### F-13 — The DPA warranted that no setting could move the model region. A console field decides it. **CLOSED on the copy, 22 Aug 2026. The mechanism gap is real and is owned by a gate, not by a build.**

**What was wrong, and it was an express warranty rather than a marketing sentence.**
`/legal/dpa` clause 9 said *"No setting, console control or environment variable can move
it; only a reviewed commit can"*, with `/legal/privacy` §8 (*"no setting, console control
or environment variable can move the model to a third country"*) and
`/legal/subprocessors` §3.2 (*"no change to our software or our settings can move the
language leg to a third country"*) saying it in their own words. Three surfaces, one
claim, and this repository contradicts it in two places of its own:

- `packages/shared/src/calevate_shared/config.py:425` — *"Azure hides the region inside
  the resource rather than in the URL, which makes `azure_openai_resource` **the value
  that decides residency in practice** … note that **no code here can check it**"*;
- `apps/api/core/platform_config.py:418` — the field's own `AppliesRule` reason: *"a
  resource in the wrong region is **a residency change no code here can detect**"*. It is
  not env-only and not name-sealed as a secret, so `managed_fields()` offers it, and
  `apps/web/src/app/admin/ops/ConfigPanel.tsx` renders it under a group literally titled
  *Language model*. It is a text box.

**Why the guard is not the answer and never was.** `scripts/check_model_residency.py`
proves four things about the SOURCE — one spelling of `AZURE_LOCATION`, no `Settings`
name carrying `region`/`location`/`residency`/`datacenter`/`posture`, no endpoint
constructible outside `azure_openai_base_url()`, and a builder that cannot emit another
region. All four remain true while an operator points the resource at
`something-westeurope`. That is exactly the hole **OPERATIONS §2 gate 20** exists to
cover — *"find the resource named in `azure_openai_resource`, and read its Location
field"* — and the documents were describing the guard as if it covered the gate's half
too.

**Closed by narrowing the sentence, not by deleting it.** All three documents now warrant
the source-code mechanism, name the resource setting as the place the region is really
decided, and say that a person confirms it. The DPA adds the commitment that follows from
that: moving to a resource in another region is a change of processing location notified
under clause 5, not a settings adjustment. `tests/legal.test.tsx` bans the absolute shape
in every document so it cannot grow back, and `residencyWarrantyMirror.test.ts`'s four
pinned substrings all survive unchanged.

**What is NOT closed, and it is not copy.** Nothing re-triggers gate 20 when
`azure_openai_resource` changes: the attestation is a dated reading of one resource, and
editing the field silently invalidates it. **What would close it:** the console write path
for that one field refusing unless a fresh attestation names the new resource — the same
shape `check_model_lifecycle.py` already uses to consume
`docs/evidence/azure-deployment-attestation.json`. Owner: ours (guards/config lane, not
this one). No external dependency.

### F-14 — Two published documents promised a recording control the product does not have. **CLOSED on the copy, 22 Aug 2026; the mechanism is pilot gate 3.**

`/legal/privacy` §4.1 told callers that *"if a caller declines recording during the call,
recording stops, the call continues, and the refusal is written to an immutable consent
ledger"*, and `/legal/acceptable-use` §2.6 told clients the same. Neither is built:
`Call.consent_recording` is on `scripts/check_wiring.py`'s known-unwired list (*"the
engine reports no per-call recording consent yet (pilot gate 3)"*), nothing writes a
`recording`-purpose `consent_ledger` row, and `apps/voice-runtime/tool_routes.py` has
exactly one in-call tool (opt-out) — so no agent can stop a recording mid-call.
`docs/SECURITY-COMPLIANCE.md` §2.2 contained both halves of the contradiction three
sentences apart (*"nothing in this codebase can [switch recording off]"* directly above
*"Caller decline ⇒ recording off"*); it now marks the second as specification.

Privacy §4.1 also implied recording was a client switch. It is not — the switch is the
recording NOTICE (`agents.recording_notice_enabled`), and the landing page's *"Every call
is recorded and kept"* was the accurate surface of the three, so it is unchanged. What a
caller has instead is erasure through the client, which fixes a destruction date and
produces a certificate, and the notice now says that.

**What closes the mechanism:** pilot gate 3. Not ours — it needs the engine to report a
per-call recording decision, or a second in-call tool once gate 8 verifies the vendor's
custom-function behaviour.

### F-15 — The model picker shows a per-minute rupee figure and calls it what the client pays. Nothing bills that leg. **The COPY is closed, 22 Aug 2026; the SCREEN is another lane's and is still wrong.**

D-454 gave clients a per-tenant and per-agent model choice with a price against each
option, and it landed after the legal sweep, so no document mentioned it. Two of the three
consequences were cheap: the DPA's clause 2 instruction list now names the model choice,
and clause 9 plus `/legal/subprocessors` §3.3 said that the choice moved no vendor, no
resource and no region (every member of `AZURE_OPENAI_MODELS` being served from the same
`azure_openai_resource`). §3.3 previously said the opposite — *"changing which model an
agent uses is a data-residency change and not a settings tweak"* — which was true only
while nobody outside this company could change it.

⚠ **AND THE ROUND TRIP IS COMPLETE: THAT REASSURANCE IS NOW WITHDRAWN IN ITS TURN, AND
§3.3's ORIGINAL SENTENCE WAS RIGHT ALL ALONG FOR A REASON NOBODY HAD YET.** The offered set
spans three providers — Azure OpenAI in East US 2, OpenAI direct on its `us` residency host,
and Google's Gemini Developer API, which has no region to request at all. A client picking a
model is therefore picking which provider handles the language leg and where it runs, which
IS a sub-processor change. Both `/legal/dpa` and `/legal/subprocessors` now say the
single-vendor, single-region promise about that leg is **WITHDRAWN, not narrowed** — the
same move D-449 made about India, one level down and for the same reason. Worth recording as
a pattern rather than an incident: this clause has now been rewritten three times in one
direction each time, and every rewrite that tried to KEEP a promise by qualifying it was the
one that had to be undone.

**The third is a money claim and it is not consistent with the contract.**
`inr_per_minute_five_min` is derived from `AZURE_LIST_PRICE_USD_PER_MTOK` — Calevate's own
list-price COST of the language leg — and `apps/api/billing/rates.py` states in capitals
that **nothing is billing the in-call leg and that this is permanent**: the leg is BYOK, so
the engine pays nothing and reports no tokens. A client's charge is their plan's overage
rate (`billing/service.priced_overage`) or `self_serve_inr_per_min`
(`rates.prepaid_billed_inr`), and neither moves with the model. The screens nevertheless
say *"what you pay now"* beside each rate
(`apps/web/src/components/llmModelPicker.tsx`), *"It costs ₹X a minute"* (both the
organisation screen and the per-agent one) and *"this is a
decision about your bill as much as about your agents"*
(`apps/web/src/app/c/[slug]/settings/models/page.tsx`,
`apps/web/src/app/c/[slug]/agents/AgentModel.tsx`). FOLLOW-UP-9 carries the lines.

`/legal/terms` §6.1 now carries the honest statement — the figure is our cost, it appears
on no invoice line and no credit deduction, switching models changes nothing you are
charged, and passing it through would be a change to the commercial terms. **That is the
contract catching up with the screen; it is not a fix for the screen**, which tells an
owner they are being charged something they are not. Owner: the agents/billing UI lane.

**One adjacent correction made in the same pass, because D-454 widened it.** DPA clause 3
said only that operator access to a client account is read-only and "cannot make
changes" — true of the impersonation grant it describes, and read by an ordinary client
as "Calevate staff cannot change anything on my account". The admin realm writes plenty:
plans, credits, spend caps, agents, and now **which model a tenant's agents run**
(`POST /v1/admin/organizations/{org_id}/llm-defaults`, `agents/llm_routes.py`). Clause 3
now carries a fourth bullet saying so, and saying that each such change is audited —
which it is: both doors of that route call `write_audit` with the value and whether it
moved.

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
- No claim that the voice platform runs the call in India — it runs it in the United
  States, and the documents say so (F-12). (`does not place the voice platform in
  India, and says where it actually is`)
- **No claim that no setting can move the model region** (F-13). The build's warranty is
  about the SOURCE; which Azure resource the endpoint names is a console field, and the
  region belongs to the resource. (`does not claim a setting cannot move the model
  region`)
- **No claim that a caller can stop a recording mid-call** (F-14), and no claim that
  recording is a switch anyone holds. Every call an agent handles is recorded; the
  toggles are about what is ANNOUNCED. (`claims no recording control the product does
  not have`)
- **No claim that choosing a model changes what a client pays** (F-15). The figure the
  picker shows is our own cost of the language leg; the charge is the plan's rate.
  (`does not price the model choice as a client charge`)

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

`{{PRIMARY_HOSTING_LOCATION}}` was not an administrative blank: filling it in **was** the F-1
decision, and D-180 took it. **It is filled as of 22 Aug 2026** — it carries a `value` in
`placeholders.ts` and the renderer substitutes it, so it is no longer one of the eighteen blanks
above; the entry stays because the data centre is named in the change that provisions one.
The mechanism is the durable part: a decided fact now reaches every document from one place, and
`assertLegalSetPublishable` refuses to render the set if `PENDING_LEGAL_REVIEW` is ever removed
while any blank remains. Between D-180 and that change the token rendered raw on `/legal/dpa`
clause 9 and `/legal/privacy` §8 — a decision taken and a document that never heard about it.

---

## 8. Additions to the OPERATIONS §7 compliance calendar

- **14 November 2026** — DPDP Consent Manager provisions commence. Re-check whether any
  Calevate flow needs a registered Consent Manager. (Assessment today: no — we collect no
  consent in our own right.)
- **13 May 2027** — **sections 3–17 of the DPDP Act commence, §16 among them.** Until that date §16
  neither permits nor restricts a transfer: it forecloses a restriction nobody has made. Two
  consequences fall on the same day — the SPDI transfer test (S-5) stops applying, and the
  sensitive tier that makes S-6 a live question disappears with it.
- **13 May 2027** — DPDP substantive obligations commence; IT Act s.43A and the SPDI Rules
  2011 fall away. Until then §3.3 is the operative regime and the privacy notice must keep
  citing it.
- **~~16 October 2026 — the Gemini 2.5 retirement (BRD R-04)~~ REMOVED 19 Aug 2026 (D-410).**
  Both LLM surfaces moved to Azure OpenAI (South India then, `eastus2` since D-449); the
  model, the date-carrying constant
  and the test that turned CI red thirty days out are all deleted, and R-04 closes. **No
  vendor-imposed model deadline is currently on this calendar** — if one is announced for
  `AZURE_OPENAI_DEFAULT_MODEL`, it comes back here and into a date-carrying constant, which
  is the mechanism that worked.
- **Quarterly** — re-check: whether the TCCCPR Third Amendment has been notified (T-10);
  whether a restricted-country list has been notified under DPDP §16 (DP-17); **whether MeitY's
  January 2026 consultation on pulling the cross-border provisions forward and compressing the SDF
  deadline has been notified** (reported, moderate confidence; the advocate gate, OPERATIONS §2 gate 37); whether any SDF class
  notification could reach us — which is what would arm **Rule 13(4)**'s localisation power over
  specified categories and their traffic data (DP-16); whether GST turnover has crossed the ₹5 crore
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

**CERT-In 2022 directions (s.70B, IT Act) — S-7**
- CERT-In, *Directions under sub-section (6) of section 70B of the IT Act 2000, No. 20(3)/2022-CERT-In* (the primary text, Government of India) — https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf (**24 Aug 2026**) — 6-hour incident reporting; logs of all ICT systems enabled and maintained **within Indian jurisdiction** for a rolling **180 days**; in force ~end June 2022 (60 days after 28 Apr 2022 issue)
- Trilegal, *2022 CERT-In Directions on Reporting Cyber Incidents* — https://trilegal.com/wp-content/uploads/2022/05/2022-CERT-In-Directions-on-Reporting-Cyber-Incidents-1.pdf (24 Aug 2026) — top-tier law-firm summary confirming the 6-hour window, the 180-day-in-India log retention, and s.70B(7) penalty exposure

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

**Voice-platform residency and compliance (F-12) — first-party vendor documentation**

Mirrored locally at `bolna-findings/mirror/pages/`, read 20 Aug 2026. These are the vendor's
own pages, not third-party reporting, and every residency sentence in the client documents
now traces to one of them.

- `enterprise/data-residency.md` — "By default, all Bolna AI services operate in United States (US)-hosted infrastructure"; "Data residency is an Enterprise feature"; what India residency covers when bought (storage AND processing)
- `enterprise/indian-server-configuration.md` — the conditions for Indian-server routing: Plivo telephony, listed transcriber/synthesizer, Azure OpenAI, and **no customer-supplied provider keys**
- `concepts/security.md` — US default (`us-east-1`) and `ap-south-1` when residency is on; TLS 1.2+; no webhook HMAC; the three webhook egress addresses; VAPT A+ on request; GDPR named and DPDP not
- `compliance-application/introduction.md` and `how-to-submit-guide.md` — the account-level compliance application: CIN certificate, GST number and certificate, 12–24h review
- `guides/inbound/obtaining-regulated-phone-numbers.md` — 140-series via Vobiz (TATA DLT portal, PE registration ₹5,900, LOA), 160-series via Plivo (RBI/SEBI certificate, PE/TM IDs, URN, header and template registration)
- `api-reference/violations/{overview,list,submit}.md` — the Violations API and the fields it carries

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
8. **S-6 — is a call recording biometric information?** Yes or no. The 2011 definition of
   biometrics includes voice patterns; nobody has decided whether an ordinary business call
   recording falls in it; and it governs until 13 May 2027, which is the whole window in which
   this product goes live. If yes, SPDI's consent and transfer duties bind every leg including a
   voice platform in the United States. This one is ahead of most of the list above and it is
   OPERATIONS §2 gate 37(a). Gate 38(b) is its companion: does the phased commencement leave any
   gap in the lawful basis for transfer before May 2027?
9. **Every citation in §9** against the gazette. Several were retrieved as secondary
   summaries because the primary sources are unreachable from this environment. Add the DPDP
   Rules' notification date to that check: this document says 14 Nov 2025 and a later synthesis
   says 13 Nov, and neither lane could reach the gazette to settle one day. **A third search on
   22 Aug 2026 found only 13 Nov 2025** — dpdpa.com's rule-by-rule reproduction and a Wikipedia
   article on the Rules both give that date, and both put Phase I (Rules 1, 2 and 17–21) in force
   from it. That is now two secondary sources against one and it is still not the gazette, so the
   published copy is unchanged and the question stays here. `/legal/privacy` §12.1 is the client-
   facing sentence carrying 14 Nov; **it is the one to correct if counsel says 13**, and nothing
   downstream turns on the day — the dates that matter (13 May 2027 for sections 3–17 and for the
   SPDI repeal) are consistent across every source read.

---

## 11. Required follow-ups outside this session's scope

| # | Action | Why it is not done here |
|---|---|---|
| FOLLOW-UP-1 | Add `/legal` links to the site footer in `apps/web/src/app/page.tsx` (its footer currently carries no links at all) and to the two realm shells. Also add legal-page links to the sign-up flow. **Nothing on the site links to `/legal` today, so the documents are unreachable except by typing the URL** — and a payment aggregator's reviewer will look for exactly those links. | `apps/web/src/app/page.tsx` and `apps/web/src/components/**` are outside this session's edit scope. |
| ~~FOLLOW-UP-2~~ | ~~Resolve F-1: narrow the landing-page copy for the language leg.~~ — **DONE, verified 24 Aug 2026.** `apps/web/src/app/page.tsx`'s residency tile now says speech and the first transcript reading are Indian while the language model runs on a *"Microsoft Azure OpenAI account in the United States, in the East US 2 region"*, confirmed by a person and *"checked, not proved by a build"*; `apps/web/tests/publicLanding.test.tsx` pins both halves and bans any India-residency claim by shape. | Was outside this session's edit scope; closed by the `apps/web` lane. |
| FOLLOW-UP-3 | Add the 35-day backup clause to `ERASURE_LIMITATIONS` / `ERASURE_EXCEPTIONS` in `apps/api/compliance/deletion.py`, so the certificate and `/legal/privacy` §9 agree. | `apps/api` is outside this session's edit scope. |
| ~~FOLLOW-UP-4~~ | ~~F-2 and F-3: retention categories for the engine-payload archive and for KB content~~ — **DONE (D-179)**: migration `c4d1f7b83e26`, two sweep arms, and the erasure's knowledge-base search. | Was outside the audit session's edit scope; closed in the next one. |
| ~~FOLLOW-UP-7~~ | ~~F-11: correct `apps/web/src/lib/legal/{subprocessors,cookies}.ts` for D-410 and D-177.~~ — **DONE 20 Aug 2026** by the parallel `apps/web` session, verified by reading the files. What remains is F-11's other half. |
| FOLLOW-UP-8 | **Bind the published sub-processor list to a constant.** One exported inventory of sub-processor identities that `apps/web/src/lib/legal/subprocessors.ts` renders and `tests/legal.test.tsx` asserts against, so a vendor added to or removed from this tree fails a test naming the legal document it did not reach. F-11's mechanism half: two vendor changes three days apart both survived in a client-facing document because nothing could see the divergence. | `apps/web/**` and `tests/legal.test.tsx` are outside this session's edit scope. **OURS, no external dependency.** |
| ~~FOLLOW-UP-6~~ **DONE 22 Aug 2026** — both callouts rewritten to say what the mechanisms do, and the two retention categories added to the `/legal/privacy` §9 table with the periods `scripts/seed.py` actually installs (90 / 365). The deliberate limit that remains — an erasure SEARCHES knowledge content and reports the count but never edits a client's own writing — is now stated as a reasoned limit rather than as a gap. | ~~**Two published callouts now UNDER-claim.** `/legal/privacy` §9 ("Two stores that no retention period reaches yet") and `/legal/dpa` §8 ("Two stores with no retention period yet") both state that the archived engine payload and knowledge content have no retention period, and privacy adds that the knowledge base "is not searched by an erasure request". D-179 made all three sentences false in the client's favour: `engine_payload` and `kb` are retention categories now, and the erasure searches and reports. Under-claiming is not a breach, which is why this is a follow-up and not a finding — but a public document that is wrong about our own controls is a defect, and the pair should be rewritten to say what the mechanisms do and what is still manual. | `apps/web/**` is outside this session's edit scope (a parallel session owns it). One callout each, in the same wording D-179 uses on the certificate.~~ |
| FOLLOW-UP-9 | **F-15's screen half: the model picker must stop calling our cost "what you pay".** `apps/web/src/components/llmModelPicker.tsx:205` labels the model in force *"what you pay now"*; `apps/web/src/app/c/[slug]/settings/models/page.tsx:69` says *"a decision about your bill as much as about your agents"* and `:210` *"It costs ₹X a minute"*; `apps/web/src/app/c/[slug]/agents/AgentModel.tsx:157` repeats the last one. (Line numbers read 22 Aug 2026, while a parallel lane was editing the same files for availability.) `billing/rates.py` is unambiguous that nothing bills the in-call leg and that the figure is our own list-price cost; a client is charged their plan's overage rate or `self_serve_inr_per_min`, neither of which moves with the model. The figure should be labelled as what it is (our cost of the language leg, published so the choice is informed) or the sentence about the client's bill removed. | The agents/billing UI is another lane's. `/legal/terms` §6.1 now states the true position, which is the contract catching up with the screen and not a fix for it. **OURS, no external dependency.** |
| FOLLOW-UP-10 | **F-13's mechanism half: make a change to `azure_openai_resource` invalidate the region attestation.** The console write path for that one field should refuse unless `docs/evidence/azure-deployment-attestation.json` names the new resource — the shape `scripts/check_model_lifecycle.py` already uses to consume that file. Today an operator can point the language leg at a resource in another region, and every guard, gate record and client document stays green while gate 20's reading silently describes a resource we no longer use. **And `docs/ROADMAP.md:673` (D-444) still repeats the withdrawn sentence internally** — *"no setting, console control or environment variable able to move it"* — which is where the next writer would copy it back from into client copy; correcting it is one clause and belongs to whoever owns that row. | `apps/api/core/platform_config.py` and `scripts/**` are the guards/config lane's. The client-facing copy no longer over-claims (F-13), so this is the mechanism and not a live misstatement. **OURS, no external dependency.** |
| FOLLOW-UP-11 | **Correct `apps/api/compliance/deletion.py:62`**, which quotes the withdrawn *"90-day minimum retention of call recordings on Indian infrastructure"* from `SECURITY-COMPLIANCE.md` §1. The duration is right and the location half has no citable source (§1, 22 Aug 2026). | `apps/api` is another lane's. One docstring line. |
| ~~FOLLOW-UP-5~~ | ~~F-6: write the breach-notification runbook section.~~ — **DONE (D-179)**: `runbooks/data-breach-notification.md`, `apps/api/compliance/breach.py` and `scripts/breach_notice.py`. What remains is the Board's own reporting channel, which is a lookup and is recorded in that runbook's §7. | Was outside the audit session's ownership; closed in the next one. |
