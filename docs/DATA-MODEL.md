# Calevate — Data Model (Postgres 16 + pgvector)

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
  billing_email, created_by, deleted_at)
reserved_slugs(slug PK)              -- admin, api, login, settings, app, www, ...
users(id, clerk_user_id UNIQUE, email, name, phone)
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
  status ENUM[draft,live,paused], engine ENUM[thinnest,bolna]  -- 'bolna' is the live
    -- value (D-31); 'thinnest' stays in the CHECK until a migration removes it
    -- (two-step deprecation, hard rule 8) --, engine_agent_ref TEXT,
  engine_staging_ref TEXT, deleted_at)
prompt_versions(id, tenant_id, agent_id, version INT, body TEXT, compiled_t0_context TEXT,
  created_by, published_at, UNIQUE(agent_id,version))               -- full history + rollback
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
  latency JSONB,                       -- {stt_ms,llm_ttft_ms,tts_ttfa_ms,turn_p50,turn_p95}
  engine_payload_ref TEXT)             -- object-storage key of raw vendor payload (debug only)
transcript_turns(id, tenant_id, call_id, idx INT, speaker ENUM[agent,caller], text TEXT,
  text_redacted TEXT, lang TEXT, start_ms INT, end_ms INT, UNIQUE(call_id,idx))
  -- default read = text_redacted; raw `text` gated by role + audit_log
call_extractions(id, tenant_id, call_id, schema_version INT, data JSONB,
  model TEXT, prompt_version INT, valid BOOL, errors JSONB)
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
  schedule JSONB, concurrency INT CHECK (1..10), retry_policy JSONB,   -- {max_attempts, backoff, windows}
  calling_hours JSONB, engine_campaign_ref TEXT, launched_at)
  -- launch is BLOCKED unless: entity DLT-registered, template approved, number series
  -- matches classification (140⇔promotional / 160|standard⇔service-transactional), DNC scrub done.
campaign_contacts(id, tenant_id, campaign_id, phone_e164, name, custom JSONB,
  status ENUM[pending,dialing,connected,no_answer,failed,dnc_blocked,completed],
  attempts INT, last_attempt_at, dedupe_hash, UNIQUE(campaign_id, phone_e164))
dnc_list(id, tenant_id NULL, phone_e164, scope ENUM[global,tenant], source, added_at)
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
  approved_by, version INT)
kb_documents(id, tenant_id, source_id, title, meta JSONB)
kb_chunks(id, tenant_id, agent_id, document_id, content TEXT, tsv tsvector,
  embedding vector(1024), embed_model TEXT, embed_version TEXT,
  chunk_meta JSONB, version INT, is_active BOOL)
-- INDEX: HNSW ON kb_chunks USING hnsw(embedding vector_cosine_ops); GIN(tsv);
--        (tenant_id, agent_id, is_active) btree.
kb_retrieval_logs(id, tenant_id, call_id, query, tier ENUM[t0,t1,t2,t3,t4],
  top_ids UUID[], top_score REAL, latency_ms INT)   -- powers knowledge-gap reports
```

## 8. Billing & Metering (append-only)

```
usage_events(id, tenant_id, call_id NULL, unit_type ENUM[telephony_s,stt_s,tts_chars,
  llm_tok_in,llm_tok_out,platform_min,number_rental,other], qty NUMERIC, unit_cost_paid NUMERIC,
  occurred_at, meta JSONB)                          -- INSERT-only; no UPDATE/DELETE grants
plans(id, tenant_id, setup_fee, monthly_fee, included_min INT, overage_rate,
  hard_cap_min INT, hard_cap_spend NUMERIC, concurrency_ceiling INT DEFAULT 10,
  effective_from, effective_to)
engine_capacity(id PK=1, platform_lines_total INT, inbound_reserve INT,
  sarvam_concurrency INT, trunk_channels INT, updated_at)
  -- singleton config; effective outbound pool = MIN(all three) − inbound_reserve;
  -- values come from verification item 8, reviewed on any vendor plan change
credit_ledger(id, tenant_id, delta NUMERIC, reason ENUM[topup,usage,adjustment,refund], ref, balance_after)
invoices(id, tenant_id, period, lines JSONB, subtotal, gst, total,
  status ENUM[draft,sent,paid,overdue], razorpay_ref)
spend_state(tenant_id PK, month, minutes_used NUMERIC, spend_used NUMERIC, capped BOOL)
  -- read by voice-runtime & campaign engine BEFORE dispatch (fail closed when capped)
```

## 9. Compliance & Audit

```
consent_ledger(id, tenant_id, call_id, phone_e164, purpose ENUM[recording,callback,marketing],
  status ENUM[granted,declined,withdrawn], captured_at, evidence JSONB)   -- immutable
retention_policies(id, tenant_id, data_category ENUM[recording,transcript,lead,consent_log],
  ttl_days INT CHECK (ttl_days >= 90 WHERE data_category='recording'),   -- TRAI 90-day floor
  action ENUM[delete,anonymize])
deletion_requests(id, tenant_id, phone_e164, scope, requested_at, completed_at,
  proof JSONB)                                       -- deletion-with-proof (DPDP)
audit_log(id, actor_type ENUM[admin,user,system], actor_id, tenant_id, action, object_type,
  object_id, ip, at)                                 -- INSERT-only; includes recording/raw-transcript reads
webhook_deliveries(id, direction ENUM[in,out], source, event_type, status, attempts,
  signature_valid BOOL, payload_ref, first_at, last_at)
-- Reliability triad (D-30, BACKEND-PATTERNS §4; all claims via conditional-UPDATE CAS):
outbox_messages(id, queue, job, payload JSONB, status ENUM[pending,published,failed],
  attempt_count INT, job_id, published_at, last_error)      -- written in the SAME txn
  -- as the domain write; ARQ dispatcher polls oldest-first; >=5 attempts -> failed(DLQ)
webhook_inbox_events(id, provider, event_key, payload_hash, status
  ENUM[processing,enqueued,processed,failed], event_name, processed_at, last_error,
  UNIQUE(provider, event_key))       -- same key + different hash = 409 (spoof signal)
idempotency_records(id, scope_key, route, method, idempotency_key, request_hash,
  status ENUM[processing,completed,failed], response_status, response_payload JSONB,
  expires_at, UNIQUE(scope_key, route, method, idempotency_key))
  -- scope_key = HMAC fingerprint of tenant/user (raw ids never stored); TTL ~24h
```

## 10. Migration & Integrity Rules

- Alembic; every migration reversible; RLS policies live in migrations (not ad-hoc).
- CHECK constraints mirror Pydantic enums; JSONB validated at API boundary.
- Nightly job: retention TTL enforcement + deletion_requests execution + proof write.
- Backups: PITR + nightly snapshot; restore drill quarterly (OPERATIONS.md §6).
- Seed data: reserved_slugs, vertical extraction templates, default retention policies.
