# PLAN — Hardening every surface, and moving dashboard AI to Gemini

**Status: PROPOSED. Nothing in this document has been implemented.**
Written 15 Aug 2026, before the work, at the founder's instruction ("plan everything and
write into a doc first before starting to implement").

This plan covers everything that should land **before** external accounts are created and
real API keys are wired in — the Bolna account, the DLT registration, the DID vendor, the
Razorpay secret, the GCP project. The ordering principle is that **a credential should
arrive into a system that is already correct**, because a live credential turns every
remaining defect from an embarrassment into an incident with someone else's customer data
in it.

Two things this plan is NOT:

- It is not a backlog. Per CLAUDE.md there is no later: each slice below is either done in
  a session or it is the next thing done. Slices are ordered, not scheduled.
- It is not a rewrite. Every finding here is a specific defect at a specific `file:line`,
  found by reading the code, not a preference about how it might have been built.

---

## 0. How this plan was produced

Two exhaustive read-only audits, both mechanical rather than by eye:

- **Backend**: 176 routes enumerated three independent ways — the live FastAPI route table
  walked with `rbac.iter_api_routes`, the generated `openapi.json` (171 operations / 145
  paths), and `scripts/check_wiring.py`. All three agree: nothing undocumented, nothing
  stale, no unmounted router. 96 of the 176 are mutating.
- **Frontend**: 43 `page.tsx` + 3 layouts = 46 route files, plus every non-page component
  carrying its own query. 77 query hooks enumerated from `src/lib/api/*.ts` and every call
  site checked for an unread `isError`.

Every finding below carries an evidence level. **READ AT SOURCE** means someone read the
line. **INFERRED** means it follows from lines that were read. Nothing here is recalled
from memory — that distinction exists because this repo has shipped a defect that came
from treating an inference as a fact (D-31/D-32).

---

## 1. Decisions this plan assumes

Taken by the founder on 15 Aug 2026, in answer to direct questions. Each becomes a
decision-log row when the work starts; they are recorded here so the plan can cite them.

| # | Decision | Consequence |
|---|---|---|
| **G-1** | Gemini is reached through **Vertex AI, `asia-south1` (Mumbai)** — never the AI Studio Developer API | Preserves the all-India residency posture D-36 chose. Costs an OAuth2 service account instead of an API key. |
| **G-2** | Dashboard AI may see **tenant-authored config plus REDACTED call data**. Never raw PII. | Excludes exactly one existing path — see §2. |
| **G-3** | **One Calevate-owned key, cost absorbed.** Usage is metered per tenant; a tenant is charged only past an included quota. | Needs per-tenant metering with a real idempotency key, a quota, and a spend brake. No new billing system. |
| **G-4** | Clients are **not billed per request**. Overage becomes one `credit_ledger` row, reason `usage`. | The existing credit system carries it. No new ledger, no new reason value. |

### The contradiction in G-2, and how this plan resolves it

The instruction was "Gemini for all AI work outside the live call". Post-call **extraction**
is outside the live call — and it is the one place raw PII must flow.

`apps/workers/pipeline.py:750` builds the transcript it hands to the extractor from
`turn.text`, **not** `redacted.text`, one line after computing both. That is deliberate and
correct: a CRM field like "callback number" needs the actual digits, and an extractor
reading `[REDACTED]` would return nothing useful.

So G-2 ("never raw PII") and "all AI outside the call" cannot both hold for extraction.
**This plan resolves it in favour of G-2**: dashboard AI moves to Gemini; **post-call
extraction stays on Sarvam**. The decision row must say this in words, because the
instruction naturally reads the other way and the next person to touch
`get_extractor()` will read it that way.

There is a second, independent reason to leave extraction alone: **its quality has never
been scored against any model** (task #87, blocked on egress and a Sarvam key). Flipping an
unmeasured default to another unmeasured default is not an improvement, it is a change of
unknowns.

---

## 2. What Gemini already is in this tree

READ AT SOURCE, all of it. This is a promotion of something that exists, not a greenfield
integration — and what exists is pointed at the wrong door.

- `apps/workers/extraction.py:55` —
  `GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"`.
  That is the **AI Studio Developer API**, a global endpoint with no region in the host.
- `:137` — authenticates with `params={"key": self._api_key}`. **Vertex does not accept an
  API key in the query string.**
- `:124-152` — `GeminiExtractor`, ~28 lines of raw `httpx`. There is **no Google SDK
  anywhere in this repo**.
- `:129` — default model `gemini-2.5-flash-lite`, which **retires 16 Oct 2026** (BRD R-04),
  two months out.
- `:564-572` — `get_extractor()`: Sarvam wins; Gemini only when Sarvam's key is absent.
  Its docstring: *"there is no silent failover between providers, because they differ on
  data residency (D-36) and that is not a runtime decision."*
- `apps/api/core/platform_config.py:364` — `gemini_api_key` is console-settable, `LIVE`.

**Moving to Vertex is a client rewrite, not a host swap**: new host and path
(`https://asia-south1-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/asia-south1/publishers/google/models/{model}:generateContent`),
OAuth2 bearer instead of a key, a service-account credential in the secrets manager, a new
`gcp_project_id` setting, and `google-auth` as a new dependency — which under hard rule 9
means the lockfile diff gets read before it is committed. The **response shape is
identical**, so the parsing at `:148-152` survives unchanged.

### External research behind G-1

- The **AI Studio / Gemini Developer API offers no data-residency guarantee** — requests go
  to a global endpoint. On the **free tier Google uses prompts, uploads and responses to
  improve its products, and human reviewers may read them.** Unusable for this product at
  any tier, and disqualifying on the free tier.
- **Vertex AI `asia-south1`** performs ML processing in-region, keeps data at rest
  in-region, and does not train on paid usage. Gemini 3.x Flash, Flash-Lite and Pro are all
  available there.
- **Pricing has a known cliff.** Gemini 3.7 Flash launched 13 Aug 2026 at **$0.75 / $3.75
  per 1M tokens introductory**, reverting to **$1.50 / $7.50 on 1 Jan 2027**. Batch is 50%
  off; cached input ~$0.15/1M. Any margin model built on today's number must carry that
  date, or it will be wrong in four months.

Sources: Google Cloud data-residency and Vertex generative-AI location docs; Google AI
Studio pricing and terms; vendor pricing trackers (Aug 2026). Cited again in the code
comments when the work lands, so the next reader inherits the evidence and not the
conclusion.

---

## 3. PART A — Hardening

Ordered by severity. Every item is a defect that exists today at the line cited.

### A-tier: land before any credential goes live

| Slice | Defect | Evidence |
|---|---|---|
| **S-1 — SSRF guard on outbound egress** | `integrations/routes.py:280` validates a tenant-supplied webhook URL as `HttpUrl` and nothing more. Any tenant `owner` can register `http://169.254.169.254/…` or an RFC1918 address, and `integrations/service.py:534` POSTs **signed lead payloads containing a name and a phone number** to it. Redirects are blocked and bodies are not stored, so it is a *blind* SSRF — but status codes and error types are readable back through `GET /v1/integrations/deliveries`, which makes it an internal port scanner and a PII egress channel into the private network. Grep for `is_private` / `link_local` / `169.254` across the integrations and workers trees returns nothing. | READ AT SOURCE |
| **S-2 — CORS blocks `PUT` and `If-Match`** | `core/middleware.py:301` lists `GET, POST, PATCH, DELETE, OPTIONS` — **no `PUT`** — and `allow_headers` omits `If-Match`. The web app is cross-origin in every environment (`client.ts:19` + a direct `fetch` at `:315`; there is no Next rewrite proxy). So **five routes are unreachable from a browser today**: the client's own spend cap (`PUT /v1/billing/caps`), feature flags, `PUT /v1/ops/config/{key}`, `PUT /v1/ops/secrets/{key}` — *the vendor-credential install path* — and `DELETE /v1/ops/config/{key}`, which sends `If-Match`. Nothing goes red because the web tests mock `fetch` and CORS is browser-side only. **This one blocks credential installation, so it is first.** | READ AT SOURCE, incl. Starlette 1.3.1's preflight code |
| **S-3 — one client-IP resolver** | `core/auth.py:783` reads the socket peer, so **every audit row's `ip` is the nginx/Docker-bridge address**, not the caller's — SEC-COMP §5's "actor, tenant, at, ip" is satisfied in shape only. Worse: `tenancy/signup.py:186` spends `SIGNUPS_PER_IP_PER_HOUR = 30` against that one shared value and **fails closed**, so 30 signups an hour caps the entire platform and one abuser denies self-serve signup to everyone. The fix already exists — `voice-runtime/engine_intake.py::client_ip` counts exactly one trusted hop and fails closed — and nginx now *sets* `CF-Connecting-IP`, so the `_request_ip` docstring saying otherwise is stale. | READ AT SOURCE (4 files + the proxy conf) |
| **S-5 — close the unauthenticated information surface** | `/healthz/ready` is unauthenticated, rate-limit-exempt and publicly proxied, and it **names the configuration keys this deployment is missing** (`core/health.py:128`), plus queue depth and oldest-job age. That is an oracle telling the internet which credentials are not installed yet — most dangerous during exactly the window this plan exists to prepare for. Separately, `/docs`, `/redoc` and `/openapi.json` are served **unauthenticated in prod** (`bootstrap.py:182`); the repo already half-knows, because `integrations/routes.py:314` moved a docstring into a `description` specifically because "`/docs` is in PUBLIC_PREFIXES". | READ AT SOURCE |
| **S-4 — rate-limiter identity** | `core/middleware.py:258` keys the per-identity bucket on `hash(auth)`. Python salts `str.__hash__` per process; prod runs `--workers=2`. One token therefore occupies N buckets — the effective limit is N× what the docstring claims and changes on every restart — and the 32-bit truncation lets one tenant consume another's bucket. `blake2s` fixes it in one line. Related: all five `/hooks` routes share one bucket, so a lead-intake flood 429s the **payment** and **identity-mirror** webhooks. | READ AT SOURCE; the N× multiplier is INFERRED from worker count |

### B-tier: correctness and compliance

| Slice | Defect |
|---|---|
| **S-6 — audit the egress-endpoint lifecycle** | Creating a webhook or Sheets destination writes **no** `audit_log` row; deleting one does (`integrations/routes.py:280`/`:314` vs `:467`). Registration is the act that starts lead PII leaving the tenant, and it is the act with no record of who did it. Of 96 mutating routes, these two are the only real audit gaps — every other unaudited handler either audits in its service, writes a lead-timeline row instead, or is a read. |
| **S-7 — one shape for an admin-realm tenant mutation** | `PATCH /v1/agents/{agent_id}/voice` (`voice_routes.py:244`) is admin-realm but lives in the *client* path space and takes its tenant **in the body**, while the house pattern — pinned by `tests/route_shape_test.py:368` — is `/v1/admin/tenants/{tenant_id}/…`. It is the only admin-realm route outside the admin path space. Two ways to do one thing is a defect even when both work, and this is the one the next author copies. |
| **S-8 — guardrail hygiene** | The D-22 mutating sweep's exemption set (`tests/authz_audit_test.py:353`) has **no staleness guard**: rename a route and its entry silently becomes a permanent hole for whatever lands on that path. Its sibling allowlist got exactly this assertion (`impersonation_reads_test.py:88`) — the lesson was learned in one file and not the other. Also `loadshed.py:38` exempts `/v1/auth` so sign-in survives maintenance mode, but **the only route under `/v1/auth` is `signup`**, a heavy multi-table write — so emergency mode still admits new tenants. |
| **A1 — the erasure form offers itself over a failed read** | `admin/tenants/[tenantId]/lifecycle/page.tsx:244` reads `useTenantErasures` and **never reads its `isLoading` or `error`**. `existing = filed.data?.[0]`; when that is undefined the screen renders the "Erase this client's data" form. So while the read is in flight, and after it 503s, the screen states no erasure has been filed and offers an irreversible DPDP tenant-wide erasure **that may already be running**. §52's worst instance, on the most destructive path in the product. |
| **A2–A5 — four more §52 violations** | A failed `/v1/agents` read makes the lead-source form persist a source that never dials (`lead-sources/page.tsx:592`); makes the "Call this lead" control silently vanish (`leads/page.tsx:235`); the follow-up card *hides itself* on a failed eligibility read, which is the exact silent-nothing the card was built to prevent (`calls/[callId]/page.tsx:85`); and "Spend this month" renders `—` forever with no explanation on a failed usage read (`c/[slug]/page.tsx:53`). |
| **A6 — extend the §52 guard to the shapes these escaped through** | `tests/surfaceStatesGuard.test.ts` is good and its stated blind spots are exactly where A1–A5 live: `?? []` outside a JSX child, `?.[0]`, `{q.data && …}`, and ternaries. Closing the class matters more than closing the five instances. |

### C-tier: finish the seams

| Slice | Defect |
|---|---|
| **S-9 — HTTP-level tests for 27 routes** | 27 routes have no test at the HTTP layer; several are tested only at the service layer, so the route wrapper — permission dependency, error mapping, audit write, response model — is never exercised. Includes the KB approve/reject/publish trio, DLT template and number status, prompt rollback, saved-view edit/delete, the Sheets endpoint, and the top-up capability read. |
| **S-10 — six half-wired ops routes** | The global-DNC surface (4 routes) and WhatsApp alert opt-in (3 routes) exist in code and in the generated types and are called by **no client and no screen** — reachable only by curl. Either build the two small admin panels or record in the decision log that they are deliberately curl-only ops procedures, and name the runbook. Silence is the one option the "leave no half-wired feature" rule forbids. |
| **A7 — `BLOCKER_COPY` is a second copy of a rule** | `campaigns/page.tsx:149` restates the server's compliance blockers in the frontend's own words and prefers its copy over the server's `reason`. It fails open for unknown rules, which is right, but nothing diffs the key set against `compliance/`, so a reworded server rule loses silently to a stale client string. |

### What the audits found CLEAN

Recorded so the plan says what does *not* need work — a silent omission reads as "not
looked at".

- **The D-119 permission-typo class is closed.** `core/rbac.py:286` fails the process at
  boot if any declared permission is unknown or granted to no role, checked against the
  live route table with a floor assertion so a broken walker cannot make it decorative. All
  176 routes pass.
- **D-22 read-only impersonation holds across all 96 mutating routes**, with 5 exemptions,
  each read and each genuinely non-mutating. The inverse sweep (no GET gated on a mutating
  permission) also holds.
- **Money.** `Decimal` throughout, `refuse_json_float` on every money-bearing request model,
  amounts as digit strings at the boundary, replay responses re-serialised so a replay
  cannot be where a `Decimal` becomes a float. **No float in any money path.**
- **Concurrency.** One CAS primitive (`db/transition.py`), idempotency claims on lead
  dispatch / callback / top-up, credit writes locking before the lookup, `If-Match`
  revision CAS on ops config. **No D-121-shaped read-then-write found on any route.**
- **Tenancy/RLS.** One tenant-scoped path; every untenanted session outside it enumerated
  and justified in place. (`check_rls_coverage` reports one drift for
  `tenant_erasure_requests` — that is a stale local database, not a defect; the migration
  carries `ENABLE`/`FORCE` + `tenant_isolation`.)
- **voice-runtime discipline**, **step-up coverage**, **error shape**, **the a11y sweep**
  (45/46 screens, one waived with a named closer, zero accepted violations), **fail-closed
  frontend defaults**, and **the optional-on-the-wire discipline** (122 optional properties
  checked; every UI access guarded) all came back clean.

---

## 4. PART B — Gemini

### B1 — the decision row, first

Nothing else may cite a decision that does not exist. One row superseding **D-36's LLM
leg**, stating: Vertex `asia-south1` only; dashboard AI on Gemini; **extraction stays
Sarvam because it sees raw PII**; one Calevate key, absorbed, metered, billed only past a
quota. Plus the SEC-COMP §4 cross-border row rewritten — it currently reasons *"Sarvam is
sovereign, so no transcript text leaves India"*, and the new reasoning is *"the endpoint is
regional"*. Google Cloud becomes a named sub-processor in the client DPA.

### B2 — the residency guardrail, before any Vertex code

An executable check in `make guardrails`, in this repo's style — not a comment. It should
assert:

1. **No global Google model host appears in any URL literal** anywhere under `apps/`,
   `packages/`, `scripts/` — specifically `generativelanguage.googleapis.com` (which is
   `extraction.py:55` today) and bare `aiplatform.googleapis.com` with no region prefix.
2. Every `*-aiplatform.googleapis.com` literal has region **`asia-south1`**.
3. **The region is a `Final` constant and is NOT reachable from console-editable config.**
   A region an operator can change from a web form at 3am is a residency posture that can
   be inverted by a click — the same doctrine `check_bootstrap_keys` already applies to
   `APP_ENV`.
4. The `locations/{…}` path segment interpolates only that frozen constant.
5. Negative controls: a doctored tree containing a `us-central1` URL must fail the check.

This is decidable from syntax, needs no network, and makes the wrong endpoint *impossible*
rather than discouraged.

### B3 — the Vertex client

OAuth2 service-account auth, project + location in the path, `google-auth` added with its
lockfile diff read (hard rule 9). Land on **3.x Flash-Lite**, not 2.5 — 2.5 retires 16 Oct
2026 — and re-run `scripts/eval.py` against the golden fixtures so the model change is
measured rather than assumed.

### B4 — metering that cannot double-charge

The concern raised before the audit was **confirmed, and the mechanism is worse than
stated**. `ux_usage_events_tenant_call_unit` (migration `b8d3f47c2a19:185`) is:

```sql
CREATE UNIQUE INDEX ... ON usage_events (tenant_id, call_id, unit_type)
 WHERE call_id IS NOT NULL
   AND unit_type IN ('telephony_s','platform_min','stt_s','tts_chars','llm_tok_out')
   AND created_at >= '2026-08-15 10:14:00+00:00'
```

A dashboard-AI row is excluded **three** ways, not one:

1. `WHERE call_id IS NOT NULL` — an explicit predicate. The row is not merely unprotected
   by NULL semantics; it is **not in the index at all**.
2. `unit_type IN (…)` omits **`llm_tok_in` entirely**.
3. **`llm_tok_out` already means something else.** `pipeline.py:1201` writes it as
   `qty = 1` meaning *"one call's LLM leg"*, priced at the whole leg cost, because the
   engine bills legs with no token count (TRD §5). Metering real tokens into that column
   would put **two different units in one column**, and `billing/service.py:770` already
   assumes it is a cost input a client never sees.

Bonus finding: **`llm_tok_in` is a column with no writer anywhere in the tree.**

So B4 is: add a nullable `ref` to `usage_events`; add **distinct** unit types for
dashboard AI rather than overloading the call-leg ones; add a second partial unique index
on `(tenant_id, unit_type, ref)` where `ref IS NOT NULL AND call_id IS NULL`, so the two
indexes cover **disjoint** row sets and neither can shadow the other; extend the CHECK.
`credit_ledger` needs **no** new reason — overage is `usage` with a `ref`, which
`ux_credit_ledger_tenant_reason_ref` already dedupes.

⚠ `usage_events` is in `APPEND_ONLY_TABLES`, so `ON CONFLICT DO UPDATE` is unavailable —
it fires `calevate_forbid_mutation`. `DO NOTHING` must repeat the partial predicate
verbatim as an `index_predicate` or Postgres will not infer the index.

### B5 — the first dashboard-AI surface: intake autofill

Business description → the FLOWS §1 step-3 answer sheet. Chosen first because it is
**tenant config only, zero call data**, so it exercises the whole path — Vertex client,
metering, quota, refusal — with no PII question at all. The intake draft is already
resumable and `IntakeFacts` is already all-optional, so the shape fits.

### B6 — the doc sweep

**24 `file:line` locations** state that Gemini is "a configurable fallback, not the
default", across `CLAUDE.md:14`, `docs/AGENTS.md:11`, `README.md:97`, `TRD.md:100,544,618`,
`ROADMAP.md:363` (the D-36 row itself — **superseded, never edited in place**),
`BRD.md:238`, `SECURITY-COMPLIANCE.md:153`, `OPERATIONS.md`, `DEV-SETUP.md:9`, plus six
code comments. None currently binds a *named* capability constant, so
`check_docs_drift` §5 would **not** catch them — which is the argument for minting one, so
the next drift is machine-decidable instead of hand-checked.

### B7 — retire or wire `llm_tok_in`

A column in a CHECK constraint with no writer. Either give it one or take it out in the
two steps hard rule 8 requires.

---

## 5. Ordering

```
S-2 (CORS)  ──▶ credentials can be installed from the console at all
S-1, S-3, S-4, S-5   ──▶ the A-tier security set; land before any live key
       │
       ├──▶ B1 (decision row) ──▶ B2 (residency guardrail) ──▶ B3 (Vertex client)
       │                                                          │
       │                                              B4 (metering) ──▶ B5 (autofill)
       │
       └──▶ S-6…S-8, A1…A7   (correctness + compliance, parallelisable)
                    │
                    └──▶ S-9, S-10, B6, B7   (seams and docs)
```

**S-2 is genuinely first.** `PUT /v1/ops/secrets/{key}` is how a vendor credential gets
installed, and today a browser cannot call it.

**B2 before B3** is not a preference. Write the guardrail that makes a global endpoint
impossible *before* writing the client that could use one.

---

## 6. Not in this plan, and why

Blocked on something outside this repo. Named, per CLAUDE.md, rather than scheduled:

- **Extraction quality scored against a real model** (task #87) — needs egress and a Sarvam
  key.
- **`create_agent` idempotency on a lost response** — needs a Bolna account to establish
  whether their API honours an idempotency key. Guessing a header and shipping it as a
  guarantee is the D-31/D-32 mistake.
- **Number provisioning and the test-call gate** — need the DID vendor account and the TM
  registration.
- **The TRAI recording-floor citation and the erasure notice's backup clause** — need the
  founder with counsel. A sentence in a notice a client hands to a data principal is a
  commitment, not a code change.
- **Live Meta lead delivery** — `graph.facebook.com` is egress-blocked here; owed the
  OPERATIONS §2b pilot gate.

---

## 7. Open questions

Answers change what gets built; each currently carries the recommendation in brackets as
a working assumption.

1. **Gemini unavailable or over quota** — feature disappears, refuses with a message, or
   falls back to Sarvam? [*Refuse with a message. A silent fallback changes output quality
   with nobody told.*]
2. **Included quota** — per tenant per month or per plan tier, counted in requests or
   rupees? [*Rupees. One 1M-token context costs what a hundred autofills do, so a request
   count does not protect you.*]
3. **Autofill trust level** — does a human approve every field, or does it save as an
   editable draft? [*Draft, never touching the publish path. D-118 is what happens when
   something reaches a clinic's phone line unreviewed.*]
4. **Scope of "harden every route"** — does it include a load/abuse posture (per-tenant and
   per-IP limits, request size caps), or correctness and authz only? [*Include it. S-3/S-4
   are already in that territory and the public signup endpoint feels it first.*]
5. **Adversarial pass** — is a pen-test-style sweep in scope beyond the audit above?
