# Can a Guntur clinic run an inbound Telugu receptionist on this product today?

Read-only audit, 4 Sep 2026, against the founder's answered setup decisions (not a generic
clinic):

1. The clinic **keeps its existing number** and conditionally forwards it to a DID we
   supply. Client-facing story: *"point your existing phone at this number."*
2. That DID is **bought from Bolna directly** (`POST /phone-numbers/buy`, `country: IN`,
   `provider: twilio | plivo | vobiz`).
3. Scope is broad and must be **dynamic**: answer + take a message, **book and reschedule
   appointments**, transfer to a human, call the patient back later, script and variables
   configured per clinic.
4. **Telugu and English mixed on the same call**, not Telugu-only.

**Evidence discipline (hard rule 11).** Every claim about OUR code is a file:line I opened
this session. Every vendor claim cites the hash-pinned mirror at `bolna-findings/mirror/`
(VERIFIED-VENDOR-DOCS) by page and line, or is marked UNKNOWN. No Bolna, Plivo, Vobiz,
Google, Razorpay or Azure account is reachable from this container. Nothing in the "does it
actually behave that way against the vendor" class is verified here and I have guessed at
none of it.

**Answer in one line: NO — three of the four decisions hit a wall in code, and the two
worst are the number and the language.**

---

## 1. THE NUMBER PATH (reported first, as asked)

### Is the Bolna-buy seam wired end to end? **NO. It is refused, on purpose, at four
separate layers, and the refusal is load-bearing on a legal decision — not a missing wire.**

The founder is right that the seam is *declared*. It is also *deliberately closed*:

| Layer | State | Evidence |
|---|---|---|
| Client/operator route | `POST /v1/numbers/purchase` **always refuses**, return type `NoReturn` | `apps/api/campaigns/provisioning_routes.py:1-21, 96` |
| Capability selector | `PROVISIONING_IMPLEMENTED: Final = False` | `apps/api/campaigns/provisioning.py:118` |
| Engine descriptor | `BOLNA_CAPABILITIES.number_series` is **empty**, so `require_capability("numbers")` refuses every series | `apps/api/engine/bolna.py:4084` |
| Adapter | `BolnaEngine.provision_number` raises `engine_capability_unverified` unconditionally: *"nothing here buys one"* | `apps/api/engine/bolna.py:4078-4097` |

There is **no search method on the port at all** (`VoiceEngine` declares
`provision_number`, `bind_inbound_number`, `unbind_inbound_number` and nothing else —
`packages/shared/src/calevate_shared/engine.py:4387-4429`), and **no admin or client screen
for buying a number** (`apps/web/src/lib/api/admin.ts:931,962,981` are the only three
number calls the front end makes: list, record, set DLT status).

**And `NumberSpec` cannot express what the vendor's buy endpoint requires.** `NumberSpec` is
`{series, provider, region, purpose}` (`engine.py:3191-3196`). `PurchasePhoneNumberRequest`
has `required: [country, phone_number]` — you must name the exact E.164 you are buying
(`bolna-findings/mirror/pages/api-reference/phone-numbers/buy.md:54-77`). So the real vendor
flow is **search → pick → buy**, and our port models "provision me something matching this
spec". The port shape is wrong for this vendor, not merely unimplemented.

**The blocker is not engineering, it is the legal decision the code is enforcing.**
`provisioning.py`'s own docstring says flipping `PROVISIONING_IMPLEMENTED` **is adopting
Model A**, which the playbook refuses for a sole proprietor: *"Do not resell Indian numbers
from a pool in your name"* and *"Do not open a Calevate carrier account 'just in case' and
park client traffic on it — that recreates Model A"*
(`docs/legal/LEGAL-OPS-PLAYBOOK.md:602,611`, stop-list items 1 and 10);
*"A future 'we provision the number for self-serve' tier is **Model A** and is **unsafe**
for a proprietor. If you ever do it: incorporate first, get written VNO/reseller status from
a licensed operator"* (`:621`). A Bolna-bought DID comes back `bolna_owned: true`
(`buy.md:88-91`) — it sits in **our** Bolna account, not the clinic's carrier account, which
is squarely the shape those two stop-list items name.

**This is a founder decision to make, not a bug for me to fix.** But it must be made
explicitly, because D-05 / Model B is currently written into four modules, the published
Terms clause 3, Acceptable Use §2.1, and the refusal copy a client reads. **Reversing it is
a decision-log entry (ROADMAP §6) and a change to published legal text, not a config flip.**
Until it is made, no code change here is safe to write.

### If that decision is made, here is exactly what is still missing

1. **`phone_numbers.engine_number_ref` has no writer anywhere in production code.** This is
   the single fatal seam and it is fatal under Model A *and* Model B. Declared at
   `apps/api/agents/models.py:566`; read at `apps/api/agents/service.py:1100,1194-1200`; the
   only production INSERT (`apps/api/agents/service.py:2273`) omits the column; the only
   UPDATE is `set_number_dlt_status` (`:2334`); the admin body has no field for it
   (`ProvisionNumberIn`, `apps/api/admin/routes.py:1343-1353`, `extra="forbid"`). A
   repo-wide grep finds it written **only in test fixtures**
   (`tests/caller_id_and_inbound_routing_test.py:133`, `tests/agent_lifecycle_test.py:132`).
   Consequence, today, on every publish of an inbound agent with a recorded number:
   `route_inbound_numbers` → `bind_inbound_number` → `_inbound_number_id`
   (`apps/api/engine/bolna.py:4119-4145`) raises `engine_number_not_linked` → `failed` → one
   `CORE_LOGIC` alarm per number (`apps/api/agents/service.py:1207-1221`), while the publish
   reports success.
2. **No `search_numbers` on the port**, no `phone_number` field on `NumberSpec`, no screen.
3. **No place to record what the number COSTS us.** `buy.md:113-117` prices in **cents**;
   `get_all.md:103-105` returns `price` as a **string** monthly rental. Under Bolna-buy the
   rental is a Calevate cost per client — `number_rental` currently has no writer for client
   numbers by explicit design (OPERATIONS §2 gate 26), which was correct under Model B and
   is wrong under this decision. Hard rule 7 applies to whatever replaces it.
4. **The id shape is still contradictory in the vendor's own docs**, and it is what
   `engine_number_ref` must hold: `buy.md:80-84` returns `id` as a **dashed UUID**;
   `get_all.md:65-68` types the same field `^[0-9a-fA-F]{32}$` (**bare hex**);
   `byot-setup.md` returns a ULID-looking value. The adapter correctly refuses to validate
   it and sends it verbatim (`apps/api/engine/bolna.py:4109-4117`). **OPERATIONS §2 gate 25**
   settles this and cannot be settled from here.

### What forwarding adds that nothing in this repo models

Conditional forwarding is the clinic's carrier's feature, configured on the clinic's own
line — no code. Two consequences worth stating:

- **The DID is never published anywhere**, so the Truecaller / caller-ID surface is about
  what the CLINIC's number shows, not ours. Fine.
- **`from_e164` on an inbound forwarded call is the ORIGINAL caller or the forwarding
  switch, depending on the carrier.** Our lead/CRM row takes `from_e164` as the patient's
  number on inbound (`apps/workers/pipeline.py:1850`). If an Indian carrier presents the
  clinic's own number instead of the patient's on a forwarded leg, **every inbound lead gets
  the clinic's own number as the patient's phone, every call-back rings the clinic, and
  caller memory keys every patient to one identity.** I cannot determine this from here —
  it depends on the carrier's forwarding implementation and on what Bolna puts in
  `telephony_data`. **UNKNOWN — needs one real forwarded test call.** This is the single
  cheapest experiment on the whole list and it is not currently any gate. It should be one.

### Verdict on step 3: **FAIL — fatal, and the top-ranked item.**

---

## 2. TELUGU + ENGLISH ON ONE CALL

### **FAIL — fatal for this customer, exactly as ranked.**

The vendor's mechanism for mixed-language calls is `multilingual_config`, and their own
guide is unambiguous: *"A multilingual agent can understand and respond in multiple
languages within a single call"*, with per-language prompts, per-language STT and TTS, and a
shared Language Switching Instructions field
(`bolna-findings/mirror/pages/customizations/multilingual-languages-support.md:20,26,113-125`;
`agent-setup/audio-tab.md:9,19,26,62`).

**Our adapter sends `multilingual_config: None` on every single publish**, explicitly, and
the reasoning is a hard rule rather than an oversight: `MultilingualConfig` keeps a
`system_prompt` **per language** and *"switches them, along with the active system prompt,
during the call"*, while `compose_engine_prompt` puts `TRUTHFUL_ANSWER_DIRECTIVE` into
`agent_prompts.task_1.system_prompt` and `verification.judge` reads it back from exactly
there. So a multilingual agent would run, for every language but the base one, **a prompt
carrying none of the compliance floor**, while our read-back scored
`truthful_answer_applied=True` off a prompt that is not the one in use. That is hard rule 5
being withdrawn by a config row. `apps/api/engine/bolna.py:3604-3650`.

And it is defended: `_check_multilingual_speech` (`:1566-1626`) **alarms** if anyone turns
multilingual on in the vendor console, because a console-added language brings its own voice
and its own transcriber that we never published.

So today: **one transcriber language per agent** (`"language": cfg.language_primary`,
`apps/api/engine/bolna.py:3575`), one voice, one prompt. `Language` is
`Literal["te-IN","hi-IN","en-IN"]` (`apps/api/agents/voices.py:122`) — pick one.

**What is NOT settled, and matters:** Sarvam Saaras is marketed for Indian code-mixed
speech, and Bolna's own table says Sarvam is *"Optimized for Indian languages like Hindi,
Tamil, and Telugu"* (`audio-tab.md:92`). It is entirely possible that Saaras on `te-IN`
transcribes English words in a Telugu sentence correctly and Bulbul reads English back
acceptably — in which case a single-language agent already delivers code-mixing and nothing
needs to change. **UNKNOWN — needs a live account and an ear.** That is precisely OPERATIONS
§2 **gate 3**, which nobody has run, and all 44 voices carry `verified=False`
(`apps/api/agents/voices.py:331`).

**So the finding is two-branched and the branch decides the size of the work:**
- If Saaras/Bulbul handle code-mixing on one language setting → **nothing to build**, gate 3
  just needs running.
- If they do not → we need `multilingual_config`, **and enabling it requires solving the
  compliance-floor problem first** (the floor must ride every per-language prompt, and
  `verification.judge` must read back every one of them). That is a real piece of work with
  a hard-rule-5 design question in it, not a config change.

**Run gate 3 before anything else on this list.** It is a phone call and an afternoon, and
it decides whether item 2 is zero work or a week.

---

## 3. THE REST OF THE JOURNEY

### Onboarding — PASS, operator-led
Self-serve signup is off by default (`packages/shared/src/calevate_shared/config.py:1333`);
an operator creates the org through the intake wizard. Default tier `prepaid`
(`apps/api/admin/service.py:194,274`).
**Inbound is genuinely unaffected by a zero balance, enforced by ORDER not by comment:**
`check_dispatch` refuses `agent_inbound_only` (`apps/api/compliance/service.py:546-551`)
*before* it reads KYC or money, and the inbound path never calls `check_dispatch` at all.
Client copy says it first: *"People calling you still get through — answering calls never
uses your credit"* (`apps/api/crm/attention.py:66-70`). **A clinic at ₹0 answers its phone.**
Residual: an inbound call still debits the wallet (`apps/workers/pipeline.py:2540-2559`) and
nothing bounds a negative balance on inbound.

### Agreements / KYC / verification — PASS
`apps/api/legal/readiness.py:246-305` builds one exhaustive blocker list from the same
predicates the gates use, each row carrying `title`/`actor`/`next_step`. Publish requires an
open account and accepted agreements (`apps/api/agents/service.py:1268,1315`), ordered after
`_load_agent` so another tenant's agent is 404 rather than a paperwork disclosure. Minor: the
screen's verdict is *"Nothing is holding up your outgoing calls"*
(`apps/api/legal/routes.py:232`) — an inbound-only clinic is shown outbound rows it will
never need.

### Building the receptionist — PASS, self-serve
Create (`apps/api/agents/routes.py:427-448`, `org:manage`), script
(`apps/api/agents/script_routes.py:59`, `org:manage`), voice, direction, language, call cap
all client-realm. `activate` calls `publish_agent` (`apps/api/agents/lifecycle.py:525`),
which creates the engine agent, reads it back and scores it (D-64), and writes
`engine_agent_routes` in the same transaction. **No operator step is required to publish** —
the admin `/publish` route is a second door, not a gate. All three notice sentences are
written at creation from the language templates, NOT NULL, both toggles on
(`apps/api/agents/lifecycle.py:244-274`).

### Dynamic script + variables — **PARTIAL, with one real bug**
Client-configurable variables exist: `ScriptVariable` with a validated key, four standard
merge fields, an insert menu, up to 100 per script
(`packages/shared/src/calevate_shared/call_script.py:59-100,173-205,260`).
**But the syntax does not match the engine's, and nothing bridges it.** Our authored fields
are `{{ key }}` and pass through `compile_call_script` **verbatim** into the published prompt
(`call_script.py:316-373` — no rewriting). Bolna substitutes **single** braces from
`user_data`: *"`{customer_name}` in the prompt becomes 'Asha'"*
(`bolna-findings/mirror/pages/api-reference/calls/make.md:32`). Our own memory slot correctly
uses single braces for exactly this reason and says so
(`packages/shared/src/calevate_shared/engine.py:2251-2264`).
And `substitute_variables` runs only on `external_deployment` engines — on Bolna
`_call_prompt_for` returns None (`apps/api/agents/service.py:1024-1033`), with a comment at
`apps/api/agents/service.py:2090-2093` asserting *"the engine does its own variable
substitution"* — which is true for a syntax we never emit.
**On INBOUND there is no `POST /call` and therefore no `user_data` at all**, so a `{{ }}` in a
clinic's script is substituted by nobody and sits literally in the running prompt.
UNKNOWN whether Bolna also matches `{{ }}` — needs a live account; it is gate 8b's shape.

### Appointment booking — **BUILT (the coordinator's premise is out of date), with two real gaps**
It exists and is wired end to end, on **Google Calendar through our own ACTIONS feature**,
not through Bolna's Cal.com tool: `apps/api/actions/calendar.py` (OAuth connect, freebusy,
event insert), `ACTION_KINDS = ("custom_api", "whatsapp", "calendar")`
(`apps/api/actions/models.py:53`), declared to the engine at publish as `api_tools`
(`apps/api/actions/service.py:523-541`), invoked mid-call by Bolna at
`POST /v1/actions/invoke/{engine}/{tool_id}` on **apps/api** (not voice-runtime — hard rule 3,
`apps/api/actions/service.py:498-507`), source-IP allowlisted like the webhook receiver
(`apps/api/actions/routes.py:80-83`), with a client console screen and a "Test API" tab
(`apps/api/actions/routes.py:576-598`).
Two gaps:
- **`operation: Literal["book", "check"]` (`apps/api/actions/schema.py:148`) — there is no
  reschedule and no cancel.** The founder asked for "book **and reschedule**". Rescheduling
  needs the event id kept from the booking and a `PATCH events/{id}`; cancelling needs
  `DELETE`. Neither exists, and nothing stores the created event id today.
- **A clinic's real constraint is a doctor's slots, not a calendar account.** Bolna's own
  booking tool is **Cal.com only** (`bolna-findings/mirror/pages/tool-calling/book-calendar-slots.md:11,26`)
  and configured in their dashboard, so it was rightly not used. Ours is Google Calendar,
  which a clinic plausibly has one of per doctor — but free/busy on a shared clinic calendar
  is not the same as "Dr Rao has a 15-minute slot at 4:20". That is a product design question
  the founder should decide before the first clinic, not a code gap.
- **External blocker:** none of it runs until `GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI`
  are set — a Google Cloud project and OAuth consent screen (`apps/api/actions/calendar.py:23-26`,
  gated by `calendar_configured()` so it refuses cleanly). Plus `actions_callback_base_url`
  must be a real public origin.
- Named hardening already in the code: the OAuth `state` is the bare tenant id and is not
  HMAC-signed (`apps/api/actions/routes.py:620-623`). Not exploitable today because the
  callback also requires an authenticated `org:manage` session, but it is on the record.

### Transfer to a human — **IN FLIGHT, not audited**
`apps/api/agents/handoff.py` is untracked and `agents/service.py`, `publishing.py`,
`verification.py` and `engine/bolna.py` are modified in the working tree by another lane.
Seam only: `AgentConfig.handoff` is `None` outside every roster member's hours, so the
adapter emits no transfer tool and "never transfer outside business hours" is structural
rather than a prompt request (`packages/shared/src/calevate_shared/engine.py:2712-2726`).
That is the right shape. Not further audited, per instruction.

### Call-back later — WORKS, with one bug and one warning gap
`apps/workers/callbacks.py:264` gates every callback dial through `check_dispatch` at fire
time (uncached DNC read), then dispatches through the one outbound entry point. The client
screen shows the gate's own sentence via `last_refusal_reason`
(`apps/api/callbacks/routes.py:116-142`).
- **Nothing warns at promise time.** A zero-balance clinic can promise a call-back it cannot
  place; the client only learns after the first deferred attempt, on the callbacks screen,
  and never in the Needs-attention queue (which has four sources and callbacks is not one:
  `apps/api/crm/attention.py:121,272,330,393`).
- **BUG: an inbound-only agent's promises die silently.** `check_dispatch` returns
  `agent_inbound_only` for `direction == "inbound"` (`apps/api/compliance/service.py:549`);
  that rule is **not** in `PERSON_LEVEL_REFUSALS` (`:180-182`), so the promise defers every
  five minutes until `expire_stale` kills it; and `agent_inbound_only` has **no entry in
  `BLOCK_REMEDIES`** (`apps/api/crm/attention.py:54-76`), so the fallback copy tells the
  clinic *"there is nothing for you to do"* when the fix is one field: set the agent to
  `both`. Nothing refuses or warns at booking (`apps/api/callbacks/service.py:184`).
  **For a clinic whose receptionist is inbound-only, this is every call-back promise.**

### Knowledge — PASS on our side, UNVERIFIED against the vendor
Text path complete: submit → approve → chunk → render one PDF → attach, with a per-agent
publish lock, detach-then-attach ordering (D-41), an `engine_kb_routes` table and a
reconciliation sweep (`apps/api/kb/service.py:842-1110`). **Not one call in this path has run
against a live Bolna account — OPERATIONS §2 gate 43 says so in those words**, with 43a-43i
under it. For a clinic the KB *is* the product.
**Content gap:** `agents.business_hours` is captured at intake
(`apps/api/admin/intake.py:496`) and read only for a dashboard tile and the handoff duty
window (`apps/api/agents/business_hours.py`). **It never reaches the prompt or the KB.** The
clinic's opening hours must be typed a second time as knowledge — and "what time are you
open" is the most common question an inbound receptionist gets.

### A call arrives — PASS, the strongest part of the system
`apps/voice-runtime/webhook_routes.py` verifies source before reading the body, bounds three
separate waits, claims the inbox by execution id and reports `X-Ack-Ms` on every path
including refusals. `apps/workers/pipeline.py` resolves the tenant through
`engine_agent_routes` (`:222-244`), upserts on `engine_call_id` with a forward-only status
clause bound from the `TERMINAL_STATUSES` constant rather than a SQL literal (`:540-560`),
copies the recording to our own key, extracts, and writes the lead from the *other* party
(`from_e164` on inbound, `:1850`). I could not construct a path where a call lands with no
row. Bolna's at-most-once unsigned delivery is covered by the 10-minute poller; its real loss
behaviour is gate 6, unmeasured.

### After the call — PASS, minus the callback gaps above

### Billing — PASS on inbound
Inbound meters and charges: NUMERIC INR throughout, prepaid debit keyed by `call_id`
(idempotent, D-39), IST billing months via one spelling, negative durations clamped with an
alarm rather than aborting the metering transaction. **External:** no Razorpay account, so
`payment_capability().creates_orders` is False with reason `no_api_secret`
(`apps/api/billing/payments.py:88-92,435`) — no online top-up; operators record bank
transfers. Gate 44.

### Compliance for INBOUND — PASS, with two open legal questions that are not ours
- **TCCCPR / DLT / TM registration does not apply to inbound.**
  `docs/legal/LEGAL-OPS-PLAYBOOK.md:325` — *"Inbound-only (customer called the business) —
  **Not required** for TCCCPR telemarketing"*; `:403` — *"Inbound does not need prior
  telemarketing consent (the person called in)"*; `:29`; and `:287` makes an ordinary
  10-digit DID **the default for reception**, so the 140/160 series question does not arise.
  PE-TM chain, header registration, template approval and DND scrub are all outbound
  machinery and **none of it stands between this clinic and its first inbound call.** It all
  becomes blocking the moment the clinic wants an automated call-back.
- **What does bind:** the AI disclosure and the recording notice. The toggles are per-agent
  but the sentences are mandatory on file, and the truthful answer to "are you an AI / is
  this recorded" is appended to every prompt and cannot be withdrawn by any column
  (`packages/shared/src/calevate_shared/engine.py:2680-2810`), then verified against the
  engine on every publish. Correctly built — **and this is exactly what `multilingual_config`
  would break, which is why item 2 is not a config flip.**
- **Open, not code:** gate 37(a) (is a voice recording SPDI/biometric data — now governs the
  live conversation and the speech leg), and gate 40 (Sarvam ToS s.17.5 permits training on
  inputs/outputs absent a signed order form s.6.2; their privacy policy permits transfer
  outside India). For a clinic that is health-adjacent audio.

---

## BUGS — code that is wrong

1. **`{{ }}` merge fields are never substituted on the Bolna path, and on inbound nobody
   substitutes them at all.** `call_script.py:316-373` emits them verbatim; Bolna's syntax is
   `{key}` (`make.md:32`); `_call_prompt_for` returns None for control-plane engines
   (`apps/api/agents/service.py:1024-1033`) and the comment at `:2090-2093` asserts the engine
   handles it. Risk is the shape gate 8b names: an agent reading a placeholder aloud.
   *Blocks "the variables are also setup".*
2. **`agent_inbound_only` is misclassified and has no client copy.**
   `apps/api/compliance/service.py:180-182` + `apps/api/crm/attention.py:54-76`. Every
   call-back promise from an inbound-only receptionist defers and expires silently, and the
   client is told there is nothing to do when there is. *Ruins the fourth capability.*
3. **"Pause" does not stop an inbound number being answered.** Downstream of GAP-1:
   `unbind_inbound_number` raises `engine_number_not_linked`, so
   `deactivate_agent`'s release fails — the exact property
   `apps/api/agents/lifecycle.py:537-541` says it exists to guarantee. *Safety-relevant.*
4. **Stale docstring:** `apps/api/agents/publishing_routes.py:72` says the router is not
   mounted; `apps/api/main.py:194` mounts it.

No money bug, no RLS bug, no double-count and no dropped-call path in the inbound pipeline.

## GAPS — seams that were never finished

1. **FATAL — `phone_numbers.engine_number_ref` has no writer.** No route, no field, no
   screen, no service function. Evidence in §1. Without it no inbound number can ever be
   bound by this product, under either commercial model. *The fix is small and entirely
   ours once the Model A/B decision is made: one field on `ProvisionNumberIn`, one column in
   the INSERT at `apps/api/agents/service.py:2273`, one audited
   `PATCH .../numbers/{id}/engine-ref` beside the existing `dlt-status` route — and
   `route_inbound_numbers` already re-binds on write.*
2. **FATAL — the Bolna-buy path is closed at four layers and the port cannot express the
   vendor's request.** §1. Reopening it is a decision-log entry plus a change to published
   legal text, then: a `search` method on the port, a `phone_number` field on `NumberSpec`,
   a buy route, a screen, and a home for the monthly rental cost.
3. **FATAL for decision 4 — one language per agent.** `multilingual_config: None` on every
   publish (`apps/api/engine/bolna.py:3650`), for a hard-rule-5 reason. Size depends entirely
   on gate 3.
4. **No reschedule and no cancel on the calendar action** (`apps/api/actions/schema.py:148`),
   and the created event id is not stored, so there is nothing to reschedule against.
5. **No per-tenant secret store.** `tenant_secrets` is documented
   (`docs/PLATFORM-CONFIG.md:418`) and never migrated. Less urgent under Bolna-buy than
   under Model B, but a clinic's Google Calendar refresh token already lives in
   `integration_credentials`, so the pattern exists and the table does not.
6. **`agents.business_hours` never reaches the agent's prompt or KB.**
7. **Call-backs are not an attention-queue source**, and nothing warns at promise time that
   an account cannot place one.
8. **Recording is never requested in the publish body.** Vendor docs say recordings are
   *"available in the execution record"* (`bolna-findings/mirror/pages/concepts/security.md:19`)
   with no documented toggle, so it is presumed on by account default and our per-agent
   recording-notice switch controls only what we *say*. UNKNOWN — needs a live account.
9. **Inbound has no spend floor and no negative-balance alarm.**

## EXTERNAL BLOCKERS — the founder's checklist

- [ ] **0. DECIDE MODEL A vs MODEL B, in writing, as a decision-log entry.** Buying the DID
      from Bolna is Model A in everything but name (`bolna_owned: true`), and the playbook
      stop-list forbids it for a sole proprietor (`:602,611,621`). This blocks every line of
      code in GAP-2 and changes published Terms clause 3 and AUP §2.1. **Nothing else on the
      number path can start until this is answered.** If the answer is "yes, Model A": get
      the advocate's view on VNO/reseller status and whether incorporation must come first.
- [ ] **1. A funded Bolna account**, key into the ops console secrets panel. Unblocks
      gates 1-13, 16f, 21-35, 43a-43i.
- [ ] **2. RUN GATE 3 FIRST — the Telugu/English ear test.** Ten-utterance code-mixed script
      on real PSTN with Saaras `te-IN` + Bulbul v3. It costs one afternoon and it decides
      whether GAP-3 is zero work or a week of compliance-floor design. All 44 voices are
      `verified=False` today. Also gate 5 (barge-in, end-of-utterance on hesitant Telugu).
- [ ] **3. ONE REAL FORWARDED TEST CALL, and read `telephony_data`.** Forward a real Indian
      landline/mobile to a Bolna DID and record what arrives as the calling number. If it is
      the clinic's own number rather than the patient's, the CRM, the call-back and caller
      memory are all wrong for this customer. This is not currently a gate and should be one.
- [ ] **4. Buy ONE Indian number through `POST /phone-numbers/buy`** and record: whether
      `country: IN` + `provider: plivo` (or `vobiz`) actually returns a number, the exact
      shape of the returned `id`, the wallet debit and its **currency**, and the monthly
      rental. Settles gates 25 and 26 and gives `engine_number_ref` its first real value.
      Note the vendor contradicts itself: `vobiz` is in the buy REQUEST enum
      (`buy.md:67-73`) but not in the buy RESPONSE's `telephony_provider` enum
      (`buy.md:118-124`, `twilio|plivo|vonage|telnyx`).
- [ ] **5. Then `POST /inbound/setup` with that number's id** — gate 25's other half. Their
      Twilio guide says inbound-by-API *"currently requires connecting your Twilio account"*;
      if that is still true, inbound binding is a permanent manual dashboard step and the
      onboarding runbook must say so.
- [ ] **6. A Google Cloud project + OAuth consent screen**, then
      `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI`. Without these, appointment
      booking — which is built — refuses cleanly and does nothing.
- [ ] **7. Decide what "a doctor's slot" means** before the first clinic: one Google Calendar
      per doctor, or per clinic with event types. This shapes the reschedule work in GAP-4.
- [ ] **8. Gate 43 — one real knowledge-base upload** on the live account (PDF accepted?
      ingestion time? does `PUT` with `vector_store` actually make the agent retrieve?
      Telugu retrieval in `multilingual` mode?). For a clinic this is the product.
- [ ] **9. Gate 21 — open the Bolna Call Tab** for the published agent: outbound timing
      restrictions OFF, no ingest source configured. Console switches our publish body
      cannot set, and "on" is the dangerous direction.
- [ ] **10. Azure gates 20 / 20b / 20c** — resource really in East US 2, model deployable
      there, and the deployment **Regional Standard, not Global**. Global is the default and
      processes worldwide.
- [ ] **11. Gate 37 — the advocate, two yes/no questions.** Is a voice recording SPDI /
      biometric data, and may we run the call given the caller's audio may be processed
      outside India on the speech leg. For a clinic this is health-adjacent.
- [ ] **12. Gate 40 — Sarvam commercial terms.** A signed order form is the only instrument
      that displaces the s.17.5 training clause. Also ask where the 30-day content-retention
      setting is changed; nobody has found it.
- [ ] **13. Razorpay account + KYC + one real payment** (gate 44), or accept bank-transfer
      top-ups recorded by an operator.
- [ ] **14. Gate 36 — the Bolna DPA deletion clause.** A DPDP erasure request must reach
      their copy of the recordings; no code here can discharge it.
- [ ] **15. A host.** Nothing is provisioned, `terraform validate` has never run
      (`infra/README.md` §5), CD is disabled, and `webhook_base_url` and
      `actions_callback_base_url` must both resolve publicly before any webhook or any
      in-call booking works.

**Deliberately NOT on this list:** DLT PE registration, TM registration, header/template
approval and the national DND scrub. All outbound-only; none blocks the first inbound call
(`docs/legal/LEGAL-OPS-PLAYBOOK.md:29,325,403`). They become blocking the day the clinic
wants an automated call-back — which, given BUG-2, is worth deciding before the demo.
