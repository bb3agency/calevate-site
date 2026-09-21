# Can this system answer EVERY inbound call, simultaneously, and never miss one?

Read-only audit, 21 Sep 2026, against the founder's core inbound value proposition:

> *"A clinic has one number and one receptionist, so only one caller gets through at a
> time. Calevate answers EVERY inbound call, simultaneously, and never misses one."*

Scope is **our own stack only** — the carrier's concurrency is out of scope by assignment
and is already covered by `docs/evidence/carrier-pricing-concurrency-2026-09-17.md`. The
brief said *assume it cannot and try to prove it*, and that is what this is.

**Evidence discipline (hard rule 11).** Every claim about OUR code is a `file:line` opened
this session. Vendor claims carry their class and their source; where the source is a
figure already sitting in this tree, it is labelled with the class that figure carries,
not re-stated as fact. Nothing here was measured against a live system, because there is
no live system to measure (finding 0). No host was reachable from this container.

---

## ANSWER FIRST: NO. THE CLAIM IS NOT DELIVERABLE TODAY, AND IT IS NOT CLOSE.

Four independent findings, each of which alone breaks the sentence. They are ordered by
how early they bite, not by severity.

| # | Ceiling | Number | Class |
|---|---|---|---|
| 0 | Calls answered simultaneously today | **0** — nothing is deployed, `pcc-deploy.toml` has never been applied, `PIPECAT_STREAM_BASE_URL` is unset | VERIFIED (this tree) |
| 1 | Calls one worker container answers | **1**, hard-coded | VERIFIED (`boot.py:193`) |
| 2 | Calls served without a ~10 s cold start | **1**, `min_agents = 1` | VERIFIED (config) + REPORTED (cold-start figure) |
| 3 | Simultaneous Cartesia/Studio calls before a 429 with no queue | **~3 units on Pro / ~5 on Startup**; vendor rule of thumb ≈4 conversations per unit, explicitly labelled a rule of thumb | REPORTED (concurrency table), VENDOR-PUBLISHED (429-no-queue behaviour) |
| 4 | Record of a call we failed to answer | **none — no row, no event, no alert, anywhere** | VERIFIED |

Finding 4 is the one to tell the founder first. **"We never miss a call" is currently
unfalsifiable in our own system: a call we fail to answer leaves no trace at all.** Not a
row, not a counter, not an alert. We could be dropping half the calls to a clinic and
neither we nor the client would be able to tell — the only record would be the clinic's
own carrier bill, which nobody on our side reads.

The honest version of the sentence today is: *"Calevate is built to answer many calls at
once. It has never answered one."*

---

## 0. THERE IS NO DEPLOYED INBOUND PATH AT ALL — **VERIFIED**

Before any concurrency number means anything: **no real call has ever been placed on this
product**, and the container that would answer one has never been deployed.

* `apps/voice-worker/pcc-deploy.toml:3` — *"⚠ THIS FILE HAS STILL NEVER BEEN APPLIED."*
* `apps/voice-runtime/carrier_routes.py:500-524` — `_stream_base_url()` raises
  `carrier_stream_base_not_configured` (502) when `PIPECAT_STREAM_BASE_URL` is unset,
  because it *"is the address of a deployment that does not exist yet (BLOCKER-1)"*.
  Until that variable holds a value, **every answer document request is refused** and no
  call reaches a worker, concurrently or otherwise.
* `docs/PIPECAT-MIGRATION.md:344` (§6 step 6) — *"THE TRANSPORT LANDED 15 Sep 2026; THE
  CALL HAS NOT HAPPENED, AND THOSE ARE NOT THE SAME CLAIM… Step 6 is DONE when a real call
  has happened, and it has not."*

What remains is configuration and an external account (a Plivo account in the India data
region, BLOCKER-1), not engineering. But the claim being sold is a claim about a running
system, and there is no running system. Everything below is therefore about what the code
WOULD do, which is the useful question, but it must not be reported as measured behaviour.

---

## 1. CONCURRENCY INSIDE OUR OWN SYSTEM

### 1a. What serialises N simultaneous calls? — **the worker container, absolutely**

`MAX_CONCURRENT_SESSIONS: Final[int] = 1` (`apps/voice-worker/voice_worker/boot.py:193`).

One call per container, enforced at admission:

* `apps/voice-worker/voice_worker/lifecycle.py:180` — `elif in_flight >= self._capacity:
  state = "busy"`, and `busy` is not `ready`.
* `lifecycle.py:200-214` — `reserve()` raises `AtCapacityError` when the registry is not
  ready. The docstring is explicit that this is *"the admission decision"*.
* `apps/voice-worker/bot.py:259` — `registry.reserve(call_id)` is called **before any IO**,
  before the transport and before the session read.
* `lifecycle.py:57-64` — `AtCapacityError` is *"RAISED rather than queued. A queued call is
  a caller listening to silence… the platform — which owns the scheduling — can put the
  session on another instance."*

**So the answer to "what serialises them" is: nothing in our code multiplexes them, and
everything depends on the platform starting one container per call.** The constant's own
comment says the 1 is not our choice — *"1 session per instance; max pool 50"*
(`boot.py:187-193`, citing `docs/evidence/engine-replacement-comet-2026-09-06.md:122`,
which that comment itself downgrades to **REPORTED** from this container's seat).

⚠ **The whole simultaneity claim therefore rests on a vendor scheduling behaviour nobody
here has observed.** It is a reasonable design; it is not a verified one.

### 1b. `carrier_routes.py` — **per-call stateless, and provably so. CLEAN.**

This is the one piece of the inbound path that is unambiguously good news.

* `apps/voice-runtime/carrier_routes.py:565-663` — `plivo_answer()` performs **no IO**: it
  verifies the source, parses the ref, reads already-buffered request parameters, renders
  two XML elements and returns.
* The module holds no mutable state. Every module-level binding is a `Final` constant or a
  frozen dataclass (`:146-270`).
* `:97-107` — the absence of IO is *asserted by test* rather than promised:
  `tests/voice_runtime_carrier_answer_test.py` is what holds it, and it is the reason the
  route carries no ack-latency meter.
* `:22` — it reads **no database row** to decide whose call it is (hard rule 1, D-603).

**Verdict: N simultaneous answer-document fetches contend for nothing.** This route will
not be the bottleneck. Note in passing (not a concurrency finding, but it is on this path):
`verify_answer_source` currently returns `ok=True, method="none"` because the carrier's
egress ranges are unknown (`:394-402`), so the route is unauthenticated by design with the
reasoning written out.

### 1c. `apps/voice-worker/` — **one container per call, and only one is warm**

`pcc-deploy.toml:72` — `min_agents = 1`.

The file's own comment is the finding, and it argues against itself:

> *"Zero would mean scale-to-zero, whose documented cold start is about 10 seconds… that
> is a business's phone ringing for ten seconds before anything answers, which that same
> line calls 'not usable for inbound'… One instance carries one session, so concurrency
> and this number are the same number."* (`pcc-deploy.toml:57-71`)

**The config reserves exactly one warm slot.** Caller #1 is answered warm. Caller #2
arriving simultaneously needs a *second* container, which by the same document's own
reasoning is a cold start of roughly ten seconds — the exact experience that comment calls
"not usable for inbound".

* **VERIFIED (vendor source, readable here):** the ceiling above `min_agents` is not
  unbounded. `max_agents` is a real key we do not set, and the installed vendor CLI's help
  text reads *"Maximum number of allowed agents (default cap 50, contact support to
  raise)"* — `pipecatcloud==1.2.0`,
  `_utils/deploy_utils.py:269-286` and `cli/commands/deploy.py:645-651`, read from the uv
  cache this session. So the platform does autoscale past the warm floor, up to 50.
* **REPORTED, not verified:** the ~10 s cold-start figure
  (`docs/evidence/engine-replacement-comet-2026-09-06.md:93,122` — a founder research run
  over an undated vendor pricing page; `docs.pipecat.ai` is egress-blocked here).
* **REASONED, and labelled as such:** that caller #2 specifically pays that cold start. The
  cold-start figure is documented for scale-to-zero; that the 1→2 scale-up uses the same
  mechanism is an inference from the same scaling knob, not a measurement. **This is
  gate-57-class and must be measured on the live system** (§5, T-2).

Nothing in our code queues, buffers or holds caller #2 while this happens. The worker
refuses (`AtCapacityError`) and the platform reschedules — or does not.

### 1d. Per-tenant or per-agent concurrency cap in our code? — **NO, and one lookalike**

Searched `concurrency`, `max_calls`, `semaphore`, `limit`, `pool` across `apps/`,
`packages/`, `scripts/`. Findings:

* **There is no inbound per-agent or per-tenant cap, deliberately.**
  `apps/api/agents/lifecycle.py:53` — *"WHAT THIS MODULE DELIBERATELY DOES NOT ADD: a
  per-agent concurrency knob."*
  `apps/api/agents/schemas.py:92-98` — *"Inbound concurrency is a per-number binding at the
  engine and the vendor documents no inbound limit, so a live agent bound to three numbers
  picks up three simultaneous calls."*
* `plans.concurrency_ceiling` (`apps/api/admin/routes.py:2784`, default 10) and
  `campaign_dispatch._tenant_ceiling` are **OUTBOUND ONLY**. They bound campaign dialling.
* `apps/workers/campaign_dispatch.py:182-183` — `PLATFORM_LINES_TOTAL = 10`,
  `MIN_INBOUND_RESERVE = 4`. This is the closest thing in the tree to a platform sizing
  assumption, and it is worth reading as one: **the whole platform is sized at ten lines,
  of which four are reserved for inbound.** That reserve protects inbound from outbound; it
  does not cap inbound. It is also written against the *rented* Bolna engine, not the
  owned-runtime path this audit is about.

**`Settings.cartesia_agent_cap` — what it caps, and whether it bites here.**
`packages/shared/src/calevate_shared/config.py:1010` — `default=2`.

It caps **LIVE AGENTS on the Cartesia voice tier, platform-wide, across every tenant** —
not concurrent calls. `apps/api/agents/voice_offer.py:445` reads it;
`count_live_cartesia_agents` (`voice_offer.py:574-612`) is the measurement, a directory
read plus one count per tenant.

**Does it bite on the inbound claim? Not directly — and that is the problem.** It is
enforced at *voice selection time*, so it stops the third clinic being CONFIGURED with a
Cartesia voice. It does nothing at call time. Its docstring explains why it exists, and
that reason IS a concurrency ceiling — see finding 2a.

### 1e. The database pool — **17 connections, 5 s wait, and a depth-2 multiplier**

* `packages/shared/src/calevate_shared/config.py:280` — `db_pool_size: int = 16`.
* `apps/api/db/session.py:453` — `max_overflow = MAX_NESTED_CONNECTIONS - 1` = **1**.
* `apps/api/db/session.py:122` — `MAX_NESTED_CONNECTIONS = 2`.
* `apps/api/db/session.py:54` — `_POOL_TIMEOUT_S = 5.0`.

So: **17 connections per API process, and a caller past them QUEUES for up to 5 seconds and
then fails.** `session.py:400-406` states this deliberately — the queue is an
`asyncio.Queue` inside the pool, chosen over a connection storm, and *"waiting 30 seconds
for a connection is not a slow request, it is a request that should already have failed"*.

**The `check_session_nesting` gate is real but is NOT the binding constraint here, and the
brief's hypothesis that it might be does not hold.** `scripts/check_session_nesting.py:60`
and `session.py:408-435` are about how many connections ONE task may hold — 2 — which is a
depth limit, not a call limit. Its effect on concurrency is a multiplier: because **every
route handler structurally holds two** (`session.py:414-421`, *"EVERY route handler…
anything the handler calls that reads a global table is a second connection held inside the
first"*), the effective ceiling is roughly **8 simultaneous in-flight API requests per
process**, not 17.

**Does that bite at N simultaneous calls? Almost certainly not, and here is the arithmetic
the repo itself supplies.** `apps/api/core/ratelimit.py:178-195` states that *"one live
call costs roughly seven requests a minute (an 8-turn batch every 10s, plus the session
read and the settlement)"*. Seven requests a *minute* per call, each holding a connection
for milliseconds, is not a sustained checkout. Ten simultaneous calls is ~70 requests/min
against a pool that the same file sizes for far more.

**Two caveats worth recording rather than dismissing:**
1. The calls are **not independent in time**. Ten calls that all start at the same instant
   all do their session read at the same instant. The burst, not the average, is what meets
   the pool — and nothing in our code staggers it.
2. `_POOL_TIMEOUT_S = 5.0` on a path where the caller is a human listening to a ringing
   phone means a pool-starved session read is a **5-second silence before the greeting**.
   No code path shortens that bound for the in-call leg.

Neither is measured. Both are T-4 in §5.

### 1f. Rate limit on our own API — **600/min, about 85 concurrent calls**

`apps/api/core/ratelimit.py:195` — `"worker_api": LimitProfile(per_client=600,
per_tenant=None)`.

This is a real, documented number in our own code, and its comment (`:178-194`) does the
arithmetic: at ~7 requests/min per live call, 600/min is *"about 85 concurrent calls of
headroom"*. It also names the consequence of breaching it, which is worse than a retry:

> *"a dropped SETTLEMENT is the only producer of the post-call outbox row on this engine,
> and there is no poller behind it, so it loses that call's extraction, CRM columns and
> lead permanently."*

⚠ **One unverified premise inside that number.** The profile is keyed **per caller
address**, and the comment assumes the worker fleet presents as one caller (*"a container
on Pipecat Cloud serving EVERY tenant from whatever egress address the platform gives
it"*). If Pipecat Cloud gives each container its own egress address, this limit is
effectively per-call and never binds. If it gives them one shared address, 85 is real.
**UNKNOWN — `docs.pipecat.ai` is egress-blocked from this container**, and no reading of
the platform's egress behaviour exists in this tree.

### 1g. Global locks on the in-call path — **CLEAN, checked rather than assumed**

The one global lock in this tree is `audit:chain` (`apps/api/compliance/audit.py:81`),
which serialises every audit write platform-wide. It does **not** sit on the call path:
`grep write_audit apps/api/worker/*.py` returns nothing, and neither
`apps/voice-runtime/tool_routes.py` nor `apps/api/worker/tools.py` takes an advisory lock,
a row lock or `FOR UPDATE`. The in-call tool endpoints (opt-out, callback, cancel, handoff)
take no lock.

`docs/evidence/deepdive-concurrency.md` is the prior pass over `apps/api` and
`apps/workers`; nothing it left open bears on the inbound path.

---

## 2. VENDOR CEILINGS ALREADY RECORDED IN THIS REPO

### 2a. Cartesia (the **Studio** rung) — **THE LOWEST VENDOR CEILING, AND IT IS DEAD AIR**

| Plan | TTS concurrency units | Class |
|---|---|---|
| Free | 2 | REPORTED |
| Pro | **3** | VENDOR-PUBLISHED for the fee; **REPORTED** for the concurrency figure |
| Startup | **5** | REPORTED |
| Scale | 15 | REPORTED |

Source: `apps/api/billing/rates.py:1788,1800` (`tts_concurrency=3` / `=5`), whose own field
comment at `:1643-1650` stamps the class explicitly — **"EVIDENCE CLASS: REPORTED — the
research run's concurrency table… the Tinmaz correspondence does not mention concurrency."**
The underlying table is `docs/evidence/cartesia-tts-verification-2026-09-06.md:132-138`.

**What happens at the ceiling is the finding, and it is VENDOR-PUBLISHED:**

> *"this cap protects a monthly plan whose concurrency ceiling returns **429 with no
> queueing** — dead air on a live call — rather than an overage line on an invoice"*
> — `apps/api/agents/voice_offer.py:593-598`, citing `docs.cartesia.ai` concurrency docs
> read 7 Sep 2026 and relayed.

**Would it bind at ten simultaneous calls?** The vendor's own rule of thumb is ~4 parallel
conversations per concurrency unit, and the vendor labels it a rule of thumb
(`cartesia-tts-verification-2026-09-06.md:142`). On that heuristic, 10 lines needs ~3 units
— Pro is *borderline*, Startup covers it. The repo's own conclusion, at
`apps/api/billing/rates.py:1563-1566`, is blunter:

> *"a self-serve plan below Scale is 'a dead-air incident waiting for a busy morning'. A 429
> has no queue."*

**I will not convert that into a number.** The unit is *unique `context_id`*, not call and
not utterance (`cartesia-tts-verification-2026-09-06.md:144`), so how many contexts one
conversation opens is a property of our pipeline that nobody has measured. OPERATIONS §2
gate 53 exists for exactly this and says so: *"THE NUMBER THAT SETS THE AVAILABILITY CAP,
AND IT MUST BE MEASURED RATHER THAN REASONED."*

⚠ **And note what the ceiling is NOT protected by.** `cartesia_agent_cap` defaults to 2,
which stops a third clinic being configured — but it caps AGENTS, not CALLS. **One clinic,
one agent, four simultaneous callers on a Pro plan is already past 3 units** if each
conversation holds one context, and the cap does nothing about it.

### 2b. Gnani (the **Clear** rung) — **60 requests/minute, scope UNKNOWN**

`apps/api/agents/gnani_voices.py:38-52`:

> *"Gnani's own console states ₹27.00 per 10,000 characters for Text to Speech, with a 60
> requests/minute limit (`app.gnani.ai/voice/pricing`, read by the founder and relayed —
> VENDOR-PUBLISHED)… **The 60 requests/minute limit is a CONCURRENCY ceiling and nobody has
> costed it.** One synthesis request per assistant turn puts a hard cap on simultaneous
> calls on this rung, independent of price. **UNKNOWN whether the limit is per key, per
> account or per model** — the page states the number and not its scope."*

**Would 60 RPM bind at ten simultaneous calls? The repo has already done this arithmetic
and the answer is: yes, plausibly, and it is question one.**
`docs/evidence/gnani-evaluation-2026-09-06.md:61-71`:

> *"at 360-540 chars/min and an utterance of roughly 100 characters, one call issues 3.6-5.4
> agent utterances a minute, so ten lines issue **36-54 requests a minute against a printed
> cap of 60** — 60-90% consumed at STEADY STATE, before the ~4x peak this repo's own
> capacity note assumes. If a WebSocket stream counts as one request the cap is irrelevant;
> if each utterance counts, Gnani TTS cannot carry ten lines on the self-serve tier at all.
> **UNKNOWN, and it is question one.**"*

The same file records that Gnani measures its **STT** WebSocket leg in sessions (20
concurrent) and prints no session figure for TTS at all — so the vendor has the vocabulary
and chose not to use it on the TTS row.

**This rung is unsellable today for an unrelated reason** (hard rule 7: no operator has
attested a Gnani invoice price, so `agents/voice_offer.py` refuses every Gnani voice —
`voice_offer.py:51-62`). That is a gate working, not a gap. But it means the 60 RPM ceiling
has never been met by real traffic and will not be until after the attestation.

### 2c. Sarvam (STT, every call) — **40 RPM recorded, but for the LLM leg, not STT**

`apps/api/billing/rates.py:641-645`:

> *"⚠ **CAPACITY IS PER ACCOUNT, NOT PER KEY.** The Starter tier allows 40 requests/minute
> on `sarvam-105b` chat, and the limit pools across every key on the account — issuing a
> second key buys no capacity… the binding constraint on this leg was always the request
> rate rather than the price."*

That figure is for **Sarvam's chat/LLM model**, which is not the in-call STT leg. **UNKNOWN
— no concurrency or RPM ceiling for Sarvam Saaras STT is recorded anywhere in this
repository.** Saaras transcribes every call on both rungs, so this is a ceiling on the
critical path that nobody has looked up. `sarvam.ai` and `docs.sarvam.ai` are egress-blocked
from this container, so it could not be closed here.

### 2d. The LLM leg — **UNKNOWN, and the blueprint says it should not be**

`docs/FLOWS.md:348` and `docs/BRD.md:429` both name *"the Azure TPM/RPM quota in
`eastus2`"* as a term of the real-ceiling `MIN()`. **No number for it exists anywhere in
this tree.** `docs/DATA-MODEL.md:943-945` records an `engine_capacity` table intended to
hold `sarvam_concurrency` and is stamped **"NOT YET CREATED."**

So two of the three terms of the platform's own documented capacity formula are unknown
numbers, and the table meant to hold them does not exist.

### 2e. The in-call embedding leg — **one network call per unresolved turn, no limit recorded**

`apps/voice-worker/voice_worker/embedding.py:1-9` — the dense retrieval arm makes *"the
only network call on the turn"*, a `POST /embeddings` to the Gemini Developer API, on turns
the lexical arm gave up on. **UNKNOWN — no RPM or concurrency ceiling for that endpoint is
recorded in this repository.** It is optional and gated (a deployment that never attested
an embedding price never constructs the embedder, `embedding.py:30-44`), so it is a ceiling
on a path that is off by default rather than one that binds today.

### 2f. Pipecat Cloud itself — **50 agents, from the vendor's own installed CLI**

The best-class evidence in this whole audit, because it was read from a package pinned in
our own lockfile rather than relayed:

* `pipecatcloud==1.2.0`, `cli/commands/deploy.py:645-651` — `--max-agents`, *"Maximum
  number of allowed agents (default cap 50, contact support to raise)"*.
* `_utils/deploy_utils.py:269-286` — `ScalingParams(min_agents=0, max_agents=None)`; the
  key is accepted by the config parser (`:567-594` `expected_keys`) and travels to the API
  as `maxAgents` (`api.py:561-562`).

**We do not set `max_agents`**, so the platform default applies. The independently recorded
figure agrees: *"1 session per instance; max pool 50"*
(`docs/evidence/engine-replacement-comet-2026-09-06.md:122`, marked **VERIFIED** there
against the vendor's pricing page, **REPORTED** from this container's seat because the host
is egress-blocked).

---

## 3. THE MISSED CALL — **NO RECORD EXISTS. THIS IS THE FINDING.**

### 3a. Where an inbound call first becomes a row — **at settlement, in the worker**

The only writer is `apps/api/worker/service.py:182-220` (`_UPSERT_CALL_SQL`), reached
through `POST /v1/worker` from `voice_worker/sink.py`. That post happens **after** the
worker has admitted the session, read the config and started (or finished) the call.

The path before it writes nothing:

* `carrier_routes.py:565-663` — the answer route does **no database write**. Its only
  output is a log line, `carrier_answer_served` (`:646-657`), carrying tenant id, agent id,
  auth method and the caller's state — **an application log line, not a row, not a metric,
  and nothing reads it**.
* `bot.py:259` — `registry.reserve(call_id)` is the admission point. On refusal it raises
  `AtCapacityError` (`lifecycle.py:57`) which propagates out of `bot()`. **It posts nothing
  to our API. It writes nothing. The `call_id` it was about to use was minted seconds
  earlier in the worker (`bot.py:251`) and dies with the exception.**

**Therefore:** a call that arrives when the container is busy, cold, crashed, or when the
platform starts nothing at all, produces **zero rows in our database and zero events on our
side.** The clinic's phone rang; we have no record that it did.

### 3b. Is there a callback path for an unanswered call? — **NO**

* `apps/api/callbacks/service.py:1-8` — `scheduled_callbacks` exists for *"A caller says
  'ring me back Tuesday at four'"*, booked **mid-call** through the in-call tool. It
  requires a call that was answered.
* `no_answer` / `busy` / `voicemail` (`apps/api/crm/models.py:39-60`,
  `crm/performance.py:41`) are **outbound** dial outcomes — the contact did not pick up.
  There is no inbound equivalent.
* Grepping `missed call`, `missed_call`, `unanswered`, `abandoned` across `apps/`, `docs/`
  and `packages/` returns nothing about an inbound call we failed to answer.

**Nothing in this product would ever ring that person back.** There is no path to build on,
either — the phone number we would need is not available (§3c).

### 3c. Could a reconciliation discover it later? — **NO, and it is structural**

* `apps/api/engine/pipecat.py:1301-1325` — `list_executions` reads **our own store**, and
  any window carrying sessions is reported INCOMPLETE with `carrier_cdr_unavailable`. A
  call that never created a session is not in our store to be found.
* **No component in this repository reads the carrier's CDR.** `CarrierCdr` is a dataclass
  the worker would be *handed* (`voice_worker/meter.py:488-503`), it defaults to `None` on
  `run_call` (`voice_worker/runtime.py:227`), and **`bot.py` does not pass it**
  (`bot.py:260-284`). The only Plivo REST endpoint anywhere in the stack is the hangup,
  inside Pipecat's serializer.
* `docs/PIPECAT-MIGRATION.md:355` — on this engine *"There is no webhook… and no poller."*

So the carrier's own record of the missed call — the one artefact that would prove or
disprove the claim — is never fetched, never stored, and never compared against ours.

### 3d. Would anyone be alerted? — **NO**

`AtCapacityError` is a Python exception inside a container on a vendor's infrastructure.
There is no alarm code for it, no `alarm_severity.py` entry, no runbook row. The readiness
marker (`lifecycle.ReadinessFile`) publishes `busy` to a **file inside the container**
(`lifecycle.py:30-36`), deliberately not to an HTTP endpoint, and nothing outside that
container reads it.

**Plain statement for the founder: we would not know. Neither would the client.**

---

## 4. WHAT BREAKS FIRST

**Today: everything, at zero.** Nothing is deployed (§0). That is an external blocker
(BLOCKER-1 — a Plivo account in the India data region), not engineering.

**On the day it is deployed as currently configured, the single lowest ceiling in our own
stack is `min_agents = 1` (`pcc-deploy.toml:72`) — ONE warm slot.** Caller #2 in a
simultaneous pair does not get a busy signal; the platform must cold-start a second
container for them, which by the repo's own figure is about ten seconds of ringing — the
duration that same file calls "not usable for inbound".

**The ceiling below that, and the one that produces DEAD AIR rather than a slow answer, is
the Cartesia TTS concurrency ceiling on the Studio rung — 3 units on Pro, 5 on Startup,
with a 429 and no queue.** It is lower in consequence even where it is higher in number,
because a 429 mid-call is silence on a live conversation, not a longer ring.

**Is a number knowable from the code?** Partially:

| Ceiling | Knowable now? |
|---|---|
| 1 warm slot | **YES** — `pcc-deploy.toml:72`, VERIFIED |
| 1 session per container | **YES** — `boot.py:193`, VERIFIED (our code); the vendor fact behind it is REPORTED |
| 50 agents platform cap | **YES** — vendor CLI in our lockfile, VERIFIED |
| ~85 concurrent calls at our own rate limit | **YES as a number**, but rests on an unverified premise about worker egress addressing |
| Cartesia units → simultaneous calls | **NO** — the unit is `context_id` and nobody has counted contexts per conversation |
| Gnani 60 RPM → simultaneous calls | **NO** — the vendor states the number and not its scope |
| Sarvam Saaras STT ceiling | **NO** — not recorded anywhere |
| Azure TPM/RPM in `eastus2` | **NO** — named in BRD/FLOWS as a term of the `MIN()`, never filled in |

**Three of the eight terms of our own documented capacity formula are unknown numbers, and
the table meant to hold them (`engine_capacity`) does not exist.** Any simultaneity figure
quoted to a client today would be a guess.

---

## 5. WHAT MUST BE MEASURED ON A LIVE SYSTEM

Each of these is unknowable from the code. None is engineering work being deferred; each
needs a running deployment, an account, or a vendor invoice.

**T-1. Does Pipecat Cloud actually start a second container for a second simultaneous
call, and how long does the caller hear ringing?**
*Do:* with the worker deployed at `min_agents = 1`, place 2, then 5, then 10 genuinely
simultaneous inbound calls. *Record:* time from carrier answer to first agent audio, per
call, per position in the burst; how many calls got `AtCapacityError` with nothing behind
them. **This is the measurement that settles the product claim.** Nothing else on this list
matters if this one fails.

**T-2. What does a cold start cost a caller in practice?** The ~10 s figure is REPORTED
from an undated vendor page (`engine-replacement-comet-2026-09-06.md:93`). *Record:* the
real p50/p95 from carrier answer to first audio on a cold container in `ap-south`.

**T-3. Cartesia contexts per conversation, and the 429 threshold.** Already registered as
**OPERATIONS §2 gate 53**, which specifies the procedure and states that its answer (d) —
*the highest simultaneous agent count that produced no 429s* — is what `cartesia_agent_cap`
must be set to. *Additionally record what this audit needs and gate 53 does not ask:* how
many unique `context_id`s ONE conversation opens, since that is the conversion factor
between units and simultaneous callers.

**T-4. Does the API connection pool queue on a synchronised burst?** *Do:* start N calls in
the same second; watch pool wait time on the session read. *Record:* whether any session
read waits, and whether any hits `_POOL_TIMEOUT_S = 5.0` — which on this path is five
seconds of silence before the greeting.

**T-5. Does the Pipecat Cloud worker fleet present one egress address or many?** Decides
whether `worker_api`'s 600/min is a platform ceiling (~85 concurrent calls) or effectively
no ceiling at all. *Record:* the source address our API sees from two containers serving two
simultaneous calls. Consequence of getting it wrong is severe and one-way: a 429 on a
settlement loses that call's extraction, CRM columns and lead **permanently**
(`ratelimit.py:184-186`).

**T-6. Gnani's 60 req/min — per what?** Per key, per account, per model, per WebSocket
session, or per utterance. Registered as **OPERATIONS §2 gate 56(b)**. Until it is answered,
the Clear rung has no knowable line count. (The rung is unsellable for an unrelated reason
today — no attested price — so this is not urgent, but it must precede the first Clear
client.)

**T-7. Sarvam Saaras STT concurrency / RPM ceiling.** Not recorded anywhere in this tree,
and Saaras is on **every** call on **both** rungs. `sarvam.ai` and `docs.sarvam.ai` are
egress-blocked here. *Needs:* a founder reading of the account's published limits, or a
support answer.

**T-8. Azure `eastus2` TPM/RPM quota for the deployment.** Readable from the Azure portal by
the human who owns the resource; it is the third term of the `MIN()` in `docs/FLOWS.md:348`
and has never been filled in.

**T-9. What a Pipecat Cloud "active minute" bills, and whether a warm idle container accrues
one.** Already registered as **OPERATIONS §2 gate 57**, and it is the cost half of the same
decision: raising `min_agents` to serve N simultaneous callers has a monthly rupee floor
attached (`docs/PIPECAT-MIGRATION.md:965-981` — one warm slot is ₹2,052/month before a
single active minute).

---

## 6. WHAT THIS AUDIT DOES NOT SAY

* It does not say the design is wrong. One container per call with platform scheduling is a
  reasonable shape, and `carrier_routes.py` is genuinely stateless and genuinely tested to
  be. The problem is not architecture; it is that **nothing has been run**.
* It does not say the fix is large. `min_agents` is one line in one file, and it is
  deliberately set to 1 with the reasoning written out: *"Raise it WITH the first client,
  not before"* (`pcc-deploy.toml:71`). That is a defensible pilot decision — it stops
  becoming defensible the moment the sentence at the top of this document is said to a
  customer.
* It does not price the fix. Raising the warm floor has a real monthly cost
  (§5 T-9) and that is a founder decision, not an engineering one.
* **It fixes nothing.** Read-only audit, as briefed. No file in this repository was modified
  except this one.
