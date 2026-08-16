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

## PART 4 — Data, tenancy and schema integrity

**Why this part matters most for the FIRST deploy:** P4.1 means a successful, green deploy
still cannot onboard client #1. It also corrects this register's closing claim.

**The four structural questions, answered by rebuilding the revision map from source:**
the chain is **linear — 65 revisions, one root (`05bba2f3c19c`), one head (`a7c31e05b8d4`),
no branch, no orphan, no cycle**. No revision has an empty or `pass`-only downgrade; the
three containing `raise` are all the count-before-you-drop refusal pattern, not
irreversibility. All nine `ADD CONSTRAINT ... NOT VALID` are paired with a `VALIDATE` in the
same `upgrade()`. All 42 tenant tables get a behavioural cross-tenant test, not just the
sweep — `rls_sweep_test.py:327` drives a wrongly-addressed INSERT against every discovered
table and asserts sqlstate `42501`, with `assert len(refused) == len(sweep.tables)` so it
cannot pass on a partial probe. One dead table (`kb_retrieval_logs`), properly recorded in
`UNWIRED_BASELINE` with dated reasons and a test that fails the day anything names it.

### P4.1 — There is no way to create the first `admin_users` row · BLOCKER · OURS

`admin_users` is the allowlist the whole admin realm resolves against (`core/auth.py:691`),
and `core/clerk_identity.py:80` states the design: *"The admin realm is never reconciled.
`admin_users` is not a Clerk mirror; it is an ops-managed allowlist."*

**Nothing in the repository ever inserts a row.** Not `scripts/seed.py`, not
`scripts/vps-deploy.sh`, not `compose.prod.yml`, not `docs/DEPLOYMENT.md`, not any runbook —
the string does not appear in any of them. It is the one table with zero writers that is NOT
recorded as deliberately dead.

After `alembic upgrade head` on a fresh VPS the table is empty, so **every admin-realm request
403s**: no organization can be created, no platform setting written, no secret stored, no
first-campaign review decided, no KYC verified. The deploy comes up green and the product is
unreachable. It fails closed, so it is not a security hole — it is a deployment that cannot
onboard anyone.

**FIX:** one INSERT, but it needs a home that is not a shell history. Either
`scripts/bootstrap_admin.py` in the family of `scripts/seed.py` (Clerk user id + role,
`ON CONFLICT DO NOTHING`), or a numbered step in DEPLOYMENT.md with the exact SQL. The Clerk
account is external; **the row is ours.**

### P4.2 — `scripts/seed.py` never runs on a production deploy, so `reserved_slugs` is empty · SERIOUS · OURS

`vps-deploy.sh:412` runs `compose --profile migrate run --rm --no-deps migrate`, whose command
is `["alembic","upgrade","head"]` (`compose.prod.yml:167`). That is the entire database step.
`scripts.seed` is invoked in exactly one place in the tree — `runbooks/stale-dev-database.md:43`,
as part of the explicitly-dev `make db-reset`.

`reserved_slugs` is the only global row the seed writes and the sole enforcement of slug
reservation (`admin/service.py:207`). Against an empty table that probe always misses, so
`admin`, `api`, `app`, `www`, `hooks`, `login`, `billing`, `support`, `security` and
`calevate` are all claimable in production.

Stated so it is not overclaimed: vertical templates and retention defaults are unaffected
(Python constants, not DB rows), and self-serve signup is off by default. So today the
exposure is the admin console's own org-creation wizard — and **it becomes a public
impersonation surface the minute `SELF_SERVE_SIGNUP_ENABLED=true`**, because
`tenancy/signup_routes.py:83` is mounted and gated only by `current_identity`.

**FIX:** add the seed to the deploy's migrate step, or a second one-shot profile beside it. It
is idempotent by construction.

### P4.3 — Seven live columns are missing from `Base.metadata`, so the next autogenerate proposes DROPPING them · SERIOUS · OURS

`alembic/env.py:19` sets `target_metadata = Base.metadata` and CLAUDE.md's workflow is
"autogenerate + hand-review diff". Seven columns exist in the migrated schema, are written and
read by production code, and are absent from the ORM models:

| Column | Created | Live use | Model omitting it |
|---|---|---|---|
| `campaigns.dnc_scrubbed_at` | `a1c8e40f27b9:163` | read `campaigns/service.py:1175`, exposed `routes.py:260` | `campaigns/models.py:63` |
| `engine_agent_routes.drift_state/_checked_at/_detected_at` | `d4b8e1c73f05:138` | the D-121 sweep's whole record | `reliability/models.py:99` |
| `engine_agent_routes.kb_drift_state/_checked_at/_detected_at` | `a7c31e05b8d4:140` | the D-158 sweep | same |

`dnc_scrubbed_at` is **compliance evidence** — when our own DNC scrub ran, half of SEC-COMP §3's
DNC bullet. The six drift columns are the ones the RLS exemption spends fourteen lines
justifying.

Two compounding effects. `check_wiring.py:298` reads its column universe from `models.py`, so
all seven are **outside the wiring guard entirely**. And this repo has recognised the
autogenerate round-trip hazard three times — `call_latency_column_test.py`,
`prefix_index_audit_test.py`, `credit_ledger_index_prune_test.py` — each time only in the
REMOVAL direction. The opposite direction has no guard and seven instances.

**FIX:** declare the seven. Then one general check that `Base.metadata` and the migrated schema
agree in BOTH directions (alembic's `compare_metadata` against a migrated DB, in the family of
`check_rls_coverage`, which already builds an owner-role engine).

### P4.4 — Four write-only columns, none recorded, in the exact shape `check_wiring` names as its blind spot · SERIOUS · OURS

`check_wiring.py:29` says it outright: *"a column with a writer and no reader is NOT caught
here."* Four live instances:

- **`phone_numbers.engine_number_ref`** — the only INSERT does not list it and nothing reads
  it. It escapes even the "no code touches it" check because `_referenced_names` matches the
  bare name and `calevate_shared/engine.py:597` declares an identically-named field on a
  **non-DB Pydantic model**. *A namesake on a different class satisfies the guard.* Its two
  siblings (`Agent.engine_staging_ref`, `Campaign.engine_campaign_ref`) ARE in
  `UNWIRED_BASELINE`.
- **`campaign_contacts.dedupe_hash`** — written every insert as `sha256(phone)[:16]`, read
  nowhere, no index; dedupe is actually done by an in-memory set and `ON CONFLICT` two lines
  above.
- **`leads.first_call_id`** — written at `pipeline.py:1200`, read nowhere, while its twin
  `last_call_id` is read six ways.
- **`platform_state.changed_by`/`changed_at`** — written by both writers, and **neither reader
  selects them**. Who threw the big red switch is answerable only from `audit_log`.

**FIX:** one line each. `dedupe_hash` and `first_call_id` are droppable under rule 8's two-step.
`engine_number_ref` belongs in `UNWIRED_BASELINE` beside its siblings, closing when
`PROVISIONING_IMPLEMENTED` does. The guard's name-matching hole deserves a note in its own
docstring, which documents its other blind spots honestly.

### P4.5 — The ledger guardrail's docstring enumerates four ledgers; there are eight · SERIOUS · OURS

`check_ledger_immutability.py:3` names `usage_events`, `consent_ledger`, `credit_ledger`,
`audit_log`. `APPEND_ONLY_TABLES` holds **eight** — plus `one_time_charges`,
`whatsapp_alert_optin_ledger`, `preference_scrub_runs`, `platform_secrets`.

This is precisely the defect CLAUDE.md hard rule 4 names in its own commentary — *"a count in
prose is the defect class D-103/D-105 exist for"* — on the first line of prose in the file
whose entire job is rule 4. The code is correct (every function iterates the constant);
migration `a2e9f31c605d:9` gets it right, so the two disagree.

Same class, lower stakes: `migration_reversibility_test.py:4` says the walk ran "over all 62
revisions"; there are 65.

**FIX:** replace the enumeration with a reference to the constant, exactly as CLAUDE.md does.

### P4.6 — `RLS_EXEMPT_TENANT_COLUMNS` claims to be the one list of what is not tenant-isolated, and three tables are missing · SERIOUS · OURS

`db/registry.py:135` states the contract: two shapes share one dict because they share *"the
only property that matters to a reviewer — 'this table is deliberately not tenant-isolated,
and here is why' — so they share one list rather than growing a second one nobody would think
to read."* Three tables of exactly those shapes are absent:

- **`webhook_deliveries`** — the important one. No `tenant_id`, no policy, and it holds
  `payload_ref`: the object-storage key of a CRM payload containing a lead's name and number.
  Its "why" lives only in a model docstring no guardrail reads and no test pins.
- **`platform_state`** — the big red switch and the TM registration; same shape as
  `platform_settings`, which IS listed.
- **`platform_ai_spend`** — whose own migration asserts the equivalence the registry does not
  honour (`e1a7c93d5b02:109`).

`check_rls_coverage` never flags them because rule 1 only iterates tables carrying `tenant_id`.
So the list is complete for the guardrail and incomplete for the reader it says it exists for —
and `guardrail_audit_test.py` pins the exact key set, so the omission is load-bearing.

**Credit where due:** every one of the five `webhook_deliveries` query sites carries
`AND endpoint_id IN (SELECT id FROM outbound_webhooks)`, each with its reason written above it.
The auditor looked for the one that forgot; there isn't one.

**FIX:** add the three with the reasons already in their model docstrings, and widen the dict's
comment from `platform_*` to "any table deliberately outside tenant isolation".

### P4.7 — Prose contradicting schema · MINOR · OURS

- `reliability/models.py:110` calls `engine_agent_routes` *"deliberately boring: two opaque ids
  and the pair they map to."* It now carries six drift columns (P4.3) — and that sentence is
  the load-bearing half of the RLS exemption's "carries no PII and no call data" argument.
- `docs/OPERATIONS.md:244` still lists *"latency stage breakdown (stt/llm_ttft/tts_ttfa/turn
  p50/p95)"* among the dashboards. `f1a7c39d5be2:100` flagged this when it dropped the column
  and declined to edit a doc it did not own. DATA-MODEL §4 and TRD §4 were fixed; OPERATIONS
  was not.

### P4.8 — Two `ON DELETE` clauses encoding deletions the schema forbids · MINOR · OURS

- `preference_scrub_runs.campaign_id → ON DELETE SET NULL` on an append-only table with an
  `ENABLE ALWAYS BEFORE UPDATE` trigger. A campaign delete fires the cascade's UPDATE, the
  trigger raises, and the delete fails with an error **naming a table the operator was not
  touching**. Latent today (no `DELETE FROM campaigns` exists).
- `webhook_deliveries.endpoint_id → ON DELETE SET NULL`. If an endpoint were hard-deleted, its
  delivery rows would go `endpoint_id = NULL` and become unreachable to **every** query in
  P4.6's list — including the retention sweep, which would then never clear their `payload_ref`
  nor delete the objects behind them. Personal data outliving its TTL with nothing pointing at
  it. The saving invariant is real and documented (*"endpoints are DEACTIVATED, never
  deleted"*) — but the FK says the opposite of the invariant, and the FK is what a future route
  author reads.

### P4.9 — `lock_timeout` is doctrine in some migrations and absent in twelve · MINOR · OURS

`f1a7c39d5be2:105` argues the rule at length under a "LOCKING (hard rule 8)" heading. Twelve
migrations taking `ACCESS EXCLUSIVE` do not set it, and two post-date the doctrine:
`f8c1d47a90e3` (two revisions from head, `add_column` on `call_extractions` — written on every
call) and `d7b1c48a2e93:81` (a CHECK swap on `agents`, which still scans under ACCESS EXCLUSIVE
on the ADD). Irrelevant for a first deploy against an empty database; **the second deploy pays.**

### Checked and clean (data/tenancy)

All 42 `TENANT_TABLES` receive ENABLE + FORCE + a `tenant_isolation` policy in the migration
that creates the table; `organizations` is special-cased on `id` in both guardrail and sweep;
registry drift is checked in BOTH directions and the arithmetic balances (44 − 2 = 42). The
uniform `FOR ALL … USING`-only policy shape is *measured* rather than asserted —
`rls_sweep_test.py:396` demonstrates why it refuses a self-hijack via two independent
PostgreSQL checks. The owner role never appears in app code; `alembic/env.py:34` refuses to
fall back to `DATABASE_URL`. The five GUC-widening sessions each widen exactly one `USING`
clause and no `WITH CHECK`, all transaction-local. No `UPDATE`/`DELETE`/`TRUNCATE` against any
of the eight ledgers in the four trees the guardrail does NOT scan; no FK into a ledger uses
CASCADE. Zero `DateTime()` without `timezone=True`; zero `datetime.now()`/`utcnow()` anywhere;
the only `sa.Float` is on the dead table. First-deploy DDL is sound: idempotent role creation,
`ALTER DEFAULT PRIVILEGES` covering later migrations, the one sequence granted explicitly, both
`NO FORCE`/`FORCE` brackets inside alembic's per-revision transaction, and the single
`CREATE INDEX CONCURRENTLY` correctly in an `autocommit_block`. ORM and migration TABLE sets
are exactly equal at 57; only the column sets diverge, at P4.3's seven.

### Correction to Section C of this register

Section C should list a fourth never-run item: **the database's first-run state**. `alembic
upgrade head` is the only database step the deploy performs, and it produces a schema with an
empty `admin_users` (P4.1) and an empty `reserved_slugs` (P4.2). This register's closing
sentence — *"the gap is almost entirely accounts, registrations and one never-executed deploy —
not code"* — is right about the shape and **wrong by two rows**: both are ours, both are small,
and the first means a successful deploy still cannot onboard client #1.

---

## PART 5 — Everything needed to actually run this

**Read this part before attempting a deploy.** Six findings here stop the first deploy or
silently break it, and three places in the operator-facing documents state facts that are
wrong rather than merely incomplete.

**The headline is structural.** This register said one thing had never run (terraform). In
this area **nothing has ever run, and no gate could have caught it**: `scripts/vps-deploy.sh`
(621 lines), `compose.prod.yml`, `Dockerfile` and `infra/nginx/` have **no CI step, no
`bash -n`, no shellcheck, no `docker compose config`, no `docker build`**. `.github/workflows/ci.yml`
never mentions any of them, `.pre-commit-config.yaml` has no shell hook, and `make check` does
not either. A repo with thirteen executable guardrails has **zero on the artefact that puts it
in production.**

### P5.1 — Nothing ever starts `redis`. The first deploy cannot succeed. · BLOCKER · OURS

`ALL_COMPONENTS=(api voice-runtime workers web nginx)` (`vps-deploy.sh:87`). `redis` is not a
component, not in the path map, and every swap is `compose up -d --no-deps "$service"` (`:459`)
— and `--no-deps` is precisely the flag telling compose **not** to start `depends_on`, so
`redis: {condition: service_healthy}` is never evaluated and the container is never created.

On the first `--all` run: workers start with no queue, `api` is swapped, `wait_healthy` polls
`/healthz` which does a Redis PING (`core/health.py:133`) and returns **503**. `curl -fsS`
fails for 90×2s and the deploy dies at `swap api` — **after migrations have already run.**

Nothing documents `docker compose -f compose.prod.yml up -d redis`; worse,
`compose.prod.yml:16` actively warns operators off running compose by hand, and
`runbooks/deploy-failed.md` §4 lists only `logs` and `curl`.

**FIX:** bring `redis` up as a first-class step before the swap loop (without `--no-deps`), or
make it an explicit numbered pre-step in DEPLOYMENT §9. The `--no-deps` reasoning is right for
*swaps* and wrong as the *only* way the stack is ever brought up.

### P5.2 — The documented rollback aborts at the migration step, in exactly the case it exists for · BLOCKER · OURS

Both `vps-deploy.sh:575` and `runbooks/deploy-failed.md:110` give the rollback as
`git checkout <previous-sha>` then `vps-deploy.sh --all --no-pull`. `--all` puts api/workers/
voice-runtime in the plan, so `run_migrations` runs `alembic upgrade head` **from the older
image**. If the failed deploy carried a migration — the case §4 is written for — the DB is at a
revision whose script **does not exist in the older image**, and alembic resolves the stored
`alembic_version` against the script directory before computing a path: `ResolutionError`, not
a no-op. **The rollback dies before swapping a single container, with production still running
the broken release.**

Compounding: `compose.prod.yml:30` tags every build `calevate/app:${CALEVATE_IMAGE_TAG:-local}`
and **nothing ever sets that variable**. There is no per-SHA image, so "rollback" is always a
full rebuild — serial `docker build` + `pnpm install` + the >2GB `next build` — on a degraded
production host, during an incident. A second consequence of the shared mutable tag: an
api-only build replaces the image `voice-runtime` uses on its next recreate, so hard rule 3's
decoupling holds at the container level and **not at the artefact level**.

**FIX:** (a) `run_migrations` must skip when the target image's head is an ancestor of the
current DB revision, or the rollback path must exclude migrations explicitly and the runbook
must say so; (b) tag images `calevate/app:<sha>` and record it in `.deploy-state/history` so a
rollback is `up -d` against an existing artefact.

### P5.3 — Migrations are NOT one transaction per revision, and three documents state a failure model the configuration does not implement · BLOCKER · OURS

`alembic/env.py:57` never passes `transaction_per_migration`. Verified against the installed
alembic: it defaults to `False`, so with PostgreSQL's transactional DDL the
`with context.begin_transaction():` at `env.py:61` opens **one transaction spanning the entire
`upgrade head` run**. All three of these are therefore wrong:

- `docs/DEPLOYMENT.md:270` — "alembic runs each revision in its own transaction, so a failure
  leaves the database at the last revision that fully applied"
- `scripts/vps-deploy.sh:397` — the same sentence
- `runbooks/deploy-failed.md:58` — "there is no half-applied revision"

Real behaviour: a failure rolls back **every** revision since the last commit point, and the
only commit points are three `autocommit_block()` calls. Alembic's own docstring says it:
*"It is recommended that when an application includes migrations with 'autocommit' blocks, that
`transaction_per_migration` be used."* This repo has such blocks and does not set it.

**The half-migrated state is real and lands on a money table.** `f9c2b41a8e57:167` builds
`CREATE UNIQUE INDEX CONCURRENTLY ux_credit_ledger_tenant_reason_ref`; a failed CONCURRENTLY
build leaves an **INVALID** index — never used for reads, still enforcing uniqueness on
inserts. The migration's own docstring documents this; `deploy-failed.md` §3, the file an
operator actually opens, does not mention invalid indexes and tells them the state is clean.

**FIX:** set `transaction_per_migration=True` — which makes the three documents TRUE rather
than editing them to describe a worse property — and add
`SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid` to `deploy-failed.md` §3.

### P5.4 — `pm2 reload calevate-web` fails on a host where it was never started, and the runbook's fix names a file that does not exist · BLOCKER · OURS

`vps-deploy.sh:480` runs `pm2 reload calevate-web`, which exits non-zero on an unknown process.
**Nothing in this repo ever runs `pm2 start`**, there is no ecosystem file, and DEPLOYMENT §2
says only "`pm2 startup` once". So DEPLOYMENT §9's `--all` aborts at `deploy web`. Then
`runbooks/deploy-failed.md:144` says to start it *"from the ecosystem definition"* — **there is
none**; `runbooks/database-restore.md:338` says `pm2 start calevate-web`, which cannot work
without one.

Secondary: `deploy_web` checks for `pnpm` and `pm2` at `:468` — **after** migrations have run
and all three containers have been swapped. Those are preflight checks living in step 9.

**FIX:** commit `apps/web/ecosystem.config.cjs`, make the step
`pm2 describe calevate-web >/dev/null || pm2 start ecosystem.config.cjs`, and move the
`command -v` checks into `preflight()`.

### P5.5 — The web build has no configuration source, ships green, and is unusable · BLOCKER · OURS

`apps/web/.env.example:1` states it: Next loads `.env*` from the **package** directory, every
`NEXT_PUBLIC_*` is inlined at build time, and a missing key *"compiles to the empty string,
ships, and fails as a broken screen in front of a client"*.

**`apps/web/.env.local` is placed by nothing.** The deploy preflights only `$ROOT/.env` and
never mentions the web file; DEPLOYMENT §9's go-live order never mentions it. So the first
`pnpm -C apps/web build` inlines empty strings and:

- `NEXT_PUBLIC_API_BASE_URL` unset → every browser at `app.calevate.tech` calls **its own
  localhost:8000**;
- both `NEXT_PUBLIC_CLERK_*_PUBLISHABLE_KEY` empty → every realm renders "sign-in is not
  configured";
- `resolveAuthMode` correctly resolves to `clerk` and **does not throw**, so `next build`
  succeeds.

`wait_healthy web` curls `/`, which the landing page answers 200. **The deploy prints DEPLOYED.**

This also breaks §9's central promise: step 10a says the remaining ~50 keys are set from
`admin.calevate.tech/ops` live — but the **publishable** keys the browser needs are build-time,
and you cannot reach `/ops` to fix anything until the admin realm's publishable key is already
baked in. A circular dependency the go-live order does not name.

**FIX:** add `apps/web/.env.local` to `preflight()` as a hard refusal alongside `.env`; add it
as a numbered item in §9 step 4; and fail the production build when either publishable key is
empty, the way it already fails on `AUTH_MODE=dev`.

### P5.6 — The object store has no credentials and no region, so recordings and raw payloads cannot be written · BLOCKER · OURS

`workers/storage.py:110` constructs the S3 client with `endpoint_url` and a `Config` — **no
`aws_access_key_id`, no `aws_secret_access_key`, no `region_name`**. botocore requires a
resolvable region for sigv4; without `AWS_DEFAULT_REGION`/`AWS_REGION` the constructor raises
`NoRegionError` before any request.

Those three variables appear **nowhere** in `.env.example` (which says "eight variables, and
deliberately nothing else"), nowhere in `compose.prod.yml`, nowhere in DEPLOYMENT §6 or §9, and
are not `Settings` fields — so they are also not among the "50 keys" the ops console manages.
The only place in the repo that gets this right is the **unapplied** lifecycle applier
(`infra/object-lifecycle/apply_lifecycle.py:181` passes `region_name`). Two constructions of the
same client, one correct, one shipping.

And the obvious operator fix is a trap: `Settings` is `extra="forbid"` with `env_file=".env"`,
so pasting `AWS_ACCESS_KEY_ID` into `/var/www/calevate/.env` **crashes any process that reads
it as a dotenv** — the same failure this register already records for `RAZORPAY_KEY_SECRET`
(P1.9). `/healthz/ready` does not probe object storage, so the deploy is green and the failure
surfaces as recording-copy retries and DLQ entries.

**FIX:** give `_client()` an explicit `region_name` sourced the way `apply_lifecycle.py` does,
add the three variables to `.env.example` and DEPLOYMENT §6 tier 1 (**the floor is not 8**), and
add an object-store probe to `/healthz/ready`.

### P5.7 — `docker compose up -d` in the deploy directory recreates production redis from the DEV file · SERIOUS · OURS

`compose.prod.yml:24` declares `name: calevate`. `docker-compose.yml` declares **no** project
name, so it defaults to the directory basename — `/var/www/calevate` → `calevate`. **Both files
address the same compose project and both define a service named `redis`.**

A bare `docker compose up -d` (the default file is `docker-compose.yml`) recreates production
redis from the dev definition: `redis:7-alpine` with `ports: "6380:6379"`, **no `--appendonly
yes`, and no `redis-data` volume** — destroying the ARQ queue and the webhook dedupe keys that
`compose.prod.yml:50` exists to protect. It also starts Postgres on `0.0.0.0:5433` with
`POSTGRES_PASSWORD: calevate` and MinIO on `0.0.0.0:9000`. A bare `docker compose down -v`
removes the whole project, prod containers included.

**Docker's published ports bypass `ufw`** (its rules sit in nat/FORWARD, not INPUT), so
DEPLOYMENT §2's "ufw inbound 22/80/443 only" does not contain any of it.

**FIX:** give `docker-compose.yml` `name: calevate-dev`, and refuse its presence in
`preflight()`. Independently, §2's hardening list needs the Docker/ufw caveat named.

### P5.8 — nginx config is installed BEFORE `nginx -t`, so a bad render survives on disk · SERIOUS · OURS

`vps-deploy.sh:535` installs the snippets and conf files, then runs `nginx -t`. If the test
fails the ERR trap stops the script — **with the broken files already in `/etc/nginx/conf.d/`**.
The running nginx is fine; the **next** reload is not, and those are triggered by Debian's daily
logrotate and by certbot's renewal hook. `deploy-failed.md:140` tells the operator "nothing was
reloaded — nginx keeps the previous config", which is true and misses the time bomb on disk.

**FIX:** back up the existing `.conf` set into staging, install, `nginx -t`, and
restore-then-fail on a bad test.

### P5.9 — Five variables the nginx step needs are checked at the very last step, and no human-facing document names them · SERIOUS · OURS

`render_nginx` requires `ROOT_DOMAIN`, `TLS_LIVE_DIR`, `ORIGIN_CERT_PATH`, `ORIGIN_KEY_PATH`
(`:489`). The script **never sources `.env`** and none is a `Settings` field, so they must be
exported in the operator's shell. The CD workflow supplies them from repo Variables; the human
first-deploy path has nothing. So §9's `--all` runs migrations, swaps three containers, does the
>2GB build — **and then dies on `ROOT_DOMAIN must be set`.**

Plus an undocumented chicken-and-egg: the config references `${TLS_LIVE_DIR}/fullchain.pem`,
`nginx -t` fails when a referenced certificate does not exist, and the ACME webroot location
certbot needs lives **inside that same file**. §9 step 5 lists "nginx render + certbot certonly"
in that order without resolving it.

**FIX:** move the five checks into `preflight()`, document the exports in §9 step 4, and add the
certificate bootstrap order (Cloudflare Origin CA cert first — it needs no ACME).

### P5.10 — `SENTRY_DSN` is a console field with no SDK behind it · SERIOUS · OURS

`core/observability.py:1021` guards `import sentry_sdk` with
`except ImportError: log.warning("sentry_dsn_set_but_sdk_missing")`. **`sentry-sdk` is not a
dependency of any package** — it appears in `pyproject.toml:130` only as a mypy override, and
**not once in `uv.lock`**. Meanwhile `sentry_dsn` is a real `Settings` field and the ops console
offers `sentry_` as a managed prefix. An operator sets the DSN on the go-live screen, sees it
accepted, and gets a log warning and no error reporting. DEPLOYMENT:594's "Sentry is hosted —
nothing to run on the VPS" reads as *configured* rather than *absent*.

**FIX:** add `sentry-sdk` to `apps/api` and `apps/workers` (**not** voice-runtime — hard rule 3),
or remove it from the console's managed set and say error reporting is unbuilt.

### P5.11 — The host backup alert path has no transport under the documented "simple shape" · SERIOUS · OURS

`infra/backup/README.md:189` offers the `postgres` user "either the repo's `.env` (simple shape)
or `/etc/calevate/alerts.env` (hardened)". **The simple shape cannot work**: `.env` is the
bootstrap eight and holds no `SMTP_*` and no `ALERTS_EMAIL` — those are console-managed, i.e. in
the database, and `host_alert.py:38` deliberately opens no DB connection. So under the
documented primary route the relay exits 78 (`EX_CONFIG`) forever.

Beyond the wrong doc: `SMTP_PASSWORD` must exist as a **second copy** on the database host,
outside the console DEPLOYMENT §6 calls the one place — and rotating it in the console silently
breaks the host relay. The external dead man covers a *failing* check; a healthy-backups /
broken-relay state pings normally and nobody learns until the night it is needed.

**FIX:** make `/etc/calevate/alerts.env` the only documented shape, and add "rotate
`SMTP_PASSWORD` in the console AND in `/etc/calevate/alerts.env`" to OPERATIONS §6.

### P5.12 — The restore-drill harness is unreachable and names a Makefile target that does not exist · SERIOUS · OURS (harness) / EXTERNAL (the real chain)

`docs/evidence/` contains no `restore-drill-*.md`, so OPERATIONS §8's "backups verified" is
un-tickable — which the docs say honestly. What this register did **not** record:
`scripts/restore_drill.py` (69KB, D-92, *"the executable half of
runbooks/backup-restore-drill.md"*) is wired to nothing.

- Its own usage block tells the reader to run a Makefile target named restore-drill.
  **There is no such target.** A committed file naming a command that does not exist.
- `runbooks/backup-restore-drill.md` never mentions `restore_drill` — zero hits. The runbook it
  is the executable half of does not know it exists.
- It is in no CI step and no `make check`.

So the one part of the backup design exercisable **without a cloud account** — whose whole point
is proving the verifier goes red — has, by the same reasoning this register applies to terraform,
almost certainly never run.

**FIX:** add the restore-drill target to the Makefile, cite it from the runbook, run it once,
commit the output.
Everything in `infra/backup/` §8 steps 1-11 remains genuinely EXTERNAL.

### P5.13 — `/healthz/ready` is called "the GO-LIVE GATE" and nothing polls it · SERIOUS · OURS

`core/health.py:7` names it the go-live gate and `runtime_config_missing_keys` is the
completeness check for nine credentials. `grep -rn "healthz/ready" scripts/ .github/ infra/
Makefile` returns **exactly one hit — a comment**. The deploy polls `/healthz`; compose polls
`/healthz/live`; OPERATIONS §8's checklist does not name it. The gate is a route nothing calls.

**FIX:** add `GET /healthz/ready` (with an `ops:manage` credential so the `fields[]` detail is
readable) as the last numbered item of §8's pre-launch checklist.

**Confirming P2.1 from the nginx side:** `calevate.conf.template:160` proxies both `= /healthz`
and `^~ /healthz/` on the **hooks** vhost. `hooks.` needs no health route at all — the deploy
polls `127.0.0.1:8100` and compose's healthcheck is in-container. **Deleting those two lines
removes the public path onto the vendor-adapter import entirely**, independent of the app-side
fix.

### P5.14 — A production role password is committed, and the production role/grant procedure is undocumented · SERIOUS · OURS

`05bba2f3c19c:593`, executed against the production cluster, does
`CREATE ROLE calevate_app LOGIN PASSWORD 'calevate_app'`. The comment says "staging/prod set it
from the secrets manager" and **nothing enforces it**; the `IF NOT EXISTS` guard makes this safe
only if a human created the role first. DEPLOYMENT §9 step 3 is one clause naming neither role,
neither attribute set, nor the owner role `ALEMBIC_DATABASE_URL` connects as, nor the
`GRANT ALL ON SCHEMA public` that CI shows is required.

Since Postgres is on the host and containers reach it over the docker bridge, `pg_hba.conf` must
admit that CIDR — and Docker's published ports bypass ufw (P5.7). A role whose password is in a
public repo is one hop away.

**FIX:** put the exact `CREATE ROLE`/`CREATE DATABASE`/`GRANT` sequence in §9 step 3 with
"generate both passwords from the secrets manager", and refuse startup when `DATABASE_URL`
carries the literal `calevate_app:calevate_app` outside `local`.

### P5.15 — Four irrecoverable-data points, and only two are guarded · SERIOUS · OURS

1. **Losing `PLATFORM_KEK`** — every console-stored credential becomes permanently
   undecryptable. Guarded **only by prose**; it is not in `BOOTSTRAP_REQUIRED` and not in
   `runtime_config_missing_keys`, so a deploy that never had it looks healthy. **Unguarded in
   code.**
2. **Losing the `age` identity** — every offsite dump unreadable. Guarded by a quarterly drill
   that has never run.
3. **`docker compose down -v` in the deploy directory** — P5.7. **Unguarded.**
4. **A short expiry on the recordings prefix** — guarded in four independent layers (DB CHECK,
   `RECORDING_FLOOR_DAYS` clamp, applier exit 2, terraform precondition). **Exemplary.**

Also: `runbooks/database-restore.md`'s "a restore un-erases" step depends on reading the
preserved pre-restore `PGDATA`. That is one `rm -rf` from making a DPDP erasure replay
impossible, and the runbook is the only thing forbidding it.

### P5.16 — Preconditions the deploy assumes and never verifies · SERIOUS · OURS

`preflight()` verifies: git/docker/curl/envsubst, compose v2, `compose.prod.yml` + `Dockerfile`,
`.env` present (mode 600 **warn only**), clean checkout, ≥3GB free, Cloudflare stamp <180d.

**Assumed and never checked:** redis container exists (P5.1) · `pnpm`/`pm2` installed (checked at
step 9 of 11) · `calevate-web` pm2 process exists (P5.4) · `apps/web/.env.local` (P5.5) · the five
nginx exports (P5.9) · `sudo` non-interactive · nginx installed and its dirs exist · TLS certs
exist · host Postgres reachable and roles exist (P5.14) · `PLATFORM_KEK` present and 32 bytes ·
`AWS_*` (P5.6) · **Postgres `max_connections ≥ 200`** — §2a's budget totals ~101 against a default
of 100 · **host has ≥4 vCPU** for `VOICE_RUNTIME_WORKERS=4`, which §2a says must never exceed
vCPU · 2GB swap (the `next build` OOM is `deploy-failed.md` §5's first cause).

### P5.17 — Silent-on-absence environment variables · SERIOUS · OURS

**Loud (process refuses, re-run inside the new image before any swap):** `APP_ENV`,
`DATABASE_URL`, `REDIS_URL`, `OBJECT_STORE_ENDPOINT`, `OBJECT_STORE_BUCKET`.
**Loud but late** (not in `BOOTSTRAP_REQUIRED`, dies at the migrate step): `ALEMBIC_DATABASE_URL`.
**Silent — deploy reports DEPLOYED:** `PLATFORM_KEK` (fails only at the first secret read) ·
`AWS_*` · `CALEVATE_IMAGE_TAG` · `API_WORKERS`/`VOICE_RUNTIME_WORKERS`/`*_DB_POOL_SIZE` (defaults
sized for ≥4 vCPU and `max_connections=200`; a smaller box silently oversubscribes both) · every
`NEXT_PUBLIC_*` · `ALERTS_EMAIL`/`SMTP_*` on the database host.
**Red on `/healthz/ready`, which nothing polls** (P5.13): the nine credentials.

### Checked and clean (ops/deploy)

**No secret is readable from a committed file** except the two named in P5.14 and P5.7. `.env`
is correctly untracked and excluded by both `.gitignore` and `.dockerignore`. Secrets-to-logs
discipline is good: `secret_routes.py:8` refuses a read-back route by construction,
`health.py:191` logs key NAMES only, and `vps-deploy.sh` prints no value anywhere. `preflight()`
re-runs `validate_bootstrap_env` **inside the new image** before any swap, which is the right
place. Swap order (workers → api → voice-runtime) correctly puts the only costly gap last, and
the webhook rate zone is sized for the post-gap catch-up. **The container swap does drop
in-flight webhooks and the docs are honest about it** — the 10-minute reconciliation tick absorbs
it, so leads appear late rather than never; note the gap is **unmeasured** and "a few seconds" is
a guess, and the 180s health wait can extend it well past the swap.

### Corrections to this register

1. **"`scripts/vps-deploy.sh` and `compose.prod.yml` exist and are complete"** — they are not.
   No way to start redis, no way to start web, no configuration source for the browser bundle,
   no object-store credentials. "Never run" was right; **"complete" is the claim that would have
   made the first deploy a surprise.**
2. **Section C is missing two rows of the terraform class:** the deploy artefacts have no CI gate
   of any kind, and `scripts/restore_drill.py` is reachable from nothing.
3. **Three operator-facing documents state a migration failure model the configuration does not
   implement** (P5.3) — not a gap in this register, a wrong fact in the three places an operator
   reads at 3am.

Minor drift, one commit each: `.env.example:86` says `OBJECT_STORE_*` are not in
`BOOTSTRAP_REQUIRED` (they have been since `settings.py:64`); `calevate.conf.template:12` lists
three substituted variables and the script substitutes five; `core/bootstrap.py:50` ships
`http://localhost:3000` in `DEFAULT_CORS_ORIGINS` unconditionally, including production.

---

## PART 6 — Workers, jobs and the reliability triad

**The cron register**, dumped from `settings.py` rather than read off the comments. `max_tries`
is **implicit (=1)** on six of ten crons, and `cron()` defaults it to 1 — confirmed in the
installed arq (`cron.py:143`):

| cron | interval | overlap prevented? | `max_tries` |
|---|---|---|---|
| `dispatch_outbox` | 10s | N/A — `FOR UPDATE SKIP LOCKED` + lease | **implicit 1** |
| `reconcile_executions` | 10min | incidentally (`job_timeout` < interval); no lease, no assertion | **implicit 1** |
| `report_stalled_pipeline` | :05,:35 | ≤300s < 30min | **implicit 1** |
| `dispatch_campaign_tick` | 30s | **YES** — Redis lease, TTL 330 > timeout 300 | implicit 1 (moot) |
| `sweep_expired` | daily | daily | **implicit 1** |
| `draw_qa_samples` | weekly | weekly | explicit 3 |
| `apply_retention` | daily | daily | **implicit 1** ← P6.2 |
| `sweep_engine_drift` | 30min | **YES — asserted at import** | explicit 3 |
| `sweep_kb_drift` | hourly | **YES — asserted at import** | explicit 3 |
| `issue_one_time_charges` | daily | daily | explicit 3 |

Unset and therefore arq defaults: `max_jobs=10`, **`job_completion_wait=0`** (P6.1), and
**`timezone=None`** — no `TZ` in the Dockerfile or compose, so every "nightly" cron above runs
**05:30–08:30 IST**, i.e. the retention sweep's bulk UPDATEs and S3 deletes land in Indian
business hours.

### P6.1 — The worker does not drain on SIGTERM; it hard-cancels, and three documents say otherwise · BLOCKER · OURS

`WorkerSettings` does not set `job_completion_wait`; arq's default `0` selects `handle_sig`
rather than `handle_sig_wait_for_completion`, which **cancels every in-flight job task in the
first millisecond of SIGTERM** (`arq/worker.py:852`). Three places state the opposite:
`compose.prod.yml:146` (*"give the current job a chance to finish"*, 60s grace),
`DEPLOYMENT.md:288` (*"in-flight work finishes instead of being killed"*), and
BACKEND-PATTERNS §10 (*"drain-then-quit shutdown"*). **The 60-second grace is handed to a
process that has already cancelled its work.**

At the container swap: the nine `FUNCTIONS` jobs requeue and burn one of three attempts —
recoverable. But **the six `max_tries=1` crons** requeue, then fail on pickup with
`job_try=2 > 1` → `JobExecutionFailed`, a `logger.warning`, and the job is dropped. Four
self-heal on their next tick. **`apply_retention` and `sweep_expired` do not — they are gone
until tomorrow, with no alert.** A deploy at 03:40 UTC silently skips the night's retention
sweep, which is a legal obligation.

**FIX:** set `job_completion_wait` under the 60s grace (e.g. 45), pinned by a test the way
`dispatch_tick_lease_test.py:235` pins `job_timeout < TICK_LEASE_TTL_S`.

### P6.2 — `apply_retention`: `max_tries=1`, no per-tenant isolation, no alert, 24-hour gap · BLOCKER · OURS

Three defects compounding on the cron that is a legal obligation. (1) `max_tries` defaults to 1
— the exact omission the same file argues against **four times** for its neighbours. (2)
`sweep_tenants` loops `await sweep_tenant(...)` with **no `try`**, so one tenant's error aborts
the sweep for **every tenant after it** — and `_due_tenants` has **no `ORDER BY`**, so which
tenants get swept is planner-dependent night to night. Its own sibling
`qa_sampling.draw_for_tenants` does this correctly and cites `sweep_tenants` as the pattern it
was split out to match. (3) The raise is not `arq.Retry`, so arq finishes it after one attempt
with a `logger.exception` and **nothing alerts**.

**FIX:** `max_tries=WORKER_MAX_TRIES`; wrap `sweep_tenant` in the try/except + failure counter
the sibling already uses; `ORDER BY tenant_id`; alert when the failure count is non-zero. Same
three apply to `sweep_expired` and `report_stalled_pipeline`'s unisolated loop.

### P6.3 — A blocking SMTP client on the worker's event loop, inside an open transaction · BLOCKER · OURS

The class D-159 fixed in `storage.py` is still live. `notifications.py:304` is an `async def`
that calls `get_transport().send(...)` — plain `smtplib.SMTP` with `starttls()` and `login()`,
15s timeout, **no `await`, no `to_thread`**. The `async def` makes the call site read as
deferred while doing nothing of the kind. It is called at `:118` **inside** the
`async with tenant_session(...)` opened at `:98`, so up to 15 seconds of synchronous socket I/O
holds an open Postgres transaction and a pooled connection **while stalling all 10 concurrent
arq jobs**.

The repo states the rule twice and violates it here: `transport.py:7` (*"callers on a latency
budget defer rather than adapt it"* — `alerting.py` defers, this does not) and `whatsapp.py:219`
(*"would park the loop … and stall every other job on the same worker"* — written about the
WhatsApp twin of this exact call, on the same lead, in the same transaction). That loop also
runs `dispatch_outbox` (10s) and `dispatch_campaign_tick` (30s), and hard rule 5's DNC deadline
is "before the next dispatch tick".

**FIX:** `await asyncio.to_thread(get_transport().send, ...)`, and move the send outside the
`tenant_session` block.

### P6.4 — D-31's guarantee of record does not cover the last three pipeline steps · BLOCKER · OURS

Direct answer to "does the pipeline recover from a crash at every step?" — **no.**
`_expected_artifacts` covers three things (`transcript`, `usage`, `extraction`);
`_post_call_stages` has **eight** steps. Steps 6–8 — hot-lead notification, campaign contact
resolution, and the **D-23 CRM fan-out** — all run *after* step 5's metering, each in its own
transaction.

So a pipeline that dies between step 5's commit and step 8 leaves `usage_events` written, which
makes `_pipeline_settled` return `settled` — and **the poller never re-drives it. The client's
CRM is never told about that call, and nothing records that it was not told.**
`report_stalled_pipeline` cannot see it either; `EXTRACTION_OWED_SQL` asks only about
extraction. The docstring's justification (*"a pipeline that reached metering reached the lead
upsert"*) is true of step 4, which precedes metering, and proves nothing about 6–8.

**FIX:** add a fourth artefact. `outbox_messages` already holds the durable proof and
`_already_enqueued` already knows how to ask: expect a `deliver_outbound_webhook` row matching
the call whenever `status == "completed"`.

### P6.5 — There is no ARQ DLQ, and three docstrings say there is · SERIOUS · OURS

`settings.py:6` promises every job *"lands in a DLQ with an alert on exhaustion"`;
`kb_reconciliation.py:381` and `billing.py:171` repeat it. **There is no such queue.** The only
DLQ is the outbox's `status='failed'`, which is fully wired — but that covers the *enqueue* leg,
not the *execution* leg. An ARQ job that exhausts its ladder is `zrem`'d off the queue, written
to a result key for an hour, and gone. **Nothing in `apps/` or `scripts/` reads an arq result
key, job status, or failed-job set.**

Six jobs compensate by alerting before giving up. **Three do not**: `sweep_engine_drift`,
`sweep_kb_drift` (whose docstring names the phantom console) and `draw_qa_samples` — so every
client's live agent can go unwatched with the console green.

Also missing: **nothing surfaces an erasure request that never completed.** `deletion_requests`
rows sit `completed_at IS NULL` forever with no cron, no alert, no ops query.
`report_stalled_pipeline` exists for calls; the DPDP equivalent does not.

**FIX:** correct the three docstrings; give the three sweeps the `attempt < WORKER_MAX_TRIES` /
else-alert shape the other six already use (copying, not designing); add an overdue-erasure probe.

### P6.6 — `execute_tenant_erasure` can exceed `job_timeout` and roll back the whole erasure, terminally · SERIOUS · OURS

It wraps the entire walk of a tenant's calls and leads in **one transaction**, and pages 500 at
a time with **one `list_objects_v2` round trip per call, serially** — 500 sequential S3 listings
per page, 10–25s per page, against `job_timeout=300`.

`retention.py:1200` argues this exact question and concludes *"if that stops being true the fix
is a resumable cursor ON THE REQUEST ROW, **not a budget that silently half-erases**"* — naming
the population as *"Indian SMBs with thousands of calls"*. **`job_timeout=300` IS that budget,
it already exists, and thousands of calls is exactly where it bites.** `TimeoutError` is not
`Retry`, so arq finishes after ONE attempt with no alert; the transaction rolls back,
`completed_at` stays NULL, and nothing re-drives it.

**FIX:** batch the prefix listings into one paginated walk per tenant (`keys_under` already
pages inside one thread hop), then either an explicit `timeout=` or the resumable cursor the
comment already names.

### P6.7 — `_already_enqueued` sequential-scans a never-pruned table, twice per call, under the per-call lock · SERIOUS · OURS

`outbox_messages` has exactly one index — `(status, created_at)` — nothing on `job`, no GIN on
`payload`. And **nothing anywhere deletes from it.** So every completed call runs two unindexed
containment scans over a permanently-growing table, once holding `lock_call_writes`, on the
2-minute SLO path, contending with `dispatch_outbox` every 10 seconds. `LIMIT 1` does not help:
the common case is "no prior enqueue", which is a full scan. `webhook_inbox_events` is likewise
never pruned.

**FIX:** replace the containment probe with the fact it stands in for (a `call_id` column, or a
`calls.crm_notified_at` guard), and add both tables to the retention sweep with a floor longer
than any re-drive window.

### P6.8 — `outbox_messages.queue` is written by six call sites and read by nothing · SERIOUS · OURS

`enqueue_outbox` takes and stores `queue=`; the column is NOT NULL; `claim_outbox_batch` selects
it. Then `dispatch_outbox` publishes **without it**, and `WorkerSettings` sets no `queue_name`,
so everything lands on arq's default queue. Callers pass `"notifications"` and `"default"`. **It
reads as routing and routes nothing** — the shape that would make an operator believe
notifications are isolated from CRM deliveries when they share one worker's ten slots.

**FIX:** honour it (`_queue_name=` plus a second `WorkerSettings` — a new deployable, so a
ROADMAP §6 entry) or delete it in a two-step deprecation. Do not leave it.

### P6.9 — The job-registration guard has two verified blind spots · SERIOUS · OURS

`_job_name_constants` reads only `ast.Assign`, so `TENANT_ERASURE_JOB: Final = "..."` — an
`AnnAssign` — **is not checked at all**. And the literal check inspects only `node.args[0]`,
while `enqueue_outbox`'s first positional is `session`, so it is **entirely inert for every
outbox call site**. Run against the tree: one missed constant, two invisible keyword literals.
All three name jobs that *are* registered, so there is no live outage — but the guard's own
docstring claims *"a literal that never became a constant is the one shape this file cannot
see"*, and it currently cannot see three more.

**FIX:** handle `AnnAssign`; check `node.keywords` for `job=`; promote the two literals.

### P6.10 — `presigned_url` is the last sync-boto3-on-the-loop call, and the comment excusing it is stale · SERIOUS · OURS

Every other function in `storage.py` is thread-hopped after D-159. `presigned_url` is not, and
is called from an `async def` route handler. Measured in this venv: `import boto3` 144ms, first
`boto3.client()` 95.7ms, subsequent ~12–15ms (there is no client cache) — so ~240ms on the event
loop for the first recording link after a deploy. `storage.py:325` still says *"The rest of this
module is still called synchronously from async code … moving them is a change to `retention`,
`outbound_webhooks` and two route modules at once."* **Those moves have happened; one call site
remains and the paragraph names four.**

**FIX:** make it `async` with `to_thread`, memoise `_client()` with a reset hook beside
`google_sheets.reset_caches`, and rewrite the stale paragraph.

### P6.11 — Minor · OURS

- **Outbound deliveries are unordered and nothing says so.** `max_jobs` unset → 10 concurrent,
  and a failed message's `locked_until` pushes it *behind* messages written later, so a client's
  CRM can receive `lead.updated` before `lead.created`. WEBHOOKS.md disclaims ordering for
  *inbound* Meta events and is silent on outbound. One sentence, or a per-(endpoint,subject)
  sequence number.
- `campaign_dispatch.py:150` claims `settings.py` asserts the lease/timeout relation at import.
  **It does not** — there is no `assert` in that file. The property is enforced by
  `dispatch_tick_lease_test.py:235`, which `settings.py:299` credits correctly. Two comments,
  one wrong.
- `deliver_outbound_webhook` parses its payload outside any failure policy, so a malformed
  payload raises `KeyError` — not `Retry` — and dies after one attempt with no alert. Both
  pipeline jobs solved this with a validation `ProblemError`; the delivery worker did not adopt
  it.
- `_copy_recording_once`'s re-drive guard reads the DB column, not the bucket, so a crash
  between the PUT and the UPDATE re-fetches from a vendor link that may have expired — on bytes
  we already hold. `recording_key` is a pure function of (tenant, call), so a `head_object` would
  answer. The docstring argues this exact scenario and stops one step short.

### Checked and clean (workers)

**All 24 `(ctx, …)`-shaped coroutines are accounted for** — 9 in `FUNCTIONS`, 10 crons, 4
lifecycle hooks, 1 wrapper. No unregistered job, no orphan enqueue point. **The outbox is
correct and completely wired**: committed attempt bump + lease, `MATERIALIZED` + total ordering
so LIMIT means limit, `_dead_letter_exhausted_claims` for claims that die without reporting, CAS
on every terminal write, systemic-vs-poison split, replay behind step-up, DLQ depth as a metric
and on the console. The auditor looked for a row that could be dispatched twice or lost and did
not find one. Idempotency and inbox both handle the abandoned-`PROCESSING` case by CAS, and a
payload-hash mismatch alerts rather than dedupes. `lock_call_writes` is taken before all three
read-then-writes it names. **The campaign claim is the best-built thing in the package** —
`MATERIALIZED` + `FOR UPDATE SKIP LOCKED`, status re-read inside the claiming transaction, claim
committed before the first dial, every dial its own transaction. Blocking-call sweep was
exhaustive: `time.sleep` only on alerting's own daemon thread and a non-async script; no
`requests`, no sync psycopg, no `subprocess`, no bare `open()` in `apps/`. The two real findings
are P6.3 and P6.10; nothing else.

---

## PART 7 — The frontend

**Two of this audit's findings independently reproduce P5.4 and P5.5** from the ops audit —
`pm2 reload` with nothing registered, and a browser bundle built with no browser variables.
Two agents reaching the same two blockers from opposite directions is the strongest signal in
this document after P1.2/P2.5. They are not repeated here.

### P7.1 — A *paused* query is neither loading nor failed, and six screens render its empty state as fact · SERIOUS · OURS

Measured against the installed library, not inferred. `queryObserver.js:310` computes
`isLoading = isPending && isFetching`, and `query.js:415` sets
`fetchStatus: canFetch(networkMode) ? "fetching" : "paused"`. `providers.tsx` sets no
`networkMode`, so the default `"online"` applies — and **nothing in `apps/web` reads `isPaused`,
`onlineManager` or `navigator.onLine`.**

So a console tab open when the network drops — which `client.ts:84` calls *"the normal case, not
an edge"* — then navigated to a screen with no cached data yields `isLoading === false`,
`error === null`, `data === undefined`. A two-arm ladder falls through to its data branch with
nothing. `isLoading` is also exactly the spelling that does **not** narrow `q.data`, and it
satisfies the §52 guard's gate; the guard says so itself: *"'Loading is a skeleton' is not
decidable here."*

Six screens each state something false: the client dashboard (**"No call history yet"**, **"No
calls yet"**), the call log (**"No calls yet"**), the client health board (**"Every client looks
healthy"**), the hold queue (**"Nobody is waiting on us"**), QA sampling (**"Every sampled call
has been reviewed"**) and quality reports. The two admin ones are sharpest: `admin/holds` itself
says *"'Nobody is waiting' is a claim about the world, and a failed read is not evidence for
it — an operator told the queue was clear because a token expired would stop looking."* The
error arm honours that; the paused arm walks past it into the sentence.

**FIX:** three characters per site — `q.isLoading || !q.data` — which is the spelling
`ConfigPanel`/`SecretsPanel` already use. Then teach the guard: this one IS syntactically
decidable.

### P7.2 — `Partial<WireType>` is a hole in the wire-fixture guard, and one live site hides a missing required field · SERIOUS · OURS

The guard resolves an assertion target to its declaring file and recurses through union members
and `getTypeArguments`. **`Partial<T>` is a mapped type**, so `getTypeArguments` returns `[]`,
its alias symbol is declared in `lib.es5.d.ts`, and `aliasTypeArguments` is never consulted.
`as Partial<Me>` and `as unknown as Partial<CallDetail>` pass. Three live sites, all in
`callDetail.test.tsx`.

And the defect is present behind one of them: the fixture at `:161` builds turns as
`{idx, speaker, text}` while **`TranscriptTurnOut.redacted` is required on the wire**. The turn
at `:241` includes it; the one at `:161` does not. Two spellings of one shape in one file, and
`pnpm -C apps/web typecheck` is green — verified.

**FIX:** walk `type.aliasTypeArguments`, add the mapped-type node forms to `targetsWireType`,
delete the three assertions, add `redacted` to the fixture, and add a `bannedPartialAssertion`
marker to the negative controls.

### P7.3 — nginx serves the admin console on the client hostname, so the realm-isolation premise is unenforced · SERIOUS · OURS

`calevate.conf.template:61` is a **single server block** for `admin.` and `app.`, with one
`location /` proxying everything. `clerkRuntime.tsx:29` reasons from the opposite premise:
*"disjoint route trees on disjoint hostnames … so only one realm's provider is ever mounted."*
In the shipped config they are not disjoint: `app.calevate.tech/admin` serves the operator
console and `admin.calevate.tech/c/<slug>` serves a client dashboard.

Not an authorization hole — the admin realm resolves against its own JWKS,
`assertMountedApplication` catches a provider mismatch, and cookies are per-key-suffixed. It is
an **unenforced premise** with one concrete consequence: **the operator sign-in surface is served
on the hostname clients are told to visit**, which is phishing surface for the console holding
cross-client data.

**FIX:** two server blocks; `location ^~ /admin { return 404; }` on `app.` and `^~ /c/` on
`admin.`. Then the docstring's sentence is a fact.

### P7.4 — Campaign launch is one click, and the server's own docstring assumes a confirmation the screen does not have · SERIOUS · OURS

Under "Everything checks out." sits a bare `<button onClick={() => launch.mutate()}>`. No second
step, no typed confirmation, no restatement of how many numbers are about to be dialled.
`campaigns/service.py:911` writes: *"the 'N contacts will be dialled' number **the client
confirms** is true."* **No client confirms anything.**

This is out of step with every comparable control: bulk lead edit is two-step plus type-the-count,
DPDP erasure types `ERASE`, the big red switch has a consequences panel plus typed reason plus
typed word, global DNC release types `RELEASE`. **Launching a campaign is the client action with
the largest irreversible blast radius in the product — it dials real Indian phone numbers under
TRAI — and it is the only one with no gate.**

**FIX:** reuse the `BulkActionBar` shape verbatim — a review step restating the dialable count,
the calling window and the number, then the danger button. Correct the server docstring either
way.

### P7.5 — The money dialog has no focus trap and never restores focus; 96 skeletons announce nothing · SERIOUS · OURS

Both are exactly what `a11y.ts:42` says the axe sweep cannot see. `KNOWN_A11Y_EXEMPTIONS` is
`{}` and `UNSWEPT_SCREENS` has one justified entry — both clean; these are outside their reach.

**(a)** `AcceptChargeDialog` — the one control that debits a wallet — moves focus on open and
handles Escape, and that is all. **No Tab cycling**, so the first Tab lands on the page behind
the `aria-modal="true"` panel; **no focus restore**, so Escape drops focus to `<body>`.
`navDrawer.tsx:143` is the repo's own APG implementation with cycling, Escape and restore, and
describes itself as *"the first"* focus-trap idiom. The money dialog is the second modal and did
not borrow it.

**(b)** `Skeleton` renders `<div aria-hidden>` with no `aria-busy`, no `role="status"`, and no
visually-hidden label anywhere in `src/` (zero `aria-busy` hits). Across **96 skeleton sites** a
screen-reader user gets nothing during every load and nothing when data arrives — the audible
equivalent of P7.1, on the audience `a11y.ts:16` names.

**FIX:** extract `navDrawer`'s trap into `useFocusTrap(ref, active)` and call it from both; give
`Skeleton` an `sr-only` label and `role="status"`.

### P7.6 — Minor · OURS

- **The team screen offers "remove" on your own row when it does not know who you are.**
  `myId = me.data?.user_id ?? null` with `me.error` unread, so on failure `isMe` is false for
  every row and the owner gets the role select and Remove on themselves. The API refuses it, so
  nothing is lost — the screen offers an action it cannot honour and then 403s.
- The client sidebar renders `—` for org and role with `me.error` unread — an honest absence
  marker, but permanent and unexplained. `TopHeader` and `HeldCount` both solved this with an
  amber badge naming the failure.
- **The homepage's scrollability depends on `:has()` and fails closed.** A browser without it
  gets the `overflow:hidden` pin and no override, so `/` is clipped at the fold. Tailwind v4's
  floor already excludes those browsers, which is why this is MINOR — but **the polarity is
  wrong**: default to `visible` and pin with `html:has([data-app-shell])`, so a `:has()` failure
  costs the app shell some rubber-banding rather than costing a stranger the homepage.
- Two API hooks have no caller anywhere (`useAgent`, `useVoiceCatalogue`), and `voices.ts:12`
  justifies the client-realm route as *"a client may HEAR what their agent sounds like"* — no
  client screen reads the catalogue, and the `Voice` schema carries **no sample or preview URL
  at all**, so the sentence describes a capability that is neither wired nor representable.
- `session.tsx:39` says a client typing `?view=admin` *"gets 401s, not a banner"*; since the
  branch was wrapped in `protect` they get redirected to `/admin/sign-in`.

### Checked and clean (frontend)

**All 34 routes are reachable — zero orphan routes**, enumerated with their entry points; the
half-wiring runs the other way (two hooks with no screen). All three type-aware guards have
empty `EXEMPT` lists with staleness assertions present. `KNOWN_A11Y_EXEMPTIONS` is `{}` and the
sweep reads routes off disk so it cannot fall behind the router. **Realm separation is intact in
code** — the two realm modules import each other never, their only shared module holds no
session, and `adminSession()` is built per call rather than read from context. **No dev-token
path is reachable in a production build** — two independent `NODE_ENV` guards, and the client
bundle's `NODE_ENV` is inlined at build so runtime env cannot re-open it. The `?? 0` / `|| 0`
sweep found **no optional-on-the-wire trap** in `src/`. Every irreversible action has a
confirmation **except campaign launch** (P7.4). The marketing homepage is readable with no JS —
prose is server-rendered and GSAP animates *from* a displaced state, so there is no `opacity:0`
resting rule to strand it.

---
---

# The fix sequence — what to do, in what order

All seven audits are in. **34 findings: 12 BLOCKER, 17 SERIOUS, plus the minors.** Nothing below
is scheduling; it is dependency order.

## Stage 1 — Make the deploy possible at all (nothing external) — **DONE**

Until these were done, a deploy could not succeed. All eight are closed.

| # | Fix | Part | State |
|---|---|---|---|
| 1 | Start `redis` as a first-class step, before the swap loop and without `--no-deps` | P5.1 | done |
| 2 | `apps/web/ecosystem.config.cjs`; `pm2 describe \|\| pm2 start` + `pm2 save` | P5.4 / P7 | done |
| 3 | Preflight `apps/web/.env.local`; fail a DEPLOY build on empty publishable keys | P5.5 / P7 | done |
| 4 | S3 client: explicit region, own session, cached; credentials named at readiness and in preflight | P5.6 / P6.11 | done |
| 5 | `scripts/bootstrap_admin.py` — **without it nobody can log in to the admin realm at all** | P4.1 | done |
| 6 | Run `scripts/seed.py` in the deploy's migrate step | P4.2 / P5.10 | done |
| 7 | Set `transaction_per_migration=True`; correct the three documents | P5.3 | done |
| 8 | Move the five nginx exports and the `pnpm`/`pm2` checks into `preflight()` | P5.9 / P5.4 | done |

**Three of the eight were not what the finding said they were, and the corrections matter
more than the fixes:**

- **P5.6's stated mechanism was wrong.** The finding claimed botocore raises `NoRegionError`
  at construction without `AWS_DEFAULT_REGION`. Measured: for **s3 specifically** it does
  not — it falls back to `us-east-1` and signs with it. So this was never a crash; it was
  every request signed under a region nobody chose, against a store (R2) that documents
  `auto`, with `SignatureDoesNotMatch` as the symptom and the region as the last place
  anyone would look. The credential half of the finding was real and worse: **every**
  object-store path fails `NoCredentialsError`, including `retention._erase_*`, where a
  store that will not answer stands between an erasure and a certificate claiming a
  deletion that did not happen.
- **A larger defect was in the same eight lines.** `_client()` used `boto3.client(...)`,
  which resolves through a process-global `DEFAULT_SESSION` — the exact defect D-106
  already found and fixed in `infra/object-lifecycle/apply_lifecycle.py`, in the copy that
  did not get the fix. It reproduced live during the sabotage check: with the global
  session restored, a test that had removed both credentials from the environment still
  presigned successfully, because an earlier test's key was cached in the shared session.
  It also rebuilt the session per call — ~90ms of botocore service-model loading, on the
  event loop, for every recording playback, since `presigned_url` is synchronous and
  called from an API route. Cached on a fingerprint of (endpoint, region, credentials):
  0.17ms, and a rotated key still yields a new client.
- **`.env.example` must NOT gain the three variables**, contrary to the fix as written.
  That file is the set a process needs to BOOT, and `tests/env_example_bootstrap_floor_test`
  asserts the exact eight-key list — correctly, since a credential-less process starts
  perfectly well and only fails at the first `put_object`. They belong to DEPLOYMENT §6
  tier 1 (the VPS `.env`), the deploy preflight, and `/healthz/ready`, which now names both
  outside `local`. `check_env_parity` gained an `SDK_ENV_KEYS` registry for the category
  the exemption actually is — a variable a third-party SDK resolves for itself, where a
  `Settings` field would be a validated value the library never consults.

P5.5's build gate is stated, not inferred: `CALEVATE_DEPLOY_BUILD=1`, set by
`vps-deploy.sh` and nothing else. CI builds this package as a compile check with no
environment at all, and that is a legitimate build — inferring the difference from what
happens to be set is the mistake D-49 exists for.

## Stage 2 — Do not lose money or break the law on day one

| # | Fix | Part | State |
|---|---|---|---|
| 9 | `charge_for_call` bills at the CLIENT rate, not our supplier cost | P1.1 | done |
| 10 | Alert + count completed calls with no usage row | P1.2 | done |
| 11 | `campaign_contacts` in both erasure paths, `status='dnc_blocked'`, counted in the proof | P3.1 | done |
| 12 | `spend_state.billed_inr` at the client rate; cap and client panel read it | P1.3 | done |
| 13 | `job_completion_wait`; `max_tries` on `apply_retention` + `sweep_expired`; per-tenant isolation | P6.1 / P6.2 | done |
| 14 | `await asyncio.to_thread` on the SMTP send | P6.3 | done |
| 15 | Fourth expected artefact so the poller re-drives the CRM fan-out | P6.4 | done |

**The money cluster (9, 10, 12) landed as one change, because it is one arithmetic.**
`billing/rates.py::client_billed_inr` is the single answer to "what does the CLIENT owe
for these minutes", reached from two call sites in the same transaction — the wallet
debit and the `spend_state` accrual — and `cost.total_inr` never appears in either again.
Migration `c4f18a6b90e2` adds `spend_state.billed_inr`; the compliance gate, the client's
cap route, the client usage panel and the admin health panel's cap utilisation all read
it, while `spend_used` stays exactly where the margin panel needs it. Both writes are
sabotage-verified, and so is the third writer nothing else could see: swapping
`_RECOMPUTE_CAPPED` back to `spend_used` passed every existing test, because their
fixtures put both numbers on the same side of the ceiling — `tests/client_rate_billing_test.py`
now puts the cap between them.

**Three decisions inside it are worth carrying forward, because each was a fork:**

- **A managed tenant with no quoted rate accrues NOTHING**, and the platform list price
  is deliberately not substituted. It was, briefly, on the argument that an absent
  `plans` row is the common state and a client's own cap needs something to bite on.
  That loses to `b1d5c8e73f04`'s settled rule — this repository does not invent a price
  a plan does not quote — because the same rate prices the panel, the cap AND the
  invoice, and a counter accruing ₹6/min beside an invoice charging ₹0 is two documents
  about one month. `warn_no_plan_in_effect` is what makes the missing plan visible.
- **The included allowance is netted off, per month rather than per call.** The meter
  computes `over(minutes_before + minutes) - over(minutes_before)` under the lock it
  already holds, so the increment is exact and independent of the order calls meter in.
  A client's retainer minutes accrue nothing towards their own cap, which is what the
  invoice will say too.
- **`_spend_used`'s closed-month branch changed as well**, and it had the same defect: it
  summed `unit_cost_paid` from the ledger, which is our supplier cost re-derived. It now
  takes the caller's client-side figure — list rate x minutes for a prepaid tier, the
  invoice's own `overage_cost` for a managed one — so the panel and the statement cannot
  disagree by a paisa.

**P3.1 — the erasure half is closed; the retention half is external and now probed.**
`_erase_campaign_contacts` is one statement with two callers, so the per-subject and
tenant-wide paths cannot drift about what an erasure does to an uploaded contact list. It
anonymizes the number per row (the unique index on `(campaign_id, phone_e164)` makes a
constant unusable), clears `name`, clears the `custom` blob that holds every column the
client pasted, and sets `status='dnc_blocked'`.

**The status is the load-bearing part, and the finding is right that it is not a records
gap.** The campaign dispatcher reads `status`, not the number, so anonymizing alone would
have left the row perfectly dialable — we would have rung a person whose certificate says
they were removed. `dnc_blocked` is the status the compliance gate's own refusal already
writes, so a settled campaign reports the row exactly as it reports one the DNC list
stopped and no reader needs a new state.

**One thing the finding did not name: `dedupe_hash`.** It holds `sha256(phone)[:16]`,
unsalted, over an Indian mobile E.164 space of ~10^9 — enumerable in seconds. Leaving it
is leaving the number in a form that reverses, so it is cleared too.

Both certificates carry the count: a sentence in the per-subject proof's `actions`, and a
first-class `campaign_contacts_erased` on the tenant certificate's `scope` — the whitelist
`_SCOPE_COUNTS` and the `extra="forbid"` response model both, because a count the worker
records and the renderer does not name is a count nobody ever sees.

**The RETENTION half stays open and is now recorded with a probe.**
`retention_policies.data_category` is CHECK-constrained to four categories, none of which
an uploaded contact list fits, so with no erasure request the list is kept indefinitely —
a DPDP §8(7) storage-limitation exposure erring in the dangerous direction. The period is
a DPA commitment to the client rather than an engineering default, so it is a third entry
in `tests/dpdp_known_gaps_test.py`, whose probe reads the live constraint and whose
equality assertion forces the entry's deletion on the day it is widened.

**The worker quartet (13, 14, 15) shares one failure shape: each produced LESS output
rather than a red job.** A healthy fleet and a broken one looked the same from outside.

- **P6.1** turned on one keyword's truthiness. arq picks its signal handler with
  `if self._job_completion_wait:` — `0` installs the hard cancel — so `compose.prod.yml`'s
  60-second grace, DEPLOYMENT §4b's "in-flight work finishes" and BACKEND-PATTERNS §10's
  "drain-then-quit" were all describing a process that had already thrown its work away.
  45s, strictly under the grace because that grace ends in SIGKILL, and the headroom
  covers the shutdown hooks that run after the drain returns.
- **P6.2** got all three halves plus one the finding did not separate out. `max_tries`
  now reaches `apply_retention`, `sweep_expired` AND `report_stalled_pipeline` — the last
  self-heals in 30 minutes but is the ALARM, and an alarm that gives up on its first
  transient error is silent for exactly as long as the incident it reports.
  `sweep_tenants` and `report_stalled_pipeline` isolate per tenant with a counter, both
  tenant lists gained `ORDER BY tenant_id`, and `apply_retention` alerts on a non-zero
  failure count. **The stall alarm was the quietest of the lot**: it fires on a total, so
  an aborted sweep produced a smaller number and read exactly like a healthy fleet — it
  now reports the tenants it could not probe and fires on that alone.
- **P6.3 was taken half-way, deliberately.** The `to_thread` is in; the send is NOT moved
  out of the `tenant_session`, and the reason is the atomicity the surrounding code argues
  for at length: the delivery record and the WhatsApp enqueue must land together, and the
  dedupe check at the top of that transaction is what stops two concurrent runs both
  sending. What the open transaction costs is one pooled connection out of sixteen, with
  no row lock held, for the length of the send. What it used to cost was the event loop —
  every job in the process, including the campaign tick hard rule 5's DNC deadline is
  defined against. Those are not the same order of problem.
- **P6.4** needed a second column, not just a fourth artefact.
  `integrations.enqueue_events` writes one outbox row per SUBSCRIBED ACTIVE endpoint and
  returns 0 when there are none — which is most tenants — so expecting `crm_fanout`
  unconditionally would have re-driven every call on every tick forever, including a
  billed extraction. `crm_fanout_owed` mirrors that endpoint predicate. The probe matches
  the same outbox row `_already_enqueued` writes, by the same job name and the same `@>`
  containment, because two spellings of one question is how a probe and a writer stop
  agreeing.

P1.2's alert is on `snapshot.billable_ready and snapshot.cost is None`, which is the
discriminator that makes it signal rather than noise: a snapshot that is not YET billable
has no cost because the vendor is still settling, and the poller will come back for it.
One the adapter has declared billable and cannot price is the adapter and the vendor
disagreeing about the payload, and no amount of waiting fixes that. The Bolna adapter
also logs its own refusal now, and `calls_unmetered` is a sixth signal on the admin
client-health board — `stop` severity, because these calls are already billed to us, are
invisible to every client-facing figure, and `_pipeline_settled` has already called them
settled so nothing will come back for them. Its grace is the poller's own
`PIPELINE_STALL_AFTER`, imported rather than restated.

## Stage 3 — Close the things that mislead an operator

| # | Fix | Part | State |
|---|---|---|---|
| 16 | The three DLQ docstrings say what actually happens; the three drift sweeps get the ladder the other six have; an overdue-erasure probe exists | P6.5 | done |
| 17 | `response.json()` and `httpx.URL(candidate)` guarded, plus a scan over the whole engine layer | P2.2 / P2.3 | done |
| 18 | Rollback, dev compose file, nginx install-before-test, restore drill, the two `/healthz/` lines | P5.2 / P5.7 / P5.8 / P5.12 / P5.13 + P2.1 | in flight |
| 19 | Disclosure | P3.3 | open |
| 20 | Paused queries, campaign launch confirmation | P7.1 / P7.4 | in flight |

**P6.5 was three findings wearing one number, and the third is the one with a statute
behind it.**

- **There is no arq DLQ, and four docstrings promised one.** An exhausted job is `zrem`'d
  off the queue and written to a result key nothing in `apps/` or `scripts/` reads. The
  only dead-letter queue in this repository is the outbox's `status='failed'`, which
  covers the ENQUEUE leg and not the execution leg — so for a job that fails while
  RUNNING, the last attempt's `alert()` is the dead-letter mechanism, and a job without
  one fails in silence. `workers/settings.py`, `billing.py` and the three drift sweeps now
  say that.
- **The three drift sweeps had no last-attempt alert**, while their six neighbours did.
  `qa_sampling`, `kb_reconciliation` and `engine_reconciliation` now carry the same
  `attempt < WORKER_MAX_TRIES: raise Retry(...)` / else `alert(...)` and raise — copied
  from `issue_one_time_charges` rather than designed, because a second shape for one
  problem is how the two stop agreeing. Two of their existing tests ENCODED the defect
  (asserting `Retry` still on the last attempt) and were rewritten.
- **Nothing watched `deletion_requests`.** Rows sat `completed_at IS NULL` forever with no
  cron, no alert and no ops query — `report_stalled_pipeline` had existed for months for
  calls, whose worst case is a lead a client did not see, while the one workflow with a
  DPDP §12 right behind it had no equivalent. `report_overdue_erasures` is that
  equivalent, hourly, with the ladder its neighbours have.

**Two things about the probe are not obvious and both were arrived at by being wrong
first.** Its bound is DERIVED and is not a legal deadline — SECURITY-COMPLIANCE §4 states
no figure, so inventing one in a constant would put a commitment in the code that nobody
made; an hour is the outer bound of every mechanism on the path (one transaction, a
10-second dispatcher, a ladder measured in tens of seconds), which makes a request still
open at it one that never ran rather than one running slowly. And it walks
ORGANIZATIONS, not `_callable_tenants()`: that list is `SELECT DISTINCT tenant_id FROM
engine_agent_routes` — tenants with a PUBLISHED AGENT — so a client who never went live and
a churned client whose routes `tenant_erasure` tore down are both outside it. Those are
precisely the tenants most likely to be holding a forgotten erasure, and reusing the list
would have produced an alarm that reads green exactly where it is needed. It reads that
directory under `admin_session`, because the first attempt used `untenanted_session` and
returned ZERO tenants on a real database: `organizations` carries its own FORCEd policy, so
the sweep would have walked an empty fleet and reported a healthy one forever.

**P2.2 and P2.3 are one mistake in two spellings: an exception type in no `except` clause
on the path.** `json.JSONDecodeError` is a `ValueError` — not a `ProblemError`, not an
`httpx.HTTPError` — so a 2xx with a non-JSON body (a WAF challenge, a proxy interstitial)
reached `create_agent` as a raw 500 and DLQ'd both the pipeline and the poller.
`httpx.InvalidURL`'s MRO does not include `httpx.HTTPError` either, so `_next_link` could
not have been caught even inside `_request`'s handler. Both are now measured rather than
assumed — `tests/adapter_escaping_exception_test.py` pins both MRO facts, so the day a
library change makes either comment false, a test says so instead of a paragraph quietly
going stale.

**The structural test is the one that matters here.** This repository had ALREADY solved
P2.2 twice — in `billing/payments.py` and in `engine/cartesia.py` — before the adapter
actually going to production missed it. A defect that recurs across three modules is not
one a per-instance test can hold, so the suite AST-scans every file in `apps/api/engine/`
for a `.json()` outside any `try`, including the adapters that do not exist yet.

## Stage 4 — Guards, drift and the rest

P4.3 (seven unmapped columns), P4.5/P4.6 (registry and docstring counts), P6.9/P7.2 (the two
holed guards), P2.6, P6.7, P6.8, P6.10, P7.3, P7.5, and every MINOR.

## Stage 5 — Only after an account exists

Gates 1–14, per Section A. Nothing in Stages 1–4 waits on any of them.

---

## What this audit changed about the earlier register

Three claims above were wrong and are corrected in place: the deploy scripts are **not**
"complete" (P5); "billing and invoicing" is **not** safely shipped (P1); and the closing claim
that the remaining gap is "almost entirely accounts, registrations and one never-executed
deploy — not code" is **wrong by the whole of Stage 1**. The shape of that claim was right —
there is no large engineering effort left — but the specific work in Stage 1 is small, ours, and
absolutely blocking.
