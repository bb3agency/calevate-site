# ThinnestAI as a voice engine: evaluation record (Oct 2026)

What we know about ThinnestAI (`thinnest.ai`), where each fact comes from, and what is still unknown. It is the evidence behind D-678 and `docs/THINNEST-INTEGRATION.md`.

**Evidence classes**, as used throughout this repository:
- **VERIFIED-VENDOR-DOCS**: the hash-pinned mirror `thinnest-findings/mirror/`.
- **VENDOR-PUBLISHED**: their website, read on 6 Oct 2026.
- **FOUNDER-RELAYED**: the founder's call with Ashutosh K (ThinnestAI's founder) on 6 Oct 2026, and his email the same day.
- **REPORTED**: a third-party summary.

## 1. Why we are looking

Calevate built its own real-time call layer: a Pipecat worker on Pipecat Cloud `ap-south`, with Vobiz as the carrier (D-592, D-662). No real call has been placed yet.

Running that layer ourselves means owning all of the following before the first client:
- latency;
- turn-taking on Indian PSTN;
- carrier wiring and its open gates (55, V-3, V-10);
- outages and scaling.

ThinnestAI is a managed orchestrator that offered BYOK (our own STT, LLM and TTS keys). The founder's choice (6 Oct 2026) is to add ThinnestAI as a second engine behind a **deployment-wide `ENGINE` switch**:
- **Pipecat stays as it is.**
- **Phone numbers are ThinnestAI's own.**
- **Voices and models come from their catalogue for now, with a slot ready for BYOK.**

## 2. Commercial terms

| Term | Value | Class |
|---|---|---|
| BYOK platform fee | **₹1/min, telephony included** | FOUNDER-RELAYED (email, 6 Oct 2026) |
| Billing pulse | 30 seconds | FOUNDER-RELAYED (call) |
| Their own models: standard / expressive | ₹1.5 / ₹2.5 per min | FOUNDER-RELAYED (call) |
| Website: standard / premium / Studio | ₹2 / ₹2.5 / ₹3 per min; Scale ₹4,999/mo | VENDOR-PUBLISHED. **Conflicts with the call; unresolved.** |
| Concurrency | 5 on pay-as-you-go; "reviewed based on volume" (email); "nothing extra" (call) | FOUNDER-RELAYED |
| Limits generally | Raised on request by email (founder's reading of the call) | FOUNDER-RELAYED |
| Calls per second | About 3, set by the carrier (Plivo) | FOUNDER-RELAYED |
| Reselling as an aggregator | Permitted; white-label programme | FOUNDER-RELAYED; white label is VERIFIED-VENDOR-DOCS (`white-label/overview.md`) |

None of these is an invoice. Hard rule 7 admits only an operator-attested figure into `unit_cost_paid`.

### 2a. The logged-in console (FOUNDER-RELAYED via a browser agent, 6 Oct 2026, Free-trial account)

**BYOK is real and workspace-wide.** This console reading said it was not in the API; the 7 Oct 2026 snapshot documents a full BYOK API (§8), so that half is superseded.
- **Where:** Settings → Your keys (`/settings/byok`). Quoted: *"With all three, calls are billed ₹1 a minute all-in (our telephony included) and chat replies ₹0.02."*
- **Switching it on:** all three legs (STT, LLM, voice) must each have a key and a model.
- **STT providers:** Deepgram, AssemblyAI, Soniox, Speechmatics, Gladia, **Sarvam**, ElevenLabs, **Cartesia**, OpenAI, Groq, Mistral, Azure Speech.
- **LLM providers:** **Sarvam**, **OpenAI**, Groq, Mistral, Anthropic, **Google Gemini**, DeepSeek, xAI, Together, Fireworks, Cerebras, OpenRouter, and **"Other (OpenAI-compatible URL)"**. Azure OpenAI is reachable only through that OpenAI-compatible option.
- **Voice providers:** Deepgram, Soniox, **Sarvam**, ElevenLabs, **Cartesia**, OpenAI, Mistral, Azure Speech, Rime, Inworld, Hume, Murf, Speechify.
- **Gnani is not offered.**

**Catalogue voice prices (in-app):**
- **Pay-as-you-go:** Standard ₹2.00/min, Premium ₹2.50, Studio ₹3.00.
- **Scale:** ₹1.90 / ₹2.375 / ₹2.85.
- **Plan gate:** Studio needs Pro or Scale.

This **supersedes the ₹1.5 standard figure from the call.**

**Telugu:**
- **Language:** an exact `Telugu` option exists. The console's "Match the customer" option is the API's `auto`.
- **Telugu Standard voices:** Abirami Te, Anjura Te, Divya, Karthik, Tanvi.
- **Premium voices:** not labelled by language.

**Plans and numbers:**

| Plan | Price | Concurrency | Recording retention (in-app) |
|---|---|---|---|
| Pay-as-you-go | — | 5 | 30 days |
| Pro | ₹2,499/mo | 10 | 49 days |
| Scale | ₹4,999/mo | 15, more on request | 75 days |

- **Number rental:** ₹349/mo on pay-as-you-go, ₹249/mo on Pro and Scale. The website says ₹250/mo.
- **Wallet top-up fee:** 10% on pay-as-you-go and 8% on Scale, per the website only. **This adds to every rupee spent.**
- **Billing pulse:** not stated. The Usage page says minutes are "Rounded up each day".
- **Recording retention on the website:** 89 days on every plan, which conflicts with the in-app figures above.

**Console vs API:**
- **Webhooks UI:** the console's "Send leads somewhere" covers leads and escalations only. Call events are API-only (`api-reference/webhooks.md`).
- **"Call your own API" form:** has a "what to say while it runs" field and no timeout setting.
- **Not found anywhere in the console:** a data-retention setting, a data processing agreement, or a statement on training.

### 2b. Per-minute cost, revised with 2a

| Path | ₹/min (Calevate legs from TRD §10.1) |
|---|---|
| Their catalogue: Standard (5 Telugu voices) / Premium / Studio | **2.00 / 2.50 / 3.00** |
| BYOK: Sarvam STT 0.50 + Gemini Flash-Lite 0.11 + Cartesia 2.06–3.09 + ₹1 | **3.67–4.70** |
| BYOK with a cheaper voice: Sarvam STT + Gemini + Sarvam voice (Bulbul v3, TRD's record ₹1.08–1.62; **re-verify, since our TTS leg left Sarvam under D-629**) + ₹1 | about 2.69–3.23 |

**Their Standard catalogue minute is the cheapest path** unless the founder's listening test finds their Telugu voices inadequate. The 10% top-up fee applies on top of every path.

## 3. What the documentation establishes (VERIFIED-VENDOR-DOCS)

All paths are under `thinnest-findings/mirror/pages/`.

| Area | Fact | Source |
|---|---|---|
| Agents | CRUD over `/api/v1/agents`. The `instructions` field holds **up to 8,000 characters** (20,000 in the 7 Oct snapshot, `agents/update-agent.md:426-431`) and is returned on read. Other fields: `greeting` up to 200 characters, `model`, `language`, `secondLanguage`, `voice.{voice, recordCalls, maxCallSeconds (60–1200), detectMachines, summariseCalls, pastConversations}`, and `collectFields` (up to 30) | `api-reference/agents.md:86-185` |
| Providers hidden | "What you will not see: which engine speaks a voice, which service runs a model, or which carrier holds a number" | `api-reference/agents.md:205-209` |
| Catalogue | `GET /voices` returns tiers `standard`, `premium` and `studio` (Studio needs Scale). `GET /models` returns e.g. `prana-voice` and `gpt-5-mini`. **No BYOK field anywhere** (6 Oct pages; superseded by the BYOK API in the 7 Oct snapshot, §8). | `api-reference/voices-and-models.md` |
| Numbers | `GET /phone-numbers` lists numbers, each `rented` or `brought`. **Renting and attaching numbers are done in the console.** | `api-reference/voices-and-models.md:67-87` |
| Outbound call | `POST /calls` takes `to` and `purpose` (**spoken first**, up to 300 characters), plus `agent`, `reference`, `variables`, `metadata`, `callingHours` (within 09:00–21:00), `retry`, `from`, `overrides` and `Idempotency-Key` (honoured 24 h). It refuses opt-outs and the do-not-call list (403). It returns 409 on a conflict, and 429 when concurrency, the per-minute rate or the **200 calls a day per chosen number** is exceeded. | `api-reference/place-call.md` |
| Call result | `GET /calls/{id}` returns status, `hangup` (answered, no_answer, busy, rejected, unreachable, cancelled, voicemail, before_agent, failed, not_placed), `seconds`, `summary`, `fields`, a `transcript` of `{speaker, text, at}`, and `recording.{url, expiresAt, ready}` (30 days on pay-as-you-go, 75 on Scale). **It has no cost field.** **Calls the API did not place return 404.** | `api-reference/get-call.md` |
| End or cancel | `DELETE /calls/{id}` | `api-reference/get-call.md:89-108` |
| Webhooks | Events: `call.completed`, `call.analysed`, `lead.captured`, `conversation.escalated`, `conversation.resolved` and `campaign.finished`. Each is signed with `x-thinnest-signature: sha256=` HMAC over the raw body, **with no timestamp**. **One attempt per event**: an endpoint that fails 5 times in a row is switched off, and `PATCH enabled:true` turns it back on. Delivery history keeps the last 50 deliveries, without payloads. | `api-reference/webhooks.md:36-123` |
| Knowledge | Per agent, at `/agents/{id}/knowledge`, by URL or text (up to 200k characters). Files can only be added in the console. | `api-reference/knowledge.md` |
| Custom API during a call | GET or POST to our endpoint with an `X-Agent-Secret` header, at most 30 calls per conversation per hour, timeout unstated | `agent/custom-api.md` |
| Voice behaviour | Barge-in after three words by default. "Are you still there?" up to 5 times. A 20-minute hard ceiling. Recording off by default. **No live transfer to a person.** | `channels/voice.md` |
| Auth | `Bearer ta_live_…` with full, build or read-only scope. Rate limit per organisation per minute. | `api-reference/authentication.md` |
| White label | 6 Oct pages: Scale plan, up to 99 client workspaces managed in the console, one shared pool of lines; the partner's zero balance stops every client. Changed in the 7 Oct snapshot (§9) | `white-label/*.md` |
| Promotional calls in India | Need a 140-series number, registered as principal entity and telemarketer | `channels/phone-numbers.md`, `channels/voice-campaigns.md` |

## 4. Privacy (VENDOR-PUBLISHED, `thinnest.ai/privacy`, 6 Oct 2026)

- **Storage:** GCP Mumbai (`asia-south1`).
- **LLM leg:** may process outside India (OpenAI, Anthropic, Gemini).
- **Sub-processors named:** Sarvam, OpenAI, Anthropic, Google, GCP, Razorpay and Meta.
- **Retention:** 180 days by default, configurable.
- **Rights:** erasure on request; breach notice within 72 hours.
- **Not stated:** a DPA, or whether our data is used for training.

## 5. Cost simulation (6 Oct 2026; Calevate's legs from TRD §10.1)

Per call-minute:

| Scenario | ₹/min |
|---|---|
| ThinnestAI's own stack: standard / expressive | 1.50 / 2.50 |
| BYOK with Gnani voice (₹1 + Sarvam 0.50 + Gemini Flash-Lite 0.11 + Gnani 0.97–1.46) | 2.58–3.07 |
| BYOK with Cartesia voice (₹1 + 0.50 + 0.11 + 2.06–3.09) | 3.67–4.70 |
| Today: Pipecat + Vobiz with Cartesia (0.44 + recording 0.10 + 0.50 + 0.11 + 2.06–3.09) | 3.21–4.24, plus Pipecat Cloud (price UNKNOWN) |

Notes:
- The 30-second pulse adds about 8% to the ThinnestAI part at a 3-minute average call.
- BYOK pays off only if ThinnestAI's own Telugu speech recognition and voices are not good enough. Test calls decide that.
- `billing/rates` cost floors carried Pipecat Cloud's ₹0.95 engine leg, not Bolna's ₹1.76 (corrected 7 Oct 2026). D-681 added the ThinnestAI Clear floor: ₹2.50 Premium × 1.10 top-up fee = ₹2.75/min (`rates.THINNEST_CLEAR_COST_FLOOR_INR_PER_MIN`).

## 6. Open questions (sent to ThinnestAI 6 Oct 2026; answers pending)

1. Which STT, LLM and TTS sit behind each tier.
2. Telugu quality on PSTN.
3. Knowledge-base grounding and our rules when the caller speaks another language.
4. **How BYOK is configured** (per account or per agent; supported providers).
5. The fee when we bring Vobiz numbers.
6. Whether pay-as-you-go suffices for API-only use, and whether client workspaces and keys can be managed via the API.
7. Cost per call in the call result or webhook.
8. Webhook re-enable, replay, and a signature timestamp.
9. The custom-API timeout.
10. A DPA, use of data for training, and sub-processors under BYOK.
11. Live transfer.
12. Confirmation that the limits can be raised.
13. A pay-as-you-go trial on one number.

## 7. Gaps that shape the integration

- **8,000-character instruction cap** (6 Oct reading; the 7 Oct snapshot raises it to 20,000, `snapshots/2026-10-07/pages/api-reference/agents/update-agent.md:426-431`).
  - `compose_engine_prompt` output must fit, including the truthful-answer floor and `CONFIDENTIALITY_RULE`.
  - A longer prompt must be refused at publish, never truncated, because truncation could cut a hard-rule-5 block.
- **No output guard.**
  - On this engine, D-674 holds through the prompt rule only. `PromptLeakGuard` runs in our own worker and cannot run inside ThinnestAI.
- **Opening line goes through `purpose`.**
  - For outbound calls the opening is `purpose` (per call); for inbound it is `greeting`. Both must carry our opening line verbatim (D-669).
- **No retry on webhooks.**
  - A reconciliation sweep over the call list is required, not optional.
  - The sweep re-enables a switched-off endpoint and raises an alarm.
- **No cost field.**
  - Metering is ₹/min times 30-second pulses at an operator-attested rate.
- **Inbound calls could not be fetched by id** (6 Oct pages). They arrive by webhook and through the call list (`api-reference/list-calls.md`). The 7 Oct snapshot takes any call id for the call, its transcript and its recording (`snapshots/2026-10-07/pages/api-reference/calls/get-call.md:7`, `calls/get-call-transcript.md:7`, `recordings/get-call-recording.md:7`).
- **Console-only numbers** (6 Oct pages; renting and pointing are API calls in the 7 Oct snapshot, but this engine still uses their console for numbers).
  - `provision_number` and `bind_inbound_number` refuse by name, with the operator's console steps.
- **No live transfer.**
  - `transfer` refuses by name.

## 8. What the 7 Oct 2026 snapshot changes (VERIFIED-VENDOR-DOCS)

The docs site was restructured on 7 Oct 2026. Paths in this section are under `thinnest-findings/mirror/snapshots/2026-10-07/pages/`; the 6 Oct pages stay as the record of what was documented then.

| Area | What is documented now | Source |
|---|---|---|
| Agent prompt | `instructions` accepts up to 20,000 characters (was 8,000). `greeting` stays at 200; a call's `purpose` should stay under 300. | `api-reference/agents/update-agent.md:426-431` |
| BYOK | A full API: status, add or replace a key, change its model, switch on or off (`GET/PATCH /byok`, `PUT /byok/credentials`, `PATCH /byok/credentials/{kind}`), plus per-agent BYOK model and voice. Still **all three keys or none**, with **no fallback** to their providers when a key fails. Gnani is not a voice provider; Azure OpenAI goes in as an OpenAI-compatible URL. | `api-reference/bring-your-own-keys.md:18-19,56,62-63,68,85-152`; `api-reference/agents/set-agent-byok-voice.md:155-157` |
| BYOK for customers | A customer workspace uses the developer's keys while BYOK is on, or a complete set of three of its own, which overrides them. Switching BYOK off for the developer switches it off for every customer. In this (morning) snapshot TTS-only BYOK was not documented. **Superseded by the evening snapshot (§10, §11): scope `voice` is documented** — `snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys.md:13-24,105-109`. | `api-reference/bring-your-own-keys.md:74-76` |
| Customers | Isolated workspaces per end customer, created by API and reached with one key plus a `Thinnest-Workspace` header (details in §9). | `api-reference/customers.md`, `guides/build-a-platform.md` |
| Phone numbers | Renting, importing, pointing at an agent and releasing are API calls now. An Indian number still needs business details approved in the console first. Bringing a number on our own carrier account (`plivo`, `vobiz`, `twilio`, `telnyx`) is documented and not used, by decision (7 Oct 2026, below). | `api-reference/phone-numbers/rent-phone-number.md:7`, `import-phone-number.md:7`, `update-phone-number.md:7`, `save-carrier-account.md:311,365-366` |
| Recordings | The MP3 lands about a minute after the call and is kept 30 days on Free and pay-as-you-go, 49 on Pro, 75 on Scale and 365 on Enterprise. Any call id from the call list works, so an inbound call's recording can be fetched. | `api-reference/recordings/get-call-recording.md:7` |
| Transcripts | `GET` a call's transcript by id, the same words `call.analysed` delivers. | `api-reference/calls/get-call-transcript.md:7` |
| Voices | Every voice speaks every supported language (the agent's language decides), each voice carries an accent tag, and Studio voices are listed on **Pro** and above (was Scale). | `api-reference/voices/list-voices.md:7,345` |
| Webhooks | A delivery is `{event, sentAt, data}`, so a signed send time is in the body. Still one attempt per event and switched off after five failures; the delivery list keeps the last 50 without payloads, and no redelivery is documented. | `api-reference/webhooks/create-webhook.md:162`; `api-reference/webhooks/list-webhook-deliveries.md:7` |
| Cost | The usage call log carries `costMicro`, what each call was actually charged. | `api-reference/usage/list-call-log.md:533-540` |

Founder decisions and what stays open:
- **Numbers (decided, 7 Oct 2026).** `ENGINE=thinnest` uses ThinnestAI's own numbers only (D-678 stands); Vobiz is isolated to `ENGINE=pipecat`. A move back to Pipecat would give clients new numbers; no portability between engines is planned or built.
- **Studio on ThinnestAI (on hold, D-681; unblocked by D-687).** On the morning snapshot BYOK was all three or none, so the founder's wish of BYOK for the voice only was not documented. The evening snapshot documents it (§10 item 1, §11), and D-687 builds Studio on it.

## 9. One workspace for every tenant, or a customer workspace per tenant

Calevate runs today with **one ThinnestAI workspace for every tenant**: one API key, every client's agents side by side, a webhook per agent, and the tenant found from our own route table. ThinnestAI now documents a second shape, built for exactly this product: a **customer workspace per tenant** (`api-reference/customers.md`, `guides/build-a-platform.md`). This is a founder decision. Nothing below is built.

| | One workspace (today) | Customer workspace per tenant |
|---|---|---|
| Isolation | Ours alone: the route table maps a vendor agent to a tenant. A bug on our side, or one leaked agent id, reaches another tenant's agent with the same key. | ThinnestAI's too: each request runs inside one customer (`Thinnest-Workspace`, `customers.md:70`); another customer's id answers 404. A key can be minted for one customer only (`customers.md:183`). |
| Per-tenant BYOK | Not possible: BYOK is workspace-wide. | Possible: a customer may hold its own complete set of three keys, overriding ours (`bring-your-own-keys.md:74-76`). Still all three legs; no voice-only BYOK. |
| Plan cap | None beyond the plan's lines. | Customers per plan: 3 on Free and pay-as-you-go, 100 on Pro, 1,000 on Scale, 10,000 on Enterprise (`customers.md:195-197`). **Pay-as-you-go caps us at 3 tenants.** A deleted customer counts until erased. |
| Concurrency | One pool for all tenants (5 on pay-as-you-go). | Still our pool; `allottedCallLines` caps one customer's share (`customers.md:132`). |
| Billing | One balance; cost per call from our attested rate (or `costMicro`). | Still one balance: customers have none of their own (`customers.md:188`). `spendThisMonthMicro` per customer gives a vendor-side per-tenant cost to reconcile against (`customers.md:119`). |
| Webhooks | One per agent, each with its own sealed secret. | One `includeCustomers` webhook for every customer, with `data.workspaceId` in the signed body (`guides/build-a-platform.md:62-65`). |
| Erasure | Per agent and per call, by our own deletion paths. | Deleting a customer erases every conversation, contact, recording and file 30 days later (`customers.md:153`); its numbers must be released first (`customers.md:143`). A clean, vendor-side end of a tenant. |
| White label | Compatible with their white-label console programme. | **Not compatible**: a workspace with API customers cannot resell their console under a brand (`customers.md:14-15`). We do not use their console for clients, so this costs us nothing today. |
| Migration | — | Every published agent, knowledge document, webhook and number would move into its tenant's customer; our route rows would carry a workspace id; the adapter would send the header on every call. |

Their white-label console programme (`white-label/*.md`) is a different product: branded console, domain, Razorpay and per-client plans, for an agency whose clients log in to ThinnestAI's console. Calevate's clients log in to Calevate, so the programme offers us nothing we use, and the snapshot is self-contradictory on whether it runs on pay-as-you-go (`white-label/overview.md:14` says every paid plan; `:104` lists "White label on pay-as-you-go" as not available yet). D-679's "used under their white-label programme" is therefore a description of the commercial relationship, not of any console feature we depend on.

Questions for ThinnestAI that decide the choice are in `docs/OPERATIONS.md` §2 (T-series).

## 10. ThinnestAI's answers, 7 Oct 2026, and what the docs confirm

**Source:** an email from Ashutosh K (founder, ThinnestAI) to the founder on 7 Oct 2026, answering the questions in §6 and the follow-up list. It was relayed verbatim. The docs were re-fetched the same evening as `thinnest-findings/mirror/snapshots/2026-10-07b/` (268 pages). Paths below are under that snapshot's `pages/`.

**Evidence classes:**
- **DOCS:** the snapshot says the same thing (VERIFIED-VENDOR-DOCS).
- **VENDOR-STATED:** the email only. This is a commercial or behavioural commitment, so confirm it in writing or on a test call before it reaches money or a client-facing claim.
- **CONTRADICTED:** the docs say otherwise. Nothing is built on it until a test call settles it.

| # | Topic | Their answer | Class |
|---|---|---|---|
| 1 | Our voice, their stack | BYOK `scope: voice`: our Cartesia key with their speech-to-text, LLM and telephony. ₹1.50/min including telephony, 30-second pulses. Settable per customer workspace. | DOCS: `api-reference/bring-your-own-keys/turn-byok-on-or-off.md:7` (scope `all`/`voice`), `get-byok-status.md:438-447`, the ₹1.50 rate at `:178` |
| 1a | Scope of BYOK | **Per workspace, not per agent.** A customer workspace can use their voices, inherit the developer's keys and scope, or have its own. Per agent only the BYOK voice is chosen (`agents/set-agent-byok-voice.md:7`). | DOCS (`turn-byok-on-or-off.md:7`: "a customer inherits your scope") |
| 2 | White label | Our clients never see ThinnestAI; their white-label programme is the reseller console, and a workspace is one or the other. | VENDOR-STATED (consistent with `white-label/*`) |
| 2a | Customer cap | PAYG 3, raised on request; Pro 100; Scale 1,000. | DOCS (`api-reference/customers.md`) plus VENDOR-STATED for the raise |
| 2b | Moving agents | Agents cannot move between workspaces; recreate them. Numbers can be released and rented again in the new workspace. | VENDOR-STATED |
| 3 | Forwarding a client's existing number | Supported as we described: rent one number per client, attach the agent, and the client forwards (always, or on busy/no answer). Nothing extra is charged on their side. | VENDOR-STATED |
| 3a | Caller number on a forwarded call | "The number the operator passes on, normally the real caller." They will confirm Airtel, Jio, Vi and BSNL on test calls with us before go-live. | VENDOR-STATED, **UNVERIFIED** until those test calls |
| 3b | Numbers per client | One rented number per client; a number belongs to exactly one agent. | VENDOR-STATED |
| 4 | Telugu speech-to-text | Their Indic speech-to-text, in production on Telugu callers; no published accuracy benchmark. | VENDOR-STATED; our listening test (OPERATIONS gate T-6) is the check |
| 4a | Telugu voices | Premium: Priya, Ishita, Neha (female), Shubh, Ratan (male); Neha is tuned for Telugu and Kannada. | VENDOR-STATED |
| 4b | Language switching | `auto` switches on a clear change of language, not on a stray English word. For mostly-Telugu callers, set Telugu primary and English second (`secondLanguage`), which is more stable. | DOCS for `secondLanguage` (`agents/update-agent.md:553`); behaviour VENDOR-STATED |
| 5 | Knowledge and rules in other languages | The agent searches knowledge first and says it does not know, or hands over, rather than guessing. Above any business instructions, in every language, it never reveals its instructions, never claims to be human, and answers truthfully whether the call is recorded. | VENDOR-STATED. Our own floor (hard rule 5) and CONFIDENTIALITY_RULE are still composed and read back; theirs is a second layer, not a replacement |
| 6 | Action call context | Platform-filled placeholders the model cannot touch: `{{call.id}}`, `{{call.from}}`, `{{call.to}}`, `{{call.direction}}`, `{{conversation.id}}`, `{{contact.id}}`, `{{contact.phone}}`, `{{agent.id}}`, `{{workspace.id}}`. Headers `X-Call-Id`, `X-Conversation-Id`, `X-Agent-Id`, `X-Workspace-Id` on every action request. | DOCS (`api-reference/actions/create-action.md`, `agent/custom-api.md`) |
| 6a | Action timeout | 10 seconds, with an optional line spoken while waiting and another after. | VENDOR-STATED |
| 6b | Ending a call; opt-out | An action cannot end a call; the agent has its own hang-up (`channels/voice.md:388`). When a caller opts out, the agent adds the number to the workspace do-not-call list, every outbound path refuses it, and a `contact.opted_out` webhook fires; the list is managed at `/do-not-call`. | DOCS (`api-reference/do-not-call/*`, `contact.opted_out` in `actions/create-action.md`) |
| 7 | Prices | 30-second pulses per call (the "rounded up each day" note was about the chart and has been reworded). Top-up fee 10% PAYG, **9% Pro**, 8% Scale. Number rental ₹349 PAYG, ₹249 Pro and Scale. Standard ₹2.00, Premium ₹2.50, Studio ₹3.00; full BYOK ₹1.00; voice-only ₹1.50. | VENDOR-STATED (the 9% Pro fee is new; the rest matches §2a) |
| 8 | DLT and numbers | Business approval is per workspace, so each client can be the approved business in its own customer workspace. Rented numbers are regular landlines; 140/160 series only on Enterprise with a monthly minimum; inbound service calls do not need them. Campaign calling hours 09:00–21:00, adjustable. | VENDOR-STATED |
| 9 | Call cost | `costMicro` and `currency` are now on `GET /calls/{id}` and in `call.analysed`, and final when `call.analysed` fires because the charge is settled first. | DOCS (`api-reference/calls/get-call.md:260,392,453`) |
| 10 | Webhooks | Retries at 1 min, 5 min, 30 min, 2 h and 6 h. Events kept 7 days, re-sendable via `POST /webhooks/{id}/redeliver`. An endpoint is switched off only after five events in a row fail all retries. `sentAt` stays the original event time on every retry. Check freshness on the signed `x-thinnest-delivered-at` header and dedupe on `x-thinnest-event-id`. | DOCS (`api-reference/webhooks/create-webhook.md:215`, `webhooks/redeliver-webhook-events.md:7,218`, `actions/create-action.md:203-222`) |
| 11 | DPA, training, residency | They will sign a DPA under the DPDP Act 2023 (ours or theirs). Recordings and transcripts are never used for training on Pro or Scale; on PAYG they may be, but will turn it off for our workspaces on request, from day one. Retention 30/49/75 days by plan, per-workspace retention can be added, and transcripts stay until deleted. Processed and stored in India (Mumbai). | VENDOR-STATED. **Ask in writing for training off on PAYG before any client call** (founder action) |
| 12 | Live transfer | "Yes": the agent says a chosen line, then connects to a phone number, and the caller stays with the agent if the transfer fails. | **CONTRADICTED**: `channels/voice.md:475` still says it "does not transfer the call". UNVERIFIED until the docs or a test call show it |
| 13 | Getting started | Start on PAYG, test Telugu on Premium voices, move to Pro or Scale at go-live. | VENDOR-STATED |

**What changes for Calevate because of this.** Each item is ours to build unless marked otherwise.
- **Webhook replay window (production defect).** Since retries exist and keep the original `sentAt`, our ±5 min `sentAt` window refuses every retry after the first attempt. Move freshness to the signed `x-thinnest-delivered-at` header and dedupe on `x-thinnest-event-id`.
- **In-call action identification.** Replace the `caller_number` match (D-682) with `{{call.id}}` and the `X-Call-Id` header, which the platform fills.
- **Call cost.** `costMicro` is final on `call.analysed`, which removes the reason D-682 gave for not recording the vendor's actual charge.
- **Do-not-call.** Mirror our DNC list into theirs, and consume `contact.opted_out`.
- **Webhook recovery.** Use the redeliver endpoint in the reconciliation sweep.
- **Studio is unblocked commercially:** voice-only BYOK at ₹1.50/min. Because BYOK scope is per workspace, a client's tier (Clear on Premium voices, or Studio on our Cartesia key) is chosen **per client workspace, not per agent**. That needs a customer workspace per tenant (§9), which is now the founder's architecture decision to make. **Resolved differently by D-687 (§11):** a rung is per WORKSPACE, not per tenant, so one shared Studio workspace serves every tenant's Studio agents and the per-tenant choice stays open.
- **Live transfer** stays refused until it is verified (item 12).

**Held back for later (founder, 7 Oct 2026): not in the 7 Oct follow-up email, to be asked before go-live.**
- **Keeping a number across customer workspaces.** In the two-workspaces-per-client scheme (one Clear, one Studio), moving an agent between tiers means recreating it in the other workspace. ThinnestAI says numbers can be released and rented again, not moved, so the client would likely get a different number. Ask: can the same number move with the agent to another customer workspace? Until it is answered, warn clients before a tier switch, and prefer forwarding from the client's own business number, so only the forward needs updating.
- **Forwarded-call test calls.** ThinnestAI offered (item 3a) to confirm what each operator passes as the caller's number on a forwarded call (Airtel, Jio, Vi, BSNL) on test calls with us. Schedule this before any client relies on forwarding; until then the caller number on forwarded calls is UNVERIFIED.

## 11. Voices on ThinnestAI: the D-687 decision (8 Oct 2026)

**The founder's decision**, built on the 7 Oct evening snapshot (paths under `thinnest-findings/mirror/snapshots/2026-10-07b/pages/`, VERIFIED-VENDOR-DOCS) and the email in §10. It supersedes D-681's "only Premium is sold, as Clear" and its "Studio on hold". The build is described in `docs/THINNEST-INTEGRATION.md` §4a.

| Rung | What speaks | Rate (VENDOR-STATED, §10 item 7) | Workspace |
|---|---|---|---|
| Clear | ThinnestAI end to end, in **studio-band** voices: catalogue voices with `tier: studio`, plus the voices our admin clones | ₹3.00/min plus the top-up fee (9% on Pro) | Developer workspace |
| Studio | Cartesia on our key through BYOK `scope: "voice"`; ThinnestAI's STT, LLM and telephony | ₹1.50/min including the line, plus Cartesia's charge to our key | One shared customer workspace |

What the docs say, and what follows from it:

- **Voice-only BYOK is documented.** Scope `voice`: "Your voice account speaks. Our speech-to-text hears the caller, our model answers, and the phone line is ours", at ₹1.50 a minute (`api-reference/bring-your-own-keys.md:13-24`). It needs only a checked voice key (`:26-28`) and is switched with `PATCH /byok {"enabled": true, "scope": "voice"}` (`:186-198`). This corrects §8's "TTS-only BYOK … is not documented", which was true of the morning snapshot only.
- **Scope is per workspace.** A customer inherits the developer's scope (`bring-your-own-keys/turn-byok-on-or-off.md:7`; `bring-your-own-keys.md:105-109`), so a rung cannot be set per agent inside one workspace. Clones belong to the workspace that made them (`api-reference/voices/list-voices.md:163-167`; `voice-clones/get-voice-clone.md:371-378`). Hence Clear agents (and clones) in the developer workspace, and Studio agents in one customer workspace with voice-only BYOK on.
- **A Studio call runs on their low-cost models only** (Prana, Prana [Voice], GPT-OSS 120B, GPT-5 Nano, GPT-4.1 Nano today); another model is refused with 400 (`bring-your-own-keys.md:44-63`). A Studio agent's model choice is narrower than a Clear agent's.
- **No fallback** if our Cartesia key fails: the voice does not speak (`:98-103`).
- **Clones** are studio voices at the studio rate, made from a 5–30 s sample under two recorded consents, admin-only, 10 on Pro and 20 on Scale, raised per workspace on request; deleting one moves its agents to a standard voice (`channels/voice-clone.md:9-12,33-51,81-120`). Studio-band voices and cloning need Pro (`api-reference/voices/list-voices.md:7`; `channels/voice-clone.md:20-24`).
- **Previews:** clones carry a short-lived `previewUrl`; BYOK voices have `POST /byok/voices/preview`, text capped at 200 characters and billed to our key (`bring-your-own-keys.md:219-232`); catalogue voices have none. We store previews in our own object store and never hand a vendor URL to a browser.
- **Gnani is not used on ThinnestAI.** It is not one of their voice providers (`bring-your-own-keys.md:88`) and we do not bring it.

**Money (calculation from the VENDOR-STATED rates; not invoices).** Clear: ₹3.00 × 1.09 = ₹3.27/min against ₹4.00, an 18.3% gross margin before the Pro subscription (price UNKNOWN here) and GST, down from 31.3% under D-681. Studio: ₹1.50 × 1.09 = ₹1.635/min plus Cartesia's cost per call-minute. Both rates reach money only through an operator's attestation (OPERATIONS gate T-14).

**Still open:** the Pro subscription's monthly price; whether a number can move with an agent between workspaces (§10, "Held back for later"); a rung switch on an agent with a number is refused until it is answered.
