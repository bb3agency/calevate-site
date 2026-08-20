# Bolna call flows — how a dial is placed, answered and ended, against our code

**Date:** 2026-08-20. **Subject:** `apps/api/engine/bolna.py` (dial + agent body),
`apps/api/campaigns/`, `apps/workers/campaign_dispatch.py`, `apps/voice-runtime/`.
**Evidence class:** VERIFIED-VENDOR-DOCS — Bolna's own live documentation, mirrored at
`bolna-findings/mirror/pages/`. This ranks with VERIFIED-OAS: it is first-party and it
describes the HOSTED platform we POST to, not the OSS framework. Where it disagrees with
the pinned OAS the disagreement is called out rather than resolved silently.

Pages read end to end: `guides/outbound/{making-outgoing-calls, batch-calling, auto-retry,
calling-guardrails, hangup-calls, disconnect-calls}.md`, `guides/inbound/{receiving-
incoming-calls, ivr-inbound-calls, dtmf, buying-phone-numbers, obtaining-regulated-phone-
numbers}.md`, `quickstarts/{api, inbound, batch}.md`,
`customizations/identify-incoming-callers.md`, `concepts/{call-flow, latency,
call-latencies}.md`. Corroborating reads: `api-reference/{errors, agent/v2/create,
agent/v2/patch_update}.md`, `agent-setup/call-tab.md`.

---

## 0. The one-line verdicts

| # | Lane question | Verdict |
|---|---|---|
| 1 | Calling guardrails | **Our understanding was right in mechanism and wrong in premise.** They are **off by default** and we never set them, so nothing in this product is being auto-rescheduled today. Three sharper facts recovered; one hazard fixed. |
| 2 | **Double retry** | **No double-dial exists today, and it was one keyword away.** `retry_config` defaults to `enabled: false` and our dial body never sends it — but the vendor also ships an **agent-level dashboard toggle** that our body did not state and our read-back cannot see. **FIXED**: §2. |
| 3 | Batch vs our dispatch | **No conflict.** We never call `/batches`. The 30-second tick concern is already answered by a Redis single-flight lease; an overrun is safe by construction, not by fitting. |
| 4 | Hangup / termination | **No gap.** Both vendor mechanisms are sent explicitly and our ceiling beats their 90-second default. Money cannot burn: no agent configuration in this product yields an unbounded call. |
| 5 | DTMF / IVR | **Do not adopt, and pin it off.** Keypad digits enter the TRANSCRIPT, the vendor's own use cases are PINs and card numbers, and our redactor cannot catch a 4-digit PIN. **FIXED**: §5. |
| 6 | Latency | **Our 100ms budget is realistic for the half it names and is not a caller-observed number.** Their figures bracket TRD §6.2's estimate; the tool-call timeout is still undocumented across all 335 pages. Two knobs we inherit silently: §6. |
| 7 | Caller identification | **No overlap with D-23** (that is outbound lead delivery; this is inbound pre-call context). Their API variant is a good seam and is settable through the body we already POST. Their CSV/Sheets variants are a **hard no** on DPDP. §7. |

**The largest finding in the lane is §8 and it needs a founder decision**: the
`VoiceEngine` port models an outbound-only world, and three things break on it — the
DLT-registered number never reaches the dial, the inbound receptionist is never routed at
the engine, and no agent we publish can carry a 140-series promotional campaign. All three
need `packages/shared/src/calevate_shared/engine.py`, which is another lane's file, so
exact decision-log text is supplied instead of a change.

---

## 1. Calling guardrails — verified, and the premise corrected

### What the page actually says

| Fact | Citation |
|---|---|
| **Off by default.** | `guides/outbound/calling-guardrails.md` — *"Toggle on **Outbound call timing restrictions** in the Call Tab. It is off by default."* |
| Set via `agent_config.calling_guardrails = {call_start_hour, call_end_hour}`, integers 0-23. | same page, "Configure via API"; schema at `api-reference/agent/v2/create.md` (`minimum: 0`, `maximum: 23`) |
| `call_end_hour` ≥ `call_start_hour`. | same page — *"`call_end_hour` must be greater than or equal to `call_start_hour`."* |
| The window is evaluated in the **RECIPIENT'S** timezone, inferred from their number. | same page — *"the system checks the current time in the **recipient's local timezone** (detected from their phone number)"* and *"A 9 AM start means 9 AM where the recipient is located."* |
| Outside the window → status `rescheduled`, queued to the next allowed start. | same page — *"the call status is set to `rescheduled` and it is automatically queued for the next allowed start time."* |
| A per-call escape hatch exists: `bypass_call_guardrails: true` on `POST /call`. | same page — *"When set to `true`, the call goes through immediately regardless of the configured window."* |
| India's rule, in their own table: TRAI, 9:00 AM – 9:00 PM IST. | same page, "Calling Regulations to Know" |
| Batch scheduling does **not** escape them. | `quickstarts/batch.md` — *"Outbound time-of-day restrictions still apply per recipient timezone. If a scheduled time falls outside the allowed window, calls are pushed to the next allowed slot."* |

### Scored against D-351

D-351 is **correct on mechanism** — Bolna does auto-reschedule an out-of-window dial, and
`rescheduled` is a live call that must not read as `failed`. The `_STATUS_MAP` entry
stands and its defensive value is unchanged.

**Its "normal case" framing is conditionally false and should be read as such.** D-351
says the 9am/6pm boundary is hit "every time"; that is true only of an agent whose
guardrails are ON. `_agent_body` sends no `calling_guardrails`, the feature is off by
default, so **no dial this product places is currently being rescheduled by Bolna**. The
map entry is protection against a console click and a future decision, not a description
of today. (Also worth noting: D-351 says "9am or 6pm boundary" — TRAI's evening boundary
is 21:00, which is what `compliance.service.DEFAULT_WINDOW` correctly uses, and what
Bolna's own India row says. 6pm appears nowhere.)

Two facts D-351 did not have, both of which matter:

* **The timezone is the RECIPIENT'S, not ours.** `compliance/service.py` reasons that
  "India is one timezone, so there is nothing per-tenant to resolve" — true of an Indian
  callee and only of an Indian callee. Our gate is IST-absolute; theirs is
  callee-relative. For `+91` they agree exactly. For any non-Indian number in a contact
  list they do not, and **theirs is the more correct one**. This is not an argument for
  enabling theirs (below); it is a note that our own gate has an unstated `+91`
  assumption.
* **The bypass flag is documented, and the vendor recommends it for testing.** Their
  accordion is titled "Bypass for Testing in Development" — *"use the bypass flag to test
  call flows at any time without waiting for the allowed window."* That is precisely the
  thing CLAUDE.md hard rule 5 forbids by name ("never add a bypass 'for testing' — use
  staging fixtures instead"). Pinned as an absence in
  `tests/bolna_call_flow_test.py::test_a_dial_never_carries_the_documented_compliance_bypass`.

### Decision: we still do NOT send `calling_guardrails`, and here is why in one place

The tempting read is CLAUDE.md's "configure engine built-ins over rebuilding them". It
does not apply here, for a reason that is specific rather than stylistic:

**Their guardrail does not REFUSE an out-of-window dial, it HOLDS it.** A held dial is
fired later by their scheduler, and a dial placed by their scheduler never passes
`compliance.service.check_dispatch` — so the platform halt (the big red switch), the
tenant's spend cap and lifecycle, the agent gate and, decisively, the DNC list were all
evaluated at the moment we handed the call over and are never asked again. Hard rule 5
requires DNC additions to take effect before the next dispatch tick; a vendor-held call
has no tick. A number added to the DNC list at 21:30 would be dialled at 09:00 the next
morning by a scheduler that has never heard of it.

The second cost is a genuine double-dial, from our own code:
`campaign_dispatch._reap_stuck_dialing` returns a contact stranded in `dialing` to
`pending` after `STUCK_DIALING_AFTER` (`CALL_CAP_MAX_S` + 10 min ≈ 70 min). A call Bolna
is holding for twelve hours is exactly such a contact, so we would re-dial the person
while the vendor still intends to.

And the upside is close to nil: `check_dispatch` is upstream of every dial path in this
product (campaign tick, the D-21 "call this lead" button, the instant-lead-callback
webhook), it is half-open at 21:00:00 (D-311) where theirs is not specified to that
precision, and it is audited. Their window could only ever fire on our bug — and on our
bug it would convert a logged refusal into a silent, ungated, twelve-hours-later call.

**What that leaves open, and it is a real residual:** a console user can turn "Outbound
call timing restrictions" on from the Call Tab, and neither our publish body nor
`get_agent` would see it. There is no documented "off" value for `calling_guardrails` —
the schema is a bare object with no `nullable` and no default — so nothing can be sent to
pin it, and inventing `null` here is the guess `_agent_body`'s own `routes` paragraph
refuses to make. → **proposed OPERATIONS gate 21, §9.**

---

## 2. Auto-retry — the double-retry verdict, in full

### Who retries what, established

| | Bolna | Calevate |
|---|---|---|
| Trigger | `retry_on_statuses`, default `["no-answer", "busy", "failed"]` (`error` also supported) | `resolve_campaign_contact` on any non-`completed` terminal status |
| Attempts | `max_retries`, default 3, range 1–3 | `retry_policy.max_attempts`, default 3 |
| Spacing | `retry_intervals_minutes`, default `[30, 60, 120]` | `retry_policy.backoff_minutes`, default `[30, 120]` |
| Voicemail | `retry_on_voicemail`, default `false` | n/a — no `voicemail` status exists on this engine (D-351) |
| Where configured | `POST /call` or `POST /batches` — **per call / per batch, never on the agent object** | `campaigns.retry_policy` |
| Gate before the next ring | **none** | `check_dispatch` — halt, cap, hour, DNC, agent |

Citations: `guides/outbound/auto-retry.md` — *"Add the `retry_config` object when making a
call via the Make Call API or Create Batch API"*; the options table gives
`enabled` / `boolean` / **`false`** as the default, `max_retries` 3, `retry_intervals_minutes`
`[30, 60, 120]`.

### The verdict

**There is no double-dial today.** `BolnaEngine.start_outbound_call` posts exactly
`{"agent_id", "recipient_phone_number", "user_data"}`, and `retry_config.enabled`
defaults to `false`, so the vendor retries nothing. We never call `/batches` either
(grepped: zero references to the route anywhere in `apps/`, `packages/`, `scripts/`).
**One ladder runs, and it is ours.**

**Ours has to be the one that survives, and not because it was first.** Each rung of
`_record_failure` returns the contact to `pending` with `next_attempt_at`, so the next
dispatch tick re-runs the whole compliance gate before the second ring. Theirs re-dials
from their own scheduler. A number that joins the DNC list between attempt 1 and attempt 2
is called anyway. Under hard rule 5 that settles it: `retry_config` is not a knob to tune,
it is a key that must not be present. CLAUDE.md's "prefer engine built-ins" yields here
for the same reason TRD §5 already promotes the poller over the webhook — the built-in is
cheaper and the built-in is not the one that can be made to obey the law.

### The defect that WAS there — an agent-level toggle nothing stated

`agent-setup/call-tab.md` ships a Call Tab switch:

> **Auto Reschedule** — Automatically retry failed calls later

and `api-reference/agent/v2/create.md` declares the matching field on
`ConversationConfig` (i.e. `task_config`, the same block our `hangup_after_silence` and
`call_terminate` already live in):

> `auto_reschedule` · `type: boolean` · `default: false` · *"Automatically reschedule the
> call when the user asks to be called back at a later time"*

**The vendor contradicts itself about what this switch does** — the dashboard page calls
it a failed-call retry, the OAS calls it an in-call callback. Reported, not resolved: both
readings are hazardous for us and `false` refuses both, so the contradiction does not have
to be settled before we are safe.

* Read as the dashboard describes it, it is a **second retry ladder stacked on ours** —
  the double dial this section exists to rule out, arriving through a console click rather
  than through a code change.
* Read as the OAS describes it, it is worse in a subtler way. The window an in-call
  callback request is validated against is, per `guides/outbound/calling-guardrails.md`
  §"In-Call Reschedule Validation", ranked: (1) `calling_guardrails` — we send none;
  (2) **the agent prompt** — *"If no guardrails are set, the LLM reads time restrictions
  from the system prompt"*; (3) a 9AM–9PM default. **Priority 2 is a tenant-authored
  string.** A client script saying the business is available round the clock would have
  the model book a 23:00 callback, placed by Bolna, against Calevate's telemarketer
  registration. Hard rule 5 says no client-authored script can withdraw a compliance
  invariant.

Our body omitted the key. An omitted key is a field left as it was — the argument
`_agent_body` already makes for `agent_welcome_message` and `multilingual_config` — so a
console click would have survived every publish, and `get_agent` reads nothing that would
have shown it.

**FIXED.** `task_config` now states `"auto_reschedule": False`. Test:
`tests/bolna_call_flow_test.py::test_every_publish_refuses_the_in_call_callback_scheduler`,
sabotage-verified.

---

## 3. Batch calling vs our dispatch — no conflict, and the tick concern is already answered

We do not use `/batches` and should not: their batch has no compliance gate, and ours must
run (SECURITY-COMPLIANCE §3). That is the deliberate divergence and it is correct. What
the pages add is the price of that divergence, stated so nobody re-litigates it:

* **Their CSV validates one column.** `guides/outbound/batch-calling.md` — *"Only the
  **`contact_number`** column is validated for correctness. Other columns ... are passed
  through as-is without any validation."* Our `campaign_contacts` path validates E.164,
  dedupes on `UNIQUE (campaign_id, phone_e164)` and scrubs against DNC before a single
  row is dialable. Their batch does none of that.
* **Their scheduler has three sharp edges we would have inherited** (`quickstarts/batch.md`):
  `scheduled_at` must be ≥ 2 minutes ahead (else `400`); a `Z` suffix is **rejected with a
  `500`** (use `+00:00`); and *"Bolna **rounds the start up to the next 10-minute mark**,
  so a `12:02` request runs at `12:10`."* A campaign whose start time silently moves by up
  to ten minutes is not something a compliance window should be built on.
* **Their per-call status starts at `prepared`** — which is how the missing enum member was
  found; already fixed in the adapter by a sibling lane, cited to
  `api-reference/errors.md`.

**"Our dispatch tick must fit inside its 30-second schedule" is the wrong frame, and the
code already knows it.** `_tick_lease` is a Redis `SET NX PX` single-flight with
`TICK_LEASE_TTL_S = 330` against a 300s `job_timeout`, so a tick that overruns 30s does
not overlap the next one — the next one declines and returns. Fitting is not required;
not overlapping is, and that is enforced rather than hoped. The measured cost is ~0.25s
per tick (D-57). **No gap.**

---

## 4. Hangup and disconnect — no gap

`guides/outbound/hangup-calls.md` documents four mechanisms. Scored against
`_agent_body`'s `task_config`:

| Vendor mechanism | Vendor default | Ours |
|---|---|---|
| Silence detection (`hangup_after_silence`) | 10s | **sent, 10** |
| Duration limit (`call_terminate`) | **90s** | **sent, `effective_call_cap(...)`** — 600 default, DB-bounded 60–3600 |
| Prompt-based hangup | none | not used — deliberate |
| Personalised hangup message (`call_hangup_message`) | `null` | not used — deliberate |

Their own comparison table is the argument for the shape we already have: duration limits
are *"100%, always triggers at set time"* and are the *"safety net for runaway calls"*,
while hangup prompts are *"Prompt-dependent, may need tuning"* and the page warns *"it may
not be 100% accurate"*. We take the deterministic one and skip the probabilistic one.

**A call in this product cannot fail to terminate.** `agents.service.effective_call_cap`
resolves a NULL column to `CALL_CAP_DEFAULT_S` (600) and the table constraint bounds the
column to 60–3600, so `call_terminate` is always a positive integer on the wire. Notably
we are also **explicitly better than the vendor default**: inheriting their 90 seconds
would cut a receptionist off mid-appointment. Pinned by
`tests/bolna_call_flow_test.py::test_the_call_can_always_end_by_itself`, sabotage-verified
by setting it to 90.

**One ambiguity, reported not guessed.** `ConversationConfig` also carries
`check_if_user_online` (`default: true`) with `trigger_user_online_message_after`
(`default: 10`) — *"Seconds of user silence after which the agent asks whether the user is
still there."* That is the same 10 seconds as `hangup_after_silence`, and nothing
documents which wins. Either the call hangs up at 10s of silence or the agent asks a
question and waits. `call_terminate` bounds the outcome either way, so the money is safe;
what is unknown is what the caller experiences. → **pilot gate 4 addendum, §9.**

---

## 5. DTMF and IVR — do not adopt, and pin DTMF off

### Should we use their DTMF built-in? No.

`guides/inbound/dtmf.md`: *"Bolna accumulates the digits until `#` is pressed. The digits
are delivered to the agent as: `dtmf_number: <digits>`"* — and the worked example is
literally `dtmf_number: 9876543210`.

Digits are **not a side channel**. They arrive as a conversation message, so they land in
the transcript this platform stores, redacts, exports and retains. The vendor's own list
of what the feature is for is: *"PIN or OTP verification"*, *"Account or order number
lookup"*, *"Phone number capture"*, and *"when callers are uncomfortable speaking a number
aloud (e.g. a password or card number)"*.

**Our redactor does not save us, and this was measured rather than assumed.** A
keypad-entered 4-digit PIN arrives as `dtmf_number: 1234`:

* `redaction._PHONE_SPAN_RE` finds it but the numbering-plan validator rejects 4 digits;
* `_CARD_RE` needs 13–19 digits;
* `_OTP_RE` needs the literal word `otp|code|pin|password` within 20 non-digit characters
  of the digits, and what precedes these is `dtmf_number`.

So a caller's PIN would be stored in cleartext in `transcript_turns.text` and would pass
straight through `text_redacted`. A 6-digit account number likewise. (A 10-digit phone
number WOULD be masked, and a card number WOULD be masked — the hole is precisely the
short secrets the vendor's own examples lead with.)

Nothing in this product asks a caller to press a key, so the feature is all edge and no
upside today. **FIXED**: `task_config` now states `"dtmf_enabled": False` — present and
false rather than absent, because the Call Tab ships a "Keypad Input (DTMF)" switch a
console user can flip on a live agent. Test:
`tests/bolna_call_flow_test.py::test_every_publish_refuses_keypad_input`, sabotage-verified.

**If an IVR product ever wants it**, the decision gets made at that line, with a
`dtmf_number:` rule added to `workers/redaction.py` in the same change.

### Should we use their IVR built-in? Not now, and the blocker is not us.

`guides/inbound/ivr-inbound-calls.md` is a genuinely good fit on paper for the
receptionist: menu + collect steps, `conditional_next` branching, per-option `agent_id`
routing, collected data delivered to the agent in `recipient_data`, and — relevant to a
Telugu-first product — Indian voices in the IVR layer (`Polly.Aditi` = *"Hindi + Indian
English"*, `Polly.Raveena` = *"Indian English"*). It also routes *"natively without an
LLM"*, which is cheaper and faster than asking a model to branch.

Three reasons it is not adoptable today, in order of hardness:

1. **`IVR is currently supported for **Plivo** phone numbers only`** (their warning, verbatim).
   Every agent we publish already names `input`/`output` provider `plivo`, so this is not
   an immediate blocker — but §8 shows the 140-series promotional path needs Vobiz, and on
   Vobiz there is no IVR. So IVR is structurally available to the transactional/service
   side of the product and structurally unavailable to the promotional side.
2. **No Telugu voice.** The IVR voice list is Polly and tops out at Hindi/Indian English.
   A Telugu-first receptionist whose menu speaks Hindi is a worse product than one that
   speaks Telugu through Bulbul from the first word.
3. **It is a second place where a caller-facing script lives**, outside
   `compose_engine_prompt` and outside anything `verification.judge` reads back. The AI
   disclosure and recording notice (D-163) are spoken by the agent; an IVR that plays a
   `welcome_message` *before* the agent connects means the first thing a caller hears is a
   string no compliance surface in this repo has ever seen.

**Recommendation:** not now. Revisit only if a client asks for department routing AND is
on 160-series/Plivo AND the menu can be English/Hindi — and even then, point 3 needs a
composition rule first.

---

## 6. Latency — our budget is realistic for the half it names, and is not caller-observed

### Their measurement model

`concepts/latency.md` gives a target and a stage budget:

> Bolna targets **sub-600ms end-to-end** for a natural conversation feel.

with Endpointing 50–300ms → Transcription 50–150ms → LLM first token 100–400ms →
Synthesis first chunk 80–200ms. **Their own stage midpoints sum to ~740ms against their
own 600ms target**; the low end sums to 280ms and the high end to 1050ms. Read the 600ms
as an aspiration, not a contract.

`concepts/call-latencies.md` gives the per-execution object: `latency_data` with
`stream_id`, `time_to_first_audio`, **`region`** (*"e.g., `in` for India"*), and per-turn
`transcriber` / `llm` / `synthesizer` breakdowns. Their own bottleneck thresholds are
transcriber >100ms/sequence, **LLM TTFT >1000ms**, synthesizer >500ms — and their own
worked example shows a turn-1 `time_to_first_token` of **1633.04ms**, i.e. their sample
data is above their own alarm line on the first turn of a call.

### Scored against ours

* **TRD §6.2's estimate is confirmed by the vendor.** It says the external-KB route costs
  *"two extra hops ... realistically +150–400ms"*. `concepts/call-flow.md` says
  *"Tool calls add 50–500ms of latency depending on the tool's response time."* Their
  range brackets ours. TRD §6.2's conclusion (v1 keeps in-call retrieval on the built-in
  KB) survives contact with first-party numbers.
* **The tool-call timeout is STILL undocumented.** Searched across the whole mirror
  including `tool-calling/`, `concepts/` and both latency pages: the only `timeout`s
  documented anywhere near a call are `call_terminate` and the IVR's 5-second
  caller-input timeout. OPERATIONS §2 gate 8's *"no timeout is documented"* is accurate
  against 335 pages, not just against a blocked docs host. That is a gate staying open for
  a verified reason, which is worth more than the gate being closed.
* **Our 100ms budget is realistic, and the way it is stated invites a wrong reading.**
  `tool_routes.py` measures the SERVER half — D-109 measured p95 1.4ms single-flight and
  ~143ms at 250 concurrent. That is comfortably inside 100ms at real concurrency and
  outside it at 250. But a caller does not experience our server half. A tool-using turn
  costs: their pipeline (280–1050ms) **+ their tool overhead (50–500ms)** + our endpoint
  **+ a second LLM pass**, because `concepts/call-flow.md` step 4 has Bolna *"Feed the
  tool result back to the LLM"* and resume. So "the 100ms budget is met" and "the caller
  waits 100ms longer" are different statements, and only the first is ours to make.
  → **proposed OPERATIONS gate 8 amendment, §9.**

### Two tuning knobs we inherit silently — proposed, not taken

Both are the same argument `_agent_body` already makes for `temperature` and `max_tokens`
("a vendor default is somebody else's release note"), and neither is taken here because
the right value is a measurement this repo does not yet have (gate 4 owns the stopwatch)
and because changing what every caller hears from a call-flow audit would be a change
nobody measured.

* **`transcriber.endpointing`** — `default: 250` (OAS), and `concepts/latency.md` says
  *"Increase to 400–500ms for callers who pause mid-sentence (non-native speakers,
  elderly). Decrease toward 100ms for fast-paced sales scripts."* Our callee population is
  named in that first sentence. We send no value.
* **`synthesizer.buffer_size`** — `default: 250` (OAS) while the same vendor's latency
  guide says *"A buffer of 100–150 characters is typical"* and *"Smaller buffers start
  audio sooner"*. **Their schema default is roughly double their own recommendation**, and
  we are on the default. This is the cheapest available latency win on the whole page and
  it costs one integer.

Also recorded: `concepts/latency.md` — *"A caller in India connecting to a US-hosted
telephony provider adds ~100–200ms round-trip"*, India providers listed as Plivo, Exotel,
Vobiz, and *"For the lowest latency within India, enable Indian server configuration"*.
That last one is `enterprise/indian-server-configuration.md`, which is GAP-WORKLIST
LEAD-C's subject and another lane's page — but it is now corroborated from a second page:
`latency_data.region` returns `in`, so the platform HAS a region concept and reports it
per execution. Given how weak CLAUDE.md says the residency claim is, a per-execution
`region` field the vendor already returns is worth capturing at gate 4 beside the
stopwatch.

---

## 7. Caller identification on inbound — no overlap with D-23, and one hard no

**No overlap.** D-23 is OUTBOUND: we deliver a finished lead into the client's Google
Sheet (`workers/sheets_sync.py`, `outbound_webhooks.kind='google_sheets'`). Bolna's
feature is INBOUND and pre-call: the engine looks the caller's number up and merges the
result *"into the AI prompt before the call begins"*. Different direction, different data,
different lifecycle. Nothing to consolidate.

**We have nothing equivalent.** `leads.is_repeat_caller` is set by `workers/pipeline.py`
AFTER the call. A regular customer ringing the receptionist today is greeted as a stranger.

### The three variants, scored

| Variant | Verdict |
|---|---|
| **Google Sheets** | **Hard no.** *"Link a **publicly accessible** Google Sheet with user data."* A world-readable spreadsheet of Indian consumers' names and phone numbers is a DPDP breach on data we are the processor for, and no DPA we sign can survive it. It is also a client-facing footgun: the button exists in Bolna's console. |
| **CSV upload** | No. It puts a copy of the client's customer list on Bolna's side, stale from the moment it is uploaded, with a deletion story we do not control (DPDP erasure would have to reach it). |
| **Internal API** | **The right seam, if we want the feature.** Data never leaves us; Bolna sends us a number and we answer. |

The API variant is settable through the body we already POST — `agent_config.
ingest_source_config` with `source_type: "api"`, `source_url`, and `source_auth_token`
(*"Bearer token for API authentication"*, and both fields are `required` when
`source_type` is `api`). The vendor calls our endpoint as
`GET …?contact_number=+91…&agent_id=…&execution_id=…`.

**Three constraints if it is ever built**, so the next person does not discover them at
implementation time:

1. **It is on the in-call path** — the lookup happens before the call begins, so it
   belongs in `apps/voice-runtime` (India co-located, already the home of in-call tool
   endpoints), not in `apps/api`. It gets the `<500ms` ack discipline of hard rule 3.
2. **The caller's phone number arrives in a QUERY STRING.** Hard rule 6 says never log
   phone numbers; a GET with the number in the URL lands in every access log by default
   (`infra/nginx/`, any proxy in front). The route needs an explicit log-suppression rule,
   not a hope.
3. **It is the one Bolna surface that supports a bearer token.** Their webhooks sign
   nothing (which is why TRD §5 uses a source-IP allowlist), but `source_auth_token` is a
   real credential. Belt and braces: bearer AND `bolna_source_ips`.

**Also worth having independently:** `ConversationConfig.disallow_unknown_numbers`
(`default: false`) — *"Only allow incoming calls from the numbers you've sourced using
IngestSourceConfig"* — and `inbound_limit` (`default: -1`, unlimited) — *"the number of
times each phone number is allowed to call"*. The second is an abuse/cost control on the
inbound receptionist that this product currently does not have in any form: one persistent
caller can burn unbounded minutes against a client's wallet, and nothing stops them.

**Not pinned in the agent body**, deliberately, and for `_agent_body`'s own stated reason:
`ingest_source_config` is declared `$ref: IngestSourceConfig` with no `nullable` and no
default, so `null` is not a documented value and sending one could break every publish.
The residual — a console-configured public Google Sheet surviving our publishes — is
gated instead (§9).

---

## 8. **FOUNDER DECISION** — the `VoiceEngine` port models an outbound-only world, and three things break on it

Three separate failures were found by three different pages in this lane. They have one
root cause, so they are written once: **`phone_numbers` is a rich table and the
`VoiceEngine` protocol cannot express any of it.** The protocol's full surface is
`create_agent`, `update_agent`, `get_agent`, `delete_agent`, `start_outbound_call`,
`end_call`, `transfer`, `provision_number`, `set_llm_credential` and the three KB
methods. Numbers can be BOUGHT and nothing else — not attached to an agent, not named as
a caller ID, not carried per campaign.

### Symptom 1 — the DLT-registered number never reaches the dial

* `guides/outbound/making-outgoing-calls.md`: the outbound caller ID is
  `from_phone_number` on `POST /call` — *"Add your purchased phone number or your own
  connected phone number in `from_phone_number` field"*. Omit it and Bolna uses its own
  pool; their table says an Indian callee *"will recieve the phone call from `+91` prefix
  phone"*.
* `BolnaEngine.start_outbound_call` posts `{agent_id, recipient_phone_number, user_data}`.
  **There is no `from_phone_number`, and there is nowhere to put one**: `CallContext`
  carries no number and `start_outbound_call(ref, to, ctx)` has no parameter for one.
* Meanwhile `campaigns.service._channel_blockers` blocks a launch AND every dispatch tick
  unless the campaign's number has the right `series` for its classification and
  `dlt_status == 'registered'`, and `phone_numbers` already holds the `e164`.

**So the number our compliance gate approves is not the number that dials.** Every
campaign call goes out on a Bolna pool number: the 140/160-series check, the DLT header
registration and the whole PE/TM model gate a number that never appears on the callee's
handset, while the callee, the TSP and the complaint trail see Bolna's instead.
`_channel_blockers` is currently a gate on a fact with no consequence — which is worse
than an absent control, because it reports green.

(`CartesiaEngine` is not the counter-example it looks like: it does refuse to dial without
`from_number_id` (`engine_caller_id_not_configured`), but it reads that from adapter-wide
config — one number for the whole platform — which is equally wrong under a model where
each tenant's Principal Entity has its own registered header. The gap is in the PORT.)

### Symptom 2 — the inbound receptionist is never routed at the engine

`guides/inbound/receiving-incoming-calls.md` is unambiguous about the required step:

> You will need to assign a phone number to your Bolna Voice AI agent for automatically
> answering all incoming calls on that phone number

and the API for it is `POST /inbound/setup {agent_id, phone_number_id}`, with
`POST /inbound/unlink` to reverse it (`quickstarts/inbound.md`).

**Neither route is called anywhere in this repository, and no protocol method could call
them.** `agents.service.register_number` writes `phone_numbers.agent_id` — with real care,
including the D-331 cross-tenant FK fix — and that write reaches our database and stops.
`engine_agent_routes` is not the missing wire: it maps `engine_agent_ref → (tenant, agent)`
so an INCOMING WEBHOOK can be attributed, which is the opposite direction.

So an admin assigns a receptionist to a number in our console, the console says it worked,
and the number answers with whatever was last set in Bolna's dashboard — or does not
answer at all. Inbound is half this product (CLAUDE.md), and its first configuration step
is a screen with nothing behind it.

### Symptom 3 — no agent we publish can carry a 140-series promotional campaign

* `guides/inbound/obtaining-regulated-phone-numbers.md` — **140-series (telemarketing/
  promotional) is carried by Vobiz; 160-series (transactional/service) by Plivo.** Their
  table, verbatim.
* `_agent_body` hardcodes `"input": {"provider": "plivo"}` / `"output": {"provider":
  "plivo"}` for every agent, with a comment that already guessed the right reason ("with
  Plivo the 160-series (transactional) carrier"). **That guess is now VERIFIED.**
* `campaigns.service.SERIES_FOR_CLASSIFICATION` maps `promotional → ("140",)`.

A promotional campaign therefore passes every gate we have and is then handed to an agent
wired to the wrong carrier. D-357 already names "a 140-series promotional agent belongs on
Vobiz" as a gap; what is new is that it is a **verified blocking gap on a whole product
line**. A sibling lane has landed the purchase half of this in
`campaigns/provisioning.py::KNOWN_PROVIDERS` (which was missing `plivo` entirely); the
half named here is different and still open — the AGENT's telephony leg, which is a
literal in `_agent_body` because `AgentConfig` carries no telephony provider.

### Why none of it was fixed in this lane

Every candidate fix edits `packages/shared/src/calevate_shared/engine.py` — `CallContext`
grows a from-number, the protocol grows an inbound-binding method, `AgentConfig` grows a
telephony provider — and that file belongs to another lane in this sweep. The data, the
gates and the adapter sides are all ready; the port is the missing hop in all three.

### Two commercial facts that belong in front of the founder while symptom 3 is open

Both from `guides/inbound/obtaining-regulated-phone-numbers.md`, both external blockers
rather than engineering:

* **160-series header registration requires an RBI/SEBI certificate** as proof of
  regulatory compliance. A dental clinic or a coaching centre cannot produce one. Our
  model lets any tenant run a `transactional` or `service` campaign on 160/standard; if
  that route is closed to non-BFSI SMBs, every SMB lands on 140/Vobiz — the exact path no
  published agent can carry.
* **Principal Entity registration on the TATA Teleservices DLT portal costs ₹5,900**, per
  client, with a Letter of Authorisation signed by a director named in the MOA, and the
  contact details in that LOA become permanent (*"cannot be easily changed after
  submission"*). A real onboarding step with a real price and a real irreversibility, per
  tenant.

Also confirmed and worth recording: **numbers bought through Bolna's own dashboard cannot
satisfy our gate.** `guides/inbound/buying-phone-numbers.md` offers Indian numbers only as
geographic landline ranges — Karnataka `+9180`, Maharashtra `+9122`, Gujarat `+9179`, NCR
`+9111`, at $5/month — and none is 140 or 160. D-05's decision to source numbers from the
telephony vendor directly is **verified correct** rather than merely preferred.

### Proposed ROADMAP §7 decision-log entry (exact text)

> | D-420 | **The `VoiceEngine` port models an outbound-only world: the number our compliance gate approves never reaches the dial, and the inbound receptionist is never routed at the engine** | Three symptoms, one root cause — `phone_numbers` carries `e164`, `series`, `provider`, `engine_number_ref` and `agent_id`, and the protocol can express none of it. **(1)** Bolna's outbound caller ID is `from_phone_number` on `POST /call` — *"Add your purchased phone number or your own connected phone number in `from_phone_number` field"* — and omitting it falls back to their centralised pool, which for an Indian callee is *"a `+91` prefix phone"* (VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/guides/outbound/making-outgoing-calls.md`). `BolnaEngine.start_outbound_call` posts `{agent_id, recipient_phone_number, user_data}` and `CallContext` has no field for a from-number. So `campaigns.service._channel_blockers`, which refuses a launch and every dispatch tick unless the campaign's number carries the right 140/160 series and `dlt_status = 'registered'`, gates a number that never rings on the callee's handset — a compliance control that controls nothing and reports green. **(2)** `POST /inbound/setup {agent_id, phone_number_id}` is the required step to make an agent answer a number (*"You will need to assign a phone number to your Bolna Voice AI agent for automatically answering all incoming calls"*, `guides/inbound/receiving-incoming-calls.md`); it is called nowhere in this repository and no protocol method could call it. `agents.service.register_number` writes `phone_numbers.agent_id` and stops at our database, so an admin assigns a receptionist and nothing at the engine changes. `engine_agent_routes` is not the missing wire — it attributes an incoming webhook, the opposite direction. **(3)** 140-series is carried by Vobiz and 160-series by Plivo (`guides/inbound/obtaining-regulated-phone-numbers.md`), while `_agent_body` hardcodes `input`/`output` provider `plivo` for every agent and `SERIES_FOR_CLASSIFICATION` maps `promotional → ("140",)` — so a promotional campaign passes every gate and is handed to an agent on the wrong carrier (D-357's gap, now verified rather than suspected). **Fix, one shape for all three:** `CallContext` grows `from_e164: E164 \| None`; the protocol grows `bind_inbound_number(ref, number)` / `unbind_inbound_number(number)` with a capability flag so an engine that cannot do it refuses loudly rather than silently; `AgentConfig` grows a telephony provider derived from the number's series. `agents.service.dispatch_call` resolves the from-number from the campaign's `phone_numbers` row, and the dial gate refuses a campaign dial with no from-number for the same reason it refuses an agent with no AI-disclosure sentence. | **All three were invisible because each half is correct in isolation.** The gate reads a real column; the adapter sends a valid body; `register_number` even carries a cross-tenant FK fix (D-331) for a field nothing downstream consumes. Nothing in the tree ever stated that the gated number and the dialled number are the same number, or that assigning an agent to a number should reach the engine, because there was no seam at which to state it — and a protocol that cannot express a claim cannot be tested for it either. **The generalisable rule: when a table is richer than the port that consumes it, the surplus columns are not future-proofing, they are a screen that lies.** |

---

## 9. Proposed OPERATIONS §2 gate text (exact)

Two new gates and two amendments. Written to be applied centrally. **The gate numbers below were provisional and BOTH SURVIVED renumbering** — three lanes
proposed a "21" in this sweep and these two were applied as **21** and **22** (the
toolchain and silence-probe proposals moved to 24 and 23, the telephony ones to 25–27).

**New gate 21 — the Call Tab switches our body cannot state**

> | 21 | Call Tab drift | For every published agent, open the Bolna Call Tab and confirm **Outbound call timing restrictions is OFF** and **no ingest source is configured**. Both are console switches with no documented "off" value our publish body can send — `calling_guardrails` is a bare object with no `nullable`/default, `ingest_source_config` is a `$ref` with neither — so `_agent_body` cannot pin them the way it pins `auto_reschedule`, `dtmf_enabled` and `multilingual_config`. **Restrictions ON is not a safety feature for us, it is a hazard:** their guardrail HOLDS an out-of-window dial and fires it later from their scheduler, which never re-runs `compliance.service.check_dispatch` — so the DNC list, the big red switch and the spend cap are evaluated once and never again (hard rule 5 requires DNC additions to take effect before the next dispatch tick), and `campaign_dispatch._reap_stuck_dialing` would re-dial the same person after ~70 minutes. **An ingest source set to CSV or Google Sheet** puts the client's customer list on Bolna's side; the Sheets variant requires a *publicly accessible* sheet (`customizations/identify-incoming-callers.md`), which is a DPDP breach on data we are the processor for. Record what each agent's tab shows, not what we expect it to show. |

**New gate 22 — which switch `auto_reschedule` actually is**

> | 22 | `auto_reschedule` semantics | The vendor documents this one field two different ways and we refuse it under both, so this gate is not blocking — it is here so the refusal has a reason on file rather than a fear. `api-reference/agent/v2/create.md` says *"Automatically reschedule the call when the user asks to be called back at a later time"*; `agent-setup/call-tab.md` says *"Automatically retry failed calls later"*. On a pilot account, set it true on a throwaway agent and observe: does a caller asking for a callback produce a scheduled execution, or does a `no-answer` produce a second one? If it is the retry reading, it is a second ladder stacked on `campaign_dispatch._record_failure` and the refusal is permanent. If it is the callback reading, the refusal is still right (an in-call callback is placed by their scheduler and passes no gate of ours) but the in-call-reschedule window question in `calling-guardrails.md` §"In-Call Reschedule Validation" becomes answerable. |

**Amendment to gate 8 (in-call tool p95) — measure the caller's delta, not our server's**

> Add: **the number to record is the CALLER-OBSERVED delta, not our endpoint's ack.**
> `tool_routes.py` measures the server half into `tool_ack_ms` and D-109 already put that
> at p95 1.4ms single-flight / ~143ms at 250 concurrent — comfortably inside TRD §6.2's
> 100ms and not the thing the caller waits for. The vendor's own model says a tool call
> costs *"50–500ms ... depending on the tool's response time"* ON TOP of our endpoint
> (`concepts/call-flow.md`), and their step 4 feeds the tool result back to the LLM, so a
> tool-using turn also pays a SECOND time-to-first-token. Record `latency_data.
> time_to_first_audio` for a turn with a tool call and for one without, on the same agent,
> and report the difference. Their own bottleneck line is LLM TTFT > 1000ms
> (`concepts/call-latencies.md`), and their own sample payload shows 1633ms on turn 1.

**Amendment to gate 4 (latency stopwatch) — two knobs and one field**

> Add: capture `latency_data` verbatim once — it carries `stream_id`,
> `time_to_first_audio` and **`region`** (*"e.g., `in` for India"*,
> `concepts/call-latencies.md`), and a per-execution region field the vendor already
> returns is worth having while the residency claim rests on a human attestation in a
> portal. **Do not store the `transcriber.turns[].turn_latency[].text` entries** — they
> carry recognised transcript text, which is hard rules 5/6; that concern is recorded in
> `apps/api/engine/bolna.py`'s module docstring as a claim and is now VERIFIED by the
> vendor's own worked payload. While the stopwatch is out, also settle the two defaults we
> inherit unstated: `transcriber.endpointing` (`default: 250`, and their guide says
> *"Increase to 400–500ms for callers who pause mid-sentence (non-native speakers,
> elderly)"* — our callee population) and `synthesizer.buffer_size` (`default: 250`, while
> the same guide calls *"100–150 characters"* typical and says smaller buffers start audio
> sooner). And confirm whether `hangup_after_silence` or `check_if_user_online` /
> `trigger_user_online_message_after` wins when both are 10 seconds; nothing documents it.

---

## 10. Proposed ROADMAP §7 decision-log entry for the change made in this lane (exact)

> | D-419 | **Two agent-level switches could place a call, or record a caller's PIN, without anything in this repo knowing** | `_agent_body`'s `task_config` now states `auto_reschedule: False` and `dtmf_enabled: False`. Both are `ConversationConfig` booleans defaulting to `false` (VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/api-reference/agent/v2/create.md` — the same schema `hangup_after_silence` and `call_terminate` already come from), so this changes no behaviour today and closes two paths that a console click could have opened on a live agent. **Both have a Call Tab switch** ("Auto Reschedule", "Keypad Input (DTMF)" — `agent-setup/call-tab.md`), an omitted key is a field left as it was, and neither is in anything `get_agent` reads back. **`auto_reschedule`** would let a callback be scheduled by BOLNA'S scheduler, which never re-runs `compliance.service.check_dispatch` — halt, cap, agent, hour and DNC evaluated once and never again, against hard rule 5's "DNC additions propagate before the next dispatch tick" — and with no `calling_guardrails` set, the window such a request is validated against is, in the vendor's own priority order, **the agent prompt**: a tenant-authored string (`guides/outbound/calling-guardrails.md` §"In-Call Reschedule Validation"). The vendor also describes the same field as a failed-call retry on its dashboard page, which would be a second ladder stacked on `campaign_dispatch._record_failure`; `False` refuses both readings, so the contradiction is reported (gate 22) rather than resolved before we are safe. **`dtmf_enabled`** delivers keypad digits INTO the conversation as `dtmf_number: <digits>` (`guides/inbound/dtmf.md`), i.e. into the transcript we store, redact and export — and the vendor's own use cases are PIN/OTP verification, account numbers and *"a password or card number"*. Measured against `workers/redaction.py` rather than assumed: a 4-digit PIN arrives as `dtmf_number: 1234`, which is too short for `_PHONE_SPAN_RE`'s numbering-plan validator, too short for `_CARD_RE`, and invisible to `_OTP_RE` because that one needs the literal word otp/code/pin/password within 20 characters and gets `dtmf_number`. Three absences are pinned alongside in `tests/bolna_call_flow_test.py`: `retry_config`, `bypass_call_guardrails`, and the complete `POST /call` key set. | **The double-retry hunt came back negative and produced this instead.** `retry_config.enabled` defaults to `false` and our dial body never sent it, so no person has ever been double-dialled by two stacked ladders — but the property was resting on nothing written down, and the vendor's own docs recommend `bypass_call_guardrails: true` "for Testing in Development", which is the bypass CLAUDE.md hard rule 5 forbids by name. An absence is the one property a reviewer cannot see in a diff. **`calling_guardrails` is deliberately NOT pinned**, against the first instinct: their window does not refuse an out-of-window dial, it HOLDS one and fires it later ungated, and our own gate is upstream, half-open at 21:00:00 (D-311) and audited — so enabling theirs would convert a logged refusal into a silent twelve-hours-later call and hand `_reap_stuck_dialing` a contact to re-dial at ~70 minutes. There is no documented "off" value to send, so the residual is gate 21 rather than a `null` invented here — the same restraint `_agent_body` already applies to `LlmAgentV2.routes`. |

---

## 11. What this lane deliberately left alone

* **`calling_guardrails`** — argued at length in §1. Not sent; gated instead.
* **`ingest_source_config`** — no documented null; §7. Gated instead.
* **`transcriber.endpointing` and `synthesizer.buffer_size`** — the right values are a
  measurement gate 4 owns, and changing what every caller hears from a call-flow audit
  would be a change nobody measured. Proposed in §6 with the evidence attached.
* **The IVR built-in** — three blockers, one of them (no Telugu voice) product-fatal today.
* **All three symptoms in §8** — the from-number on the dial, the inbound
  number-to-agent binding, and the per-series telephony carrier on the agent — need
  `packages/shared/src/calevate_shared/engine.py`, which is another lane's file. Exact
  decision-log text supplied instead.
* **`_STATUS_MAP` / `prepared`** — found independently here from
  `api-reference/errors.md`, and already landed by a sibling lane with the same citation
  by the time this lane reached the edit. Verified present and correct; not touched.
* **The three webhook source IPs** (`concepts/call-flow.md`, `quickstarts/api.md`) —
  found here, already fixed as D-414 by a sibling lane during this session.
  `DEFAULT_BOLNA_SOURCE_IPS` now holds all three. Verified; not touched.
* **The 140/160 → Vobiz/Plivo mapping, the ₹5,900 PE registration and the RBI/SEBI
  certificate requirement** — Lane E's pages. Reported in §8 only because they decide
  whether the dial path can run at all.
