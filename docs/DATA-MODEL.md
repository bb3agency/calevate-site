# Calevate — Data Model (Postgres 16; pgvector is a D-28 contingency, not the plan)

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
reserved_slugs(slug PK)              -- admin, api, login, settings, app, www, ...
users(id, clerk_user_id UNIQUE, email, name, phone, deactivated_at)
  -- deactivated_at re-checked by the auth guard on EVERY request (BACKEND-PATTERNS §7):
  -- a cached Clerk session must not outlive a deactivation
memberships(id, tenant_id, user_id, role ENUM[owner,staff], UNIQUE(tenant_id,user_id))
  -- staff: no billing.*, no org settings, no raw (unredacted) transcripts
invitations(id, tenant_id, email, role, token_hash UNIQUE, expires_at DEFAULT now()+'72h',
  used_at, created_by)               -- single-use; hash only; burned on accept
admin_users(id, clerk_user_id UNIQUE, name, role ENUM[superadmin,operator])  -- separate realm
```

## 3. Agents & Configuration

```
agents(id, tenant_id, name, direction ENUM[inbound,outbound,both],
  language_primary, languages_extra TEXT[],
  stt_provider, stt_model, tts_provider, tts_voice, llm_model,     -- config strings
  system_prompt_id → prompt_versions, extraction_schema_id → extraction_schemas,
  business_hours JSONB, escalation_config JSONB, disclosure_line TEXT NOT NULL,
  status ENUM[draft,live,paused], engine ENUM[fake,bolna]  -- 'thinnest' REMOVED from the
    -- CHECK (D-31: retired before any adapter or production row existed, so the
    -- two-step deprecation in hard rule 8 does not apply — nothing ever wrote it)
    --, engine_agent_ref TEXT,
  engine_staging_ref TEXT, deleted_at)
prompt_versions(id, tenant_id, agent_id, version INT, body TEXT, compiled_t0_context TEXT,
  notes TEXT, created_by, published_at, UNIQUE(agent_id,version))   -- full history + rollback
  -- notes = operator-facing "why this version exists" ("rollback to v3", "new pricing").
  -- Deliberately NOT compiled_t0_context: that is a build artefact OF the version,
  -- reserved by D-39 for the T0 compiler.
extraction_schemas(id, tenant_id, agent_id, version INT, fields JSONB, published_at)
phone_numbers(id, tenant_id, agent_id, e164 UNIQUE, series ENUM[140,160,standard],
  provider, engine_number_ref, dlt_status ENUM[pending,registered,blocked], purpose TEXT)
```

`extraction_schemas.fields` shape (validated by Pydantic on write):
```json
[
 {"key":"budget","label":"Budget","type":"number","description":"Property budget in lakhs","required":true},
 {"key":"preferred_location","label":"Location","type":"text","description":"Area/locality the caller wants","required":true},
 {"key":"bhk_size","label":"BHK","type":"enum","enum_values":["1BHK","2BHK","3BHK","4BHK+"],"required":false},
 {"key":"timeline","label":"Timeline","type":"text","description":"When they intend to buy","required":false}
]
```
Vertical templates = seed rows (clinic: symptom, preferred_doctor, insurance, urgency,
preferred_slot; real_estate: above; insurance; education). Changing a schema creates a new
version; Leads render columns by the version active at extraction time (no data loss).

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
  latency JSONB,                       -- {stt_ms,llm_ttft_ms,tts_ttfa_ms,turn_p50,turn_p95}
  engine_payload_ref TEXT)             -- object-storage key of raw vendor payload (debug only)
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
lead_events(id, tenant_id, lead_id, type ENUM[status_change,note,call,notification], payload JSONB, actor)
```

## 6. Campaigns & Ingest

```
campaigns(id, tenant_id, agent_id, name, classification ENUM[promotional,transactional,service] NOT NULL,
  number_id → phone_numbers, dlt_template_id → dlt_templates,
  status ENUM[draft,scheduled,running,paused,completed,cancelled],
  schedule JSONB, concurrency INT CHECK (1..10), retry_policy JSONB,   -- shipped default:
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
campaign_contacts(id, tenant_id, campaign_id, phone_e164, name, custom JSONB,
  status ENUM[pending,dialing,connected,no_answer,failed,dnc_blocked,completed],
  attempts INT, last_attempt_at, next_attempt_at, last_call_id NULL → calls ON DELETE
  SET NULL, dedupe_hash, UNIQUE(campaign_id, phone_e164))
  -- next_attempt_at is what makes the per-CONTACT backoff ladder above real: the
  -- dispatcher claims "due pending contacts, oldest first" through
  -- INDEX ix_campaign_contacts_due (campaign_id, status, next_attempt_at).
dnc_list(id, tenant_id NULL, phone_e164, scope ENUM[global,tenant], source, added_at,
  CHECK ((scope='global' AND tenant_id IS NULL) OR (scope='tenant' AND tenant_id IS NOT NULL)),
  UNIQUE(tenant_id, phone_e164))
  -- ASYMMETRIC RLS, the one deviation from the §1 pattern: the USING (read) clause also
  -- admits `tenant_id IS NULL` so a globally suppressed number is honoured for everyone,
  -- while WITH CHECK (write) does not — a tenant must not be able to suppress a number
  -- for every other client.
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
> Cross-call caller memory (H3) lives in the managed service, keyed back to our rows by
> provider ids in `meta`. See TRD §6.1 — do not add a "conversation state" table.

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
kb_chunks(id, tenant_id, agent_id, document_id, content TEXT, tsv tsvector,
  embedding vector(1024), embed_model TEXT, embed_version TEXT,
  chunk_meta JSONB, version INT, is_active BOOL)
-- INDEX: HNSW ON kb_chunks USING hnsw(embedding vector_cosine_ops); GIN(tsv);
--        (tenant_id, agent_id, is_active) btree.
kb_retrieval_logs(id, tenant_id, call_id, query, tier ENUM[t0,t1,t2,t3,t4],
  top_score REAL, latency_ms INT)   -- powers knowledge-gap reports
  -- `top_ids UUID[]` was specified here and is NOT in the shipped table: it would point
  -- at kb_chunks rows, which D-28 made contingency. Add it with the chunks, or not at all.
```

## 8. Billing & Metering (append-only)

```
usage_events(id, tenant_id, call_id NULL, unit_type ENUM[telephony_s,stt_s,tts_chars,
  llm_tok_in,llm_tok_out,platform_min,number_rental,other], qty NUMERIC, unit_cost_paid NUMERIC,
  occurred_at, meta JSONB)                          -- INSERT-only; no UPDATE/DELETE grants
plans(id, tenant_id, setup_fee, monthly_fee, included_min INT, overage_rate,
  hard_cap_min INT, hard_cap_spend NUMERIC, concurrency_ceiling INT DEFAULT 10,
  effective_from, effective_to)
credit_ledger(id, tenant_id, delta NUMERIC, reason ENUM[topup,usage,adjustment,refund],
  ref, balance_after, occurred_at, meta JSONB)          -- INSERT-only (hard rule 4)
-- INDEX ix_credit_ledger_tenant_recent (tenant_id, occurred_at DESC, id DESC)
--   (migration a6f2e84b1d37). The balance is NOT an aggregate — that is why
--   balance_after is denormalized — so every read is `ORDER BY occurred_at DESC,
--   id DESC LIMIT 1` on the pre-dispatch path. The `id DESC` tail is load-bearing:
--   occurred_at is stamped with clock_timestamp(), so "newest" must be a TOTAL order or
--   two readers disagree about which row it is. `ix_credit_ledger_tenant_id` is now a
--   redundant prefix and is deliberately NOT dropped in the same release (hard rule 8).
--   REFUSED in the same migration, and recorded so nobody re-derives it: a partial
--   UNIQUE(tenant_id, ref) WHERE reason IN ('topup','usage') would make double-crediting
--   impossible instead of merely unlikely, but existing rows violate it and this is an
--   append-only ledger — the fix is compensating entries by a person, then the index.
--   That correction path now exists (`scripts/reconcile_credit_ledger.py`, dry-run by
--   default, `--apply` to write; compensating `adjustment` entries through
--   `record_entry` under the tenant credit lock, never an UPDATE or DELETE). The index
--   is still REFUSED: the violating pairs are manufactured faster than they are
--   corrected while the test suite runs, so it lands only after a reconciled database
--   and a fixture that seeds its residue backdated rather than by double-crediting.
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
invoices(id, tenant_id, period, lines JSONB, subtotal, gst, total,
  status ENUM[draft,sent,paid,overdue], razorpay_ref)
  -- SHIPPED INSTEAD (M2): an invoice is a DERIVED STATEMENT, not a row. `build_invoice`
  -- (apps/api/billing/invoice.py) computes it from usage_events + plan on request and
  -- persists nothing. That is WHY the invoice number can be deterministic
  -- (CAL-{YYYYMM}-{first 8 hex of tenant_id}): with no stored row there is no sequence to
  -- collide with, and regenerating a month can never mint a second number for it.
  -- This table lands only when an invoice acquires state we cannot derive (sent/paid/
  -- overdue, razorpay_ref) — i.e. with collection, not with the statement.
```

## 9. Compliance & Audit

```
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
retention_policies(id, tenant_id, data_category ENUM[recording,transcript,lead,consent_log],
  ttl_days INT CHECK (ttl_days >= 90 WHERE data_category='recording'),   -- TRAI 90-day floor
  action ENUM[delete,anonymize])
  -- SEEDED defaults (`scripts/seed.DEFAULT_RETENTION_POLICIES`): recording 90/delete,
  -- transcript 365/anonymize, lead 1095/anonymize, consent_log 2555/anonymize. These
  -- do NOT match the numbers SEC-COMP §4 prints — see the open question recorded there;
  -- the DPA quotes the doc and the sweep obeys these rows.
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
- Backups: PITR + nightly snapshot; restore drill quarterly (OPERATIONS.md §6).
- Seed data: reserved_slugs, vertical extraction templates, default retention policies.
