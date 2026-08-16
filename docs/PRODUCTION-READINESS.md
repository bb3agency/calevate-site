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
