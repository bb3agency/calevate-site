# 02: Developer platform and integrations, Outpero v1 compared with Calevate 0.5.98

Written 28 Nov 2026 against branch `rel-0.5.98` (worktree rel596). Read-only research.

**Sources.**
- Outpero's side is VENDOR-PUBLISHED: `../outpero-openapi-2026-11-28.json` (OpenAPI 3.1, 37 operations), `../public-site-and-docs.md` §4, and `../screens/app-routes.md` (#/developers, #/settings/credentials, employee Actions and Outcomes tabs).
- Our side was read from the code in this tree. Each claim names the file it came from.
- Where a check was not run, the text says so.

**Founder rule.** Never copy them; be creative and better. The designs below either sit on doors we already have or go past theirs. None of them reproduces their wire shapes.

---

## 0. The finding in one paragraph

Our integration *plumbing* is better than Outpero's at almost every joint. That covers signed webhooks with rotation, a persisted retry ladder, Send again, opt-in transcripts with audit, native Meta and portal intake, a lead dry-run, launch-check, required idempotency with in-doubt handling, sealed saved credentials, seven in-call action kinds with a 6-second budget, and RFC 9457 errors with `remediation`.

**But we have no public API at all.** `apps/api/core/auth.py::_credential` accepts only the session cookie (plus the local-only `dev:` bearer), and refuses any other bearer silently. Its docstring calls it "a sentence for an integrator we do not have".

So everything a CRM, n8n flow or agency would automate has to be done by a person in the dashboard. That covers placing a call, reading results, running a campaign, adding to DNC and registering a webhook. Outpero has sold that since 16 Oct 2026.

It is the single largest gap in this area, and most of the remaining gaps hang off it: keys, scopes, rate-limit headers, API activity, an events feed, Postman and n8n assets, and a versioning policy.

The good news is structural. Every operation Outpero exposes already exists here behind a session, and goes through the compliance gate (`compliance/service.check_dispatch`) and the idempotency triad (`reliability/service.claim_idempotency`). The work is a **machine principal plus a curated, frozen surface**, not new business logic.

---

## 1. Capability matrix

Legend:
- **BETTER**: ours exceeds theirs on the axis that matters.
- **PARITY**: equivalent.
- **WEAKER**: we have it, but it is worse.
- **LACK**: grepped, not found.

| # | Capability | Outpero (28 Nov) | Calevate (file) | Verdict |
|---|---|---|---|---|
| A1 | Machine authentication (API keys) | `Bearer op_live_…`, shown once, fingerprint stored, checksum suffix for secret scanners, max 10 keys, browser origins refused (403) | None. `core/auth.py:_credential` is cookie-only; `grep` for api_keys / access_tokens / ApiKey in apps/api and packages finds nothing | **LACK** |
| A2 | Key scopes | Full access or Read only (2 levels) | RBAC exists (`core/rbac.py`: `calls:read`, `calls:read_raw`, `leads:read/write/dispatch`, `org:manage`, `wallet:read`…) but nothing binds it to a key | **LACK** (good foundation) |
| A3 | Public endpoint surface | 37 operations: me, balance, employees, numbers, calls (create, cancel, list, get), leads, campaigns (create, contacts, launch, pause, resume, cancel), dnc, events, inbound-calls, webhook-endpoints | The same operations exist as session routes: `crm/routes.py` (`/v1/calls`, `/v1/leads`, `/v1/leads/{id}/call`, `/v1/one-calls`), `campaigns/routes.py` (launch-check, launch, pause, resume, stop, contacts, results), `compliance` dnc router, `integrations/routes.py`, billing wallet | **LACK** as public; the internals are **BETTER** |
| A4 | Idempotency | `Idempotency-Key` optional, 24 h, `Idempotent-Replayed`, 422 on reuse with a different body, 409 in flight | `reliability/service.py`: `require_idempotency_key` *requires* a key on irreversible routes; tenant/user scope is HMAC-pseudonymised; in-doubt state (`mark_idempotency_in_doubt`), sweep | **BETTER** (no replay header: small WEAKER) |
| A5 | Dry run | `dry_run` on every write; lists checks | Lead dry-run `POST /v1/lead-sources/{id}/test` (real chain, no write); campaign `GET /v1/campaigns/{id}/launch-check` (preview of the gate). No dry run on one call or DNC | **PARITY** (narrower, but it is the real gate) |
| A6 | Rate limits | 120 reads and 60 writes per minute per key; 300 per minute per account; 1,000 API calls a day; `X-RateLimit-*`; 429 with `Retry-After` | `core/ratelimit.py`: per-tenant, per-family and cost-weighted profiles plus the nginx edge; `tests/rate_limit_census_test.py` forbids an unlimited route; 429 carries `Retry-After` (`core/errors.py:9`). No `RateLimit` headers; not per key | **WEAKER** (better engine, invisible to the caller) |
| A7 | Per-person pacing | "3 calls per person per 24 h across all sources"; a duplicate within 5 minutes returns the existing call | `check_dispatch` person rules are destination_not_india, erased, dnc, no_consent_record, no_consent, consent_expired (`compliance/service.py:890-1022`). No cross-source per-person frequency cap found | **LACK** (and a TCCCPR harassment exposure the moment an API exists) |
| A8 | Errors | `{error:{type,code,message,param,request_id}}` | RFC 9457 problem+json with `code`, `kind`, `retryable`, `remediation`, `trace_id` (`core/errors.py`, WEBHOOKS §2.5) | **BETTER** |
| A9 | Versioning policy | Additive-only v1, `/v2` with 12 months' notice, events carry `api_version` "2026-10-16" | Envelope has 5 keys and no version (WEBHOOKS §1.2); `User-Agent: Calevate-Webhooks/1`; no written policy | **WEAKER** |
| A10 | OpenAPI / Postman publishing | Curated public openapi.json, Postman collection (37 requests), "Copy as n8n node" | `apps/web/src/lib/api/openapi.json` is the *whole internal* API, used for the typed client; `/docs` and `/openapi.json` are not served in production (`core/bootstrap.py:479-501`) | **LACK** (public) |
| B1 | Outbound webhooks: events | 6 + `*`: call.completed, call.not_connected, lead.created, call.inbound_answered, call.inbound_missed, campaign.status_changed | 6: lead.created, lead.updated, call.completed, call.updated, call.recording_ready, campaign.completed (`integrations/service.py:117`). No not-connected, missed-inbound or campaign pause/start events, and no `*` | **WEAKER** (different set; theirs covers failure states, ours covers corrections) |
| B2 | Signing | `sha256=HMAC(ts.body)`, 5-minute window, `-Previous` header for 24 h after a rotation | `t=…,v1=…[,v1=old]` (Stripe shape) over `ts.body`, 5-minute window, grace 0 to 1,440 min, `grace_minutes:0` for a leak (WEBHOOKS §1.3-1.6) | **BETTER** (immediate-kill path; one header) |
| B3 | Retries | 8 attempts over ~24 h; auto-disable after 3 days failing, with a notice | 8 attempts over ~27.5 h, persisted `next_attempt_at`; non-retryable 4xx stop at once; on-call alerted (WEBHOOKS §1.5, memory bfa5e0c1). No auto-disable and no *client* notice found (`grep auto.?disabl` = 0) | **PARITY** (better ladder; missing the client-facing breaker) |
| B4 | Delivery log and resend | Per-endpoint deliveries with a status filter, resend | `GET /v1/integrations/deliveries` (last 50, ≤200), `resendable`, `POST …/resend`, payload view behind `calls:read_raw` with audit (`integrations/routes.py:1030-1117`). No status or endpoint filter | **PARITY+** |
| B5 | Test event | `POST /webhook-endpoints/{id}/test` | Not found in `integrations/routes.py` | **LACK** |
| B6 | Payload privacy | "Include call transcripts" switch | Phone masked by default; raw phone, recording link, redacted transcript and raw transcript are separate opt-ins; raw needs `calls:read_raw`, a step-up and an audit row per delivery; opt-out is honoured on retries (memories 21066d2f, 78649999) | **BETTER** (by a distance) |
| B7 | Endpoint creation safety | Key-holder creates | Step-up code per create (D-730); SSRF guard re-checked at delivery, IDNA ambiguity refused (WEBHOOKS §1.6) | **BETTER** for humans; it blocks machine creation (see design G4) |
| B8 | Native destinations | Webhook only (+ per-employee legacy webhook) | Webhook, Google Sheets (client's own Google, `drive.file`), LeadSquared (`integrations/models.py:40`) | **BETTER** |
| B9 | Events feed (pull) | `GET /events` kept for 30 days, `GET /events/{id}` | None; the delivery log is per delivery, not per event | **LACK** |
| C1 | Lead intake auth | `POST /lead-intake/<connection-id>` + `X-Outpero-Lead-Secret` | `POST /hooks/v1/ingest/{webhook_id}` + `X-Ingest-Secret`, compared in constant time, every rotation secret accepted (WEBHOOKS §2.1) | **PARITY** |
| C2 | Intake dedupe | "Duplicate leads within a few minutes ignored" | Body-hash dedupe per source; sender-id dedupe for portals; `leadgen_id` for Meta; LeadSquared echo check (memory 46e844e3) | **BETTER** |
| C3 | Intake consent | Not in the contract | `consent_field`; the lead is saved but not called without an affirmation; portal enquiries carry a 7-day permission; IndiaMART bought leads are not called (WEBHOOKS §2.3, §2.7) | **BETTER** |
| C4 | Meta Lead Ads | Docs: via Zapier. Product page lists FB/IG lead ads | Native: handshake, `X-Hub-Signature-256`, `leadgen_id` dedupe, redrive after Meta gives up, `GraphLeadRetriever` (`ingest/meta.py`, `ingest/graph.py`). **But the Page token is operator-attached** (`META_PAGE_ACCESS_TOKENS`, no route; `meta.py:86-110`), and no live Meta delivery has ever been read (`meta.py` "Still owed") | **WEAKER in practice** (better design, but no self-serve connect; unproven live) |
| C5 | Portals and CRMs in | IndiaMART, JustDial, Zoho, LeadSquared, Sell.Do named on the marketing page | IndiaMART, 99acres, MagicBricks, Housing, LeadSquared push presets; zoho, sheets, website_form, custom (`integrations/models.py:27`). No JustDial or Sell.Do preset | **PARITY** (JustDial is the visible hole) |
| C6 | Intake activity log | Accepted / deduplicated / rejected | `GET /v1/lead-sources/activity` with per-source duplicate counts; refusal codes mapped to sentences (memory 5a9db588) | **PARITY** |
| C7 | Instant-lead calling policy | Delay, window, out-of-hours (next open / +3 h / +6 h / next day / hold), retry ladder ≤ 9 steps | `ingest/lead_policy.py` (D-716): the same axes plus an answering-machine switch; held queue `/v1/lead-calling/held` with release and drop; hours only narrow the platform window (CHECK) | **PARITY** |
| D1 | WhatsApp in-call | Interakt, AiSensy, Meta Cloud, "Other WhatsApp" | `actions/schema.py:310` aisensy, meta_cloud, interakt, plus a custom provider; **spoken consent** args `caller_agreed` and `caller_words` reserved on every send (D-784) | **BETTER** (consent evidence) |
| D2 | Calendar | Google Calendar | `actions/calendar.py` freebusy check + book; OAuth per client | **PARITY** |
| D3 | Custom API | Custom API, no documented timeout or retry | `actions/execution.py`: egress guard, 4 s per request, 6 s in-call budget, 4 s lookup (`in_call.py:57-60`), gzip-safe capped reads, per-tool test and log routes | **BETTER** |
| D4 | Other action kinds | Sheets read/write, transfer (marketing) | sheets, payment_link (client's own Razorpay), crm (Zoho, HubSpot), caller_lookup, forwarding/handoff (`actions/models.py:70`) | **BETTER** |
| D5 | Saved credentials | Save once, reused by any action | `integration_credentials`, sealed with AAD per tenant and credential (`actions/credentials.py:60-220`), rotate, test, OAuth connect for Google, Zoho and HubSpot | **BETTER** |
| E1 | Automation-tool templates | n8n, Make, Zapier, Pabbly guides; 4 importable n8n workflows | One sentence: "Another CRM? Use Zapier, Make or Pabbly." (`IntegrationsScreen.tsx:146`). No guide, template or app | **LACK** |
| E2 | API activity log | Every request, newest first, bodies never stored, filter all / succeeded / errors | None (the only "api_activity"-like hit is unrelated, `compliance/rights_desk_routes.py`) | **LACK** |
| E3 | Developer docs site | docs.outpero.com/#api: quickstart, concepts, reference, guides, changelog | `docs/WEBHOOKS.md` is excellent but lives in the repo; no public page under `apps/web/src/app` (only `resources`, `status`, `security`…) | **LACK** (public) |
| E4 | Public status page | None (status.outpero.com is NXDOMAIN) | `apps/web/src/app/status` | **BETTER** |
| E5 | Conversational setup | None | Pip can create and edit endpoints and lead sources, rotate, resend (memory fd606025, D-893) | **BETTER** (unique) |

### What to do with the August "differentiation table" (memory 777dd436)

| August claim | 28 Nov status |
|---|---|
| Their URL token → our HMAC-signed, replay-protected webhooks | **No longer a differentiator.** They sign with HMAC over ts.body now. We keep an edge only in the immediate-kill rotation. |
| Their fire-once → our outbox + retries + log + replay | **Parity.** They have 8 retries, a log and resend. Our edge is persistence across restarts, honest 4xx semantics, and opt-outs honoured on retries. |
| Undocumented outbound payload → published versioned schema + generated client | **Reversed.** They publish OpenAPI and Postman; ours is in-repo, unversioned and unpublished. |
| Meta via Zapier → native Meta ingest | **Still true in code, unproven live,** and needs an operator to attach the token. |
| Untyped vars → typed extraction | Still true (their unknown fields are now ignored, but still untyped). |
| 3 versions, no diff → full history + diffs + staging | Not re-checked here (outside this area). |
| Undocumented tool timeouts → enforced in-call budget | Still true (`actions/in_call.py:57`). |
| DNC on bulk only → DNC on every path | **Mostly closed by them.** The API, test calls and instant leads are all DNC-gated per their app; only their Help centre lags. |

---

## 2. Gaps and designs

Each design keeps the hard rules:
- **Engine isolation (HR2):** nothing here touches vendor shapes.
- **RLS (HR1):** every new table carries `tenant_id` and FORCEd RLS, with a cross-tenant zero-rows test.
- **Append-only (HR4):** the new ledgers join `APPEND_ONLY_TABLES`.
- **PII-free logs (HR6).**
- **Compliance gate on every dial (HR5):** the API calls the same `check_dispatch` doors; there is no second dial path.

Effort is engineering hours for one agent. A gap whose closure depends on something *outside this repo* names it.

### G1. Machine principal: tenant API keys with scopes (LACK, keystone)

**Better than theirs**
- **Scopes are our RBAC permissions, not two levels.** A key carries a subset of the *creator's* permissions, so a key can never exceed its creator. Offered presets:
  - "Read results": calls:read, leads:read.
  - "Place calls": + leads:dispatch.
  - "Run campaigns": + campaign write.
  - "Manage DNC".
  - `calls:read_raw` is never grantable to a key in v1, because raw transcripts stay human-only (HR5).
- **Bound to an agent allow-list (optional) and a source-IP allow-list (optional).** An agency's n8n box gets a key that can only dial through agent X from IP Y.
- **Expiry by default (90 days) with a renewal nudge.** Outpero keys never expire.
- **Key format.** `cvk_live_<base62 32>_<crc32>`, plus `cvk_test_` for sandbox keys (G9). Register the prefix with GitHub secret scanning when that programme is available to us; that is an external step, verify the programme's terms first.

**Design**
- **Table and storage.** New `api_keys` table: tenant_id, created_by, name, prefix, `sha256(secret)` (or an HMAC with a platform pepper, the same pattern as `scope_key`), scopes text[], agent_ids uuid[] NULL, ip_cidrs cidr[] NULL, expires_at, last_used_at, revoked_at. FORCEd RLS.
- **Auth path.** In `core/auth.py`, a separate machine credential path: `Authorization: Bearer cvk_…` is honoured **only on routes under `/api/v1/`**, the public surface (G2). The cookie routes keep refusing every bearer, so the browser can never be talked into using a key, and the `_credential` invariant stands.
- **Browser requests refused.** Requests carrying `Origin` or `Sec-Fetch-Site: cross-site` are refused (as theirs are), plus CORS is never enabled on `/api/v1`.
- **Creation is a human act with step-up.** The D-730 pattern: `create_api_key:<slug>`. The secret is shown once. Every use writes `last_used_at` (debounced through Redis).
- **Principal shape.** The `Principal` gains `kind="api_key"` and `key_id`. `audit_log` rows record `actor_kind=api_key` and the key id, never the secret.

**Acceptance**
1. A key without `leads:dispatch` gets 403 `scope_missing` naming the scope.
2. A cookie route presented with a valid key gets 401, unchanged.
3. A key restricted to agent A gets 403 when dialling through agent B.
4. A revoked or expired key gets 401 within one request.
5. Cross-tenant zero-rows test on `api_keys`.
6. The rate-limit census covers `/api/v1`.
7. A secret never appears in logs (redaction test).

**Effort** 10-14 h. **Depends on** nothing external.

### G2. Curated public surface `/api/v1` over existing doors (LACK)

**Better than theirs**
- **One call endpoint for every mode.** Outpero restricts `POST /calls` to "instant-mode employees" and needs campaigns for bulk. Ours wraps `crm/one_call.OneCallIn`, which already takes `phone | lead_id`, an agent, a purpose and `at` (scheduled), and goes through `lead_dial.place_lead_call` / `swipe.schedule_lead_callback` with the gate.
- **The response says *why* a call cannot go now and when it can** (`opens_at`, already in `one_call.py:122`), not just `blocked`.
- **`GET /api/v1/calls/{id}?wait=30` long-poll.** It holds until the call reaches a terminal state or 30 s pass, so n8n users need neither polling loops nor webhooks for simple flows. It is cheap with the existing live-call topic.
- **Results carry our business outcome** (`business_outcome`, `business_outcome_label`), the agent's own goal. Theirs carry 4 fixed labels.
- **Leads are "people" with captured fields typed by the job's lead details** (D-715, D-1029). Each field has its label and type, not a bag of strings.

**Surface v1.** Each route is a thin adapter calling the existing service function, with its own frozen Pydantic response models:
- `GET me`, `GET balance` (wallet).
- `GET agents`, `GET agents/{id}`. This is the public shape: no prompts, but variables and capture fields.
- `GET numbers`.
- `POST calls`, `GET calls`, `GET calls/{id}`, `POST calls/{id}/cancel`.
- `GET leads`, `GET leads/{id}`.
- `POST leads`. This is the API twin of ingest: it goes through `ingest_lead` with the same consent rule, so API-created leads cannot skip `consent_field` semantics.
- `GET/POST campaigns`, `POST campaigns/{id}/contacts`, `GET campaigns/{id}/launch-check`, `POST campaigns/{id}/launch|pause|resume|stop`.
- `GET/POST/DELETE dnc`. DELETE requires a reason and is audited, and a number the *person* put on DNC by spoken opt-out cannot be removed by API (DNC provenance).
- `GET inbound-calls`.
- Webhook endpoints (G4).
- `GET events` (G5).

**Freezing.** Public response models live in `apps/api/public_api/schemas.py`, and `scripts/check_public_api_snapshot.py` diffs `public-openapi.json` against the committed snapshot in CI, failing on a removal or type change (additive-only, enforced, not just promised).

**Acceptance**
1. Every `/api/v1` write that rings a phone routes through `check_dispatch`, proven by a test that walks the routes and asserts the gate was called.
2. Every irreversible write requires `Idempotency-Key` (`require_idempotency_key`).
3. The public OpenAPI snapshot gate is in `ci.yml`.
4. Pagination is cursor-based (`starting_after`-style is fine, but use our uuid_v7 ids as cursors).
5. Money fields are strings of NUMERIC INR (HR7), never floats.

**Effort** 24-32 h for the full list; 10 h for the first slice (me, agents, calls, leads, dnc). **Depends on** G1.

### G3. Visible, per-key rate limits + per-person pacing in the gate (WEAKER / LACK)

**Better than theirs**
- **Standard headers.** Emit the IETF `RateLimit-Policy` / `RateLimit` header fields (draft-ietf-httpapi-ratelimit-headers; check the current draft number before writing, under the quality-bar rule) instead of ad-hoc `X-RateLimit-*`. Keep `Retry-After` on 429. Limits are per key *and* per tenant, reusing `core/ratelimit.py` profiles (reads, `bulk_write`, `costly`), so there is no second counter.
- **Daily dial cap per account is a budget that adapts, not a constant.** Default it from the account's paid state (trial vs paid, like their 100 → 1,000), and let the existing spend caps (`compliance/service.spend_capped`) remain the real ceiling.
- **Per-person pacing as a gate rule, not an API rule.** Add `person_contact_pacing` to `person_level_refusal` in `compliance/service.py`: at most N connected-or-attempted calls to one E.164 per tenant per rolling 24 h **across every path** (API, campaign, instant lead, callback, Pip, test calls), with N as a console setting. Ours then protects the person from *every* door, where theirs covers API calls only.
- **Not settled on refusal.** It is *transient*, so a campaign contact retries next window and is never settled. This respects the `SETTLED` refusal doctrine documented at `compliance/service.py:215-240`.

**Acceptance**
1. Four calls to one number via four different doors in 24 h: the 4th is refused with `person_contact_pacing` and `opens_at`.
2. `RateLimit` headers are present on every `/api/v1` answer.
3. The census test still passes.

**Effort** 6-8 h. **Depends on** the founder picking N (a compliance posture, not engineering). Hold it as a console setting with a conservative default and say so in the decision row.

### G4. Webhooks: the failure-state events, wildcard, test event, breaker, machine-managed endpoints (WEAKER / LACK)

**Better than theirs**
- **Events they lack *and* ones they have that we lack.** Add:
  - `call.not_connected`, carrying our honest reason vocabulary: no answer, busy, refused by gate (with rule), erased, out of hours, deferred to `opens_at`.
  - `call.inbound_missed`, with the missed-caller call-back the agent scheduled, if any.
  - `campaign.status_changed`, which subsumes started, paused (with *why*: the big red switch, spend cap, out of credits, owner), resumed and stopped.
  - `lead.consent_changed` and `dnc.added`. These are compliance events for CRMs that must stop marketing the same person elsewhere. Outpero has no equivalent. Masked phone by default (B6).
- Keep `campaign.completed` and `call.updated`, which theirs lack.
- **`"*"` subscription = "all current events", never future ones by default.** We said every event is a payload promise (`integrations/service.py:114`). A future event is opt-in, with a per-endpoint `auto_subscribe_new_events` switch. That is safer than theirs, where a new event lands on an unprepared receiver.
- **Test event** `POST /v1/integrations/endpoints/{id}/test` (and `/api/v1` twin). It sends a signed, synthetic envelope marked `"test": true`, recorded in the delivery log as `test`. Its data is synthetic, never a real lead.
- **Circuit breaker that tells the client.** After every delivery to an endpoint has failed for 72 h, pause the endpoint (not deactivate), email the account owner and post an announcement. Paused events are *held*, and "Resume" replays them through `resend_delivery`. Their breaker drops events; ours holds and replays.
- **Machine endpoint creation.** A key with `webhooks:manage` (a new scope) may create endpoints **only for events without personal data opt-ins** (no raw phone, transcript or recording). Turning those on stays a human step-up act (D-730 stands). This keeps the privacy edge without blocking n8n.
- **Delivery log filters.** Add `?endpoint_id=&status=&event=`.

**Acceptance**
1. Each new event has a payload test and a WEBHOOKS.md row.
2. `*` excludes events added after the subscription unless the switch is on.
3. After 72 h of failures the endpoint is `paused` and one email is sent (dedupe key per endpoint per pause).
4. Resume replays the held deliveries in `created_at` order.
5. A key without step-up cannot enable `include_raw_transcript`.

**Effort** 14-18 h. **Depends on** G1 for the machine half only.

### G5. Events feed (pull) with replay cursor (LACK)

**Better than theirs.** `GET /api/v1/events?after=<event_id>&type=` returns the same envelopes webhooks carry, for 30 days, plus a durable **per-key cursor** (`GET /api/v1/events/next`, acknowledged with `POST …/ack`). A receiver behind a firewall that cannot accept webhooks gets exactly-once-per-cursor consumption. Outpero offers list-only.

**Design.** Envelopes are already stored in the outbox (`KEEP_PAYLOAD_AFTER_RUN_JOBS`). Add an append-only `integration_events` row per event at fan-out (event id, type, created_at, data with masking at *read* time per key scope), with a 30-day retention sweep. Erasure goes through `retention._erase_outbox_messages`' sibling.

**Acceptance**
1. A webhook delivery and the feed carry the same `id` for the same event.
2. Erasure removes a person's events from the feed.
3. RLS zero-rows test.

**Effort** 8-10 h. **Depends on** G1.

### G6. API activity log (LACK)

**Better than theirs.** Per request: key id, method, route *template* (not the raw path, so no phone numbers in `/dnc/{phone}`), status, problem `code`, `trace_id`, latency and idempotency replay flag. Bodies are never stored (HR6), and neither are query strings.

Plus, beyond theirs:
- **"Explain this error" links each problem code to its remediation** (we already emit `remediation`).
- **A per-key health summary:** error rate over 24 h, and the last 429.

**Design.** Write the row in middleware for `/api/v1` only, buffered to a Redis stream and flushed by a worker into the partitioned table `api_requests` (tenant_id, RLS, 30-day retention). It must never sit on the request path's DB transaction.

**Acceptance**
1. No phone number or body appears in any row (test with a DNC delete).
2. The dashboard shows the last 100 with a filter.
3. The write never adds more than 1 ms p95 (a Redis XADD).

**Effort** 6-8 h. **Depends on** G1.

### G7. Self-serve Meta Lead Ads connect + live proof (WEAKER in practice)

**Better than theirs.** A "Connect Facebook Page" button: OAuth with `pages_show_list`, `leads_retrieval`, `pages_manage_metadata`, and the app subscribes the Page to `leadgen` itself. The client never pastes a verify token, and our `leadgen_id` dedupe, redrive and consent rule stay as built. Outpero still routes Meta through Zapier in its docs.

**Design.** This *changes* the documented decision that the Page token lives only in `META_PAGE_ACCESS_TOKENS` (`ingest/meta.py:86-110`). Per-tenant tokens would move into `integration_credentials`, sealed like every other client credential (D-700 pattern, AAD = tenant + credential id). That needs a decision-log row superseding the env-only rule, because the module argues against a DB-held token. The argument was "no runtime secret-fetching client"; sealed client credentials have since become the repo's one way (`actions/credentials.py`), so the argument has moved. **Flag this to the founder; do not silently pick.**

**Acceptance**
1. A Page is connected and subscribed with no operator step.
2. A token invalidated by Meta surfaces `meta_page_token_invalid` to the client with a Reconnect button.
3. Cross-tenant Page id spoofing is still impossible (keyed by lead source).

**Effort** 12-16 h. **Depends on (external)**:
- a Meta app with Advanced Access to `leads_retrieval`, which requires Meta App Review and Business Verification of the Calevate legal entity;
- OPERATIONS §2b's live-delivery gate.
`graph.facebook.com` is egress-blocked from this container, so the live read has never been tested.

### G8. Published developer docs + OpenAPI + Postman + automation templates (LACK)

**Better than theirs**
- **Generated, not hand-written.** `app.calevate.tech/developers` (or `calevate.tech/developers`) renders from `public-openapi.json` (G2) and WEBHOOKS.md, so the docs cannot drift from the code. Outpero's docs already contradict their own product: DNC on Instant, `call.ended` vs `call.completed`, ₹6.8 vs ₹7 (public-site §6.16).
- **Generated assets.** Postman collection, an n8n *community node* (`n8n-nodes-calevate`, generated from the OpenAPI), a Make custom app and Zapier templates. A real n8n node beats their "Copy as n8n node" snippets: credentials are stored once and the trigger node uses the events feed (G5) or webhooks.
- **Telugu-first worked examples.** The quickstart includes "IndiaMART enquiry → Telugu call → result in Google Sheet", using our native portal intake plus Sheets destination with **zero code**. That says what we are without naming anyone.
- **Hard-rule-visible docs.** Each operation page states which gate it passes through and which refusal codes it can return, generated from a route annotation listing `check_dispatch` rules.

**Acceptance**
1. CI fails if `/developers` renders an operation absent from the snapshot or misses one.
2. The Postman collection is regenerated on release.
3. The n8n node is published to npm under our org with provenance (HR9: no postinstall scripts, `pnpm audit` clean).
4. The page names no provider (D-679).

**Effort** 16-24 h (docs page 6 h, Postman 2 h, n8n node 8-10 h, templates 4 h). **Depends on** G2. Zapier and Make public listings need those vendors' app review (external).

### G9. Sandbox: test keys that dial nobody (LACK; theirs is `dry_run` only)

**Better than theirs.** A `cvk_test_` key runs against the real tenant config with the **fake engine** (`ENGINE=fake` exists for tests, `apps/api/engine/fake.py`). Calls "complete" with a scripted transcript, fire real signed webhooks marked `"livemode": false`, are never billed, and never touch the voice platform. Integrators can build a full round trip (place → webhook → write-back) before spending a rupee. Outpero's `dry_run` only validates; it cannot exercise the webhook path.

**Design**
- Test-mode rows live in the same tables with `livemode=false` (a column on calls, leads and integration_events), excluded from analytics, billing and the cost ratchets.
- The fake engine is selected per request by key mode, inside the adapter seam (`engine/__init__`), so HR2 holds.
- The compliance gate still runs, so integrators see real refusal codes, but the dial is to the fake engine.

**Acceptance**
1. A test key never produces a `usage_events` row or a vendor HTTP call (test asserts zero egress).
2. Test data is invisible on the dashboard unless the "Show test data" toggle is on.
3. It is erased after 7 days.

**Effort** 14-20 h. This is the riskiest item because of the livemode column across tables, so do it after G1, G2 and G4. **Depends on** G1 and G2.

### G10. Versioning policy and `api_version` on every envelope (WEAKER)

**Better than theirs.** A date-pinned version per key (`Calevate-Version: 2026-12-01` header; default = the version current when the key was created, as Stripe does). Envelopes carry `api_version`. A breaking change ships as a new dated version with transforms on our side, so old integrations never break and nothing needs a "12 months' notice".

Start honest: one version, plus a written promise (additive-only within a version, which the G2 snapshot gate enforces). Build the transform layer only when the first breaking change is actually needed (YAGNI, with the policy written now).

**Acceptance**
1. WEBHOOKS.md §0 states the policy.
2. Every envelope has `api_version`.
3. The snapshot gate proves additive-only.

**Effort** 3 h (policy + field); transforms later, when there is a breaking change. **Depends on** nothing.

### G11. JustDial and Sell.Do intake presets (PARITY hole)

**Better than theirs.** Add them as `ingest/portals.py` presets with sender-id dedupe and the 7-day enquiry permission, the same as IndiaMART.

**Acceptance.** Fixture-based mapping tests from each vendor's published push format.

**Effort** 3-4 h each. **Depends on (external)**: each vendor's published push or webhook format, which must be read at source before writing (HR11). If no format is published, ask the client's account manager, the same as for 99acres and MagicBricks (WEBHOOKS §2.7).

### G12. Speed-to-lead proof on intake (adjacent; flagged to the analytics lane)

Outpero's Instant analytics charts qualify rate by first-call delay. Our intake already timestamps receipt and dial, so the feature is a read on existing data. It is listed here only because sales will ask whether the API path is as fast. Route it to the analytics analysis rather than duplicating it.

---

## 3. Ranked: top 15 gaps by business impact

Impact is judged on three things: deals lost without it (agency, CRM-led SMB, IndiaMART-heavy trades), compliance exposure, and the cost of being second.

| Rank | Gap | Verdict | Why it ranks here | Effort |
|---|---|---|---|---|
| 1 | **G1 Machine API keys with RBAC scopes** | LACK | Without it nothing else in this area exists; agencies and CRM-led clients cannot integrate at all | 10-14 h |
| 2 | **G2 Public `/api/v1` surface (calls, leads, campaigns, DNC, agents, balance)** | LACK | The thing Outpero launched on 16 Oct; every RFP from a CRM-using SMB asks "do you have an API" | 24-32 h (first slice 10 h) |
| 3 | **G3b Per-person pacing rule in `check_dispatch` (all doors)** | LACK | An API without it is a harassment-complaint vector under TCCCPR; it protects every existing door today too | 4-5 h |
| 4 | **G4a Failure-state events: `call.not_connected`, `call.inbound_missed`, `campaign.status_changed`** | WEAKER | CRMs need to know "we couldn't reach them" to hand off to a human; today they hear only successes | 6-8 h |
| 5 | **G7 Self-serve Meta Lead Ads connect (+ live proof)** | WEAKER in practice | Meta lead ads are the largest instant-lead source for Indian SMBs; ours needs an operator today and is unproven live | 12-16 h + Meta App Review |
| 6 | **G8 Published developer docs + public OpenAPI + Postman** | LACK | They look like a platform and we look like an app; generated docs also out-credibility their self-contradicting ones | 8 h |
| 7 | **G8b n8n community node + Make/Zapier/Pabbly templates** | LACK | The Indian SMB automation stack *is* n8n, Pabbly and Zapier; a real node beats their snippets | 12-14 h |
| 8 | **G9 Sandbox keys on the fake engine (real webhooks, zero cost)** | LACK | Shortens agency evaluation from "buy credits and test on your phone" to minutes; a clear "better" | 14-20 h |
| 9 | **G4b Webhook breaker that pauses, holds, tells the owner and replays** | LACK | Their breaker silently drops; a broken CRM sync is the top churn reason in integrations | 4-5 h |
| 10 | **G5 Events feed with a durable per-key cursor** | LACK | Firewalled CRMs (common in BFSI) cannot take webhooks; this unlocks them | 8-10 h |
| 11 | **G6 API activity log (route templates, no bodies, no numbers)** | LACK | Halves support tickets for integrators; needed the day G2 ships | 6-8 h |
| 12 | **G3a `RateLimit` headers, per-key limits, adaptive daily dial cap** | WEAKER | Integrators back off correctly instead of hammering 429s; the trial-vs-paid cap limits abuse | 3-4 h |
| 13 | **G4c Test event + machine-managed endpoints (no-PII events only) + `*` without future events** | LACK | Setup friction in n8n and Make; keeps the D-730 privacy edge | 4-5 h |
| 14 | **G10 Versioning policy + `api_version` on envelopes** | WEAKER | Cheap trust signal; the snapshot gate makes "additive-only" a fact, not a promise | 3 h |
| 15 | **G11 JustDial and Sell.Do presets** | PARITY hole | JustDial is a top-3 enquiry source for local services in AP/TS; Sell.Do for real estate | 3-4 h each + vendor format |

**Suggested order:** 1 → 3 → 2 (first slice) → 4 → 12 → 11 → 6 → 13 → 9 → 6/8 docs → 7 → 5 → 8b → 14 → 15. Items 3, 4, 9 and 14 can run in parallel with G1 because none needs a machine principal.

**External blockers named:**
- Meta App Review and Business Verification (G7).
- Zapier and Make public-app review (G8b; private templates need nothing).
- JustDial and Sell.Do push formats (G11).
- The founder's choice of the per-person cap N (G3b).
- The founder's ruling on moving Meta Page tokens into sealed `integration_credentials` (G7), which reverses the reasoning in `ingest/meta.py:86-110`.

## 4. Where we are already better, and should say so on the developer page

- **Transcript and phone opt-ins.** Opt-outs are honoured on retries, and raw transcripts are audited per delivery (B6).
- **Rotation that kills a leaked secret instantly** (`grace_minutes: 0`).
- **Honest retry semantics.** A 4xx stops; the retry ladder is persisted.
- **Consent-aware intake.** `consent_field`, a 7-day permission for portal enquiries, and bought IndiaMART leads never called.
- **Native IndiaMART, property-portal and LeadSquared intake, and LeadSquared, Sheets and webhook destinations.**
- **Seven in-call action kinds** with a 6-second budget and spoken-consent evidence on every WhatsApp send.
- **Required idempotency** with an in-doubt state.
- **RFC 9457 errors** with remediation.
- **A public status page.**
- **Pip sets up integrations conversationally.**
