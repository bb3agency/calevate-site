# Bolna tool-calling, integrations and template library — audited against the mirrored docs

**Scope.** The 5 `tool-calling/` pages, the 20 `tutorials/` pages, the 16 `voice-agents/`
pages and `agent-setup/tools-tab.md`, read end to end from
`bolna-findings/mirror/pages/`, against this tree. Every claim below cites a mirrored path
and quotes the line. Where the vendor is silent or contradicts itself, that is reported as
silence or contradiction — it is not resolved by inference (D-31, D-32, D-350).

**One-line verdict.** Transfer is now VERIFIED as an agent-object tool and stays
`transfer=False` for a reason that has changed again; the in-call tool timeout is
**documented nowhere**, so our 100ms budget has no vendor ceiling to check against and
gate 8's "no timeout is documented" is confirmed rather than closed; Cal.com is usable by
clients but has nowhere in our onboarding to live; the tutorials yielded **two payload
fields our adapter did not know and one it was right to ignore**; and the template library
contains **no prompt text at all**, so the prompt-craft half of that brief has no subject.

---

## 0. Changes made in this pass

| File | Change | Verified |
|---|---|---|
| `apps/api/engine/bolna.py` | New `_check_transfer_leg`, called from `_snapshot`. Pages `CORE_LOGIC`/`engine_transfer_leg_unhandled` when an execution carries `transfer_call_data` — a second call leg with its own recording and its own cost that this tree drops on the floor. | 2 sabotages, §1.4 |
| `tests/bolna_snapshot_test.py` | 7 tests (4 functions, one parametrised ×4) pinning the alarm and the hard-rule-6 bound on what it may say. | red→green pasted, §1.4 |
| `docs/FLOWS.md` §3 | `transfer_call (warm to client staff…)` — **"warm" was a claim nothing supported**. Replaced with what the vendor actually documents and the three things that must be settled first. | doc only |

Nothing else in this lane was changed. Where a finding needed a shared model, an
OPERATIONS gate row or a ROADMAP entry, the proposed text is in §7 and §8 rather than
applied — those files are owned centrally this pass.

---

## 1. Call transfer to a human

### 1.1 Is it verified now? Half of gate 18 is answered YES, from the vendor's own OAS

Gate 18 asks two things: *"(a) does the hosted `/v2/agent` body accept a transfer tool
definition, and under which key? (b) does any REST route transfer a live execution?"*

**(a) YES, and the key is `transfer_call`.** The hosted agent-create body binds an
`ApiTools` block —
`bolna-findings/mirror/pages/api-reference/agent/v2/create.md:690-707`:

```
    ApiTools:
      type: object
      properties:
        tools:
          type: array
          items:
            oneOf:
              - $ref: '#/components/schemas/TransferCallTools'
        tools_params:
          $ref: '#/components/schemas/TransferCallToolParams'
```

and `TransferCallTools` (same file, `:1114-1156`) fixes the key:

```
    TransferCallTools:
      title: transfer_call
      properties:
        name:
          description: Any unique name for this function tool
          example: transfer_call_support
        key:
          enum:
            - transfer_call
          default: transfer_call
```

The destination is CONFIG, exactly as our D-262 reading of their OSS said —
`TransferCallToolParams` (`create.md:1157-1187`) carries a `param` that is *"Stringified
JSON of the tool schema"* with the example `{"call_transfer_number":
"+19876543210","call_sid": "%(call_sid)s"}`. The UI page agrees: **Transfer to phone
number** is *"Destination number in international format (e.g. `+19876543210`)"*
(`tool-calling/transfer-calls.md:24`). So the model picks WHEN, never WHERE.

**(b) NO.** No route in the mirrored `api-reference/` transfers a live execution. The
transfer surface is entirely agent-object configuration plus one read-side object
(`transfer_call_data`). `VoiceEngine.transfer(call_id, to, warm)` — an out-of-band
instruction to a call already in flight — remains unimplementable.

**So `BOLNA_CAPABILITIES.transfer=False` stays correct, and its reason changes a third
time.** It was "nobody checked" (pre-D-262), then "the built-in is an in-call tool
configured at publish time, read from their OSS" (D-262). It is now: *the built-in is an
in-call tool configured at publish time, confirmed in the vendor's own hosted OpenAPI
document, and the Protocol's shape has no vendor route at all.* That is a stronger
statement standing on VERIFIED-OAS rather than VERIFIED-OSS. The capability flag does not
move.

### 1.2 Warm or cold? THE VENDOR DOES NOT SAY, AND OUR BLUEPRINT CLAIMED IT DID

`docs/FLOWS.md` §3 listed `transfer_call` as *"(warm to client staff during business
hours)"*. Searched across the entire mirror:

```
grep -rniE "warm transfer|cold transfer|attended transfer|blind transfer|consultative" pages/
→ (no matches)
```

Not one page uses warm, cold, attended, blind or consultative about a transfer. What the
docs DO describe is consistent with a **cold/blind** handoff and stops short of saying so:
the agent speaks a pre-tool message — *"Sure, I'll transfer the call for you. Please wait a
moment."* (`transfer-calls.md:25`) — and the worked example ends *"Agent triggers
transfer\_call function → Call is routed to configured sales number"*
(`transfer-calls.md:174`). There is no described step in which staff are briefed while the
caller holds, and the only briefing mechanism offered is **fire-and-forget**:

> *"The pre-call webhook is **fire-and-forget**. A slow or failing webhook endpoint never
> blocks or delays the transfer itself."* — `transfer-calls.md:39`

A briefing channel that cannot delay the transfer is by construction not a warm handoff.
**That is evidence, not proof, and it is recorded as evidence.** FLOWS.md now says the
vendor documents this nowhere; gate 18 gets a criterion to observe it (§7).

### 1.3 THE COMPLIANCE VERDICT

**Transfer must not be offered until three things are settled, and only one of them is
about the vendor.**

**(i) The recording and the transcript boundary moves, and there is a second recording we
have never seen.** The transferred leg is a first-class object with its own everything —
`bolna-findings/mirror/pages/api-reference/agent/v2/get_agent_execution.md:270-328`:

```
    TransferCallData:
      properties:
        provider_call_id: …
        status: …
        duration:  description: Total duration of this transferred call in seconds
        cost:      description: Total cost incurred for this transferred call
        to_number: … from_number: …
        recording_url:
          description: Recording URL for the transferred call
        hangup_by: … hangup_reason: … hangup_provider_code: …
```

The vendor even serves it from a dedicated route —
`bolna-findings/mirror/pages/changelog/may-2026.md:99-103`:

> ```
> https://api.bolna.ai/recordings/call/{execution-id}
> https://api.bolna.ai/recordings/transfer/{execution-id}
> ```
> *"Use the `transfer` variant if the call included a transfer leg."*

**`transfer_call_data` appears nowhere in this repository.** `_snapshot` reads
`telephony.get("recording_url") or payload.get("recording_url")` and nothing else, so the
transfer leg's audio would be: never copied by `pipeline`'s recording stage, never subject
to our retention policy, and **unreachable by a DPDP erasure**, while continuing to exist
on the vendor's side. Its `cost` is a per-call cost outside `total_cost`/`cost_breakdown`
that hard rule 7 never meters.

**(ii) The disclosure obligations do not evaporate at the handoff, and nothing in our tree
carries them across it.** Hard rule 5's guarantee is enforced by appending to the ENGINE
AGENT's prompt (`compose_engine_prompt`) and verified against the engine on publish and on
drift. A human who picks up the transferred leg is not covered by a sentence a different
party spoke to a different leg. Two questions are ours and neither is answerable from
vendor docs: whether the recording notice the caller already heard extends to a leg
recorded separately by the same platform, and whether the AI disclosure needs an inverse
("you are now speaking to a person") at the handoff. These are legal questions for the
founder, not engineering questions — §8.

**(iii) A per-agent escalation number becomes ENGINE config, not one of our columns.**
`TransferCallToolParams.<name>.param` holds the destination as a stringified JSON blob
inside the agent object. That means the number is set at publish time, lives on the vendor,
and is not covered by our drift sweep (which proves the PROMPT, not the tool list). D-262
already called this "a design decision, not a flag flip"; the OAS confirms the shape.

### 1.4 What was DONE about it, and the red/green

We cannot carry the transfer leg without touching a shared model and settling (i)–(iii), so
the correct move is not to handle it — it is to make the silent case impossible. **The
Transfer Call tool is enabled from a console toggle** — *"Click **+ Add** next to any tool
to enable it for your agent."* (`agent-setup/tools-tab.md:19`) — i.e. it can appear on an
agent we published **without a deploy**, and today that would be invisible.

`apps/api/engine/bolna.py::_check_transfer_leg` now pages on the first execution that
carries one, from every path that snapshots an execution (webhook and poller alike).
Hard rule 6 governs what it may say: `TransferCallData` carries two E.164 numbers and a URL
resolving to caller audio, so the alert names the execution id, the leg's vendor status and
two derived booleans, and nothing else.

**Sabotage 1 — delete the call site:**

```
--- SABOTAGE 1: call site deleted ---
>       detail = str(_alert_records(caplog)[0].get("detail"))
E       IndexError: list index out of range
=========================== short test summary info ============================
FAILED tests/bolna_snapshot_test.py::test_an_execution_with_a_transfer_leg_pages
FAILED tests/bolna_snapshot_test.py::test_the_transfer_alarm_names_no_phone_number_and_no_recording
2 failed, 32 passed, 1 warning in 0.36s
```

**Sabotage 2 — violate hard rule 6 by pasting `to_number` into the alert:**

```
--- SABOTAGE 2: hard rule 6 violated (to_number pasted into the alert) ---
E           AssertionError: '+919876543210' must never reach a log line
E             eted', to +919876543210, second recording present: True, separate cost present: True. …
=========================== short test summary info ============================
FAILED tests/bolna_snapshot_test.py::test_the_transfer_alarm_names_no_phone_number_and_no_recording
1 failed, 33 passed, 1 warning in 0.30s
```

**Restored — green:**

```
--- RESTORED, expect GREEN ---
34 passed, 1 warning in 0.29s
```

(Re-run after other lanes landed their own tests in the same file: `7 passed, 39
deselected` for `-k "transfer_leg or transfer_alarm or ordinary_execution_is_silent"`.)

### 1.5 The transfer tool's pre-call webhook, and one thing to be careful of

`transfer-calls.md:34-124` documents an optional pre-call webhook. Two fields, both inside
the tool's `value`: `pre_call_webhook_param` (the JSON body template, and *"This is the
on/off switch — if it is not set, no pre-call webhook fires"*, `:46`) and
`pre_call_webhook_url` (`:47`). Substitutions available at transfer time are `%(reason)s`,
`%(summary)s`, `%(call_transfer_number)s`, `%(call_sid)s` (`:53-58`).

**The trap, in the vendor's own warning** (`transfer-calls.md:114`):

> *"when `pre_call_webhook_param` is set without a `pre_call_webhook_url`, the pre-call
> webhook is sent to your agent's configured Webhook URL. If you already use that endpoint
> for post-call execution webhooks, it will now also receive pre-call webhooks."*

Our agent-level webhook URL **is** our voice-runtime receiver. If transfer is ever enabled
with `pre_call_webhook_param` set and the URL left blank, our post-call receiver starts
taking mid-call deliveries whose body is *"the same execution record"* merged with the
template (`:80`) at `status: "in-progress"`. `engine_intake` dedupes on
`(execution_id, status)`, so a pre-call webhook at `in-progress` would collide with the
genuine `in-progress` transition and one of the two would be discarded. **If transfer is
ever enabled, `pre_call_webhook_url` must be set explicitly to a distinct route.** Recorded
here rather than coded, because nothing enables transfer today.

**Two vendor self-contradictions on this surface, reported and not resolved.**

1. `TransferCallToolParams` in the OAS (`create.md:1157-1187`) declares only `method`,
   `url`, `api_token`, `param` — it does **not** carry
   `pre_call_webhook_param`/`pre_call_webhook_url`, which the narrative page
   (`transfer-calls.md:42-47`) and the June 2026 changelog
   (`changelog/june-2026.md:76-87`) both document. Either the OAS is stale or the fields
   are UI-only.
2. **Is `tools` an array or a string?** `ApiTools.tools` is `type: array` whose description
   reads *"It needs to be a JSON string as this will be passed to LLM"*
   (`create.md:693-700`). Those cannot both be true of the same JSON member. The adjacent
   `TransferCallToolParams.<name>.param` resolves the same way for itself — declared
   `type: string`, described as *"Stringified JSON of the tool schema"* — so the vendor
   does stringify nested tool JSON somewhere, and the `tools` declaration is the one that
   disagrees with itself. **Whoever runs gate 18 must send one and read it back**, because
   an adapter that guesses wrong here gets a 422 or, worse, a silently toolless agent.

---

## 2. Custom function calls and our 100ms budget

### 2.1 The schema, and what our endpoint would have to be configured as

Their schema (`tool-calling/custom-function-calls.md:147-172`) is OpenAI function calling
plus three Bolna extensions:

```json
{
  "name": "…", "description": "…", "pre_call_message": "…",
  "parameters": { "type": "object", "properties": {…}, "required": […] },
  "key": "custom_task",
  "value": { "method": "GET", "param": {"p": "%(p)s"}, "url": "…",
             "api_token": "Bearer …", "headers": {} }
}
```

`"key": "custom_task"` is mandatory and fixed (`:176`, and `tools-tab.md:58`). Parameter
values are Python `%`-format specifiers, `%(name)s` / `%(name)i` / `%(name)f`
(`:276-280`), and *"The name in `properties` must be identical to the name in `param`
mapping (case-sensitive)"* (`:283`).

**Our endpoint is `POST /tools/v1/{engine}/opt-out` and it reads a JSON body.** Two
configuration constraints follow from their doc and neither is optional:

1. **The tool MUST be `"method": "POST"`.** For a GET, `param` becomes the query string —
   their worked example sends `…/orders?order_id=ORD-78234` (`:307`) — and
   `tool_routes._opt_out` reads only the body via `execution_key(payload)`. A
   GET-configured tool would also hit a POST-only route: 405, and the agent would tell the
   caller nothing useful. For POST, `param` becomes the JSON body: their appointment
   example maps `param` keys one-for-one onto `--data '{…}'` (`:435-491`).
2. **`headers` must carry `Content-Type: application/json`.** Their POST examples set it
   explicitly (`:487-489`); it is not implied.

### 2.2 THE FINDING THAT MATTERS: `execution_id` is missing from BOTH tool-calling pages

Our tool endpoint's ONE required field is the execution id, and it 422s without one —
deliberately, because *"an unkeyable TOOL call has no poller behind it"*
(`tool_routes.py:164-178`).

The **prompting** guide lists `execution_id` as a system variable
(`guides/prompting/using-context.md:34`):

> `| execution_id | Unique ID of the conversation or call |`

But the two pages that tell you what you may put **into a function parameter** omit it.
`tool-calling/custom-function-calls.md:581-586`, headed "Auto-Injected System Variables":

```
| `{agent_id}`    | The `id` of the agent                                    |
| `{call_sid}`    | Unique `id` of the phone call (from Twilio, Plivo, etc.) |
| `{from_number}` | Phone number that **initiated** the call                 |
| `{to_number}`   | Phone number that **received** the call                  |
```

`tool-calling/introduction.md:83-89` lists the same four (plus "Custom variables"). Both
omit `execution_id`, `current_date`, `current_time` and `timezone` — all four of which
`using-context.md:31-40` declares as system variables.

**Why this is not pedantry.** `{call_sid}` is explicitly *the telephony provider's* id, not
Bolna's execution id. `apps/workers/optout.py` resolves the tenant and the number from an
authenticated `GET /executions/{execution_id}` (D-31: the payload is a hint, the fetch is
the truth). Configure the tool with `%(call_sid)s` and that fetch is issued with a
Twilio/Plivo SID and fails. **If the shorter list is the authoritative one for function
parameters, our one in-call tool endpoint cannot be configured at all.** This is a
one-observation question and it belongs in gate 8 (§7).

Note our endpoint already hedges correctly — `_EXECUTION_ID_FIELDS` accepts `execution_id`,
`id` and `call_id`, each tried independently — so nothing here needs a code change. What it
needs is the observation.

### 2.3 THE TIMEOUT: not documented, anywhere, and that IS the finding

Searched the whole mirror for a tool-call timeout. Every timeout the doc set contains is
something else:

| Documented timeout | Where | What it governs |
|---|---|---|
| **Total Call Timeout** | `agent-setup/call-tab.md:129` | whole-call duration ("300s (5 min) for support") |
| `inactivity_timeout` | `guides/post-call/list-phone-call-hangup-status.md:72` | caller silence |
| `eot_timeout_ms` (300 ms–3 s) | `providers/transcriber/deepgram-flux.md:46` | end-of-turn detection |
| call setup 30 s | `sdks/web-call.md:318` | web-call `connect_failed` |
| IVR input `timeout` (5 s) | `guides/inbound/ivr-inbound-calls.md:106` | DTMF collection |

**None of these is a tool-call timeout.** There is no documented ceiling on how long Bolna
will wait for our endpoint, no documented retry on a tool call, and no documented statement
of what the agent says when our endpoint is slow. The only retry sentence in the doc set is
about the direction we RECEIVE — *"HTTP `200` — return fast; Bolna retries on non-2xx or
timeout"* (`api-reference/limits.md:62`) — and even that names neither a count nor a
duration.

**So gate 8's parenthetical — "no timeout is documented — the ceiling is unmeasured" — is
CONFIRMED by the full doc set, not merely still open.** Consequences, stated rather than
inferred:

- **Our 100ms budget (TRD §6.2) is OURS and has nothing to check it against.** It is not
  wrong; it is unconstrained from above. It stays the right target for a caller's
  perception of dead air, and it remains the number to measure.
- **The product-quality question genuinely has no documented answer.** What the caller
  hears while our endpoint is slow is the `pre_call_message` and then silence — the docs
  offer `pre_call_message` as the mitigation (*"Set a friendly message like 'Let me check
  that for you' so callers know to wait"*, `:778-780`) and say nothing about what follows if
  the call never returns. This is exactly the "nobody has looked at it" case, and it stays
  open because it needs one live observation, not a design.
- **Our endpoint is already built for the pessimistic reading**: it never does the work
  inline, it bounds the body at 4 KiB, and it bounds the enqueue with
  `asyncio.timeout(_DURABLE_DEADLINE_S)` so a Redis stall cannot hold the agent open. The
  refusal path returns an actionable sentence — *"The request was not registered; please
  tell the caller it will be handled."* — which is the right shape whatever the ceiling
  turns out to be.

**No gap found in the endpoint itself.** Nothing in `tool_routes.py` needs to change on
this evidence.

### 2.4 One security note on `api_token`

`value.api_token` is *"Authorization header value (e.g. `Bearer your_token`)"*
(`:265`) and is stored **in the agent object on the vendor's side** — the cURL importer
even auto-populates it from a pasted command (`:104`). If a client-facing tool endpoint of
ours ever requires a bearer, that bearer lives in Bolna's console, is visible to anyone with
dashboard access to that agent, and is not in our secrets manager. Our current tool endpoint
authenticates by **source-IP allowlist**, not by a bearer, so this does not bite today —
and that is now a reason to keep it that way rather than an accident.

---

## 3. Calendar booking (Cal.com)

**Usable by our clients: YES, with a caveat. Anywhere in our onboarding to put it: NO.**

Two built-ins, `fetch-calendar-slots.md` and `book-calendar-slots.md`, identical in shape.
Configuration is five fields (`fetch-calendar-slots.md:21-27`): Description, Pre-tool
message, **API Key** (*"Your [Cal.com API key]"*), **Select Events** and **Choose
Timezone** — and *"**Select Events** and **Choose Timezone** dropdowns appear only after
entering a valid Cal.com API key"* (`:30`).

Findings:

- **The client's Cal.com API key is entered into the Bolna agent.** It is a third-party
  credential, held by our engine vendor, scoped to the client's whole Cal.com account.
  Nothing in our onboarding, our DPA surface or our sub-processor list contemplates a
  credential of that shape.
- **It is a dashboard flow, not an API flow.** Both pages are UI walkthroughs, and the
  mirrored `api-reference` `ApiTools.tools` binds `oneOf: [TransferCallTools]` only
  (`create.md:696-697`) — no calendar tool schema is published. So a client could not be
  onboarded onto it through `publish_agent`; a human would configure it in Bolna's console,
  outside our tree and outside our drift sweep.
- **Timezone is a foot-gun for us specifically.** *"Mismatched timezones cause the agent to
  communicate incorrect times to callers."* (`fetch-calendar-slots.md:102`). Our convention
  is UTC in the DB, IST at the edge; a Bolna-side timezone dropdown is a third place that
  has to say Asia/Kolkata.
- **Market fit is real.** Their own dentist, front-desk and salon templates all point at it
  as the next step (e.g. `voice-agents/salon-booking-agent.md`: *"Connect [Cal.com] for
  real-time slot booking"*), and those are our verticals.

**Reported, not built** — as instructed. The honest position is that appointment booking
for clinics is a headline use case we do not serve, that Bolna's Cal.com built-in would
serve it, and that adopting it means accepting a client credential in the vendor's console
and a tool our publish path does not manage. That is a founder decision (§8), not an
integration to start.

---

## 4. Automation tutorials, read for CONTRACT

The tutorials are UI walkthroughs, but they do carry payload evidence the reference pages
omit. Compared against `packages/shared` normalized models, `apps/api/engine/bolna.py` and
`docs/vendor/bolna/hosted-oas.md`.

### 4.1 Fields a tutorial names that our adapter does not know

| Field | Evidence | Our tree | Verdict |
|---|---|---|---|
| `context_details.recipient_data` (dict of the dynamic vars sent at dial time) | `make-com/send-email-after-bolna-call.md:50-62`, `send-sms-…:41-53`, `send-whatsapp-…:43-55`, `n8n/send-email-…:43-55` — four independent pages, identical shape | **not read anywhere** | **GENUINE FINDING — see below** |
| `context_details.recipient_phone_number` | same four pages | not read; we read `telephony_data.{from,to}_number` | Redundant for us. Do NOT start reading it — a second spelling of the callee number is the "two ways of doing one thing" defect, and `telephony_data` is the OAS-backed one. |
| `error_message` | `google-sheets/…:229` (`webhook.error_message \|\| webhook.status`) | not read | Minor. We derive failure from `status`; a human-readable reason would improve the campaign-stall runbook. Not worth a field until one is observed. |
| `transfer_call_data` | OAS, §1.3 | **not read** | **GENUINE FINDING — alarmed this pass** |

**On `context_details.recipient_data`.** This is the round-trip of our own `user_data`:
`start_outbound_call` sends `{"agent_id", "recipient_phone_number", "user_data"}`
(`bolna.py:1667`) and the tutorials show those same keys coming back on the post-call
webhook under `context_details.recipient_data`. That is genuinely useful — it is the
vendor confirming which context a call actually ran with, which is the drift question for
the CallContext path (D-21). **It is a finding, not a fix**, and deliberately: reading it
means adding a member to `ExecutionSnapshot` (`packages/shared/.../engine.py`, owned by
Lane B this pass), and the field carries `lead_name` / `context_note` /
`prior_call_summary` — lead PII, which hard rule 6 and the transcript-redaction default
both bear on. Proposed as a ROADMAP entry in §8 rather than half-wired here.

### 4.2 Contract drift: `POST /call` has THREE shapes across the vendor's own docs

| Source | Body |
|---|---|
| OAS (`api-reference/calls/make.md:88-119`) | `agent_id` + `recipient_phone_number` required; `from_phone_number`, `user_data` optional |
| `guides/prompting/using-context.md:96-107` | same — `recipient_phone_number`, `from_phone_number`, `user_data` |
| `tutorials/google-sheets/…:140-143` | `{agent_id, recipient_phone_number}` |
| **`tutorials/sip-trunking/outbound-calls.md:82-89`** | **`{agent_id, recipient: {phone_number, name}, from_number}`** |

The SIP page's nested `recipient` object and `from_number` spelling contradict the OAS and
the other three. `hosted-oas.md` already publishes the tiebreak from the vendor
(*"Treat the YAML as the canonical schema if a SKILL.md and the spec disagree"*), so **the
OAS wins and our adapter is already correct** — `bolna.py:1667` sends
`recipient_phone_number`. Recorded so nobody "fixes" it toward the tutorial.

### 4.3 `webhook.execution_id || webhook.id` — the vendor's own code hedges

`google-sheets/…:204`:

```javascript
  const executionId = webhook.execution_id || webhook.id;
```

The vendor's own tutorial does not know which spelling its webhook uses. Our
`engine_intake._EXECUTION_ID_FIELDS` already tries `execution_id`, `id` and `call_id`
independently, and `start_outbound_call` reads `data.get("execution_id") or
data.get("id")`. **No gap found**, and the hedge is now corroborated by the vendor.

### 4.4 D-23 Google Sheets sync — contract drift check

The tutorial is a *client-side* Apps Script pattern (Sheets → Bolna directly), which is
architecturally the opposite of our D-23 sync (our CRM → the client's sheet). There is no
shared contract to drift. Two things it does confirm that bear on ours:

- The status ladder it writes is `scheduled → queued → in-progress → completed / failed`
  (`:61`), while `api-reference/limits.md:61` writes `queued → in-progress →
  call-disconnected → completed`. **`call-disconnected` is in our `_STATUS_MAP` already**
  and the tutorial's omission of it is the tutorial being loose, not a new status.
- *"The webhook payload mirrors the [Get Execution API] response"* (`:239`) — the third
  independent statement of that fact, matching `hosted-oas.md`'s. Our poller-as-truth design
  (D-31) does not depend on it, which is the right way round.

**No D-23 drift found.**

### 4.5 Webhook source IPs — a confirmation worth recording

`api-reference/limits.md:60`:

> `| Source IPs | 13.203.39.153, 13.126.9.249, 13.202.133.53 — whitelist all three on your server |`

`hosted-oas.md` records the vendor's prose files as naming **one** address. Our
`DEFAULT_BOLNA_SOURCE_IPS` already holds **all three** and matches this line exactly.
**No gap found** — and the one-IP claim in `hosted-oas.md` §"Facts the prose files add" is
now superseded by a first-party page listing three.

### 4.6 SIP trunking — two things this lane should record

- **`sip:13.200.45.61:5060`** is Bolna's SIP media server, named in five places
  (`sip-trunking/introduction.md:73`, `inbound-calls.md:19,38,127`,
  `plivo-trunk-setup.md:34`, `twilio-trunk-setup.md:34`, `outbound-calls.md:150,168`).
  Combined with the three webhook IPs above, these are the vendor's egress/ingress
  addresses. Whether they are in-region is a residency question for gate 9 and is NOT
  asserted here.
- **SRTP is not supported**: *"Media must use standard (unencrypted) RTP. Trunks requiring
  mandatory SRTP will not work with Bolna."* (`sip-trunking/introduction.md:119`). If we
  ever route Exotel/Vobiz trunks through Bolna, media is unencrypted on that hop, which is a
  sentence a client DPA has to contain.
- Their compliance posture on BYOT is explicit and convenient for our PE/TM model: *"Your
  existing compliance setup (DLT registration, STIR/SHAKEN) stays with your provider. Bolna
  does not interfere."* (`sip-trunking/introduction.md:110`).

---

## 5. The template library — and the brief that has no subject

**READ ALL 16. THEY CONTAIN NO PROMPT TEXT.** Every page is the same five elements: a title,
a one-sentence description, an Industry/Languages/Call-to-test table, an "Import this agent"
link to `bolna.ai/a/<uuid>`, and a Next Steps card group. The prompts live behind the import
link, which is a `bolna.ai` host and refused by this environment's proxy.

**So the "whether their prompts handle anything ours miss" half of the brief cannot be
answered from the mirror, and nothing was inferred to fill it.** That is also the cleanest
possible outcome for the copyright constraint: there was no prompt text to be tempted by.

### 5.1 Coverage: what they have that we do not

Our `scripts/seed.VERTICAL_TEMPLATES` holds four: `clinic`, `real_estate`, `insurance`,
`education`.

| Their template | Industry | Ours |
|---|---|---|
| Dentist Appointment | Hospitality | ≈ `clinic` (ours is general; theirs is dental-specific) |
| Property Tech | Real Estate | ≈ `real_estate` |
| Lead Qualification | Ed Tech | ≈ `education` |
| Sales – Loans, Sales – Credit Card | BFSI | ≈ `insurance` (adjacent, not the same) |
| **COD Confirmation** | E-Commerce | **none** |
| **Cart Abandonment** | E-Commerce | **none** |
| **Customer Support** | E-Commerce | **none** |
| **Salon Booking** | Hospitality | **none** |
| **Front Desk** (generic receptionist) | Hospitality | **none** |
| **Recruitment** | Recruitment | **none** |
| **Reminders** (EMI / payment due / collections) | BFSI | **none** |
| **Surveys** (NPS / CSAT) | Hospitality | **none** |
| Announcements | BFSI | none |
| Onboarding | Health Tech | none |
| Weekend Planner | Real Estate | none (a demo, not a vertical) |

**The four gaps worth a founder's attention, in order:**

1. **COD confirmation** (`voice-agents/cod-confirmation-agent.md`) — *"Calls customers
   before delivery to confirm orders … reducing failed deliveries and RTO."* This is
   arguably the single highest-volume Indian SMB voice use case, it has a hard rupee ROI a
   client can compute before buying, and the call is **transactional**, which puts it on the
   160-series and out of the promotional consent regime. We have nothing in e-commerce at
   all.
2. **Salon / personal services** (`salon-booking-agent.md`) — inbound booking, enormous SMB
   density in Indian cities, and the closest thing to `clinic` we already know how to build.
3. **Front desk / generic receptionist** (`front-desk-agent.md`) — this is literally what
   our BRD calls the inbound product, and we have no vertical-neutral template for it; every
   one of our four is a specific industry.
4. **Recruitment screening** (`recruitment-agent.md`) — outbound, high volume, and the
   extraction schema is the easiest of the lot.

**One to approach carefully rather than copy.** `reminders-agent.md` covers *"upcoming EMIs,
payment due dates … and collections"* and their own Next Steps says to *"Set [calling
guardrails] to comply with TRAI/TCPA hours"*
(`voice-agents/reminders-agent.md:25`). Debt collection by voice in India sits under
RBI's recovery-agent conduct rules **on top of** TRAI/DLT, including calling-hour
restrictions and harassment prohibitions that are stricter than our current compliance gate
models. It is a real market and it is not a template to seed without a compliance read.

### 5.2 What we should NOT take from them

Every one of their templates is prompt-only: no template in that library carries an AI
disclosure sentence or a recording notice, because Bolna has no equivalent of hard rule 5.
Ours must carry both (`agents.ai_disclosure_line` / `recording_notice_line`, NOT NULL and
non-blank) and the truthful-answer directive is appended by `compose_engine_prompt`
regardless. A template imported from their library and pointed at an Indian caller would
ship without either. That asymmetry is a feature of our product and worth saying out loud in
sales material.

---

## 6. Explicit "no gap found"

Stated so a future reader can tell "checked and fine" from "not looked at":

- **`tool_routes.py` needs no change** on this evidence (§2.3).
- **`execution_key`'s three spellings** are corroborated by the vendor's own hedging code
  (§4.3).
- **Our webhook source-IP allowlist** matches the published three exactly (§4.5).
- **`POST /call` body** matches the OAS; the SIP tutorial is the outlier (§4.2).
- **The 24-hour pre-signed recording link** (`changelog/may-2026.md:118`, *"do not store or
  cache it"*) is already handled: `pipeline` copies the audio first and overwrites
  `calls.recording_url` with OUR object key, so no vendor URL is ever persisted or rendered.
- **`call-disconnected`** is already in `_STATUS_MAP`.
- **D-23 Sheets sync** has no shared contract with their Sheets tutorial and no drift (§4.4).

---

## 7. Proposed OPERATIONS §2 gate-table text — EXACT, to be applied centrally

*Applied 20 Aug 2026. The gate-18 criteria replacement carries one correction: the vendor has
no `hangup_detail` field, so (e) now names `hangup_by` / `hangup_reason` / `hangup_provider_code`
(D-414). The gate-9 parenthetical was folded into the rewritten gate 9 (D-415) rather than
patched, because that whole row was replaced in the same pass.*

**Replace the criteria cell of gate 18** (the `#`/name cell is unchanged):

> `BOLNA_CAPABILITIES.transfer=False` was "nobody checked", then "the built-in is an in-call
> tool, read from their OSS" (D-262). **Half of this gate is now ANSWERED from the vendor's
> own hosted OpenAPI document and the value still does not move.** (a) **Does the hosted
> `/v2/agent` body accept a transfer tool, and under which key? YES —
> `key: "transfer_call"`.** `ApiTools.tools` is an array of `TransferCallTools` with
> `tools_params` keyed by the tool's `name`, and the destination is CONFIG inside
> `TransferCallToolParams.<name>.param` (a *stringified* JSON blob, example
> `{"call_transfer_number": "+19876543210","call_sid": "%(call_sid)s"}`). (b) **Does any
> REST route transfer a live execution? NO** — none exists in the published paths, so the
> shape `VoiceEngine.transfer(call_id, to, warm)` names remains unimplementable and `False`
> is right for a stronger reason than before. **What is left is four live observations, and
> the first two are compliance, not plumbing.** (c) **WARM OR COLD — the vendor documents it
> NOWHERE**: no page uses warm, cold, attended, blind or consultative, and the only briefing
> channel offered (the pre-call webhook) is explicitly *"fire-and-forget … never blocks or
> delays the transfer"*, which cannot be a warm handoff. Observe on a real call whether the
> caller is held while staff are briefed, and record it. (d) **Does the caller hear anything
> at the handoff, and is the transferred leg recorded with the caller's knowledge?** The
> transferred leg is a SEPARATE object with its own `recording_url`, `cost`, `duration`,
> `hangup_reason` (`TransferCallData`), served from its own route
> `GET /recordings/transfer/{execution-id}`. Capture a full `transfer_call_data` as an
> adapter fixture. (e) does a transfer land on Exotel/Vobiz Indian PSTN, and what does the
> execution record say afterwards (status, `hangup_detail`, cost of BOTH legs)? (f) if
> `pre_call_webhook_param` is used, `pre_call_webhook_url` **must** be set explicitly — left
> blank it falls back to the agent-level Webhook URL, i.e. our post-call receiver, where an
> `in-progress` pre-call delivery collides with the genuine `in-progress` transition on
> `engine_intake`'s `(execution_id, status)` dedupe key. **Pass** = we can name the
> mechanism AND answer (c) and (d). **This is a design decision, not a flag flip**: a
> per-agent escalation number becomes engine config set at publish time and is NOT covered
> by the drift sweep (which proves the prompt, not the tool list); carrying the second leg
> needs new `ExecutionSnapshot` members plus a decision on separate metering and separate
> retention. Until then `engine/bolna.py::_check_transfer_leg` pages
> `engine_transfer_leg_unhandled` if a transfer leg ever appears — the tool is enabled by a
> console toggle (*"Click + Add next to any tool"*), so it can arrive without a deploy.
> Blocked outside this repo on: a Bolna account. Evidence:
> `docs/evidence/bolna-tools-integrations.md` §1, `docs/vendor/bolna/oss-harvest.md` §5.

**Append to the criteria cell of gate 8**, after the existing "no timeout is documented"
sentence:

> **THE ABSENCE IS NOW CONFIRMED ACROSS THE WHOLE DOC SET, NOT MERELY UNCHECKED.** Every
> timeout Bolna documents governs something else — Total Call Timeout
> (`agent-setup/call-tab`), `inactivity_timeout`, the transcriber's `eot_timeout_ms`, the
> web-call 30 s setup timeout, the IVR input timeout. There is **no documented tool-call
> timeout, no documented tool-call retry, and no documented statement of what the agent says
> when our endpoint is slow** — the only retry sentence in the doc set is about deliveries
> to us (*"return fast; Bolna retries on non-2xx or timeout"*) and names neither a count nor
> a duration. So TRD §6.2's 100ms is OURS, unconstrained from above, and this gate is the
> only thing that can produce a ceiling. **Also settle the one question that decides whether
> our tool endpoint can be configured AT ALL:** `guides/prompting/using-context` lists
> `execution_id` as a system variable, but BOTH tool-calling pages omit it from their
> "auto-injected system variables" tables, listing only `agent_id`, `call_sid`,
> `from_number`, `to_number`. `call_sid` is the TELEPHONY provider's id, and
> `apps/workers/optout.py` resolves the tenant from an authenticated
> `GET /executions/{execution_id}` — so if `%(execution_id)s` does not substitute inside a
> custom function's `param`, `POST /tools/v1/{engine}/opt-out` 422s every call and the
> in-call opt-out path is dead. Configure the tool as **`"method": "POST"`** (a GET puts
> `param` in the query string, which our body-reading route never sees, and hits a POST-only
> route) with `headers: {"Content-Type": "application/json"}` and
> `"key": "custom_task"`, then record: whether `%(execution_id)s` arrived, the tool-call
> p95, and what the agent said to the caller when the endpoint was deliberately stalled.

**Correct gate 9's parenthetical** — it currently reads *"(Recordings sit on S3 us-east-1
— storage ≠ compute, but both matter.)"* Proposed replacement:

> (Recording storage **moved during 2026 and the doc set is inconsistent about where it
> was**: the OAS example is `bolna-call-recordings.s3.us-east-1.amazonaws.com/AC…/RE…` —
> note the Twilio account/recording SID shapes, so that example may be a Twilio URL rather
> than Bolna's own store — while the May 2026 changelog names the pre-June format as
> `bolna-recordings-india.s3.amazonaws.com`. Since 1 June 2026 both are superseded by
> `https://api.bolna.ai/recordings/call/{execution-id}` (and `…/recordings/transfer/…` for a
> transfer leg), which resolves to a pre-signed link expiring in 24 hours. **So ask where
> the bucket is rather than assuming either answer**; storage ≠ compute, and both matter.)

---

## 8. Needs a founder decision (outside this repo)

1. **Do our AI-disclosure and recording obligations follow the caller across a transfer to a
   human?** Specifically: (a) does the recording notice the caller already heard extend to a
   leg the same platform records separately, and (b) is an inverse disclosure ("you are now
   speaking to a person") required or advisable at the handoff? This is a legal question
   under the same TRAI/DPDP split that D-163 already separates. **Transfer should not be
   offered to any client until it is answered** — the engineering (a second recording to
   copy, retain and erase; a second cost to meter) is straightforward once it is.
2. **Cal.com**: are we willing to have a client's Cal.com API key held in Bolna's console,
   configured by a human outside `publish_agent` and outside our drift sweep, in exchange for
   real appointment booking in clinics and salons? If yes, it is a sub-processor/DPA item and
   an onboarding step we do not currently have. If no, appointment booking stays a custom
   function against our own endpoint and we build it.
3. **Which of the four uncovered verticals to seed first** (§5.1). Recommendation: COD
   confirmation, on ROI legibility and on the 160-series/transactional classification.
   Collections/EMI reminders needs a compliance read (RBI recovery-agent conduct rules on
   top of TRAI/DLT) before it is a template rather than after.

**Proposed ROADMAP §6 decision-log entry**, for the one field this pass found and
deliberately did not wire:

> **D-422 — `context_details.recipient_data` is a real return channel and is NOT read yet.** *(applied centrally 20 Aug 2026 as D-422.)*
> Four independent Bolna tutorials (Make.com email/SMS/WhatsApp, n8n email) show the
> post-call webhook carrying `context_details.recipient_data` — the round-trip of the
> `user_data` our `start_outbound_call` sent — alongside
> `context_details.recipient_phone_number`. Reading it would let the CallContext path (D-21)
> verify which context a call actually ran with, instead of trusting that what we sent is
> what ran. **Not wired in the pass that found it, for two reasons and both are the rule
> rather than the exception:** it needs a new member on `ExecutionSnapshot` (a shared model),
> and the field carries `lead_name`/`context_note`/`prior_call_summary`, i.e. lead PII that
> hard rule 6 and the transcript-redaction default both bear on — so where it lands is a
> data-model decision, not an adapter read. **What closes this:** a decision on whether the
> echo is stored or only compared-and-discarded. Do NOT also start reading
> `context_details.recipient_phone_number` — `telephony_data.{from,to}_number` is the
> OAS-backed spelling and a second one is the two-ways-of-doing-one-thing defect. Evidence:
> `docs/evidence/bolna-tools-integrations.md` §4.1.
