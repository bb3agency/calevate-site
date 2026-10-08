# ThinnestAI engine: integration plan (D-678)

## Status

- **Decided 6 Oct 2026 by the founder.**
- **Phase 1 built 6 Oct 2026; phase 2 (D-682) built 7 Oct 2026** against the 7 Oct snapshot of their docs (`thinnest-findings/mirror/snapshots/2026-10-07/pages/`). `runbooks/thinnest-first-live-call.md` is the founder's checklist for the first live call.
- **Deployed to production with `ENGINE=thinnest` on 7 Oct 2026.**
- **Voices (D-687, 8 Oct 2026)** are built against the 7 Oct evening snapshot (`thinnest-findings/mirror/snapshots/2026-10-07b/pages/`, which wins over `2026-10-07` where they differ). Clear is the ThinnestAI voice band the console setting `thinnest_clear_voice_band` names (Premium for testing, Studio with admin clones once on Pro); Studio is our Cartesia key through voice-only BYOK in our one developer workspace, chosen per agent with `byok` (D-688, §4a). This supersedes D-681's "only Premium is sold, as Clear" and its "Studio on hold", and D-687's shared Studio customer workspace.
- **Sync with the 8 Oct docs (D-690, 8 Oct 2026)**, against `thinnest-findings/mirror/snapshots/2026-10-08/pages/`: built-in tools pinned at publish and read back, action call identity by `{{call.id}}` / `X-Call-Id`, every call setting read back and repaired by the drift sweep, the `{error, code}` envelope, `voice.language`, a paused line (`answersCalls: false`), `null` resets, live transfer, caller memory as `pastConversations: recap`, and each call's `costMicro` kept and reconciled. `docs/ROADMAP.md` D-690 names the files.

The founder decided three things:

1. ThinnestAI becomes a third selectable voice engine, `ENGINE=thinnest`, behind the existing **deployment-wide** switch.
2. ThinnestAI's own numbers are used: rented and attached in their console. Confirmed 7 Oct 2026: Vobiz is isolated to `ENGINE=pipecat`, bringing a carrier account to ThinnestAI is not used, by decision, and a move back to Pipecat would give clients new numbers (no portability between engines).
3. Voices and models come from their catalogue, with a clearly marked slot for BYOK once ThinnestAI documents how it works. For voices this is superseded by D-687 (§4a): the voice-only BYOK documented on 7 Oct carries the Studio rung, and the language model stays theirs.

**The Pipecat engine is not changed by any of this.** `ENGINE=pipecat` must behave exactly as it does today, and every Pipecat, Vobiz and carrier test must stay green.

Evidence for every vendor fact below:
- `thinnest-findings/mirror/` (VERIFIED-VENDOR-DOCS; the paths in this document are under its `pages/`);
- `docs/evidence/thinnest-ai-evaluation.md` (commercial terms and open questions).

## 1. Shape: a `control_plane` engine

ThinnestAI hosts the agent and the call. We configure it through their REST API (`https://app.thinnest.ai/api/v1`, `Bearer ta_live_…`, `api-reference/introduction.md`, `authentication.md`). Results come back as signed webhooks and are read from their call endpoints.

That is `AgentHosting = "control_plane"`: the shape the rented engine had before D-639. The generic machinery for it already exists:
- **the engine webhook route:** `voice-runtime /engine/{engine}`, with `engine_intake.py`, `webhook_routes.py` and `WEBHOOK_AUTH_BY_ENGINE`;
- **execution reconciliation:** `get_execution` / `list_executions`;
- **the rest:** the post-call pipeline over `ExecutionSnapshot`, and `kb_index_sync`.

**Reuse those seams; do not build parallel ones.**

| Calevate leg | Pipecat today | ThinnestAI |
|---|---|---|
| Phone line | Vobiz (our account) | ThinnestAI-rented number only (their carrier; ₹1/min with BYOK includes it). Vobiz is never used on this engine (founder, 7 Oct 2026) |
| Call control | voice-runtime answer XML → Pipecat Cloud | ThinnestAI |
| STT / LLM / TTS | Sarvam / Gemini-Azure-OpenAI / Cartesia-Gnani, our keys | STT and LLM: theirs (`GET /models`). TTS: Clear speaks their studio-band catalogue voices and our admin's clones; Studio speaks Cartesia on our key through voice-only BYOK (§4a). No Gnani |
| Opening | `greeting`-only opening, D-669 | Inbound: agent `greeting`. Outbound: the call's `purpose` (spoken first) |
| Truthful floor, confidentiality | Prompt plus worker checks plus `PromptLeakGuard` | Prompt only, verified by reading `instructions` back. No output guard is possible |
| In-call tools | `/v1/worker/**` on our API | ThinnestAI custom actions to our API with `X-Agent-Secret` (`agent/custom-api.md`). Phase 2 |
| Hang-up and results | Vobiz callbacks plus worker settlement | `call.completed` and `call.analysed` webhooks, plus the call list |
| Recording | Vobiz records; we copy to R2 within 90 days | `recording.url` (public signed link, expires in 30 or 75 days); we copy to R2 |
| Cost | Vobiz CDR `total_cost` | Operator-attested ₹/min times 30-second pulses. Each call's `costMicro` is kept on `calls.engine_charged_inr` and reconciled against it (D-690, §5) |

## 2. Mapping the `VoiceEngine` protocol (`apps/api/engine/thinnest.py`)

| Protocol method | ThinnestAI | Notes |
|---|---|---|
| `holds_credentials` / `credential_env_keys` | `THINNEST_API_KEY` | Env-only secret |
| `create_agent` | `POST /agents` | Fields: `name`, `instructions` = `compose_engine_prompt(cfg)`, `greeting` = our opening line, `model` (or `null` for the default), `language`, `voice.{answersCalls:true, unavailableMessage:null, voice, language, recordCalls:true, maxCallSeconds, detectMachines:false, summariseCalls:false, pastConversations}`, `scheduleCallbacks:false`, `captureLeads:false`, `escalation`, `collectFields: []`, `byok`; then `PATCH /agents/{id}/tools` pins the built-in tools and is read back (D-690). `secondLanguage` is retired (`snapshots/2026-10-08/pages/api-reference/agents/update-agent.md:560-573`) and not sent. **Refuse if the composed prompt is over 20,000 characters** (`snapshots/2026-10-07/pages/api-reference/agents/update-agent.md:426-431`); never truncate. |
| `update_agent` | `PATCH /agents/{id}` | Same mapping |
| `get_agent` | `GET /agents/{id}` | Returns `instructions` for the publish and drift verifier: the hard-rule-5 floor plus `CONFIDENTIALITY_MARKER` |
| `delete_agent` | `DELETE /agents/{id}` | 204 |
| `override_call_script` | `PATCH /agents/{id}` `voice: {answersCalls: false, unavailableMessage}` (D-690) | A paused line: the carrier's voice reads the reasonless credit-stop sentence and the call ends; no AI answers and nothing is billed as a call. The restoring publish sends `answersCalls: true` (`snapshots/2026-10-08/pages/api-reference/agents/update-agent.md:940-1016`; `channels/voice.md:696-725`) |
| `start_outbound_call` | `POST /calls` | `to`, `purpose` = opening line, `agent`, `reference` = our call id, `metadata` = tenant, agent and call ids, `Idempotency-Key` = our dispatch key. **No `retry`**: our campaign ladder owns retries. **No `callingHours`**: our compliance gate owns the window, and their 09–21 check runs anyway. Map 403, 409 and 429 to our refusals (`dial_was_not_placed` where nothing rang). |
| `end_call` | `DELETE /calls/{id}` | 200 means cancelled, 202 means ending, 409 means already ended |
| `transfer` | **Refuse by name** | Nothing outside a call can move it. The agent itself puts a caller through (`in_call_handoff`, D-690): `handOver {mode: call, phone, line}` with `tools.escalate_to_human`, on numbers rented from ThinnestAI or on Plivo or Telnyx numbers; elsewhere the platform falls back to a chat hand-over (`snapshots/2026-10-08/pages/channels/voice.md:483-492`) |
| `search_numbers`, `provision_number`, `release_number`, `bind_inbound_number`, `unbind_inbound_number` | **Refuse by name**, with the console step | Renting stays a console step. Attaching is ours but outside the protocol: `campaigns/engine_numbers.py` sets `agent`/`callingAgent` with `PATCH /phone-numbers/{number}` (D-691, §3a) |
| `list_engine_numbers` | `GET /phone-numbers` (not paged, `snapshots/2026-10-08/pages/api-reference/phone-numbers/list-phone-numbers.md:7`) | Read only through `engine_numbers.vendor_numbers`, the one seam for vendor number calls (§3a) |
| `set_llm_credential` | **The LLM BYOK slot**: refuse with `byok_not_documented` | Full (`scope: all`) BYOK is not used. The voice-only BYOK of the Studio rung is a separate path (§4a): our Cartesia key and `PATCH /byok {"enabled": true, "scope": "voice"}` in our developer workspace, with each agent's `byok` saying whether it follows it |
| `attach_kb` / `detach_kb` / `list_kb` / `list_account_kb` | `POST`, `DELETE` and `GET /agents/{id}/knowledge`, text only (200k characters per document, `knowledge.md:52`) | We send text extracted by our own `document_text`/`document_ocr`. A longer source is split on chunk boundaries (`engine/text_split.split_for_text_cap`) into at most 10 documents (2,000,000 characters; above that it is refused with `engine_kb_text_too_long`). Each part's title carries `[cv-part i/n group]`; the handle is `cv-parts:<id>,<id>…`, which `list_kb` rebuilds from the titles and `detach_kb` removes part by part. A part refused midway removes the parts already sent and refuses with `engine_kb_part_failed` |
| `list_voices` | `GET /voices` plus `GET /models` | Tier mapping in §4 |
| `get_execution` | `GET /calls/{id}` | The 6 Oct pages answered 404 for calls the API did not place; the 7 Oct snapshot takes any call id (`snapshots/2026-10-07/pages/api-reference/calls/get-call.md:7`). The signed delivery is still read first, and the call list settles anything missed |
| `list_executions` | `GET /calls?…` with a cursor (`list-calls.md`) | Reconciliation source for inbound calls and for missed webhooks |
| `verify_webhook` | `x-thinnest-signature-v2` = `sha256=` + HMAC-SHA256 of `<x-thinnest-delivered-at>.<raw body>` under the endpoint `signingSecret`, constant-time, and the delivery time within 5 minutes of our clock (`snapshots/2026-10-08/pages/api-reference/webhooks.md:100-147`, D-691) | The v1 header (body only, no time) is not accepted; both ride every attempt |
| `parse_webhook` | `call.completed` and `call.analysed` → `CallEvent` | Map `status`/`hangup` to our outcomes; transcript `{speaker, text, at}` → `TranscriptTurn` |

The capabilities descriptor must be honest. For example:
- `agent_hosting="control_plane"`;
- no control-plane transfer; in-call hand-over from a destination fixed at publish (D-690);
- no number provisioning;
- knowledge base as text;
- speech legs are the engine's own (`SpeechControl` = engine-dictated);
- webhook auth `hmac`.

**It must pass `packages/shared/tests/engine_conformance/`.**

## 3. Inbound path, results and reconciliation

1. **Webhook registration.** A webhook is registered per agent at publish time: `POST /webhooks` with `{agent, url: <WEBHOOK_BASE_URL>/engine/thinnest, events}`, the events being `call.analysed`, `call.completed`, `contact.opted_out`, `conversation.escalated` and `lead.captured` (D-691). An endpoint registered with fewer is brought up to date in place with `PATCH /webhooks/{id} {events}`, keeping its secret.
   - The `signingSecret` is returned **once**. Store it sealed (envelope-encrypted like other credentials), keyed by agent.
   - Re-publishing must not create duplicates.
2. **voice-runtime `/engine/thinnest`.**
   - Verify `x-thinnest-signature-v2` against the agent's secret, chosen by the `agent` query parameter of our own url, then refuse (401) a `x-thinnest-delivered-at` more than 5 minutes from our clock. Never `sentAt`: every retry repeats the first attempt's bytes, so `sentAt` is hours old by design (`webhooks.md:110-131`).
   - Dedupe in the inbox on the signed event `id` (equal to `x-thinnest-event-id`, the same on every retry and re-send); the unit is `<event>:<event id>`. `x-thinnest-attempt` is recorded on `webhook_deliveries.attempts`; a duplicate logs it.
   - Route by event: call events to `ingest_engine_event`; `contact.opted_out` to `ingest_engine_opt_out` (§6); `lead.captured` and `conversation.escalated` to `ingest_engine_notice`, which normalises them with `parse_notice` (D-690), attributes them to the route's tenant and records them id-only — no product surface consumes a notice yet. The endpoint's own `test` delivery is acked and ignored.
   - Ack in under 500 ms (hard rule 3) and hand off to ARQ.
3. **Worker.**
   - Upsert the call row: `engine_call_id` = their `id`, our `reference` comes back.
   - Write the transcript (redaction as today), run our own extraction pass, and update CRM and leads.
   - Meter the minutes (§5).
   - Copy `recording.url` to R2 (90 days) once `ready`; it expires on their side after 30 or 75 days.
   - Fire our client webhooks, including `call.recording_ready`.
4. **Reconciliation sweep (required).** ThinnestAI retries a failed attempt after 1m, 5m, 30m, 2h and 6h and switches an endpoint off after five events in a row that failed every attempt (`snapshots/2026-10-08/pages/api-reference/webhooks.md:110-155`). So:
   - list calls since the last watermark and settle any we have not;
   - check each endpoint's `enabled` flag, `PATCH enabled:true` with an alarm when it was switched off, then `POST /webhooks/{id}/redeliver {since}` once — back to 9 hours before the endpoint was last seen healthy, never past 7 days (D-691, `workers/engine_webhooks.redelivery_since`). Re-sent events keep their ids, so the inbox absorbs any already handled.

### 3a. Numbers (D-691)

Renting is a ThinnestAI console step. Everything after it is ours, through ONE seam, `campaigns/engine_numbers.py` (`number_workspace`, `vendor_numbers`, and the attach and business-details calls), which takes the vendor workspace a tenant's numbers live in. Today that is always our developer workspace; when each client gets its own customer workspace (founder decision, 8 Oct 2026; a later lane), `number_workspace` answers per tenant and nothing else changes.

- **Record this number.** The client's Numbers page lists what ThinnestAI holds; an unrecorded number has a **Record this number** action (`POST /v1/admin/numbers/tenants/{id}/engine/record`) for that tenant. A hand-typed number with provider `thinnest` (`POST /v1/admin/tenants/{id}/numbers`) goes through the same function. Both refuse a number ThinnestAI does not hold (`engine_number_not_held`), a typed handle that is not the vendor's (`engine_number_ref_mismatch`) and a number another client's agent answers (`engine_number_answered_by_other_client`). Handle, `engine_owned` (= `source: rented`) and series are read, never typed.
- **Price.** A rented number gets `client_inr_per_month` from the attested number price (gate 26, ₹499) and its first period is collected in the same transaction (D-665); `renew_number_rentals` bills it from then on. A rented number recorded before this was priced is priced by the daily sweep from its NEXT renewal date (`rental_charged_from`). A brought number is not priced. Our own cost for a rented number is not metered: `meter_number_rentals` skips `thinnest` rows, whose rental ThinnestAI charges in rupees from the workspace balance.
- **Attachment; we are the master.** From our row: an agent that answers (`inbound`/`both`) is the number's `agent` with `callingAgent` null (an agent calls out on its own line, `calls/place-call.md:974`); an outbound-only agent is lent it as `callingAgent`; a released number or one on no live published agent has neither. Sent on record, on attach (admin and client flows) and by the daily sweep, only the fields that differ (re-sending one is a 409). `agent` is applied before `callingAgent` and a refusal keeps what was applied (`phone-numbers/update-phone-number.md:7`): a partial or refused apply alarms `engine_number_attachment_failed`, and the sweep retries.
- **Daily sweep** (`reconcile_engine_numbers` on this engine): per tenant, against the list of the workspace that tenant's numbers live in — `engine_number_unrecorded` (held, recorded by nobody; never adopted), `engine_number_missing_at_vendor`, `engine_number_attachment_repaired` (drift put back). At most 100 numbers are re-read a run.
- **Business details.** `GET /phone-numbers/business-details` (developer workspace today, through the seam) is shown read-only on the ops page; `rejected`, `suspended` or `expired` alarms `engine_business_details_lapsed` from the daily sweep.

## 4. Voices, models, language

- **Voices.** `GET /voices` returns tiers `standard`, `premium` and `studio`; Studio needs their Pro plan or above (`snapshots/2026-10-07/pages/api-reference/voices/list-voices.md:7`; the 6 Oct pages said Scale).
- **Price rungs.** Their tiers map to our price rungs only through an **operator-attested ₹/min per tier** (hard rule 7). Since D-687 their `studio` band is sold as our Clear rung and the voice-only BYOK leg as our Studio rung; `standard` and `premium` are not sold (§4a, §5). Until a rate is attested its voices are offered as unavailable, with the reason.
- **Models.** `GET /models` lists models with `voice:true` (fast enough for calls) and `available`.
- **Business facts as knowledge.** On publish (agent and experiment arm alike) the facts document is created, replaced only when the facts changed (sha256 on `engine_agent_routes.facts_digest`; the new document is attached before the old one is removed, and a failed removal removes the new one again and refuses with `engine_facts_replace_failed`), and removed when the script no longer has a facts block. Deleting the vendor agent deletes its knowledge (`agents.md:82`). The handle is recorded on `engine_agent_routes.facts_kb_ref`, and the KB publish gate, drift sweep and orphan sweep count it as ours, under the tenant's knowledge lock. The document carries the INTAKE half of the block only (`t0_block.facts_without_knowledge`, D-689): the "Published knowledge:" half is the client's published sources, which reach the agent as their own documents.
- **The client's knowledge, on every agent (D-689, 8 Oct 2026).** Knowledge belongs to the client and every one of its agents answers from it; ThinnestAI keeps knowledge per agent only (`api-reference/knowledge/*`, no workspace-level knowledge base), so each published source is one document on EACH of the client's published, non-archived vendor agents, claimed per (source, agent) on `engine_kb_routes`. A new version is attached to every agent before any old copy is withdrawn; an attach refused on any agent removes every copy the publish added and refuses; a withdrawal refused on some agents completes the rest and alerts `kb_fan_out_incomplete`. Withdrawing or deleting a source removes it from every agent. An agent published later — and any agent a fan-out could not reach — is caught up on its next publish and by `sweep_kb_uploads` (`kb/service.converge_agent_knowledge`); archiving an agent withdraws its copies. The drift sweep compares each vendor agent with the claims recorded for that agent.
- **Per-agent choice (built).** `agents.engine_voice_id` and `agents.engine_model_id` (migration `b7e2d94f1a30`, NULL = the vendor default) are set through `PATCH /v1/agents/{id}` from the admin and client voice panels and sent as `voice.voice` and `model` (`agents.md:105-110,156`) only on a leg the engine dictates. `agents/engine_choice.py` checks them against a live `GET /voices` + `GET /models` before the vendor write, and on a draft at save time, refusing by name: `engine_voice_not_in_catalogue`, `engine_voice_tier_unpriced` (band not attested, through `engine_minute_is_billable`), `engine_voice_tier_unknown`, `engine_model_not_in_catalogue`, `engine_model_not_call_capable`, `engine_model_not_on_plan`, `engine_catalogue_incomplete`, and `engine_voice_choice_not_offered` / `engine_model_choice_not_offered` on an engine that runs our own voices or models. The route row's `engine_rate_key` is stamped from the chosen voice's band, or `platform` when none is chosen.
- **Clearing a choice sends `null`** (D-690): `null` puts the agent back on the vendor default, Prana [Voice] for the model and Kavya for the voice (`snapshots/2026-10-08/pages/api-reference/agents/update-agent.md:536-545, :951-961`); `engine_choice_reset_unsupported` is retired. Kavya bills at the Premium band, so publish still refuses an agent with no voice chosen (`engine_voice_required`) and the drift sweep repairs a live agent found on another voice. A cleared model changes no rate key.
- **Language (D-690).** An agent has one language; "to serve two, leave the agent on Match the customer" and `secondLanguage` is retired (`snapshots/2026-10-08/pages/channels/voice.md:225-239`; `api-reference/agents/update-agent.md:560-573, :962-970`). So an agent with one language is sent `language` and `voice.language` fixed to it (Telugu → `"Telugu"`), which also tells the recogniser what to listen for; an agent with extra languages (Telugu first, English too) is sent `language: "auto"` with `voice.language: null`, and its Telugu greeting still opens the call. A primary language outside the 37 the console offers is `auto`.
- **BYOK.** A WORKSPACE setting (console: Settings → Your keys). The 7 Oct 2026 morning snapshot documented it as **all three legs or none**; that is **superseded by the evening snapshot**, which documents two scopes: `all` and `voice` (`snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys.md:13-24`; `bring-your-own-keys/turn-byok-on-or-off.md:7`). D-687 uses `voice` for the Studio rung (§4a). Full (`all`) BYOK is still not sold: `set_llm_credential` refuses (`byok_not_documented`), and `THINNEST_BYOK_ENABLED` still describes the developer workspace running on all three of its own keys (D-681). With it on, a per-agent catalogue voice or model does not apply: the pickers lock with a plain reason (`EngineCatalogueOut.choosable=false`, `choice_note`), a new choice is refused with `engine_choice_under_byok`, a stored one is not sent, and every publish stamps the `platform` rate key instead of a voice tier.
- **Voices (7 Oct 2026 snapshot).** Every voice speaks every supported language and the agent's language decides which; each voice carries an accent tag; Studio voices are listed on Pro and above (`api-reference/voices/list-voices.md:7,345`).
- **In-app catalogue prices (FOUNDER-RELAYED, not invoices).** Standard ₹2.00/min, Premium ₹2.50, Studio ₹3.00 (Scale plan: ₹1.90 / ₹2.375 / ₹2.85). Telugu Standard voices: Abirami Te, Anjura Te, Divya, Karthik, Tanvi. These are what an operator attests per tier; nothing in code holds them.

### 4a. Voices on this engine (D-687, D-688, 8 Oct 2026)

The founder's decisions; they supersede D-681's "Clear = Premium band" and "Studio on hold". D-688 replaced D-687's shared Studio customer workspace with per-agent BYOK in one workspace and made the band sold as Clear a setting. Paths are under `thinnest-findings/mirror/snapshots/2026-10-07b/pages/`; the per-agent `byok` field is LIVE-DOCS (`docs.thinnest.ai/api-reference/agents/update-agent`, read 8 Oct 2026; evaluation §12 item 1).

| Our rung | What speaks | Vendor rate (VENDOR-STATED) | Workspace |
|---|---|---|---|
| **Clear** | ThinnestAI's own stack end to end, in the band `thinnest_clear_voice_band` names: **Premium** (default, any plan) or **Studio** (catalogue voices with `tier: studio` and our admin clones, Pro and above) | ₹2.50/min Premium or ₹3.00/min Studio, plus the wallet top-up fee | Our developer workspace, agent `byok: "off"` |
| **Studio** | Cartesia on **our** key through BYOK `scope: "voice"`; ThinnestAI's STT, LLM and telephony | ₹1.50/min including the line, plus Cartesia's own charge to our key | Our developer workspace with voice-only BYOK on, agent `byok: "workspace"` |

- **Studio band.** `GET /voices` lists `standard`, `premium` and `studio`, and `tier` is the band a call is billed at; studio voices (the shared catalogue and our clones) are listed only on **Pro** and above (`api-reference/voices/list-voices.md:7,436-451`). A clone is a studio voice at the same per-minute rate (`channels/voice-clone.md:9-12,81-89`). So Clear on the Studio band needs ThinnestAI Pro; on Premium it does not. Every band is cached for the admin with its band (`platform_voice_catalog.vendor_band`); only the band sold as Clear can be added (`voice_band_not_sold` otherwise), and a listing with none of it is the `voice_catalogue_no_studio_band` alarm, not a credential failure.
- **Clones are the admin's, never a client's.** The vendor makes cloning admin-only and records two separate consents against the voice, with who agreed and when (`channels/voice-clone.md:33-44,114-120`); our admin route sends both as explicit admin attestations and writes `audit_log`. A sample is 5 to 30 seconds, WAV, MP3, M4A or WebM (`:47-51`). Limits: **10 clones on Pro, 20 on Scale**, raised per workspace on request (`:93-99`). Deleting a clone moves every agent using it to a **standard** voice (`:103-112`), a band we do not sell, so the drift sweep must notice it.
- **Clients pick, they do not browse the vendor.** A client sees only voices the admin added to our catalogue AND enabled, with a preview. Previews are stored in our object store and served by us: a clone has a 60-second `previewUrl`, a BYOK voice has `POST /byok/voices/preview` (text capped at 200 characters, billed to our Cartesia key, `api-reference/bring-your-own-keys.md:219-232`), and a catalogue voice has none, so the admin may upload a short sample.
- **One workspace, per-agent `byok` (D-688).** BYOK is switched per workspace (`bring-your-own-keys/turn-byok-on-or-off.md:7`), and every agent carries `byok`: `workspace` follows it, `off` keeps the agent on ThinnestAI's voices and models at their normal rate whatever the workspace does. So our developer workspace runs voice-only BYOK with our Cartesia key, Clear agents are published `off` and Studio agents `workspace`; every create and update states it, never leaving the `workspace` default. The publish read-back refuses a mismatch and the drift sweep sets a live agent's `byok` back to what its rung requires (`engine_agent_voice_key_repaired`). Clones stay in the same workspace. No customer workspace is created anywhere in this product.
- **Switching Studio voices on.** One operator act per deployment, "Enable Studio voices" (`POST /v1/ops/voices/studio-voices/enable`, step-up), in this order: every published agent not on a Studio voice is set to `byok: off` and read back, and nothing is switched on if any fails (`studio_agents_not_kept_off`), because turning voice-only BYOK on moves every agent not `off` onto Cartesia; our Cartesia key is installed (`PUT /byok/credentials`) unless the workspace already holds one; `PATCH /byok {enabled: true, scope: "voice"}`; the state is read back. Turning it off (`.../disable`) withdraws the Studio voices and asks for confirmation while Studio agents are published. A rotated `cartesia_api_key` is pushed to the workspace through the outbox (`apps/workers/studio_voice_key.py`; `studio_voice_key_push_failed` pages on failure). The hourly voice sync reads `GET /byok` and, if our key is off while Studio agents are published, raises `studio_voice_key_off_with_agents`; it never switches BYOK back on.
- **Studio voice per agent.** `GET /byok/voices` lists what our Cartesia key reaches (`bring-your-own-keys.md:200-217`) and `PUT /agents/{id}/byok-voice` sets the agent's voice (`:255-258`; `agents/set-agent-byok-voice.md:7`).
- **Model on a Studio call.** With voice-only BYOK the call minute includes their model, so a call runs only on their low-cost models (Prana, Prana [Voice], GPT-OSS 120B, GPT-5 Nano, GPT-4.1 Nano today; `GET /models` marks `voiceOnlyByok`); setting another model returns 400, and an agent already on another model runs GPT-OSS 120B on calls (`bring-your-own-keys.md:44-63`). A Studio agent's model choice is therefore narrower than a Clear agent's.
- **No fallback.** If our Cartesia key fails, the voice does not speak; their own STT and LLM keep their usual backups (`bring-your-own-keys.md:98-103`).
- **Rung switch.** A field change on republish: the vendor agent, its number and its knowledge stay where they are (D-688). The switch is read once when a call starts, so a call already ringing keeps the old voice.
- **Gnani is not used on this engine.** No ThinnestAI surface, label or price names it.

## 5. Money

ThinnestAI's `costMicro` (millionths of the currency, on `call.analysed` and `GET /calls/{id}`, `snapshots/2026-10-08/pages/api-reference/calls/get-call.md:498-523`) is what a call cost the workspace; it is kept on `calls.engine_charged_inr` and reconciled, never metered (D-690: `engine_call_cost_variance` compares charge × (1 + top-up fee) with the attested minute; a Studio call must carry its Cartesia row). Metering works as follows:
- **Billed minutes:** `ceil(seconds / 30) × 0.5`.
- **Rate:** an operator-attested `THINNEST_INR_PER_MIN`, in NUMERIC INR and console-managed, plus a per-tier rate if we use their voices.
- **Meaning of ₹1/min:** BYOK including telephony. Their own models are ₹1.5 or ₹2.5 (FOUNDER-RELAYED).
- **Unit cost:** `unit_cost_paid` = billed minutes × attested rate.
- **No rate, no sale:** an unattested rate refuses to sell the minute, exactly as the LLM price door does today.
- **Client billing (D-681):** the client is billed in the same 30-second steps on every engine (`rates.client_billed_minutes`), separately from this cost metering.
- **What is sold (D-687, superseding D-681's Premium-only rule):** the vendor `studio` band is sold as **Clear** (₹4.00 on every pack) and the voice-only BYOK leg as **Studio** (the Studio column, ₹7.00 falling to ₹5.50). `standard` and `premium` voices are refused. Publish still refuses an agent with no voice chosen (`engine_voice_required`) and full workspace-keys mode (`engine_own_keys_not_on_sale`). The client rung comes from the stamped `engine_agent_routes.engine_rate_key`, never from `agents.tts_voice`. The Studio leg has its own rate key, `byok_voice` (D-687), for which the operator attests ₹1.50; Cartesia's own charge to our key is a separate cost line through the existing Cartesia pricing.
- **Cost floors (D-687).** A floor is a margin guard and never the billed cost. The rates are VENDOR-STATED (evaluation §10 item 7: studio band ₹3.00, voice-only BYOK ₹1.50, top-up fee **9% on Pro**) and reach money only through an operator's attestation.
  - **Clear:** ₹3.00 × 1.09 = **₹3.27/min** against ₹4.00, an **18.3%** gross margin before the Pro subscription itself (its monthly price is not recorded in this repo: UNKNOWN) and before GST. D-681's Premium floor was ₹2.75 at 31.3%, so **Clear's margin falls by 13 points; the founder should confirm the ₹4.00 Clear price still stands.** Pay-as-you-go (10% fee) would be ₹3.30 (17.5%), but studio voices need Pro.
  - **Studio:** ₹1.50 × 1.09 = ₹1.635/min, plus Cartesia's cost per call-minute (TRD §10.1: ₹2.06–3.09, `rates.cartesia_tts_inr_per_call_minute`), so about ₹3.70–4.73/min. At the deepest Studio rung (₹5.50) that is 32.8% down to 14.1%.

## 6. Compliance (unchanged rules, new enforcement points)

- **Our dial gate still decides every outbound call** (`check_dispatch`). ThinnestAI's own opt-out, do-not-call and 09:00–21:00 checks are a second net, not our control.
- **Person-level writes only in the client's OWN workspace (D-691).** The do-not-call push and the contact erasure below act on a whole ThinnestAI workspace. Both ask `tenancy/engine_workspace.own_workspace` when queued and again when sent, and the client refuses a request without an `org_` workspace header (`engine/thinnest_customer_data.py`), so neither can reach our developer workspace, which holds every client's data. Until the workspace lane replaces `workspace_for_tenant`, no tenant has one, so today both are skipped.
- **Do-not-call is ours, per client, and two-way (founder decision, 8 Oct 2026, revised; D-691).** Our per-client list decides every dial. Each tenant-scoped addition is pushed through the outbox to `POST /do-not-call` in the client's own workspace (`compliance/engine_dnc.py`, job `push_engine_dnc`). A `contact.opted_out` is filed on the list of the client whose agent heard it, through `record_call_optout` (`detected_by: engine_platform`), so it binds before the next dispatch tick (hard rule 5). A dial ThinnestAI refuses with `do_not_call`/`opted_out` for a number NOT on that client's list is `engine_platform_dnc_block` ("blocked by the voice platform's do-not-call list", `compliance/platform_dnc.py`): it settles the contact like a person-level refusal and adds nothing to the client's list.
- **Erasure (founder decision, 8 Oct 2026, revised; D-691).** No endpoint deletes one call (`DELETE /calls/{id}` only cancels, `calls/cancel-call.md:7`); `DELETE /contacts/{id}` erases a person's contact, conversations, calls and recordings in one workspace (`workspace/data-and-erasure.md:14-56`). Our copies are always erased by us. Where the tenant has its own workspace, the erasure queues `erase_engine_contact` (subject sealed), which finds the contact with `GET /contacts?phone=` and deletes it; the `voice_engine` task records the outcome — `confirmed` when every recording went, `requested` when ThinnestAI reports `recordingsPending` (it retries nightly and exposes no completion signal, so an operator closes it). The proof says `contact_erasure_requested_in_client_workspace`. Where it has none, nothing is asked, no task is opened and the proof says the copy was "not deleted at the voice platform; expires with its plan retention" (`not_deleted_expires_with_plan_retention`).
- **Hard rule 5.**
  - The composed prompt carries the truthful floor and `CONFIDENTIALITY_RULE`.
  - Publish and drift verify both by reading `instructions` back.
  - The 20,000-character cap is checked before publish (`snapshots/2026-10-07/pages/api-reference/agents/update-agent.md:426-431`; the 6 Oct pages said 8,000). The facts stay in knowledge because `instructions` is re-sent, and paid for, on every turn.
  - **The business facts are not in the prompt (founder's decision, 6 Oct 2026).** On this engine only, the script's `[T0 FACTS]` block is taken out of `instructions` and pushed as one knowledge document titled "Business facts" (`agents/engine_facts.py`), so the 8,000 characters hold the platform rules and the client's script. The prompt gains one platform-written section, `FACTS_IN_KNOWLEDGE_GUIDANCE`: look the facts up in knowledge, never guess, and say "I don't know" with a callback offer when they are not there. Every hard-rule block (speaking rules, `CONFIDENTIALITY_RULE`, the truthful floor) stays in the prompt and the read-back still verifies them. Every other engine composes byte-for-byte as before (`tests/thinnest_facts_in_knowledge_test.py` pins the digests).
- **D-669.** Opening line verbatim in `greeting` (inbound) and `purpose` (outbound).
- **D-674.** The prompt rule only. `PromptLeakGuard` does not run on this engine, and SECURITY-COMPLIANCE §6.1 must say so.
- **Recording notice.**
  - `recordCalls:true` makes ThinnestAI record.
  - Our recording disclosure and truthful answer apply unchanged.
- **Promotional calls.** These need a 140-series number registered with DLT (`channels/phone-numbers.md`). Our DLT gate is unchanged.

## 7. Configuration

| Key | Where | Notes |
|---|---|---|
| `ENGINE=thinnest` | console-managed (needs republish) | Deployment-wide switch |
| `THINNEST_API_KEY` | env-only secret | `ta_live_…`, full access (calls need it) |
| `THINNEST_API_BASE_URL` | env-only, default `https://app.thinnest.ai/api/v1` | Tests point it at a fake |
| `ENGINE_INTAKE_KEK` | env-only, same value on api, workers and voice-runtime | Seals the per-agent webhook signing secrets and the verified delivery bodies |
| `WEBHOOK_BASE_URL` | console-managed (needs republish) | Public `https://` origin ThinnestAI posts call results to |
| `ENGINE_ACTIONS_BASE_URL` | console-managed (needs republish) | Public `https://` API origin the in-call actions call |
| `THINNEST_MAX_CONCURRENT_CALLS` | console-managed (live), default 5 | The pay-as-you-go ceiling; raise only when ThinnestAI confirms (gate T-7) |
| `THINNEST_BYOK_ENABLED` | console-managed (needs republish), default off | The developer workspace runs on all three of its own keys (`scope: all`); such calls are not on sale (D-681). Not the Studio rung's voice-only BYOK |
| `THINNEST_CLEAR_VOICE_BAND` (`thinnest_clear_voice_band`) | console-managed (needs republish), default `premium`, added by D-688 | The ThinnestAI voice band sold as Clear: `premium` or `studio` (Pro and above; clones are Studio). Attest that band's per-minute rate before offering it. An agent already published keeps its band's rate key until republished on a voice of the new band |
| Per-minute rates (`platform`, `standard`, `premium`, `studio`, `byok_voice`) | ops console **Per-minute rates**, attested with step-up | Hard rule 7. The band `thinnest_clear_voice_band` names is sold as Clear and `byok_voice` (voice-only BYOK) as Studio (D-687, D-688); no other band is sold |
| Per-agent webhook signing secrets and action secrets | sealed in the DB | Returned once by the vendor, or generated by us |

Each key has an entry in `check_deploy_env` (env-only ones), `DEPLOYMENT.md` §12.7 and
`PLATFORM-CONFIG.md` §4, a plain label in the ops console's Calling section, and readiness
on `/healthz/ready`: `THINNEST_API_KEY` from the adapter, and `ENGINE_INTAKE_KEK` (api,
workers, voice-runtime), `WEBHOOK_BASE_URL` and `ENGINE_ACTIONS_BASE_URL` (api, workers)
outside `local` (`apps/api/core/settings.py`, `tests/thinnest_readiness_test.py`). Ambient
vendor keys are stripped in tests by `tests/conftest._no_ambient_credentials`.

## 8. What is built (phase 1, D-678; phase 2, D-682)

Phase 1 built the adapter, the inbound intake, reconciliation, the catalogue, the business
facts as knowledge and engine-minute pricing. Phase 2 makes `ENGINE=thinnest` on par with
Pipecat for a first live call. Pipecat's behaviour is unchanged by both.

- **Adapter and catalogue.** `apps/api/engine/thinnest.py` (conformance suite), the offer
  seam for voices and models (`agents/engine_catalogue_offer.py`, `engine_choice.py`), the
  20,000-character instruction cap (`engine/hosted_platform.py`), facts as one knowledge
  document (`agents/engine_facts.py`).
- **In-call actions (phase 2).** Opt-out, call-back, call-back cancel and the hand-over
  request are ThinnestAI custom actions to `/v1/worker/engine-actions/thinnest/<tool>` on the
  api (`engine/thinnest_actions.py`, `reliability/engine_actions.py`,
  `worker/engine_actions.py`), each carrying the agent's sealed per-agent secret in
  `X-Agent-Secret`, verified in constant time before the body is read, reusing the Pipecat
  tools' service functions. Registered, converged and enabled at publish, removed at
  unpublish, and checked by the drift sweep. Which call: every body carries the platform-
  filled `{{call.id}}` and every action call the `X-Call-Id` header
  (`snapshots/2026-10-08/pages/agent/custom-api.md:84-119`); the receiver reads the call
  with `GET /calls/{id}` and acts only when it is live on that agent (D-690). An agent with
  a hand-over destination on duty puts the caller through itself (`escalate_to_human`) and
  holds no hand-over action of ours; without one the request is recorded, not bridged.
- **Call lifecycle and money (phase 2).** Dispatch is held to `thinnest_max_concurrent_calls`
  (`engine/carrier_pacing.py`); a delivery whose signed `x-thinnest-delivered-at` is more
  than 5 minutes from our clock is refused (`voice-runtime/signed_intake.REPLAY_TOLERANCE`,
  D-691; the `sentAt` window it replaced dropped every retry);
  the usage call log's per-call charge is compared with what we metered and alarmed on a
  difference (`workers/engine_charges.py`), never written as a correction (hard rule 4);
  recordings are copied from the engine with its documented retention
  (`engine/recording_source.py`).
- **Product surfaces (phase 2).** The rate card says, per deployment, which voice no agent
  can be put on (`CreditPacksOut.voice_not_offered`, `billing/payment_routes.
  voice_tier_not_offered`): on this engine, Studio until our Cartesia key is on in the
  workspace and its minute is attested (D-688; it was always Studio under D-681), and the cheaper rung on our own voices.
  `/pricing` leads with the voice that can be bought; the client "What calls cost", the
  public rate card and the ROI calculator print the server's sentence. The ops
  per-minute rate panel says which rate a client is sold (`sold_as`). Number purchase
  and transfer settings render the server's own refusals and reasons on this engine;
  client copy names no provider (D-679), held by `publicVendorNames.test.ts`.
- **Readiness and configuration (phase 2).** §7.
- **Docs.** OPERATIONS §2 T-series (questions for ThinnestAI), FLOWS §3a, this file, and
  `runbooks/thinnest-first-live-call.md`.

- **Voices (D-687, D-688).** §4a: the band named by `thinnest_clear_voice_band` as Clear,
  voice-only BYOK Cartesia as Studio in the same workspace with per-agent `byok`, admin clone
  and preview routes, the client picker limited to admin-enabled voices. The D-687 and D-688
  rows of `docs/ROADMAP.md` name the files.

**Decided (D-688, superseding D-687's workspaces):** every agent in our one developer
workspace, Clear `byok: off` and Studio `byok: workspace`. A customer workspace per tenant
(`docs/evidence/thinnest-ai-evaluation.md` §9, gate T-8) stays a founder decision; nothing
in this tree creates one. Decided: ThinnestAI's own numbers
only on this engine.

**Gates that stay open, needing ThinnestAI's answers:** OPERATIONS §2 T-1..T-10 (T-1, BYOK
per leg, is answered by the 7 Oct evening snapshot: scopes `all` and `voice`) — whether `null` resets `voice.voice` or `model`, the webhook replay
window and redelivery, the action timeout and call identification, the DPA and training,
Telugu quality, the concurrency raise, customer workspaces, the DLT roles on our numbers,
and per-band prices on an invoice.
