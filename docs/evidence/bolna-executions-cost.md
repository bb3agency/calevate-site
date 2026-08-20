# Bolna executions, cost, statuses and batches — audited against the live docs mirror

**Lane:** executions · batches · calls · post-call guides · pricing · fetch-agent-executions
**Evidence:** `bolna-findings/mirror/pages/` (fresh mirror). Every claim below quotes a line
and names its file. Where the vendor contradicts itself, that is stated rather than
resolved by preference.
**Scope rule applied throughout:** an ambiguous vendor document does not license a guess
(D-31, D-32, D-350). Two findings below are acted on *because* both readings of the
ambiguity accept the same fix; one is deliberately NOT acted on because the readings
produce different numbers.

---

## 0. Headline

| # | Finding | Class | Status |
|---|---------|-------|--------|
| A | The executions poller omitted `to`, a **required** query parameter. The guarantee of record 400s on every tick. | code contradicts docs | **FIXED** |
| B | The webhook source-IP allowlist held **1 of 3** documented egress addresses, and it fails safe — two of three senders were being rejected. | capability constant wrong | **FIXED** |
| C | Gate 7's **unit** half is settled by the vendor's own worked example — arithmetic, not a precedence rule. | assumption → fact | **FIXED (evidence + tests)** |
| D | Gate 7's **currency** half is *not* settled, and cannot be settled by capturing a payload — `AgentExecution` declares no `currency` field. | assumption stands | refusal branch kept |
| E | Our stack (`azure/gpt-4o-mini`, `saaras`, `bulbul:v2`) is **included in Bolna's flat $0.06/min rate**. The cost case for BYOK is gone; the residency case is not. | founder decision | reported, not changed |
| F | `bulbul:v3` is **not** on the preferred list — D-36's default TTS falls off the flat rate onto variable billing. | founder decision | reported, not changed |

---

## 1. Gate 7 — the money. What the pages settle and what they do not.

### 1.1 The UNIT is now observed, not adjudicated

The adapter previously justified `_ASSUMED_MINOR_UNITS_PER_MAJOR = 100` with the vendor's
own precedence rule ("treat the YAML as the canonical schema"), which decides *which
document to believe* and says nothing about the world. The hosted API reference now prints
a real completed execution.

`bolna-findings/mirror/pages/api-reference/executions/get_execution.md`, "Completed
execution example":

```json
"conversation_duration": 16,
"total_cost": 3.23,
"cost_breakdown": { "platform": 2, "network": 1, "transcriber": 0.23, "llm": 0, "synthesizer": 0 }
```

Two facts fall out that no amount of prose could give:

1. **`total_cost` is exactly the sum of the five legs.** `2 + 1 + 0.23 + 0 + 0 = 3.23`.
   `_cost` has always converted total and legs on one divisor and one rate so that a row's
   parts reproduce its whole; that was chosen on first principles and is now corroborated.
2. **The major-unit reading is arithmetically impossible.** 3.23 over 16 s is 12.11
   units/min. As minor units that is ~12.1 US cents/min, which sits on top of the rate the
   vendor publishes for the Voice AI leg plus telephony and platform fee. As major units it
   is **$12.11/min ≈ ₹1,060 for one minute of an Indian phone call** — three orders of
   magnitude from every price either party publishes.

The decomposition corroborates it independently. `cost_breakdown.network: 1` and
`platform: 2` are whole units on a 16-second call because
`bolna-findings/mirror/pages/pricing/call-pricing.md` bills telephony **"by call duration
(rounded to minutes)"** and the platform fee as **"A flat per-minute fee"**, while
`transcriber: 0.23` is fractional because STT is **"Billed by call duration (rounded to
seconds)"** on the same page. Only the minor-unit reading makes that pattern coherent.

The OpenAPI wording is unchanged and still agrees: `total_cost` — *"Total cost incurred by
this execution in cents"*; `cost_breakdown` — *"Breakdown of the costs in cents"*; and all
five `CostBreakdown` members *"... in cents"* with fractional examples (4.2 / 1.2 / 2 / 6.8
/ 0.7), so `_to_inr`'s `Decimal(str(...))` still matters.

**Action taken:** the constant keeps its value and changes class. The comment above
`_ASSUMED_MINOR_UNITS_PER_MAJOR` now carries the arithmetic and its citations, and two
tests pin it (§6).

### 1.2 The CURRENCY is still not settled — and a payload capture cannot settle it

- The OAS names no currency at all.
- `bolna-findings/mirror/pages/pricing/preferred-models.md` quotes the flat rate as
  **"\$0.06/min (₹5.52/min)"** and refers to **"the 6¢/min rate"** — so every price Bolna
  publishes is primary in dollars and "cent" means the US one. That is an inference from a
  price list, not a statement about *this field*.
- `bolna-findings/mirror/pages/pricing/call-pricing.md` introduces a **third** word for the
  same quantity: *"go to the Agent Executions page to see how many **credits** the
  conversation consumed."* A wallet credit need not be one US cent.

**The refusal branch stays.** `_MINOR_UNITS_PER_MAJOR` gets no INR entry.

**Correction to a premise in the audit brief.** The brief states that "an INR-billed
account currently meters NOTHING — the refusal branch fires and every call records no
cost." That is not what happens against the documented shape. `AgentExecution` declares
exactly seventeen properties — `id`, `agent_id`, `batch_id`, `conversation_duration`,
`total_cost`, `status`, `error_message`, `answered_by_voice_mail`, `transcript`,
`created_at`, `updated_at`, `cost_breakdown`, `telephony_data`, `transfer_call_data`,
`batch_run_details`, `extracted_data`, `context_details` — and **`currency` is not among
them**. So `_cost`'s `payload.get("currency") or payload.get("cost_currency")` always
misses, `currency_stated` is always `False`, and the `engine_cost_unit_unknown` branch is
**unreachable** without Bolna adding an undocumented key. An INR-billed account today
meters on the house USD assumption — a quieter and more dangerous failure than a gap,
because the number looks fine.

**Consequence for gate 7:** its currency criterion cannot be closed by capturing an
execution. It needs an **invoice or wallet statement**. Proposed replacement text in §7.

The defensive reads are correct to keep (they cost nothing and catch a vendor addition),
and a test now pins the absence so nobody plans around a field that is not there.

### 1.3 Plausibility band — no change needed

The vendor's published INR equivalent, **₹5.52/min** for the Voice AI leg, sits inside
`_PLAUSIBLE_INR_PER_MIN_FLOOR..CEILING` (₹0.10–₹100) with wide margin, and the worked
example prices at ~₹10.7/min at fx 88. The band neither cries wolf nor misses the 100x
error. The vendor example is a 16-second call, below
`_PLAUSIBILITY_MIN_DURATION_S = 30`, so it is skipped live — exactly as designed.

---

## 2. Finding A — the poller was sending half of a required pair (FIXED)

`bolna-findings/mirror/pages/api-reference/executions/get_executions.md`:

> **Warning:** The `from` and `to` query parameters are **required** to filter executions by date.
> * Both `from` and `to` are **required** and must be passed **together**.
> * The maximum allowed range between `from` and `to` is **7 days**.
> * Dates must be in **UTC ISO 8601** format (e.g. `2026-06-07T00:00:00.000Z`).

and its OpenAPI block marks **both** `required: true`.

`BolnaEngine.list_executions` sent `from`, `page_number`, `page_size` — and no `to`. Per
the API reference that is a 400 on every tick: `vendor_request` raises,
`reconcile_executions` reports `reconciliation_fetch_failed`, and the mechanism D-31
appoints the **guarantee of record** never runs. This is the same failure shape D-353 was
opened to fix (a route that 404s forever), one parameter further along.

### The vendor contradicts itself, and here it does not matter

`bolna-findings/mirror/pages/guides/fetch-agent-executions.md` — also in this lane — says:

> * **Query Parameters** (all optional unless noted):

lists `from`/`to` with no "required" note, and prints a worked example that omits them
entirely (`?page_size=50&page_number={page_number}`).

So one first-party page says required and another says optional. **Both readings accept
the same request:** `from`+`to` is a valid filtered listing whether or not the pair is
mandatory. Sending both is the *intersection* of the two readings, not a bet on one.
Only *omitting* `to` depends on which page is right. That asymmetry is why this was fixed
rather than logged — and it is explicitly unlike the cost unit (§1.2), where the two
readings produce different numbers and the adapter therefore refuses.

### The 7-day cap refuses; it does not clamp

Silently moving `from` forward would make `complete=True` a claim about a period nobody
asked us to skip, and `ListingIncompleteReason` has no member for "our own arithmetic
narrowed the window" — its four values (`explicit_more`, `full_page_suspected`,
`page_cap_reached`, `next_link_no_progress`) are all assertions about **vendor**
truncation. Borrowing one would put a word into an operator's alert that
`docs/OPERATIONS.md` defines as something else, which is the same defect D-365 removed
members for. A caller asking for a window the vendor will not serve is a bug in the
caller, so it fails there with `engine_listing_window_too_wide` naming the limit, rather
than becoming an opaque vendor 400.

**No production caller can reach it:** `reconcile_executions` uses
`now - 30 minutes`; the conformance suite uses 1 hour; `GateContext.since` defaults to 6
hours. It is a guard on the contract, not a live path.

**If Lane B would rather clamp than refuse**, the change needed in
`packages/shared/src/calevate_shared/engine.py` (which I must not edit) is exactly:

```diff
     # continuing would burn the page cap on identical pages and then report the wrong
     # reason. Named for the link era and kept, because the CONDITION is the same whether
     # the next page is named by a cursor (Cartesia) or by a page number (Bolna).
     "next_link_no_progress",
+    # The caller asked for a window wider than the vendor will serve in one request, so
+    # the adapter narrowed it to the vendor's maximum. Unlike the four above this is OUR
+    # bound, not evidence of vendor truncation — kept distinct because an operator's
+    # remedy is different: repeat the listing over successive windows, not investigate
+    # the vendor.
+    "listing_window_clamped",
 ]
```

I did not depend on it. The refusal is correct on its own and is the smaller change.

---

## 3. Finding B — two of three webhook senders were being rejected (FIXED)

`bolna-findings/mirror/pages/guides/post-call/polling-call-status-webhooks.md`:

> Webhooks are sent from the following IP addresses. **Whitelist all three** on your
> server to ensure you receive all webhook events.
>
> ```
> 13.203.39.153
> 13.126.9.249
> 13.202.133.53
> ```

Corroborated inside this lane by
`bolna-findings/mirror/pages/api-reference/executions/get_execution.md`: *"Whitelist source
IPs `13.203.39.153`, `13.126.9.249` and `13.202.133.53`."* — and outside it in
`concepts/security.md`, `api-reference/limits.md`, `concepts/call-flow.md`,
`concepts/glossary.md`, `quickstarts/api.md` and `build-with-ai/agents-md.md`.

`DEFAULT_BOLNA_SOURCE_IPS` held **one** address. Every source this repository had read —
the pinned OAS, `bolna-core.md`, `setup-webhook/SKILL.md`, `execution-payload.md` — named
one, and they were right when they were read. **The mirror dates the change:** the older
snapshot `bolna-findings/mirror/llms-full.txt` still carries the single-IP wording
(*"Bolna sends webhooks from a fixed source IP: **`13.203.39.153`**"*, line 10138) while
the fresh `pages/` tree carries three. The vendor renumbered; our constant did not.

**Why this is severe rather than partial.** `parse_source_ip_allowlist` fails **safe** — an
address not in the set is *rejected*. Which sender carries a given status transition is not
ours to choose, so this is not "some lost webhooks" but arbitrary lost transitions,
`completed` among them. Survivable only because the poller is the guarantee of record
(TRD §5, "payloads as hints, poller as truth") — and Finding A had that poller sending a
malformed request at the same time. **Both halves of the guarantee were down together.**

Fixed in `packages/shared/src/calevate_shared/config.py` (the one runtime copy) and in
`scripts/pilot/gates_api.py`, whose `DOCUMENTED_EGRESS_IP` deliberately restates the
vendor fact rather than importing it. That constant is now `DOCUMENTED_EGRESS_IPS` and
gate 1 scores **every** address: scoring one of three would have been the worst outcome
available to a gate — a green `accepts_documented_egress` on an allowlist rejecting two
thirds of deliveries.

---

## 4. Webhook retry semantics (D-352) — the hosted docs do not corroborate the retry

`polling-call-status-webhooks.md` describes the URL, the payload shape and the source IPs.
It says **nothing whatever** about retries, signing, delivery guarantees, ordering or
replay. The only delivery-adjacent statements on the page are:

> **Your webhook endpoint must be publicly accessible** and able to receive HTTP POST requests.

> The webhook payload is the **same structure as the Raw Call Data** ... It matches the
> [Get Execution API] response format.

D-352 flipped our reading from "at-most-once" to "retries on non-2xx" on the strength of
`references/execution-payload.md` §"Webhook delivery" and `setup-webhook/SKILL.md`
§"Idempotency" in the skills repo. **The hosted docs neither confirm nor contradict it —
they are silent.** So the retry claim still rests on one first-party source. That does not
reverse D-352, but it does mean the claim is *uncorroborated*, and TRD §5's design
("payloads as hints, poller as truth") remains load-bearing rather than belt-and-braces.

**One thing the page adds that we should keep in view:** the agent-level webhook URL can
also receive **pre-call** webhooks:

> If a tool sets a `pre_call_webhook_param` without its own `pre_call_webhook_url`, the
> pre-call webhook is sent to **this agent-level Webhook URL**. The endpoint you configure
> here may therefore receive in-progress pre-call webhooks in addition to your post-call
> execution webhooks. Distinguish them by the `in-progress` `status` and the extra fields
> from the tool's `pre_call_webhook_param`.

Our receiver dedupes on `(execution_id, status)` and treats payloads as hints, so an extra
`in-progress` delivery is absorbed rather than mis-handled. **No code change.** It becomes
reachable only if a tool with `pre_call_webhook_param` is ever configured, which
`BOLNA_CAPABILITIES.transfer=False` currently precludes — and a concurrent lane is already
adding a `transfer_call_data` alarm for exactly that drift.

**Docs corrected:** `docs/TRD.md` §5 still said "**UNSIGNED, at-most-once**" (superseded by
D-352 over a year of commits), "source-IP allowlist (13.203.39.153)" (one address) and
"dedupe on execution_id" (D-352 requires the **pair**, or `completed` is discarded as a
duplicate of `queued`). All three corrected in place.

---

## 5. Per-page results — including the pages with no gap

### `api-reference/executions/` (5 pages)

| Page | Result |
|---|---|
| `overview.md` | **No code gap.** One doc defect to note: it lists `GET /batch/:batch_id/executions` (singular `batch`) while every OpenAPI block spells the path `/batches/{batch_id}/executions`. We call neither. |
| `get_execution.md` | Source of Findings A-adjacent (IPs), C (worked example). Route `GET /executions/{execution_id}` matches `bolna.py:get_execution`. **No gap** on the route. |
| `get_executions.md` | **Finding A.** Also confirms `page_size` max 50 / default 20 — our `_LISTING_PAGE_SIZE = 50` is at the documented maximum. **No gap** on paging. |
| `get_batch_executions.md` | Byte-identical `AgentExecution` schema. Documents *"Returns a bare JSON array of execution objects (not wrapped in a `data` key)"* — our `_request` already wraps bare arrays as `{"data": [...]}`. **No gap.** |
| `get_execution_raw_logs.md` | `GET /executions/{execution_id}/log`. **We do not call it, and should not.** Its `data` field carries raw assistant/user text and its new `reasoning_content` field carries model reasoning over the same material — both are transcript content under hard rules 5/6. **No change; recorded so nobody adds it as a "debugging aid".** |

### `api-reference/batches/` (8 pages)

**We do not use Bolna's Batch APIs at all, and that is correct.** No `/batches` call exists
anywhere in `apps/`. `apps/workers/campaign_dispatch.py` dials per contact through
`POST /call` so that the compliance gate, DNC propagation and the big red switch run
**before every dial** (hard rule 5).

The pages make that a stronger conclusion than it was:

- `create.md`: a batch is a **CSV upload** — *"`contact_number` is **required** — E.164
  format"* — and `schedule.md` starts it. Once running, the only lever is
  `POST /batches/{batch_id}/stop`, which returns *"Batch is not queued or running"* (404)
  otherwise. So a **per-contact** DNC withdrawal mid-batch cannot be honoured except by
  stopping the **whole** batch. That is a compliance argument against adopting batches, not
  merely a preference.
- `create.md` also warns of two vendor sharp edges we would inherit: *"Use a **numeric UTC
  offset** like `+00:00` — the `Z` suffix is rejected with a 500"*, and *"Bolna rounds the
  start up to the next 10-minute mark"* — a rounding that would silently move a campaign
  window we told a client about.
- `get_batch.md` / `get_batches.md`: batch `status` is a **different enum** from execution
  status — `created, scheduled, running, completed, stopped, failed`. Worth stating
  explicitly because both are called "status" and neither maps to `CallStatus`.
- `executions.md` is the same document as `executions/get_batch_executions.md` under a
  different title.
- `overview.md` lists `GET /batches/:agent_id` where the OpenAPI path is
  `GET /batches/{agent_id}/all`.

**No code change. No gap.**

### `api-reference/calls/` (3 pages)

- `make.md` — our body is `{agent_id, recipient_phone_number, user_data}`. The two optional
  fields we omit are omitted **correctly** and should stay omitted:
  - **`retry_config`** (default `enabled: false`). Vendor-side auto-retry would re-dial a
    number **without** re-running our compliance gate or re-checking DNC. Our dispatcher
    owns retries.
  - **`bypass_call_guardrails`** (default `false`) — *"Skip time validation checks and make
    call immediately"*. Never send this; hard rule 5 forbids a bypass.
  - `user_data` is confirmed as the personalization mechanism (*"Pass `user_data` to inject
    variables into your agent's prompt and welcome message"*), which is what D-21 uses it
    for. **No gap.**
- `stop_call.md` — `POST /call/{execution_id}/stop`, *"Stop a queued or scheduled call"*.
  Matches `end_call` post-D-353, and confirms it cannot hang up a live call. **No gap.**
- `overview.md` — lists only `POST /call`; the stop route is documented but not listed.
  Cosmetic.

### `guides/post-call/` (3 pages)

- `list-phone-call-status.md` — the full status list, matching `_VENDOR_STATUSES` exactly.
  **Verified value by value against five independent enumerations** in this lane
  (`get_execution.md` `AgentExecution.status`, its `BatchRunData.status`,
  `get_executions.md`'s `status` query filter, `get_batch_executions.md`, and this page's
  three tabs): `scheduled, queued, rescheduled, initiated, ringing, in-progress,
  call-disconnected, completed, balance-low, busy, no-answer, canceled, failed, stopped,
  error` — fifteen, no more. **NO GAP.** `test_every_status_the_vendor_can_send_is_mapped`
  continues to guard it.
  - **Gate 17 (`voicemail`) gets a firmer answer.** There is no `voicemail` status in any
    of the five enumerations, and this page shows `answered_by_voice_mail` as a top-level
    boolean on an execution whose `status` is plain `completed`. The adapter comment
    already says exactly this; the hosted docs now corroborate it independently of the OAS.
  - **Two undocumented-in-OAS fields appear in this page's example payload:**
    `usage_breakdown` (`synthesizer_characters`, `synthesizer_model`,
    `transcriber_duration`, `transcriber_model`, `llm_tokens`, `llm_model`) and
    `extraction_webhook_status`. Neither is in `AgentExecution`. We read neither. Recorded
    only — `usage_breakdown` would be the natural source for per-leg *usage* metering if we
    ever want it, but it is undocumented and unpinned, so it is not a thing to build on.
- `list-phone-call-hangup-status.md` — **we read no hangup field at all**, and there is no
  column to put one in. That is a gap in *coverage*, not a contradiction, and closing it is
  a product decision (what a client's screen says) rather than an adapter fix. Two facts
  worth pinning before anyone does:
  - **The vendor names the field two different ways.** This page says `hangup_code`; the
    OpenAPI in `get_execution.md` says `hangup_provider_code`. Anyone mapping it must
    tolerate both.
  - `hangup_by` is a small closed-ish set — `API Request`, `Callee`, `Caller`, `Carrier`,
    `Error`, `Plivo`, `Unknown`, *(empty)* — and *"Code `4000` appears across multiple
    categories (API, Caller, Callee). The correct interpretation depends on **call
    direction**"*. A naive `hangup_code == 4000` mapping is therefore wrong by
    construction.
  - The only two Bolna-side reasons documented are `inactivity_timeout` and
    `llm_prompted_hangup` — **no voicemail hangup reason**, which is a second, independent
    strike against the OSS-derived `HangupReason.VOICEMAIL_DETECTED` reading in gate 17.
- `polling-call-status-webhooks.md` — Findings B and §4.

### `pricing/` (3 pages) — see §6

### `guides/fetch-agent-executions.md`

Contradicts `get_executions.md` on whether `from`/`to` are required (§2). Otherwise
corroborates our paging contract: *"`50` results per page is the maximum allowed. Default
is `20`"*, and *"keep fetching while `has_more == true`"* — which is exactly what
`list_executions` does and why the D-353 `has_more` walk is right. **No gap** beyond §2.

---

## 6. Founder decisions — NOT changed by me

### E. BYOK buys us **no cost saving on the LLM leg**. It still buys residency.

`bolna-findings/mirror/pages/pricing/preferred-models.md`:

> Every Bolna workspace ships with a **flat per-minute rate** — **\$0.06/min (₹5.52/min)**
> at standard wallet tiers — that already includes a curated set of transcriber (ASR), LLM,
> and voice (TTS) models.

The current preferred list contains **our exact stack**:

| Component | Preferred models (verbatim) | Our choice |
|---|---|---|
| LLM | `gpt-4.1-mini`, `gpt-4o-mini`, **`azure/gpt-4o-mini`**, **`azure/gpt-4.1-mini`**, `azure/ptu-gpt-4-1-mini` | `AZURE_OPENAI_DEFAULT_MODEL = gpt-4o-mini`, `gpt-4.1-mini` a live switch |
| ASR | `saarika:v2.5`, **`saaras:v2.5`**, **`saaras:v4`** | Sarvam Saaras (D-36) |
| TTS | `eleven_turbo_v2_5`, `eleven_flash_v2_5`, **`bulbul:v2`**, `sonic-3`, … | Sarvam Bulbul **v3**, v2 = value tier (D-36) |

So Bolna already runs an **Azure OpenAI** deployment of both our models and bundles it into
the flat rate. Meanwhile:

> When you bring your own keys (BYOK), Bolna does not charge for those components. You only
> pay your providers directly, plus Bolna's platform fee. — `call-pricing.md`

> If you pick a model outside this list (a premium model, a BYOK provider, or a model not
> yet marked as preferred), that component is billed at variable, usage-based rates instead
> of the flat rate. — `preferred-models.md`

**The decision to put to the founder:** the *cost* argument for BYOK on the in-call LLM leg
is dead — going BYOK moves that component **off** a bundled flat rate and onto our own Azure
bill plus Bolna's platform fee. **The residency argument is untouched and is why D-410
exists.** Bolna's `azure/*` deployment is *theirs*; its region is unstated, and per
CLAUDE.md a resource's region and its Regional-vs-Global deployment mode can only be
attested in the portal by a human — which we cannot do for someone else's resource, and
Global is Azure's default. Routing in-call transcripts through an Azure deployment whose
region we cannot attest breaks the DPA claim.

**I did not change our provider posture.** My reading is that BYOK survives on residency
alone and that this should be recorded as such, so nobody later "optimises" it away on
cost. That is a founder call, not mine.

Two commercial notes for gate 12 while it is open:

- *"Larger wallet top-ups (e.g. \$600+) get a lower effective per-minute rate as a volume
  discount — the preferred model bundle itself is the same across tiers."* — this is direct
  evidence for gate 12(b) (do volume tiers apply?), at least for the bundled rate.
- **Gate 12(g) — the KB.** `call-pricing.md` enumerates the bill exhaustively: *"costs
  broken down into three components: Voice AI processing (STT + LLM + TTS), telephony
  charges, and a Bolna platform fee"*, then *"Every call's total cost is the sum of five
  components across three parts"*. **No knowledge-base line item exists in either
  enumeration**, and `cost_breakdown` has exactly five keys with no KB member. That
  strengthens D-33's "included" inference materially — but a pricing page that does not
  mention a charge is not a commitment that there is none, so gate 12(g) does **not**
  close. Get it in writing.

### F. `bulbul:v3` is not on the flat rate

Only **`bulbul:v2`** appears under Sarvam TTS. D-36 makes **v3** our default and calls v2
the "value tier". Per `preferred-models.md`, selecting v3 pushes the TTS component **off**
the flat rate onto variable usage-based billing — inverting the assumption, because the
"value tier" is the one that is *included*. The page also warns:

> Model names above match what's shown in the dashboard exactly (including casing and
> version suffixes like `:v2.5`). Selecting a similarly-named model from a different
> provider, or a newer/older version of the same model, may fall outside the preferred list.

Same trap applies to ASR: `saaras:v2.5` and `saaras:v4` are preferred; **`saaras:v3` is
not listed**. Whichever Saaras version we pin decides whether STT is bundled.

**Founder decision, and it is a live cost question, not a hypothetical.** I changed
nothing — D-36 is a quality decision and reversing it on price is not an adapter's call.
The page also cautions that the list *"is a snapshot"* and to check the Add Funds panel,
so this belongs in gate 12's negotiation rather than in a constant.

### Recording residency — handed to Lane D

Every OpenAPI example in this lane serves recordings from
`https://bolna-call-recordings.s3.us-east-1.amazonaws.com/<redacted example SID>/RE…` —
**US-East-1**. Present in `get_execution.md`, `get_executions.md`,
`get_batch_executions.md`, `batches/executions.md` and `list-phone-call-status.md`, on both
`telephony_data.recording_url` and `transfer_call_data.recording_url`.

`docs/TRD.md` §5 already records this ("direct S3 URL (us-east-1), no documented expiry")
and the pipeline copies recordings to our own storage first for exactly that reason. **One
nuance Lane D needs that is not obvious:** the same page's prose example shows a *different*
URL form —

```json
"recording_url": "https://api.bolna.ai/recordings/call/b7140255-af33-4608-8e97-04dd944b8e48"
```

— a Bolna-hosted proxy route that **reveals nothing about where the object is stored**. So
residency cannot be inferred from the URL form a given payload happens to carry, and an
audit that sees only proxy URLs would wrongly conclude the S3 exposure is gone. A call
recording is personal data under DPDP; the legal write-up is Lane D's, not mine, and I have
edited nothing under `/legal/`.

---

## 7. Exact text proposed for files I must not edit

### `docs/OPERATIONS.md` §2 — gate 7, replacement for the sentences from
### "**THE ONE THAT RAISED THIS TO A HARD GATE**" onward

> **THE UNIT IS SETTLED; THE CURRENCY IS NOT, AND THIS GATE NOW SCORES ONLY THE SECOND
> (D-412).** Our adapter divides by 100 (`_ASSUMED_MINOR_UNITS_PER_MAJOR`). That constant
> used to rest on the vendor's own precedence rule between two contradicting first-party
> documents — a rule about which document to believe, not an observation. Their hosted API
> reference now prints a real completed execution
> (`bolna-findings/mirror/pages/api-reference/executions/get_execution.md`):
> `conversation_duration: 16`, `total_cost: 3.23`,
> `cost_breakdown {platform 2, network 1, transcriber 0.23, llm 0, synthesizer 0}`. Two
> things fall out. **`total_cost` is exactly the sum of the five legs** (2+1+0.23 = 3.23).
> And **the major-unit reading is arithmetically impossible**: 3.23 over 16 s is 12.11
> units/min — ~12¢/min as minor units, which sits on their published $0.06/min Voice AI
> rate plus telephony and platform fee, versus **$12.11/min ≈ ₹1,060/min** as major units.
> The decomposition corroborates it: `network`/`platform` are whole units on a 16-second
> call because telephony and the platform fee bill per *minute*, while `transcriber` is
> fractional because STT bills per *second* (`pricing/call-pricing.md`). **The unit no
> longer needs a live capture; a capture can only confirm it.**
> **WHAT IS STILL OPEN IS THE CURRENCY, AND A PAYLOAD CANNOT CLOSE IT.** `AgentExecution`
> declares seventeen properties and **`currency` is not one of them**, so `currency_stated`
> is always False and the adapter's INR-refusal branch is unreachable without an
> undocumented key — meaning an INR-billed account does **not** meter nothing today, it
> meters on the house USD assumption, which is quieter and worse. The OAS names no
> currency; `pricing/preferred-models.md` quotes "$0.06/min (₹5.52/min)" and "the 6¢/min
> rate" (so every published price is primary in dollars); and `pricing/call-pricing.md`
> introduces a third word — executions consume "**credits**", a wallet unit that need not
> be one US cent. **The test is therefore an INVOICE or wallet statement, not a payload
> capture:** place calls totalling a known duration, then reconcile the wallet debit
> against the summed `total_cost` and name the currency the account is billed in. **Pass**
> = we can state the currency from a document Bolna issued us. Blocked outside this repo
> on: a Bolna account with funds.

### `docs/OPERATIONS.md` §2 — gate 12, sentence to append to (a) and (g)

> **(a) — the flat rate is now confirmed in both currencies and the bundle is enumerated:**
> `bolna-findings/mirror/pages/pricing/preferred-models.md` states "**\$0.06/min
> (₹5.52/min)** at standard wallet tiers" and lists the included models. **Our entire stack
> is inside it** — `azure/gpt-4o-mini` and `azure/gpt-4.1-mini` (LLM), `saaras:v2.5` /
> `saaras:v4` (ASR), `bulbul:v2` (TTS). So the **cost** case for BYOK on the in-call LLM leg
> is gone; BYOK moves that component off a bundled rate onto our own bill plus the platform
> fee. **The residency case is untouched and is the whole of D-410's reason** — Bolna's
> `azure/*` deployment is theirs, its region is unstated, and Global is Azure's default.
> Record that BYOK now stands on residency alone so nobody later optimises it away on
> price. Same page also answers (b) in part: "Larger wallet top-ups (e.g. \$600+) get a
> lower effective per-minute rate as a volume discount — the preferred model bundle itself
> is the same across tiers."
> **(g) — the inference is stronger but still an inference:** `pricing/call-pricing.md`
> enumerates the bill twice ("three components: Voice AI processing (STT + LLM + TTS),
> telephony charges, and a Bolna platform fee"; "the sum of five components across three
> parts") and **names no knowledge-base charge in either**, matching `cost_breakdown`'s
> five keys. A pricing page that omits a charge is not a commitment that none exists —
> still get it in writing.

### `docs/OPERATIONS.md` §2 — gates 17 and 18, field-name correction

Both gates instruct capturing a field called **`hangup_detail`**. **No such field exists.**
The vendor's names are `hangup_by`, `hangup_reason`, and `hangup_provider_code` (OpenAPI in
`get_execution.md`) — which the hangup guide calls `hangup_code`
(`guides/post-call/list-phone-call-hangup-status.md`). Replace `hangup_detail` with
"`hangup_by` / `hangup_reason` / `hangup_provider_code` (the hangup guide calls the last
one `hangup_code` — capture whichever spelling arrives)" in both gates.

Gate 17 may also be narrowed: the hosted docs now show **no `voicemail` status in any of
five independent status enumerations**, and **no voicemail hangup reason** (the only two
Bolna-side reasons documented are `inactivity_timeout` and `llm_prompted_hangup`). The
remaining question is purely the product one — should `answered_by_voice_mail` surface as a
distinct status on a client's screen — not the factual one.

### `docs/ROADMAP.md` §6 — proposed decision-log entry

> **D-412 — Bolna renumbered its webhook egress and requires both halves of the executions
> date filter; both halves of the guarantee of record were down.** *Supersedes the
> single-egress premise in D-31/TRD §5 and completes D-353.*
> **(1)** `DEFAULT_BOLNA_SOURCE_IPS` held one address. Bolna now publishes **three** —
> `13.203.39.153`, `13.126.9.249`, `13.202.133.53` — and instructs receivers to "whitelist
> all three ... to ensure you receive all webhook events"
> (`bolna-findings/mirror/pages/guides/post-call/polling-call-status-webhooks.md`; the
> older `llms-full.txt` snapshot in the same tree still shows the single-IP wording, which
> dates the change). `parse_source_ip_allowlist` fails safe, so two of three senders were
> being **rejected**, losing arbitrary status transitions including `completed`.
> **(2)** `list_executions` sent `from` without `to`. `get_executions.md` marks both
> `required: true` and says so twice in prose, with a **7-day** maximum span — so the
> poller D-31 appoints the guarantee of record 400s on every tick. `fetch-agent-executions.md`
> calls the same parameters "all optional"; the contradiction is not resolved and does not
> need to be, because **both readings accept `from`+`to`** — sending the pair is the
> intersection, not a bet. Only omitting `to` depends on which page is right.
> **(3)** The 7-day cap **refuses** (`engine_listing_window_too_wide`) rather than clamping:
> `ListingIncompleteReason`'s four values are all claims about *vendor* truncation, and
> emitting one for our own arithmetic would mislead an operator's runbook lookup. No
> production caller reaches it (`reconcile_executions` uses 30 minutes).
> **(4)** Gate 7's **unit** half is closed by the vendor's own worked example — 3.23 over
> 16 s is $12.11/min under the major-unit reading, ~12¢/min under the minor-unit one, and
> `total_cost` is exactly the sum of the five legs. The **currency** half stays open and
> cannot be closed by a payload capture: `AgentExecution` declares no `currency` field, so
> an INR-billed account meters on the USD assumption rather than refusing. Gate 7 now needs
> an invoice.
> Closes: nothing external. Opens: gate 12 should record that BYOK survives on **residency
> alone**, since `azure/gpt-4o-mini` and `azure/gpt-4.1-mini` are inside Bolna's flat
> $0.06/min bundle.

---

## 8. Files changed

| File | Change |
|---|---|
| `apps/api/engine/bolna.py` | `_LISTING_MAX_WINDOW` added; `list_executions` sends `to` and refuses a >7d window; module docstring's single-IP claim corrected and the uncorroborated retry noted; `_ASSUMED_MINOR_UNITS_PER_MAJOR` comment upgraded from precedence-rule to observation, with the `currency`-field absence recorded. |
| `packages/shared/src/calevate_shared/config.py` | `DEFAULT_BOLNA_SOURCE_IPS` → all three documented egresses, with why and what the omission cost. |
| `scripts/pilot/gates_api.py` | `DOCUMENTED_EGRESS_IP` → `DOCUMENTED_EGRESS_IPS` (tuple); gate 1 scores every address and names the rejected ones. |
| `docs/TRD.md` §5 | "at-most-once" → uncorroborated-retry; one IP → three; dedupe on execution_id → on the `(execution_id, status)` pair. |
| `tests/bolna_listing_test.py` | 5 new tests (pair sent, single window across the fan-out, UTC offset on both bounds, >7d refused, exactly-7d served); `SINCE` made relative. |
| `tests/bolna_snapshot_test.py` | 3 new tests pinning the vendor's worked example (legs sum to total; only the minor-unit reading is a possible phone bill; no `currency` field). |
| `tests/pilot_gates_test.py` | `PartialAllowlistEngine` double + test that a subset allowlist fails `accepts_documented_egress` and names the rejected addresses. |
| `tests/engine_audit_test.py` | fixed-date listing fixture made relative (it had drifted past the vendor's window). |
| `scripts/check_bootstrap_keys.py`, `tests/engine_name_drift_test.py` | comment references to the renamed constant. |

**Not touched:** `docs/ROADMAP.md`, `docs/OPERATIONS.md`, `CLAUDE.md`,
`tests/fixtures/coverage_baseline.json`, `bolna-findings/**`,
`packages/shared/src/calevate_shared/engine.py`, `apps/web/**`, `/legal/**`.
