# Production readiness — the gap register

**What this is.** One prioritised place to see everything standing between this repository
and a live client on a VPS. It is a NAVIGATION document: nothing here is a new decision,
and every row points at the file, gate or decision entry that owns the detail.

**Why it exists.** The gaps were already documented — in OPERATIONS §2's gate table, in
ROADMAP §6's decision log, in the "not done, and named" clauses several decisions end
with, and in `infra/README.md` §5. That is four places, ordered by when each was written
rather than by what has to happen first, and none of them answers the only question that
matters before a deploy: *what is actually stopping us, and which of it is ours?*

**The one distinction that governs everything below** (CLAUDE.md, "Tempo"): a gap is
either OURS — an engineering task with no timeline, done now or next — or it is EXTERNAL,
waiting on a legal entity, a vendor account, a registration or a signed term, and no
amount of coding closes it. Mixing the two is how a blocker acquires a fake schedule.
Sections A and B are that split, and they are the whole point of the document.

---

## Reading the status column

| Mark | Meaning |
|---|---|
| **BLOCKED** | Waiting on something outside this repository. Named, with what closes it. |
| **OURS** | Engineering work. Nothing external is required. |
| **UNVERIFIED** | Shipped code resting on a vendor claim nobody has tested against a live account. The code works; the premise is unconfirmed. |
| **NEVER RUN** | Written, reviewed, committed — and never once executed. |

---

## A. External blockers — nobody can code around these

### A1. The voice engine account (blocks the most)

**One missing thing — a Bolna account with credit — blocks twelve of the fourteen
operational gates.** OPERATIONS §2 holds the full pass criteria; this is the dependency
view.

| Gate | Question it settles | Consequence of it staying open |
|---|---|---|
| 1 H | Webhook trust: source allowlist, dedupe, whether a signature header exists | TRD §5's "unsigned engine" premise is unconfirmed. The receiver's IP-allowlist + execution-id design is built for it. |
| 2 H | API-only provisioning, and `delete_agent`'s repeat-delete status | `agents/service.py::_reclaim_orphan` assumes a repeat delete answers 404. If it is 400, a compensation DLQs. |
| 3 H | Telugu STT/TTS quality on our keys; is Bulbul **v3** selectable | The whole Telugu-first positioning is unmeasured. |
| 4 H | Real-call latency p50/p95, and whether `latency_data` agrees with a stopwatch | `calls.latency` was dropped rather than filled with numbers that are not the caller's experience; this gate chooses the storage shape. |
| 5 H | Telugu turn-taking, barge-in, endpointing | An orchestration property BYOK models do not fix. |
| 6 H | Webhook loss + **listing pagination** | `bolna._LISTING_PAGE_SIZES` currently GUESSES the page size from round numbers. |
| 7 S | Post-call fidelity: cost breakdown, currency, time-to-`completed` | Metering and the 2-minute lead SLO both rest on it. |
| 8 S | KB retrieval in Telugu, tool-call p95, **and `kb_list_carries_agent_linkage`** | This is the honest limit of the D-158 KB drift sweep: if the listing carries no agent linkage, the sweep is blind in both directions and reports `unreadable`. |
| 10 H | Is one account for many end-clients permitted | Our entire tenancy model sits on this. |
| 11 H | Are the humans responsive | Named as "the gate ThinnestAI failed". |
| 12 H | Commercials in writing — above all the BYOK platform fee | Observed at ~₹1.76/min in the dashboard vs a ≤₹1.50 target; worth ₹5,200/month at 20k platform-min. A dashboard figure is not a commercial term. |
| 13 S | Concurrency ceiling across engine, Sarvam and the SIP trunk | Effective ceiling is the MIN of three, and none is confirmed. |

**Also needed and separately external:** Sarvam BYOK keys (gate 3), and an Exotel/Vobiz
SIP trunk (gate 13).

### A2. Dated and unavoidable — the Gemini retirement

| Item | Status | Detail |
|---|---|---|
| Gate 14 — does `asia-south1` serve our Gemini model | **BLOCKED** on a GCP project + service-account key | `GEMINI_MODEL_CONFIRMED_IN_REGION is False`. The test is ONE call. Search now points the right way (2.5 class is in Mumbai's ML-processing table; 3.x is not) but a summary of a page nobody could open is not a 200. |
| Gate 14b — **replace `gemini-2.5-flash` before 16 Oct 2026** | **BLOCKED**, same key, and it comes due either way | **CI goes red on 16 Sep 2026** via `test_the_shipped_gemini_model_has_runway_left`. If nobody acts, assists 404 and fall back to Sarvam with the G-6 disclosure — degraded and disclosed, not an outage. |

**Wrong answers, all three blocked in code**: widening the region, using `locations/global`,
or widening `RETIREMENT_RUNWAY_DAYS` to quiet the test. `scripts/check_model_residency.py`
fails the build on the first two.

### A3. Compliance and commercial registrations

| Item | Status | What closes it |
|---|---|---|
| DLT / PE-TM registration | **BLOCKED** | Registration as Telemarketer with clients as Principal Entities. Nothing outbound is lawful without it. |
| Razorpay API secret | **BLOCKED** | No deployment has one, so `PaymentCapability.creates_orders` answers False with reason `no_api_secret`. **The code is built (D-98); a client still cannot pay.** |
| WhatsApp BSP decision + WABA | **BLOCKED** | `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA = False` in `apps/workers/whatsapp_cloud.py`. No WABA, no phone number id. |
| Archive `retention_policies` category | **BLOCKED** | A DPA commitment plus a documented enum change (SECURITY-COMPLIANCE §4). |
| Extraction quality scoring (task #87) | **BLOCKED** | Needs a real model against real transcripts. Until then D-36 records Telugu extraction quality as UNMEASURED — which is why the homepage captions its demo as an illustration and why `moments.py` ships exactly ONE model kind rather than a taxonomy. |

---

## B. Ours — engineering, nothing external required

### B1. Named as not-done inside shipped decisions

| Item | Where | Note |
|---|---|---|
| Phone-number provisioning | `campaigns/provisioning.py`, `PROVISIONING_IMPLEMENTED = False` | The route exists and its own summary says "not implemented yet". Honest, and still a hole in the onboarding path. |
| TTS rung attribution unverified | `billing/rates.py`, `ENGINE_TTS_MODEL_GENERATION_VERIFIED = False` | The margin panel splits cost by rung; the mapping from engine model name to rung is not confirmed. Money (hard rule 7). |
| HMAC path in the receiver | `voice-runtime/engine_intake.py` — `reason="signature verification not implemented"` | Only reachable for an engine that SIGNS. Bolna does not (gate 1), so this is unreached today and would be needed the moment a signing engine is added. |

### B2. Structural, worth doing before scale rather than after

| Item | Status | Why it matters |
|---|---|---|
| `apps/api/core/transport.py` move | **OURS** | The SMTP transport lives under `apps.workers`, which voice-runtime is forbidden to import — so the alert delivery thread holds a recorded, measured exception (`RUNTIME_IMPORTS_ON_THE_ALERT_THREAD`). Moving it to `apps/api/core/` closes the hole and deletes the exception. |
| Per-call latency storage | **OURS**, but *sequenced after gate 4* | `calls.latency` was dropped deliberately. The shape gets chosen from the payload gate 4 actually captures — building it first would be guessing. |

---

## C. Never run — written, reviewed, never once executed

This is the category that most resembles progress and is not.

| Item | Status | What it needs |
|---|---|---|
| `infra/terraform/` | **NEVER RUN** | `terraform init` and `terraform validate` have never executed — `registry.terraform.io` was blocked by egress, so **no resource attribute has ever been checked against a real provider schema**. `terraform fmt -check` passes, which proves HCL syntax and nothing more. Its ONLY resource is the S3 lifecycle configuration. |
| The object-lifecycle policy | **NEVER RUN** | `runbooks/object-lifecycle.md`, starting with the SQL that produces `--max-tenant-ttl-days`. Must not be guessed. |
| Object store selection | **UNDECIDED** | Production is Cloudflare R2 (DEPLOYMENT §1, TRD §2); DEV-SETUP §3 also names DO Spaces. R2, DO Spaces and MinIO each implement a different subset of S3 lifecycle grammar. Pin it before applying anything. |
| The deploy itself | **NEVER RUN** | `scripts/vps-deploy.sh` and `compose.prod.yml` exist and are complete. No host has ever run them. |

---

## D. Unverified vendor premises baked into shipped code

These are not defects. They are marked assumptions (D-31/D-32's doctrine: a vendor
behaviour is a gate or a marked assumption, never a silent premise). Listing them together
because a reader should know how much of the adapter rests on a claim.

**Bolna publishes no OpenAPI spec, so every payload shape in the adapter is a
hand-maintained claim.** Specifically:

- **Listing page size** — `bolna._LISTING_PAGE_SIZES` guesses from round numbers (gate 6b).
- **Pagination shape** — the adapter follows only a continuation the payload hands it, and
  never a guessed `?page=`. Where it cannot rule out a further page it returns
  `complete=False` and the poller alerts. (gate 6c)
- **Repeat `delete_agent`** — assumed 404, folded into idempotent success. (gate 2)
- **`list_kb` agent linkage** — assumed present. If absent, the D-158 sweep reports
  `unreadable` rather than a fleet-wide false alarm. (gate 8a)
- **`DELETE /knowledgebase/{rag_id}`** — whether it also clears the agent's reference, or
  leaves a dangling `rag_id`. (gate 8b)
- **Cartesia `DELETE /agents/{id}`** — INFERRED; Cartesia publishes no agent-delete
  reference at all.

---

## E. Suggested order before the VPS deploy

Sequenced by dependency, not by size. Each step is either unblocked today or names the
one thing it waits on.

**Step 1 — things that need nobody (do now).**
`apps/api/core/transport.py` move. `terraform init && terraform validate` if egress now
permits it; if it does not, that becomes an external blocker and should be recorded as one.

**Step 2 — the two accounts, in this order.**
A **GCP project + service-account key** is the cheapest unblock in the whole document: it
is one key, it closes gate 14, and it starts the clock on 14b, which turns CI red on
**16 Sep 2026** whether or not anyone acts. A **Bolna account** unblocks twelve gates and
is the gate to everything voice.

**Step 3 — run the pilot.**
`make pilot` runs gates 1, 2 and 6 today. Gates 3, 4, 5 need real PSTN calls in Telugu.
Gate 12 is a negotiation, not a test, and should open on the ₹1.50 number with the
₹5,200/month and ₹15,600/month figures in hand.

**Step 4 — the legal path, in parallel and on someone else's clock.**
DLT/PE-TM registration. Nothing outbound is lawful before it, and it is the item most
likely to be the true critical path — so it should start before anything technical needs
it.

**Step 5 — infrastructure, once the store is pinned.**
Object store decision → lifecycle runbook → terraform validate → apply → first deploy.

**Step 6 — what only a live client produces.**
Gate 4's latency capture chooses the per-call latency storage shape. Task #87's extraction
scoring needs real transcripts. Both are correctly sequenced last, and neither should be
guessed at earlier.

---

## What is NOT on this list, and why

The product surfaces are built. Onboarding, agents, campaigns with the compliance gate,
CRM and extraction, knowledge base with approval and drift reconciliation, recordings with
key moments, billing and invoicing, DPDP erasure with certificates, the ops console, the
admin console and the marketing site are shipped and tested — 4,533 backend tests and 981
web tests, thirteen executable guardrails, and a coverage ratchet at its floor on seven
hard-rule surfaces.

The gap between that and a live client is almost entirely **accounts, registrations and
one never-executed deploy** — not code. That is a good position to be in, and it is worth
stating plainly so the remaining work is not mistaken for a larger engineering effort than
it is.

---
---

# The final audit — findings as numbered parts

Seven parallel read-only audits were run across the whole repository before the deploy,
one per subsystem. What follows is their output organised as **PARTS**: each part is a
self-contained unit of work with its own findings, fixes and dependencies, so they can be
worked through one at a time.

**Status of this section:** 2 of 7 audits reported (money/billing, voice/engine). Parts
are appended as each audit lands, so a part number is stable once written.

**Severity, as the audits used it.** BLOCKER = must fix before a paying client. SERIOUS =
fix before scale. MINOR = worth doing.

**Two findings were reached independently by two different audits** (P1.2 and P2.5 are the
same defect seen from the billing side and the engine side). That agreement is the
strongest evidence in this document and the reason P1.2 is ranked first.

---

## PART 1 — Money that is wrong the day a client pays

**Why first:** every item here loses real rupees on day one, none is hard to fix, and none
of it appeared in the register above — whose closing section listed "billing and invoicing"
among what is shipped and tested. A deploy planned off that sentence would have shipped all
three.

### P1.1 — Self-serve calls are billed at OUR supplier cost, so margin is zero by construction · BLOCKER · OURS

`apps/workers/pipeline.py:1509` calls `charge_for_call(..., amount_inr=cost.total_inr)`,
and `cost.total_inr` is what the engine charges **us** (`bolna.py:1043`, converted from USD
cents). Meanwhile `self_serve_inr_per_min` (₹6.00, `config.py:562`) is read in exactly ONE
place — `billing/service.py:1092` — and only to render the "about N minutes left" runway
string.

So the wallet is debited at roughly ₹2/min while the screen prices the same minute at
₹6/min. The balance drains at a third of the advertised rate and Calevate books **₹0 gross
margin on the entire self-serve motion**. `config.py:551` explicitly promises that the
runway framing *and the top-up flow* price from the same source; the debit path never reads
it.

**FIX:** `charge_for_call` must take a BILLED amount, not `cost.total_inr` — derive it the
way `usage_summary` already does (`self_serve_inr_per_min × minutes` for prepaid tiers) and
keep `cost.total_inr` on `unit_cost_paid` and the margin query. The two numbers must stop
being one number.

### P1.2 — A completed call with an unreadable cost is silently free, and the poller calls it settled · BLOCKER · OURS (detector) / EXTERNAL premise (gate 7)

**Found independently by both the billing and the engine audits**, which is why it leads.

`bolna.py:1022` returns `None` when `total_cost` is absent — silently, no log. `pipeline.py:1411`
then does `if cost is None: return 0`: no usage row, no `charge_for_call`, no `spend_state`
increment. And `pipeline.py:1671` only expects a usage artifact `if snapshot.cost is not
None`, so the reconciliation poller — D-31's *guarantee of record* — classifies the call
**`settled`** and never repairs it.

The blast radius is the entire billing surface, because every client-facing figure derives
from `usage_events` and not from `calls` (`service.py:992` counts
`COUNT(DISTINCT call_id) FROM usage_events`). `total_cost` and `cost_breakdown.*` are
**hand-maintained claims from a vendor with no OpenAPI spec** (gate 7). If the live account
spells that key differently: every usage panel reads 0 calls / 0 minutes / ₹0.00, every
invoice renders empty, no spend cap ever arms, no wallet is ever debited — **and nothing
anywhere goes red.**

Refusing to fabricate a cost is right. Refusing to COUNT the refusals is not.

**FIX:** (a) in `_meter`, when `snapshot.billable_ready and snapshot.cost is None`, `alert()`
rather than `return 0`; (b) add a "completed calls with no usage row" counter to the admin
health surface — `_pipeline_settled` already has the query shape at `pipeline.py:1739`;
(c) add a conformance clause so an adapter claiming `billable_ready=True` must carry a cost
or explicitly declare it cannot.

### P1.3 — The client's spend cap is denominated in our supplier cost, and that cost is printed on their screen · SERIOUS · OURS

`pipeline.py:1540` accumulates `spend_state.spend_used` from `cost.total_inr`;
`billing/caps.py:191` compares the client's `cap_spend` against that column; and
`cap_routes.py:124,144` lets the client set the cap and shows them the used figure, rendered
at `usage/page.tsx:336`.

Two defects in one column. A client who caps at ₹5,000 is stopped at ₹5,000 of **Calevate's**
cost — roughly ₹20,000 of their own bill. And `service.py:728` states the rule in as many
words — *"The client panel never shows `unit_cost_paid`. Our supplier pricing is
commercially ours"* — while the panel three functions below publishes its aggregate.

**FIX:** a second column (`billed_inr`) accumulated at the CLIENT's rate. Cap and client
panel read the new one; the margin panel keeps the old one.

### P1.4 — Two USD/INR rates, 8.7% apart · SERIOUS · OURS

`config.py:212` defaults `usd_inr_rate` to `88.00` — the rate that converts every engine leg
into `unit_cost_paid`. `ai_quota.py:190` bakes in *"₹95.66 to the dollar (RBI reference, 16
Aug 2026)"*. One fact about the world, two values, same month. The 88.00 default understates
our own cost ~8%, so the margin panel reads too healthy and — compounding P1.1 — the
self-serve wallet is debited a further ~8% below true cost.

**FIX:** one home. Best: `ai_quota.py` derives its INR price from
`settings.usd_inr_rate × USD list price` instead of storing a pre-multiplied literal.

### P1.5 — The INR branch of the cost adapter divides by 100 on a silent premise · SERIOUS · OURS to mark, EXTERNAL to settle (gate 7)

`bolna.py:196` computes `cents / 100 * rate` and `bolna.py:1041` hands a stated-INR payload
to the same function with `rate = 1`, i.e. it assumes INR arrives in **paise**. The
docstring argues carefully about the RATE and never about the SCALE. If Bolna reports INR in
rupees, every INR call is metered at **1/100th** of true cost. The USD-cents premise is
marked; this one is not — the exact shape D-31/D-32 forbid.

**FIX:** name the minor-unit assumption in a constant beside `_ASSUMED_CURRENCY` and add it
to gate 7, or refuse the INR branch until the gate answers.

### P1.6 — The ledger-correction path has no production entrypoint · SERIOUS · OURS

`billing/service.py:1241` defines `record_tier_correction`; its only callers are in
`tests/tts_tier_metering_test.py`. Hard rule 4 says fixes are compensating entries — so the
compensating entry for a mis-tiered call is a 145-line function invocable from pytest and
nowhere else. `usage_events` carries an immutability trigger, so a mis-billed call in
production today has **no legal remedy** short of hand-written psql against an append-only
table.

**FIX:** one audited ops action, or a `scripts/` entry point in the family of
`reconcile_credit_ledger.py`. It needs a `chars` input only a Sarvam usage export supplies —
name that in the runbook.

### P1.7 — `tts_tier_source` is written on every row and read by nothing; the register was wrong about why · SERIOUS · OURS

The audit corrected this document. The earlier claim — *"the mapping from engine model name
to rung is not confirmed"* — conflates two constants and is wrong about both:

- `ENGINE_REPORTS_TTS_MODEL = False` (`rates.py:74`): there **is no engine model name**. The
  engine reports a synthesizer leg cost only, so the rung is read from the agent's
  configured voice via `agents/voices.py`. The mapping is not unconfirmed; it does not exist.
- `ENGINE_TTS_MODEL_GENERATION_VERIFIED = False` (`rates.py:109`): a different question —
  whether Sarvam's premium rung is still *called* v3 given Aug-2026 reports of a v4 at the
  same price. **The money is unaffected**; the exposed thing is the identifier.

**It can mislead an operator in one specific way.** `billable_tier` (`rates.py:168`) returns
`("value", "unproven")` for an unrecognised voice, so an unattributable call is stamped
`value` and lands in `minutes_value`. `tier_usage`'s docstring (`service.py:1195`) claims
three buckets keep "we know this ran on v2" and "we never knew" apart. They do not.

**FIX:** add `meta->>'tts_tier_source'` to `_tier_totals`' GROUP BY and give the panel a
fourth cell for value-but-unproven. Correct the docstring either way.

### P1.8 — Invoice will self-certify as a tax invoice while missing a mandatory particular · SERIOUS · OURS (columns) / EXTERNAL (registration)

`gst.py:206` decides "may this deployment issue a TAX INVOICE" from the four
`GST_SUPPLIER_*` env values alone, and `invoice.py:402` flips `document_type` on that
predicate. But the recipient block (`invoice.py:411`) carries name, email, GSTIN and state —
**no address** — and `tenancy/models.py:43` has no postal-address column at all. Rule 46(e)-(f)
requires name **and address**. Also absent: Rule 46(p) reverse-charge statement; a real
issue DATE (`generated_at` is the render timestamp, re-derived every GET).

**FIX:** add `organizations.billing_address`, print it, and give `document_type` a
per-document blocker list so it cannot go green on a document missing a mandatory field. The
reverse-charge line is one literal.

### P1.9 — Minor money items · MINOR · OURS

- `payments.py:252` says a `Settings` field *"DOES NOT EXIST YET"*. It exists
  (`config.py:605`). Before it existed, setting `RAZORPAY_KEY_SECRET` crashed boot on
  `extra="forbid"`; now it configures. A stale paragraph on the money-critical module that
  tells a reader the opposite of the truth. Delete it.
- `apps/web/src/components/ui.tsx:474` (`formatINR`) and `usage/page.tsx:631` (`addRupees`)
  TRUNCATE below two decimals rather than round. Safe today because every field they receive
  is paise-rounded server-side, but `unit_inr` on an invoice line is a deliberate 4dp rate —
  one future caller drops a fraction of a paisa on a legal document. Make them refuse or
  round explicitly.
- The margin panel hard-codes `"Premium (v3)"` / `"Value (v2)"`
  (`admin/tenants/[tenantId]/page.tsx:665`) while the catalog owns those words
  (`voices.py:150`) and `rates.py:109` says the generation is unverified.
- `scripts/pilot/safety.py:60` imputes ~467 chars/min, the exact imputation `rates.py:142`
  refuses to make. Low stakes (a budget line, never a ledger row) but the same premise
  treated two ways.

---

## PART 2 — The ack budget and the engine boundary

**Why second:** P2.1 is a measured hard-rule-3 violation on the service carrying live calls,
and the guard written to prevent exactly it cannot see it.

### P2.1 — `/healthz/ready` pulls the vendor adapter and httpx onto the live-call event loop · SERIOUS · OURS

Measured, not inferred. `health.py:163` → `settings.py:479` → `engine/__init__.py:108` →
`build_engine` → `from apps.api.engine.bolna import BolnaEngine`. voice-runtime builds with
`minimal=True` but `bootstrap.py:363` installs the health router anyway, and
`infra/nginx/calevate.conf.template:161` proxies `^~ /healthz/` on the `hooks.` vhost — so
the route is **publicly reachable**.

Booting voice-runtime exactly as uvicorn does, then making one `/healthz/ready` call:

```
httpx at boot: False    engine at boot: False
AFTER readiness call: ['apps.api.engine', 'apps.api.engine.bolna',
                       'apps.api.engine.capabilities', 'apps.api.engine.document', 'httpx']
```

With `ENGINE=fake` it pulls `apps.api.billing` instead. Every one of those is in the
receiver's own `FORBIDDEN` list. The import costs **381 / 435 / 394 ms** in three fresh
interpreters — against a **500 ms** ack budget, synchronously, on the event loop, on the
service whose vendor delivers at most once with no retry.

The guard misses it because `_boot_modules()` measures `sys.modules` after importing `main`
only, and `_drive()` exercises the hook and tool routes and never `/healthz/ready`.

Secondary: voice-runtime reports itself **not ready** for `BOLNA_API_KEY`, a credential it
never uses — it makes no outbound call at all.

**FIX:** inject a per-service `config_probe` into `build_health_router` (the way `detail_gate`
already is), or move `credential_env_keys` to a module-level table beside
`WEBHOOK_AUTH_BY_ENGINE` so readiness can name a key without constructing an adapter. Then
add `/healthz/ready` to `_drive()` so the clause actually covers it.

### P2.2 — A raw `JSONDecodeError` escapes the Bolna adapter on a non-JSON 2xx · SERIOUS · OURS

`bolna.py:650` calls `response.json()` unguarded. The `>=400` branch raises first, so the
exposure is a **2xx with a non-JSON body** — a WAF challenge, a proxy interstitial, a CDN
maintenance page. `JSONDecodeError` is a `ValueError`: not a `ProblemError`, not an
`httpx.HTTPError`, caught by nothing. It reaches `create_agent` as a raw 500 with no code and
no remediation; it makes `verify_publish`'s *"never raises for a vendor-side failure"*
docstring false; and it DLQs the post-call pipeline and the reconciliation poller.

**This repo already solved this twice.** `payments.py:656` catches `ValueError` and
`tests/payment_order_test.py:503` pins it by name. `cartesia.py:372` has the guard. The
adapter actually going to production is the one that missed it.

**FIX:** wrap in `try/except ValueError` → the existing `engine_bad_response` ProblemError.
Add a conformance clause parametrised over all three adapters.

### P2.3 — `_next_link` raises `httpx.InvalidURL` out of the poller, contradicting its own docstring · SERIOUS · OURS

`bolna.py:1207` constructs `httpx.URL(candidate)` on a vendor-supplied string, unguarded.
Verified against the installed httpx: `httpx.URL("http://a​.com")` raises `InvalidURL`,
whose MRO does **not** include `httpx.HTTPError` — so `_request`'s handler would not catch it
even if it were inside one, and it is not. The docstring three lines above promises the
opposite: *"anything else is dropped — dropping degrades to `explicit_more`, which is loud"*.

`list_executions`' only caller is `reconcile_executions`, which under D-31 **is the guarantee
of record**. An exception there retries three times and DLQs, and every execution whose
webhook was lost stops being recoverable until somebody reads the DLQ.

**FIX:** catch `httpx.InvalidURL` → log + `continue`, landing on `explicit_more` exactly as
promised. Add the case beside the existing off-origin test.

### P2.4 — Cartesia is selectable at runtime and is not safe to select · SERIOUS · OURS to record / EXTERNAL to close

The register listed ONE inferred Cartesia route. Counting what the adapter actually calls:
**read at source: zero** (the one sourced route is never called), **reported: one**,
**INFERRED: ten** — create/update/get/delete agent, end call, get/list executions, and three
document CRUD siblings — plus an unverified status enum and transcript shape.

Three things make it unsafe today, at once: every webhook is refused (`cartesia.py:818` fails
closed, and the receiver independently refuses `hmac`), so 100% of calls depend on an
INFERRED poller path; `_cost` returns `None` forever, so **no usage_event is ever written for
any call** and nothing says so (P1.2); and `billable_ready` is equated to `terminal` on an
unsourced premise. It also has **no throttle ladder at all**, so a 429 becomes a
non-retryable `engine_rejected` — the exact harm the Bolna adapter documents avoiding.

And it IS selectable: `EngineName` includes it, migration `d7b1c48a2e93` widened the CHECK,
and `engine` is console-editable at runtime, whose `AppliesRule` warns only about stale refs
and webhook URLs.

**FIX:** expand the register's row to the ten routes plus the two permanent gaps. Extend the
`AppliesRule` text. Consider refusing `engine=cartesia` in config validation until signature
verification and cost reading exist.

### P2.5 — Half the `VoiceEngine` contract has no production caller, including a model CLAUDE.md names · SERIOUS (as a hard-rule documentation defect) · OURS

`parse_webhook`, `verify_webhook`, `transfer` and `end_call` have **no production caller**
(pilot scripts and conformance only; `transfer` has none anywhere). And `CallEvent` — which
**hard rule 2 names as one of the two normalized models everything else consumes** — has
exactly one hit across `apps/`, a comment. Nothing constructs or reads one.

This is defensible design and undefended prose: D-31 makes the webhook payload a hint the
receiver discards and the authenticated `get_execution` the truth, so the real isolation
boundary is `ExecutionSnapshot`, not `parse_webhook` — which `engine.py:1027` still calls
*"The isolation boundary"*.

**FIX:** state the standing at each Protocol member, or delete `transfer` and its capability
field until an escalation surface needs it. Correct hard rule 2's wording in CLAUDE.md and
docs/AGENTS.md: the models production consumes are `ExecutionSnapshot` and `TranscriptTurn`.

### P2.6 — Contract and guard drift · MINOR · OURS

- `fake.py:479` fabricates a snapshot for an unknown execution id while its own comment says
  it matches the real thing; `bolna.py:1066` 404s. Two adapters disagree and there is **no
  conformance clause** for `get_execution` on an unknown id, though there are explicit ones
  for `get_agent` and `detach_kb`. This is verbatim the divergence `EngineCapabilities` exists
  to prevent.
- `engine_availability()`, `engine_not_configured()` and `provisionable_series()`
  (`capabilities.py`) are exported, documented as *"the ONE deployment-side refusal, so every
  surface says it the same way"* — and have **no callers**. The three adapters hand-roll the
  same error code instead. `provisionable_series`' docstring claims the campaign gate matches
  on the series; the gate matches on OUR `phone_numbers.series`.
- `engine_intake.py:119` looks the auth METHOD up by engine and then uses Bolna's IP allowlist
  for any engine declaring `source_ip` — inert today, and precisely the hazard the same file
  flags one branch below for `hmac`.
- `tests/engine_audit_test.py:1005` bans two adapters out of three; `cartesia` is missing. The
  property is covered by a prefix rule elsewhere, which makes this a duplicated check whose
  weaker copy fell behind — the drift class D-103 exists for.

---

## PART 3 — Indian telecom and privacy law as enforced code

**Why third:** P3.1 is the only finding in this whole audit where the product does something
to a real person that a certificate says it did not do.

**Status of the section's four core questions**, answered structurally rather than by
inspection (the auditor ran the AST half of `check_compliance_invariants.py` directly):

- **Can anything dial outside 09:00–21:00 IST? No.** Exactly four dial sites exist, all four
  pass `check_dispatch` → `within_calling_hours`. Retries re-enter through the same path
  (`campaign_dispatch.py:962`), scheduled campaigns dial nothing themselves, and per-campaign
  windows can only NARROW and are re-asked per contact.
- **Does an in-call opt-out propagate before the next tick? Not provably** — see P3.4.
- **Is every claim on the erasure certificate true? Yes** — but a whole store of personal data
  is neither erased nor admitted (P3.1).
- **Does the audit chain detect tampering? Yes, except tail truncation** (P3.7).

### P3.1 — `campaign_contacts` is unreachable by BOTH erasures, has NO retention clock, and neither certificate admits it · BLOCKER · OURS

`campaign_contacts` carries `phone_e164 NOT NULL`, `name`, and `custom JSONB` holding **every
other column the client pasted from their CSV** (`campaigns/models.py:118`, written at
`campaigns/service.py:610`). The string `campaign_contacts` appears in **none** of
`workers/retention.py`, `compliance/deletion.py`, `compliance/tenant_erasure.py`,
`compliance/deletion_proof.py`.

Three consequences, each independently serious:

1. **The per-subject DPDP §12 erasure misses it.** `execute_deletion_request` locates the
   subject through `calls` and `leads` only (`retention.py:990`). Their number, name and
   pasted columns survive intact.
2. **The subject stays DIALABLE after being certified erased.** The contact row is still
   `status='pending'` with a live number, and the erasure adds no DNC entry — there is no
   `add_to_dnc` anywhere in `retention.py` — so `check_dispatch` permits the dial. **We ring a
   person whose certificate says they were removed.**
3. **Both certificates claim exhaustive enumeration and are not.**
   `TENANT_ERASURE_LIMITATIONS` lists seven exceptions, the per-subject register eight, the
   proof `actions` map ten stores — and none names this one. SEC-COMP §4 says explicitly that
   what erasure does not reach "is enumerated in the certificate rather than left to
   inference".

Separately **no clock reaches it**: `retention_policies.data_category` is CHECK-constrained to
`('recording','transcript','lead','consent_log')` (`05bba2f3c19c`), so an uploaded contact
list is kept **indefinitely, with full phone numbers** — a DPDP §8(7) storage-limitation
exposure that is undisclosed. And nothing is watching: `tests/dpdp_known_gaps_test.py:31`
holds exactly two entries and asserts equality.

**FIX (one change, three parts):** (a) add `campaign_contacts` to both erasure paths —
anonymize `phone_e164`, NULL `name` and `custom`, set `status='dnc_blocked'` so a running
campaign settles rather than dials; (b) add the count to `proof.actions` in both paths;
(c) if the founder decides erasure should not touch a client's own contact list, it becomes a
`*_LIMITATIONS` entry with an authority line **plus** a `dpdp_known_gaps_test` entry — never
silence. The retention half (a `campaign_contact` category) is a documented-enum change and a
DPA commitment: **EXTERNAL**, same shape as the KB reservation.

### P3.2 — The number that decides whether a call is lawful has no authority, and the document it cites says the opposite · SERIOUS · OURS (citation) / EXTERNAL (the value)

`DEFAULT_WINDOW = (time(9,0), time(21,0))` (`compliance/service.py:75`) is sourced as
"SEC-COMP §2.5", and `campaigns/service.py:352` tells the client in a 422 body that *"That
window is the law (TRAI)"*. SEC-COMP §2.5 is one line — *"Calling hours: campaign engine
enforces permitted windows; **per-tenant timezone**"* — containing neither `09:00` nor `21:00`
nor a TRAI provision, and asking for per-tenant timezone resolution that
`compliance/service.py:30` explicitly refuses. Two contradictions in one citation, on the
constant with the widest blast radius on the platform.

`compliance/optout.py:11` is the standard this repo set — it cites TCCCPR 2018 Reg. 6/17, the
12 Feb 2025 Second Amendment and PIB PRID 2102413 by name, and records which gazette PDFs
were unreachable. The calling window does not meet it.

**FIX:** put a citation of that form beside `DEFAULT_WINDOW`; correct SEC-COMP §2.5 to state
the window and drop "per-tenant timezone" (or say why the code departs); note that TCCCPR
time bands are subscriber-preference-scoped and the NCPR is not obtainable to us, so
09:00–21:00 is the conservative outer bound rather than a per-subscriber answer.

### P3.3 — Nothing records that the AI disclosure was actually spoken, and the read-back that claims to verify it cannot see the field that speaks · SERIOUS · OURS

Three layers, and the top two do not connect:

- The disclosure reaches the vendor twice — prepended to the system prompt AND as the greeting
  field (`bolna.py:675` `agent_welcome_message`, `cartesia.py:408` `introduction`). Only the
  greeting makes it the deterministic FIRST utterance.
- `judge()` computes `disclosure_applied` from `snapshot.carries_prompt_marker(...)`
  (`agents/verification.py:141`) against `AgentSnapshot.system_prompt` — and `AgentSnapshot`
  has **no greeting field at all** (`engine.py:498`). So `disclosure_applied=True` is true by
  construction of our own prepend and proves nothing about the field that actually speaks.
  OPERATIONS §7 escalates `disclosure_applied: false` as *"the one property here with a legal
  consequence"* — an incident signal wired to the wrong half.
- `calls.disclosure_played` (`crm/models.py:85`) is **written by nothing in the repository**.
  It is rendered on the client call detail and on the weekly QA compliance-review queue
  (`quality/sampling.py:203`), where a reviewer working OPERATIONS §5's "disclosure spoken"
  scenario sees a permanently null field where the evidence belongs.

The only real control is a one-off manual pre-launch check. IT Act / Sanjay Pandey exposure
(SEC-COMP §1) rests on it.

**FIX:** (a) add `greeting` to `AgentSnapshot` with a `_readable` flag in the shape the other
two use, populate from both adapters, and split the verdict into prompt-carried vs
greeting-carried — an unreadable greeting reports `None`, never `True`; (b) either write
`disclosure_played` from the post-call transcript pass (the same deterministic match
`detect_opt_out` already does over turns) or drop the column from both response models. A
compliance field that is structurally always null is worse than an absent one.

### P3.4 — Hard rule 5's "before the next dispatch tick" is false of the in-call tool path · MINOR · OURS (wording) / EXTERNAL (gate 8)

For a DNC row that EXISTS, propagation is ≤1 tick — the gate's read is live SQL with no cache.
But detection→row is unbounded: `tool_routes.py:162` only enqueues, and `workers/optout.py:86`
then makes a vendor `get_execution` round trip before any write, with a 30s/120s retry ladder.
SEC-COMP §2.3 states this correctly ("target ≤ minutes"); CLAUDE.md hard rule 5 does not.

Second, unmarked: `optout.py:115` reads `from_e164`/`to_e164` from an execution **still in
progress**. Whether Bolna populates those mid-call is recorded nowhere. The failure is loud
(`in_call_optout_unattributable`) but D-31/D-32 doctrine says a vendor behaviour is a gate or
a marked assumption, never a silent premise.

**FIX:** reword the hard rule to what is enforced ("a DNC addition is honoured by the next
dispatch tick"), and add "does `get_execution` carry both numbers for an in-progress
execution?" to gate 8 as item (c).

### P3.5 — Backups and the recording-floor authority · SERIOUS · EXTERNAL, and correctly registered already

Both are real, both held open by an equality assertion in `tests/dpdp_known_gaps_test.py:31`,
both name who closes them, and SEC-COMP §4 reserves both in writing. The auditor checked
whether the register had gone stale — it has not. **No action.** Recorded only because P3.1 is
a third gap of exactly this class that *should* be in that file and is not.

### P3.6 — Two bounded edges on the dial gate · MINOR · OURS

- `within_calling_hours` uses `start <= current <= end` (`compliance/service.py:124`), so
  `21:00:00.000–.999` is dialable. One second, and a `<` away.
- `check_dispatch`'s big-red-switch read goes through a 5s memo over a 15s Redis cache, so it
  can be up to 20s stale — `loadshed.py` states and defends that bound, but
  `campaign_dispatch.py:645`'s comment ("stops a batch mid-flight because `check_dispatch`
  re-reads it per contact") reads stronger than it is. One-line correction.

### P3.7 — The audit chain cannot detect tail truncation, and the summary is outside the hash · MINOR · OURS

`verify_chain` walks forward from GENESIS and re-anchors per row, so a deleted MIDDLE range is
caught as `link` — but deleting the NEWEST n entries leaves a chain that verifies end-to-end
with zero breaks, because the head "lives nowhere else" and there is no external anchor.

The DB-layer mitigation is strong (migration `a2e9f31c605d` adds `BEFORE TRUNCATE ... FOR EACH
STATEMENT` triggers, `ENABLE ALWAYS` so `session_replication_role = replica` cannot bypass
them, and `calevate_app` holds no TRUNCATE grant), so this is defence-in-depth rather than a
live hole. But `ChainVerification`'s own design principle is that "the scope is part of the
answer", and its verdict cannot say this. Also: `write_audit`'s `summary` is deliberately not
in the hashed payload, so the chain attests actor/action/object and never the detail — worth a
sentence so nobody reads `ok=True` as "the summaries are intact".

**FIX:** record `entries_checked` + `newest_checked_at` from each run into a durable ops row,
so a later walk can assert the log only grew. One table, one comparison, and it turns the
strongest remaining attack on the ledger into a detectable one.

### Checked and clean (compliance)

No gate bypass parameter, no environment read on any gate-bearing function, no test hook —
`gate_bypasses()` and `stale_exemptions()` both clean across `apps/`, `packages/`, `scripts/`.
`check_dispatch` fails closed on a missing org row and derives refusing consent statuses by
SUBTRACTION from `CONSENT_STATUSES`, so a new status blocks by default. Phone normalization is
ONE function used by every DNC writer and reader alike, so the exact-string match cannot miss.
DLT/PE-TM, template, series and national-DND gates are re-asked every tick, and `add_contacts`
refuses non-draft campaigns, which closes the "scrub 3, add 5000" hole. CSV export is
`calls:read_raw` + audited with column keys but never values. Webhook phone masking happens at
the fan-out per endpoint, so a producer passing the domain row cannot leak. `redact_mapping`
fails closed on TYPE — Pydantic models render as `<ClassName>`, sequences as a count — and
exception messages are withheld rather than masked. OTel is redacted at the exporter, Sentry
has both `scrub_event` and `scrub_breadcrumb`. All three compliance jobs are registered.

---
