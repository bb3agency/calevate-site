# ThinnestAI replies, 11-13 Oct 2026

Three emails from Ashutosh (ThinnestAI founder), relayed by the founder on 12 Oct 2026. Every
statement here is **VENDOR-STATED** (email) unless marked otherwise; where it disagrees with a
primary source, both are given. Earlier answers: rememory "ThinnestAI reply 11 Oct 2026" and
"ThinnestAI answers 11 Oct 2026 (second)". Questions asked: `thinnest-api-requests-2026-10-10.md`
and `thinnest-email-2026-10-11-gemini.md`.

## 1. Models (reply to the Gemini email, 11 Oct)

| Statement | Note |
|---|---|
| GPT-OSS 120B is "not suggested for voice calls, as it's fast but dumb"; what we heard at the end of call A was its thinking | Confirms the cause in `docs/evidence/in-call-model-trials-2026-10-11.md`. |
| They recommend **Prana [Voice]**; re-run the test with it | Not yet tested. |
| "All models on call are with reasoning off" | GPT-OSS 120B has no "off" (OpenAI harmony cookbook: low, medium or high), which matches what was heard; Gemini 3 Flash-Lite cannot fully switch it off either (below). |
| Gemini 2.5 Flash and Flash-Lite "are being deprecated by Google"; they offered them before and stopped because Google's implicit caching was not hitting, and explicit caching at $1/hour does not fit a ₹2-2.50 minute | **Google disagrees on the first half**: its deprecations page (updated 9 Oct 2026) says "No shutdown date announced" for both. Google does steer new projects to 3.x. The caching half is their measurement; we cannot check it. |
| **Offer:** Gemini 3.1 Flash-Lite on our Google key, with our own voice and **their speech recognition (Sarvam)**, for a **₹1/min** platform fee | This is set-up B of our email at ₹1.00. Set-up A (their voices, our model) was not answered. |
| A fine-tuned turn-taking and backchannel model of their own goes live "in a few weeks" | Nothing to build. |

**Gemini 3.1 Flash-Lite** (VP, ai.google.dev, read 12 Oct 2026): $0.25 per 1M input tokens,
$1.50 per 1M output tokens (thinking included), $0.025 cached input, $1.00 per 1M tokens per hour
of cache storage; earliest shutdown 7 May 2027 (deprecations page). Thinking: "Gemini 3 Flash and
Flash-Lite also do not support full thinking-off"; its default level is `minimal`, which "does not
guarantee that thinking is off"; thinking tokens are billed. Thought text comes back only as
summaries when `includeThoughts` is set (thinking page), so it should not reach the voice, but
its time and tokens are not zero. UNKNOWN until tested: how often minimal thinking adds delay.

## 2. The 10 Oct and 11 Oct (12:01 AM) emails, answered 12 Oct

**Agent voice settings, all now on the API** (`voice` on Get / Create / Update Agent; values
checked like the console and refused when out of range; a missing field keeps its value, `null`
resets it):

| Field | Meaning, default, range |
|---|---|
| `thinking` | fillers while the agent works; on |
| `thinkingLines` | up to 8 lines of 60 characters; empty or null = their fillers; not per language, a call uses the lines in the caller's script and falls back to theirs |
| `thinkingDelayMs` | quiet before a filler; 900, 200-5000 |
| `thinkingRepeatMs` | gap between fillers and during a tool call; 2500, 1000-10000 |
| `thinkingAtTurnEnd` | a short acknowledgement before every reply; off |
| `turnSilenceSeconds` | 0.2-3; null = their adaptive default, about 0.25 s |
| `interruptWords` | 1-6; 3 |
| `neverInterrupt` | whole agent including the greeting; not per line or step |
| `holdShortSpeech` | keep words spoken over the agent; on |
| `greetingUninterruptible` | phone lines; off |
| `ambience` / `ambienceVolume` | null, "office" or "office-quiet"; 0.15, 0.05-1 |
| `endCallOnFinish` | off on new agents |
| `nudgeAfterSeconds` / `nudges` / `nudgePhrase` | "are you still there?": null or 5-180; 1-5, default 1; up to 120 characters, empty = theirs in the caller's language |
| `endAfterSilenceSeconds` | 5-180; the call stretches it so every nudge gets its turn |
| `endPhrases` | up to 12 phrases of 2-60 characters, matched anywhere in what the caller says, any language, case and punctuation ignored |
| `callInstructions` | up to 4,000 characters, separate from `instructions` and not counted in their limit; on calls it **replaces their built-in call rules**, is placed after the instructions, and generally wins a conflict |

**Where the agent answers:** `voice.surfaces` is writable: any of "phone", "web", "whatsapp".
**A new agent starts with the website call button and WhatsApp**; phone is added when a number
is attached. Adding "phone" with calls on and no number gives 409 `phone_number_required`.
WhatsApp calls also need the Calls switch on the WhatsApp connection.

**Doc conflicts settled:** Studio voices need **Pro** or above (the Scale guide was wrong). The
instructions limit is **20,000 characters everywhere** (API, console save, MCP); the 8,000 was
only the console text box, which now counts to 20,000. Steps are separate: 12 steps, 80-character
title, 600-character detail.

**Current step:** not reported by test chat or calls; noted as a request.

**Our own voice key per customer:** works as we built it (D-717): with our developer switch off,
a customer with its own key and `{"enabled": true, "scope": "voice"}` runs voice-only BYOK on
its own (`GET /byok` → `using: "own"`), others unaffected; an agent there with `byok: "off"`
stays on their voices at their rate. The same Cartesia key may be installed in any number of
customer workspaces.

**Money:**
- A voice-only BYOK minute is ₹1.50, 30-second pulses, charged to our developer wallet, shown in
  `costMicro`.
- **Top-ups carry only the payment gateway's charge, 2.36% in INR, the same for everyone.** This
  contradicts the console reading of 6 Oct (10% pay-as-you-go, 8% Scale) and the 9% Pro figure
  our code uses (`billing/rates.THINNEST_PAYG_TOPUP_FEE` / `THINNEST_WALLET_TOPUP_FEE`, D-723).
  Our recorded costs are therefore overstated by about 7-8% of the ThinnestAI part.
- Test chat: each reply costs a website chat reply on the agent's model, and appears in the inbox.
- `GET /models` now returns `callTier` (standard or premium), `callPricePerMinuteMicro` and
  `currency`; the price is the model with a standard voice, raised by a premium or Studio voice,
  replaced by the BYOK rate for a BYOK agent. Only GPT-5 Mini is premium today. GPT-OSS 120B's
  id is `gpt-oss-120b`, on every plan, no surcharge.
- They do not publish latency; the Playground figures are approximate.

**Confirmed as built:** `callStartUrl` returns the new secret on a `PATCH` that sets a new
address and on `callStartSecret: "rotate"`; the signature is HMAC-SHA256 over
`<x-thinnest-delivered-at>.<body>`; 0.8 s is inside their 2 s. `ringSeconds` is live on every
plan and covers campaigns, call-backs, Place Call and batch calls; forwarded calls always ring
30 s. Forwarding with the agent off works (as on 11 Oct).

**A change made during a live call:** the connected call keeps the full configuration it started
with (instructions, steps, model, voice settings); the next call uses the new one. This holds for
every agent field (OPERATIONS T-28).

**Custom actions in a test chat:** `{{call.id}}` and `{{call.from}}` are empty and `X-Call-Id` is
not sent; every request carries `X-Test-Chat: true` and `{{test.chat}}` fills as "true". The
console Playground and MCP tool calls do not set it.

**Our Cartesia clones:** `GET /byok/voices` lists our own account's voices first, then
Cartesia's catalogue page by page up to 2,000, with a `complete` field when partial;
`PUT /agents/{id}/byok-voice` and per-call `overrides.voice` accept our own clones, checking
Cartesia directly for a voice missing from the list.

## 3. What Studio would cost us with Gemini 3.1 Flash-Lite at ₹1/min

Same method and token figures as `docs/evidence/in-call-model-research-2026-10-11.md` §6a-6b
(about 23,500 input and 200-400 output tokens a call minute; ₹96 per USD), with the gateway charge
of 2.36% now stated by ThinnestAI. They report implicit caching does not hit, so no caching is
assumed. Minimal thinking adds output tokens not counted here (about ₹0.04 a minute per 50
thinking tokens a reply).

Gemini 3.1 Flash-Lite: 23,500 × $0.25 + 200-400 × $1.50 per 1M = $0.0062-0.0065 = **₹0.59-0.62
a minute**.

| Minutes a month | Studio today (₹1.50 + Cartesia) | Studio + Gemini 3.1 Flash-Lite (₹1.00 + Cartesia + Gemini) |
|---|---|---|
| 1,000 (pay-as-you-go) | ₹4.96 | ₹5.03-5.06 |
| 5,000 (Pro) | ₹4.37 | ₹4.44-4.47 |
| 10,000 (Pro) | ₹4.19 | ₹4.26-4.29 |
| 25,000 (Pro) | ₹3.70 | ₹3.77-3.80 |
| 50,000 (Pro) | ₹3.66 | ₹3.73-3.76 |

Each figure: ThinnestAI × 1.0236 + Cartesia on its cheapest plan at 571 characters a minute
(₹3.42, 2.33, 2.40, 2.06, 2.07) + ThinnestAI Pro's ₹2,499 spread over the minutes above 1,000.
So the Gemini set-up costs us about **₹0.08-0.11 a minute more** than Studio today. Rate card: Studio
₹6.00 (D-728).

## 4. What it changes in Calevate

| # | Change | Size | Waits on |
|---|---|---|---|
| 1 | **Top-up fee 2.36%, not 10%/9%.** Our cost per minute (`billing/engine_minutes.thinnest_topup_fee`, rates constants, cost floors, margins, the charge reconciler) uses the wrong fee, so every ThinnestAI cost row and margin is overstated. Fix forward, plus compensating usage rows for past calls (hard rule 4). Client prices are unaffected. | half a day | founder: confirm against a real wallet top-up receipt (money, hard rule 7) |
| 2 | **Instructions limit 20,000, not 8,000.** Raise `engine/thinnest.INSTRUCTIONS_MAX_CHARS`, the prompt budget test, the Script page meter and refusal; D-752's cuts can be relaxed and the common facts can sit in the instructions (no knowledge search, faster replies). Longer instructions cost more model tokens per reply under our own Gemini key. | 2-3 hours | nothing |
| 3 | **`voice.surfaces` defaults to web and WhatsApp on a new agent.** Today every agent we create is reachable from a website call button and WhatsApp that we never offered. Send `surfaces` explicitly on every create and update and add it to the drift check; which surfaces to send is a product decision. | 1-2 hours | founder: phone only for now, or also web/WhatsApp |
| 4 | **Test chat marks itself (`X-Test-Chat: true`, no `X-Call-Id`).** Our in-call actions (do-not-call, call-back, bookings) must answer success and write nothing on a test chat; the once-per-call guard keyed on `X-Call-Id` must handle its absence. | 2-3 hours | nothing |
| 5 | **The rest of the voice settings on the API.** `endPhrases` (end the call on "cut the call", "కట్ చేయండి"), `nudge*`, `endAfterSilenceSeconds`, `thinkingLines` per script language, `thinkingAtTurnEnd`, `greetingUninterruptible`, `neverInterrupt`, `holdShortSpeech`, `ambience`. Send our values on every agent and drift-check them; expose the useful ones in Call handling (D-751 pattern). | 1-2 days for all; `endPhrases` and the nudges alone half a day | founder: which ones clients may change |
| 6 | **`callInstructions` replaces their built-in call rules.** We could move our call rules there (outside the 20,000) and stop conflicting with theirs, but we would then own every rule theirs covered (ending, interruptions, time). | design first, then a day | their built-in rules' text (unanswered) |
| 7 | **`GET /models` price fields.** Read `callTier` / `callPricePerMinuteMicro` to show and check model bands instead of an operator typing them; the attested rate stays what bills (hard rule 7). | half a day | nothing |
| 8 | **Our own Cartesia clones.** The voice catalogue sync can list our own clones (they come first) and must read the `complete` flag. | 2-3 hours | nothing |
| 9 | **Gemini 3.1 Flash-Lite on our key, our voice, their Sarvam STT, ₹1/min.** A new set-up: install our Google key per workspace, a new rate key and rung, model choice, and metering of Gemini's cost, which ThinnestAI does not report per call (Google bills us in total). | 3-5 days | ThinnestAI: how it is switched on through the API (scope name, key kind), and a test; founder: whether to adopt it |
| 10 | **Docs only:** Studio needs Pro; a change during a live call waits for the next call (OPERATIONS T-28 closed); `callStartUrl` secret and `ringSeconds` confirmed; GPT-OSS id `gpt-oss-120b`. | 1 hour | nothing |

Founder action, no build: a test call on **Prana [Voice]**, as ThinnestAI recommends.

## 5. Still unanswered (as of 12 Oct; most answered 13 Oct, §11)

From the 9 Oct email: the signed DPA and sub-processor list ("being prepared"), and training off in
writing for every workspace.

From the 11 Oct Gemini email (numbers as sent):

- 1 (Gemini): the price on Pro and Scale; set-up A (their voices with our Gemini); what happens
  when our Google key fails mid-call; whether per-agent model choice, `temperature` and
  `maxReplyTokens` work. How the ₹1 set-up is switched on through the API.
- 8: whether Prana and Prana [Voice] reason, and Telugu measurements.
- 9: whether GPT-5.4 Nano is allowed with our own voice; what a disallowed agent runs on.
- 10: whether `temperature` and `maxReplyTokens` apply on calls.
- 12: what makes up the 2-3 s before the first word.
- 13: the Smart / Timer / Ear end-of-turn mode on the API.
- 14: Telugu recogniser accuracy and per-agent choice (the recogniser is Sarvam, from the offer).
- 15: our own voice's speed, volume and emotion on the API.
- 16: the Cartesia pronunciation dictionary.
- 17, 18: the spoken time line and the bracketed notes.
- 19-21: interrupted turns trimmed, joined generations, cut-off speech billed to our Cartesia.
- 22, 23: how the agent ends a call, and what the built-in call rules say.
- 24: narrowing the built-in do-not-call and reporting its trigger words.
- 25: `tools[].output` shape and language detection in test chat.
- 26: TRAI regulation 4, the Originating Access Provider notice.

Answered on 12 Oct in passing: 11 (a BYOK agent bills at the flat BYOK rate whatever the model).

## 6. Audit against the code, 12 Oct 2026: what is still to build

A file-by-file check of every 11 and 12 Oct answer. Already built, with evidence: caller lookup
with repeat dedupe (`worker/engine_lookups.py`), new secret on PATCH and rotate
(`engine/thinnest_actions.py:566-609`), once-per-call actions (`reliability/in_call_once.py`),
the soft source-IP check, `speakBefore`, number-level forwarding as the healer's fallback
(`campaigns/engine_numbers.py:935-995`), `call.problem`, the quality block, the status API,
waiting out `agent_on_live_call`, number move with step-up auth, the Clear/Studio hand-off guard.

Still to build, in order:

1. **Voice catalogue paging (a bug in waiting).** `list_own_key_voices` reads one page and
   ignores `complete`, and the sync withdraws every voice the listing does not name on the
   premise that the listing is unpaged (`agents/hosted_voices.py:404-411`). ThinnestAI now pages
   it to 2,000 with `complete`; a partial read would withdraw voices clients chose. Walk the
   pages, never withdraw on a partial listing, mark our own clones. 2-3 h.
2. **Instructions limit 20,000** (`engine/thinnest.INSTRUCTIONS_MAX_CHARS`, `agents/prompt_routes.py:55`,
   `lib/api/prompts.ts:37`, `teach/pinned.py`, tests `thinnest_publish_limits`, `agent_prompt_budget`,
   `prompt_size`, docs). 2-3 h.
3. **`voice.surfaces` sent and drift-checked**; handle 409 `phone_number_required`; retire the
   D-720 "information only" stance. 1-2 h. Founder: phone only, or web and WhatsApp too.
4. **Top-up fee 2.36%**: one constant, floors, the meter, the reconciler, the fee label map (keyed
   by value), a compensating row for every cost row written at 10% or 9%, ops panel, tests, docs.
   Half a day. Founder: confirm from a top-up receipt.
5. **Test chat**: read `X-Test-Chat`; opt-out, call-back and cancel answer success and write nothing;
   decide the same for client actions. 2-3 h.
6. **Idempotency-Key on renting a number**, and 409 `idempotency_in_progress` read as "maybe bought,
   read back"; close T-19. 1-2 h.
7. **`endPhrases` and the nudges** (half a day), then the other voice fields and Call handling UI
   (1-2 days). Founder: values, and which clients may change.
8. **`GET /models` price fields** read and checked against the recorded bands. Half a day.
9. **`allottedCallLines` per customer.** Half a day. Founder: how lines are split.
10. **Test-chat cost metering.** Half a day, once ThinnestAI states the per-reply price per model.
11. **Docs**: T-19 and T-28 answered, the "UNVERIFIED" usage-id note in `workers/engine_charges.py`,
    Studio needs Pro, `gpt-oss-120b`, the `endCallOnFinish` line in THINNEST-INTEGRATION, the fee
    text. 1 h.

Not without a decision: `callInstructions` (needs their built-in rules' text), the Gemini ₹1
set-up (needs their API switch and the founder), and a sweep for forwarded calls with no agent
(rejected by D-743 because we never detach an agent).

## 7. Ashutosh's first answers to the consolidated email, 12 Oct 2026 11:44

He answered what he knew and will check the rest with his backend team, adding that "some of
the answer may be inaccurate"; corrections and the remaining answers will follow. VENDOR-STATED.

| Our question | His answer | Note |
|---|---|---|
| 1.1 How the Gemini ₹1 set-up is switched on | **Not built.** Only "all three keys" and "voice only" exist. Try Prana [Voice] meanwhile. | Plan W-Gemini stays parked. |
| 1.2 ₹1 on every plan, 2.36% on top-ups | ₹1/min on every plan; 2.36% gateway charge on top-ups on every plan. | Confirms founder decision F2 (build W4). |
| 1.3 Thinking level, includeThoughts | Calls use thinking "none" where the model has it, otherwise "minimal". Prana [Voice] takes `{"reasoning": {"effort": "none/low/high/max"}}`. | Whether we can set Prana's effort per agent through the API is not said. |
| 1.4 Our Google key refused mid-call | **The caller hears silence.** Keep the Google key on a higher tier. | A real risk for any own-key model set-up: a failed key is a silent call. |
| 1.5 Per-agent model, temperature, maxReplyTokens | Temperature is applied, shown as Answer Style (Strict, Balanced, Creative). He also says "Gemini 2.5 Flash models are being deprecated on 15th October 2026". | **Conflicts with Google**: its deprecations page (updated 9 Oct 2026) says "No shutdown date announced" for `gemini-2.5-flash` and `gemini-2.5-flash-lite`. Neither source settles which is right for their account; recheck Google's page before relying on 2.5. maxReplyTokens and per-agent model not answered. |
| 1.6 gemini-2.5-flash-lite on our key | "Yes definitely, you can use gemini key." | Today that means scope "all": our own speech recognition too (1.1). |
| 1.7 Their voices with our Gemini key | Price would not differ much, since the model costs them little; negotiable with a minimum monthly commitment at higher volume. | |
| 3 Time to the first word | "This has been fixed." | Re-test the opening delay on the next outbound test call. |
| 4.2 Telugu speech recognition | Sarvam STT / "Indic-Transcribe", which has publicly available accuracy data. | Per-agent choice and the end-of-turn mode not answered. |
| 8 Prana reasoning | Their models were tested; reasoning is controllable with `{"reasoning": {"effort": ...}}`. | Telugu results not given. |
| 9.2 Match the customer in test chat | **Does not work in chat mode**; they will build it. | Our test chats in Telugu may get English replies until then; the agent's language should be fixed to Telugu for Telugu test chats. |
| 10 TRAI automated-call notice | They use **Plivo** for telephony; other details to follow. | Plivo is a communications platform, not itself an Indian access provider, so the Originating Access Provider is still to be named. |

Still to come from him: 1.5 (maxReplyTokens, per-agent model), 2 (our voice's speed, volume,
emotion, model and pronunciation dictionary through the API), 4.1 (end-of-turn mode), 5 (text
that is not speech), 6 (interruptions), 7 (ending calls and do-not-call), 8.2-8.3 (GPT-5.4
Nano, the fallback model), 9.1 (`tools[].output`), 10 in full, 11 (DPA, sub-processors,
training off).

## 8. Negotiation opening (founder, 12 Oct 2026)

Ashutosh's answer to 1.7 is a lever: "If you use our STT and TTS, the cost wont differ much,
cause LLM don't cost us much. We can negotiate if you have minimum monthly commitment with
higher volume." In his own words the model is a small part of their cost, which means the
₹2.50 Clear minute (their speech recognition, model and voice) carries room. The founder intends
to ask for a lower per-minute price against a minimum monthly commitment once our volume
supports one. To prepare: our monthly minutes by tier (the usage ledger has them), a commitment
level we can safely meet, and the price that would move Clear's margin (our rate card ₹4.50,
D-728). Our own model on their voices would be the set-up to price in the same conversation.

## 9. Questions for the next email (from the 12 Oct build)

1. `GET /byok/voices`: could each voice say whether our own Cartesia account owns it? Today the
   answer has id, name, language, gender and sample, and only the order says "own voices first".
2. Does `POST /phone-numbers` (rent) honour `Idempotency-Key`? The errors page says keys are kept
   24 hours, but the rent page does not list the header. We now send it (OPERATIONS T-19).
   **Answered 18 Oct 2026 (Ashutosh, item 17): yes, it is honoured.**
3. Is `voice.surfaces: []` accepted on an agent with no number? We send it so a new agent does not
   answer on the website button or WhatsApp. **Answered 18 Oct 2026 (item 12): accepted;
   `phone_number_required` fires only when `phone` is added without a number.** The retry
   without the field and its alarm `engine_agent_surfaces_refused` were removed.

## 10. Ashutosh's answer on the automated-call notice (TRAI TCCCPR regulation 4), received 13 Oct 2026

Answers question 10 of the consolidated email (§10, six parts). **VENDOR-STATED, and
second-hand:** ThinnestAI relays what Plivo, their telephony provider, told them. **Every
part is still open**; ThinnestAI is waiting on Plivo's written clarification and will send it.
**Founder, 13 Oct 2026: record it and wait for their confirmation.**

| Our question | Their answer | Still open |
|---|---|---|
| 10.1 Which licensed operator issues and originates the numbers | Licensed Indian telecom operators provide the numbering and network origination underneath Plivo. | **Which operator** stands behind each of our numbers. |
| 10.2 Who is the Originating Access Provider | Plivo coordinates with its underlying operators for origination and regulatory compliance. | Whether the operator or Plivo handles the regulation 4 notice for customer workspaces. They have asked Plivo in writing. |
| 10.3 How a client gives the notice | Plivo is still working out the workflow for the 080/022 fixed-line numbers with its access-provider partners. | No endpoint, form or process through ThinnestAI yet; to be shared once Plivo confirms. |
| 10.4 What acknowledgement comes back | No standard acknowledgement, reference number or certificate confirmed yet. Meanwhile: keep the written notice sent to the provider and any written acknowledgement, with the workspace, business identity, numbers, call purpose and submission date. | The evidence form. |
| 10.5 Existing declarations | For existing 080/022 fixed-line numbers, each number must be mapped to the business actually making the calls; where a platform calls for a client, the compliance ID must be the client's. Plivo says the mapping can be reviewed and updated in its console or API. | Whether automated-call notices and their purposes are declared today for every client workspace, or whether one account-level declaration covers all clients. |
| 10.6 DLT declarations under the Third Amendment | The CLI registration and DLT declaration workflow is being developed with the access-provider partners. | Who submits each declaration, how client-specific ones are recorded, and what evidence is issued. |

Their interim advice: keep our own records of the business making the calls, the purpose and
nature of each automated-calling use, the numbers used, and the customer consent and campaign
records.

**Superseded the same day by D-762 (founder, 13 Oct 2026):** the product no longer asks a
client for the notice; a disclosure inside the no-cold-calls pledge (version 2) replaces it,
and the risk that the regulation still binds the Sender is accepted. The two bullets below
on the notice describe the position before D-762. The open questions in this section stand.

**What it changed in Calevate at the time of the reply: nothing in code.**
- **The notice stays the client's job.** Regulation 4 binds the Sender, and a client is the
  Sender (`compliance/autodialer.py`). Nothing in this reply says ThinnestAI or Plivo gives
  the notice for a workspace. So the outbound gate keeps refusing a dial until the client has
  recorded its notice (`autodialer_notice_blocker`, `autodialer_notices`), and no screen tells
  a client it is compliant.
- **Records.** The interim advice matches what we already keep per client: business identity
  (KYC record, D-692/D-696), numbers rented in the client's own name in its own workspace
  (D-693), consent and DNC records, campaigns, and the notice record with its date and stated
  objective.
- **Number mapping (10.5).** Our numbers are rented in each client's own workspace and business
  name (D-693). Whether Plivo's own mapping for each number names the client and carries the
  client's compliance ID is not something we can see from here. Ask for it in the follow-up.
- **OPERATIONS gate 59 stays open.** No operative text, notice form, unit or acknowledgement
  has been confirmed.

**Ask in the follow-up, once Plivo answers:**
1. The licensed operator behind each number we rent, and whether Plivo or that operator is the
   Originating Access Provider.
2. The notice procedure for a client (to whom, in what form, through which channel), and the
   acknowledgement it returns.
3. Whether each of our clients' numbers is mapped at Plivo to that client's business and
   compliance ID, and how we can read that mapping per workspace.
4. Who records the DLT declaration under the Third Amendment, per client.

## 11. Ashutosh's full answer to the consolidated email, received 13 Oct 2026 11:34

Answers §7's "still to come" and corrects three of his 12 Oct answers. **VENDOR-STATED**
(email, relayed by the founder 13 Oct 2026). He says the new API fields are in their docs
(Bring your own keys and the agent pages); our mirror's latest snapshot is `2026-10-08`, so
**none of the new fields below is VERIFIED-VENDOR-DOCS yet** (hard rule 11): a fresh snapshot
comes before any wire value is built.

### 11.1 Corrections to the 12 Oct answers

| Item | 12 Oct said | 13 Oct says |
|---|---|---|
| 1.4 Our model key refused or rate-limited mid-call | The caller hears silence | The caller hears "Sorry, I am having trouble just now. Could you say that again?" on that turn. `call.problem` with `kind: byok_failed` fires once per call, and a critical `byok.failed` notification names the reason. **No backup model on our own keys.** Silence only if the failure comes mid-sentence or the voice key fails. |
| 1.3 Thinking level | "none" where the model has it, else "minimal" | On our key nothing was sent before; now the lowest level the model accepts, thought text never requested. Gemini 3 Flash-Lite and other Gemini 3: `minimal` (Google: may still reason a little). Gemini 3 Pro: `low`. Gemini 2.5 Flash and Flash-Lite: thinking off. Gemini 2.5 Pro: smallest budget. |
| 8.1 Prana | Reasoning controllable | Prana reasons and runs at "low" on calls. Prana [Voice] sends no reasoning setting. |

### 11.2 Answers

| Our question | Their answer | What it means for us |
|---|---|---|
| 1.1 Gemini on our key, their speech recognition, their voice | **Built.** `PUT /api/v1/byok/credentials/llm` (provider `google`, with a model), then `PATCH /api/v1/byok` `{ "scope": "llm", "enabled": true }`. A workspace setting like scope `voice`: a customer workspace uses our key unless it brings its own. | Same inheritance as scope `voice` (D-717/D-727): switching it on in the developer workspace would put every client without its own key on our Google key. Whether an agent can opt out (as `byok: "off"` does for voice) is **not stated**. |
| 1.2, 1.7 Price | Scope `llm`: the normal per-minute plan of the voice the agent speaks (Standard, Premium or Studio, plan discount applies); nothing extra for the model. ₹1/min flat only when **all three** keys are ours; voice-only ₹1.50. Top-ups 2.36%. Chat replies on this scope ₹0.02. | **Clear with our Gemini costs the same ₹2.50 as Clear today, plus our Google bill**: no saving, only a model choice. The 11 Oct offer (our Gemini, our voice, their recogniser at ₹1) is now unpriced: the voice and llm scopes together are neither "voice-only" nor "all three". Must ask. |
| 1.5, 1.6 Models | Any model our key offers; per agent with `PUT /agents/{id}/byok-model`, including `gemini-2.5-flash-lite` (thinking off). Temperature applies on calls (Answer Style). | `maxReplyTokens` still not answered. His 12 Oct "2.5 deprecated 15 Oct 2026" still conflicts with Google's page ("No shutdown date announced", 9 Oct); recheck before choosing 2.5. |
| 2 Our Cartesia voice | Per agent: speed 0.6-1.5, volume 0.5-2.0, emotion (English only), Sonic model incl. `sonic-3.6`, pronunciation dictionary id. Console "How it sounds", `PUT /agents/{id}/byok-voice`, or MCP. `POST /byok/voices/preview` plays a setting before saving. Sent on every speech request; a PATCH that omits them keeps them. Speed not on Professional Voice Clones; speed, volume and emotion refused on Sonic 2. | Today `_apply_own_key_voice` sends only `{"voice": …}` (`engine/thinnest.py`). **They could not hear `sonic-3.6` on our account: founder to check it once** (preview in their console). |
| 3 Time to first word | The greeting is a fixed line before the model runs. Cut from about 1.0-1.1 s (answer webhook to first audio) to about 0.4-0.5 s, plus carrier and phone time. A shorter greeting and voicemail detection off help. | Re-measure on the next outbound test call. Voicemail detection is already off. |
| 4 Turn-taking | `voice.turnDetection`: `smart`, `timer` or `ear`. Platform default **Timer**. In Timer, `turnSilenceSeconds` is the silence that ends a turn (default 0.25 s); in Smart it is a ceiling (default 0.6 s). Ear needs a recogniser that supports it. Telugu uses Sarvam; they have no Telugu accuracy figures; recogniser per agent only with all three own keys. | We send `turnSilenceSeconds` from Call handling and never state the mode, so a change of their default would change what our number means. |
| 5 Text that is not speech | "[cut off before finishing]" was theirs; "[awaiting response]", "(Waiting for user response)", "[hang_up]", "[call hang_up]" were the model's. Now stripped before speech and before saving: bracketed stage directions, visible thinking, link addresses, written tool names. "(Monday to Friday)" and "[1]" stay. | Nothing to build. Transcripts saved before the fix keep the old text. |
| 6 Interruptions | The thrice-glued question was their bug (a backup-model retry appended with no space); fixed, and the retry is told what the caller heard. A cut-off turn is trimmed to what was heard and the model sees it was cut off; the stored transcript is corrected where possible; rarely the summary may still show the full reply. Text goes to the voice sentence by sentence, so a cut-off sentence may already be synthesised on our Cartesia account. | Studio's Cartesia cost (571 characters a minute in §3) does not count synthesised-but-unheard sentences: an UNKNOWN uplift to the Studio cost floor. |
| 7 Ending calls and do-not-call | The model ends a call with the `hang_up` tool; "[hang_up]" in a transcript was the model's text. `callInstructions` replaces **only their 16 speaking rules** (short replies, no brackets, one question per turn …); the hang-up rule, the interruption rule, the clock line and the do-not-call tool stay. The false do-not-call was theirs (the tool description did not exclude "that's all, you can cut the call"); now excluded, and it asks first when unsure. `contact.opted_out` now carries the caller's words as `reason`. `voice.recordDoNotCall` turns the tool off per agent. Goodbyes in Telugu, Tamil, Kannada, Malayalam, Bengali and Marathi end calls; "let's talk later about the price" does not. Their fixed fallback lines (apology, closing) are written in Hindi and Telugu; a native speaker is reviewing them and they invite corrections. | The clock line cannot be turned off. The 16 rules' text is still not given. Founder: review their Telugu fallback lines. |
| 8 Models they host | With voice-only BYOK, an agent set to a model that is not allowed runs on GPT-OSS 120B. | `agents/engine_choice` already refuses a non-`voiceOnlyByok` model for a Studio agent. |
| 9 Test chat | `tools[].output.result` is our response body as a raw string (not parsed JSON), cut at 4,000 characters. With "Match the customer", chat follows the script of the latest message (Telugu script → Telugu); Telugu in English letters is the model's judgement. | Our parser (`engine/thinnest._test_chat_tool`) reads `output` itself, not `output.result`; check against the docs snapshot. |
| 10 TRAI notice | The Plivo statement stands; he will write when Plivo answers. | §10 and D-762 unchanged. |

### 11.3 What it touches in Calevate

| # | Area | Today | Change | Waits on |
|---|---|---|---|---|
| A | Docs snapshot | Latest mirror `2026-10-08` | Fresh snapshot of Bring your own keys, Set agent BYOK voice and model, Preview BYOK voice, Update agent (`turnDetection`, `recordDoNotCall`), Webhooks (`contact.opted_out` `reason`, `byok.failed`), Test chat. Every item below cites it. | nothing |
| B | Own-key failure alarm (`workers/engine_signals.py`) | `own_key_failed` alarms "could not get an answer, even from its backup model" | Correct the text: no backup on our own keys, the caller heard the apology. Subscribe to `byok.failed` if it is a webhook event (UNKNOWN until A). | A |
| C | Studio voice tuning | `PUT /agents/{id}/byok-voice` sends `voice` only | Per-agent speed, volume, emotion, Sonic model and pronunciation dictionary id: stored on the agent (migration, `pg_dump` first), sent on every publish, read back by the drift sweep, previewed with `POST /byok/voices/preview` before saving. Refuse speed on a Professional Voice Clone and all three on Sonic 2, as they do. | A; founder: admin only, or clients too |
| D | Turn detection | Mode never sent; `turnSilenceSeconds` sent | Send `voice.turnDetection` explicitly (`timer`, today's behaviour) on every create and update, add it to the drift map, and say in the Call handling copy that the silence ends a turn. | A |
| E | Do-not-call reason (`workers/engine_signals.py` opt-out path, `compliance/optout.py`) | `contact.opted_out` files the number; no reason kept | Keep `reason` as the opt-out evidence (the `matched` span the consent ledger already stores), capped and redacted like transcript text, shown to the client as why the number was added. Never logged (hard rule 6). | A |
| F | Their do-not-call tool (`voice.recordDoNotCall`) | On by their default, beside our own opt-out action | Keep it on (a missed opt-out is the costlier error), send it explicitly and drift-check it so a change of their default cannot switch it off. | founder (recommend: on) |
| G | Test chat tool output | Reads `output`, parses a string | Read `output.result` if that is the shape; tolerate the 4,000 cut (an unreadable status shows as unknown, not as failed). | A |
| H | Gemini on our key (scope `llm`) | Not built (W-Gemini parked) | Per-workspace Google key install and `scope: llm` switch with read-back (the `ensure_studio_workspace` pattern), `PUT /agents/{id}/byok-model`, model choice in `engine_choice`, a rate key, metering of our Google cost. | ThinnestAI: questions 1-3 in §11.5. Founder: adopt or not. |
| I | Studio cost floor | Cartesia at 571 characters a minute | Mark the unheard-sentence uplift UNKNOWN on the cost model; measure from Cartesia usage against our minutes once Studio carries traffic. | traffic |
| J | `callInstructions` | Not used | Still not adopted: the 16 rules' text is not given, and their non-replaceable rules already cover ending, interruptions, time and do-not-call. | their 16 rules' text |
| K | Docs | — | THINNEST-INTEGRATION (turn detection, thinking levels, own-key failure, text stripping, interruptions), OPERATIONS (first-word latency re-test), this file's §5. | nothing |

### 11.4 Build plan, in order

1. **A** docs snapshot, then a one-pass check of every field in §11.2 against it. Anything the
   docs do not show stays out of the build and goes into the next email.
2. **B, D, G, K** together: small, no migration, no decision. One commit.
3. **E** opt-out reason: no migration if it fits the existing evidence column, otherwise one
   reversible migration. One commit.
4. **F** after the founder's answer (one line in the publish body and the drift map).
5. **C** Studio voice tuning: migration (`pg_dump` before deploy), adapter, drift, preview,
   admin UI, tests for the new behaviour only. About a day.
6. **H** only after ThinnestAI answers §11.5 questions 1-3 and the founder decides.

### 11.5 For the next email

1. Our Gemini key with our own Cartesia voice and your recogniser (scopes `voice` and `llm`
   together): what is the per-minute price? The 11 Oct offer said ₹1; the 13 Oct answer gives
   ₹1 only when all three keys are ours.
2. With scope `llm` on in our developer workspace, every customer workspace without its own key
   uses ours. Can a single agent stay on your models (like `byok: "off"` for the voice), or does
   it apply to every agent of the workspace?
3. On our own Google key, does any webhook or usage record give the tokens per call, so we can
   cost each call?
4. Is `byok.failed` a webhook event we can subscribe to, and what does its payload carry?
5. The text of the 16 speaking rules that `callInstructions` replaces.
6. Is `maxReplyTokens` applied on calls?

### 11.6 What we want, and what their console offers (founder, 13 Oct 2026)

**Founder's target set-ups:**
- **Clear:** their speech recognition and their voice, **our model** (Gemini on our key).
- **Studio:** their speech recognition, **our voice (Cartesia) and our model**.

Their console's "Which keys are yours" (screenshot relayed by the founder, 13 Oct 2026) offers
three choices, one per workspace:
- **All three of my keys** at ₹1/min all-in.
- **Only my voice** at ₹1.50/min (their speech-to-text, model and telephony).
- **Only my language model**, billed on the normal voice plan (Standard, Premium or Studio).

So Clear maps to "Only my language model". **Studio as the founder wants it (our voice and our
model, their speech recognition) is not one of the choices.** It was the 11 Oct ₹1 offer
(§1). Because the choice is per workspace, a client with both Clear and Studio agents also
needs it per agent. Today's code runs both rungs on their model: Clear has no own key and
Studio uses "Only my voice".

**Ask them:**
1. A fourth choice, "my voice and my language model, your speech-to-text", at the ₹1 offered on
   11 Oct.
2. The choice set per agent, not only per workspace.
3. Questions 3, 4 and 6 of §11.5.

### 11.7 Their console now offers our two set-ups (founder, 13 Oct 2026, later the same day)

The founder relayed a fresh screenshot of the console's "Which keys your agents use by
default" and reported that the feature is built. It now offers four choices:

| Choice | What is ours | Price shown |
|---|---|---|
| All three of my keys | speech-to-text, LLM and voice | ₹1/min all-in |
| Only my voice | voice (their speech-to-text, model and telephony) | ₹1.50/min |
| **My voice and my language model** | LLM and voice; they keep the speech recogniser | **₹1.00/min** |
| Only my language model | LLM (e.g. Gemini or OpenAI); their speech-to-text and voice | the per-minute voice plan of the call: Standard, Premium or Studio |

So both founder set-ups (§11.6) exist: **Clear = "Only my language model"** (scope `llm`),
**Studio = "My voice and my language model"** (scope `llm_voice`; ₹1.00/min with their speech-to-text and phone line included,
`bring-your-own-keys.md:18-20, :25-28`). §11.6's first ask is answered; D-764 is
built on exactly these two scopes and stays switched off until the founder turns it on.
The prices are as shown in their console (VENDOR-PUBLISHED, founder-relayed); D-764 still
bills the ₹1 minute only at an operator-attested figure.

Their screen and the docs (`bring-your-own-keys.md:22-24, :27`) name a **"Standard"** voice
plan beside Premium and Studio. Our code knows the Premium and Studio bands only
(`thinnest_clear_voice_band`). Ask what Standard is and what it costs before offering it. The
same table bills a chat reply at ₹0.02 on both own-model scopes (:28), so test chats on our model
cost per reply.

**Founder decisions, 13 Oct 2026:** the model picker stays admin-only for now (clients choose
no model, D-750 stands); the own-model cost floor is to use our real prompt sizes, not the
900-token reference prompt.

### 11.8 For the next email (documented 13 Oct 2026; the founder will send it later)

1. **Setting one agent's model when only the LLM is ours.** `PUT /agents/{id}/byok-model`
   is described two ways in the 13 Oct snapshot. The page text says it is refused with `409`
   "when the workspace is not using its own keys, or when this agent is set to
   `byok: "off"`" (`api-reference/agents/set-agent-byok-model.md:7`). The response table
   says `409` means the workspace "is not using its own voice key (it brings no keys, or only
   its language model)" (same file, :471-480). Read literally, the second means a Clear agent
   (scope `llm`, no voice key) cannot be given its own model and always runs the key's model.
   Which is right? D-764 currently treats the `409` as "not using its own model key" and
   sends the model on every Clear and Studio publish; if the second reading holds, Clear
   agents run the model stored on the key (`thinnest_own_model_default`) and the per-agent
   choice applies to Studio only.
2. **The "Standard" voice plan** in the console (§11.7): what it is, which voices, and the
   per-minute price.
3. Still open from §11.5: tokens per call on our own Google key beyond `usage` on Get Call
   and `call.analysed` (is `cachedInputTokens` billed by Google at the cached rate through
   their call?), and whether `maxReplyTokens` applies on calls.
4. The text of the speaking rules `callInstructions` replaces (§11.5 item 5).

## 12. Ashutosh's answer to the founder's follow-up, received 14 Oct 2026 10:07

Relayed by the founder. **VENDOR-STATED** unless a snapshot line is cited (paths under
`thinnest-findings/mirror/snapshots/2026-10-13/pages/`).

1. **"My voice and my language model, our speech-to-text" is built** at ₹1/min flat, the
   11 Oct offer; chat replies ₹0.02 each, as on the other own-key choices. Studio is this
   choice (`llm_voice`), Clear stays "Only my language model" (`llm`). A workspace needs **both
   an LLM key and a voice key** for Studio. Matches `api-reference/bring-your-own-keys.md:18-20,
   :25-28`.
2. **Per-agent choice.** Each agent follows the workspace default, is `off`, or names a scope
   the workspace holds keys for, so one client can have Clear and Studio agents in one
   workspace (the agent's "How Agent uses your keys" setting; API field `byok`). The snapshot
   already documents it (`api-reference/calls/get-call.md:191-199`: `null` follows the
   workspace, `"off"`, or `all | voice | llm | llm_voice`; a scope without verified keys is
   refused `409`). **If a key is later removed, the call still goes ahead on the workspace
   default and is billed for what actually ran.** **Live date: "with our next release"; he
   will confirm.** Until then a per-agent `llm`/`llm_voice` may not take effect.
3. **Tokens per call: added.** Get Call and `call.analysed` carry
   `usage {inputTokens, outputTokens, cachedInputTokens}`. Where a provider reports no usage,
   the input side is an estimate from the prompt's length (`api-reference/calls/get-call.md:
   1102-1135`: "treat it as a close guide rather than an invoice"; the post-call summary and
   field extraction are not counted).
4. **`byok.failed` is a console notification, not a webhook.** Subscribe to `call.problem`,
   which fires once per call, while the call is still going, with `kind: "byok_failed"` and
   payload `{callId, agentId, kind, detail, at}`; `detail` is a plain sentence describing the
   failure.
5. **`maxReplyTokens` applies to every call reply, own key included.** Default 300, settable
   100-800 per agent (Playground → Reply length; `api-reference/agents/update-agent.md:839-845`,
   "one ceiling for chat and calls"). A reply that reaches it is **cut off at that point**.

### 12.1 What it means for Calevate

| Item | State before this reply | What is missing on our side | Built (D-769, 14 Oct 2026) |
|---|---|---|---|
| 1. `llm_voice` | Built, D-764, switched off | Confirm a Studio publish on our model installs both the Cartesia key and the Google key in the client's workspace before naming `llm_voice` | Already in order (`ensure_studio_in`, then `ensure_own_model_in`, then the write); the last read must now also show the voice key ready, else `studio_account_not_ready` with nothing written. Tested |
| 2. Per-agent scope | Built: every agent names its scope and the publish reads it back | Not live at the vendor until their next release; the read-back already refuses a publish the vendor ignored. A call that falls back to the workspace default is billed differently from the route's rate key: our cost must come from what the vendor charged for the call, not from the scope we asked for | Read-back refusal confirmed and tested (`workspace` or `voice` back after `llm_voice`; `voice` was unread before). `engine_call_cost_variance` already compares each call's charge with its metered minute; on `byok_llm_voice` it now names a possible fallback. Alarmed, not restated: no documented field says which scope a call ran on. T-29 and the runbook: `thinnest_own_model` stays off until ThinnestAI confirms |
| 3. Usage tokens | Metered (D-764) | Mark a call's token cost as estimated when the vendor estimated it (it does not say so per call: question below) | Waits on §12.2 question 2 |
| 4. `byok_failed` | Alarm `engine_call_own_key_failed` (D-767) | Carry `detail` (the vendor's sentence) to the operator alarm, never to a client | `EngineProblem.operator_detail` (byok only; one line, 240 characters, digit runs of six or more masked) ends the alarm's text |
| 5. `maxReplyTokens` | **Not sent**: every agent runs the vendor default 300 | State it on every agent write, verify it on read-back and in the drift sweep, admin-settable 100-800 per agent | Sent on every write from `agents.max_reply_tokens` (migration `b9d4e2a7c6f1`) else console `thinnest_reply_length` (300); read back at publish and by the sweep (`reply_length`); admin "Reply length" under Call handling |

### 12.2 For the next email (unsent; the founder sends)

1. When a call falls back to the workspace default because a key was removed, does Get Call or
   `call.analysed` say which scope ran and what the minute was billed at?
2. Does `usage` say when the input count is an estimate?
3. With our own LLM key, do the post-call summary and field extraction run on our key (so our
   Google account pays tokens `usage` does not count) or on yours?
4. Still open from §11.8: the `byok-model` `409` wording; the Standard voice plan; the speaking
   rules `callInstructions` replaces. And the live date of per-agent scopes.

## 13. Draft of the next email (14 Oct 2026, unsent; the founder sends)

Gathers everything still unanswered from §5 (9 and 11 Oct emails), §9 (12 Oct build), §11.2
and §11.8 (13 Oct), and §12.2 (14 Oct). Items answered since are left out. Questions 12 and 13
are gaps A3 and A10 of `docs/evidence/prompting-practices-2026-10.md`. Its gap A9 (whether they
speak a filler while a tool runs) is answered by their docs: `thinking`, default true, says a
short filler when a reply has not started after `thinkingDelayMs`, "for example while an action
runs" (`api-reference/agents/create-agent.md:1364-1368`, snapshot 2026-10-13).

> **Subject:** Calevate: follow-ups after the per-agent keys release
>
> Hi Ashutosh,
>
> Thanks for building the fourth choice and per-agent keys so quickly; that is exactly the
> Clear and Studio split we need. A consolidated list of what is still open on our side:
>
> **Per-agent keys and billing**
> 1. When will per-agent `byok` go live? We will hold our Gemini set-ups until you confirm,
>    and then place one test call on each.
> 2. With our own LLM key, do the post-call summary and field extraction run on our key (so
>    Google bills us for tokens `usage` does not count) or on yours?
> 3. `PUT /agents/{id}/byok-model`: the page text says it is refused with `409` when the
>    workspace is not using its own keys, but the response table says `409` means "not using
>    its own voice key (it brings no keys, or only its language model)". Can a Clear agent
>    (scope `llm`, no voice key) have its own model, or does it always run the model stored
>    with the key?
> 4. What is the Standard voice plan (which voices, and the per-minute price), next to Premium
>    and Studio?
> 5. Is there a volume rate on the Studio voice band? Clear runs on it, and at ₹3.00 a minute it
>    is most of our cost.
>
> **Agent behaviour**
> 6. The text of the 16 speaking rules that `callInstructions` replaces, so our prompt keeps
>    the ones we still want.
> 7. Is `voice.surfaces: []` accepted on an agent with no number? We send it so a new agent does
>     not answer on the website button or WhatsApp.
>
> **Numbers**
> 8. Does `POST /phone-numbers` (rent) honour `Idempotency-Key`? The errors page says keys are
>     kept 24 hours, but the rent page does not list the header; we send it.
>
> **Compliance**
> 9. The signed DPA and the list of your sub-processors that handle a call on your stack.
> 10. Please exclude our developer workspace, and every customer workspace under it, from model
>     training (your "Your data: erasure and training" page says the owner asks support; this is
>     that request), and confirm in writing once it is done.
> 11. Any update from Plivo on the TRAI regulation 4 notice.
>
> **How the model sees our instructions**
> 12. When the caller goes quiet, does the model see anything (an empty turn, an event, the
>     time since they spoke), or do `nudgeAfterSeconds` and `endAfterSilenceSeconds` handle it
>     entirely outside the model? We will only write a silence rule into our instructions if the
>     model actually sees the silence.
> 13. Where do our `instructions` sit in what the model receives, relative to your own rules,
>     the steps, the per-call variables and the caller memory? Is the part that is the same on
>     every call sent first, so it can be cached, and what does `cachedInputTokens` count?
>
> **Placing calls** (added 15 Oct 2026, after our free-trial test calls were refused)
> 14. What exactly makes an agent one that "answers the phone" for Place Call (`409
>     calling_not_set_up`, `404 agent_not_found`)? Is it `answersCalls: true` with `phone` in
>     `voice.surfaces`? Our trial agents have no number of their own: one shared number's line
>     is an agent with Answer calls off, and each test call lends the number to the trial
>     agent as `callingAgent`. After we sent `surfaces: []` to agents without a number, every
>     test call got `calling_not_set_up`. We now set `surfaces: ["phone"]` on the agent right
>     after lending it the number. Is that the intended way, and does a lent number count as a
>     number "to call from" for `phone_number_required`?
> 15. Does lending a number (`callingAgent`) add `phone` to the borrowing agent's surfaces by
>     itself, and does it stay when the number is lent to another agent? Can an agent with
>     `phone` but no number of its own ever answer an inbound call?
>
> Thanks,
> Umesh

### 13.1 Things to ask them to build (for the same email; founder adds)

Each request rests on a documented limitation (snapshot paths under
`thinnest-findings/mirror/snapshots/2026-10-13/pages/`) and a requirement in our code or docs.

> **Things that would help us, if you can build them** (if any already exists, please point us
> to it)
>
> A. **What each call was billed as.** Get Call already gives `costMicro`. Alongside it, please
>    add which key choice the call ran on (`off`, `voice`, `llm`, `llm_voice` or `all`), the voice
>    plan (Standard, Premium or Studio), the per-minute rate and the billed seconds. We sell two
>    tiers at different prices and reconcile every call; with per-agent choices and the fallback
>    when a key is removed, the total alone cannot tell us which tier a call really ran on.
>
> B. **Characters synthesised on our voice key, per call.** Cartesia bills us per character, and
>    sentences sent before an interruption are synthesised even when the caller never hears them.
>    A per-call count of characters sent to our voice account (on Get Call or `call.analysed`),
>    and ideally stopping synthesis at the interruption, would let us cost Studio exactly. Today we
>    can only count the characters in the transcript.
>
> C. **Mark estimated token counts.** A flag such as `usage.inputTokensEstimated: true` when the
>    input side is your estimate, so we know which calls to treat as approximate.
>
> D. **Share our clones with our customer workspaces.** Our admin clones voices in the developer
>    workspace; a client's agent runs in that client's own workspace, so today we re-create the
>    clone in every client workspace from the stored recording, and each copy counts against that
>    workspace's clone limit. Letting a developer's clone be used by its customer workspaces would
>    remove the copies and the limit problem.
>
> E. **Shorter retention, or deleting one call.** Recordings are kept 30 / 49 / 75 days by plan,
>    and no endpoint deletes a single call or recording (`DELETE /calls/{id}` only cancels). We keep
>    our own copy, and our clients set their own retention, sometimes shorter than yours. A
>    per-workspace retention setting on the API, or `DELETE` for one call's recording and
>    transcript, would let their setting apply on your side too.
>
> F. **Tell us when an erasure finishes.** `DELETE /contacts/{id}` can answer `recordingsPending`
>    and the rest is retried nightly with no completion signal, so a person has to close our
>    erasure record by hand. A webhook (for example `contact.erased`) or a status on the contact
>    when the last recording is gone would close it automatically.
>
> G. **A webhook when a workspace's own keys change.** If a key fails verification, is removed or
>    own keys are switched off, a webhook would let us react immediately; today we see a key
>    failure only per call (`call.problem`) and check each workspace on a schedule.
>
> H. **Mark which voices our own Cartesia account owns** in `GET /byok/voices` (today only the
>    order implies it).

Evidence: A — `api-reference/calls/get-call.md:594-605` (`costMicro`), §12 item 2 (fallback);
B — §11.2 row 6; C — `api-reference/calls/get-call.md:1102-1112`; D — `docs/THINNEST-INTEGRATION.md`
"Clones" (`agents/clone_copies.py`, gate T-18); E — `workspace/usage.md:88-96`,
`api-reference/calls/cancel-call.md:7`; F — `workspace/data-and-erasure.md:14-56`,
THINNEST-INTEGRATION "Erasure" (D-691); G — §12 item 4, the hourly sweeps (D-727, D-764); H — §9
item 1 (moved here from question 9 of the draft).

## 14. Ashutosh's answer to the §13.1 requests, received 15 Oct 2026

- **From:** Ashutosh K, founder of ThinnestAI.
- **Relayed by:** the founder.
- **Evidence class:** **VENDOR-STATED**.
- **Status:** all eight requests of §13.1 (A–H) are "built and live".
- **What the answers below are.** A summary, item by item; the email's own text, as the founder pasted it, is the record and follows the summary as §14.0.
- **Where the docs check is.** `docs/evidence/thinnest-reply-2026-10-15.md` checks each answer against the docs snapshot `thinnest-findings/mirror/snapshots/2026-10-15/`. **All eight are documented there** (VERIFIED-VENDOR-DOCS). The differences are noted beside each answer.

A. **What each call was billed as.**
   - Get Call and `call.analysed` carry `billing` with five fields:
     - `keys` (`off | all | voice | llm | llm_voice`): what the call actually ran on, after any fallback;
     - `voicePlan` (Standard | Premium | Studio): null for flat own-key prices and for older calls;
     - `ratePerMinuteMicro`;
     - `billedSeconds`: empty until settled;
     - `currency`.
   - For a forwarded call with no agent, trust `costMicro`.
   - *Docs:* `voicePlan` is lower case (`standard | premium | studio | null`), and it is also null for a free trial call. List Calls does not carry `billing`. The forwarded-call rule is not in the docs.
B. **`usage.ttsCharacters`.** All text sent to the voice, including cut-off sentences. It matches what our Cartesia account bills.
   - *Docs:* the field is documented. The match with a Cartesia invoice is only "what a voice provider charges for".
C. **`usage.inputTokensEstimated`.** True when the input tokens are their estimate.
   - *Docs:* nullable, and null for calls before 15 Oct.
D. **Shared clones.**
   - Developer-workspace clones are usable by customer workspaces' agents automatically.
   - No copies are made, and the clones count only against our limit.
   - Customers can pick a clone but cannot edit or delete it.
   - Deleting a clone moves its agents to a standard voice.
   - *Docs:* `sharedFromDeveloper: true` in a customer's `GET /voices`. Whether the id equals the developer workspace's `voiceId` is not stated. **Answered 18 Oct 2026 (Ashutosh, item 1): the same id.**
E. **Deleting one call's content, and shorter retention.**
   - `DELETE /api/v1/calls/{id}/content` deletes one call's recording, transcript, summary and collected fields. The billing record stays.
   - `callRetentionDays` on the workspace (Update Workspace) sets a shorter retention, never longer than the plan's.
   - *Docs:* `callRetentionDays` runs from 1 day to `planRetentionDays` (30 / 49 / 75 / 365). `null` keeps transcripts with no end.
F. **`contact.erased`.** A webhook sent once, when the last recording is gone.
G. **`byok.changed`.** A webhook sent when a key is added, replaced, removed or fails verification, or when BYOK or its default choice changes. It carries no key material.
   - *Docs:* "fails verification" is `key_failed_verification`, which is a refusal when a key is saved. Saved keys are not re-checked on a schedule, and a key that stops working on a call is still only `call.problem` `byok_failed`. A key's model change is not sent.
H. **`own` on `GET /byok/voices`.** `GET /byok/voices` marks our own account's voices `own: true`.

### 14.0 The email, verbatim (Ashutosh K, 15 Oct 2026, 2:49 PM)

> All eight are built and are live now.:
>
> A. What each call was billed as. Get Call and call.analysed now carry billing:
>
> keys: the choice the call ran on: off, all, voice, llm or llm_voice.
>
> voicePlan: Standard, Premium or Studio, the plan actually priced. It is null for the flat own-key prices and for calls made before this release.
>
> ratePerMinuteMicro, billedSeconds and currency.
>
> If a key was missing and the call fell back, keys shows what it actually ran on. billedSeconds is empty until the call is settled. On forwarded calls with no agent, the rate and plan shown are the agent's, although only the carrier charge was billed. Treat those calls by costMicro.
>
> B. Characters on your voice key. usage.ttsCharacters counts all text we sent to the voice. That includes sentences cut off by an interruption that the caller never heard, so it matches what your Cartesia account bills. We can't stop synthesis already sent to your voice provider.
>
> C. Estimated tokens. usage.inputTokensEstimated is true when the input side is our estimate.
>
> D. Clones shared with your customers. Your clones in the developer workspace are now usable by your customer workspaces' agents automatically. No copies are needed, and they count only against your limit. Customers can pick them but not edit or delete them. If you delete a clone, the agents using it move to a standard voice.
>
> E. Deleting one call, and shorter retention.
>
> DELETE /api/v1/calls/{id}/content deletes one call's recording, transcript, summary and collected fields. The billing record stays. DELETE /calls/{id} still only cancels.
>
> callRetentionDays on the workspace (Update Workspace) sets a shorter retention for recordings and transcripts, never longer than the plan's. If you don't set it, transcripts stay as today.
>
> A delete doesn't reach data already copied into a contact, webhooks already sent, or the metadata you attached.
>
> F. Erasure finished. A contact.erased webhook is sent once, when the last recording is gone.
>
> G. Your keys changed. A byok.changed webhook fires when a key is added, replaced, removed or fails verification, or BYOK or its default choice changes. It never includes key material.
>
> H. Your own voices. GET /byok/voices marks your own account's voices own: true.

### 14.1 What it closes and what stays open

**Closed:**

- **§13.1 A–H** (the requests): all eight, per the docs.
- **§12.2 question 1**, which scope ran after a fallback and what the minute was billed at: `billing.keys` and `ratePerMinuteMicro`. The fallback happens when the call starts, and `keys` is the stack as set up then (`api-reference/calls/get-call.md:200-203`, `:1240-1252`).
- **§12.2 question 2**, whether `usage` says when the input count is an estimate: `usage.inputTokensEstimated`.
- **§11.8 item 3, in part:** what `usage` counts on our own key is documented again. Whether Google bills `cachedInputTokens` at the cached rate through their call is **still open**.

**Partly answered:**

- **§13 question 4** (the Standard voice plan). `standard` is now a documented `voicePlan` value and a List Voices tier. Its per-minute price is **not** stated.

**Still open:**

- **§11.8 item 1 = §13 question 3:** the `byok-model` `409` wording. `set-agent-byok-model.md` changed only in its preamble.
- **§11.8 item 2:** the Standard price.
- **§11.8 item 4 = §13 question 6:** the `callInstructions` rules.
- **§13 question 1:** the per-agent `byok` live date. This reply does not mention it.
- **§13 question 2 = §12.2 question 3:** whether the post-call summary and extraction run on our own LLM key.
- **§13 questions 5 and 7–13.**
- **§13 questions 14 and 15:** Place Call `calling_not_set_up` and `callingAgent` surfaces. `place-call.md` changed only in its preamble.

**New, for the next email:**

1. Is a developer clone's id in a customer workspace's `GET /voices` the same as its `voiceId` in the developer workspace? (One read of each listing answers this without asking.)
2. What does `billing` hold on a forwarded call with no agent: `null`, or `voicePlan: standard`?
3. Does "a free trial call" (`voicePlan`, `ratePerMinuteMicro` and `billedSeconds` all null) include test calls that our own free-trial agents place in our developer workspace, or only ThinnestAI's own free plan?
4. `voice.reaskAfterSeconds` is in the Voice guide (`channels/voice.md:659`) but in no API schema. Does Update Agent accept it? Is there an API field for the console's "up to four" reply languages?

## 15. Draft of the next email (16 Oct 2026, unsent; the founder sends)

Gathers what §14.1 left open, the four new questions it lists, and what building A–H on our
side (D-796, D-797, D-798) raised. §13 questions 1-15 are repeated only where §14.1 marks them
open, because the 15 Oct reply answered only the §13.1 requests.

> **Subject:** Calevate: thank you for A–H, and what is still open
>
> Hi Ashutosh,
>
> Thank you for shipping all eight so quickly. We have built every one of them into Calevate:
> each call is now reconciled on `billing`, Studio is costed on `ttsCharacters`, client agents
> use our shared clones, a client's retention is set on its workspace, call content is deleted
> per call, and `contact.erased` and `byok.changed` are wired in (question 22 is why one
> endpoint cannot receive them yet). What is still open:
>
> **From the new release**
> 1. Shared clones: is a developer clone's id in a customer workspace's `GET /voices` the same
>    as its `voiceId` in our developer workspace? We publish client agents with that id and
>    refuse if it is not listed, so a different id would stop every client publish on our clones.
> 2. What does `billing` hold on a forwarded call with no agent: `null`, or the agent's plan and
>    rate as your email says? We would like the docs to state it.
> 3. Does "a free trial call" (plan, rate and billed seconds all null) include the test calls our
>    own free-trial agents place in our developer workspace, or only calls on your free plan?
> 4. A call that ends before the agent speaks (`hangup: before_agent`) is charged the carrier's
>    fee and its seconds are rounded to the carrier's block. How long is that block, and what is
>    the fee, so we can reconcile those calls instead of flagging them?
> 5. Could List Calls carry `billing` too, or could you send a webhook when a call is settled?
>    A call settled after `call.analysed` has no billing in what we receive, so today we read
>    Get Call for each one.
> 6. `voice.reaskAfterSeconds` is in the Voice guide but in no API schema. Does Update Agent
>    accept it? Is there an API field for the console's "up to four" reply languages?
>
> **Per-agent keys and billing** (still open from our last email)
> 7. Please confirm per-agent `byok` (all four choices) is live for every workspace, so we can
>    place one test call on each set-up.
> 8. With our own LLM key, do the post-call summary and field extraction run on our key (Google
>    bills us for tokens `usage` does not count) or on yours? And does Google bill
>    `cachedInputTokens` at its cached rate through your call?
> 9. `PUT /agents/{id}/byok-model`: the page says `409` when the workspace is not using its own
>    keys, but the response table says `409` means "not using its own voice key". Can a Clear
>    agent (scope `llm`, no voice key) have its own model?
> 10. The per-minute price of the Standard voice plan, and is there a volume rate on the Studio
>     band? Clear runs on Studio at ₹3.00 a minute, which is most of our cost.
>
> **Agent behaviour**
> 11. The text of the 16 speaking rules that `callInstructions` replaces, so our prompt keeps the
>     ones we still want.
> 12. Is `voice.surfaces: []` accepted on an agent with no number?
> 13. When the caller goes quiet, does the model see anything (an empty turn, an event, the time
>     since they spoke), or do `nudgeAfterSeconds` and `endAfterSilenceSeconds` handle it outside
>     the model?
> 14. Where do our `instructions` sit in what the model receives, relative to your rules, the
>     steps, the per-call variables and the caller memory? Is the part that is the same on every
>     call sent first, so it can be cached?
>
> **Placing calls**
> 15. What exactly makes an agent one that "answers the phone" for Place Call (`409
>     calling_not_set_up`)? Our trial agents have no number of their own: one shared number's
>     line is an agent with Answer calls off, and each test call lends the number to the trial
>     agent as `callingAgent`. We now set `surfaces: ["phone"]` on the borrowing agent right after
>     the lend. Is that the intended way, and does a lent number count as a number "to call from"
>     for `phone_number_required`?
> 16. Does lending a number add `phone` to the borrowing agent by itself, and does it stay when the
>     number is lent to another agent? Can an agent with `phone` but no number of its own ever
>     answer an inbound call?
>
> **Numbers**
> 17. Does `POST /phone-numbers` (rent) honour `Idempotency-Key`? We send it.
> 18. Can a client workspace use a 140-series number (a TRAI voice header registered on DLT for
>     the client as Principal Entity) as `from` on Place Call: rented through you, or brought
>     in? We are deciding whether to support promotional calling and need to know if the header
>     can be presented on your stack.
>
> **Compliance**
> 19. The signed DPA and the list of your sub-processors that handle a call on your stack.
> 20. Please exclude our developer workspace and every customer workspace under it from model
>     training, and confirm in writing once done.
> 21. Any update from Plivo on the TRAI regulation 4 (autodialer) notice, and which access
>     provider holds the numbers you rent to us.
>
> **Webhooks** (failing since we added the two new events)
> 22. Every sweep since 16 Oct, `PATCH /webhooks/{id}` adding `contact.erased` and
>     `byok.changed` to an existing endpoint answers `500 internal_error` "Could not save the
>     endpoint.", and `POST /webhooks` for the same agent with all eight events answers `500
>     internal_error` "Could not add the endpoint." (17 Oct, 21:21 IST; developer workspace,
>     endpoint `wh_47764a52-314c-4ada-ab87-ffb8693cfb7f`, on, no failures). Your docs list both
>     events for agent endpoints. Could you look at why the save fails? Until then that endpoint
>     keeps its six older events.
>
> **Recordings**
> 23. When a whole line is forwarded to a person's phone (no agent on the call), is that call
>     recorded, and is the audio available from `GET /calls/{id}/recording`? The voice guide
>     says phone calls are recorded on every number, and the phone-number page does not say
>     either way for a forwarded line. We keep our own copy of every recording and alarm when
>     one is missing, so we need to know whether to expect one.
>
> Thanks,
> Umesh
