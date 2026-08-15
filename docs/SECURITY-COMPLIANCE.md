# Calevate — Security & Compliance Specification

Version 1.0 · July 2026. This maps every legal/security obligation to a concrete system
feature. Nothing here is optional; items marked [GATE] block launch of the relevant feature.

---

## 1. Regulatory Baseline (India)

| Regime | What it governs for us | Key facts encoded below |
|---|---|---|
| TRAI TCCCPR (+2025 amendments) | Commercial calls, number series, DND, templates | 140-series exclusively for promotional robo-calls; 160-series for transactional/service; misclassification = most common registration failure; 5+ spam complaints in rolling 10 days ⇒ TSP enforcement within 5 days; penalties: 15-day outgoing suspension (first), 1-year disconnection + blacklist (repeat) |
| DLT registration | Who may place commercial calls | Principal Entity registration ₹5,900 (first TSP; later TSPs free); telemarketer + header + **voice template** registration required; unregistered ⇒ blocked at network as spam |
| DPDP Act 2023 + Rules (notified Nov 2025) | Recordings, transcripts, leads = personal data | Consent is the only general-purpose lawful basis (no "legitimate interest"); phased deadlines — enforcement live now, consent-manager framework Nov 2026, **full substantive compliance mandatory 13 May 2027**; erasure with proof; breach notification; penalties up to ₹250 crore |
| TRAI recording rule | Recording retention | **90-day minimum retention of call recordings on Indian infrastructure** (floor in retention_policies) |
| IT Act 2000 / case law | Undisclosed recording | Disclosure before recording required (Sanjay Pandey line of cases); criminal exposure for breach of confidentiality |
| Sectoral overlays | If client is BFSI/insurance | RBI/IRDAI/SEBI rules incl. longer retention (e.g., 2y RBI); no cross-selling on 160-series service calls |
| EU AI Act Art. 50 | Only if EU callers (not v1) | AI must disclose it is AI from 2 Aug 2026 — we disclose everywhere anyway |

## 2. Call-Level Compliance (built into every agent) [GATE for any live agent]

1. **AI disclosure**: `agents.disclosure_line` is NOT NULL; first utterance of every call
   identifies the assistant as AI, in the caller's language. Verified by regression suite.
2. **Recording consent**: disclosure includes recording notice; explicit consent captured
   for outbound recording where required; `calls.consent_recording` + immutable
   `consent_ledger` row with evidence (transcript span). Caller decline ⇒ recording off,
   call continues, ledger row written.
3. **Opt-out honored live**: "don't call me again" ⇒ tool adds to tenant `dnc_list`
   within the call; propagates to campaigns immediately (target ≤ minutes, not the 4h norm).
   Built in TWO layers with one write path (D-56, `apps/api/compliance/optout.py`): the
   in-call tool (`POST /tools/v1/{engine}/opt-out` in voice-runtime → the
   `record_in_call_optout` job) is this bullet as written, and the post-call pipeline's
   transcript pass is the layer under it — because the tool depends on the model
   invoking it and on Bolna's custom-function behaviour, which is still an OPERATIONS §2
   gate rather than a verified vendor fact. TRAI's own ceiling is "near real time, and
   in no case beyond twenty-four hours"; hard rule 5's "before the next dispatch tick"
   (30s) is the stricter number we hold ourselves to.
4. **No cross-sell on service calls**: topic-fencing config on 160-series/service agents;
   regression scenario asserts the agent refuses promotional turns.
5. **Calling hours**: campaign engine enforces permitted windows; per-tenant timezone.

## 3. Campaign Compliance Gate [GATE — launch button disabled until all pass]

DLT role model (corrected): the **client is the Principal Entity (PE)** — calls are made
on their behalf, under their identity and templates; **Calevate is the registered
Telemarketer (TM)** linked to each client PE. Calevate's TM registration (requires our
entity — Risk R-01) is the company-level blocker; each client's PE registration
(~₹5,900 first TSP) is an onboarding-wizard step we execute for them (part of setup fee).

A campaign cannot launch unless ALL of — each bullet now naming the blocker
`campaigns.service.launch_blockers` returns, so a screen, a test and this section can
cite the same string:
- Calevate TM registration exists AND this client's PE registration + TM-link are active
  (inbound-only operation is the interim mode while pending). Ours is
  **`tm_registration_missing`**, read from `platform_state` (D-43) — one row, false for
  every tenant at once, and reported alongside the client's own blockers rather than
  short-circuiting them. Theirs is **`pe_registration_missing`** (no row at all) or
  **`pe_registration_not_active`**, and then **`tm_link_not_active`**. Those last two are
  the only sequential pair in the function: a TM link to an entity that is not registered
  cannot be active either, and telling a client to chase an authorisation for a
  registration they do not yet have sends them to the wrong desk.
- `campaigns.classification` set; number series matches (promotional⇔140; transactional/
  service⇔160/standard — `number_series_mismatch`, `number_missing`); the number's own DLT
  header registered (`number_not_registered`); voice `dlt_templates.status='approved'` and
  linked, for this classification (`dlt_template_missing`, `dlt_template_not_approved`,
  `dlt_template_mismatch`). Three registrations, and none implies another.
- Contact list DNC-scrubbed (national DND + tenant `dnc_list`) with scrub timestamp; a
  list with nothing left after the scrub is `all_contacts_dnc`, an empty one
  `no_contacts`. **The two scrubs are separate facts and this bullet used to claim a
  national one the system could not perform** (migration a1c8e40f27b9):
  - **Tenant list** — `launch_campaign` marks every contact on this tenant's `dnc_list`
    (and every `scope='global'` row) `dnc_blocked` before the CAS to `running`, and now
    stamps `campaigns.dnc_scrubbed_at` in the same statement. That is the scrub
    timestamp this bullet promises for our half, and nothing recorded it before.
  - **National DND** — the customer preference register (NCPR) is **not obtainable**:
    it lives on the access providers' DLT platform, which scrubs a list you submit and
    returns a reference, a count and a verdict valid to 23:59:59 that day, and every
    operator's DLT documentation states that the preference database itself "will not be
    accessible to telemarketers". So the artefact is a RUN, not a loaded list:
    `preference_scrub_runs` (DATA-MODEL §9), recorded through
    `POST /v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub`
    (step-up confirmed, audited, counts only — no number is stored). Until a current run
    exists, a **promotional** campaign is refused by `national_dnd_scrub_missing`,
    `national_dnd_scrub_expired` (the run aged past its IST day) or
    `national_dnd_scrub_incomplete` (contacts were added after it ran) — at launch AND
    on every dispatch tick, because the validity window ends at midnight while a
    campaign keeps dialling. `transactional` and `service` campaigns are outside the
    rule: under full DND every category is blocked except service-implicit, and
    transactional traffic is delivered whatever the preference, so scrubbing them would
    suppress calls a preference-registered subscriber is entitled to receive.
  - **WHAT IS EXTERNAL**: performing a scrub needs a Registered Telemarketer
    relationship with an access provider and a login to that provider's DLT platform —
    the same relationship that produces `platform_state.tm_id`, so this gate blocks
    nothing that `tm_registration_missing` was not already blocking. **What is still
    unverified**: the recorded reference is taken from an operator and never queried
    back, so the gate proves an accountable assertion rather than a performed scrub
    (`tests/national_dnd_test.py::UNVERIFIED_SCRUB_EVIDENCE`).
  - **`dnc_list.scope='global'` is NOT the national register** and never was: it is an
    absolute platform-wide suppression (a regulator/TSP instruction naming a number, or
    our own permanent refusal), and it had **no writer anywhere** until
    `POST /v1/ops/dnc/global` (step-up confirmed, audited, `GLOBAL_SOURCES` =
    `regulator` / `platform_block`). NCPR preferences are category-scoped and expire
    daily, so loading them here would refuse lawful transactional traffic. A tenant
    session still cannot create a global row — the RLS `WITH CHECK` admits the new
    branch only for a session carrying no `app.tenant_id`.
- Consent provenance recorded for the list (source + date) — a purchased list with no
  consent artefacts is refused, in writing, as policy. **`consent_provenance_missing`**
  when nobody has said (`campaigns.consent_source IS NULL`, which is what every campaign
  predating the columns honestly reports) and **`consent_source_refused`** when the answer
  is `purchased_list`. The enum deliberately INCLUDES `purchased_list`: the refusal this
  bullet promises can only be written if the client can say the word, and an enum stocked
  only with acceptable answers does not stop purchased lists — it hides them behind
  whichever member sounds nearest. Declared through
  `POST /v1/campaigns/{campaign_id}/consent-provenance` (drafts only, audited).
- **Subscriber KYC verified** — `kyc_missing` (nothing filed) or `kyc_not_verified`
  (filed, not cleared; the string names the state, because `submitted` means we owe them
  a review and `rejected` means they owe us a document). D-47, and it is deliberately
  **not the same scope as the rest of this list**: the DIALLING gate applies to
  `self_serve` and `trial` tenants only — a managed tenant's identity was verified out of
  band and their dialling is already gated by `pe_registration_*` and
  `number_not_registered` — while **buying a number is gated for every tier**, because the
  DoT business-connection obligation attaches to the connection and `plan_tier` is an
  admin-settable column. Asked once, in `compliance.kyc_blocker`, by both the per-dial
  gate and this launch preview. Inbound answering is never gated (D-38).
- **The account's first campaign has been reviewed by a human** — `first_campaign_review_pending`
  (nobody has looked yet) or `first_campaign_review_rejected` (a reviewer looked and said
  no, and the refusal carries their words). D-51, and R-11's last mitigation. Same scope
  split as the KYC dial gate — `self_serve` and `trial` tenants only, because a managed
  tenant's first campaign was set up by us — and the hold is on the **account**, not on a
  campaign row: while it is held every campaign is refused, so it cannot be skipped by
  launching a second one or by deleting the one an operator was reading. Asked in
  `launch_blockers` AND in `dispatch_blockers`, so a release withdrawn after complaints
  arrive stops a RUNNING campaign at the next tick. Released once, no later campaign is
  refused on this rule. Deliberately not asked by `check_dispatch`, which also serves the
  D-21 single-lead button and the instant callback — neither is a campaign.
- Per-tenant caps (`spend_state`) not exceeded (`spend_cap`), and the prepaid wallet not
  exhausted (`no_credits`). The effective ceiling is `LEAST(admin, client)` — a client may
  lower their own at will and may never loosen it past the admin's (SURFACES §2b) — and a
  cap raised for a capped tenant does NOT by itself release the gate: the flag is derived
  and re-derived by `POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute` or by the
  client's own cap write.

## 4. Data Protection (DPDP) — Feature Map

| Obligation | Feature |
|---|---|
| Notice + consent | Client-facing DPA + privacy notice; caller disclosure line; consent_ledger (incl. the `messaging` purpose — see below) |
| Purpose limitation | data_category on storage; consent purpose enum; no secondary use of client data (we are Data Processor for clients' caller data; Fiduciary for client-account data — recorded in DPA) |
| Retention limits | retention_policies per category with TTL enforcement job; recording floor 90 days (TRAI), default 180; BFSI clients configurable ≥ regulator minimum; transcripts/leads default 24 months |
| Erasure with proof | deletion_requests workflow: `POST /v1/compliance/deletion-requests` writes the row and queues the worker in ONE transaction (transactional outbox) → locate by phone across calls/turns/extractions/leads/recordings → delete/anonymize → write proof JSON (what, where, when, hashes) **and clear `phone_e164` in that same UPDATE**, so a completed request is not the last surviving copy of the number it certifies as erased (D-44; `subject_ref`, the same hash the proof and the subject-access export use, is what remains) → certificate to requester; covers our object storage AND engine copies (adapter deletes engine-side records; Bolna's deletion API is undocumented — pilot gate, and a written erasure commitment goes in the Bolna contract, so the certificate reports engine-side deletion as `unconfirmed_pending_vendor_api` rather than claiming it). **Recordings under 90 days: see the open decision below — this row and the retention row above point in opposite directions.** |
| Breach notification | Incident runbook (OPERATIONS.md §7): classify, contain, notify Board + principals per Rules timeline; webhook_deliveries + audit_log provide forensic trail |
| Security safeguards | §5 below |
| Cross-border | CAUTION (D-31): Bolna call recordings observed on S3 us-east-1; their Enterprise tier offers full India data-residency (audio, transcripts, logs, in-India inference) — residency posture must be pinned in the Bolna contract and disclosed in the client DPA until then. **Models are all-India BY DEFAULT since D-36** — Sarvam is sovereign and now serves STT, LLM *and* TTS, so no transcript text leaves India on the default stack. This inverts the earlier posture: "all-India" is no longer a client opt-in at a quality tradeoff, it is what ships. Gemini remains a *configurable fallback*; enabling it sends transcript text (never audio) to Google and therefore requires a DPA disclosure and an explicit per-tenant decision — treat switching an agent to Gemini as a residency change, not a config tweak. This is a live differentiator: Outpero's privacy policy admits "some providers may process data on servers located outside India" (evidence/outpero-teardown-aug2026.md §9b) |

**Tenant-level erasure — a different data subject, and a different DPDP relationship
(D-122).** The `deletion_requests` row above is ONE data principal exercising §12 against
a client's caller records: the client is the Fiduciary, we are the Processor, and the
certificate is theirs to hand on. The END of an engagement is a separate instruction under
§8 — the Fiduciary is responsible for processing carried out on its behalf and has the
Processor erase on instruction — covering every subject in the account at once. It has its
own table (`tenant_erasure_requests`), its own admin-realm surface
(`POST /v1/admin/tenants/{id}/erasure`, superadmin + a step-up bound to the tenant), and
its own certificate; it reuses the same worker module, the same object-store helpers and
the same `recording_erasure_holds` schedule, because the MECHANISM is one mechanism even
though the subjects are two. It is the only writer of `organizations.deleted_at`, it
refuses an account that is not already `churned`, and what it does not erase — the
append-only ledgers (hard rule 4), DNC suppressions, the client's own users and
memberships, engine-side copies, and the same client-uploaded knowledge content the
per-subject register already declares unsearched — is enumerated in the certificate
rather than left to inference. Nothing here DECIDES that open question; it repeats the
per-subject register's statement so the two certificates cannot disagree.

**Delivered CRM bodies (D-23) are personal data we now retain, and the terms are these.**
`webhook_deliveries.payload_ref` holds the object-storage key of the body we POSTed to a
client's own endpoint — the lead's name, their number in whatever form that endpoint's
`include_raw_phone` choice produced, and every extracted field. Kept because the delivery
log could otherwise prove only that a POST happened, so "you sent us the wrong lead" was
answerable with a reconstruction rather than with evidence. What makes retaining it
lawful rather than merely useful:

- **Retention period**: the tenant's OWN `lead` policy — the same category and clock as
  `call_extractions.data`, because it is the same class of data (see the retention row
  above; the seed default is 1095 days and is subject to the open question below). The
  nightly sweep deletes the objects and clears the references. This one does NOT depend
  on the bucket lifecycle rule the recording arm relies on: nothing here sits under a
  statutory floor, so the per-tenant mechanism is the whole answer and it exists.
- **Erasure**: `execute_deletion_request` deletes them by SUBJECT. The subject is in the
  object key (`webhook-bodies/{tenant}/{lead|call}-{id}/{delivery}.json`), so the erasure
  enumerates the object store by prefix rather than trusting the reference column — which
  is what reaches an object written by a worker that died before recording the reference.
  A store that will not answer aborts the erasure and retries it; the certificate never
  claims a deletion we could not perform. The count appears in the proof's `actions`.
- **What is deliberately NOT retained**: any event we cannot attribute to an erasable
  subject (today, `campaign.completed`). An object no data principal can be matched to is
  precisely the breach this store is designed not to become, so it is not written.
- **Access**: same class as a raw transcript and gated the same way — `calls:read_raw`
  plus an `audit_log` row on every read (`GET /v1/integrations/deliveries/{id}/payload`).
  `staff` and an impersonating operator see the delivery record and never the body.
- **Bounded**: 64 KiB per delivery, truncation declared inside the stored object. Neither
  the endpoint URL nor the signing secret is ever part of it.

**Archived raw engine payloads (D-126) are the third personal-data store outside
Postgres, and the erasure reaches them.** `calls.engine_payload_ref` holds the
object-storage key of the vendor's own document for a call (hard rule 2 keeps that
document out of typed columns); it carries the caller's number and the transcript, so it
is personal data whatever it is kept for. Its key was
`engine-payloads/{engine}/{date}/{execution_id}` — naming neither tenant nor subject, so
no erasure could enumerate one person's copies. It is now
`engine-payloads/{tenant}/{call}/…` and `_erase_engine_payloads` destroys every object
under the erased calls' prefixes, on the per-subject path and the tenant path alike, with
the count in the proof's `actions`. Two limits stated rather than implied: **nothing
writes this archive yet** (the arm exists BEFORE the producer, because after the producer
the unreachable objects already exist), and **no retention category expires it** — the
enum is `recording|transcript|lead|consent_log`, so for anyone who has NOT filed an
erasure the only clock is the bucket's 90-day `engine-payloads/` lifecycle rule, which
has never been applied to a real bucket (infra/README §5). Giving the archive its own
retention category is a DPA commitment and a change to a documented enum, and is reserved
here the same way the backup clause below is.

**OPEN DECISION — erasure vs. the 90-day recording floor.** Surfaced by the DPDP erasure
producer (`apps/api/compliance/deletion.py`), stated here rather than resolved, because
two adjacent rows of the table above point opposite ways for one concrete case: a call
recording less than 90 days old, whose subject has just asked to be erased.

- **§4 "Erasure with proof"** describes the workflow as covering *recordings*, in our
  object storage and on the engine.
- **§1 (TRAI recording rule) and §4's own retention row** record a **90-day minimum
  retention** of call recordings on Indian infrastructure — a floor the codebase treats
  as binding in two independent places: a DB CHECK on `retention_policies.ttl_days`, and
  `apply_retention` clamping every recording TTL to `RECORDING_FLOOR_DAYS = 90`.

Both readings are defensible. *Erasure wins*: DPDP's right is the data principal's, the
TRAI rule governs a telemarketer's own record-keeping, and a Processor that cannot delete
on instruction has a compliance gap. *Retention wins*: a statutory retention obligation is
one of the standard grounds on which an erasure request is lawfully deferred, and
destroying the recording destroys the evidence that the call itself was compliant.

**The prerequisite has been built, and the decision is narrower than it was.** This
section used to say that no per-tenant mechanism deleted recording bytes, that three
modules named a lifecycle rule which does not do what they assumed, and that building the
real mechanism was "prerequisite work for this decision, not a consequence of it". That
work is done (migration `9c1d3e7a05f4`), and doing it surfaced a defect nobody had
named:

- **The retention sweep never deleted the audio.** `apply_retention` cleared
  `calls.recording_url` at `max(ttl, floor)` and left the object in the bucket until the
  2555-day growth ceiling — so "recordings are kept for 90 days" was true of a column and
  false of a person. The sweep now deletes the object and then clears the reference, in
  that order (`_sweep_objects_in_batches`), so a crash leaves a dangling reference rather
  than an unreachable object.
- **An erasure made the audio permanently undeletable.** The pointer clear destroyed the
  only handle anything had on the key, and the sweep selects
  `WHERE recording_url IS NOT NULL` — so a caller who exercised their §12 right ended up
  with their recording orphaned in the bucket forever, while a caller who did nothing had
  theirs expire on the tenant's policy. That is not either side of the question below; it
  is the failure to have asked it.

**What the code does today.** `execute_deletion_request` still clears
`calls.recording_url` **unconditionally, at any age** — unchanged, because this section
forbids making it conditional before the decision is taken. It now also splits the audio:
a recording **past** the floor is destroyed by the request, and a recording **inside** it
is written to `recording_erasure_holds` with the earliest instant at which destroying it
is lawful, which the nightly sweep then honours without a second request. The certificate
states the destroyed count and the destruction date, so the notice no longer has to say
"treat the audio as still existing" indefinitely.

**Why a deferral rather than a refusal, stated where it is relied on.** DPDP §12(3)
requires erasure "unless retention of the same is necessary for the specified purpose or
for compliance with any law for the time being in force" — a retention obligation moves an
erasure's date, it does not cancel it — and DPDP §8(7)'s storage limitation makes holding
the data past the end of that obligation a breach in its own right. So the lawful shape of
"we cannot delete this yet" is a schedule, and a schedule has to be a row rather than a
sentence. (DPDP Rules 2025 Rule 8's Third Schedule erasure periods are **not** engaged:
they apply to e-commerce, online gaming and social-media fiduciaries above 2 crore / 50
lakh user thresholds, and Rule 8(3)'s 48-hour pre-erasure notice rides on them.)

**What is STILL reserved to the founder**, and it is now the whole of the open question:
whether an erasure should destroy a recording **younger** than the floor anyway. Nothing
in the code takes it — no under-floor recording is destroyed early — and it still needs
the Bolna erasure commitment from pilot gate 12(f) in hand, because an answer that binds
our storage but not the engine's is not an answer. Until then: do not narrow the
certificate's limitations text, and do not make the pointer-clear conditional on age
without deciding this first. Resolving it is a decision-log entry against this section
(ROADMAP §6); resolving it "erasure wins" is now a one-line change, because it only moves
`erase_after` to `now()`.

**And the floor's own authority is in doubt** — recorded as an equality-asserted entry in
`tests/dpdp_known_gaps_test.py` rather than resolved here, because it is counsel's call.
§1 attributes the 90 days to TRAI; TRAI's 90-day figure in the TCCCPR framework is the
opt-out cooling period before a sender may seek fresh consent, and the two-year archive of
commercial records/CDR/EDR/IPDR is **Unified Licence clause 39.20** (amended December
2021), which binds licensees — telecom service providers — and not a telemarketer. The
floor errs towards keeping data, so nothing is destroyed too early; it errs the other way
into §8(7), because retaining personal data on a legal basis that does not exist is itself
the storage-limitation breach.

**OPEN QUESTION — the retention defaults in this document and the ones in the seed do not
match, and neither matches the other.** Surfaced by the retention sweep, stated here
rather than resolved because it is a policy call, not a code fix.

- §4's retention row above says **transcripts/leads default to 24 months** (730 days), and
  recordings to a **default of 180** over the 90-day TRAI floor.
- `scripts/seed.DEFAULT_RETENTION_POLICIES` — the rows a new tenant actually gets, and the
  rows the nightly sweep obeys — are **transcript 365 days**, **lead 1095 days**,
  **recording 90 days**, consent_log 2555 days.

So a transcript is deleted at half the documented age and a lead is kept at one and a half
times it. This matters beyond tidiness: the client-facing **DPA quotes this document**,
while `apply_retention` obeys the rows — so today we tell clients one retention period and
run another, in both directions. It cannot be settled by picking whichever number is in
front of you: the seed values are a defensible split (a lead is the CRM record the client
bought and keeps using; a transcript is raw personal data with a shorter useful life),
and 24 months for both is what has been promised in writing.

**Who must decide: the founder**, because it is a commitment to clients and a DPA edit,
not an implementation detail. Whichever way it goes, both places change in the same
release — this section, and `DEFAULT_RETENTION_POLICIES` — and the change is recorded as a
decision-log entry (ROADMAP §6). Existing tenants' rows are their own decision: a policy
row already agreed with a client is not silently re-timed by a seed change.

**OPEN QUESTION — an erasure does not reach the backups, and a restore un-does one.**
Surfaced by the backup work (D-50, `infra/backup/`), stated here rather than resolved
because whether it must be disclosed is a legal call.

- Both backup chains retain **35 days**. So for up to 35 days after a completed erasure,
  the person's data still exists in a base backup, in the WAL segments and in the offsite
  dump. The window is deliberately short for exactly this reason — every extra day of
  retention is an extra day an erasure cannot fully reach our data — but it is not zero,
  and a backup that could be edited to remove one subject would not be a backup.
- **A point-in-time restore un-erases people.** Anyone whose erasure completed after the
  recovery target comes back holding a certificate saying they were removed.
  `runbooks/database-restore.md` makes replaying those erasures a MANDATORY step, and the
  authoritative list has to come from the preserved pre-restore cluster, because requests
  raised after the target do not exist in the restored one.
- `ERASURE_LIMITATIONS` (`apps/api/compliance/deletion.py`) does **not** currently carry a
  backup clause. Every other limitation of the erasure is disclosed on the certificate;
  this one is not, and that asymmetry is the open item. **Who must decide:** the founder
  with counsel — a backup-retention clause is standard in DPDP-facing erasure notices, but
  adding a sentence to a notice that clients hand to data principals is a commitment, not
  a code change. Whichever way it goes, this section and `ERASURE_LIMITATIONS` change in
  the same release, with a decision-log entry (ROADMAP §6).

**Messaging consent is its own permission, and it is never inferred.** The campaign
follow-up (FLOWS §4.5) is a business-initiated WhatsApp message to a consumer, which
brings in a regime the dial gate above does not cover:

- **Meta's WhatsApp Business Messaging Policy** requires an opt-in before any
  business-initiated message. It may be collected on any channel and need not be
  WhatsApp-specific, but it must state that the person is opting in to receive MESSAGES
  and name the business they will come from, and it must be an affirmative act. The
  business must be able to produce the TIMESTAMP and the SOURCE of that opt-in when a
  number is challenged.
- **TCCCPR 2018 as amended (Second Amendment, 12 Feb 2025)**: explicit consent under
  Reg. 2(y) is consent verified from the recipient and recorded by the **Consent
  Registrar** on DLT via Digital Consent Acquisition — a registrar function we cannot
  perform, so what we hold is OUR evidence, not registrar-grade explicit consent. The
  same amendment refuses indefinite consent: consent tied to an ongoing transaction
  lapses in seven days and inferred consent dies with the contractual relationship.
- **DPDP §6** binds consent to the purpose it was given for and requires withdrawal to
  be as easy as consent.

Encoded as: `consent_ledger.purpose = 'messaging'` with a mandatory `consent_source` and
evidence (DATA-MODEL §9, migration c2f7a91b4e63); captured through
`POST /v1/compliance/messaging-consent` (`leads:dispatch`, audited, number in the body
and never in a URL); read by `apps/api/compliance/consent.py`, which honours a validity
window so a stale opt-in stops authorising messages. Consent to be CALLED — a campaign's
`consent_source` provenance, or a `callback` ledger row — never satisfies it, and nothing
backfills it. The follow-up still passes `check_dispatch` first: this is an additional
gate, never a substitute for the DNC read.

**PII redaction (workers step 2):** regex + validator pass for Aadhaar (Verhoeff), PAN,
card (Luhn), OTP patterns, plus LLM-assisted pass for spoken-out numbers; produces
`text_redacted`. Default UI shows redacted; raw text requires owner/admin role and writes
audit_log. Redaction runs BEFORE any transcript leaves our system (exports, notifications).

## 5. Application & Infrastructure Security

Identity & access
- Two auth realms (admin vs client), separate Clerk apps, separate cookies/domains; MFA
  mandatory on admin; session lifetimes: admin 12h, client 7d refresh.
  - **MFA is enforced server-side**, in `apps/api/core/auth.py::verify_token`, from
    Clerk's `fva` session claim: an admin-realm token whose second-factor age is `-1`
    (never verified) is refused `403 mfa_required`, and a token carrying no `fva` at all
    is refused `403 mfa_claim_missing` — unknown fails closed. It gates READS as well as
    writes, because it is authentication, not authorization. Enforced in the verifier so
    no route can forget it; `tests/admin_mfa_test.py` pins both directions plus the
    client realm's exemption. The admin console explains the refusal rather than
    enforcing it (`app/admin/layout.tsx`).
  - **Step-up (`X-Confirm-Action`) is a SEPARATE control and is retained**, not replaced:
    MFA is per SESSION (once, at sign-in, for 12h), step-up is per ACTION and per TARGET.
    The session that mis-clicks the big red switch is a session that has already passed
    MFA. Requiring a *fresh* second factor for high-risk actions (Clerk reverification)
    is the named next step and needs a browser reverification flow — OPERATIONS §8.
- RBAC: admin{superadmin,operator}; client{owner,staff}. Staff cannot access billing,
  org settings, raw transcripts, or exports containing unredacted data.
  - The endpoint→permission map is asserted AT BOOT (`core/rbac.py::
    assert_policy_registry_complete`), and the assertion is non-vacuous in four
    directions: a route with no declaration, a declaration with no lock behind it, a
    declaration that names a different permission than the lock checks, and — since a
    permission that does not exist satisfied all three by being wrong twice — a declared
    string that is not in the `Permission` type or that no role in `ROLE_PERMISSIONS`
    holds. The last one is a lock with no key: `role_has` refuses every caller, so the
    route 403s the whole population while reading as guarded.
  - The two realms' roles live in ONE `ROLE_PERMISSIONS` dict, so their separation is a
    convention in Python and a CHECK constraint in Postgres
    (`ck_memberships_role_enum`, `ck_admin_users_role_enum`). The constraint is the
    enforcement — a colliding role name cannot be STORED — and
    `tests/rbac_registry_test.py` holds the two statements of that fact to each other.
- Admin impersonation (D-22): READ-ONLY "view as client" — a scoped read-only session
  against the client realm, never a client credential; session start + every page view
  audit-logged (actor=admin_user, tenant, at, ip). No mutations while impersonating.
  - **Entry requires a short-lived signed GRANT**, minted by `POST /v1/admin/
    impersonation-grants` and presented as `X-Impersonation-Grant` beside
    `X-Impersonate-Org` (`apps/api/core/impersonation.py`). The grant is bound to the
    operator (`act.sub` = `admin_users.id`) and the tenant (`sub` = `organizations.id`)
    — RFC 8693's delegation claim shape, chosen because D-22's "no dual attribution"
    is exactly what that claim exists to express — plus a fixed audience and a
    minutes-long expiry. Absent, malformed, expired, another operator's or another
    tenant's are all refused; nothing degrades to a plain admin session.
  - It is **not a credential**: it never replaces the operator's admin-realm Clerk
    token, which is verified (and MFA-gated) on every request, and whose `admin_users`
    row and role are re-read from the database on every request. Revocation is
    therefore instant — sign-out, row deletion or losing `admin:impersonate` refuses
    the next request — which is why there is no denylist and no grants table.
  - The two ledger rows mean different things and both are needed:
    `admin.impersonation_started` is ONE PER GRANT ("authority was issued to operator X
    for tenant Y at T from IP I"), and `admin.impersonation_read` is at most one per
    (admin, tenant) per minute ("data was actually reached"). They carry the same
    `grant_id` so a session's two halves join exactly.
  - `X-Impersonate-Org` is either ABSENT or a slug. A present-but-blank value is a
    request defect and is refused `422 impersonate_org_blank`, because the third state
    it used to produce was worse than either: `impersonating=True` with no
    `admin:impersonate` check, no grant and no audit row. The flag is now derived from
    the RESOLVED tenant, so `Principal.impersonating` cannot be true unless a grant was
    verified and a read was recorded — which is what every mutating dependency reads it
    for. Driven in `tests/realm_boundary_test.py`.
  - A route declared `realm="client"` is not part of view-as and says so:
    `403 impersonation_not_available_here`, not the verifier's "this token is not valid
    for this realm". The refusal was always correct; the sentence sent an operator to
    whoever owns Clerk instead of to whoever owns the console. The client-realm
    mutations an operator can reach from a client's screen (`PUT /v1/billing/caps`,
    `POST /v1/billing/topups/intent`, `POST /v1/compliance/whatsapp-alerts`) are the
    live instances.
  - LIFECYCLE, and the asymmetry is deliberate: a `churned` organization locks out its
    own members (`_load_client_principal` filters `status <> 'churned'`) and stays
    reachable by an audited operator, because the questions that arrive after a client
    leaves — a DPDP erasure to verify, a final invoice to explain, a complaint to answer
    — are not answerable from outside the tenant. `suspended` locks out nobody; a
    SOFT-DELETED tenant is refused to both. Nothing about the departed-client entry is
    quieter: same permission, same grant, same two ledger rows, same read-only rule.
- Invitations: 72h single-use signed tokens, hash-at-rest, burned on use. **"Account
  creation only via invitation" is no longer true of the client realm** — D-34/D-39 put
  self-serve in scope and `POST /v1/auth/signup` ships (SURFACES §2c): a Clerk-verified
  user with no organization creates their own tenant, rate-limited by a signup quota, with
  `plan_tier` restricted to `self_serve`/`trial`. The ADMIN realm stays invite-only with
  Clerk signup disabled (D-37), which is where that rule still holds.

Data
- Postgres RLS FORCEd on all tenant tables; app sets tenant GUC from verified session;
  fail-closed. Admin access path uses distinct role + always-audited queries.
- Recordings: our object storage is system of record; SSE + per-tenant envelope keys (KMS);
  presigned URLs 5-min TTL; bucket public-access blocked at account level.
- Secrets: engine/model/client keys in secrets manager only; DB stores references.
  Quarterly rotation; per-integration webhook secrets.
- usage_events, consent_ledger, audit_log: INSERT-only DB grants (no UPDATE/DELETE for app role).

Transport & webhooks
- TLS everywhere; HSTS. Inbound engine webhooks: authenticity per engine capability
  (TRD §5). Where the engine signs: HMAC-SHA256 + timestamp window + replay cache.
  **Bolna (D-31) does not sign**: strict source-IP allowlist (their static egress
  13.203.39.153) enforced at nginx AND in-app — through Cloudflare this REQUIRES the
  D-27 real_ip restoration (CF-Connecting-IP), which is now load-bearing, not
  nice-to-have — plus execution-id dedupe, payloads treated as hints, and the
  authenticated Get Execution fetch as truth. Unexpected source ⇒ 401 + alert. The
  reconciliation poller, not webhook delivery, is the guarantee of record.
  Outbound (to client CRMs): our own HMAC signing + a 3-attempt retry budget with
  30s/120s backoff (`WORKER_MAX_TRIES`, `RETRY_BACKOFF_S`) that retries transport
  failures and 5xx/408/425/429 only — any other 4xx is recorded `rejected {code}`
  without a retry — + delivery log.
- Client-facing webhook ingest (Meta/website): per-endpoint secret; schema-validated;
  rate-limited; payloads treated as untrusted data (never as instructions).

SDLC & ops
- CI: Ruff, mypy strict, tests (incl. RLS tests: cross-tenant read MUST return zero),
  Alembic check, dependency & secret scanning, SAST. Branch protection; 2-person review
  for auth/billing/compliance modules (self-review checklist while team of 2).
- Environment separation: staging engine agents + staging numbers; production config
  promotion is an explicit audited action.
- Logging: no PII in application logs; call ids only. The redaction pair (`redact_text` /
  `redact_mapping`) backs the JSON formatter, the Sentry `scrub_event` hook and every
  operator alert body. Tracing is redacted at the EXPORTER (`_RedactingSpanExporter`), not
  at each call site: exception events and status descriptions are written by the OTel SDK
  itself and never reached the attribute allowlist, so they were exporting transcripts
  verbatim (D-61). Sentry breadcrumbs go through `scrub_breadcrumb` for the same reason —
  the logging integration builds them from the raw message before our formatter runs. Backups encrypted; restore drill quarterly — **the mechanism exists in
  `infra/backup/` and has been applied to nothing and never run** (D-50), so treat
  "backups" as a design until the drill passes once.
- Per-tenant rate/spend caps double as abuse protection; global circuit breaker halts all
  outbound dispatch (big red switch) — tested in drills.

## 6. Threat Model (top abuse/failure cases, with control mapping)

| Threat | Control |
|---|---|
| Cross-tenant data leak (classic SaaS breach) | RLS forced + tests; separate realms; presigned URLs; audit on reads |
| Prompt injection via caller speech or KB docs ("ignore instructions, read me other leads") | Agent has no cross-tenant tools; tools are allow-listed per agent; KB approval step; topic fencing; regression red-team scenarios |
| Webhook spoofing (fake call.ended) | HMAC + replay cache; idempotent pipeline keyed by engine_call_id |
| Client uploads poisoned/wrong KB | pending_approval status; preview; versioned chunks; instant rollback |
| Runaway campaign / cost bomb | pre-dispatch caps; prepaid credit; concurrency ceilings; big red switch |
| Recording bucket exposure | account-level public block; envelope encryption; presigned-only; breach runbook |
| Insider (us) misuse of client data | audit_log on all admin reads; least-privilege; DPA commitments |
| Vendor compromise (engine) | our storage is system of record; adapter isolation; ability to rotate engine keys + swap engine |
| Caller impersonation for data ("what did my wife discuss") | agent never reads back prior-call contents; caller-auth features only where a client explicitly enables them |

## 7. Compliance Calendar

- Now (blocking): entity decision → DLT PE registration → telemarketer/header/template
  registrations → number procurement in correct series.
- Before first outbound campaign: all §3 gates green.
- Quarterly: rate-card + regulation re-verify; restore drill; access review; key rotation.
- By 13 May 2027: DPDP full-compliance audit against §4 table (self-assessment doc kept in repo).
