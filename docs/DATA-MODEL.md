# Calevate — Data Model (Postgres 16 + pgvector; the `vector` extension is REQUIRED since D-502)

Version 1.0 · Conventions: snake_case; every table has id UUID PK (uuid_v7), created_at,
updated_at; every tenant-scoped table has tenant_id UUID NOT NULL REFERENCES organizations(id)
and an RLS policy; soft-delete via deleted_at where noted; money as NUMERIC(12,4) INR;
phone as E.164 TEXT; all timestamps timestamptz.

## 1. RLS pattern (applied to every tenant table)

```sql
ALTER TABLE t ENABLE ROW LEVEL SECURITY;
ALTER TABLE t FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON t
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- API sets: SET LOCAL app.tenant_id = '<verified-org-id>'; per request/txn.
-- Admin console uses a separate role with a broader policy + mandatory audit_log writes.
-- Missing/invalid GUC ⇒ zero rows (fail closed).
```

## 2. Tenancy & Identity

```
organizations(id, name, slug UNIQUE CHECK (slug ~ '^[a-z0-9-]{3,40}$') IMMUTABLE-by-trigger,
  status ENUM[prospect,onboarding,active,suspended,churned], vertical_template TEXT,
  plan_tier ENUM[managed,self_serve,trial] NOT NULL DEFAULT 'managed',   -- D-34/D-39
    -- which MOTION this org belongs to, not a feature flag: it decides whether credits
    -- gate dispatch (compliance gate) and whether the self-serve screens render
  billing_email, created_by, deleted_at)
  -- NOBODY HARD-DELETES THIS ROW, and since migration d1b8f30c94a7 the table says so.
  -- `tenant_isolation` is FOR ALL and `WITH CHECK` is not consulted on DELETE, so `USING`
  -- alone decided and it admitted the session's own org: a tenant could destroy the anchor
  -- every tenant table's FK points at (PROVEN, D-207). `organizations_delete_admin_only` is
  -- RESTRICTIVE FOR DELETE, `USING (app.admin = 'on')` — an admin-realm operation or none.
  -- The lifecycle is unchanged: `deleted_at` is the soft delete and
  -- `tenant_erasure_requests` is still the only thing that writes it.
  -- An UNKEYED read of this table is a sequential scan of the whole platform's client list
  -- (34,470 rows / 596 buffers / 9.7 ms, measured): the policy's `id IN (SELECT ...)` branch
  -- cannot be an index condition. Keyed reads (`slug =`, `id =`) plan as index scans and are
  -- what every request path uses; the one unkeyed reader is the admin directory.
reserved_slugs(slug PK)              -- admin, api, login, settings, app, www, ...
users(id, clerk_user_id UNIQUE, email, name, phone, deactivated_at, email_verified_at)
  -- clerk_user_id: NOTHING WRITES OR READS IT since D-177. Kept one release under hard
  -- rule 8's two-step deprecation and recorded in `scripts/check_wiring.UNWIRED_BASELINE`;
  -- the DROP is step 2 (AUTH-MIGRATION §11). Do not add a reader.
  -- deactivated_at re-checked by the auth guard on EVERY request (BACKEND-PATTERNS §7):
  -- a cached session must not outlive a deactivation. It is also the client realm's whole
  -- liveness rule in `authn/subjects.py`, so signing in and staying signed in agree.
  -- email_verified_at: set by the `email_verify` OTP round trip, or directly on
  -- invitation redemption (possession of the emailed token IS the proof) — D-170.
  -- WHERE THE CREDENTIAL LIVES: not here. `auth_credentials` (Argon2id + KEK-derived
  -- pepper) and `auth_sessions` (opaque token fingerprint, mfa_verified_at, idle/absolute
  -- bounds), both FORCEd deny-by-default RLS, migration e9a4c1d70b52 — AUTH-MIGRATION §2.
memberships(id, tenant_id, user_id, role ENUM[owner,staff], UNIQUE(tenant_id,user_id))
  -- staff: no billing.*, no org settings, no raw (unredacted) transcripts, and no
  -- recording audio (D-181: the audio is the source of the text that rule protects)
invitations(id, tenant_id, email, role, token_hash UNIQUE, expires_at DEFAULT now()+'72h',
  used_at, created_by)               -- single-use; hash only; burned on accept
admin_users(id, clerk_user_id UNIQUE, email, name, role ENUM[superadmin,operator],
  deactivated_at)                                                     -- separate realm
  -- Same two-step deprecation on its clerk_user_id, and the same DROP owed. This table is
  -- an ops-managed allowlist reconciled from nothing; `scripts/bootstrap_admin.py` writes
  -- the first row (D-171) and the console writes every later one
  -- (`POST /v1/admin/operators`, `admin:operators`, superadmin only).
  -- UNIQUE on lower(email) WHERE deactivated_at IS NULL — one LIVE operator account per
  -- address, the same partial shape `users` carries (c7a1e93d40b8).
  -- REVOCATION IS `deactivated_at`, NOT A DELETE (f2c74b81a9d3). Eight tables reference
  -- this one ON DELETE RESTRICT because they record which operator approved a campaign,
  -- verified a KYC record or installed a credential, so the DELETE the admin realm's
  -- liveness rule once assumed raises 23503 for exactly the operators somebody would want
  -- removed. The row is evidence; the account ends, and its password, sessions and
  -- outstanding setup link are destroyed with it.
```

**The four AUTHENTICATION tables are NOT above, and they are not missing either** — they
have one home and this document is not it. `auth_credentials`, `auth_sessions`,
`auth_email_tokens` and `auth_otp_challenges` (migrations `e9a4c1d70b52` and
`b3d9f6a2c815`, `apps/api/authn/models.py`) hold the password hash, the opaque session, the
single-use emailed tokens and the OTP challenges that D-165/D-170 brought in-house from
Clerk. **`docs/AUTH-MIGRATION.md` §2 is their schema of record** and carries the column
list, the predicates and the reasoning; duplicating the shape here would be the second copy
that drifts. What belongs here is the invariant they share with everything else: all four
carry **FORCEd deny-by-default RLS** — they are not tenant-scoped, so the policy is not
`tenant_id =` anything; the app role reaches them only through
`db/session.credential_session`, which is their sole opener.

## 3. Agents & Configuration

```
agents(id, tenant_id, name, direction ENUM[inbound,outbound,both],
  language_primary, languages_extra TEXT[],
  stt_provider, stt_model, tts_provider, tts_voice, llm_model,     -- config strings
  system_prompt_id → prompt_versions, extraction_schema_id → extraction_schemas,
  business_hours JSONB, escalation_config JSONB,
  -- THE OPENING NOTICES (D-163, migration f4a1d0b6e29c). SEC-COMP §2 states two
  -- invariants under two regimes — AI identification (TRAI/UCC) and a recording notice
  -- (DPDP §5/§6) — and they shared ONE column, so a client could have both or neither.
  -- The SENTENCES are mandatory (a dial is refused without an AI one); whether either is
  -- VOLUNTEERED at the top of a call is the tenant's own decision, per agent, inbound and
  -- outbound alike. What no column here can reach is the ANSWER to a caller who asks —
  -- `calevate_shared.engine.TRUTHFUL_ANSWER_DIRECTIVE`, which is deliberately not data.
  ai_disclosure_line TEXT NOT NULL CHECK (length(btrim(ai_disclosure_line)) > 0),
  recording_notice_line TEXT NOT NULL CHECK (length(btrim(recording_notice_line)) > 0),
  caller_memory_notice_line TEXT NOT NULL             -- D-507, migration e1a4d70c9b52
    CHECK (length(btrim(caller_memory_notice_line)) > 0),
  -- SENTENCE THREE HAS NO `*_enabled` COLUMN, and that is the decision rather than an
  -- omission: it is spoken exactly when `caller_memory_enabled` is true, so "remembers a
  -- caller and does not say so" is not a state this schema can hold. The two above are
  -- independently switchable (D-163) because their obligations hold whatever this product
  -- is configured to do; this one exists only because a switch we record is on.
  ai_disclosure_enabled BOOL NOT NULL DEFAULT true,
  recording_notice_enabled BOOL NOT NULL DEFAULT true,
  disclosure_line TEXT NOT NULL,  -- LEGACY: the two sentences joined, whatever the
    -- toggles say. Still written, no longer read by the publish path — step 1 of a
    -- two-step deprecation (hard rule 8); step 2 drops it (D-163).
  status ENUM[draft,live,paused,archived], engine ENUM[fake,bolna]  -- 'thinnest' REMOVED
    -- from the CHECK (D-31: retired before any adapter or production row existed, so the
    -- two-step deprecation in hard rule 8 does not apply — nothing ever wrote it)
  archived_at TIMESTAMPTZ,   -- e4b90d27c1f6. NOT a delete and not `deleted_at`: the row
    -- stays, its calls and leads stay readable, and the agent can be restored to `paused`.
    -- `ck_agents_archived_at_matches_status` is an EQUIVALENCE, not an implication —
    -- `(status = 'archived') = (archived_at IS NOT NULL)` — so neither half can be set
    -- without the other, in either direction. The transition table is
    -- `agents.lifecycle.AGENT_TRANSITIONS`; the DB CHECK is what makes it unbypassable.
    --, engine_agent_ref TEXT,
  engine_staging_ref TEXT, deleted_at,
  -- TWO-SPEED PUBLISHING: the `live_*` columns hold what the ENGINE was last SENT, which
  -- is a different fact from what the agent is configured with. A save stages; a publish
  -- is what moves the live pointer, so the pair can legitimately disagree and every
  -- screen that renders one of them has to say which one it is showing.
  live_prompt_id → prompt_versions,          -- a4e7b2c95d18
  live_tts_voice, live_tts_provider,         -- c8b3f14e7a29; NULL = nothing recorded as
                                             -- sent, never "in sync" (no backfill: see D-74)
  max_call_duration_s)                       -- the per-agent cost-runaway ceiling
prompt_versions(id, tenant_id, agent_id, version INT, body TEXT, compiled_t0_context TEXT,
  notes TEXT, created_by, published_at, UNIQUE(agent_id,version))   -- full history + rollback
  -- notes = operator-facing "why this version exists" ("rollback to v3", "new pricing").
  -- Deliberately NOT compiled_t0_context: that is a build artefact OF the version,
  -- reserved by D-39 for the T0 compiler.
extraction_schemas(id, tenant_id, agent_id, version INT, fields JSONB, published_at)
phone_numbers(id, tenant_id, agent_id, e164 UNIQUE, series ENUM[140,160,standard],
  provider, engine_number_ref, dlt_status ENUM[pending,registered,blocked], purpose TEXT)
  -- KNOWN UNMODELLED STATE, recorded rather than added: a Truecaller-verified number can
  -- enter "Delisting Pending" for 1-3 business days, during which "outbound and inbound
  -- calls on this number will be blocked"
  -- (bolna-findings/mirror/pages/guides/inbound/truecaller-verification.md:161,215).
  -- It is triggered by a click in a dashboard we do not own, with no webhook and no
  -- documented status field to read, and our dispatcher would keep handing the number to a
  -- campaign. The column is NOT extended for it: nothing is Truecaller-verified yet (the
  -- vendor does not publish the price), and a state we cannot observe is a lie in a column.
  -- Interim control is procedural — nobody delists a number attached to a live agent —
  -- and gate 27 asks whether GET /phone-numbers/all exposes any verification status at all.
```

`extraction_schemas.fields` shape (validated by Pydantic on write). `reason` is the
optional per-field free-text AI hint ("why this variable is needed"): it is fed to the
extractor to fill the field more accurately, and when empty the field name/label alone is
used.
```json
[
 {"key":"budget","label":"Budget","type":"number","reason":"Property budget in lakhs","required":true},
 {"key":"preferred_location","label":"Location","type":"text","reason":"Area/locality the caller wants","required":true},
 {"key":"bhk_size","label":"BHK","type":"enum","enum_values":["1BHK","2BHK","3BHK","4BHK+"],"required":false},
 {"key":"timeline","label":"Timeline","type":"text","reason":"When they intend to buy","required":false}
]
```
Vertical templates = seed rows (clinic: symptom, preferred_doctor, insurance, urgency,
preferred_slot; real_estate: above; insurance; education). The field list is editable by
the client (owner role, self-serve) AND by Calevate admins/superadmin (D-460, superseding
D-21's admin-only clause). Each save is live: it creates a new schema version used on the
next call; Leads render columns by the version active at extraction time (no data loss),
so history is preserved.

## 4. Calls & Transcripts

```
calls(id, tenant_id, agent_id, engine_call_id UNIQUE, direction, from_e164, to_e164,
  status ENUM[queued,ringing,in_progress,completed,failed,no_answer,busy,voicemail],
  started_at, ended_at, duration_s INT, recording_url TEXT,     -- OUR storage, not engine's
  disclosure_played BOOL, consent_recording ENUM[granted,declined,na],
  outcome_tag ENUM[resolved,needs_follow_up,transferred,dropped],
  sentiment ENUM[positive,neutral,negative], summary TEXT,
  campaign_id NULL → campaigns, lead_id NULL → leads,
  callback_of_call_id NULL → calls ON DELETE RESTRICT,   -- D-21 M2: the call this one
    -- follows up. Naming the parent is what BOUNDS the callback chain, and an unbounded
    -- chain is a compliance problem (repeat dialling), not a UX one.
  engine_payload_ref TEXT,             -- object-storage key of raw vendor payload (debug only;
                                       -- engine-payloads/{tenant}/{call}/…, so a DPDP erasure can
                                       -- enumerate it — D-126. Write the ref BEFORE the object.)
  recall_requested_at TIMESTAMPTZ,     -- the instant the big red switch asked the engine to drop
                                       -- this dial before it rang (D-432, migration d5c81f30ab47).
                                       -- NULL = never asked. The recall job does NOT settle the
                                       -- call: the reconciliation poller is the guarantee of
                                       -- record (D-31), so the row stays `queued` until the poller
                                       -- closes it, and this stamp is what stops a second halt
                                       -- re-POSTing a stop for every dial already stopped and then
                                       -- alarming about work that succeeded.
  erased_subject_ref TEXT)             -- the one-way handle a DPDP erasure leaves when it clears
                                       -- from_e164/to_e164 (D-310, migration c1e9a4f7d302). Those
                                       -- two columns are what the erasure LOCATES a subject's
                                       -- calls by, so without this an erased call is orphaned from
                                       -- its subject and records that arrive for it afterwards —
                                       -- a call still in flight when the erasure ran — can never
                                       -- be reached. Same construction as deletion_requests.
                                       -- subject_ref; written and read only by the erasure.
--   INDEX ix_calls_erased_subject_ref (tenant_id, erased_subject_ref) WHERE erased_subject_ref
--   IS NOT NULL — partial because the population is: only erased calls carry a value.
-- INDEX ix_calls_tenant_started (tenant_id, started_at DESC NULLS LAST, id DESC)
--   (migration c9e2a7b41d63). The calls list and the polled dashboard tiles order by exactly
--   this key; without it page 1 was a top-N heapsort of every call the tenant has
--   (38.953 ms / 1,770 buffers at 45,000 rows → 0.096 ms / 15). `NULLS LAST` is written out
--   because DESC defaults to NULLS FIRST, and an index declared the obvious way serves a
--   different ordering and brings the sort back.
transcript_turns(id, tenant_id, call_id, idx INT, speaker ENUM[agent,caller], text TEXT,
  text_redacted TEXT, lang TEXT, start_ms INT, end_ms INT, UNIQUE(call_id,idx))
  -- default read = text_redacted; raw `text` gated by role + audit_log
call_extractions(id, tenant_id, call_id, schema_version INT, data JSONB,
  model TEXT, prompt_version INT, valid BOOL, errors JSONB,
  UNIQUE(tenant_id, call_id))       -- ONE extraction per call (migration d3b71c9a5e08)
  -- Both readers already assumed it: the CRM detail takes `ORDER BY created_at DESC
  -- LIMIT 1` and the retention eraser rewrites "the" extraction for a call. The pipeline
  -- upsert closes the REPLAY case; only the constraint closes the RACE (an ARQ retry
  -- overlapping the reconciliation poller). Keyed on tenant_id FIRST so a unique
  -- violation is only ever reachable against a row your own RLS policy can see.
```

## 5. Leads (mini-CRM)

```
leads(id, tenant_id, agent_id, phone_e164, name, source ENUM[inbound_call,webhook,campaign,manual],
  status ENUM[new,contacted,interested,hot,won,lost], data JSONB,   -- keys per extraction schema
  schema_version INT, first_call_id, last_call_id, call_count INT, is_repeat_caller BOOL,
  assigned_to NULL → users, deleted_at, UNIQUE(tenant_id, phone_e164, agent_id))
-- INDEX ix_leads_tenant_recent (tenant_id, updated_at DESC, id DESC) WHERE deleted_at IS NULL
--   (migration c9e2a7b41d63). `list_leads_page` and the CSV export both take this ordering
--   and nothing in the schema knew it: page 1 was a top-N heapsort of the tenant's whole
--   lead table (28.454 ms / 1,668 buffers at 50,001 rows → 0.064 ms / 6, no sort node), and
--   the export's larger LIMIT SPILLED — 8,224 kB external merge to disk → no sort at all.
--   PARTIAL because `_lead_scope` opens with `deleted_at IS NULL` unconditionally.
lead_events(id, tenant_id, lead_id, type ENUM[status_change,note,call,notification], payload JSONB, actor)
```

## 6. Campaigns & Ingest

```
campaigns(id, tenant_id, agent_id, name, classification ENUM[promotional,transactional,service] NOT NULL,
  number_id → phone_numbers, dlt_template_id → dlt_templates,
  status ENUM[draft,scheduled,running,paused,completed,cancelled],
  schedule JSONB,   -- a ONE-TIME future start: {kind: 'one_time', start_at: <UTC ISO-8601>}
    -- plus an optional {last_blocked: {at, rules[]}} when the gate refused that start.
    -- `kind` is a discriminator, not decoration: recurrence is NOT built, and the
    -- dispatcher refuses any other value rather than firing it once (FLOWS §5).
    -- NULL = no pending start. Read only by apps/api/campaigns/scheduling.py.
  concurrency INT CHECK (1..10), retry_policy JSONB,   -- shipped default:
    -- {max_attempts: 3, backoff_minutes: [30, 120]} — this per-CONTACT ladder is the one
    -- place backoff actually exists; the ARQ job ladder is flat (FLOWS §6)
  calling_hours JSONB, engine_campaign_ref TEXT, launched_at,
  consent_source TEXT NULL CHECK (consent_source IS NULL OR consent_source IN
    ('existing_customer','inbound_enquiry','web_form_optin','offline_form_optin',
     'purchased_list')),
  consent_collected_at NULL,
  CHECK ((consent_source IS NULL) = (consent_collected_at IS NULL)))
  -- consent provenance for the LIST (SEC-COMP §3, migration b8e4c1d70f92): where these
  -- numbers came from and when. An enum, not free text, so the gate can refuse a value
  -- BY NAME (`consent_source_refused`) and the DPDP self-assessment is a GROUP BY.
  -- `purchased_list` is deliberately IN the enum — §3 promises a refusal in writing and
  -- a refusal can only be written if the client can say the word. Nullable with no
  -- backfill: a campaign predating the columns says NULL, which is the truth (nobody
  -- asked), and is BLOCKED at launch (`consent_provenance_missing`) rather than
  -- defaulted into a consent nobody gave. Answered afterwards through
  -- `POST /v1/campaigns/{id}/consent-provenance`, drafts only. Source and date travel
  -- together or not at all — a date with no source names nothing.
  -- launch is BLOCKED unless: entity DLT-registered, template approved, number series
  -- matches classification (140⇔promotional / 160|standard⇔service-transactional), DNC scrub done.
  -- dnc_scrubbed_at (migration a1c8e40f27b9): WHEN the tenant-list scrub ran, stamped by
  -- `launch_campaign` in the SAME statement as the transition to `running` — a second
  -- UPDATE would survive a CAS that lost its race and claim a scrub for a launch that
  -- never happened. It is the scrub timestamp SEC-COMP §3 promises for OUR half; the
  -- NATIONAL half's timestamp is the provider's, in `preference_scrub_runs.scrubbed_at`,
  -- because the two scrubs are run by different parties at different times. Nullable
  -- with no backfill: a campaign launched before the column has no honest answer.
campaign_contacts(id, tenant_id, campaign_id, phone_e164, name, custom JSONB,
  status ENUM[pending,dialing,connected,no_answer,failed,dnc_blocked,completed],
  attempts INT, last_attempt_at, next_attempt_at, last_call_id NULL → calls ON DELETE
  SET NULL, dedupe_hash, UNIQUE(campaign_id, phone_e164))
  -- next_attempt_at is what makes the per-CONTACT backoff ladder above real: the
  -- dispatcher claims "due pending contacts, oldest first" through
  -- INDEX ix_campaign_contacts_due (campaign_id, status, next_attempt_at).
  -- INDEX ix_campaign_contacts_last_call_id (last_call_id) WHERE last_call_id IS NOT NULL
  -- (migration c9e2a7b41d63). `_settle_contact` runs once per completed campaign call and
  -- its docstring promised "one indexed lookup and stops"; it reached the row through the
  -- tenant's whole contact list (4.700 ms / 650 buffers over 29,520 → 0.020 ms / 2).
dnc_list(id, tenant_id NULL, phone_e164, scope ENUM[global,tenant], source, added_at,
  CHECK ((scope='global' AND tenant_id IS NULL) OR (scope='tenant' AND tenant_id IS NOT NULL)),
  UNIQUE(tenant_id, phone_e164),
  UNIQUE INDEX uq_dnc_list_global_phone (phone_e164) WHERE tenant_id IS NULL)
  -- ASYMMETRIC RLS, the one deviation from the §1 pattern: the USING (read) clause also
  -- admits `tenant_id IS NULL` so a globally suppressed number is honoured for everyone,
  -- while WITH CHECK (write) admits a global row ONLY for a session carrying no
  -- `app.tenant_id` (migration a1c8e40f27b9) — a tenant must not be able to suppress a
  -- number for every other client, and that half is unchanged.
  -- `scope='global'` is an ABSOLUTE platform-wide suppression (a regulator/TSP
  -- instruction naming a number, or our own permanent refusal), written only by
  -- `POST /v1/ops/dnc/global` — step-up confirmed and audited. It is NOT the national
  -- customer preference register: NCPR preferences are category-scoped (a fully-blocked
  -- subscriber still receives transactional calls) and expire daily, so loading them
  -- here would refuse lawful traffic. That is `preference_scrub_runs` in §9.
  -- The PARTIAL unique index is the one that constrains global rows: NULLs are distinct
  -- in a unique index, so `UNIQUE(tenant_id, phone_e164)` never applied to them, and
  -- nothing noticed because until a1c8e40f27b9 nothing could write one.
inbound_webhooks(id, tenant_id, source ENUM[meta_lead_ads,website_form,zoho,sheets,custom],
  secret_ref TEXT, agent_id, mapping JSONB, active BOOL)   -- lead-in → instant call
outbound_webhooks(id, tenant_id, kind ENUM[webhook,google_sheets], url TEXT,
  secret_ref TEXT, events TEXT[],           -- e.g. {lead.created, lead.updated, call.completed}
  mapping JSONB, active BOOL)               -- us → client's tools (D-23); table ships in M1,
                                            -- delivery starts M2; HMAC-signed, our envelope;
                                            -- deliveries logged in webhook_deliveries(direction=out)
dlt_templates(id, tenant_id, kind ENUM[voice], classification, body TEXT,
  dlt_ref TEXT, status ENUM[draft,submitted,approved,rejected])
```

## 7. Knowledge Base (RAG)

> D-28 (Jul 2026): retrieval/memory moved to a managed third-party API service —
> `kb_chunks` + its indexes are now CONTINGENCY (built only if the D-28 bake-off
> fails). `kb_sources`/`kb_documents` (the approval workflow) and
> `kb_retrieval_logs` remain OURS regardless of provider; provider-side document/
> namespace ids are recorded in `kb_documents.meta`.
>
> D-33 (Aug 2026): **no table backs in-call working memory (H1)** — the engine holds the
> running dialogue for the call's duration and discards it at hangup, so there is nothing
> to persist mid-call. Its durable residue lands in the tables we already have via the
> post-call pipeline: `calls` (summary, sentiment, outcome_tag), `transcript_turns`,
> `call_extractions` → `leads` (H2).
> Cross-call caller memory (H3) is `caller_memories` + the `caller_memory` scope of
> `caller_chunks` (D-503), in OUR Postgres. ⚠ This line used to read "lives in the managed
> service, keyed back to our rows by provider ids in `meta`" — written under D-28, which
> D-502 reversed: there is no managed vector service. The instruction it carried is
> UNCHANGED and still binding — do not add a "conversation state" table; H1 has no table at
> all, because the engine holds the running dialogue and discards it at hangup.

```
kb_sources(id, tenant_id, agent_id, kind ENUM[file,url,text,call_corpus], name, uri,
  status ENUM[uploaded,parsed,pending_approval,approved,rejected,archived],
  submitted_by, approved_by, approved_at, rejection_reason, published_at,
  is_active BOOL, version INT, UNIQUE(agent_id, name, version))
  -- A named source is VERSIONED, and publish eligibility is `approved_at IS NOT NULL`,
  -- not `status = 'approved'`: FLOWS §7's rollback republishes a version that an earlier
  -- publish ARCHIVED, and gating on the current status refused the only rows the
  -- recovery path exists for. Rejection never stamps approved_at, so a rejected source
  -- still cannot reach an agent.
kb_documents(id, tenant_id, source_id, idx INT, title, content TEXT, meta JSONB,
  UNIQUE(source_id, idx))          -- idx = chunk order; the chunks ARE the document
  -- meta is where provider-side ids live (see the D-28 note above). Specifically
  -- `meta->>'engine_kb_ref'` on idx = 0 holds the ENGINE's handle for this source's
  -- attached copy — a source is pushed to the engine as one document, so the handle
  -- hangs off its first chunk. Without it a published version cannot be withdrawn
  -- (D-41); it is cleared on detach, because a handle left behind after the engine copy
  -- is gone would make the NEXT publish refuse for a reason that is no longer true.
kb_chunks(id, tenant_id, agent_id, source_id, document_id, tsv tsvector,
  embedding vector(1536), embed_model TEXT, embed_dim INT, embed_state TEXT,
  chunk_meta JSONB, version INT, is_active BOOL)   -- BUILT (D-502, migration dc1aaeeeff02)
-- INDEX: HNSW ON kb_chunks USING hnsw(embedding vector_cosine_ops) WITH (m=16,
--        ef_construction=64), built CONCURRENTLY; GIN(tsv);
--        (tenant_id, agent_id, is_active) btree; (tenant_id) WHERE embed_state='pending'.
-- FORCEd RLS `tenant_isolation`, in the same migration (hard rule 1).
-- FOUR DELTAS FROM THE CONTINGENCY SPEC ABOVE, each with a reason:
--  * NO `content` COLUMN. The client's prose lives once, on kb_documents, reached through
--    document_id. A second copy doubles what retention and backups pay for, gives a DPDP
--    erasure two rows to find, and lets a correction to one diverge from the other. What is
--    stored here is DERIVED and reconstructible, which is what makes the migration
--    reversible without loss.
--  * `vector(1536)` NOT `vector(1024)`: the width text-embedding-3-small is ASKED for
--    (`retrieval/embedding.EMBEDDING_DIMS`, sent as the request's `dimensions`), not a
--    vendor default anyone here has read. Not `halfvec`: that type needs pgvector 0.7.0 and
--    this server has 0.6.0 — and quantisation belongs in the INDEX (pgvector's own
--    half-precision indexing) rather than in a lossy column, which is also what keeps an
--    export to a managed vendor full-fidelity.
--  * `embed_state` replaces `embed_version`: it is the ingestion sweep's IDEMPOTENCY KEY
--    (pending/ready/refused), and `embedding IS NULL` cannot say "we asked and the answer
--    was unusable" — kb_documents.gloss_state's argument, one table over.
--  * `source_id` is denormalised beside `document_id`, because provenance on a result is
--    the SOURCE's own name — what the client called the thing they uploaded.
caller_chunks(id, tenant_id, subject_kind ENUM[lead,call_turn,call_summary,caller_memory],
  subject_id UUID, idx INT, call_id UUID NULL, agent_id UUID, subject_ref TEXT,
  subject_ref_kek_id INT, first_turn_idx INT NULL, last_turn_idx INT NULL,
  retention_category ENUM[transcript,lead], occurred_at TIMESTAMPTZ, tsv tsvector,
  embedding vector(1536), embed_model TEXT, embed_dim INT, embed_state TEXT,
  content_sha256 TEXT, scrubbed_at TIMESTAMPTZ NULL)  -- BUILT (D-503, migration c6b1f0d47e83)
-- `kb_chunks` above, pointed at a DATA PRINCIPAL's words instead of a client's own
-- document. Same column types, same indexes (HNSW m=16/ef_construction=64 CONCURRENTLY,
-- GIN(tsv), a partial index on the pending backlog), same FORCEd RLS, same "no content"
-- rule. THE DIFFERENCE IS THE ERASURE SEAM, and it is the whole reason this is a second
-- table rather than three more columns:
--  * `kb_chunks` erases by CASCADE, which is sound ONLY because retention really DELETEs a
--    kb_sources row. A DPDP erasure does NOT delete a call — it scrubs it in place and
--    keeps the row as billing evidence (usage_events references it, FK RESTRICT) — so a
--    cascade on call_id NEVER FIRES. `retrieval/caller_erasure.py` is the explicit arm,
--    called from execute_deletion_request, execute_tenant_erasure and the nightly sweep.
--  * A SCRUBBED ROW IS KEPT AND EMPTIED, never deleted: the ingestion sweep discovers
--    un-projected subjects, so a deleted row would be re-projected next tick and a vector
--    re-bought for text the erasure had just destroyed. `scrubbed_at` is the tombstone and
--    `ck_caller_chunks_forgotten_has_no_keys` makes "no vector AND no lexemes" a database
--    constraint rather than a convention in a worker.
--  * `subject_ref` is `compliance/caller_ref`'s KEYED MAC of (tenant, E.164) under a
--    PLATFORM_KEK-derived key — NOT export.subject_ref, which is unsalted over a ~10^9
--    space and takes no tenant into the input. `subject_ref_kek_id` bounds the ring walk an
--    erasure does, so a KEK rotation cannot hide a row from a §12 request.
--  * ONE TABLE, THREE SCOPES. `subject_id` is an IDEMPOTENCY KEY and never a foreign key:
--    a transcript chunk windows several turns (which retention may DELETE), a lead yields
--    several chunks from one payload, and a caller memory derives from no single row.
--  * `retention_category` is set by the projection registry from
--    `retrieval/models.SUBJECT_RETENTION`, so a scope cannot file a caller's sentence on
--    the 1095-day CRM clock by calling itself a lead. Both values are real
--    `retention_policies` categories with real sweep arms; there is no new category.
caller_memories(id, tenant_id, agent_id, subject_ref TEXT, subject_ref_kek_id INT,
  fact TEXT, source_call_id UUID NULL, occurred_at TIMESTAMPTZ,
  scrubbed_at TIMESTAMPTZ NULL)  -- BUILT (D-503, migration c6b1f0d47e83)
-- The SOURCE caller_chunks projects for the caller_memory scope, because a content-free
-- projection cannot be a distilled fact's home. FORCEd RLS; `source_call_id` is PROVENANCE
-- with ON DELETE SET NULL and is explicitly NOT the erasure path (the row outlives the call
-- it was learned on, which is the feature); `occurred_at` comes from the source call's end
-- and NOT created_at, or a backfill would restart every caller's retention clock. Gated by
-- `agents.caller_memory_enabled`, DEFAULT FALSE — the opposite of the disclosure toggles,
-- because the posture a silence must not produce here is "remembers".
-- ITS PRODUCER AND ITS SWITCH LANDED IN D-509: `calls.caller_memory_state`
-- (pending|remembered|nothing|skipped, migration a1f6c30d92be) is the distiller's
-- idempotency marker, and the THIRD value is why it exists — `source_call_id` can record
-- that a call produced a fact and can never record that a call was read and owed nothing,
-- which is what most calls owe, so without it a retry re-buys the same answer.
-- `organizations.caller_memory_attested_at`/`_attested_by` is the per-tenant permission
-- the enable route requires: on the ORGANISATION because the attested fact is about the
-- business, so a client with four agents answers once.

scheduled_callbacks(id, tenant_id, agent_id, source_call_id UUID NULL,
  source_execution_id TEXT, lead_id UUID NULL, phone_e164 TEXT,
  requested_at TIMESTAMPTZ, booked_at TIMESTAMPTZ,
  status ENUM[scheduled,dialing,completed,cancelled,refused,missed,failed],
  attempts INT, next_attempt_at TIMESTAMPTZ NULL,
  last_refusal_rule TEXT NULL, last_refusal_reason TEXT NULL,
  last_call_id UUID NULL, settled_at TIMESTAMPTZ NULL,
  note TEXT NULL, language TEXT NULL)  -- BUILT (D-510, migration d8f31a7c2409)
-- "Ring me back Tuesday at four", booked by the in-call tool and dialled by the campaign
-- tick through `dispatch_call` — the one outbound entry point, which is what makes a
-- call-back inherit the DLT header, the A/B arm and cross-call memory without knowing they
-- exist. FORCEd RLS.
-- THE IDENTITY IS `(tenant_id, source_execution_id)`, not the call: the `calls` row is
-- written by the status webhook and may not exist when the promise is made, so
-- `source_call_id` is a nullable POINTER. The upsert is guarded by `booked_at` rather than
-- DO NOTHING, because "make it five, not four" is an ordinary sentence and two jobs racing
-- must land on the caller's LATER word.
-- `requested_at` IS WHAT THE CALLER WAS TOLD AND NEVER MOVES. A transient refusal defers
-- `next_attempt_at`; the first draft moved `requested_at` and the two-hour staleness cutoff
-- then receded by five minutes every five minutes, which is the livelock class
-- `tests/dispatch_refusal_settlement_test.py` exists for.
-- FIVE OF THE SEVEN STATUSES ARE ENDINGS, and `last_refusal_reason` carries the compliance
-- gate's OWN client-facing sentence for the two that are refusals — so the client's screen
-- says why a call they were promised did not happen, in the words the dial button would
-- have shown them.
kb_retrieval_logs(id, tenant_id, call_id, query, tier ENUM[t0,t1,t2,t3,t4],
  top_score REAL, latency_ms INT)   -- powers knowledge-gap reports
  -- `top_ids UUID[]` was specified here and is NOT in the shipped table. Its stated
  -- condition — "add it with the chunks" — is now MET (D-502), but the blocker was never
  -- the chunks: this table still has no producer and cannot have one (see
  -- `apps/api/kb/models.py::KbRetrievalLog`), because the retrieval whose outcome it would
  -- log happens inside the engine. Add it with a PRODUCER, or not at all.
```

## 8. Billing & Metering (append-only)

```
usage_events(id, tenant_id, call_id NULL, unit_type ENUM[telephony_s,stt_s,tts_chars,
  llm_tok_in,llm_tok_out,platform_min,number_rental,other], qty NUMERIC, unit_cost_paid NUMERIC,
  occurred_at, meta JSONB)                          -- INSERT-only; no UPDATE/DELETE grants
-- INDEX ix_usage_events_call_id (call_id) WHERE call_id IS NOT NULL (c9e2a7b41d63). The
--   post-call metering guard, `_pipeline_settled`'s EXISTS and the unmetered-calls panel all
--   probe by call; offered only `tenant_id` each was a scan of the tenant's ENTIRE metering
--   history to find at most five rows (25.794 ms / 3,617 buffers at 225,000 → 0.024 ms / 4).
--   PARTIAL because `number_rental` and the `ai_assist_*` units carry no call — and a partial
--   index still serves the FK check, since `call_id = $1` under a strict operator proves the
--   predicate.
-- INDEX ix_usage_events_tenant_occurred (tenant_id, occurred_at) (c9e2a7b41d63). Every money
--   rollup is "this tenant, this month" (33.788 ms / 3,822 buffers → 2.058 ms / 74). It is
--   also what made the month predicate indexable AT ALL: `to_char(... ) = :month` is STABLE,
--   so it can be neither an index condition nor an index expression, and
--   `plans.ist_month_window` now hands SQL a half-open range instead (D-209).
plans(id, tenant_id, setup_fee, monthly_fee, included_min INT, overage_rate,
  overage_rate_value NUMERIC NULL, hard_cap_min INT, hard_cap_spend NUMERIC,
  client_cap_min INT NULL, client_cap_spend NUMERIC NULL,
  concurrency_ceiling INT DEFAULT 10, effective_from, effective_to)
  -- `overage_rate_value` prices D-36's value TTS rung; NULL means the plan quotes no
  -- separate value rate and everything bills at `overage_rate` (migration b1d5c8e73f04).
  -- `client_cap_*` are the CLIENT's own ceilings beside the admin's `hard_cap_*`; the
  -- effective cap is LEAST(admin, client), DERIVED and never stored, so clearing the
  -- client's own lands back on the admin's rather than on unlimited (billing/caps.py).
  -- WHICH ROW IS IN EFFECT (D-46). `effective_from`/`effective_to` are the row's VALID
  -- TIME, and every money reader resolves through ONE helper,
  -- `billing/plans.plan_in_effect_sql` — the invoice, the usage panel, both cap reads,
  -- the worst-case call-cost quote and the dispatch concurrency ceiling. The period is
  -- HALF-OPEN, `effective_from <= at < effective_to` (SQL:2011 application-time
  -- semantics), so `old.effective_to = new.effective_from` is exactly right with no gap
  -- and no instant priced twice. `at` is passed in and is NOT always now: a closed month
  -- prices at its last instant (which is what makes the derived invoice re-renderable), a
  -- future month at its first. NULL bounds are not a defect — "since forever" and "until
  -- further notice" is what an open-ended retainer is — so overlap is resolved by a TOTAL
  -- ORDER rather than forbidden by an EXCLUDE constraint (declined: every row today is
  -- NULL/NULL and mutually overlapping, and `caps.apply_client_caps` mints a windowless
  -- row for a tenant with no plan): latest `effective_from` (NULL as -infinity), then
  -- `created_at DESC, id DESC`. With every window NULL that collapses to the newest-row
  -- rule this repo had before. A tenant with plan rows and none in effect is UNPRICED —
  -- no fee, no included minutes, no rate, no ceiling — deliberately, and logs
  -- `plan_window_leaves_tenant_unpriced`; falling back to the expired row would charge a
  -- client at terms whose end date we were told.
credit_ledger(id, tenant_id, delta NUMERIC, reason ENUM[topup,usage,adjustment,refund],
  ref, balance_after, occurred_at, meta JSONB)          -- INSERT-only (hard rule 4)
-- INDEX ix_credit_ledger_tenant_recent (tenant_id, occurred_at DESC, id DESC)
--   (migration a6f2e84b1d37). The balance is NOT an aggregate — that is why
--   balance_after is denormalized — so every read is `ORDER BY occurred_at DESC,
--   id DESC LIMIT 1` on the pre-dispatch path. The `id DESC` tail is load-bearing:
--   occurred_at is stamped with clock_timestamp(), so "newest" must be a TOTAL order or
--   two readers disagree about which row it is.
-- DROPPED: ix_credit_ledger_tenant_id (migration e7c3d10a9f52) — step two of the
--   two-step a6f2e84b1d37 opened (hard rule 8), taken only once the composite had been
--   observed carrying real plans. It was a STRICT PREFIX of the composite, so every
--   query in the repo that touches credit_ledger was EXPLAIN ANALYZEd on a loaded
--   database before and after: no node type changed and nothing fell back to a seq
--   scan; each plan simply names the composite where it named the prefix. It costs 2
--   more shared buffers per bitmap scan and buys an append-only table one insert-time
--   index instead of two (~7% faster over 200k appends), which is the trade worth
--   making on a table where no UPDATE ever repays the write. The model's `index=True`
--   went with it — leaving it would have had the next autogenerate helpfully recreate
--   the index, a deprecation that un-deprecates itself.
-- INDEX ux_credit_ledger_tenant_reason_ref UNIQUE (tenant_id, reason, ref)
--   WHERE ref IS NOT NULL AND reason IN ('topup','usage','adjustment')
--   AND occurred_at >= <the migration's own timestamp> (f9c2b41a8e57). Four earlier
--   attempts proposed UNIQUE(tenant_id, ref) and argued about the PREDICATE; the KEY was
--   the wrong shape. `ref` is two namespaces in one column — a `usage` row carries a call
--   id, a `topup` row carries whatever the bank printed — and the system TOLERATES that
--   collision in three places deliberately, so the old key would have turned a
--   defended-against collision into a 500 on a valid payment. The cutoff is because the
--   ledger is append-only and the pre-existing violating pairs are real double-credits
--   that hard rule 4 makes permanent: they are corrected by compensating entries
--   (`scripts/reconcile_credit_ledger.py`, dry-run by default, `--apply` to write,
--   through `record_entry` under the tenant credit lock — never an UPDATE or DELETE),
--   not by deleting money rows. Consequence for developers: a database carrying that
--   residue cannot reach head — `runbooks/stale-dev-database.md`, and do not stamp past
--   it.
one_time_charges(id, tenant_id, kind ENUM[setup_fee], ref, description, amount NUMERIC,
  billing_month, plan_id NULL, occurred_at)          -- INSERT-only (hard rule 4)
-- INDEX ux_one_time_charges_tenant_kind_ref UNIQUE (tenant_id, kind, ref)
--   (migration c7e1a4b90d63). What a charge billed ONCE actually is: `plans.setup_fee`
--   reaches a client through this ledger and nowhere else. The writer
--   (apps/api/billing/charges.py) does an unconditional INSERT … ON CONFLICT DO NOTHING,
--   so regeneration of a derived invoice, a plan change, a re-onboarding and two
--   concurrent generations all resolve to the same one row — there is no read-then-write
--   to lose a race (BACKEND-PATTERNS §5). `ref` is in the key so a fee that must be
--   undone is a NEW row with a negative amount under its own ref (hard rule 4's
--   compensating entry), which the same invoice prints as a credit line.
--   `billing_month` is WHICH STATEMENT the charge belongs to — the tenant's onboarding
--   month, i.e. the IST month of organizations.created_at — and is not derivable from
--   `occurred_at`, which is the (later) moment that month's invoice was first rendered.
--   `amount` is the fee AS BILLED, copied from the plan in effect at that month's
--   pricing instant: `plans` is mutable, so a re-derived amount could change a statement
--   the client already paid.
spend_state(tenant_id PK, month, minutes_used NUMERIC, spend_used NUMERIC, capped BOOL)
  -- read by the COMPLIANCE GATE before every outbound dispatch (fail closed when capped)
  -- — apps/api/compliance/service.py, not voice-runtime; see TRD §9

-- ── NOT YET CREATED. Still intended; kept here so the intent is not lost, but do NOT
-- ── read the two blocks below as shippable schema.
engine_capacity(id PK=1, platform_lines_total INT, inbound_reserve INT,
  sarvam_concurrency INT, trunk_channels INT, updated_at)
  -- singleton config; effective outbound pool = MIN(all three) − inbound_reserve;
  -- values come from verification item 8, reviewed on any vendor plan change.
  -- SHIPPED INSTEAD (M1): the dispatcher holds ONE constant, PLATFORM_LINES_TOTAL = 10
  -- (with MIN_INBOUND_RESERVE = 4) in apps/workers/campaign_dispatch.py — deliberately a
  -- constant until the pilot produces real numbers, so the measured value has exactly one
  -- place to land. The table lands when there is more than one number to store.
  -- ⚠ THE PILOT IS NOT NEEDED FOR THE FIRST OF THOSE NUMBERS AND THIS COMMENT USED TO
  -- IMPLY IT WAS: the vendor publishes the account's ceiling on a read endpoint —
  -- GET /user/me returns concurrency:{max,current}
  -- (bolna-findings/mirror/pages/api-reference/user/info.md:78-87) — and the paid tier
  -- "scal[es] automatically with monthly usage" (pricing/outbound-calling-concurrency.md:19),
  -- so a correct constant decays without a deploy. inbound_reserve is a separate question
  -- and a live one: their docs say inbound is never queued or restricted at all, which
  -- would make the reserve free throughput — pilot gate 13, FLOWS §5, do NOT act on prose.
invoices(id, tenant_id, period, lines JSONB, subtotal, gst, total,
  status ENUM[draft,sent,paid,overdue], razorpay_ref)
  -- SHIPPED INSTEAD (M2): an invoice is a DERIVED STATEMENT, not a row. `build_invoice`
  -- (apps/api/billing/invoice.py) computes it from usage_events + plan on request and
  -- persists nothing. That is WHY the invoice number can be deterministic
  -- (CAL-{YYYYMM}-{first 8 hex of tenant_id}): with no stored row there is no sequence to
  -- collide with, and regenerating a month can never mint a second number for it.
  -- This table lands only when an invoice acquires state we cannot derive (sent/paid/
  -- overdue, razorpay_ref) — i.e. with collection, not with the statement.
  -- The one fact a derived statement could NOT re-derive — "this tenant's one-time
  -- onboarding fee has been billed" — lives in `one_time_charges` above rather than
  -- forcing this table to exist early (D-63).
```

## 9. Compliance & Audit

```
preference_scrub_runs(id, tenant_id → organizations ON DELETE RESTRICT,
  campaign_id → campaigns ON DELETE SET NULL, provider TEXT, scrub_ref TEXT,
  scrubbed_at, expires_at, submitted_count INT, suppressed_count INT,
  recorded_by_admin_id → admin_users NULL, recorded_at,
  UNIQUE(campaign_id, provider, scrub_ref),
  CHECK (length(btrim(provider)) >= 2), CHECK (length(btrim(scrub_ref)) >= 3),
  CHECK (submitted_count >= 0),
  CHECK (suppressed_count >= 0 AND suppressed_count <= submitted_count),
  CHECK (expires_at > scrubbed_at))
  -- The NATIONAL half of SEC-COMP §3's DNC bullet (migration a1c8e40f27b9). The
  -- customer preference register is not obtainable — it lives on the access providers'
  -- DLT platform, which scrubs a SUBMITTED list and returns a reference, a count and a
  -- verdict valid to 23:59:59 that day — so the durable fact is a RUN, not a row per
  -- number. Read by `compliance.preference_scrub.national_dnd_blocker` as
  -- `national_dnd_scrub_missing` / `_expired` / `_incomplete`, asked by BOTH
  -- `launch_blockers` and `dispatch_blockers` because the window closes at midnight IST
  -- while a campaign keeps dialling. Promotional campaigns only: under full DND every
  -- category is blocked except service-implicit and transactional traffic is delivered
  -- regardless, so gating those would suppress calls the subscriber is entitled to.
  -- COUNTS ONLY — no phone number is stored (hard rule 6); the numbers the register
  -- blocked become `campaign_contacts.status='dnc_blocked'`, never `dnc_list` rows,
  -- because a preference blocks a CLASS of traffic today and does not suppress the
  -- person forever. INSERT-only (`APPEND_ONLY_TABLES`) with ONE bounded exception the
  -- trigger names: `ON DELETE SET NULL` on `campaign_id` is executed by Postgres as an
  -- UPDATE, and a blanket trigger would make a scrubbed campaign undeletable forever.
  -- Standard §1 RLS created with the table.
dlt_registrations(id, tenant_id UNIQUE → organizations ON DELETE RESTRICT, pe_id TEXT,
  entity_name TEXT, status ENUM[not_started,submitted,active,suspended,rejected]
  NOT NULL DEFAULT 'not_started',
  tm_link_status ENUM[not_linked,pending,active,revoked] NOT NULL DEFAULT 'not_linked',
  registered_at, verified_at,
  CHECK (status <> 'active' OR (pe_id IS NOT NULL AND registered_at IS NOT NULL)))
  -- The CLIENT half of SEC-COMP §3's first bullet: the DLT Principal Entity, read by
  -- `launch_blockers` as `pe_registration_missing` / `pe_registration_not_active` /
  -- `tm_link_not_active`. The THIRD registration in the family — the header
  -- (`phone_numbers.dlt_status`) and the voice template (`dlt_templates.status`) are the
  -- other two, and none implies another. PE status and TM-link status stay two columns
  -- because they fail separately and the client's next action differs. Mutable by
  -- design (a registration is suspended and restored over its life); who changed it is
  -- `audit_log`'s job. Standard §1 RLS, created in migration c5a930e6b1d4 with the
  -- table. `verified_at` = when WE last confirmed it with the registrar.
kyc_records(id, tenant_id UNIQUE → organizations ON DELETE RESTRICT,
  status ENUM[not_started,submitted,in_review,verified,rejected,expired] NOT NULL
    DEFAULT 'not_started',
  entity_type ENUM[sole_proprietorship,partnership,llp,private_limited,public_limited,
    trust_or_society,huf] NULL,
  document_kind ENUM[cin,llpin,gstin,udyam,shop_establishment,trade_licence] NULL,
  document_ref TEXT NULL, signatory_name TEXT NULL, evidence_ref TEXT NULL,
  rejection_reason TEXT NULL, verified_by_admin_id → admin_users NULL,
  submitted_at, verified_at,
  CHECK (status <> 'verified' OR (document_kind IS NOT NULL AND document_ref IS NOT NULL
         AND verified_by_admin_id IS NOT NULL AND verified_at IS NOT NULL)),
  CHECK (status <> 'rejected' OR rejection_reason IS NOT NULL),
  CHECK (document_ref IS NULL OR document_ref !~ '^[0-9]{12}$'))
  -- Subscriber KYC (D-47, migration a3f6b1e02d95): the fact that a person at Calevate
  -- verified this BUSINESS's identity, against a named public-registry document, on a
  -- date, with the pack filed under a reference. Read by `compliance.service.kyc_blocker`
  -- as `kyc_missing` / `kyc_not_verified` — the DIAL gate for `self_serve`/`trial` only,
  -- the NUMBER-PURCHASE gate for every tier. Mutable and one row per tenant for the same
  -- reason as `dlt_registrations`: a verification is cleared, expires and is withdrawn
  -- over its life, and the gate reads current state on every dial; `audit_log` holds who
  -- changed it. Standard §1 RLS created with the table.
  -- The three CHECKs are the three questions, made unstorable-if-unanswered: an auditor's
  -- (what, against what, by whom, when), a support person's (why is this blocked), and
  -- DPDP's. NEVER the document itself — `document_kind` names ENTITY registries only, so
  -- nothing here identifies a natural person; `evidence_ref` is a reference to where the
  -- pack is filed (the discipline `outbound_webhooks.secret_ref` uses for credentials);
  -- `signatory_name` is a name with no identity-document number beside it. The 12-digit
  -- regex is a backstop, not the control: no permitted registry id is 12 bare digits, so
  -- an Aadhaar pasted into a business field fails at the moment of the mistake.
  -- Deliberately does NOT duplicate `dlt_registrations.pe_id` — overlapping evidence, two
  -- regimes, different holders.
first_campaign_reviews(id, tenant_id UNIQUE → organizations ON DELETE RESTRICT,
  status ENUM[approved,rejected] NOT NULL,
  reviewed_campaign_id → campaigns ON DELETE SET NULL,
  decision_note TEXT NOT NULL, decision_source ENUM[operator,migration_backfill] NOT NULL
    DEFAULT 'operator',
  decided_by_admin_id → admin_users NULL, decided_at NOT NULL,
  CHECK (decision_source <> 'operator' OR decided_by_admin_id IS NOT NULL),
  CHECK (length(btrim(decision_note)) >= 3))
  -- R-11's manual review of a self-serve account's FIRST campaign (D-51, migration
  -- c4d9e18a72b6). One mutable row per tenant, standard §1 RLS created with the table.
  -- READ THE ABSENCE: there is no `pending` status and no row until a human decides, so
  -- "no row" IS held. A stored `pending` would be a second representation of one fact
  -- that can disagree with the absence, and the reader fails CLOSED to held on an
  -- unscoped session (the shape `kyc.NOT_RECORDED` uses).
  -- The hold is on the ACCOUNT, which is the whole design: a `campaigns.review_required`
  -- flag is defeated by launching a second campaign or deleting the flagged one, and
  -- neither is an attack. `reviewed_campaign_id` is therefore EVIDENCE of what an
  -- operator read — SET NULL on delete, because losing the pointer must not change
  -- whether the account is cleared.
  -- Read by `compliance.service.first_campaign_hold_blocker` as
  -- `first_campaign_review_pending` / `first_campaign_review_rejected`, asked by BOTH
  -- `launch_blockers` and `dispatch_blockers` (so a withdrawn release stops a RUNNING
  -- campaign) and deliberately NOT by `check_dispatch`, which also serves the D-21
  -- single-lead button. Mutable and absent from APPEND_ONLY_TABLES for the same reason as
  -- `kyc_records` and `dlt_registrations`: this is current state, and the immutable
  -- history is `audit_log`. `decision_source` keeps the migration's grandfathering
  -- honest — self-serve tenants that had already launched are backfilled as
  -- `migration_backfill`, so a NULL decider is self-describing rather than an anonymous
  -- release, and the CHECK makes an operator release that cannot name its operator
  -- unstorable.
consent_ledger(id, tenant_id, call_id, phone_e164,
  purpose ENUM[recording,callback,marketing,messaging],
  status ENUM[granted,declined,withdrawn], captured_at, evidence JSONB,
  consent_source ENUM[inbound_call_verbal,web_form_optin,offline_form_optin,
    whatsapp_inbound_message,staff_recorded_request] NULL)   -- immutable
  -- `messaging` + `consent_source` land in migration c2f7a91b4e63. It is the purpose
  -- that governs BUSINESS-INITIATED messaging (the WhatsApp campaign follow-up,
  -- FLOWS §4.5), and it is deliberately NOT derivable from anything else: consent to be
  -- CALLED is not consent to be MESSAGED, so nothing was backfilled and no code path
  -- converts a `callback` or `recording` row into a `messaging` one.
  -- CHECKs, all in that migration: a `messaging` row must name its `consent_source`; a
  -- `granted` row must carry `evidence`, must not come from `staff_recorded_request`
  -- (a client's staff may record an opt-OUT, never an opt-IN) and must name its
  -- `call_id` when the source is `inbound_call_verbal`. There is deliberately no
  -- `assumed`/`implied` member — an unevidenced grant is unrepresentable, not merely
  -- discouraged.
  -- INDEX ix_consent_ledger_messaging_lookup (tenant_id, phone_e164, captured_at DESC,
  --   created_at DESC) WHERE purpose = 'messaging' — the latest-row-wins read in
  --   `apps/api/compliance/consent.py`, index-only and never sorting.
  -- Append-only (hard rule 4): a withdrawal is a NEW row that supersedes, never an
  -- UPDATE, and the read honours a validity window
  -- (`MESSAGING_CONSENT_VALIDITY_DAYS`) so a stale opt-in stops authorising messages
  -- while remaining in the ledger as evidence of what happened.
retention_policies(id, tenant_id,
  data_category ENUM[recording,transcript,lead,consent_log,engine_payload,kb,copilot_memory,
                     caller_memory],
  ttl_days INT CHECK (ttl_days >= 90 WHERE data_category='recording'),   -- TRAI 90-day floor
  action ENUM[delete,anonymize])
  -- SEEDED defaults (`scripts/seed.DEFAULT_RETENTION_POLICIES`): recording 90/delete,
  -- transcript 365/anonymize, lead 1095/anonymize, consent_log 2555/anonymize,
  -- engine_payload 90/delete, kb 365/delete, copilot_memory 180/delete,
  -- caller_memory 180/delete (D-507). These
  -- do NOT match the numbers SEC-COMP §4 prints — see the open question recorded there;
  -- the DPA quotes the doc and the sweep obeys these rows.
  -- engine_payload and kb are D-179 (migration c4d1f7b83e26), and each gave a clock to a
  -- store of personal data that sat outside every policy a tenant could set:
  -- `calls.engine_payload_ref`'s archived vendor document, and SUPERSEDED knowledge-base
  -- versions. `action` is not read on either — an opaque vendor document and a chunk of
  -- prose have no anonymized form — so an `anonymize` row on those two destroys.
  -- copilot_memory is the in-app assistant's memory (migration d4a9c17e6b02): what a
  -- client's own STAFF asked the copilot, and the facts a background worker distilled out
  -- of it. `action` is not read there either, for the `kb` reason. 180 days, shorter than
  -- the transcript clock, because nothing depends on the rows — they are working context,
  -- regenerated by use, and the client bought none of it. Deliberately ABSENT from
  -- `compliance/caller_notice._CATEGORY_LABELS`: that generates a document for the
  -- client's CALLERS, who are not the subject of this data.
  -- `campaign_contact` is deliberately NOT here: an uploaded contact list has no clock
  -- either, and how long a client's own list is kept is a DPA commitment whose number is
  -- the founder's (`tests/dpdp_known_gaps_test.py` probes this constraint to hold that
  -- gap open).
  -- The sweep also ages out the DERIVED copies of the same personal data, classified by
  -- WHAT THEY ARE and then timed by the tenant's own policy row
  -- (`workers/retention.DERIVED_COPIES`): `calls.summary` is a retelling of the
  -- conversation, so it runs on the TRANSCRIPT clock; `call_extractions.data` is
  -- structured CRM of the same class as `leads.data`, so it runs on the LEAD clock and
  -- deliberately outlives the transcript. Nothing personal outlives its category, and
  -- no CRM field is deleted earlier than the category the client agreed to.
deletion_requests(id, tenant_id, phone_e164 NULL, subject_ref TEXT NOT NULL, scope,
  requested_at, completed_at, proof JSONB,           -- deletion-with-proof (DPDP)
  CHECK (completed_at IS NOT NULL OR phone_e164 IS NOT NULL),   -- an OPEN request
    -- always names its subject: it is the worker's only handle on them
  CHECK (subject_ref IS NOT NULL))
-- UNIQUE INDEX uq_deletion_requests_open_subject (tenant_id, phone_e164)
--   WHERE completed_at IS NULL (migration e2c47b90d5a1) — one OPEN request per subject.
--   The predicate is the point: erasure is not terminal for a phone number, so a second
--   genuine request next month must still be possible. Leading with tenant_id keeps a
--   unique violation reachable only against a row your own policy can see.
-- INDEX ix_deletion_requests_tenant_subject (tenant_id, subject_ref).
  -- phone_e164 is nullable since migration f4a8e1c07b62 (D-44) and is CLEARED in the
  -- same UPDATE that stamps completed_at + proof, so a completed request is no longer
  -- the last surviving copy of the number it certifies as erased — no retention policy
  -- sweeps this table. It cannot be cleared earlier: the worker resolves the subject
  -- FROM the row. The column is NOT dropped (hard rule 8, two-step).
  -- subject_ref = sha256(number)[:32], the identical construction to the erasure
  -- proof's `subject_hash` and the subject-access export's `subject_ref`, which is why
  -- all three line up. It answers "have we already erased this person?" to a reader who
  -- already holds the number, and nothing to one who does not. A BEFORE INSERT trigger
  -- (`deletion_requests_subject_ref`) fills it from phone_e164 when the writer did not,
  -- and never overwrites — the application stays the author, the trigger is the floor.
audit_log(id, actor_type ENUM[admin,user,system], actor_id, tenant_id, action, object_type,
  object_id, ip, at, prev_hash, entry_hash)          -- INSERT-only; includes recording/
  -- raw-transcript reads. prev_hash/entry_hash are the D-30 hash chain: each entry
  -- commits to its predecessor, so a deleted or edited row breaks verification
  -- (`GET /v1/ops/audit/verify`) instead of disappearing quietly.
webhook_deliveries(id, direction ENUM[in,out], source, event_type, status, attempts,
  signature_valid BOOL, payload_ref, endpoint_id NULL → outbound_webhooks ON DELETE SET NULL,
  first_at, last_at)                 -- ONE row per delivery, not per attempt
  -- endpoint_id is outbound-only (D-23) and is how the client-facing delivery screen
  -- scopes rows: it filters THROUGH outbound_webhooks, which IS tenant-RLS'd, so this
  -- table needs no policy of its own.
  -- payload_ref (outbound) is the object-storage key of the BODY we POSTed:
  --   webhook-bodies/{tenant}/{lead|call}-{id}/{delivery}.json. It is personal data, so
  --   it comes with the three things personal data needs. ERASABLE: the subject is in
  --   the key, so the DPDP worker enumerates the store by prefix and finds even an
  --   object whose row never recorded the reference. EXPIRING: the retention sweep runs
  --   it on the tenant's own `lead` policy, the same clock as call_extractions.data
  --   (SEC-COMP §4). BOUNDED: 64 KiB per delivery, truncation declared inside the
  --   object. An event that names no subject (campaign.completed) is NOT retained —
  --   we keep nothing we could not later be asked to destroy. Storage is best-effort
  --   and never blocks a delivery, so NULL means "no copy", by any of four honest
  --   routes; the client-facing list exposes that as a boolean, never the key.
  -- INDEX ix_webhook_deliveries_retained_body (created_at) WHERE payload_ref IS NOT NULL
  --   (migration b3d61f0a97c4) — partial, because the sweep clears references and no row
  --   ever regains one, so the population it serves is the small live tail.
-- Reliability triad (D-30, BACKEND-PATTERNS §4; all claims via conditional-UPDATE CAS):
outbox_messages(id, queue, job, payload JSONB, status ENUM[pending,published,failed],
  attempt_count INT, locked_until, job_id, published_at, last_error)  -- written in the
  -- SAME txn as the domain write; ARQ dispatcher polls oldest-first; >=5 attempts ->
  -- failed(DLQ). INDEX ix_outbox_pending (status, created_at) serves the claim.
  -- locked_until = the claim LEASE (D-42, migration 7c04ab5f9e26), nullable: NULL means
  -- never claimed or the claim is resolved. It exists because the attempt bump has to
  -- COMMIT to survive a SIGKILL, and committing releases the FOR UPDATE locks — so
  -- exclusivity moves onto the row. Claim predicate: `status = 'pending' AND
  -- (locked_until IS NULL OR locked_until <= now())`. A lapsed lease needs no reaper;
  -- status keeps its three values, so every existing reader stays correct.
webhook_inbox_events(id, provider, event_key, payload_hash, status
  ENUM[processing,enqueued,processed,failed], event_name, duplicate_count INT NOT NULL
  DEFAULT 0, enqueued_at, processed_at, last_error,
  UNIQUE(provider, event_key))       -- same key + different hash = 409 (spoof signal)
  -- duplicate_count = how many times the same event arrived again after the first claim.
  -- It is the "deduplicated" column of the webhook activity view; without it a vendor
  -- retrying fifteen times looks like one quiet success.
idempotency_records(id, scope_key, route, method, idempotency_key, request_hash,
  status ENUM[processing,completed,failed], response_status, response_payload JSONB,
  expires_at, UNIQUE(scope_key, route, method, idempotency_key))
  -- scope_key = HMAC fingerprint of tenant/user (raw ids never stored); TTL ~24h
```

## 9a. Global tables (deliberately NOT tenant-RLS'd — every exception listed)

Hard rule 1 admits no silent exceptions. A table that CARRIES `tenant_id` and still has no
policy must be named, with its reason, in `apps/api/db/registry.py::RLS_EXEMPT_TENANT_COLUMNS`
— the RLS-coverage guardrail reads that dict, so an undeclared exception fails CI. The
reasons are repeated here. (`platform_state` and `idempotency_records` carry no `tenant_id`
at all, so they are not tenant tables and need no exemption entry.)

```
engine_agent_routes(engine, engine_agent_ref, tenant_id, agent_id, active,
  created_at, updated_at, PRIMARY KEY(engine, engine_agent_ref))
  -- The inbound routing table: (vendor engine, vendor agent id) → (tenant, agent).
  -- WHY IT IS EXEMPT: an engine webhook arrives carrying only the VENDOR's agent id —
  -- no session, no tenant, no GUC — so resolving it is inherently a cross-tenant read.
  -- Keeping that two-id lookup in its own global table is EXACTLY what lets `agents`
  -- stay FORCE-RLS'd; the alternatives (an exemption on `agents`, or running the
  -- resolver as the owner role) would punch a cross-tenant hole through the control the
  -- whole design rests on. It carries no PII and no call data, and it is written by the
  -- agent-publish path in the SAME transaction that sets agents.engine_agent_ref, so
  -- the two cannot disagree. Composite PK because the same vendor id may exist on two
  -- engines during a migration and must resolve independently.
platform_state(id PK CHECK (id = 1), load_shed_mode
  ENUM[normal,reduced,emergency,maintenance], outbound_halted BOOL, halt_reason,
  changed_by, changed_at, updated_at,
  tm_registration_status TEXT NOT NULL DEFAULT 'not_registered'
    CHECK (tm_registration_status IN
           ('not_registered','submitted','active','suspended','revoked')),
  tm_id TEXT, tm_registered_at, tm_verified_at,
  CHECK (tm_registration_status <> 'active'
         OR (tm_id IS NOT NULL AND tm_registered_at IS NOT NULL)))
  -- Single-row global switchboard: the load-shed mode AND the big red switch.
  -- tm_* = CALEVATE's own DLT telemarketer registration (D-43, migration
  -- d7f2a3c9b410) — the company half of SEC-COMP §3's first bullet, read by
  -- `launch_blockers` as `tm_registration_missing`. ONE fact about one entity (us), so
  -- it is not copied per tenant: N copies drift and the gate could not say which row is
  -- the platform. `tm_registered_at` is the registrar's date, `tm_verified_at` is when
  -- WE last looked (same reason `dlt_registrations.verified_at` exists). The second
  -- CHECK is why the seed says `not_registered`: seeding `active` would mean inventing
  -- a registration number. Read by `ops/service.read_tm_registration` on the CALLER's
  -- session — deliberately NOT through `core.loadshed`'s cache (a compliance fact
  -- checked once per launch must not be 15s stale) and fail-CLOSED on a missing row,
  -- the opposite of that cache's deliberate fail-open.
  -- BACKEND-PATTERNS §6 requires the load-shed mode to be DURABLE in Postgres (Redis is
  -- only its cache) so a Redis flush cannot silently re-open a service an operator shut.
  -- The outbound halt shares the row because it answers the same question — "is the
  -- platform allowed to do work right now" — and one row means one read. Global by
  -- definition; written only through the audited admin ops surface (step-up confirm).
audit_log  -- (defined in §9) exempt because the admin realm reads cross-tenant by
           -- design; every such read is itself audited.
```

## 10. Migration & Integrity Rules

- Alembic; every migration reversible; RLS policies live in migrations (not ad-hoc).
- CHECK constraints mirror Pydantic enums; JSONB validated at API boundary.
- Nightly job: retention TTL enforcement (calls/turns/extractions/leads, plus the derived
  copies in §9) + deletion_requests execution + proof write. Its worklist comes from
  `engine_agent_routes`, the global bridge table — NOT from enumerating `organizations`,
  which made the tick's cost grow with the client list instead of with the data. Every
  write still happens inside `tenant_session`, so no RLS exemption and no admin role.
- **A redundant prefix index is dropped on MEASUREMENT, and the keepers carry their
  reason.** Eleven single-column btrees in this schema are a strict prefix of another
  btree on the same table; four were dropped (migration `b9e5d2c74a18`:
  `ix_transcript_turns_call_id`, `ix_prompt_versions_agent_id`,
  `ix_extraction_schemas_agent_id`, `ix_memberships_tenant_id`) and **seven stay**, each
  pinned by `tests/prefix_index_audit_test.py` WITH the plan that collapsed without it, so
  the next catalog-driven tidy-up fails with an argument rather than a diff. Uniqueness of
  the cover is NOT the discriminator (the leading-column rule carries no uniqueness
  condition, `btcostestimate`'s unique shortcut needs a qual on every key column, and
  nothing can depend on a non-unique `ix_*`). What decides it is btree **deduplication**: a
  non-unique index on a repeating column collapses duplicates into one posting-list tuple
  per distinct value and a cover whose trailing columns are distinct cannot, so the cover
  is 4–18x the size and offering it alone for `tenant_id = …` moves the query onto a
  sequential scan rather than onto the cover. That is why the four big `ix_*_tenant_id`
  indexes — the ones every `tenant_isolation` qual runs through — stay. Verdicts are taken
  at realistic rows-per-key, not at seed size: two keepers only failed at scale. Bar for a
  drop: no node type changes, nothing falls back to a seq scan, and the extra buffers are
  stated. Two near-misses are excluded by construction — a prefix of a PARTIAL index
  covers a subset of rows and therefore covers nothing.
- **An unindexed foreign-key CHILD column is judged on who SCANS it, not on whether the
  parent cascades.** D-192 counted 33 such columns and added none, because no parent in this
  schema is ever hard-deleted so the referential scan is unreachable — correct, and the wrong
  test. The census is 34 by `pg_constraint` + `pg_index.indkey[0]` (one, `leads.assigned_to`,
  is a false positive: a PARTIAL index serves it, which a catalog query cannot see). Five were
  taken in `c9e2a7b41d63`, four of them bought entirely by application queries, each with its
  before/after plan in the migration; the other 28 are declined THERE, by group, with reasons.
  Bar for adding one: a named call site, a measured plan at realistic rows, and a statement of
  the write cost. `docs/evidence/deepdive-dbscale.md` is the full record.
- **A reset drops the schema; it does not walk the chain backwards.** `make db-reset` runs
  `scripts/db_reset.py` (D-208). A downgrade can be REFUSED by the data a database holds —
  `b3d9f6a2c815` re-imposes NOT NULL on `admin_users.clerk_user_id`, which the first-party
  operator `scripts/bootstrap_admin.py` creates violates — and it fails MID-CHAIN, leaving
  `alembic_version` disagreeing with the schema. That is not hypothetical: it is the state the
  shared development database was found in.
- Backups: PITR + nightly snapshot; restore drill quarterly (OPERATIONS.md §6). The
  mechanism lives in `infra/backup/` (D-50) and **has never been applied or run** — see
  SECURITY-COMPLIANCE §4 for what the 35-day backup window means for an erasure.
- Seed data: reserved_slugs, vertical extraction templates, default retention policies.
