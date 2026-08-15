# PLAN — Harden every surface, then move dashboard AI to Gemini

**Status: PARTS 1–16 and 18 IMPLEMENTED (D-127 … D-138). PART 17 is pilot-gated.**
Written 15 Aug 2026, revised the same day with the founder's answers folded in, and again
when the work landed. The parts below are kept as WRITTEN, not rewritten into the past
tense: what each one found is recorded in its decision row, and a plan edited to match its
outcome stops being evidence of what was known beforehand.

Part 17 (BYOK Gemini for the in-call LLM) is the only part not built, and deliberately —
it needs the Bolna Engine Verification Session to answer whether the custom-LLM config
accepts auth at all, what a proxy hop costs the latency budget, and where Bolna's own
servers run. See §6 and Part 17.

Everything here lands **before** external accounts and real keys are wired in — the Bolna
account, the DLT registration, the DID vendor, the Razorpay secret, the GCP project. The
principle is that **a credential should arrive into a system that is already correct**,
because a live key turns every remaining defect from an embarrassment into an incident
with someone else's customer data in it.

Eighteen parts. Each is a unit of work one person can pick up and finish: why it exists,
what changes, which files, what "done" means, and what must be true before it starts. Per
CLAUDE.md there is no later — parts are **ordered, not scheduled**.

---

## 0. How this plan was produced, and how to read it

Two exhaustive read-only audits, both mechanical rather than by eye.

- **Backend**: 176 routes enumerated three independent ways — the live FastAPI route table
  walked with `rbac.iter_api_routes`, the generated `openapi.json` (171 operations / 145
  paths), and `scripts/check_wiring.py`. All three agree: nothing undocumented, nothing
  stale, no unmounted router. **96 of the 176 are mutating.**
- **Frontend**: 43 `page.tsx` + 3 layouts = 46 route files, plus every non-page component
  holding its own query; 77 query hooks enumerated from `src/lib/api/*.ts` and every call
  site checked for an unread `isError`.

Every finding carries an evidence level. **READ AT SOURCE** — someone read the line.
**REPORTED, NOT READ** — from a vendor doc or a search result, not verified against the
running thing. **INFERRED** — follows from lines that were read. That distinction is not
pedantry: this repo has shipped a defect that came from treating an inference as a fact
(D-31/D-32), and vendor behaviour in particular is a gate in OPERATIONS §2 or a marked
assumption in an adapter, never a silent premise.

**Every part below ends the same way**: sabotage each new guarantee, confirm the failure
signatures are distinct, restore, and assert a green baseline either side. A test that
cannot fail is worth less than no test, because it also carries a claim.

---

## 1. Decisions this plan assumes

Taken by the founder, 15 Aug 2026. Each becomes a decision-log row when the work starts.

| # | Decision |
|---|---|
| **G-1** | Gemini is reached through **Vertex AI, `asia-south1` (Mumbai)** — never the AI Studio Developer API. |
| **G-2** | Dashboard AI sees **tenant-authored config plus REDACTED call data**. Never raw PII. |
| **G-3** | **One Calevate-owned key, cost absorbed.** Metered per tenant; charged only past an included quota. |
| **G-4** | Overage is **one `credit_ledger` row, reason `usage`** — no per-request billing, no new ledger. |
| **G-5** | **Quota exhaustion prompts a modal.** Nothing is debited from the wallet until the user explicitly accepts. |
| **G-6** | On Gemini failure: **fall back to Sarvam or refuse with a message.** A fallback is always disclosed. |
| **G-7** | **First post-call extraction stays Sarvam.** Gemini serves the *user-triggered* work afterwards — re-summarise, reshape, ask-about. |
| **G-8** | **Autofill always requires human approval** — client or operator. It never reaches the publish path unapproved. |
| **G-9** | Hardening covers **every route**, including load and abuse posture, plus an adversarial pass. |

### Why G-7 is the right shape, and what it resolved

The original instruction — "Gemini for all AI outside the live call" — collided with G-2.
Post-call extraction *is* outside the live call, and it is the one path that must see raw
PII: `apps/workers/pipeline.py:750` builds the transcript from `turn.text`, **not**
`redacted.text`, one line after computing both, because a CRM "callback number" field
needs the actual digits. An extractor reading `[REDACTED]` returns nothing useful.

G-7 resolves it cleanly and better than my own first instinct: **the raw-PII pass stays
sovereign (Sarvam), and everything the user asks for afterwards runs on Gemini over the
redacted copy.** The decision row must say this in words, because the instruction reads
the other way at a glance and the next person to touch `get_extractor()` will read it that
way.

### On choosing between the models by evidence

I searched for a Sarvam-vs-Gemini comparison that decides this and **the public
benchmarks do not answer our question.** Sarvam Vision beats Gemini 3 Pro on olmOCR-Bench
(84.3% vs 80.2%) — that is *OCR*. Sarvam-M lags on Hindi grammatical error correction
(13.81 GLEU, attributed to parameter count) — that is *GEC*. Nobody has published **Telugu
code-mixed call transcript → structured CRM fields**, which is the only benchmark that
governs this choice. [REPORTED, NOT READ]

So the honest answer is not to pick from someone else's leaderboard. **This repo already
owns the right instrument** — the golden-transcript fixtures and `scripts/eval.py`, which
is a regression ratchet rather than a vibes check. Part 16 prepares it to score both
providers head to head; the decision is made by that run, on the day keys exist.

---

## 2. What Gemini already is in this tree

READ AT SOURCE. This is a promotion of something that exists — and what exists points at
the wrong door.

- `apps/workers/extraction.py:55` — `GEMINI_CHAT_URL` is
  `generativelanguage.googleapis.com`, the **AI Studio Developer API**: a global endpoint
  with no region in the host.
- `:137` — authenticates with `params={"key": …}`. **Vertex does not accept an API key in
  the query string.**
- `:124-152` — `GeminiExtractor`, ~28 lines of raw `httpx`. **No Google SDK anywhere in
  this repo.**
- `:129` — default model `gemini-2.5-flash-lite`, which **retires 16 Oct 2026** (BRD R-04).
- `:564-572` — `get_extractor()`: Sarvam wins; Gemini only when Sarvam's key is absent.
  Its docstring already states the principle this plan extends: *"there is no silent
  failover between providers, because they differ on data residency (D-36) and that is not
  a runtime decision."*

### The external research behind G-1

- The **AI Studio / Gemini Developer API offers no data-residency guarantee**, and on the
  **free tier Google uses prompts, uploads and responses to improve its products, with
  human reviewers able to read them.** Disqualifying for this product.
- **Vertex AI `asia-south1`** processes in-region, keeps data at rest in-region, and does
  not train on paid usage. Gemini 3.x Flash, Flash-Lite and Pro are all available there.
- **Pricing carries a known cliff.** Gemini 3.7 Flash launched 13 Aug 2026 at **$0.75 /
  $3.75 per 1M tokens introductory**, reverting to **$1.50 / $7.50 on 1 Jan 2027**. Batch
  is 50% off; cached input ~$0.15/1M. Any margin model built on today's number must carry
  that date or be wrong in four months. [REPORTED, NOT READ]

---

# PART 1 — Unblock the console: CORS

**Why first.** `PUT /v1/ops/secrets/{key}` is how a vendor credential gets installed, and
**a browser cannot call it today.**

`core/middleware.py:301` lists `GET, POST, PATCH, DELETE, OPTIONS` — **no `PUT`** — and
`allow_headers` omits `If-Match`. The web app is cross-origin in every environment
(`client.ts:19`, direct `fetch` at `:315`; there is no Next rewrite proxy), so Starlette's
preflight refuses. Five routes are unreachable from the browser: `PUT /v1/billing/caps`
(the client's own spend cap), `PUT …/feature-flags/{flag}`, `PUT /v1/ops/config/{key}`,
`PUT /v1/ops/secrets/{key}`, and `DELETE /v1/ops/config/{key}` (sends `If-Match`).
**Nothing goes red**: web tests mock `fetch`, and CORS is browser-side only. [READ AT SOURCE]

**Changes.** Add `PUT` to `allow_methods`, `If-Match` to `allow_headers`.

**The guard that matters more than the fix.** A test that walks `iter_api_routes(app)`,
collects the method set, and asserts it is a subset of `allow_methods` — plus `client.ts`'s
header names against `allow_headers`. Without it the same class returns the next time a
method is introduced.

**Files** `apps/api/core/middleware.py`, new `tests/cors_contract_test.py`.
**Done when** a preflight for each of the five routes succeeds in test, and adding a
seventh method to any router fails CI until `allow_methods` follows.

---

# PART 2 — One client IP, and a rate limiter that means what it says

Two defects that compound, and the first corrupts the compliance record.

**2a. Every audit row's `ip` is the proxy's.** `core/auth.py:783` reads the socket peer,
so SEC-COMP §5's "actor, tenant, at, ip" is satisfied in shape only. Worse,
`tenancy/signup.py:186` spends `SIGNUPS_PER_IP_PER_HOUR = 30` against that one shared
value and **fails closed** — so 30 signups an hour caps the entire platform and one abuser
denies self-serve signup to everyone. The fix already exists in this repo:
`voice-runtime/engine_intake.py::client_ip` counts exactly one trusted hop and fails
closed, and nginx now *sets* `CF-Connecting-IP`, which makes the `_request_ip` docstring
saying otherwise stale. [READ AT SOURCE]

**2b. The limiter's identity bucket is `hash(auth)`.** Python salts `str.__hash__` per
process and prod runs `--workers=2`, so one token occupies N buckets — the effective limit
is N× the declared one and changes on every restart — and the 32-bit truncation lets one
tenant consume another's bucket. `blake2s` fixes it in one line. [READ AT SOURCE; the N×
multiplier is INFERRED from worker count]

**Changes.** Promote `client_ip`/`is_trusted_peer` into `packages/shared` (one definition,
per "one way per problem") and use it for `_request_ip`, the signup quota's IP dimension,
and the limiter's unauthenticated fallback. Switch the identity key to `blake2s`.

**Files** `packages/shared/…`, `apps/api/core/{auth,middleware}.py`,
`apps/api/tenancy/signup.py`, tests.
**Done when** an audit row records the caller's address behind a proxy, two forged
`CF-Connecting-IP` hops are refused, and the per-identity limit is stable across a restart.

---

# PART 3 — Every route gets a limit and a ceiling (G-9)

Part 2 makes the identity real; this part applies it **everywhere**, which is what "every
route" was asked for.

**Today**: nginx applies per-real-IP `limit_req` zones (auth 20r/m, admin 180r/m, client
120r/m, webhooks 600r/m burst 200, health 60r/m) and a 2 MiB app-wide body cap with 25/10
MiB per vhost. That is a real defence and the audit credits it. What is missing is the
**per-tenant** dimension and per-family isolation. [READ AT SOURCE]

**Changes.**
1. A **per-tenant** limit alongside per-IP, since one tenant behind one NAT is the ordinary
   Indian SMB case and per-IP alone punishes the wrong party.
2. **Split the `/hooks` profiles.** All five share one bucket, so a lead-intake flood 429s
   the **payment** and **identity-mirror** webhooks. Key the ingest profile on
   `webhook_id`, the natural per-tenant dimension.
3. **Cost-weighted limits** on routes that do expensive work — a vendor round trip, an LLM
   call, a large export, an email send — rather than one flat number for a 1-row read and a
   20,000-row CSV.
4. A **route-census test**: every route in `iter_api_routes` is covered by a named limit
   profile, so a new route cannot be born unlimited.

**Done when** the census test fails on an unprofiled route, and a per-tenant flood is
refused without touching a neighbour.

---

# PART 4 — Stop the egress path from being a scanner

**`integrations/routes.py:280` validates a tenant-supplied webhook URL as `HttpUrl` and
nothing more.** Any tenant `owner` can register `http://169.254.169.254/…` or an RFC1918
address, and `integrations/service.py:534` POSTs **signed lead payloads carrying a name and
a phone number** to it. Redirects are blocked and bodies are not stored, so it is a *blind*
SSRF — but status codes and error types are readable back through
`GET /v1/integrations/deliveries`, which makes it an internal port scanner and a PII egress
channel into the private network. Grep for `is_private` / `link_local` / `169.254` across
integrations and workers returns nothing. [READ AT SOURCE]

**Changes.** One `assert_public_http_url()` used at **registration and again at connect
time** — resolve, reject loopback/link-local/private/multicast/reserved, reject non-80/443,
and **re-check after DNS**, because registration-time DNS can be rebound. Pair with the
existing `follow_redirects=False`.

**Also in this part**: creating an egress endpoint writes **no** `audit_log` row while
deleting one does (`:280`/`:314` vs `:467`). Registration is the act that starts lead PII
leaving the tenant, and it is the act with no record of who did it. Of 96 mutating routes
these two are the only real audit gaps — every other unaudited handler audits in its
service, writes a lead-timeline row, or is a read.

**Done when** a link-local, a private, a rebinding and a non-80/443 destination are each
refused with their own message, and registration writes an audit row carrying the **host**,
never the full URL with its query.

---

# PART 5 — Close the unauthenticated information surface

**`GET /healthz/ready` names the configuration keys this deployment is missing**
(`core/health.py:128`), plus queue depth and oldest-job age — unauthenticated,
rate-limit-exempt in-app, and publicly proxied. That is an oracle telling the internet
which credentials are not installed yet, which is **most dangerous during exactly the
window this plan exists to prepare for.** [READ AT SOURCE]

Separately, `/docs`, `/redoc` and `/openapi.json` are served **unauthenticated in prod**
(`bootstrap.py:182`). The repo already half-knows: `integrations/routes.py:314` moved a
docstring into a `description` specifically because "`/docs` is in PUBLIC_PREFIXES".

**Changes.** Keep the status code — a probe needs it — and move the *detail* behind
`ops:manage` or the existing origin lock; unauthenticated callers get `{status, service}`.
Turn the docs routes off in prod (the web client is generated from the checked-in
`openapi.json`, so nothing loses a capability).

---

# PART 6 — Adversarial pass (G-9)

Authorised testing against our own code and a local deployment; no third-party systems.
Ordered by what the audit suggests is worth attacking rather than by a generic checklist.

1. **Tenant isolation under adversarial input** — path/body/header tenant confusion, IDOR
   sweeps over every `{tenant_id}`/`{agent_id}`/`{lead_id}` route with a valid token from a
   neighbouring tenant. RLS should make these zero-row rather than 403, and the difference
   is worth confirming empirically.
2. **The realm boundary** — every admin route with a client token and the reverse, plus the
   impersonation header in every malformed shape (D-119 was exactly this class, and blank
   was the state nobody designed).
3. **Idempotency and replay** — double-submit every money path, replay top-up webhooks with
   altered amounts, and race the credit debit.
4. **Injection surfaces** — SQL through every `text()` parameter, CSV formula injection on
   the five export surfaces (D-116 found the fifth), header injection into email and
   webhook paths.
5. **Auth token handling** — expiry, `fva` claim absence, algorithm confusion, forged
   impersonation grants.
6. **Resource exhaustion** — the limits from Part 3, oversized bodies, deep JSON nesting
   (`voice-runtime` already catches `RecursionError`; the API path is untested for it),
   and the 20,000-row export.

**Output** is findings in the same table shape as the audits, each with a reproduction. Any
finding that is real is fixed in this plan, not filed.

---

# PART 7 — One shape per problem, and guardrail hygiene

**7a.** `PATCH /v1/agents/{agent_id}/voice` (`voice_routes.py:244`) is admin-realm but sits
in the **client** path space and takes its tenant **in the body**, while the house pattern —
pinned by `tests/route_shape_test.py:368` — is `/v1/admin/tenants/{tenant_id}/…`. It is the
only admin-realm route outside the admin path space. Two ways to do one thing is a defect
even when both work, and this is the one the next author copies. Move it, then add the
assertion "no admin-realm route lives outside the admin path space".

**7b.** The D-22 mutating sweep's exemption set (`tests/authz_audit_test.py:353`) has **no
staleness guard** — rename a route and its entry silently becomes a permanent hole for
whatever lands on that path. Its sibling allowlist has exactly this assertion
(`impersonation_reads_test.py:88`); the lesson was learned in one file and not the other.

**7c.** `loadshed.py:38` exempts `/v1/auth` so sign-in survives maintenance mode — but
**the only route under `/v1/auth` is `signup`**, a heavy multi-table write. Emergency mode
currently still admits new tenants.

---

# PART 8 — The 27 routes with no HTTP test

27 routes have no test at the HTTP layer; several are tested only at the service layer, so
the route wrapper — permission dependency, error mapping, audit write, response model — is
never exercised. Includes the KB approve/reject/publish trio, DLT template and number
status, prompt rollback, saved-view edit/delete, the Sheets endpoint, and the top-up
capability read.

One request-level test each: 403 for the wrong role, 403 under impersonation where
mutating, and the happy-path status and response model. Mechanical, and the kind of work
that finds two or three real defects on the way through — the erasure-list gap the ratchet
just caught was exactly this class.

---

# PART 9 — Six half-wired ops routes

The global-DNC surface (4 routes) and the WhatsApp alert opt-in (3) exist in code and in
the generated types and are called by **no client and no screen** — reachable only by curl.
Either build the two small admin panels, or record in ROADMAP §6 that they are deliberately
curl-only ops procedures and name the runbook that uses them. Silence is the one option
"leave no half-wired feature" forbids.

---

# PART 10 — The frontend refusal sweep

Seven real §52 violations — "loading is a skeleton, failure is a refusal, and neither is a
number, a state, or an empty state". [READ AT SOURCE]

| Screen | What a failed read renders today |
|---|---|
| `admin/…/lifecycle/page.tsx:244` | **The worst one.** `useTenantErasures`'s `isLoading` and `error` are read nowhere; `filed.data?.[0]` undefined falls through to the **"Erase this client's data" form**. So during the read and after it 503s, the screen states no erasure has been filed and offers an irreversible DPDP tenant-wide erasure **that may already be running.** |
| `lead-sources/page.tsx:592` | A failed `/v1/agents` leaves only "Not yet — save leads, don't call", so the client **persists a source that never dials**, believing they have no agents. |
| `leads/page.tsx:235` | The "Call this lead" control **silently vanishes**. |
| `calls/[callId]/page.tsx:85` | The follow-up card **hides itself** — the exact silent-nothing the card's own comment says it exists to prevent. |
| `c/[slug]/page.tsx:53` | "Spend this month" renders `—` forever, unexplained. |
| `integrations/page.tsx:100` | The last live `EXEMPT` entry; fails closed but silently. Move to `useWriteAccess`, which already says *"We could not check whether you can…"*. |
| `campaigns/page.tsx:149` | `BLOCKER_COPY` is a **second copy of a server rule**; a reworded server blocker loses silently to a stale client string. |

**And the guard, which matters more than the seven.** `tests/surfaceStatesGuard.test.ts`
is good, and its stated blind spots are exactly where these live: `?? []` outside a JSX
child, `?.[0]`, `{q.data && …}`, and ternaries. Closing the class is the deliverable;
closing the instances is the by-product.

**Found clean, and worth not disturbing**: the a11y sweep (45/46 screens, one waived with a
named closer, zero accepted violations), fail-closed defaults everywhere
(`useWriteAccess` never returns `allowed: true` without a response in hand), server
verdicts never recomputed (`is_verified`, `messageable`, `ready`, tri-state
`disclosure_played`), and the optional-on-the-wire discipline (122 optional properties, 32
of the dangerous shape, every access guarded).

---

# PART 11 — The Gemini decision row, first

Nothing may cite a decision that does not exist. One row superseding **D-36's LLM leg**,
recording G-1 through G-8 — and stating in words that **extraction stays Sarvam because it
sees raw PII**, since the instruction reads the other way at a glance.

`SECURITY-COMPLIANCE.md:153` needs rewriting rather than editing: it currently reasons
*"Sarvam is sovereign, so no transcript text leaves India"*. Under this plan the reasoning
becomes *"the endpoint is regional"* — a different argument reaching the same guarantee,
and the client DPA gains Google Cloud as a named sub-processor.

---

# PART 12 — The residency guardrail, before any Vertex code

Executable, in `make guardrails`, in this repo's style — not a comment. It asserts:

1. **No global Google model host in any URL literal** under `apps/`, `packages/`,
   `scripts/` — specifically `generativelanguage.googleapis.com` (which is
   `extraction.py:55` today) and bare `aiplatform.googleapis.com` with no region prefix.
2. Every `*-aiplatform.googleapis.com` literal carries region **`asia-south1`**.
3. **The region is a `Final` constant and is NOT reachable from console-editable config.**
   A region an operator can change from a web form at 3am is a residency posture invertible
   by a click — the doctrine `check_bootstrap_keys` already applies to `APP_ENV`.
4. The `locations/{…}` path segment interpolates only that frozen constant.
5. **Negative controls**: a doctored tree containing a `us-central1` URL must fail.

Decidable from syntax, needs no network, and makes the wrong endpoint *impossible* rather
than discouraged. **This is why it precedes Part 13** — write the guard before the client
that could violate it.

---

# PART 13 — The Vertex client

OAuth2 service-account auth, project and location in the path, `google-auth` added with its
lockfile diff read (hard rule 9 — the July 2025 ESLint `postinstall` incident is the
reason). Land on **3.x Flash-Lite**, not 2.5, which retires 16 Oct 2026. The **response
shape is identical** to the Developer API, so the parsing at `extraction.py:148-152`
survives unchanged; what changes is the host, the auth, and the credential's home (secrets
manager, never `platform_config`).

**Structured output.** Vertex supports a response schema that guarantees valid JSON — which
replaces `_first_json_object`'s fence-stripping for the Gemini path. Worth taking: a
model-side schema is a stronger guarantee than a parser, and the schema counts against the
input token budget, which Part 14 meters.

---

# PART 14 — Metering, quota, and the wallet modal (G-3, G-4, G-5)

## The metering defect this part must not inherit

Confirmed by reading migration `b8d3f47c2a19:185`:

```sql
CREATE UNIQUE INDEX ... ON usage_events (tenant_id, call_id, unit_type)
 WHERE call_id IS NOT NULL
   AND unit_type IN ('telephony_s','platform_min','stt_s','tts_chars','llm_tok_out')
   AND created_at >= '2026-08-15 10:14:00+00:00'
```

A dashboard-AI row is excluded **three** ways:

1. `WHERE call_id IS NOT NULL` — an explicit predicate. The row is **not in the index at
   all**, not merely unprotected by NULL semantics.
2. The `unit_type` list **omits `llm_tok_in` entirely.**
3. **`llm_tok_out` already means something else**: `pipeline.py:1201` writes it as
   `qty = 1` meaning *"one call's LLM leg"*, priced at the whole leg cost, because the
   engine bills legs with no token count (TRD §5). Metering real tokens into that column
   puts **two different units in one column**, and `billing/service.py:770` already assumes
   it is a cost input a client never sees.

Bonus: **`llm_tok_in` is a column with no writer anywhere in the tree.**

## What this part builds

- **`usage_events.ref`** (nullable) + **distinct dashboard-AI unit types** rather than
  overloading the call-leg ones + a **second partial unique index** on
  `(tenant_id, unit_type, ref)` where `ref IS NOT NULL AND call_id IS NULL`, so the two
  indexes cover **disjoint** row sets and neither shadows the other. `ref` is the request's
  idempotency key — these are console-button calls and a double-click is the realistic
  duplicate.
  ⚠ `usage_events` is append-only, so `ON CONFLICT DO UPDATE` fires
  `calevate_forbid_mutation`; `DO NOTHING` must repeat the partial predicate verbatim as an
  `index_predicate` or Postgres will not infer the index.
- **Quota: per tenant per month, with the ceiling per plan tier.** Counted in **rupees**,
  displayed as **both**. A rupee ceiling is what actually protects you — one 1M-token
  context costs what a hundred autofills do — and a request count is what a client can
  reason about, so the screen shows "82 of ~500 assists used" over a rupee ceiling doing
  the real work.
- **The modal (G-5).** At the ceiling the feature **blocks and asks**, naming what it will
  cost and what will be debited. Nothing leaves the wallet until the user accepts. The
  acceptance is itself auditable — it is a person agreeing to spend money.
- **Overage** is one `credit_ledger` row, reason `usage`, deduped by the existing
  `ux_credit_ledger_tenant_reason_ref`. **No new reason value, no new table.**
- **A platform-wide spend brake** on our own key, independent of any tenant's quota, since
  G-3 means an unbounded bug spends *our* money.

---

# PART 15 — Availability semantics (G-6)

One place decides what happens when Gemini is unavailable, over quota, or unconfigured —
not a policy re-implemented per feature.

- **Fall back to Sarvam where a fallback is honest**, and **say so in the response and on
  the screen**. A silent fallback quietly changes output quality with nobody told, which is
  the one outcome G-6 rules out.
- **Refuse with a message** where no fallback is honest, carrying `remediation` the user can
  act on — `ProblemNotice` already renders the server's own words.
- **A capability flag** so a surface that cannot work is visibly explained rather than
  silently missing — the shape `PaymentCapability` already uses, with its own reason
  (`no_credential`, `quota_exhausted`, `provider_unavailable`).
- Never a bare spinner and never an empty state: §52 governs this surface like every other.

---

# PART 16 — Score the extractors before changing the default (task #87)

Prepares the head-to-head that G-7's boundary should eventually rest on: both providers
against the golden-transcript fixtures through `scripts/eval.py`, scored per field, with
the result written as evidence under `docs/evidence/`.

**Blocked outside this repo** on egress and a Sarvam key, and named as such rather than
scheduled. What is *not* blocked, and belongs here, is the harness: a provider dimension in
the eval runner so the run is one command on the day the keys exist.

---

# PART 17 — BYOK external LLM for the in-call path

**The founder asked whether Gemini can serve the in-call LLM. Researched: yes in principle,
and it costs a new deployable.**

Both halves check out. Bolna supports a **custom LLM** and *"expects your custom LLM to be
an OpenAI compatible server"*, configured with an LLM URL and a name. Vertex publishes an
**OpenAI-compatible endpoint** at `…/locations/{location}/endpoints/openapi`, with function
calling supported. [REPORTED, NOT READ — `bolna.ai` is egress-blocked from this
environment]

**The catch is authentication.** Bolna's custom-LLM form takes a URL and a name; the
reachable documentation shows **no API-key field**. Vertex requires an **OAuth2 bearer that
expires hourly**, so even a static key field would not suffice. Something of ours must sit
between them, minting tokens and speaking OpenAI on one side, Vertex on the other.

That proxy would be **in the live call path** — the most expensive kind of component here.
D-25 requires in-call-path services to be India co-located; hard rule 3's latency
discipline applies; a new deployable needs its own decision-log entry (ROADMAP §6); and it
adds a hop to a budget where p95 is the product.

**Therefore: pilot-gated, not planned.** The Bolna Engine Verification Session (OPERATIONS
§2) answers the three questions nobody here can — whether the custom-LLM config accepts
auth, what the added latency is, and where Bolna's own servers run, which is a residency
question in its own right. Guessing any of them and shipping it as a guarantee is precisely
the D-31/D-32 mistake.

---

# PART 18 — Make the docs true, and close `llm_tok_in`

**24 `file:line` locations** state that Gemini is "a configurable fallback, not the
default": `CLAUDE.md:14`, `docs/AGENTS.md:11`, `README.md:97`, `TRD.md:100,544,618`,
`ROADMAP.md:363` (the D-36 row itself — **superseded, never edited in place**),
`BRD.md:238`, `SECURITY-COMPLIANCE.md:153`, `OPERATIONS.md`, `DEV-SETUP.md:9`, plus six
code comments. **None currently binds a named capability constant, so
`check_docs_drift` §5 would not catch them** — which is the argument for minting one, so
the next drift is machine-decidable instead of hand-checked.

Also: `TRD.md:544` describes `get_extractor()`'s *behaviour*, which is the line that goes
stale the instant precedence changes; and `ROADMAP.md:15` says "Gemini API key", which
becomes a GCP project and a service account.

And close **`llm_tok_in`**: a column in a CHECK constraint with no writer. Give it one or
remove it in the two steps hard rule 8 requires.

---

## Ordering

```
1  CORS ─────────────────▶ credentials can be installed at all
2  client IP + limiter identity
3  per-route limits ◀── needs 2
4  SSRF + egress audit
5  information surface
        │
        ├── 6  adversarial pass ◀── after 1-5, so it tests the intended posture
        │
        ├── 7  route shape + guardrail hygiene
        ├── 8  27 untested routes
        ├── 9  half-wired ops routes
        ├── 10 frontend refusal sweep + guard extension
        │
        └── 11 decision row ─▶ 12 residency guardrail ─▶ 13 Vertex client
                                                            │
                                              14 metering + quota + modal
                                                            │
                                              15 availability semantics
                                                            │
                                              16 eval harness (scoring blocked externally)
                                              17 BYOK in-call  [PILOT-GATED]
                                              18 doc sweep + llm_tok_in
```

**1 is genuinely first**: you cannot install the keys this plan prepares for.
**12 before 13** is not a preference: write the guard that makes a global endpoint
impossible before writing the client that could reach one.
**6 after 1–5**: an adversarial pass against a posture you are about to change measures the
wrong thing.

---

## Blocked outside this repo — named, not scheduled

- **Extraction scoring** (Part 16) — egress and a Sarvam key.
- **`create_agent` idempotency** — needs a Bolna account to establish whether their API
  honours an idempotency key.
- **BYOK in-call LLM** (Part 17) — the same pilot session.
- **Number provisioning and the test-call gate** — the DID vendor account and TM
  registration.
- **The TRAI recording-floor citation and the erasure notice's backup clause** — the
  founder with counsel. A sentence in a notice a client hands to a data principal is a
  commitment, not a code change.
- **Live Meta lead delivery** — `graph.facebook.com` is egress-blocked; owed the OPERATIONS
  §2b gate.
