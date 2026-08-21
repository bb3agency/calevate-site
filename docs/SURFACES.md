# Calevate — Surfaces & Integration Patterns

Version 1.0 · July 2026. Three parts, per the product framing: the **admin panel**
(authoritative, operated by us), the **client-facing CRM** (SaaS-like, near-identical per
client, Outpero is the floor — teardown in BRD §5), and the **integration layer** with
the rented engine — Bolna per D-31 (no compromises).

Status of each section: §1 and §2 are researched FEATURE INVENTORIES that seed the
build-time design discussions — items here are candidates, not commitments, unless they
carry a decision-log reference. §3 is DECIDED engineering doctrine.

---

## 1. Admin Panel (admin.calevate.tech) — inventory for the build-time discussion

What it is: the operations console for a managed voice-agent business. It does NOT
replicate the client UI; it shows operational internals the client never sees.
Already decided: two-realm auth (TRD §11), admin roles superadmin|operator, MFA,
read-only audited impersonation (D-22), always-audited admin reads (SEC-COMP §5).

Client lifecycle
- New-client wizard (FLOWS §1) with draft/resume; compliance status surfaced per step.
- Account lookup with full operational context: org, plan, engine refs, numbers,
  DLT state, caps, credit balance, recent errors — one screen per client.
- Controlled mutations with audit: plan changes, credit adjustments (compensating
  entries, never edits), cap raises, suspend/reactivate, offboarding trigger.
- Batched onboarding pattern (industry: weekly cohorts once client count grows).

Tenant health board (the core admin screen — industry-standard for voice agencies)
- Per-client tiles: call volume, answer rate, latency p50/p95 vs budget, pipeline lag,
  error rate, spend vs cap, engine webhook delivery health.
- Alert-before-the-client-notices doctrine: latency drift, answer-rate dips, and
  webhook failures alert us first (OPERATIONS §4 alert list).
- QA sampling: spot-check ~5% of calls per client per week (queue surfaced in admin;
  ties into the regression harness and knowledge-gap reports).

Engine & config management
- Per-client engine refs (agents, numbers, KB attachments), BYOK key status,
  staging→live promote (maps to engine draft/publish), prompt version history +
  rollback, extraction schema editor (admin-only, D-21).
- Secrets: references only, never values (SEC-COMP §5); key rotation reminders.
- Per-tenant feature flags (config rows, TRD conventions) — enable beta features or
  debug modes per client without deploys.

Commercials
- Margin per client (usage_events cost vs plan revenue — the D-12 payoff).
- Invoice run surface (M2); dunning states; usage anomaly review.

## 2. Client CRM (app.calevate.tech/c/<slug>) — inventory for the build-time discussion

Floor: everything in the Outpero teardown (BRD §5). Already decided: schema-driven
Leads table (D-09), fixed status enum + admin-only schemas (D-21), "Call this lead"
with context note (M1), AI callback on needs-follow-up (M2), outbound sync (D-23),
staff/owner role split (SEC-COMP §5).

Table UX (2026 CRM patterns worth adopting when we build)
- Saved views: named filter+column combinations per user (e.g. "Hot this week").
- Inline edit for status and assignment (exit via Enter/click-out; no modal for
  single-field edits); full record in a detail drawer, not a page navigation.
- Bulk actions with the researched guardrails: progress indicator, result summary
  (n succeeded / n failed), inline warnings before destructive/irreversible batches.
- Faceted filters driven by the extraction schema (enum fields → facet values).
- Column chooser mirrored in CSV export (choose-what-you-export, Outpero parity).

Dashboard (role-adaptive; the 2026 pattern is "prioritized operating surface")
- Owner default: outcomes + spend (calls, resolved-by-AI %, after-hours captured,
  minutes used vs included, hot leads awaiting action).
- Staff default: work queue (needs-follow-up first, repeat callers flagged).
- Live tiles for in-progress calls (transport: §3.2).

Trust surfaces (our differentiators made visible)
- Per-call: transcript (redacted by default), recording player, AI summary, extracted
  fields, latency badge.
  - The player and the transcript are ONE instrument, not two panels: every turn
    carrying `start_ms` is a seek target, and the turn being spoken is highlighted as
    the audio runs. Reviewing a call means reading and listening at the same time, and
    a transcript you cannot click is a transcript you scroll while guessing.
  - The audio is always OUR copy, reached by a presigned link whose life is derived from
    the call's own duration (D-153) and refreshed in place if it still expires. The
    engine's URL never reaches a browser (hard rule 2), and every link minted writes an
    `audit_log` row — "who listened to this call" is answerable.
  - Recordings are kept for at least 90 days because TRAI requires it; that floor is
    enforced in the schema, not by policy, and DPDP erasure defers rather than breaks it.
  - **"Key points in this call"** (D-156) — timestamps computed ONCE by the post-call
    pipeline, never per listen, so the panel costs nothing to open. Clicking one seeks the
    player. Hidden entirely when a call has none: an always-present heading over an empty
    box on every short call is a heading people learn to skip. Markers derived from the
    transcript's own turn offsets are shown plainly; anything the assistant suggested is
    badged, because one of the two cannot be at the wrong second and the other can.
- Monthly QA report (D-15) rendered in-app, not just PDF.
- "Why customers call" themes and knowledge-gap-driven "your agent couldn't answer
  these" list — turns T4 refusals into KB update requests.

## 2b. Self-serve surfaces (D-34) + patterns adopted from the Outpero teardown

Lands M2 (D-39: schema in M1, surface when a user needs it). These are **additions to the
same client app** — a self-serve org is the same `organizations` row with a different
`plan_tier`, so nothing forks.

**Self-serve-only screens**
- **Sign-up + org create**: email/password or Google (FLOWS §2), slug validated against
  `reserved_slugs`.
- **Credit wallet**: balance, **runway in minutes** ("₹X · ≈ N min, M min on premium" —
  their money-UX is genuinely good), top-up packs, auto-receipt with GST.
- **Plan/usage**: agents live vs draft, minutes used, spend against cap.
  - **Spend cap, client-editable** — `GET /v1/billing/caps` (`billing:read`) and
    `PUT /v1/billing/caps` (`org:manage`; mutating, so D-22 refuses an impersonating
    admin). There are TWO caps per plan: `hard_cap_min`/`hard_cap_spend` are admin-owned
    and `client_cap_min`/`client_cap_spend` are the client's, and the effective ceiling
    is `LEAST(admin, client)` with NULL meaning "no constraint from this side". A client
    may lower theirs to anything including zero and may clear it (falling back on the
    admin's), and may **never** set one looser than the admin's —
    `client_cap_exceeds_plan_cap`, refused rather than clamped. A cap set BELOW this
    month's spend is accepted and **binds immediately**: the write recomputes
    `spend_state.capped` from the counters already in the row, so the next dial is
    refused rather than the dial after the next call happens to meter. Inbound is
    unaffected — the gate is outbound-only — which is what makes an immediate stop a
    safe control to hand a client. The reasoning is in `apps/api/billing/caps.py`.
  - **Two overage rates.** `plans.overage_rate_value` prices the value TTS rung
    separately (D-36's ladder; `usage_events.meta.tts_tier` already says which rung a
    call ran on). **NULL means the plan quotes no separate value rate — everything bills
    at `overage_rate`**, which is every plan that predates the column, so no bill moved
    when it landed. The included allowance is consumed on the DEARER rung first, leaving
    the cheaper minutes to be charged for, and unattributed minutes bill at the value
    rate (the same honesty rule `billing/rates.py` applies to cost). The invoice prints
    one line per rung so each still multiplies out. **No retail value rate is set
    anywhere in the codebase** — TRD §10.1's bands are unmeasured, so the number is a
    founder decision, not a derivation.
- **Number purchase + KYC**: gated; calling stays disabled until verification clears.
  **SHIPPED** (migration `a3f6b1e02d95`, `kyc_records`). Two gates, and they answer the
  plan-tier question differently on purpose — the argument is in
  `apps/api/compliance/kyc.py`, with the DoT/TRAI sources it rests on. **Dialling** is
  gated for `self_serve`/`trial` only, exactly as `credits_exhausted` is:
  `compliance.service.check_dispatch` refuses with `kyc_missing` / `kyc_not_verified`
  and `campaigns.service.launch_blockers` previews the same names, while a managed
  tenant's identity was verified out of band before we bought their number and is
  already gated by `pe_registration_*`. **Buying a number** —
  `POST /v1/numbers/purchase` (`org:manage`) — is gated for **every** tier, because the
  DoT business-connection obligation attaches to the connection and a control keyed on
  an admin-settable column is a control one support ticket from being switched off.
  Inbound is untouched (D-38): the gate is outbound-only and inbound never enters it.
  Ops records the verification through `POST /v1/admin/tenants/{tenant_id}/kyc`
  (`admin:tenants`, audited); the client reads their own state at
  `GET /v1/compliance/kyc` (`org:read`, absence is a 200 with `recorded: false`), and
  there is deliberately no client-realm write. **NOT IMPLEMENTED: provisioning itself.**
  D-05's vendors are a decision, not a credential — no telephony account, no adapter —
  so a verified account's purchase is refused with `number_provisioning_not_configured`
  and `campaigns.provisioning.PROVISIONING_IMPLEMENTED = False` is the greppable
  constant. Numbers are provisioned by operations out of band today. **No identity
  document is stored anywhere**: `kyc_records` keeps a public business-registry
  identifier and a reference to where the pack is filed, and a CHECK constraint refuses
  a value shaped like an Aadhaar.

**Patterns worth adopting (evidence: teardown §9c/§9d — all verified in their product)**
- **"Needs attention" queue** — leads on hold or awaiting retry, with early release. This
  is the operational work-queue our dashboard inventory (§2) is missing; it belongs next to
  the Leads table for both motions.
- **Webhook activity view** — every inbound delivery shown as **accepted / deduplicated /
  rejected**, with the raw payload. Pair it with a **"Test webhook"** button that runs a
  sample lead end-to-end *without placing a call*. Together these are the single biggest
  integration-DX win available, and they cost us little because the reliability triad
  (D-30) already records everything needed.
- **Two-speed publishing** — script/flow/actions/webhook edits require an explicit
  **"Apply to live calls"**; voice, extraction fields and training apply immediately.
  Split by blast radius, with an unsaved-changes banner offering Apply or Undo. Nothing
  goes live silently.
- **Precedence rule, stated in the UI** — *script decides content, rules decide conduct,
  voice only changes delivery*. Cheap to say, removes a whole class of support question.
- **Cost-runaway guard** — a per-agent max call length (their default 10 min, adjustable).
  We have no equivalent today and should.
- **Honest degraded-tier billing** — if a premium voice is unavailable the call runs on the
  cheaper voice and is **billed at the cheaper rate**, never silently upgraded.

**Where we deliberately go further** (teardown §9d table): HMAC-signed webhooks with
timestamp + replay protection (they use a URL-path token and an *optional* header);
outbox-backed delivery (publish retried up to `OUTBOX_MAX_ATTEMPTS` = 5 by the dispatcher,
plus a per-delivery ladder of `WORKER_MAX_TRIES` = 3 attempts at 30s/120s — no longer a
gap: the delivery worker raises `arq.Retry(defer=…)`, see §3.1 and the FLOWS §6 note), a
delivery log and **replay** (they fire
once and can arrive with null fields); a **published, versioned** outbound payload schema
(theirs is undocumented); **a direct lead-ingest endpoint** —
`POST /hooks/v1/ingest/{webhook_id}` with per-endpoint secret, field mapping and a
no-call dry run, no Zapier in the middle — plus a **native Meta Lead Ads receiver**,
`GET|POST /hooks/v1/ingest/meta/{webhook_id}`: their subscription handshake
(`hub.mode`/`hub.verify_token`/`hub.challenge`, token derived per endpoint, never
stored), `X-Hub-Signature-256` verified against the raw bytes with the app secret
before any parse, dedupe keyed on `leadgen_id` (the lead is the unit of work — Meta
batches and re-batches), the form-field mapping, and consent that is never assumed: a
lead-ad fill with no opt-in question on the form is saved and **not** dialled
(`no_consent_field_configured`). (*The Graph read that carries the answers is **built**
— this parenthetical said it was not, for a wave after D-90 landed it.
`GET /{leadgen_id}?fields=field_data` sits behind the `LeadRetriever` Protocol with
`field_data` → flat-map normalization feeding the same consent gate, and
`LEAD_RETRIEVAL_IMPLEMENTED = True` is the greppable constant. What is missing is the
CREDENTIAL: it needs a Page access token with `leads_retrieval` and this deployment
holds no Meta credentials, so a verified delivery today still lands as a RECORDED refusal
(`meta_lead_retrieval_unavailable`) against its `leadgen_id`, visible in the activity
view — which now marks it `recoverable` — and re-claimable the day a token exists.
"The day a token exists" used to mean "if Meta is still retrying": it redelivers for
~36 hours and then unsubscribes the Page, after which the `leadgen_id` was durable and
unreachable by anything. `POST /v1/lead-sources/{webhook_id}/meta/redrive` (`org:manage`,
audited) is what acts on it now, through the same `_absorb_leadgen` a live delivery takes
— same claim, same capability selector, same consent branch, same compliance gate — with
the count and the button on the Meta card of the lead-sources screen.
`apps/api/ingest/meta.py` states the credential position, and
`POST /v1/lead-sources/{webhook_id}/meta/setup` answers the handshake half — a POST
because the response carries a verify token, the mirror of `/v1/dnc/check`.*);
typed+validated extraction (theirs is untyped — the "Delhi
in a quantity field" bug); full version history with diffs and audit (they keep 3
versions, no diff); and **DNC on every dispatch path** including instant, which is where
their compliance actually fails.

## 2c. Shipped today — no longer candidates

§1 and §2 above are inventories (candidates). This section is the short list of what has
actually landed, so nobody re-proposes a screen that exists. Verified against the route
tree in `apps/web/src/app` and the OpenAPI paths in `apps/web/src/lib/api/schema.d.ts`.

Client realm (`/c/<slug>/…`)
- **Leads** with a **list ⇄ board toggle** — the board is one column per D-21 status,
  so the "work the pipeline stage by stage" pattern is built, not pending.
- **`/performance`** (`GET /v1/performance`) · **`/attention`** (`GET /v1/attention` — the
  §2b "needs attention" queue, shipped) · **`/agents`** (read-only agent roster, plus the
  §2b **unsaved-changes banner** from `GET /v1/agents/{agent_id}/pending`, the
  **precedence rule** and lane table from `GET /v1/agents/lanes`, and the cost-runaway
  guard read as "longest one call may run / most one call can cost" — `null`
  `worst_case_call_cost_inr` renders as "we cannot say yet", never ₹0. Apply and Undo are
  deliberately absent here: both are admin-realm, because the staged script is authored
  admin-realm) ·
  **`/lead-sources`** (`GET /v1/lead-sources/activity`, `POST /v1/lead-sources/{id}/test` —
  the §2b webhook-activity view and its no-call "test webhook", shipped — plus the Meta
  Lead Ads setup card, `POST /v1/lead-sources/{webhook_id}/meta/setup`, which prints what
  to paste into the Meta App Dashboard) ·
  **`/campaign-review`** (`GET /v1/compliance/first-campaign-review` — the client's view
  of R-11's first-campaign hold, D-51. Read-only by construction: there is no mutation in
  the module, so no 403 trap can be built on it, and the screen says plainly that the
  release is recorded by Calevate operations. `pending` and `rejected` are different
  screens — pending is "we will look", rejected carries the reviewer's own words and needs
  a different next step — and the state helper keys on the server's `held` answer rather
  than on `status`, failing CLOSED so an unrecognised rule stays held. It states both
  halves of the account scoping in the client's words, because a client who thinks every
  campaign needs review will not build a second one) ·
  **`/messaging-consent`** (records what a consumer said about being messaged and looks
  up whether we may; the screen that makes a `recipient_not_opted_in` escalation fixable
  by somebody saying yes) · **`/do-not-call`** (`/v1/dnc`, with removal offered only where
  `is_removable()` says the entry may be undone here — the flag and the endpoint read one
  definition, so no button is rendered that would 422) ·
  **`/settings/alerts`** (`GET`/`POST /v1/compliance/whatsapp-alerts` — the owner's own
  WhatsApp hot-lead opt-in, in the first person, which is what a CHECK constraint requires.
  The notice text and its version come from the SERVER on every response and the version
  shown is the version sent back, so a stale build is refused rather than recorded; the
  grant is withheld while `delivery_available` is false, and the withdrawal never is) ·
  **`/integrations`** (endpoints + delivery log) · **`/verification`** (the client's own
  view of `GET /v1/compliance/kyc` — the page a self-serve owner opens because their
  outbound stopped. It leads with "inbound is unaffected", says plainly that the client
  cannot self-verify, and carries no upload control, because the record stores a
  registry identifier and a filing reference and never a document) ·
  `/calls`, `/campaigns`, `/knowledge`,
  **`/usage`** (usage panel + the §2b client cap editor) ·
  **`/ai-assist`** ("AI help" — what the console's dashboard AI has used this month
  against the allowance the plan includes, and the ONE place in either realm where a
  client agrees to spend money on more. D-127 G-5: at the ceiling the feature blocks and
  the screen opens a dialog naming the exact rupee figure, what it buys, that the unused
  part does not carry over, and that nothing has been charged yet — the debit happens
  only on accept, is one `credit_ledger` row, and is audited. Deliberately NOT part of
  `/usage`: that panel is what the CLIENT is billed for, this is what Calevate absorbs
  until a ceiling, and merging them would put a figure a client never pays into the
  screen they check their bill on).

Admin realm (`/admin/…`)
- **Begin a view-as session** (`POST /v1/admin/impersonation-grants`,
  `admin:impersonate`, admin realm) — takes a tenant SLUG and returns the short-lived
  signed grant every impersonated request must carry as `X-Impersonation-Grant` beside
  `X-Impersonate-Org`. It replaced `POST /v1/admin/tenants/{tenant_id}/impersonate`,
  which minted nothing and which the console never called — so D-22's "session start
  audit-logged" row was absent for every session that ever happened. The grant is bound
  to this operator AND this tenant and is refused against any other; minting is what
  writes `admin.impersonation_started`, so that row can no longer be skipped. Addressed
  by slug because every place view-as is initiated holds one (including
  `/c/<slug>?view=admin`, where no tenant id is in scope), and bound to the id because
  that is what RLS keys off. See SECURITY-COMPLIANCE §5 and `apps/api/core/
  impersonation.py`. Read-only is unchanged: `requires()` still refuses every mutating
  permission to an impersonating principal, grant or no grant.
- **Who this operator is** (`GET /v1/admin/me`, `org:read`, admin realm) — the console's
  own identity read: the `admin_users` id, the role and the role's permission set, with no
  tenant touched and no impersonation header accepted as a substitute. It exists because
  `/v1/me` resolves through `current_any`, which reaches the admin realm only when
  `X-Impersonate-Org` is present, so a bare admin token asking it is verified as a CLIENT
  token and refused — leaving the console to learn its own role by entering some client, or
  to guess it from a 403 on whatever the current screen happened to read. `org:read`, not
  `admin:tenants`: D-22 forbids gating a GET on a permission read-only impersonation
  refuses, and beyond that rule an identity read gated on the authority to manage tenants
  would answer "what may I do" only to the accounts that may already do the most. It drives
  every admin-realm gate (`@/app/admin/access`) and the SIDEBAR: an entry whose screen the
  session cannot use is shown and DEAD with the permission named, never hidden — the same
  doctrine the client console applies to controls — while an identity that is unread or
  unreadable leaves every entry live, because the API is the enforcement and an operator
  must not be locked out of the never-shed ops surface by a slow read.
- **The client health board** (`/admin/health`; `GET /v1/admin/client-health`) — §1's
  "tenant health board", built as an EXCEPTION REPORT rather than the per-client tile grid
  that inventory imagined. Only accounts with at least one live signal appear, most broken
  first; an account with nothing wrong is absent, which is what keeps it from becoming a
  second client directory (`GET /v1/admin/tenants` is the roster, and its summary now says
  so — both surfaces used to claim the title "client health overview"). FIVE signals, each
  actionable the day it appears: `calls_stopped`, `outbound_blocked`, `spend_cap_near`,
  `deliveries_failing`, `knowledge_waiting`. `outbound_blocked` is COMPOSED from the
  predicates that refuse the dial (`read_tenant_holds`, `pe_registration_blocker`,
  `spend_capped`, `credits_exhausted`) rather than a second copy of their conditions, so
  the board cannot tell an operator an account is fine while the client is staring at a
  refusal — and its causes carry the gates' own rule names, never their `reason` prose,
  which interpolates an operator's free text (hard rule 6, same line `admin/holds.py`
  draws). **§1's latency p50/p95 and answer-rate tiles are deliberately NOT built**:
  `calls.latency` was dropped in migration `f1a7c39d5be2` and D-49 removed the trace
  config, so neither is observable today and a tile would be a fabricated number on the
  screen operators trust most. The call trend carries a `basis` — `measured`, `too_new` or
  `no_baseline` — for the reason `after_hours_basis` exists, and the console has exactly
  one reader of it (`trendClaim`) which returns a union, so no code path can format a
  percentage the data does not support. `org:read`, not `admin:tenants` (D-22), realm-
  separated, unaudited by design like the hold queue, and cross-tenant with **no RLS policy
  widened**: the directory under `app.admin`, then each tenant's own session. Money is a
  string on the wire. The R-11 holds appear only as CAUSES and link to the hold queue's own
  remedy screens rather than being re-implemented here.
- **Prompt history + rollback** per agent (`/admin/tenants/{id}/agents/{agentId}/prompt`;
  `GET|POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt`, `…/prompt/rollback`).
  Rollback is copy-forward, never pointer-rewind (FLOWS §7).
- **First publish** ("Voice platform"), on that same page: puts an agent that has never
  reached the engine onto it (`POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/
  publish`). It is a separate control from Apply because Apply is a RE-publish — it pushes
  only when the agent is already live — so before this panel existed there was no screen
  anywhere that could make a wizard-created agent dialable. `published` is the server's
  answer (`engine_agent_ref IS NOT NULL`) and never inferred from `status`; the button is
  disabled with the server's own precondition when the agent has no prompt version, since
  publishing one is refused (`agent_has_no_script`) rather than filled in with a
  placeholder. The panel states that it publishes and signs nothing off: FLOWS §1 step 7's
  test call and regression run are pilot-gated.
- **Pending invitations for a client** (on the wizard's invite step;
  `GET`/`DELETE /v1/admin/tenants/{tenant_id}/invitations[/{invitation_id}]`) — the live
  keys to a client's account, addresses masked, with a cancel. It exists because minting a
  second live token for one address is refused: without a way to see and cancel the first,
  an operator whose token was lost was stuck for 72 hours, and the client-realm revoke
  cannot help an account whose owner has not signed in yet.
- **Two-speed publishing controls**, on that same page: **Apply to live calls** /
  **Undo** (`POST …/apply` with the staged version as the CAS token, `POST …/undo`) and
  the **per-agent call cap** (`PATCH …/call-cap`, applies immediately — a live agent is
  re-published in the same transaction). The version list distinguishes *staged* from
  *live*: `active` on a history row is the DRAFT pointer, and the live version number
  comes from the pending read.
- **Printable invoice statement** (`/admin/tenants/{id}/invoice`;
  `GET /v1/admin/tenants/{tenant_id}/invoice`) — a white, print-first document. It is a
  DERIVED statement, not a stored row (see DATA-MODEL §8).
- **Credit top-up and corrections** (`/admin/tenants/[tenantId]/credits` —
  `POST|GET /v1/admin/tenants/{tenant_id}/credits`, `POST .../credits/adjustments`) —
  **SHIPPED** (D-82, D-87). The screen records a payment against its bank reference, which
  doubles as the idempotency key and as the typed confirmation — different every time, so
  it cannot become muscle memory. Corrections are APPENDED against a named ledger row
  (hard rule 4: the wrong entry stays, because it is the evidence), bounded by that
  entry's remaining reversible amount, and step-up-confirmed only in the direction that
  takes credit AWAY. The response's `stops_dialling` is the dial gate's own verdict on the
  balance the write produced, rendered as a stop-toned notice — never re-derived on the
  client. `runbooks/topup-payments.md` §3 no longer describes hand-constructing the call.
  The self-serve wallet UI in §2b is separately still M2.
- **Ops** (`/admin/ops`; `/v1/ops/platform`, `/v1/ops/outbox/replay`, `/v1/ops/audit/verify`).
  `GET /v1/ops/platform` returns the load-shed mode, the outbound halt, **`halt_reason`**
  and the TM registration in ONE row read — a halt shown beside a reason from a different
  instant is worse than either alone. The reason is REQUIRED to halt (a halt nobody
  explained is one nobody can safely lift), cleared on release, and untouched by a
  load-shed-only change. **The step-up header names the transition, not the endpoint**
  (D-45): `X-Confirm-Action: halt_outbound` / `release_outbound` / `set_load_shed:<mode>`,
  joined with `+` when one request does both. The old blanket `set_platform_state` string
  authorises nothing; the refusal prints the header that would have worked. The **outbox
  replay** takes the same treatment, and its target DOES vary: `replay_dead_letters` for
  the whole queue, `replay_dead_letters:<job>` when scoped to one job, refused in both
  directions so a header can never authorise a wider act than the request performs. It is
  the most destructive control on this screen and was until recently the only one without
  a header, which is worth stating plainly: replaying does not merely flip rows, it
  RE-SENDS — real HMAC-signed webhooks into clients' CRMs, real Sheets appends, real
  emails, across every tenant at once. Scoping exists because of the 100-row cap: an
  operator recovering one client's CRM webhooks out of a queue full of dead-lettered
  emails would otherwise replay 100 emails, read `replayed: 100` as success, and leave
  every webhook parked. Per-TENANT scoping is not offered and cannot be: `outbox_messages`
  is an infra table with no `tenant_id` (BACKEND-PATTERNS §4), tenant ids sit unindexed
  inside the JSONB payload, and the console says so rather than letting an operator assume
  the scope bounds WHOSE data moves.
  `GET /v1/ops/platform` carries **`outbox_dead_letters`** — depth, per-`job` breakdown and
  the oldest entry's age, from ONE grouped aggregate that is also the source of the
  `outbox_dlq_depth` metric, so the number an operator confirms against and the number the
  alert fires on cannot drift. It is there rather than on a route of its own for a reason
  worth keeping: `ops:manage` is a MUTATING permission, so a new GET declaring it would
  have to be written into `ADMIN_CONSOLE_GETS` — an allowlist whose own test warns that
  entries are how it becomes a hole. A field on an already-exempt route adds none.
  `GET /v1/ops/audit/verify` is the one deliberate exception on this router: it reads and
  writes nothing.
- **Spend-cap recompute** (`POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute`,
  `ops:manage`, step-up bound to the tenant, audited on the same session as the write).
  Re-derives `spend_state.capped` from counters already metered against the ceiling now
  in force, and **never writes the flag directly** — an ops button that set `capped=false`
  would be a third DEFINITION rather than a third caller. It closes a real dead end: the
  gate reads the flag, a capped tenant meters nothing so the meter can never clear it,
  and the client's own `PUT /v1/billing/caps` needs `org:manage`, which D-22 refuses to an
  impersonating admin — so an outbound-only client whose ceiling ops had just raised
  stayed stopped until they acted themselves or the IST month rolled over. The response
  reports the counters and the effective ceiling next to the flag, so "it did not work"
  becomes "the ceiling is 2 and they have used 3".
- **Global do-not-call** (`/admin/ops/dnc`; `GET`/`POST /v1/ops/dnc/global`,
  `DELETE /v1/ops/dnc/global/{entry_id}`, `ops:manage`, both writes step-up confirmed and
  audited). The writer for `dnc_list.scope='global'` (D-107) — an ABSOLUTE platform-wide
  suppression, ranked above every tenant's own list and removable by no client. Its own
  nav entry rather than a panel on `/admin/ops`, because whoever needs it is following
  `runbooks/dnc-complaint.md` and not scrolling a screen of platform switches. Two
  asymmetries are the design: the suppression takes ONE typed word for the whole paste,
  and the RELEASE is confirmed per row against the masked number it would un-suppress —
  lifting one re-permits dialling somebody who asked not to be dialled, for every client
  at once. `GlobalEntryOut.removable` is `is_removable()`'s answer about CLIENTS and is
  always false here, so it deliberately does NOT gate the ops control.
- **WhatsApp alerts for a client's owner** (panel on `/admin/tenants/{id}`;
  `GET`/`POST /v1/admin/tenants/{tenant_id}/whatsapp-alerts`, `admin:tenants`, audited) —
  for the opt-in given on an onboarding call rather than on the client's own screen. A
  grant carries the reference of the document it rests on (the service AND a CHECK refuse
  one that cannot evidence itself); a withdrawal needs none. The GET exists so the panel
  is not write-only: the ledger is append-only, so recording a month-old form over last
  week's withdrawal is not editable, and the client-realm read deliberately reports no
  subject state to an impersonated session.
- **Calevate's own TM registration** (`POST /v1/ops/platform/tm-registration`, `ops:manage`)
  — the company half of SEC-COMP §3's first bullet, recorded on `platform_state` (D-43)
  and returned by `GET /v1/ops/platform`. Step-up confirmed in BOTH directions, with the
  header naming which one: `X-Confirm-Action: record_tm_registration` to make it live,
  `withdraw_tm_registration` to take it out of `active`. Audited in the same transaction
  as the write. While it is not `active`, NO tenant can launch an outbound campaign,
  however complete their own PE registration is; inbound answering is unaffected.
- **Identity (KYC)** (`/admin/tenants/{id}/kyc`; `POST /v1/admin/tenants/{tenant_id}/kyc`,
  `admin:tenants`, audited) — where the verification is recorded. Its own screen rather
  than a panel, because it is an audited write with four fields an auditor asks about
  (what, against what reference, by whom, when) and the CHECK behind it makes a
  `verified` row that cannot answer them unstorable. Deliberately no client-realm twin:
  under the Telecom Act the subscriber's identity is something the provider verifies,
  never something the subscriber asserts.
- **The hold queue** (`/admin/holds`; `GET /v1/admin/compliance/holds`) — the ops work
  list of accounts waiting on a human, covering BOTH R-11 human-decision gates (KYC and
  the first-campaign review), oldest signup first because that is the triage order. It is
  also surfaced on the tenant directory, so the screen an operator already reads carries
  the flag. Built with **no RLS policy widened**: the directory under the admin session,
  then each tenant's own session asking the ordinary gate (`apps/api/admin/holds.py`
  argues the alternatives). `org:read`, not `admin:tenants` — D-22 forbids gating a GET on
  a permission read-only impersonation refuses, and the realm is what separates admin from
  client here. The row carries the account, its motion, its signup instant and the rule
  names, and deliberately NO reason text, signatory or document reference: the rejection
  reason interpolates an operator's free text, which belongs nowhere near the widest-read
  list in the console (hard rule 6). Read-only and unaudited by design — every decision
  taken from it writes its own entry.
- **First-campaign review release** (`/admin/tenants/{id}/first-campaign-review`;
  `POST /v1/admin/tenants/{tenant_id}/first-campaign-review`,
  `admin:tenants`, audited, tenant in the PATH) — R-11's last mitigation and the ops half
  of it (D-51). `approved` releases the ACCOUNT, not the campaign: this rule never blocks
  another of its campaigns afterwards. `rejected` keeps it held and shows the client the
  reviewer's words. It upserts, so a release can be withdrawn when complaints arrive and
  granted again, and the history is `audit_log` rather than this row. No client-realm
  twin and no request path — absence of a decision IS the held state.
- **Client DLT Principal Entity registration**
  (`POST /v1/admin/tenants/{tenant_id}/dlt-registration`, `admin:tenants`) — upsert; the
  fact `launch_blockers` reads as `pe_registration_*` / `tm_link_not_active`. Deliberately
  has no client-realm twin: a client who could mark their own PE registration `active`
  would be marking the launch gate green on a registration that does not exist. Tenant in
  the PATH, not inferred from the session — an admin-realm mutation that infers its tenant
  is un-callable by construction under D-22.

Compliance API (client realm)
- **DNC**: `GET|POST /v1/dnc`, `POST /v1/dnc/check`, `DELETE /v1/dnc/{entry_id}`.
- **Messaging consent**: `POST /v1/compliance/messaging-consent` (`leads:dispatch`, 201,
  audited) records what a consumer said about being messaged, and
  `POST /v1/compliance/messaging-consent/lookup` (`leads:read`) answers whether we may
  message them. Both are POST because the identifier IS the personal data (same rule as
  `POST /v1/dnc/check`), neither echoes the number back, and there is no DELETE: the
  ledger is append-only, so "no longer" is `status: withdrawn`, a new row that
  supersedes. A number nobody has ever been asked about is a 200 saying
  `status: "none"`, not a 404. See SEC-COMP §4 for why this consent is separate from
  consent to be called.
- **DPDP subject export**: `POST /v1/compliance/subject-export`.
- **DPDP erasure**: `POST /v1/compliance/deletion-requests` (201; idempotent per open
  request — a duplicate is a 200-shaped body with `already_open`, not a 409) and
  `GET /v1/compliance/deletion-requests/{request_id}` for the proof certificate. Filing
  and status reads carry DIFFERENT permissions on purpose: filing is mutating, so D-22
  refuses it to an impersonating admin; a status read discloses no personal data and
  stays available to them. Every response carries the erasure's stated limitations
  (SEC-COMP §4). Both surfaces speak `subject_ref`, never the phone number.
- **Voice catalog**: `GET /v1/agents/voices` (D-36's premium/value ladder as data).
- **Scheduled campaign start**: `POST /v1/campaigns/{campaign_id}/schedule` /
  `DELETE` the same path (`leads:dispatch`, audited) — a ONE-TIME future start, stored
  in `campaigns.schedule` and fired by the dispatch tick. Same permission as `POST
  /launch` because it IS a launch with a delay on it, and the compliance gate runs at
  FIRE time rather than at schedule time (FLOWS §5). The response carries
  `first_dial_not_before`: a 22:00 start is accepted and answered with 09:00, because a
  start is not a dial. Recurrence is deliberately unbuilt.
- **Consent provenance for a campaign list**:
  `POST /v1/campaigns/{campaign_id}/consent-provenance` (`leads:dispatch`, drafts only,
  audited) — SEC-COMP §3's fourth bullet, and the answer path for a draft created before
  the columns existed. It refuses on a non-draft campaign, so a declaration cannot be
  back-filled after the dialling it was supposed to authorise.

Self-serve + payments (D-34/D-39) — **read the caveat, this is not a working checkout**
- **Signup**: `POST /v1/auth/signup` (201). Under `rbac.PUBLIC_PREFIXES`, which is the
  honest classification: no permission can gate a caller who has no organization yet. The
  locks are a verified **first-party** session with no membership (`current_identity`;
  D-177 — no permission can gate a caller with no organization, so the credential is the
  gate), a quota of 5 signups per user and 30 per IP per hour
  consumed on every
  ATTEMPT (a refused slug is not free — free failures are what make a limiter enumerable),
  and two switches: `self_serve_signup_enabled`, which **defaults to OFF** (R-11's kill
  switch — public tenant creation should be something someone switched on), and the
  platform load-shed mode. `/v1/auth` used to be exempt from shedding on the grounds that
  the exemption is right for signing IN — which was hollow while a vendor owned sessions,
  because the only route the prefix actually covered was this one. The exemption was
  removed; the route's own mode check stays as the second lock. **⚠ D-177 changed the
  premise and the list was not revisited**: `/v1/auth/{realm}/login` and `login/otp` are
  real, mounted, mutating routes now, so an operator holding no live session cannot sign in
  while the platform is in `reduced`, `emergency` or `maintenance` — including to turn the
  shed off, which is the one thing `ALWAYS_ALLOWED_PREFIXES` exists to protect
  (`core/loadshed.py` says a session route "should be exempted BY NAME, with the reason, on
  the day it exists"; that day has passed). Naming a route rather than restoring the prefix
  is the fix, and it is a decision about who may sign in during a shed — recorded here
  rather than made here. Creates the organization, its
  receptionist agent, its extraction schema and its retention policies, and makes the
  caller the owner; `plan_tier` is `self_serve` or `trial` — `managed` is the invoiced
  motion and is not self-assignable. The wallet starts empty, so the compliance gate
  refuses outbound until it is topped up, and the response says so in `next_steps`.
- **Top-up intent**: `POST /v1/billing/topups/intent` (`org:manage` — spending the client's
  money is not a read, and being mutating is what makes D-22 refuse it to an impersonating
  admin). Prices the top-up (₹100–₹100,000), binds it to the session's tenant, and refuses
  a `managed` tenant (`topup_not_available`) or a deployment whose payment capability is
  not configured (`payments_not_configured`). **Whether the capability exists is now a
  STATEMENT, not an inference**: `PAYMENT_PROVIDER` names it, `payments.payment_capability()`
  is the ONE selector both this route and the receiver ask (so a second read of settings
  cannot disagree), the only name with an adapter behind it is `razorpay` and any other
  resolves to `provider_not_implemented`, and a known provider still needs BOTH the key
  id and the webhook secret — a deployment that could take money and never credit it is
  refused on both surfaces. The refusal writes nothing. Same shape as the Google Sheets
  seam (§2 integrations). **NOT IMPLEMENTED: server-side order creation.** Creating
  the provider-side order needs API credentials this deployment does not hold, so the
  response carries `provider_order_id: null` and `provider_order_pending: true` — the gap
  is in the contract rather than discovered at integration time. There is no checkout that
  can be opened from this response today.
- **Payment webhook**: `POST /hooks/v1/razorpay` → one `credit_ledger` entry, signature
  verified before anything is read, inbox-claimed on `payment.captured:<payment id>` and
  idempotent on the ledger `ref` under the per-tenant credit lock. Never load-shed (a
  payment landing during degraded mode is still a payment); fails CLOSED with no secret
  configured. **The signing scheme and every payload path it reads are UNVERIFIED against
  a live Razorpay account** (`billing/payments.py` marks each one) — if they are wrong,
  every event is refused and nothing is credited. Treat the pair above as scaffolding with
  an honest hole in it, not as a payment flow.

Shared shape across all three compliance surfaces: a phone number is submitted in a POST
body and everything afterwards is keyed by an opaque id, never `GET /…/{phone}`. The
identifier IS the personal data, and a number in a URL lands in access logs, proxy logs,
referrers and browser history (hard rule 6).

## 3. Integration Layer (our site ⇄ engine [Bolna, D-31]) — DECIDED doctrine

The verified vendor surface lives in TRD §5 (events, HMAC, rate limits, Get Call).
This section fixes HOW we consume it. No compromises means: no lost events, no
duplicate side effects, no stale UI lying to a client.

### 3.1 Webhook intake pipeline (applies to every engine event)

Queue-first, idempotent, replayable — the industry-standard shape, mapped to our stack:

1. **Verify**: per engine capability (TRD §5). Signed engines: HMAC over raw body,
   timestamp window, timing-safe compare. **Bolna (unsigned)**: source-IP allowlist
   (**13.203.39.153, 13.126.9.249, 13.202.133.53 — THREE addresses; this named one until
   D-414, and the parser fails safe, so two of the vendor's three senders were being
   REJECTED**; via D-27 real_ip restoration) in-app, and there only — the edge layer
   is declined, not pending (SECURITY-COMPLIANCE §5); payloads are
   hints — truth comes from the authenticated Get Execution fetch. Unexpected
   source ⇒ 401 + alert (treat as attack until proven config drift — runbook).
2. **Dedupe**: replay-cache on the event key (Redis SETNX, 24h TTL; for Bolna:
   execution_id + status) AND idempotency keys on processing — dedupe at the door and
   at every side effect. **Bolna's delivery guarantee is UNSETTLED, not "at-most-once"**
   — the OSS single-POST deliverer D-31 read is a different program from the hosted one
   (D-352), their skills repo claims the hosted platform retries on non-2xx, and their own
   hosted webhook page says nothing about retries or guarantees
   (`bolna-findings/mirror/pages/guides/post-call/polling-call-status-webhooks.md`). Either
   way OUR poller re-surfaces the same executions, so duplicates occur downstream and the
   dedupe above is load-bearing under BOTH readings — which is why nothing here depends on
   settling it.
3. **Persist-then-ack**: write the minimal event row + archive raw payload to object
   storage, ack 2xx < 500ms. Never process inline (hard rule 3).
4. **Process async**: ARQ jobs keyed by event/call id; every side effect is an upsert
   or guarded by processed-state; **3 attempts**, outbound deliveries waiting 30s
   then 120s (`WORKER_MAX_TRIES` in `apps/api/core/queue.py`, `RETRY_BACKOFF_S` in
   `apps/workers/outbound_webhooks.py`); retried for transport failures / 5xx / 408 /
   425 / 429 only, any other 4xx stopping immediately as `rejected {code}`; DLQ +
   Sentry on exhaustion. ⚠ A plain `raise` in a worker is terminal on the first attempt
   under arq 0.28 — see the note in FLOWS §6 — so a job that wants the ladder must raise
   `arq.Retry`. The reconciliation poller in step 6 remains the guarantee of record
   either way (D-31).
5. **Replay tooling exists BEFORE the first incident** (industry lesson): admin
   surface to inspect webhook_deliveries, re-run a delivery, and re-run a pipeline
   step for a call id. **There is no engine-side supplement to it**: this line used to say
   "the engine's own per-delivery retry API supplements ours", and Bolna publishes no
   delivery history, no replay endpoint and no per-delivery retry anywhere in their
   documentation (`bolna-findings/mirror/`, TRD §5). Ours is the only replay there is.
6. **Reconcile**: **Bolna's delivery guarantee is UNSETTLED — this bullet claimed "NO
   retries at all (verified)" and the verification did not cover the hosted platform.**
   The OSS single-POST deliverer is a different program (D-352); their skills repo says the
   hosted platform retries on non-2xx; their own hosted webhook page says nothing about
   retries, signing or guarantees. Design for loss either way — which is what makes the
   10-min List-Executions poller (FLOWS §3) the guarantee of record rather than a safety
   net (D-31), a conclusion that holds under BOTH readings.
   Reconciliation closes the loop: exactly-once PROCESSING = idempotency +
   reconciliation, not delivery magic.

Outbound webhooks (us → client tools, D-23) mirror the same doctrine from the sender
side: our envelope, HMAC signing, the same flat 3-attempt ladder (`MAX_ATTEMPTS` is
`WORKER_MAX_TRIES` — deliberately ONE budget so the last try knows it is the last and the
`outbound_webhook_exhausted` alert has a moment to fire; the FLOWS §6 arq trap that made
that alert unreachable is FIXED — `deliver_outbound_webhook` raises `arq.Retry(defer=…)`,
so the ladder walks and the exhaustion branch is live), delivery log (webhook_deliveries direction=out, one
row per delivery with `endpoint_id`), and a per-endpoint disable switch on repeated
failure. The client-facing form of these rules is WEBHOOKS §1.5.

**Which events actually fire.** `lead.created` (ingest), `lead.updated` (any edit that
MOVES a lead — the single-lead PATCH and the bulk action, one event per lead per request)
and `call.completed` (post-call pipeline) are produced. `campaign.completed` is
subscribable and has no producer: the endpoint form offers it, nothing enqueues it, and
`tests/crm_egress_known_gaps_test.py` records that as an open gap with the act that
closes it rather than leaving a client to discover it by waiting. A Sheets endpoint
subscribed to it is refused with `no_column_order` on every delivery, which is the honest
half of the same hole.

**What is IN the payload, on both kinds.** The phone is the masked string by default and
raw only on the endpoint's own recorded opt-in (`mapping.include_raw_phone`), applied at
the fan-out because that is the last point that knows which endpoint a body is for. The
`call.completed` summary is redacted BY THE PRODUCER (`workers/pipeline`) before it ever
reaches an outbox row — the column it comes from is stored raw — and the transcript never
leaves at all. `tests/crm_egress_redaction_test.py` asserts all of this on the BYTES
handed to the socket and to the Sheets transport, not on a field of an object.

Every cell of a Sheets row goes through the formula guard, and so does every cell of the
HEADER — `columns` and `headers` are free strings on the endpoint's mapping, a heading is
a cell, and the CSV export's own comment already cited this writer as the rule it copied.

The delivery log answers "did it arrive?"; the retained BODY (`payload_ref`) answers "and
what was in it?" — the question that actually ends a dispute. It is unredacted customer
data, so the screen offers it only to a holder of `calls:read_raw` and only where a copy
still exists, and opening it writes an `audit_log` row, exactly like a raw transcript
(hard rule 5). Retention, erasure and the size cap are SEC-COMP §4; what the SCREEN owes
is that a missing copy reads as a stated absence rather than a link into a refusal, and
that a truncated copy says so.

### 3.2 Real-time UI sync (D-24)

- **v1 (M1): TanStack Query polling.** Dashboard/leads refetch on interval + on window
  focus; post-call data appears within the 2-min SLO without any new infra. Boring
  solution first, per doctrine.
- **Upgrade (with M3 moat work): SSE, not WebSockets.** One `/events` stream per
  client session (live call tiles, lead-created toasts); server pushes invalidation
  hints, TanStack Query refetches — events carry "what changed", never payloads
  (avoids auth/staleness bugs in the stream). SSE chosen because our flow is strictly
  server→client, it's plain HTTP (no proxy/infra changes), and it's materially
  cheaper per connection than WebSockets. WebSockets are explicitly NOT planned — we
  have no client→server streaming need; revisit only via a decision-log entry.

### 3.3 Engine API usage rules (adapter-internal)

- Client-side throttle with 429 ⇒ backoff + jitter. **Bolna's API rate limits ARE
  published and this line used to say they were not**: 500 req/min each on `/call`,
  `/v2/agent/{id}` and `/v2/agent/{id}/executions`, 1000/min elsewhere, counted per
  ORGANIZATION (`bolna-findings/mirror/pages/api-reference/rate-limiting.md:18-27`).
  DISPATCH pacing — how fast the platform will actually dial — is a different quantity and
  is still unpublished (pilot); OUR dispatcher paces outbound creation regardless
  (FLOWS §5).
- Get Execution on `completed` (webhook and poller share the payload shape — TRD §5;
  cost/recording/extraction fields are null before `completed`); recording copy is
  the first pipeline step — and copy-first is what carried us through the vendor's one
  dated breaking change: raw S3 recording URLs stopped working 1 Jun 2026, replaced by
  `https://api.bolna.ai/recordings/call/{execution-id}` whose *"resolved pre-signed link …
  expires after 24 hours — do not store or cache it"*
  (`bolna-findings/mirror/pages/changelog/may-2026.md:91,99,118`). We never parse, store or
  re-use a vendor URL; `calls.recording_url` holds our own object key, so the 24h window
  only has to outlive one fetch. Our storage is system of record.
- All engine calls carry timeouts + circuit breakers (TRD §12); breaker-open ⇒
  degrade to reconciliation mode, never drop work. **Shipped today: the timeout only**
  (`REQUEST_TIMEOUT_S = 10.0` in `apps/api/engine/bolna.py`). The 429 throttle above and
  the breaker are DECIDED and unbuilt — the dispatcher's own pacing and the
  reconciliation poller are what currently stand in for them, so treat both bullets as
  intent until an adapter carries them.
- **A vendor OpenAPI spec DOES exist and this line used to deny it**: Bolna publishes an
  OpenAPI 3.1 document (`docs/vendor/bolna/hosted-oas.md` holds the pin, the checksum and
  the endpoint inventory), and their full documentation set is mirrored read-only under
  `bolna-findings/mirror/` with a per-page SHA-256 manifest. Typed adapter models are read
  from those rather than from recollection. A spec is still what the vendor SAYS the server
  does: pilot-captured payloads are committed as fixtures, payload drift is caught by the
  conformance suite, and new fields get a diff-review before adoption.

---

Cross-references: BRD §4–5 (scope + competitor floor) · TRD §5 (vendor surface) ·
FLOWS §3/§5 (lifecycles) · SECURITY-COMPLIANCE §5 (auth/audit) · ROADMAP D-21…D-24.
