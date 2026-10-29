# Calevate — Data Model (Postgres 16 + pgvector; the `vector` extension is REQUIRED since D-502)

Version 1.0 · Conventions: snake_case; every table has id UUID PK (uuid_v7), created_at,
updated_at; every tenant-scoped table has tenant_id UUID NOT NULL REFERENCES organizations(id)
and an RLS policy; soft-delete via deleted_at where noted; money as NUMERIC(12,4) INR;
phone as E.164 TEXT; all timestamps timestamptz — absolute instants, so the zone is chosen
only where one is read: IST (`Asia/Kolkata`) for every day, week and month bucket, named in
the SQL as `AT TIME ZONE 'Asia/Kolkata'` and never left to the session (D-709).

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
    -- born `onboarding`; moves to `active` by itself once an owner has joined and the
    -- business profile has no go-live blockers (`tenancy/onboarding`, D-695), on the
    -- profile save or invite acceptance that completes it, audited
    -- `tenant.onboarding_completed`. Operators move `active`<->`suspended`; closing is
    -- `closure`. KYC, the pledge and payment are separate axes: `onboarding` and `active`
    -- dial alike (`compliance/service._STOPPED_STATUSES`).
  plan_tier ENUM[managed,prepaid,self_serve,trial] NOT NULL DEFAULT 'prepaid',
                                                          -- D-34/D-39, D-521 (default)
    -- which MOTION this org belongs to, not a feature flag: it decides whether credits
    -- gate dispatch (compliance gate) and whether the self-serve screens render.
    -- The four names answer TWO questions and the pairs are NOT the same set:
    --   pays from a wallet   -> prepaid, self_serve, trial  (billing/rates.PREPAID_TIERS)
    --   opened by a stranger -> self_serve, trial           (compliance.SELF_SERVE_TIERS,
    --                                                        the admin hold queue)
    -- `prepaid` (D-521) is what every new account gets and what every existing account
    -- was migrated to (a8d3f61c04e7); `managed` is invoiced on a retainer. No route sets
    -- `plan_tier` today; a change is a reviewed SQL update.
  first_paid_at NULL, first_paid_via NULL IN (wallet_topup, manual_topup, before_d697,
    operator_conversion, complimentary), first_paid_reason NULL,
    -- D-697: the first credit that unlocked paid features; NULL is a trial account.
    -- `complimentary` (D-890, migration e3b9d5f1a827) is a super admin making the account
    -- paid with no payment behind it (`POST /v1/admin/tenants/{id}/paid`, `billing:comp`);
    -- `first_paid_reason` keeps their words, because `audit_log` records who and what only.
    -- Written once by `billing/first_payment._claim` (`WHERE first_paid_at IS NULL`).
  billing_email, created_by, deleted_at,
  closed_at, erase_after, closure_reason, closed_by FK admin_users ON DELETE SET NULL)
    -- D-538, migration e6c1a49d2f70. THE GRACE WINDOW between "closed" and "erased":
    -- an admin closes a client, the client is emailed, and the tenant erasure is FILED
    -- (never executed here) by `workers/account_closure.sweep_due_erasures` when
    -- `erase_after` passes. `tenancy/closure.py` is the only writer of all four.
    -- THE THREE FACTS NEST, and three CHECKs hold it so the readers of these columns
    -- cannot disagree about whether a business exists:
    --   ck_organizations_deleted_implies_no_deadline  deleted_at  => erase_after IS NULL
    --   ck_organizations_erase_after_implies_closed   erase_after => closed_at
    --   ck_organizations_closed_implies_churned       closed_at   => status = 'churned'
    -- `erase_after` NULL on a closed account is intended: it is what an UNDO leaves, and
    -- it is how an account closes with its records KEPT. Deliberately NOT added:
    -- "churned implies closed_at" — churned predates this and existing rows carry no
    -- closure instant, so the CHECK would be a backfill of a date nobody observed.
    -- ON `organizations` rather than in a table because the sweep is CROSS-TENANT and
    -- `admin_session()` widens USING on exactly this table (b57e2f9c4a13); a tenant-RLS'd
    -- one would be invisible to the cron (§9a states the same rule from the other side).
    -- A SECOND scheduled-erasure deadline exists on `tenant_trials` (D-536, §8); the two
    -- sets are disjoint by construction and `request_tenant_erasure` dedupes an account
    -- that is in both.
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
  -- low_balance_alert_inr NUMERIC(12,2) NULL, CHECK 0..100000 (migration f1a6c3e9d204,
  -- D-893 L6): the balance below which the client is warned credit is low. NULL is
  -- Calevate's line (`billing.service.LOW_BALANCE_INR`), 0 stops the low warning; the
  -- empty-wallet warning ignores it. Read only through `billing.service.low_balance_line`
  -- (the ledger's crossing, `Balance.is_low`, the wallet reads, the attention queue).
  -- default_opening_wait_ms INT NULL (a9c4e1d7b352, D-901) and default_reask_after_ms INT
  -- NULL (b7e2d5a9c813, D-907): the account's defaults for the two agent call settings of
  -- the same names (§3), same CHECKs; NULL follows the console / Calevate's 5 s.
  -- caller_memory_attestation_version SMALLINT NULL (f5cd440f4e1c, D-899/D-900): which
  -- caller-memory statement the owner accepted (`agents/publishing.CALLER_MEMORY_ATTESTATIONS`);
  -- acceptances before the revision were backfilled to 1, new ones record 2. NULL = never
  -- accepted. An account still on 1 is asked to accept 2 and its caller memory pauses until
  -- it does (D-900).
  -- erasure_sweep_attempted_at, erasure_sweep_failures INT NOT NULL DEFAULT 0
  -- (c7e4a9d2f513): each hourly attempt to file this account's erasure is stamped, so
  -- `tenancy/closure.due_erasures` tries untried accounts first; three failures in a row
  -- raise `closure_erasure_stuck`.
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
  used_at, created_by, last_sent_at NOT NULL DEFAULT now(), send_count NOT NULL DEFAULT 1)
                                     -- single-use; hash only; burned on accept
  -- D-538, migration e6c1a49d2f70. A RESEND ROTATES THIS ROW rather than minting a second
  -- invitation: `token_hash` is replaced, `expires_at` restarts, `email` may be corrected,
  -- and `send_count`/`last_sent_at` count sends of ONE key. So the previous link dies in
  -- the same statement that mints the new one and two live keys to one account cannot
  -- exist by construction (`create_invitation`'s `invitation_already_pending` refusal
  -- stays, guarding a door nobody needs). The pair is the rate limiter's clock AND the
  -- console's "last sent 4 minutes ago, 3 times" line — one fact, because a screen reading
  -- a different value from the limiter tells an operator to wait when they need not.
  -- A CORRECTED ADDRESS IS AN OPERATOR ATTESTATION, audited as
  -- `admin.invitation_readdressed` (the ACTION, because audit_log has no summary column)
  -- and NEVER a verification: `users.email_verified_at` stays NULL and D-185's
  -- `email_verify` round trip is still what proves a mailbox. It is only reachable while
  -- `used_at IS NULL` — after redemption the address is a login identity.
admin_users(id, clerk_user_id UNIQUE, email, name, role ENUM[superadmin,operator],
  deactivated_at, stay_signed_in BOOL NOT NULL DEFAULT false)         -- separate realm
  -- stay_signed_in (D-766, migration b6d2f8a41c97): the operator's own "Stay signed in"
  -- switch. On, their second-factor-complete sessions take the client realm's bounds
  -- (12 h idle / 14 d) and a persistent cookie; read on every session verification.
  -- Only the operator may switch it on (fresh second factor); a superadmin may switch it
  -- off. Written only by `authn/stay_signed_in.py`, audited as
  -- `admin.stay_signed_in_changed`. No RLS, like the rest of this table.
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
tenant_engine_workspaces(id, tenant_id → organizations RESTRICT UNIQUE, engine,
  external_ref UNIQUE, workspace_id UNIQUE NULL,
  status ENUM[pending,active,plan_limit,failed,offboarding,deleted] DEFAULT 'pending',
  last_error_code, attempts INT DEFAULT 0, provisioned_at, deleted_at,
  business_status ENUM[none,draft,submitted,accepted,rejected,suspended,expired,unknown] NULL,
  business_can_rent BOOL, business_review_note, business_submitted_at, business_checked_at,
  business_document_id NULL,
  studio_enabled_at, studio_checked_at, studio_error_code (e9b2c7d4a1f3, D-717),
  own_model_enabled_at, own_model_checked_at, own_model_error_code (a4c8e1f6b2d9, D-764),
  created_at, updated_at)
  -- studio_* / own_model_*: where our Cartesia key / our Google (LLM) key was confirmed on in
  -- this workspace, the last matching `GET /byok`, and our code for the last failure
  -- (each error code CHECK <= 64 chars).
  -- D-693, migration d93b6f2a4c18. Each client's own ThinnestAI customer workspace
  -- (`POST /customers`, reached with `Thinnest-Workspace: org_…`,
  -- `thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/customers.md:18-91`).
  -- `external_ref` = `calevate-<tenant uuid>`, sent as the customer's `externalId`, so
  -- provisioning finds a workspace it already made from the tenant id alone.
  -- `workspace_id` is the `org_…` id once it exists. `business_*` is our last reading of
  -- the workspace's business-details application (`phone-numbers/get-business-details.md:7`).
  -- Read through ONE resolver, `tenancy/engine_workspace.resolve_workspace`, which answers
  -- the id only while `status = 'active'` and never falls back to our developer workspace.
  -- FORCEd §1 RLS, plus the untenanted READ arm `tenant_engine_workspaces_directory_read`
  -- (`<guc> IS NULL`, never `true`, as c3f7b21a94e8 introduced): the provisioning and
  -- reconciliation sweeps list every tenant's workspace from the directory session, while
  -- a session scoped to one tenant still sees nothing of another. Writes stay strict.
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


### The business profile (D-695, migration `f4c8b2e6a1d9`)

```
business_profiles(id, tenant_id UNIQUE FK organizations, -- FORCEd tenant_isolation
  hours JSONB NOT NULL DEFAULT '{}'  -- {mon: {opens, closes} | null}: null = CLOSED,
                                     -- an absent day = NOT ANSWERED YET
  branches JSONB[] , services JSONB[] (price_inr a digit STRING, hard rule 7),
  faqs JSONB[], staff JSONB[] (name, pronunciation, role), booking_rules TEXT,
  languages TEXT[]                   -- every language the business serves: since D-815 the
                                     -- STARTING reply languages of an agent created from now on
  setup_steps JSONB {step: done|skipped}, setup_started_at, setup_dismissed_at,
  merge_notes JSONB                  -- written only by the D-695 data move: per field, the
                                     -- value kept and the values set aside
  updated_by, created_at, updated_at)

business_contacts(id, tenant_id FK, position, label, phone_e164 CHECK E.164,
  note TEXT,                          -- when to call, in the client's words
  UNIQUE (tenant_id, phone_e164) DEFERRABLE INITIALLY DEFERRED)   -- FORCEd tenant_isolation
```

ONE profile per client, the single source of what every agent says about the business:
each agent's [T0 FACTS] is compiled from it (`tenancy/business_profile.fact_lines`), the
after-hours flag and the handover rota are judged against its hours, and its languages are
where a NEW agent's reply languages start (D-815); each agent then keeps its own list
(`agents.languages_extra`, below), which a later profile save does not rewrite. Contacts never enter a
prompt. `agent_handoff_members.contact_id` (NOT NULL, CASCADE) makes each agent's handover
list a SELECTION from `business_contacts`; the member's `label`/`phone_e164` are the
contact's, copied in the same transaction by the one writer. `organizations.intake` and
`agents.business_hours` are no longer read or written (hard
rule 8, step 1). `invitations.invitee_name` / `invitee_phone` carry the owner's details from
the operator's form to their account.

## 3. Agents & Configuration

```
agents(id, tenant_id, name, direction ENUM[inbound,outbound,both],
  language_primary, languages_extra TEXT[],  -- D-815: the reply languages after the main one,
    -- in order; CHECK ck_agents_languages_extra_offered: offered tags only, at most three,
    -- never language_primary (migration e3b9d4a7c218, which copied each business's list in)
  stt_provider, stt_model, tts_provider, tts_voice, llm_model,     -- config strings
  engine_voice_id TEXT, engine_model_id TEXT,  -- b7e2d94f1a30, D-678. A voice and a model
    -- from the ENGINE'S OWN catalogue (ThinnestAI `GET /voices`, `GET /models`), sent only
    -- on a leg the engine dictates; NULL = the engine's default. Separate from `tts_voice` /
    -- `llm_model`, which name OUR catalogue. CHECK `^[^[:space:]]{1,128}$` is a floor; the
    -- offer (catalogue membership, call-capable, plan, attested band rate) is decided at
    -- publish by `agents/engine_choice.py`. The chosen voice's band is stamped as
    -- `engine_agent_routes.engine_rate_key`.
  studio_voice_speed NUMERIC(3,2), studio_voice_volume NUMERIC(3,2),  -- f3b8d1c6a7e2, D-767.
  studio_voice_emotion TEXT, studio_voice_model TEXT, studio_voice_dictionary_id TEXT,
    -- How a Studio voice (our own Cartesia key) sounds on this agent. The client sets speed,
    -- volume and emotion on its own agents (D-843, `voice_tuning_routes.router`); the model
    -- and dictionary stay with operators (`admin_router`). Speed also reaches a Clear voice
    -- as ThinnestAI's `voice.speakingSpeed` (D-884, `agents/voice_tuning.py`).
    -- NULL is the provider's default. CHECKs: speed 0.6-1.5, volume 0.5-2.0, emotion one of
    -- eight, model one of five Sonic ids, dictionary id `^[A-Za-z0-9][A-Za-z0-9_-]{2,79}$`,
    -- and `sonic-2` with speed, volume and emotion NULL (ThinnestAI `byok-voice`). Sent only
    -- while `engine_voice_id` is a Studio voice (`agents/voice_tuning.py`).
  max_reply_tokens INTEGER,  -- b9d4e2a7c6f1, D-769. The longest reply in tokens, set by
    -- operators only; CHECK 100-800 (ThinnestAI `maxReplyTokens`). NULL inherits the console's
    -- `thinnest_reply_length` (`agents/reply_length.py`); sent on every publish.
  system_prompt_id → prompt_versions, extraction_schema_id → extraction_schemas,
  business_hours JSONB, escalation_config JSONB,   -- business_hours: unread since D-695 (the profile)
  business_outcomes JSONB,   -- c4e9a2f7b183, D-836. The agent's own call outcomes, at most 8
    -- `{key, label, meaning, lead_status ∈ contacted|interested|hot}` (CHECK: array, length
    -- <= 8). NULL until drafted or saved by the owner; extraction then offers the neutral
    -- `calevate_shared.business_outcomes.STARTING_OUTCOMES`. `[]` = the owner wants none.
  business_outcomes_draft TEXT,   -- the ONE AI draft: queued|running|done|failed|skipped,
    -- NULL = never queued (`agents/call_outcomes.queue_draft`, CAS from NULL; never re-queued).
  field_suggestions JSONB,   -- d1a7c3e9f246, D-889. Suggested changes to the agent's lead
    -- details waiting for the owner (`agents/field_suggestions.Suggestion`: add_choices |
    -- remove_choices | new_field, with reason and source). CHECK: array, length <= 6.
  field_suggestions_state TEXT,   -- queued|running|done|failed|skipped; NULL = never queued.
    -- Re-queued on a script, business-details or quick-facts save, the first publish, the
    -- second caller asking for the same unlisted thing, and "Check again".
  field_suggestions_inputs TEXT,  -- sha256 of what the last pass read; same hash = no spend
  field_suggestions_dismissed JSONB NOT NULL DEFAULT '[]',  -- fingerprints the owner turned
    -- down, never offered again (CHECK: array, length <= 200)
  field_suggestions_at TIMESTAMPTZ,   -- when the state last moved
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
  ai_disclosure_enabled BOOL NOT NULL DEFAULT false,     -- D-669 (migration a6d2f81c4e3b):
  recording_notice_enabled BOOL NOT NULL DEFAULT false,  -- a call opens with the greeting only
  disclosure_line TEXT NOT NULL,  -- LEGACY: the two sentences joined, whatever the
    -- toggles say. Still written, no longer read by the publish path — step 1 of a
    -- two-step deprecation (hard rule 8); step 2 drops it (D-163).
  -- DEFAULT WORDING, NOT A SCHEMA CHANGE: `compliance/disclosure` holds the default
  -- sentences for new agents. Migrations c3e8a1f5d702 (D-861: every word of a Telugu or
  -- Hindi line in the language's own letters; the memory sentence reworded) and
  -- f2b7c4e9d815 (D-865: the Telugu and Hindi AI sentence introduces the agent by name)
  -- rewrote a stored line ONLY where it was exactly the previous default, left every edited
  -- line alone, and queued one platform live-apply run so live agents were republished.
  status ENUM[draft,live,paused,archived], engine ENUM[fake,thinnest]
    -- `EngineName` is `thinnest` and `fake` since D-763 (`calevate_shared.config.
    -- SELECTABLE_ENGINES`, derived and never retyped; `agents/models.ENGINES`). The database
    -- CHECK `ck_agents_engine_enum` still admits 'cartesia' and 'pipecat' until next
    -- release's migration narrows it (hard rule 8); nothing writes them. 'bolna' left with
    -- D-639; 'thinnest' returned with D-678 (migration f3a8c61d2e57).
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
  knowledge_pack_sha256 TEXT, knowledge_pack_recorded_at TIMESTAMPTZ,
    -- b5d3a91e7c64, D-599. NO LONGER WRITTEN (D-763); dropped next release. The digest of
    -- the in-call knowledge pack our own engine loaded, and when it was recorded. On
    -- ThinnestAI the client's knowledge reaches every agent as vendor knowledge documents
    -- (D-689, `engine_kb_routes`), so nothing derives a pack.
  script_proposal JSONB,   -- D-820. The ONE script suggestion waiting on the Script page
    -- (`agents/script_proposals.py`; a row column, not a table: it is replaced by the next
    -- request and cleared by the review). `mode` is `change` | `whole` | `steps` (asked of
    -- Pip) or `knowledge` (D-923: written by us when a file added to the knowledge goes
    -- live, never nameable by a request); `status` drafting | ready | failed; `base_script`
    -- fixed at request time; `documents`/`document_names` on a `knowledge` proposal. Every
    -- write after the request is a CAS on its `id`. Never reaches a call by itself.
  -- CALL SETTINGS ADDED 24-27 OCT 2026. Each is sent to ThinnestAI on every publish and
  -- read back as drift (D-911); a NULL inherits the account's default, then the console's.
  opening_waits_for_caller BOOL NOT NULL DEFAULT false,  -- f4b8c1d6a273, D-871. Sent as
    -- `voice.openingWaitsForCaller`; backfilled true on agents that only place calls.
  opening_wait_ms INT NULL,   -- a9c4e1d7b352, D-901. `voice.openingWaitSeconds`; CHECK
    -- 500..10000 on whole tenths. NULL -> organizations.default_opening_wait_ms -> console
    -- `thinnest_opening_wait_ms`.
  turn_detection TEXT NULL,   -- a9c4e1d7b352, D-901. An operator's timer | ear | smart for
    -- one agent over the console's `thinnest_turn_detection`; never offered to clients.
  caller_has_screen BOOL NOT NULL DEFAULT false,  -- e7c2a9b4d158, D-906. The owner's switch:
    -- the prompt lets the agent name on-screen labels, give one step a turn, spell a web
    -- address.
  reask_after_ms INT NULL,    -- b7e2d5a9c813, D-907. `voice.reaskAfterSeconds`; CHECK 0
    -- (never) or 1500..10000 on whole tenths. NULL -> organizations.default_reask_after_ms
    -- -> 5 s.
  voice_settings JSONB NULL,  -- b3f9d2a7c41e, D-896. The call-handling settings the agent was
    -- last published with (closed-set values and numbers, no caller text), copied onto each
    -- new `calls.voice_settings`.
  -- `language_primary`/`languages_extra` CHECKs admit the staged languages (ta, kn, ml, mr;
  -- migration d6f1a8c3e925, D-855); which ones a client may pick is decided at run time by
  -- `agents/languages.client_language_tags` and the console's
  -- `staged_agent_languages_enabled`, not by the constraint.
  max_call_duration_s)                       -- the per-agent cost-runaway ceiling
agent_hot_facts(id, tenant_id, agent_id FK agents UNIQUE, items JSONB array, digest,
  budget_chars, used_chars >= 0, candidates, calls_read, computed_at, created_at, updated_at)
  -- b3f9d2a7c41e, D-896. The facts one agent knows by heart, chosen from the client's live
  -- knowledge by what its callers ask (`agents/hot_facts.py`). FORCEd tenant_isolation;
  -- zero-rows proof `tests/hot_facts_test.py`.
script_line_changes(id, tenant_id, agent_id FK agents CASCADE, target IN (draft, script),
  stage_index >= 0, before_text, after_text, created_at, UNIQUE(agent_id, target, stage_index))
  -- d7c2e9a4f6b1, D-894. Every script step the migration that took the stock Telugu
  -- "సరే అండి," off changed or queued, so its downgrade restores exactly those steps.
  -- FORCEd tenant_isolation.
team_alert_contacts(id, tenant_id, channel IN (email, whatsapp) DEFAULT email,
  address 3..254, whatsapp_credential_id NULL, whatsapp_template/_language/_number_id/
  _values NULL (all set for whatsapp), is_default, verified_at, code_hash, code_expires_at,
  code_sent_at, code_attempts >= 0, removed_at, created_at, updated_at)
team_alert_rules(id, tenant_id, agent_id FK agents, contact_id NULL FK team_alert_contacts,
  on_outcomes JSONB array, on_fields JSONB array, in_call BOOL DEFAULT false, ...)
team_alerts(id, tenant_id, agent_id, call_id FK calls, contact_id, trigger IN (after_call,
  in_call, follow_up), reasons JSONB array, status IN (queued, sent, failed, cancelled)
  DEFAULT queued, attempts >= 0, sent_at, ...)
  -- `follow_up`: a Follow-up's "tell the team" step (f4b8d2a6c913, D-940).
  -- c4e9a2f7d816, D-904 "Tell my team". The business's own team addresses (verified once by
  -- an emailed code), one rule row per agent (which outcomes and choice values tell the
  -- team, and whether the agent may tell it during the call), and one delivery row per
  -- (call, address), which is also the idempotency key. All three FORCEd tenant_isolation;
  -- zero-rows proof `tests/team_alerts_test.py`. The same migration widens
  -- `agent_test_cases.caller_lines` to 1..20 lines (was 6) so a guided procedure can be a
  -- saved test.
follow_ups(id, tenant_id, name 1..80, status IN (draft, live, paused, off) DEFAULT draft,
  trigger JSONB object, settings JSONB object, draft JSONB array NULL, live_version_id NULL
  FK follow_up_versions, starter NULL IN (call_new_leads, qualify_new_leads,
  missed_call_callback, appointment_reminder, payment_reminder, win_back), created_by NULL
  FK users, created_at, updated_at; live/paused => live_version_id; UNIQUE(tenant_id) WHERE
  starter = 'call_new_leads')
follow_up_versions(id, tenant_id, follow_up_id FK, number >= 1, steps JSONB array, trigger,
  settings, published_by, published_at, UNIQUE(follow_up_id, number))   -- APPEND-ONLY
follow_up_runs(id, tenant_id, follow_up_id FK, version_id FK, lead_id NULL FK leads,
  phone_e164, status IN (running, waiting, done, stopped) DEFAULT waiting, step_id, wake_at,
  waiting_call_id NULL FK calls, last_call_id NULL FK calls, attempt >= 0, trigger_ref,
  started_at, ended_at (set exactly when done/stopped), end_reason <= 64, goal_reached,
  created_at, updated_at; UNIQUE(follow_up_id, lead_id) WHERE running/waiting;
  UNIQUE(follow_up_id, lead_id, trigger_ref); UNIQUE(follow_up_id, phone_e164, trigger_ref)
  WHERE lead_id IS NULL)
follow_up_run_events(id, tenant_id, run_id FK, step_id, attempt, kind <= 32, result <= 64,
  call_id NULL (plain id), at, UNIQUE(run_id, step_id, attempt, kind))   -- APPEND-ONLY
  -- f4b8d2a6c913, D-940 Follow-ups (docs/FOLLOW-UPS.md). A journey, its steps frozen at each
  -- publish (a run finishes on the version it started on), one lead going through one
  -- version, and what happened at each step as short codes; the unique event key is what
  -- makes a worker retry a no-op. The only phone number is the run's own. All four FORCEd
  -- tenant_isolation; zero-rows proof `tests/follow_ups_rls_test.py`. Both erasures
  -- anonymize a run's number and stop it (`retention._erase_follow_up_runs`).
  -- `follow_up_scan(stale_s)` is the minute tick's per-tenant worklist (SECURITY INVOKER).
  -- The migration gives every organisation a live "Call new leads" (version 1) from its
  -- `lead_call_policies` agent, wait and retries; those four columns are no longer written.
prompt_versions(id, tenant_id, agent_id, version INT, body TEXT, compiled_t0_context TEXT,
  notes TEXT, created_by, published_at, UNIQUE(agent_id,version))   -- full history + rollback
  -- notes = operator-facing "why this version exists" ("rollback to v3", "new pricing").
  -- Deliberately NOT compiled_t0_context: that is a build artefact OF the version,
  -- reserved by D-39 for the T0 compiler.
extraction_schemas(id, tenant_id, agent_id, version INT, fields JSONB, published_at)
  -- `fields` holds the agent's BUSINESS fields only (D-715). The fixed core every lead
  -- carries — name, what they want (`need`), preferred time, other number, language,
  -- notes (`calevate_shared.lead_fields.CORE_LEAD_FIELDS`) — is composed in by every
  -- reader (`with_core`) and never stored, so no edit, template or draft can drop it. A
  -- stored field under a core key (an older agent's `need`/`preferred_time`) is shadowed
  -- by the core definition on read; its captured values stay under the same key.
  -- A template correction never rewrites a schema or prompt version in place: a lead
  -- records the version it was captured under. Migrations b3d7e2a9c461 (D-881, spoken
  -- money ranges), c8e2f4a6b913 (D-887, BHK sizes to 5BHK+), c8e4a1f7b2d5 (D-888) and
  -- d7c2e9a4f6b1 (D-894) queue `refresh_field_reason` / `refresh_example_lines` outbox jobs
  -- that write a NEW version only where the agent still holds the old wording word for
  -- word, and republish a live agent; anything an owner edited is left alone.
lead_field_drafts(id, tenant_id UNIQUE, status ENUM[queued,running,done,failed],
  fields JSONB NULL, model, error_code, requested_by, requested_at, completed_at)
  -- A custom business's ONE AI draft of its business fields (D-715, migration
  -- b4e8d2a61c90). UNIQUE(tenant_id) is "drafted once, never again"; a failed draft is
  -- re-queued on the same row. `fields` is the record of what was drafted; the client's
  -- edits are ordinary `extraction_schemas` versions. FORCEd tenant RLS.
lead_call_policies(id, tenant_id UNIQUE, calling_agent_id NULL FK agents SET NULL,
  wait_seconds 0..3600, hours_start TIME >= 09:00, hours_end TIME <= 21:00, days TEXT[],
  holidays DATE[] <= 60, after_hours ENUM[next_open,open_plus_3h,next_day,hold],
  retry_attempts 0..3, retry_interval_minutes 10..1440, detect_machines BOOL, updated_by)
  -- A client's plan for calling new leads (D-716, migration a9c4e2f7d138). No row = the
  -- defaults (call at once inside the platform window, no retries, machine check off).
  -- `detect_machines` is published to every agent as `voice.detectMachines`. FORCEd RLS.
lead_call_holds(id, tenant_id, lead_id FK leads CASCADE, agent_id, source,
  status ENUM[held,released,dropped], held_at, settled_at, settled_by, callback_id)
  -- Leads that arrived after hours on a "hold" plan (D-716); one open hold per lead
  -- (partial UNIQUE). Releasing books a `lead-release:` call back. No phone copied here.
  -- FORCEd RLS.
pipecat_agents(id, tenant_id → organizations RESTRICT, agent_id → agents RESTRICT,
  variant_id → prompt_experiment_variants RESTRICT NULL, engine_agent_ref TEXT UNIQUE,
  name, agent_config_version_id, resolved_config JSONB, created_at, updated_at)
  -- NO LONGER WRITTEN (D-763); dropped next release. Our own engine's record of an agent
  -- (D-592, migration e2f5a91c8d47), one per agent and per experiment arm
  -- (ux_pipecat_agents_agent_variant, D-663). FORCEd tenant RLS until the drop.
  -- `agent_config_versions` and `agent_config_attestations` (append-only) and
  -- `pipecat_kb_objects` were written only for that engine too and go in the same release.
phone_numbers(id, tenant_id, agent_id, e164 UNIQUE, series ENUM[140,160,standard],
  provider, engine_number_ref, dlt_status ENUM[pending,registered,blocked], purpose TEXT,
  engine_owned BOOL NOT NULL DEFAULT false, purchase_price_usd NUMERIC(12,4),
  monthly_rental_usd NUMERIC(12,4), released_at TIMESTAMPTZ,
  direction ENUM[inbound,outbound,both] NOT NULL DEFAULT 'inbound',
  activated_at TIMESTAMPTZ, client_inr_per_month NUMERIC(12,2),
  carrier_binding_id TEXT, rental_charged_from DATE)
  -- `direction`, `activated_at` and `client_inr_per_month` land with migration
  -- c9d41f7b2e08, the client's own browse/buy/assign flow.
  -- `provider` names who supplies the number: `ck_phone_numbers_provider_carrier` allows
  -- NULL, 'vobiz', 'plivo' or 'thinnest' (migration a3d9e6f1c204). Every number on
  -- ThinnestAI is 'thinnest'; 'vobiz' and 'plivo' are no longer written (D-763) and leave
  -- the CHECK next release.
  -- `carrier_binding_id` (migration d4a7b2c91e30, D-662): NO LONGER WRITTEN (D-763);
  -- dropped next release. It held our own carrier's attachment id for the number.
  -- `rental_charged_from` (migration e8b14d6a2c57, D-665) is the first rental period the
  -- CLIENT is charged for. NULL = from the purchase (every new number); the migration
  -- stamped each existing client-priced number with its first renewal date after the deploy,
  -- so the period under way then was never charged. The rental itself is a wallet `usage`
  -- debit (`meta.kind = number_rental`, ref `number_rental:<number_id>:<YYYY-MM>`) for a
  -- prepaid account, or a `one_time_charges` row of kind `number_rental` for an invoiced
  -- one, decided in `billing/number_rental.collect_number_rental` (§8).
  -- `direction` is what the client bought the number FOR and AUTHORISES NOTHING. No gate
  -- matches `series` to a campaign's classification (D-692, D-775).
  -- `activated_at` NULL means the holder's identity is unverified, and the ONE thing such
  -- a number cannot do is be bound to an agent — which, by D-420, is the only way any
  -- number reaches a handset. So KYC gates activation rather than the sale: a client may
  -- buy before verifying and still cannot place or take a call.
  -- `client_inr_per_month` is what the CLIENT pays, frozen at purchase from
  -- `number_price_attestations`; `monthly_rental_usd` is what the VENDOR charges US. A
  -- price and a cost are different facts and hard rule 7 binds both (NUMERIC, never float).
  -- D-537, migration d1e58c7a94f2. `engine_owned` is the one column that separates the two
  -- commercial models: a number WE bought through the voice engine (Model A, the inbound
  -- leg) from a connection the CLIENT holds on their own carrier account (Model B, still
  -- half the product). Releasing at the vendor stops a monthly charge for the first and
  -- does nothing for the second, and before this column they were the same row.
  -- THE TWO PRICES ARE THE VENDOR'S OWN QUOTE IN THE VENDOR'S OWN CURRENCY, and hard rule 7
  -- is honoured by both halves: NUMERIC never float, and the RUPEE lives in
  -- `usage_events.unit_cost_paid`, struck each month at that month's rate. Storing a rupee
  -- here would freeze one exchange rate into a recurring charge that is re-struck monthly.
  -- `released_at` is what stops the meter; the ROW survives a release because a closed
  -- month's cost query still refers to it.
  -- `engine_number_ref` HAD NO WRITER until D-537 and every inbound publish alarmed while
  -- reporting success — see `agents/service.provision_number` and `set_number_engine_ref`.
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
  -- D-693: on `thinnest` a rented number's `engine_number_ref` carries its workspace,
  -- `<number>@<org_…>` (`calevate_shared/engine_scope.py`) for a number in the client's own
  -- customer workspace; an unscoped ref is a number held in our developer workspace
  -- ("held in the platform account", testing only, `engine_numbers.is_platform_held`).
phone_number_holds(id, tenant_id, number_id FK phone_numbers, agent_id NULL,
  reason IN (account_closed, wallet_negative), held_at DEFAULT now(), release_at NULL
  (>= held_at), remind_at NULL, anchor_source NULL IN (vendor, recorded), detached_at,
  start_notice_at, reminder_notice_at, release_notice_at, ended_at NULL,
  end_reason NULL IN (resumed, released), created_at, updated_at)
  -- D-860, migration e8c4b1d7a352. A stopped client's rented number (account closed, or
  -- the wallet below zero for the console's `number_hold_after_negative_days`) is held:
  -- nobody answers it, no rent is charged, and it is released before the voice platform's
  -- next monthly renewal unless the client tops up or the account reopens.
  -- `uq_phone_number_holds_open` keeps one open hold per number and is the insert's conflict
  -- target; `release_at` stays NULL until the hold job has read the rent day; the three
  -- `*_notice_at` stamps are when each email was queued. FORCEd tenant_isolation
  -- (zero-rows proof `tests/number_holds_test.py`). Ids, instants and our codes only, so a
  -- tenant erasure leaves the rows, as it leaves `phone_numbers`.
engine_number_purchases(id, tenant_id → organizations RESTRICT, idempotency_key,
  vendor_number, workspace_id, agent_id NULL, direction ENUM[inbound,outbound,both],
  status ENUM[renting,recorded,refused,failed] DEFAULT 'renting', number_id NULL,
  refusal_code NULL, requested_by ENUM[client,admin], created_at, updated_at,
  UNIQUE(tenant_id, idempotency_key))
  -- D-693, migration d93b6f2a4c18. One number-purchase request in a client's own
  -- ThinnestAI workspace (`campaigns/engine_number_purchase.py`). Committed as `renting`
  -- BEFORE the vendor rents, because the rent charges our balance at once and documents no
  -- idempotency key (`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/
  -- phone-numbers/rent-phone-number.md:7,343-344`): a retry with the same key finds this
  -- row and answers its outcome, and an unfinished one is resolved by reading the number
  -- back, never by renting twice. The number itself is the `phone_numbers` row it points at.
  -- FORCEd §1 RLS.
engine_voice_clone_copies(id, tenant_id → organizations RESTRICT, voice_id,
  workspace_id, vendor_voice_id, vendor_clone_id, created_at, updated_at,
  UNIQUE(tenant_id, voice_id, workspace_id))
  -- D-693, migration d93b6f2a4c18. Maps our catalogue `voice_id` to the ids of a copy of
  -- one of our clones made in a client's own workspace. FORCEd §1 RLS.
  -- LEGACY since D-797: client agents speak our clones as shared clones, so nothing writes
  -- it; rows are read only to delete those copies when the clone is deleted
  -- (`agents/shared_clones.forget_clone`). Dropped in a later release (hard rule 8).
platform_voice_catalog gains sample_object_key TEXT NULL (D-693, migration d93b6f2a4c18):
  -- the sealed recording an admin clone was made from (`voice-clone-samples/
  -- <sha256(voice_id)>`). LEGACY since D-797: no longer written; read only to delete the
  -- object with its clone. Dropped with the table above.
```

`extraction_schemas.fields` shape (validated by Pydantic on write). `reason` is the
optional per-field free-text AI hint ("why this variable is needed"): it is fed to the
extractor to fill the field more accurately, and when empty the field name/label alone is
used.
```json
[
 {"key":"budget","label":"Budget","type":"number","reason":"Property budget in lakhs","required":true},
 {"key":"preferred_location","label":"Location","type":"text","reason":"Area/locality the caller wants","required":true},
 {"key":"bhk_size","label":"BHK","type":"enum","enum_values":["1BHK","2BHK","3BHK","4BHK","5BHK+"],"required":false},
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
  carrier TEXT NULL CHECK (carrier IS NULL OR carrier IN ('vobiz','plivo')),
                                       -- (D-663, migration f5c2a8e41d07, ck_calls_carrier_enum)
                                       -- NO LONGER WRITTEN (D-763); dropped next release, with
                                       -- INDEX ix_calls_carrier_live. Our own carrier's leg.
  carrier_call_id TEXT NULL,           -- NO LONGER WRITTEN (D-763); dropped next release. Our
                                       -- own carrier's call id. Still READ by both erasures,
                                       -- which quote it on a `telephony` processor-erasure task
                                       -- for rows from test calls placed before D-763 (D-664).
                                       -- INDEX ix_calls_tenant_carrier_call_id (migration
                                       -- d4a7b2c91e30) WHERE carrier_call_id IS NOT NULL.
  started_at, ended_at, duration_s INT, recording_url TEXT,     -- OUR storage, not engine's
  transfer_recording_url TEXT NULL,    -- the transferred leg's recording (D-533, migration
                                       -- b8d1f04c73a9): OUR key, same bucket, retention and
                                       -- erasure as recording_url; NULL unless the call handed over.
  carrier_recording_id TEXT NULL,      -- NO LONGER WRITTEN (D-763); dropped next release, with
                                       -- CHECK ck_calls_carrier_recording_id_shape and INDEX
                                       -- ix_calls_recording_uncopied. Our own carrier's recording
                                       -- id (D-668); read by the erasures as carrier_call_id is.
  recording_copied_at TIMESTAMPTZ NULL, carrier_recording_deleted_at TIMESTAMPTZ NULL,
                                       -- (D-670, migration c5d82f1a9e47) NO LONGER WRITTEN
                                       -- (D-763); dropped next release, with INDEX
                                       -- ix_calls_carrier_recording_undeleted. A ThinnestAI
                                       -- recording is copied by `engine/recording_source.py`
                                       -- into `recording_url`.
  disclosure_played BOOL, consent_recording ENUM[granted,declined,na],
  outcome_tag ENUM[call_back_booked,needs_you,answered,transferred,hung_up_early,missed],
                                       -- DERIVED from facts after extraction (crm/outcomes,
                                       -- founder decision 6, migration c4e8a1f7d290). The CHECK
                                       -- still admits resolved/needs_follow_up/dropped for one
                                       -- release (hard rule 8); nothing writes them.
  business_outcome TEXT, business_outcome_label TEXT,
                                       -- D-836 (c4e9a2f7b183): the key of the agent's own outcome
                                       -- the extraction model chose and its label AS IT READ THEN,
                                       -- beside outcome_tag (which keeps precedence on screen).
                                       -- CHECK both NULL or both set.
  sentiment ENUM[positive,neutral,negative],
  summary TEXT,                        -- ENGLISH; the engine's own when in Latin script, else
                                       -- the extraction model's.
  summary_local TEXT, summary_language TEXT, -- the same summary in the call's language
  summary_source ENUM[engine,extraction], summary_state ENUM[pending,ready,failed,empty],
  headline TEXT (<= 90 chars, stored redacted), next_step TEXT (stored redacted),
  callback_requested BOOL, translation_state ENUM[pending,ready,failed,not_needed,unavailable],
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
-- Also on `calls`, documented where they are produced: caller_memory_state (§7, D-513),
--   knowledge_state (migration e2a91c7f45b8; NO LONGER WRITTEN, D-763, dropped next
--   release: our own engine reported whether its knowledge pack loaded) and crm_notified_at
--   (migration e83b5d1a4c07: when the CRM fan-out was promised for this call).
-- FUNCTION carrier_lines_in_use(p_carrier, live_horizon, ring_horizon) → integer
--   (D-663, migration a6d3b9f52e18). NO LONGER CALLED (D-763); dropped next release. The dial
--   gate counts ThinnestAI's outbound lines with its own query under the same advisory lock
--   (`agents.service._hold_engine_line`, `engine/dial_lines.py`); the call row's status IS
--   the hold, so nothing has to release a line.
-- FUNCTION queued_dial_scan — the big red switch's recall scan — reaches `ringing` dials as
--   well as `queued` ones since migration b7e4c0a63f29 (D-663).
-- calls.engine_quality JSONB (migration a5d1c7e93f28, D-736): the voice platform's per-call
--   `quality`, as `CallQuality` (reply_ms_*/first_token_ms_* median/p90/max, turns, long
--   silences, interruptions, model errors, backup answers); numbers-or-null by CHECK. Since
--   D-902 it also carries `answer_ms_*` (the wait for the first word of the actual answer,
--   the reply time every screen leads with; NULL before 27 Oct 2026, never zero) and
--   `knowledge_turns`, inside the same numbers-only CHECK.
-- calls.engine_timeline JSONB NULL (migration d8f3a6c1e924, D-902): each turn's timings as
--   the voice platform timed them (`calevate_shared.events.CallTimeline`: first sound,
--   answer, and the split of the wait). Times only, no words. CHECK: an object holding a
--   `turns` array. NULL until `workers/call_timeline.fetch_call_timeline` stores it, and on
--   calls the platform timed nothing for; an empty timeline is never stored. Shown only to
--   an operator (view-as); clients see the typical answer wait.
-- calls.voice_settings JSONB NULL (migration b3f9d2a7c41e, D-896): `agents.voice_settings`
--   copied when the call row is first written, so reply times split by turn detection.
-- calls.not_placed_reason TEXT NULL IN (from_number_withdrawn, unstated) (migration
--   b7e2d4f9a613, D-842): why a booked call never rang, mapped by the adapter from the
--   vendor's `error` (`calevate_shared.events.NotPlacedReason`). The vendor's sentence is
--   never stored.
-- calls.paid_test_call BOOL NOT NULL DEFAULT false (migration b5d8f2a9c741, D-859): a test
--   call a paying account placed to the owner's own phone; a partial index on
--   (tenant_id, created_at) WHERE paid_test_call serves its daily cap.
-- FUNCTION call_reply_scan(since) (migration d3f8b2c6a417, D-770): SECURITY INVOKER loop over
--   live organizations that binds `app.tenant_id` per tenant and returns each completed call
--   since `since` with its quality, `slow_reply` signal and metered voice tier; the admin
--   Voice response time report reads it from an `admin_session()`. It also returns
--   `voice_settings` (b3f9d2a7c41e) and `engine_timeline` (d8f3a6c1e924), each by drop and
--   re-create because a changed return type cannot be `CREATE OR REPLACE`d.
-- TABLE call_engine_latency (migration b7d3e91c4a05): NO LONGER WRITTEN OR READ (D-770; its
--   only producer was the Pipecat loop, D-763); dropped in a later release (hard rule 8).
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
  business_outcome TEXT,            -- D-836: the model's choice of the agent's outcomes, kept
                                    -- so a re-drive writes the same calls.business_outcome
  unlisted JSONB,                   -- D-889: {field_key: the caller's words} for a choice
                                    -- field none of whose choices fitted (the field stays
                                    -- null). Caller words: erased with `data` by all three
                                    -- retention/erasure sweeps. CHECK: object or NULL.
  reread_attempts SMALLINT NOT NULL DEFAULT 0 (>= 0), reread_at NULL,
                                    -- D-841, migration e1d84b3c7a20: a reading that came
                                    -- back as a provider failure (`errors._model`) is read
                                    -- again by `workers/extraction_reread`, a bounded number
                                    -- of times within a day of the call.
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
lead_saved_views(..., screen TEXT NOT NULL DEFAULT 'leads' CHECK IN (leads, calls))
  -- A named filter and column set private to one person (migration a7e2c40d9b53, FORCEd
  -- tenant_isolation). Since e5a1c7d93b20 (D-893 L2) the Calls log saves views in the same
  -- table; a name is unique per person PER SCREEN (`uq_lead_saved_views_tenant_user_screen_name`).
```

## 6. Campaigns & Ingest

```
campaigns(id, tenant_id, agent_id, name, classification ENUM[promotional,transactional,service] NOT NULL,
    -- `transactional` stays in the CHECK for old rows; clients may file only promotional or
    -- service (D-773) and the launch gate refuses transactional (`classification_not_campaignable`).
  number_id → phone_numbers, dlt_template_id → dlt_templates,
  status ENUM[draft,scheduled,running,paused,completed,cancelled],
  schedule JSONB,   -- a pending start: {kind: 'one_time', start_at: <UTC ISO-8601>} or a weekly
    -- repeat {kind: 'recurring', start_at: <next occurrence>, rule: {...}}
    -- plus an optional {last_blocked: {at, rules[]}} when the gate refused that start.
    -- `kind` is a discriminator: the dispatcher refuses any value it does not know
    -- rather than firing it once (FLOWS §5). Stop (D-773) sets it NULL.
    -- NULL = no pending start or repeat. Read only by apps/api/campaigns/scheduling.py.
  concurrency INT CHECK (1..10), retry_policy JSONB,   -- shipped default:
    -- {max_attempts: 3, backoff_minutes: [30, 120]} — this per-CONTACT ladder is the one
    -- place backoff actually exists; the ARQ job ladder is flat (FLOWS §6). The client
    -- chooses it per campaign since D-773: 1–5 tries, each gap one of 15, 30, 60, 120,
    -- 240 or 1440 minutes (`campaigns.service.validated_retry_policy`).
  auto_pause_reason TEXT NULL CHECK (IN complaint_spike, out_of_credit, spend_cap),
    -- which automatic safety paused it (migration e7a3c5d9b1f4, D-773); maintenance and
    -- the healer have their own marker columns. Cleared by any move a person makes.
  complaint_reviewed_at NULL,
    -- the client confirmed they read the opt-outs behind a complaint-spike pause; Resume
    -- is refused until it is set, and both spike windows restart from it.
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
  -- launch is BLOCKED (`launch_blockers`) by named rules: the agent, the account (KYC, the
  -- no-cold-calls pledge, agreements, money; D-692), consent provenance, the number's
  -- binding and carrier, the national DND scrub for promotional, and an empty or all-DNC list.
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
  previous_secret_ref TEXT NULL, previous_secret_expires_at TIMESTAMPTZ NULL,
                                            -- both or neither (d5f1a3c7e902): the secret a
                                            -- rotation replaced, still signing until then
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
kb_sources(id, tenant_id, agent_id NULL, kind ENUM[file,url,text,call_corpus], name, uri,
  status ENUM[uploaded,parsed,pending_approval,approved,rejected,archived],
  submitted_by, approved_by, approved_at, rejection_reason, published_at,
  is_active BOOL, version INT, UNIQUE(tenant_id, name, version))
  -- D-689: a source belongs to the TENANT and every agent of the tenant answers from it.
  -- `agent_id` is deprecated (not written since migration e6b2d9f4a1c3; provenance on
  -- older rows; dropped in a later release), as is the same column on kb_uploads,
  -- kb_chunks (cleared) and kb_index_documents.
  -- A named source is VERSIONED, and publish eligibility is `approved_at IS NOT NULL`,
  -- not `status = 'approved'`: FLOWS §7's rollback republishes a version that an earlier
  -- publish ARCHIVED, and gating on the current status refused the only rows the
  -- recovery path exists for. Rejection never stamps approved_at, so a rejected source
  -- still cannot reach an agent.
  -- D-658: what the account's own people add is inserted `approved` with
  -- `approved_by = submitted_by` (a re-read of a page a member linked: submitted_by NULL,
  -- approved_by the linker) and published by a worker; `pending_approval` is left for
  -- what nobody in the account added (view-as, intake seed, a changed page an operator
  -- linked). A version an automatic publish finds superseded is set `archived`.
kb_documents(id, tenant_id, source_id, idx INT, title, content TEXT, meta JSONB,
  UNIQUE(source_id, idx))          -- idx = chunk order; the chunks ARE the document
  -- meta held the provider-side ids until D-519 and NO LONGER DOES: `engine_kb_ref` and
  -- `engine_kb_digest` moved to `engine_kb_routes` (migration f1c9e0a73b46), which
  -- migrates the values across and clears the keys. Do not write them here again.
engine_kb_routes(engine, engine_kb_ref, tenant_id, agent_id, source_id, digest,
  created_at, updated_at,
  PRIMARY KEY (engine, engine_kb_ref), UNIQUE (source_id, agent_id))
  -- ONE CLAIM PER (SOURCE, AGENT) since D-689: on an engine whose knowledge is per vendor
  -- agent, a source is one vendor object on each of the tenant's agents.
  -- THE CLAIM THAT TIES ONE VENDOR KNOWLEDGE BASE TO ONE TENANT. We run one engine
  -- account for every tenant and the vendor's knowledge base is an ACCOUNT-level object
  -- with no owner field, so this row is the only thing that says whose it is. Without it
  -- a published version cannot be withdrawn (D-41) and no erasure path can find it.
  -- `engine_kb_ref` is the handle the AGENT references (Bolna: the vector id), never the
  -- id the vendor's DELETE route takes — that one is recovered inside the adapter.
  -- The PK is the uniqueness that matters: two sources may not claim one vendor object.
  -- Globally readable + FORCEd tenant_isolation for writes, exactly like
  -- engine_agent_routes and for the same reason (the orphan question is cross-tenant);
  -- registered in RLS_EXEMPT_TENANT_COLUMNS with that reason.
  -- NO foreign key to kb_sources ON PURPOSE: the claim must OUTLIVE our own rows, or a
  -- retention expiry or a tenant erasure would delete the only record that can address
  -- the vendor's copy at the moment we promise a client it is gone.
  -- The row is deleted on detach, because a claim on an object we no longer believe
  -- exists is exactly what the orphan sweep must not see.
kb_uploads(id, tenant_id, agent_id, source_id, source_kind ENUM[pdf,url,docx,txt,csv,
  xlsx,image], original_key, original_filename, original_bytes, original_sha256,
  content_type, source_url, document_key, document_sha256, text_provenance ENUM[parsed,
  ocr], extractor, ingest_status ENUM[received,converting,conversion_unavailable,
  conversion_failed,processing,processed,error], ingest_detail, content_digest,
  last_checked_at, change_detected_at, read_state ENUM[reading,ready,failed] NULL,
  read_detail, page_count, UNIQUE(source_id))
  -- read_state/read_detail/page_count (D-893 L8, migration f2b7d4e9a1c6): how reading a
  -- PDF's or a link's words into kb_documents went, apart from ingest_status, because the
  -- PDF is published as its file whether or not its words could be read. NULL for every
  -- kind the conversion lane reads.
  -- THE FILE, PHOTOGRAPH OR LINK BEHIND ONE kb_sources VERSION (D-534, migration
  -- b3f7c21ea940). 1:1 with that version, because an upload IS a knowledge source: it is
  -- approved, versioned, published, superseded and expired by the machinery above. What
  -- lives here is only what is true of an uploaded ORIGINAL; the review state, the
  -- submitter and the live flag stay on kb_sources and are NOT duplicated.
  -- WHAT EACH KIND BECOMES: a `pdf` is handed to the engine as the client's own bytes
  -- (document_key = original_key), so what is published is the file itself; a `url`
  -- is scraped BY the engine (no document_key, nothing of ours to upload); every other
  -- kind has its TEXT extracted by the conversion lane
  -- (`calevate_shared.document_ingest`), chunked into kb_documents, and published through
  -- the one renderer — so a client's own bytes pass the same automated text gate as typed
  -- knowledge (`kb/service._FORBIDDEN_CODEPOINTS`).
  -- NO `rag_id`-shaped second vendor identifier: the handle an agent references lives on
  -- engine_kb_routes and nowhere else (hard rule 2, `tests/kb_boundaries_test.py`).
  -- content_digest is OUR reading of a link's visible text, for change detection only —
  -- a materially changed page submits a NEW version: published in the linker's name when
  -- a member linked it (D-658), for review when an operator did, the live one serving
  -- until the new one is published. FORCEd RLS `tenant_isolation` in the same migration: every row either is the
  -- client's content or names an object-storage key that dereferences to it.
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
-- WHAT IT SERVES: the dashboard copilot and CRM search, never a call — in-call knowledge is
--   ThinnestAI's own knowledge base (D-689). Whether a managed store (Supermemory) may ever
--   replace it, the four reasons `kb_documents` stays ours whatever the store is, and the
--   three-release retirement it would take (stop reading, stop writing, drop) are TRD §6.3.
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
--  * A `call_summary` row is projected from the REDACTED summary
--    (`retrieval/call_projection.project_summary`); `calls.summary` itself is stored
--    unredacted. Migration e5b1d9c3a7f2 deleted the live summary rows built from raw text so
--    the sweep rebuilt them; tombstoned rows were kept, for the reason above.
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
-- ITS PRODUCER AND ITS SWITCH LANDED IN D-513: `calls.caller_memory_state`
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
  note TEXT NULL, language TEXT NULL)  -- BUILT (D-514, migration d8f31a7c2409)
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
-- grace_from TIMESTAMPTZ NULL (migration d4a7c3e91f26, D-914): a call-back belongs to the
-- campaign of the call it was promised on. While that campaign is paused the tick holds it
-- (`last_refusal_rule = campaign_paused`; no new status, the refusal pair says it); on
-- resume `release_resumed` makes it due at the first moment the calling hours allow and
-- the two-hour grace counts from `grace_from` instead of `requested_at`, which still never
-- moves. NULL on every call-back never held. Stopping the campaign calls its waiting
-- call-backs off (`controls.stop_campaign`, audit `callbacks.called_off`).
kb_retrieval_logs(id, tenant_id, call_id, query, tier ENUM[t0,t1,t2,t3,t4],
  top_score REAL, latency_ms INT)   -- powers knowledge-gap reports
  -- `top_ids UUID[]` was specified here and is NOT in the shipped table. Its stated
  -- condition — "add it with the chunks" — is now MET (D-502), but the blocker was never
  -- the chunks: this table still has no producer and cannot have one (see
  -- `apps/api/kb/models.py::KbRetrievalLog`), because the retrieval whose outcome it would
  -- log happens inside the engine. Add it with a PRODUCER, or not at all.
teach_questions(id, tenant_id, question_key, inputs_hash NULL, draft_status NULL
  ENUM[queued,ready,none], draft NULL, draft_source_kind NULL ENUM[profile,fact,answer,file],
  draft_source_label NULL, settled NULL ENUM[answered,dismissed], settled_reason NULL,
  settled_by NULL, settled_at NULL, UNIQUE(tenant_id, question_key))
  -- D-893, migration f2a6c8e1d5b9, FORCEd RLS. The Questions to answer list is computed on
  -- every read (`teach/questions.py`: open gaps by topic, practice and setup questions);
  -- this row keeps only what cannot be recomputed: the owner's answer or dismissal of a
  -- question no open gap carries, and the draft with the fingerprint of the inputs it was
  -- written from (`draft IS NULL` iff no source). Tenant erasure deletes it.
```

## 8. Billing & Metering (append-only)

```
usage_events(id, tenant_id, call_id NULL, unit_type ENUM[telephony_s,stt_s,stt_min,
  tts_chars,tts_kchars,llm_tok_in,llm_tok_out,llm_ktok_in,llm_ktok_out,platform_min,
  number_rental,other,ai_assist_ktok_in,ai_assist_ktok_out,ai_stt_min,
  forwarding_test_min,whatsapp_msg,ai_assist_10ktok_cached_in,llm_10ktok_cached_in], qty NUMERIC,
  unit_cost_paid NUMERIC, occurred_at, meta JSONB)  -- INSERT-only; no UPDATE/DELETE grants
-- `ai_assist_10ktok_cached_in` (D-816, migration b4d2e9c71a58) — the share of an assist's
--   input the provider served from its prompt cache, per TEN thousand tokens at the attested
--   cached rung (`platform_model_prices.cached_input_usd_per_mtok`); `ai_assist_ktok_in`
--   then carries only the rest. Written only when the provider reported a count AND a rung
--   is attested; Gemini 3.1 Flash-Lite's $0.025/M is ₹0.0024 per thousand (1.05% off) but
--   ₹0.0238 per ten thousand.
-- `llm_10ktok_cached_in` (D-817, migration c8a3f5e19b62) — the same split for a ThinnestAI
--   call on our own Google key: the call's `cachedInputTokens` at the attested cached rung,
--   `llm_ktok_in` the rest; written only when ThinnestAI reported a count AND a rung is
--   attested. `meta.llm_input_tokens` / `meta.llm_cached_input_tokens` keep both counts.
-- `stt_min` (D-638, migration c5e8a1f47b92) — the STT leg per MINUTE of audio, written
--   only for an engine that reports a per-leg cost breakdown; a ThinnestAI call is metered
--   per attested minute (TRD §10.0) and writes none. Per second the Saaras rate (₹30/hour =
--   ₹0.008333…/s) stores as 0.0083 in NUMERIC(12,4), 0.4% light; per minute it is ₹0.5000
--   exactly. `stt_s` is written by nothing any more and stays in the CHECK for the rows
--   already on the ledger; every reader costs a row as `qty * unit_cost_paid` in its own
--   unit, so both sum correctly.
-- INDEX ux_usage_events_tenant_call_stt_min UNIQUE (tenant_id, call_id, unit_type)
--   WHERE call_id IS NOT NULL AND unit_type = 'stt_min' (c5e8a1f47b92).
-- `llm_tok_*` vs `llm_ktok_*` (D-592, migration a3f1c6e82d47). `llm_tok_in`/`llm_tok_out`
--   carry a rented engine's reported leg charge at `qty = 1`, with no token count to price
--   against. `llm_ktok_in`/`llm_ktok_out` carried a real token count in thousands, with the
--   attested per-thousand rate in `unit_cost_paid`; they are NO LONGER WRITTEN (D-763) and
--   stay in the CHECK for the rows already on the ledger (an append-only ledger keeps its
--   history; the units leave the CHECK only if no row holds them). Two unit types rather
--   than a re-reading of the old two, because a `qty` whose unit depends on which engine
--   ran the call is a column no reader can sum. THOUSANDS for `ai_assist_ktok_*`'s
--   arithmetic: `unit_cost_paid` is NUMERIC(12,4) and `gpt-4o-mini` input at ~₹0.0000144 a
--   token stores as 0.0000.
-- INDEX ux_usage_events_tenant_call_ktok UNIQUE (tenant_id, call_id, unit_type)
--   WHERE call_id IS NOT NULL AND unit_type IN ('llm_ktok_in','llm_ktok_out')
--   (a3f1c6e82d47), on `ux_usage_events_tenant_call_kchars`' pattern.

call_metering_refusals(id, tenant_id, call_id, leg, code, detail, remediation,
  occurred_at, created_at)                          -- INSERT-only; no UPDATE/DELETE grants
-- NO LONGER WRITTEN (D-763); dropped next release. A leg of one call on our own engine
--   that could not be honestly priced (D-592, migration a3f1c6e82d47): a refused leg had no
--   honest `usage_events` representation (`qty = 0` meters real spend as free), so the
--   refusal was recorded here instead. On ThinnestAI an unpriced minute is a `usage_events`
--   row with a NULL cost and an alarm (TRD §10.0). Append-only and FORCE-RLS'd until the
--   drop; every column is an id, a machine code or prose this repository authored.
-- INDEX ix_call_metering_refusals_tenant_occurred (tenant_id, occurred_at DESC).
-- `tts_chars` vs `tts_kchars` (D-547, migration f4b90c1d7e26) — TWO synthesizer units,
--   because there are two ways to know what synthesis cost and they are not the same
--   measurement. `tts_chars` carries the ENGINE's own reported leg charge at `qty = 1`
--   (the engine buys the synthesis and bills us for it, reporting no character count).
--   `tts_kchars` carries OUR OWN count for a voice on our own key — on ThinnestAI the Studio
--   voice, Cartesia on our key, which Cartesia bills to us directly and ThinnestAI does not
--   — so the cost is the operator-attested Cartesia rate (`platform_tts_prices`) times the
--   characters the agent spoke, counted from
--   `transcript_turns`. `pipeline._tts_cost_row` writes one or the other, decided by the
--   voice, never both — and writes NEITHER rather than a zero when a BYOK call has no
--   attested price, because a fabricated ₹0 on an append-only ledger reads exactly like a
--   working leg. The unit is a THOUSAND characters for `ai_assist_ktok_*`'s reason:
--   `unit_cost_paid` is NUMERIC(12,4), and ₹3.4496 per 1,000 characters stores per
--   character as 0.0034 — our own cost, 1.4% light, for ever.
-- INDEX ux_usage_events_tenant_call_kchars UNIQUE (tenant_id, call_id, unit_type)
--   WHERE call_id IS NOT NULL AND unit_type = 'tts_kchars' AND created_at >= cutoff
--   (a3c62f8b4d19). The natural key for the sixth metered unit, as a SECOND partial index
--   disjoint from `ux_usage_events_tenant_call_unit` rather than a wider version of it:
--   widening in place means dropping the key that protects four live legs and rebuilding it
--   CONCURRENTLY over the whole table, whose failure mode is an INVALID unique index that
--   rejects insertions while being useless. The two predicates are disjoint, so together
--   they ARE the wider key.
-- INDEX ix_usage_events_call_id (call_id) WHERE call_id IS NOT NULL (c9e2a7b41d63). The
--   post-call metering guard, `_pipeline_settled`'s EXISTS and the unmetered-calls panel all
--   probe by call; offered only `tenant_id` each was a scan of the tenant's ENTIRE metering
--   history to find at most five rows (25.794 ms / 3,617 buffers at 225,000 → 0.024 ms / 4).
--   PARTIAL because `number_rental` and the `ai_assist_*` units carry no call — and a partial
--   index still serves the FK check, since `call_id = $1` under a strict operator proves the
--   predicate.
-- INDEX ux_usage_events_carrier_cdr UNIQUE (tenant_id, call_id) WHERE call_id IS NOT NULL
--   AND unit_type = 'other' AND meta->>'kind' = 'carrier_cdr' (migration d4a7b2c91e30,
--   D-662). Our own carrier's CDR set our cost for a call as one compensating row; NO
--   LONGER WRITTEN (D-763), and the index is dropped next release.
-- `number_rental` FINALLY HAS A WRITER (D-537): `apps/api/billing/number_rental.py`, one row
--   per bought number per IST billing month, idempotent in the DATABASE on the ref
--   `number_rental:<number_id>:<YYYY-MM>` against `ux_usage_events_tenant_unit_ref`. `qty` is
--   1 — ONE MONTH, never thirty days and never a proration, because the vendor charges a
--   whole month on a renewal date. It is the only cost in this system no event produces, so
--   `workers/number_rental.meter_number_rentals` is a cron rather than a handler, and
--   `attribution.UnattributedCost` — built for exactly this callless row and never populated
--   until now — is what keeps every total that claims to be a partition one.
-- INDEX ix_usage_events_tenant_occurred (tenant_id, occurred_at) (c9e2a7b41d63). Every money
--   rollup is "this tenant, this month" (33.788 ms / 3,822 buffers → 2.058 ms / 74). It is
--   also what made the month predicate indexable AT ALL: `to_char(... ) = :month` is STABLE,
--   so it can be neither an index condition nor an index expression, and
--   `plans.ist_month_window` now hands SQL a half-open range instead (D-209).
platform_tts_prices(provider, effective_from, inr_per_1k_chars NUMERIC(12,6),
  attested_by FK admin_users, attested_at, source_note)   -- INSERT-only (hard rule 4)
-- PK (provider, effective_from) (migration e1d75c2b8a43). The operator-attested TTS price,
--   and the TTS twin of `platform_model_prices`: hard rule 7 has no REPORTED tier, a BYOK
--   synthesizer leg costs ₹0 from the engine, and what the vendor bills is a MONTHLY PLAN
--   with a character allotment that no payload can report — so the only figure that may
--   reach `unit_cost_paid` is one a human read off an invoice and typed in.
-- RUPEES per THOUSAND CHARACTERS, not the LLM table's USD per million tokens. The figure is
--   derived by the operator from a plan (Startup: ₹4,312 / 1.25M chars = ₹3.4496/1k), so the
--   division and any conversion have already happened by the time it can be read; storing
--   dollars would mean asking somebody to un-divide it. `source_note` is REQUIRED and is
--   where the plan, its period and any fx used are recorded.
-- ⚠ UNKNOWN, and not resolved by the table: the vendor's OVERAGE rate past the allotment
--   (plan ADDENDUM 1, unknown #3). An attestation prices a character INSIDE the allotment; a
--   deployment running past it pays more than this says. That is a vendor question.
-- Platform-scoped (one vendor account for the whole deployment), so no `tenant_id` and a
--   written reason in `db/registry.RLS_EXEMPT_TENANT_COLUMNS`. Append-only with the shared
--   `calevate_forbid_mutation` / `calevate_forbid_truncate` triggers, both ENABLE ALWAYS: a
--   correction is a NEW effective instant so a re-rendered month resolves the price its
--   characters were metered at. `ops/model_pricing.tts_price_is_billable` is the ONE door
--   that decides whether a voice tier may be offered at all.
platform_cost_attestations(subject IN (thinnest_topup_fee, razorpay_topup_fee,
  thinnest_number_month), effective_from, value NUMERIC(14,6) >= 0 (< 1 for the two fees),
  attested_by NULL FK admin_users, source_note (>= 3 chars), expires_at NULL, created_at)
  -- PK (subject, effective_from); D-840, migration d8a4c2e7f150, `billing/cost_attestations.py`.
  -- The cost inputs that are not a per-minute price but still reach money: the voice
  -- platform's wallet top-up fee (a fraction on every minute it bills), the gateway's fee on
  -- a client top-up (counted in the cost floor) and the monthly rent of a number rented in
  -- the voice platform's console. The 2.36% top-up fee that used to be a code constant is the
  -- carried-over first row (`attested_by` NULL, effective from the epoch, VENDOR-STATED in
  -- ThinnestAI's email of 12 Oct 2026); the gateway fee and the number rent are NOT seeded.
  -- Platform-scoped (RLS_EXEMPT_TENANT_COLUMNS), APPEND-ONLY with the shared triggers,
  -- ENABLE ALWAYS: an editable figure would re-price minutes and rentals already metered.
platform_in_call_data_use(provider, attested_at, attested_by FK admin_users,
  vendor_account_ref, paid_tier_confirmed BOOL, no_training_opt_in_confirmed BOOL,
  source_note)   -- PK (provider, attested_at); D-839, migration a3d8f1c6e092
  -- The operator's attestation about a provider's data-use terms for RAW CALLER SPEECH on our
  -- own model, the shape of `platform_dashboard_data_use` (D-477) with its own statement and
  -- step-up `attest_in_call_data_use:<provider>`; `own_model_readiness` reads this one only.
  -- Platform-scoped (RLS_EXEMPT_TENANT_COLUMNS), APPEND-ONLY, ENABLE ALWAYS.
copilot_consents.kind TEXT NOT NULL DEFAULT 'accepted' IN (accepted, withdrawn)
  -- Same migration (D-839). The append-only consent table (D-788) records the owner turning
  -- Pip off as a later `withdrawn` row; `copilot/consent.read_consent` judges the latest row.
refund_intents gains failed_at NULL and refund_ref NULL (migration e5c1a9d3f720)
  -- A refund attempt that failed definitively is kept with `failed_at` (excluded from the
  -- refund ceiling) instead of being deleted, so the next attempt counts it and derives a new
  -- `X-Refund-Idempotency` key; `refund_ref` is the gateway refund id the claim became, so a
  -- `refund.failed` webhook fails exactly that claim. Tenant policy unchanged.
plans(id, tenant_id, setup_fee, monthly_fee, included_min INT, overage_rate,
  overage_rate_second NUMERIC NULL, overage_rate_value NUMERIC NULL,
  hard_cap_min INT, hard_cap_spend NUMERIC,
  client_cap_min INT NULL, client_cap_spend NUMERIC NULL,
  concurrency_ceiling INT DEFAULT 10, effective_from, effective_to)
  -- `overage_rate_second` is the plan's SECOND overage-rate slot — a founder pricing
  -- lever, NOT a voice quality (nothing about which voice spoke chooses a rung; that is
  -- `usage_events.meta.voice_tier`). NULL means the plan quotes no separate second rate
  -- and everything bills at `overage_rate` (migrations b1d5c8e73f04, c72b9e40af15).
  -- `overage_rate_value` is the name it replaces and is MID-DEPRECATION (D-558, hard
  -- rule 8 step 1): still written from the same bind by `billing/terms.py::record_terms`
  -- and still read as the fallback half of `billing/plans.py::OVERAGE_RATE_SECOND_SQL`,
  -- so a process that has not been redeployed prices a month identically. Step 2 drops
  -- it; dropping it in the release that stopped writing it is what rule 8 forbids.
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
credit_ledger(id, tenant_id, delta NUMERIC,
  reason ENUM[topup,usage,adjustment,refund,bonus,grant],
  ref, balance_after, occurred_at, meta JSONB)          -- INSERT-only (hard rule 4)
-- `bonus` (c3a9f1e6b820) and `grant` (a71f3c9e5d84, D-535) are the two reasons that put
--   credit on a wallet WITHOUT a client paying — `billing/models.GRANTED_CREDIT_REASONS`,
--   against `PAID_CREDIT_REASONS` which is `topup` alone. `service.credit_totals` is the
--   ONE definition of the split and both the operator's wallet panel and the client's own
--   statement publish it: credit we GAVE reading as credit they BOUGHT would inflate the
--   revenue side of our own margin figures, which is the lie D-39 refused when it declined
--   to seed opening balances. `usage`/`adjustment`/`refund` are in NEITHER set — they are
--   movements, not origins, and letting a correction subtract from `granted_inr` would
--   understate what a client was actually given.
-- A REFUND OF A PACK TAKES ITS BONUS BACK (founder decision, 4 Oct 2026, D-672):
--   `payments.credit_refund` writes the `refund` row (ref = refund id) and, in the same
--   transaction and under the same `lock_tenant_credits`, a NEGATIVE `bonus` row keyed on
--   the SAME refund id (`meta.kind = 'credit_pack_bonus_clawback'`, `meta.payment_ref`,
--   `meta.refund_ref`) — distinct from the grant's key (the payment id), so
--   `ux_credit_ledger_bonus_ref` makes it idempotent. Size: the cumulative target
--   bonus × (refunded so far ÷ amount paid), half-up to `MONEY_Q` and clamped at the bonus,
--   minus what earlier refunds of the payment already took — so partials that sum to the
--   payment take back exactly the bonus. It comes off the bonus's own `bonus_legacy` lot and
--   is `allow_negative`, like the refund: a spent bonus becomes overdraft. It is in
--   NEITHER total of `credit_totals` (a movement, as `refund` is) and the client reads it as
--   "Pack bonus taken back after a refund" (`wallet_routes._entry_label`). Unreachable for
--   a purchase made today: every catalogue pack has `bonus_pct = 0` since D-547.
-- INDEX ux_credit_ledger_grant_ref UNIQUE (tenant_id, ref) WHERE reason = 'grant'
--   AND ref IS NOT NULL (a71f3c9e5d84). The `bonus` index's shape, for the same reason: a
--   brand-new reason has no pre-fix duplicate residue, so it needs no cutoff and rebuilding
--   f9c2b41a8e57 to fold it in would be heavier and riskier than a clean index. The key is
--   an OPERATOR-SUPPLIED reference and NOT a content address over (amount, reason): two
--   goodwill grants of the same size to one client two months apart are ordinary, and a
--   content address would report the second as a replay of the first.
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
credit_lots(id, tenant_id, source ENUM-as-CHECK[topup,grant,bonus_legacy,migration,override],
  pack_id NULL, override_of_pack_id NULL,
  credits_total NUMERIC(12,4), credits_remaining NUMERIC(12,4),
  clear_inr_per_min NUMERIC(12,4), studio_inr_per_min NUMERIC(12,4),
  ledger_entry_id UNIQUE FK credit_ledger(id), opened_at, closed_at NULL, expires_at NULL,
  created_at, updated_at)                    -- NOT append-only, and NOT in APPEND_ONLY_TABLES
-- WHAT IT HOLDS AND WHY IT EXISTS (D-547, `docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md` §3.1).
--   A credit is still ₹1. EXPIRY (D-840, on since D-897, 27 Oct 2026, Terms 6.1 revision 19):
--   a purchase (`source = topup`) opened while `Settings.credit_pack_expiry_months` is set
--   (default 12) gets `expires_at` = opened_at + that many IST calendar months, frozen with the
--   lot's other terms; grants, overrides and every lot opened before the switch carry NULL
--   and never expire. `workers/credit_expiry.expire_credit_lots` (daily 08:11 IST) lapses what
--   is left by one negative `adjustment` row (`meta.kind = credit_expiry`) and closes the lot,
--   and promises one `notify_credit_lapsing` email per lot 30 days before.
--   What a bigger pack buys is no longer BONUS
--   CREDITS on the balance — it is a CHEAPER MINUTE, and a minute has two prices because the
--   voice tier is chosen per agent (`clear` | `studio`). A price that varies by purchase
--   cannot live on the tenant and cannot live on the ledger row that spends it: it belongs to
--   the credits themselves. A lot IS that grouping — the credits one purchase (or grant, or
--   the migration, or an operator override) created, carrying the two per-minute rates FROZEN
--   at the moment it was opened.
-- CHECKS: `source IN ('topup','grant','bonus_legacy','migration','override')`;
--   `credits_total > 0`; `credits_remaining >= 0 AND credits_remaining <= credits_total`;
--   `clear_inr_per_min > 0`; `studio_inr_per_min >= clear_inr_per_min`. The last one is
--   the card's own shape made structural: the Studio rung is never the cheaper of the two
--   on any pack, so a row that says it is is a data defect, not a promotion.
-- ⚠ THE TWO RATE COLUMNS WERE `sarvam_inr_per_min` / `cartesia_inr_per_min` UNTIL
--   19 Sep 2026. They were named for the VENDORS then serving each rung, and one of those
--   vendors (Sarvam) left the synthesis leg entirely on 18 Sep 2026, leaving a money column
--   named after a company with nothing to do with it. Renamed to the RUNGS by
--   `f1c40d8b6e93`, which refuses to run against a non-empty `credit_lots` because these
--   rates are FROZEN at purchase — so from the first sale the names are frozen with them.
-- RLS: ENABLE + FORCE with the strict `tenant_isolation` policy for EVERY verb — the
--   repo-wide shape, NOT the `OR <guc> IS NULL` form `f2b91c47e0a3` had to correct on
--   `kb_uploads`. Registered in `db/registry.TENANT_TABLES`, so `check_rls_coverage` refuses
--   it if the registration is forgotten, and the migration ships its cross-tenant zero-rows
--   test.
-- WHY IT IS NOT APPEND-ONLY, AND WHAT REPLACES THE TRIGGER THAT WOULD HAVE SAID SO. Two
--   columns must mutate — `credits_remaining` falls as calls are billed, `closed_at` is
--   stamped when it reaches zero — so the table cannot be in `APPEND_ONLY_TABLES` and hard
--   rule 4's immutability trigger is not what guards it. The guarantee that actually matters
--   here is NARROWER and is enforced in its own right: trigger `credit_lots_terms_frozen`
--   REFUSES any UPDATE that changes a column other than `credits_remaining`, `closed_at` and
--   `updated_at`. So the two rates, the source, the pack and the opening ledger row are
--   immutable by the database, and a later rate-card change cannot reach credit already sold.
--   `check_ledger_immutability` is NOT the checker for this (it reads the append-only set);
--   `tests/credit_lots_terms_frozen_test.py` is.
-- INDEX ix_credit_lots_fifo (tenant_id, opened_at, id) WHERE closed_at IS NULL — the FIFO
--   scan, and the only access path the debit has. `id` is the tail for the same reason
--   `credit_ledger`'s recency index carries one: two lots opened in the same instant must
--   still have a TOTAL order, or two readers disagree about which one is next.
-- `ledger_entry_id` is UNIQUE, so a lot is one-to-one with the credit-adding ledger row that
--   opened it. That is what makes the pair re-derivable: the money movement is the ledger's,
--   the price is the lot's, and neither can exist without the other.
-- WHAT THE LEDGER GAINED, WHICH IS NOTHING STRUCTURAL. `credit_ledger` is UNCHANGED in shape
--   and still INSERT-only. A `usage` row carries `meta.lots`, the splits it drew — one entry
--   per lot the debit touched, in consumption order, EVERY ONE CARRYING A `kind`:
--     meta.lots = [{kind: "call", lot_id, credits, minutes, inr_per_min, voice_tier}, …]
--     meta.lots = [{kind: "ai_assist", lot_id, credits}, …]
--   ⚠ **THIS PARAGRAPH USED TO SAY `voice_tier` IS NULL ON A SPLIT THAT PRICED NO MINUTES,
--   AND THE BUILD DID NOT DO THAT** (plan ADDENDUM 2 §2.1). On an `ai_assist` split
--   `minutes`, `inr_per_min` and `voice_tier` are ABSENT KEYS, not nulls: the dashboard-AI
--   quota buys RUPEES of assistance at face value, so there is no rate and no voice, and a
--   key whose null means "not applicable" is the tri-state defect `AgentSnapshot.*_readable`
--   exists to avoid. `lot_id` follows the same rule — it is absent on the OVERDRAFT portion,
--   which came from no lot at all. A reader totalling TALK MINUTES filters `kind == "call"`;
--   one totalling MONEY sums `credits` across every split whatever its kind, and that sum IS
--   the row's own `delta`.
--   The D-455 language-model surcharge rides its call's OWN row as an `ai_assist` split for
--   exactly that reason: it is rupees, and its minutes are already counted by the call splits
--   beside it. The overdraft part, if any, is the last entry, priced at the rate of the lot
--   that ran out. A month's statement and the margin panel are re-derivable from those rows
--   ALONE (D-492/D-458 kept): nothing recomputes a price from today's card, and
--   `billing/service.voice_tier_usage` is the reader that proves it — a month's minutes and
--   charges per voice, read out of `meta.lots` and out of nothing else.
-- WHAT A CORRECTION DOES TO A LOT, which is not one rule but two, decided by DIRECTION:
--   * a compensating `adjustment` that takes credit AWAY restates the corrected entry's own
--     lot downwards (plan ADDENDUM 2 §2.2): `credits_total` falls by the correction,
--     `credits_remaining` FLOORS at zero, and whatever the lot had already spent becomes
--     wallet overdraft, which the balance carries and the next purchase repays first. The
--     RATES do not move — what was sold at ₹4.70 was sold at ₹4.70 even when the amount was
--     wrong.
--   * a purchase reversed IN FULL, or a correction of a credit row that opened no lot at all
--     (one written before this table existed), cannot be a restatement: `credits_total > 0` is
--     a CHECK, so a lot cannot be restated to nothing. That credit is spent off the FIFO queue
--     at FACE VALUE instead — the rule every other debit obeys, and the only one that keeps
--     invariant 1 true. `billing/service.remove_credit_from_lots` is the one door for both.
--   * a `topup` RESTATEMENT (the under-credited payment repair) is the opposite direction and
--     lands on the SAME lot: one bank transfer was sold at one card, so the difference grows
--     that purchase's lot rather than opening a second one behind it.
-- THE FOUR INVARIANTS THAT BIND THE PAIR (each one a test, plan §2.3.1–4):
--   1. `SUM(credit_lots.credits_remaining) = the wallet balance` for every tenant, whenever
--      the balance is ≥ 0. THE BALANCE IS STILL `balance_after` ON THE NEWEST LEDGER ROW —
--      that is unchanged, it is still denormalised, and it is still what every reader reads.
--      The lots do not become a second source of truth for the balance; they are its
--      partition by price, and this invariant is what says so. A NEGATIVE balance means every
--      lot is at zero and the overdraft is `-balance`.
--   2. A debit consumes the lot with the smallest `opened_at` that still has
--      `credits_remaining > 0`, and SPLITS across lots when one runs out; each part is priced
--      at ITS lot's rate for the call's voice tier. So one call can be billed at two
--      different per-minute prices, and the ledger row says which.
--   3. A lot's two rates NEVER change after creation — the trigger above, not a convention.
--   4. Overdraft minutes are priced at the rate of the last lot consumed, and the NEXT
--      credit-adding entry repays the overdraft FIRST and opens its lot with the remainder.
--      A lot is therefore never opened while the wallet is negative.
tenant_trials(id, tenant_id, days, started_at, ends_at,
  status ENUM[active,converted,expired,stopped], ended_at NULL, ended_reason NULL,
  erase_after NULL, erasure_filed_at NULL, started_by NULL)   -- NOT append-only (D-536)
-- A time-boxed period a client is billed NOTHING for (migration a71f3c9e5d84). It is a
--   STATE row, UPDATEd once from `active` to a terminal status and never summed into a
--   balance, so it is deliberately absent from `db/registry.APPEND_ONLY_TABLES` and carries
--   no immutability trigger — the reading `topup_attempts` gets, for the same reason. What
--   a trial COSTS is still recorded where money facts live: `usage_events` meters every
--   minute with our real `unit_cost_paid` throughout. What does NOT happen is a
--   `credit_ledger` debit, and there is no `credit_ledger` row of any kind — the founder
--   refused "grant them credit and let the normal gate honour it" precisely because the
--   ledger would then assert they were given money nobody gave them.
-- IT IS NOT `organizations.plan_tier = 'trial'`. That column answers two standing
--   questions about a MOTION (does this account pay from a wallet; did a stranger open it
--   unattended) and has no clock. A `managed` client can be given a trial and a
--   `trial`-tier signup can be outside one.
-- CHECK ck_tenant_trials_days_range (days BETWEEN 1 AND 365). The founder chose days with
--   NO spend ceiling, so days are the only bound this arrangement has — bounded at the API
--   boundary AND here, because a bound only a route enforces is not a bound against a
--   script.
-- CHECK ck_tenant_trials_ended_iff_not_active ((status='active') = (ended_at IS NULL)).
--   "Open" is one fact stored once; a row reading `expired` with a NULL `ended_at` is one
--   the erasure sweep would schedule from a NULL and skip for ever.
-- INDEX ux_tenant_trials_active UNIQUE (tenant_id) WHERE status = 'active'. At most one
--   open trial per client as a database fact rather than a reader's `if`: two operators
--   starting one at the same moment would otherwise both read "none open" and both insert.
-- INDEX ix_tenant_trials_tenant_recent (tenant_id, started_at DESC, id DESC). Every
--   surface reads the NEWEST trial (a screen has to be able to say "their trial ended on
--   the 3rd"), so the plan walks to one row instead of sorting the account's history.
-- `erase_after` is the earliest instant a NON-CONVERTING client's personal data may be
--   erased — the grace period the founder sets, frozen onto the row at start so a moved
--   platform default cannot move the date of a client already inside their window. NULL
--   for ever once the trial converted: their leads, calls and transcripts are the value
--   they just built. `apps/workers/trials.py` FILES a tenant erasure through
--   `compliance/tenant_erasure.py` when it falls due and erases nothing itself.
one_time_charges(id, tenant_id, kind ENUM[setup_fee,number_rental], ref, description,
  amount NUMERIC, billing_month, plan_id NULL, occurred_at)  -- INSERT-only (hard rule 4)
-- kind `number_rental` (D-665, migration e8b14d6a2c57, ck_one_time_charges_kind_enum): an
--   INVOICED (managed) account's phone-number rental, one row per number and period
--   (ref `number_rental:<number_id>:<YYYY-MM the period starts in>`, the same ref a prepaid
--   account's wallet debit carries), printed as a "Phone number rental" line by
--   `billing/number_rental.rental_statement_lines`. Written by the purchase and by the daily
--   `workers/number_rental.renew_number_rentals`; there is no monthly invoice job.
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
  -- D-692 (migration a7c3e91d5f20) adds: kyc_path ENUM[manual,digilocker], legal_business_name,
  -- gst_registered BOOL, gstin (format CHECK, only when GST-registered), owner_id_type
  -- ENUM[aadhaar,pan] + owner_id_masked (CHECK pins XXXX-XXXX-dddd / XXXXXddddX), name_match,
  -- digilocker_required + _reason/_at/_by_admin_id (reason required when set) and
  -- digilocker_verified_at. `kyc_blocker` is now the dial gate on EVERY tier, plus
  -- `kyc_digilocker_required`. Untenanted SELECT arm `kyc_records_review_queue_read` (status
  -- submitted/in_review only) feeds the admin review queue.
  -- D-696 (migration c5e9a2d71b48) adds: owner_pan_checked BOOL NOT NULL DEFAULT false +
  -- owner_pan_checked_at + owner_pan_checked_by_admin_id → admin_users RESTRICT (CHECK: the
  -- three set together) — the reviewer matched PAN, name and date of birth at the Income
  -- Tax "Verify Your PAN" service before a manual approval; no date of birth is stored. CHECK
  -- `no_manual_aadhaar_awaits_review`: a manual-path row with owner_id_type aadhaar cannot be
  -- submitted/in_review (the manual path takes a PAN card only; aadhaar stays for DigiLocker
  -- and for reviews decided before D-696).
kyc_documents(id, tenant_id → organizations RESTRICT, slot ENUM[business,owner_id],
  kind (business: gst|incorporation|udyam; owner_id: pan_card, or aadhaar on rows from
  before D-696 only), object_key,
  filename (1-99), content_type ENUM[pdf,jpeg,png], size_bytes (1..5 MiB), sha256,
  uploaded_by_user_id → users, payload_nonce, dek_wrapped, dek_nonce, kek_version,
  superseded_at, purged_at, created_at, updated_at)
  -- D-696 CHECK `aadhaar_copy_never_held`: kind aadhaar implies delete_requested_at set, so
  -- no Aadhaar copy is held; the migration requested deletion of every earlier one.
  -- D-692. Metadata of uploaded KYC files; the bytes are envelope-sealed ciphertext under
  -- `kyc-documents/{tenant}/`. One current row per slot (partial unique index). Owner-ID
  -- files are purged on the review decision or after 30 days (untenanted SELECT arm
  -- `kyc_documents_owner_id_purge_read`); the business certificate is kept while the
  -- account is open. FORCEd §1 RLS.
  -- purge_failures INT NOT NULL DEFAULT 0, purge_failed_at NULL (migration c7e4a9d2f513):
  -- failed deletes are counted so `workers/kyc_owner_id_purge` tries never-failed files
  -- first and raises `kyc_purge_stuck`, instead of a batch of failing rows starving the rest.
outbound_pledge_acceptances(id, tenant_id → organizations RESTRICT, pledge_version INT > 0,
  text_sha256, accepted_by_user_id → users, ip, accepted_at, created_at)   -- INSERT-only
  -- D-692. The no-cold-calls pledge; the gate compares the latest row's version with
  -- `compliance.outbound_pledge.PLEDGE_VERSION`. Append-only + TRUNCATE triggers, ALWAYS.
kyc_verification_requests gains id_document ENUM[aadhaar,pan] NULL (D-692).
autodialer_notices(id, tenant_id → organizations RESTRICT, state ENUM[notified,withdrawn],
  access_provider TEXT NULL, objective TEXT NULL, notified_on DATE,
  notice_reference TEXT NULL, declared_clis TEXT[] NOT NULL DEFAULT '{}',
  attestation_version SMALLINT NULL, attestation_sha256 TEXT NULL (64 hex),
  recorded_by → users RESTRICT, created_at)          -- INSERT-only (hard rule 4)
  -- D-941 (migration d941a2c7e5b3): the client's declaration of the numbers its automated
  -- calls come from, read by the dial gate from `a2p_declaration_enforced_from`. The
  -- LATEST row is the current position (INDEX ix_autodialer_notices_latest_for_tenant), a
  -- withdrawal a new row. CHECKs: version and SHA paired; a row is attested OR carries
  -- the D-637 provider and objective. D-637 rows (migration e5c1a70b93f4, CLIs from
  -- f39583a282fb) carry no attestation and cover no dial.
-- consent_ledger also carries ix_consent_ledger_callback_lookup (tenant_id, phone_e164,
--   captured_at DESC, id DESC) WHERE purpose = 'callback' and ix_consent_ledger_withdrawn_call
--   (call_id) WHERE status = 'withdrawn' AND call_id IS NOT NULL (migration e95e0d780629),
--   the two reads the callback consent check makes.
carrier_compliance_applications(id, tenant_id → organizations ON DELETE RESTRICT,
  carrier ENUM[plivo,vobiz] NOT NULL, UNIQUE (tenant_id, carrier),
  status ENUM[not_started,documents_required,submitted,accepted,rejected,expired] NOT NULL
    DEFAULT 'not_started',
  carrier_application_id TEXT NULL,
  document_kind ENUM[gst_certificate,certificate_of_incorporation,udyam_registration] NULL,
  document_object_ref TEXT NULL, document_filename TEXT NULL,
  signed_application_ref TEXT NULL, rejection_reason TEXT NULL,
  recorded_by_admin_id → admin_users NULL, submitted_at, decided_at, + the four status CHECKs)
  -- NO LONGER WRITTEN OR GATED ON (D-763); dropped next release. A tenant's compliance
  -- application with our own carrier (migration c7a4f9e15b03, D-662, D-666). On ThinnestAI
  -- the equivalent is the client workspace's business-details application, read from the
  -- vendor (`tenant_engine_workspaces`, THINNEST-INTEGRATION §3a). The retention sweep still
  -- reads the table so any document bytes its two `*_ref` columns point at are erased with
  -- the tenant; the document bytes were never stored in the row.
first_campaign_reviews(id, tenant_id UNIQUE → organizations ON DELETE RESTRICT,
  status ENUM[approved,rejected] NOT NULL,
  reviewed_campaign_id → campaigns ON DELETE SET NULL,
  decision_note TEXT NOT NULL, decision_source ENUM[operator,migration_backfill] NOT NULL
    DEFAULT 'operator',
  decided_by_admin_id → admin_users NULL, decided_at NOT NULL,
  CHECK (decision_source <> 'operator' OR decided_by_admin_id IS NOT NULL),
  CHECK (length(btrim(decision_note)) >= 3))
  -- NO LONGER READ OR WRITTEN (D-783, 15 Oct 2026); dropped in a later release. It held
  -- the D-51 manual review of a self-serve account's first campaign (migration
  -- c4d9e18a72b6): one mutable row per tenant, standard §1 RLS, absence meaning held. The
  -- founder removed the review; no gate asks it and no route reads or writes it. The
  -- decisions it recorded are also in `audit_log` (`first_campaign_review.decided`).
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
number_holders(id, tenant_id → organizations ON DELETE RESTRICT UNIQUE,
  holder_type ENUM[individual,business], holder_name TEXT, holder_email TEXT,
  recorded_by → users ON DELETE RESTRICT, created_at)
  -- WHOSE CONNECTION A BOUGHT NUMBER IS (migration c9d41f7b2e08). The registered owner is
  -- the CLIENT, not Calevate, and that is what separates connecting a number for a business
  -- from reselling numbers in our own name (LEGAL-OPS-PLAYBOOK stop-list, items 1 and 10).
  -- ONE ROW PER TENANT, collected once and reused for every number after the first:
  -- `tenant_id` is UNIQUE and the table carries `calevate_forbid_mutation` +
  -- `calevate_forbid_truncate`, both ENABLE ALWAYS, so "cannot be changed later" is a
  -- property. A holder edited after a number was registered would name an owner the
  -- operator's own record does not, and only theirs decides who is liable.

number_price_attestations(id, inr_per_month NUMERIC(12,2), source TEXT,
  attested_by → users ON DELETE RESTRICT, created_at,
  CHECK (inr_per_month > 0), CHECK (length(btrim(source)) > 0))
  -- WHAT A NUMBER-MONTH COSTS A CLIENT, in rupees, attested by an operator with the
  -- document they read it from — hard rule 7's standard, the one `billing/rates
  -- .llm_inr_per_ktok` and `agents/voice_offer.tts_price_is_billable` already apply.
  -- Until a row exists, no client can be quoted and no purchase proceeds; the vendor's own
  -- USD quote is OUR cost and never becomes a client-facing figure.
  -- PLATFORM-SCOPED (no tenant_id, no policy): one rate for every client. A per-tenant rate
  -- is a pricing decision nobody has taken (OPERATIONS §2 gate 26) and a table shaped for
  -- one would invite it to be taken by accident.
  -- Append-only: a rate change is a NEW row, because `phone_numbers.client_inr_per_month`
  -- froze what each number was sold at and editing the rate would leave those unexplainable.

outbound_sender_attestations(id, tenant_id → organizations ON DELETE RESTRICT,
  phone_number_id → phone_numbers ON DELETE RESTRICT,
  state ENUM[attested,withdrawn], statement_version TEXT,
  attested_by → users ON DELETE RESTRICT, created_at,
  CHECK (length(btrim(statement_version)) > 0))
  -- UNWRITTEN AND UNREAD SINCE D-775 (14 Oct 2026): the outbound sender attestation, its
  -- routes and its panel were removed, so no route, gate or screen touches this table.
  -- Kept with its rows, FORCEd RLS and append-only triggers; dropped in a later release
  -- (hard rule 8). It held a client's per-number confirmation that it was the sender of
  -- calls from an ordinary (non-140/160) number (migration b7e4c02fa519), latest row
  -- winning (INDEX ix_outbound_sender_attestations_latest_for_number), a withdrawal a new
  -- row, `statement_version` the wording accepted, `attested_by` the client's own user.
  -- Standard §1 RLS, FORCEd, created with the table.
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
  next_attempt_at NULL, outbox_message_id NULL,
  first_at, last_at)                 -- ONE row per delivery, not per attempt
  -- status 'retrying' + next_attempt_at: an outbound webhook waiting on its retry
  -- schedule; the retry sweep re-enqueues it from outbox_message_id (d5f1a3c7e902).
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
  -- consumed_at NULL (migration c8a4e2f7b913): written by the consumer once a run of the
  -- message succeeded and checked before the next run, so a re-publish after a lost
  -- `published` mark (arq dedupes a job id only within its `keep_result` window) does not
  -- repeat the side effect. NULL = no run recorded.
webhook_inbox_events(id, provider, event_key, payload_hash, status
  ENUM[processing,enqueued,processed,failed], event_name, duplicate_count INT NOT NULL
  DEFAULT 0, enqueued_at, processed_at, last_error,
  UNIQUE(provider, event_key))       -- same key + different hash = 409 (spoof signal)
  -- duplicate_count = how many times the same event arrived again after the first claim.
  -- It is the "deduplicated" column of the webhook activity view; without it a vendor
  -- retrying fifteen times looks like one quiet success.
idempotency_records(id, scope_key, route, method, idempotency_key, request_hash,
  status ENUM[processing,in_doubt,completed,failed], claim_nonce UUID NULL, response_status,
  response_payload JSONB, expires_at, UNIQUE(scope_key, route, method, idempotency_key))
  -- scope_key = HMAC fingerprint of tenant/user (raw ids never stored); TTL ~24h
  -- in_doubt (migration b3e7c9a15d24): committed by a holder about to start a side effect it
  -- cannot take back (a real phone call); the lease re-claim never takes such a record, so
  -- a retried key whose dial may have happened is never placed twice.
  -- claim_nonce (migration a6d2f8c41e97): minted on every take; `complete_idempotency` and
  -- `fail_idempotency` require it, so a holder whose lease lapsed cannot complete or reopen
  -- its successor's claim. NULL only on rows claimed by the previous release.
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
  -- D-678 adds webhook_id + sealed signing secret, engine_rate_key (f3a8c61d2e57) and
  -- facts_kb_ref, facts_digest (b7e2d94f1a30): the knowledge document holding this vendor
  -- agent's business facts on an engine that keeps them out of the prompt
  -- (`agents/engine_facts.py`), with the sha256 of its text; both or neither (CHECK
  -- `ck_engine_agent_routes_facts_whole`). Counted as ours by the KB reconciliation.
  -- engine_own_model TEXT NULL (a4c8e1f6b2d9, D-764, CHECK `^[^[:space:]]{1,128}$`): the
  -- model of OUR language-model key the vendor agent was published on, NULL on the engine's
  -- own model; the meter costs the call's tokens at its attested price. engine_rate_key
  -- admits `platform, standard, premium, studio, byok_voice, byok_llm_voice`.
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
  developer_retention_days INT NULL, developer_retention_plan_days INT NULL,
  developer_retention_checked_at NULL,
  own_model_developer_enabled_at NULL, own_model_developer_checked_at NULL,
  own_model_developer_error_code TEXT NULL,
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
  -- developer_retention_* = what our developer workspace last confirmed from
  -- `GET /workspace` (`callRetentionDays`, `planRetentionDays`, when read), written by
  -- the hourly retention sweep (migration c5f6e1202331, D-809) and read by the
  -- missing-recording sweep for calls held there; NULL until first read.
  -- own_model_developer_* = what our developer workspace last answered about our Google
  -- key (D-834, migration e3a7c1d9b524): first pass, last pass, last failure's code.
  -- Free-trial agents answer on that key there; the own-model switch-on readiness and
  -- the hourly repair read it.
  -- BACKEND-PATTERNS §6 requires the load-shed mode to be DURABLE in Postgres (Redis is
  -- only its cache) so a Redis flush cannot silently re-open a service an operator shut.
  -- The outbound halt shares the row because it answers the same question — "is the
  -- platform allowed to do work right now" — and one row means one read. Global by
  -- definition; written only through the audited admin ops surface (step-up confirm).
audit_log  -- (defined in §9) exempt because the admin realm reads cross-tenant by
           -- design; every such read is itself audited.
```

## 9b. The auto-healer (D-701, migration `b7d4e2a91c3f`)

| Table | Scope | What a row is |
|---|---|---|
| `heal_incidents` | global (RLS-exempt, §9a) | One problem a playbook is working on: `dedupe_key` (one unresolved per key, `uq_heal_incidents_open_key`), `playbook`, `trigger_code`, `scope` agent/tenant/platform, nullable `tenant_id`/`agent_id`, `state` open/mitigated/escalated/resolved, `attempts`, `next_attempt_at`, and the public status post (`public`, `public_title`, `component`). |
| `heal_actions` | global, **append-only** | Every step any playbook took: `playbook`, `step`, `outcome`, `attempt`, nullable `incident_id`/`tenant_id`/`agent_id`/`alarm_code`/`alert_id`, redacted `detail` (500 chars), `actor_type` healer/admin/user. |
| `heal_client_incidents` | tenant, FORCE RLS + a `FOR SELECT` read when no tenant is set (the notice sweep) | The client's side of one incident and one agent: `kind`, `protection` none/paused/forwarded, `campaigns_paused`, `requeued`, `missed_calls`, `must_act`, and when each notice went out. |
| `heal_fallback_phones` | tenant, FORCE RLS | The owner-set phone callers are handed to while an agent is held; one per client, an Indian mobile (CHECK). |
| `agent_health_windows` | tenant, FORCE RLS | One agent's real calls in one fifteen-minute window: the seven signal counts, `score` NUMERIC(5,2), the agent's `baseline`, `deviating`. Kept fourteen days. |
| `heal_proposals` | tenant, FORCE RLS | A behaviour change waiting for a person: `kind` rollback_prompt/review_knowledge/review_languages, `status`, `detail` (ids and numbers only); one pending per agent and kind. |

Two columns elsewhere: `agents.inbound_silence_reason` accepts `healer` (the CHECK
`ck_agents_inbound_silence_reason`), and `campaigns.paused_by_heal_id` (FK, SET NULL) marks
a pause the healer must undo, cleared by any person's pause or resume
(`campaigns/service.set_campaign_status`).

## 9c. Announcements, the bell's read mark, a call's follow-up mark (D-869, migration `b9e4d2a7c513`)

```
platform_announcements(id, message 1..280, link_url NULL, link_label NULL (needs a link),
  tone IN (info, success, warning, critical), audience IN (all, trial, paid, tenant, outbound),
  target_tenant_id NULL FK organizations CASCADE (set exactly when audience = tenant),
  -- `outbound` (D-941, migration d941a2c7e5b3): accounts with an agent that places calls.
  starts_at, ends_at NULL (> starts_at), ended_at NULL, created_by/updated_by NULL
  FK admin_users SET NULL, created_at, updated_at)
  -- Platform-scoped, RLS-exempt with its reason in RLS_EXEMPT_TENANT_COLUMNS. A client
  -- reads it only through announcements/service.active_for, which applies the audience
  -- (trial = organizations.first_paid_at IS NULL).
announcement_dismissals(id, tenant_id, announcement_id FK CASCADE, created_at, updated_at,
  UNIQUE(tenant_id, announcement_id))          -- FORCE-RLS; who pressed it is the audit row
notification_reads(id, tenant_id, user_id FK users CASCADE, seen_through, created_at,
  updated_at, UNIQUE(tenant_id, user_id))      -- FORCE-RLS; one high-water mark per person
calls.follow_up_state NULL IN (resolved, needs_you), follow_up_set_at, follow_up_set_by
  NULL FK users SET NULL  -- a person's mark, never rewritten by the pipeline
```

## 9d. Plans: one approval for an action over a set (D-893, migration `f4b8d2a61c39`)

```
copilot_plans(id, tenant_id FK organizations RESTRICT, user_id FK users CASCADE,
  origin IN (pip, console), tool (an ActionTool name), target_type IN (lead, call, callback),
  args jsonb (the action's arguments, lens included), title, why, lens_text (who, in words),
  run_at NULL, target_count >= 0, excluded_count >= 0,
  exclusions jsonb ([{reason, count}]), estimate_inr NUMERIC(14,2) NULL >= 0
  (NULL = not known), estimate_note,
  plan_hash (sha256 of tool, change, frozen targets, exclusions, estimate, run_at),
  status IN (proposed, approved, running, done, cancelled, expired), expires_at,
  approved_at (NOT NULL once approved/running/done), started_at, finished_at,
  done_count, skipped_count, failed_count, result NULL,
  campaign_id NULL FK campaigns SET NULL, created_at, updated_at)
  -- FORCE-RLS tenant_isolation plus copilot_plans_ops_read (FOR SELECT, untenanted
  -- sessions: the resume sweep finds stalled plans across tenants). user_id CASCADE: a plan runs as
  -- the person who approved it and has nobody to run as once they are gone; what it did
  -- is in the rows it touched and audit_log. Partial index on (updated_at) WHERE status
  -- IN (approved, running) serves the resume sweep.
copilot_plan_targets(id, tenant_id, plan_id FK copilot_plans CASCADE, target_id, position,
  excluded bool, status IN (pending, done, skipped, failed), reason NULL, finished_at NULL,
  created_at, updated_at, UNIQUE(plan_id, target_id))
  -- FORCE-RLS. The targets are FROZEN when the plan is built: approval binds the hash of
  -- exactly these rows. The UNIQUE pair is the run's idempotency key; each target is
  -- re-checked when it runs (still matching, still allowed) and skipped with a reason
  -- otherwise. target_id is not a FK: it names a lead, a call or a lead to book, by
  -- target_type. Erased with the tenant; per-subject erasure is exempt
  -- (check_erasure_coverage) because a row holds an id and a status, never PII.
campaigns.kind IN (standard, pip) DEFAULT standard
  -- pip: the campaign a dialling plan (calls_place_bulk) created and launched.
```

## 9e. "Meet your agent", and going live after the first payment (D-855, D-859, D-863, D-918)

```
first_runs(id, tenant_id UNIQUE, jobs TEXT[] DEFAULT '{}' (one to three starter jobs, each
  once), job TEXT NULL (DEPRECATED), language_primary, languages_extra TEXT[], brief NULL
  (<= 4000 chars), questions JSONB array, answers JSONB, questions_status DEFAULT idle,
  questions_disclosure, questions_brief_hash, question_runs >= 0, build_status DEFAULT idle,
  build_steps JSONB object, build_disclosure, build_runs >= 0, build_requested_at,
  document_ids UUID[] DEFAULT '{}', agent_id NULL, finished_at, dismissed_at,
  created_at, updated_at)
  -- Migration f8d2a6c4b1e7 (D-855). A new owner's first run: the jobs and languages chosen,
  -- the brief in their own words, the follow-up questions our AI wrote for the business
  -- (stored whole, each answer beside its question for the script writer, a7d3e9c2f416,
  -- D-863), the build's progress step by step, the agent it built, and when the owner
  -- finished or put it aside. It is also the first-run marker the sign-in junction reads.
  -- `question_runs`/`build_runs` bound how often the model is asked.
  -- `job` -> `jobs` is hard rule 8's two-step deprecation: nothing writes `job` since
  -- a7d3e9c2f416, and the column and its CHECK go in a later release. The backfill that
  -- copied `job` into `jobs` ran under FORCEd RLS and matched no rows, so cdd375802099
  -- re-runs it inside a NO FORCE / FORCE bracket.
  -- `document_ids` (e6b2d9f4a718, D-918): which ordinary knowledge uploads (`kb_uploads`,
  -- at most `first_run/models.MAX_DOCUMENTS` = 3) are this run's documents, so the question
  -- and script writers can read their words. An id array, not a join table: every read
  -- joins `kb_uploads` under RLS, so an upload removed on the knowledge screen stops
  -- counting. FORCEd tenant_isolation.
first_run_recordings(id, tenant_id, first_run_id FK first_runs, status DEFAULT queued,
  language, object_key NULL, content_type NULL, words NULL, error_code NULL, ...)
  -- One spoken piece of the brief (up to three of 30 s): the audio's object key until a
  -- worker has heard it, then the words; the key is cleared as the audio is deleted.
  -- FORCEd tenant_isolation; zero-rows proof `tests/first_run_test.py`. Tenant erasure
  -- deletes both tables. `business_copies.last_trigger` admits `first_run`.
agent_workspace_moves(id, tenant_id, agent_id, workspace_id, status IN (waiting, moved, held,
  failed) DEFAULT waiting, reason_code, attempts >= 0, alarmed_code, last_attempt_at,
  moved_at, ..., UNIQUE(agent_id, workspace_id))
  -- Migration b5d8f2a9c741 (D-859). The move of one agent from the developer workspace into
  -- the paying client's own customer workspace, state kept; `alarmed_code` stops the hourly
  -- retry paging twice for one cause. The go-live guide reads it as the move's progress.
go_live_guides(id, tenant_id UNIQUE, owed_at, finished_at, dismissed_at, ...)
  -- Written at the first payment; the sign-in junction and dashboard read it as the guide's
  -- marker.
agent_test_copies(id, tenant_id, agent_id, engine_agent_ref, last_used_at, ...)
  -- A moved agent's developer-workspace copy kept for test calls on the shared trial line
  -- while the client has no number of its own; retired with the copy.
  -- All three FORCEd tenant_isolation (zero-rows proof `tests/go_live_test.py`); tenant
  -- erasure deletes them. The same migration adds `calls.paid_test_call` (§4) and
  -- `organizations.first_paid_via = operator_conversion` (§2).
```

## 9f. Pip's notes (D-936, migration `e5b9d3f7a248`)

```
copilot_notes(id, tenant_id FK organizations RESTRICT, kind IN (hot_lead_waiting,
  balance_runway, knowledge_gap_repeat, good_week), subject 1..64, episode_key 1..96,
  payload jsonb object (ids and counts only), seen_at, dismissed_at, dismissed_by NULL FK
  users SET NULL, acted_at, resolved_at, created_at, updated_at,
  UNIQUE(tenant_id, kind, episode_key),
  UNIQUE(tenant_id, kind, subject) WHERE resolved_at IS NULL)
  -- FORCE-RLS. One open note per kind and subject; the line is composed at read time.
  -- Resolved or dismissed notes older than 30 days are pruned by the detector run;
  -- tenant erasure deletes every row.
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
