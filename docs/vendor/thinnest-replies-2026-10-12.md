# ThinnestAI replies, 11-12 Oct 2026

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

## 5. Still unanswered

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
3. Is `voice.surfaces: []` accepted on an agent with no number? We send it so a new agent does not
   answer on the website button or WhatsApp; if it is refused we save the agent without it and
   alarm (`engine_agent_surfaces_refused`).

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
