# ThinnestAI engine: integration plan (D-678)

## Status

- **Decided 6 Oct 2026 by the founder.**
- **Phase 1 built 6 Oct 2026; phase 2 (D-682) built 7 Oct 2026** against the 7 Oct snapshot of their docs (`thinnest-findings/mirror/snapshots/2026-10-07/pages/`). `runbooks/thinnest-first-live-call.md` is the founder's checklist for the first live call.
- **Deployed to production with `ENGINE=thinnest` on 7 Oct 2026.**
- **Voices (D-687, 8 Oct 2026)** are built against the 7 Oct evening snapshot (`thinnest-findings/mirror/snapshots/2026-10-07b/pages/`, which wins over `2026-10-07` where they differ). Clear is ThinnestAI's studio band plus admin clones; Studio is our Cartesia key through voice-only BYOK in one shared customer workspace (§4a). This supersedes D-681's "only Premium is sold, as Clear" and its "Studio on hold".

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
| Cost | Vobiz CDR `total_cost` | No cost field. Operator-attested ₹/min times 30-second pulses |

## 2. Mapping the `VoiceEngine` protocol (`apps/api/engine/thinnest.py`)

| Protocol method | ThinnestAI | Notes |
|---|---|---|
| `holds_credentials` / `credential_env_keys` | `THINNEST_API_KEY` | Env-only secret |
| `create_agent` | `POST /agents` | Fields: `name`, `instructions` = `compose_engine_prompt(cfg)`, `greeting` = our opening line, `model`, `language`/`secondLanguage`, `voice.{voice, recordCalls:true, maxCallSeconds, detectMachines:false, summariseCalls}`, `collectFields` from the extraction schema. **Refuse if the composed prompt is over 20,000 characters** (`snapshots/2026-10-07/pages/api-reference/agents/update-agent.md:426-431`); never truncate. |
| `update_agent` | `PATCH /agents/{id}` | Same mapping |
| `get_agent` | `GET /agents/{id}` | Returns `instructions` for the publish and drift verifier: the hard-rule-5 floor plus `CONFIDENTIALITY_MARKER` |
| `delete_agent` | `DELETE /agents/{id}` | 204 |
| `override_call_script` | Per call: `overrides.callInstructions` (up to 4,000 characters) plus `purpose` | `place-call.md:194-208` |
| `start_outbound_call` | `POST /calls` | `to`, `purpose` = opening line, `agent`, `reference` = our call id, `metadata` = tenant, agent and call ids, `Idempotency-Key` = our dispatch key. **No `retry`**: our campaign ladder owns retries. **No `callingHours`**: our compliance gate owns the window, and their 09–21 check runs anyway. Map 403, 409 and 429 to our refusals (`dial_was_not_placed` where nothing rang). |
| `end_call` | `DELETE /calls/{id}` | 200 means cancelled, 202 means ending, 409 means already ended |
| `transfer` | **Refuse by name** | No live transfer (`channels/voice.md`) |
| `search_numbers`, `provision_number`, `release_number`, `bind_inbound_number`, `unbind_inbound_number` | **Refuse by name**, with the console step | Renting and attaching are console-only (`voices-and-models.md:86-87`) |
| `list_engine_numbers` | `GET /phone-numbers` | Lets our admin numbers page show what is attached; `agent` is carried as the answering agent (`voices-and-models.md:76,84-86`) |
| `set_llm_credential` | **The LLM BYOK slot**: refuse with `byok_not_documented` | Full (`scope: all`) BYOK is not used. The voice-only BYOK of the Studio rung is a separate path (§4a): our Cartesia key and `PATCH /byok {"enabled": true, "scope": "voice"}` in the Studio workspace |
| `attach_kb` / `detach_kb` / `list_kb` / `list_account_kb` | `POST`, `DELETE` and `GET /agents/{id}/knowledge`, text only (200k characters per document, `knowledge.md:52`) | We send text extracted by our own `document_text`/`document_ocr`. A longer source is split on chunk boundaries (`engine/text_split.split_for_text_cap`) into at most 10 documents (2,000,000 characters; above that it is refused with `engine_kb_text_too_long`). Each part's title carries `[cv-part i/n group]`; the handle is `cv-parts:<id>,<id>…`, which `list_kb` rebuilds from the titles and `detach_kb` removes part by part. A part refused midway removes the parts already sent and refuses with `engine_kb_part_failed` |
| `list_voices` | `GET /voices` plus `GET /models` | Tier mapping in §4 |
| `get_execution` | `GET /calls/{id}` | The 6 Oct pages answered 404 for calls the API did not place; the 7 Oct snapshot takes any call id (`snapshots/2026-10-07/pages/api-reference/calls/get-call.md:7`). The signed delivery is still read first, and the call list settles anything missed |
| `list_executions` | `GET /calls?…` with a cursor (`list-calls.md`) | Reconciliation source for inbound calls and for missed webhooks |
| `verify_webhook` | HMAC-SHA256 of the raw body with the endpoint `signingSecret`, `x-thinnest-signature: sha256=…`, constant-time compare | No timestamp, so replay protection is the inbox dedupe in §3 |
| `parse_webhook` | `call.completed` and `call.analysed` → `CallEvent` | Map `status`/`hangup` to our outcomes; transcript `{speaker, text, at}` → `TranscriptTurn` |

The capabilities descriptor must be honest. For example:
- `agent_hosting="control_plane"`;
- no transfer;
- no number provisioning;
- knowledge base as text;
- speech legs are the engine's own (`SpeechControl` = engine-dictated);
- webhook auth `hmac`.

**It must pass `packages/shared/tests/engine_conformance/`.**

## 3. Inbound path, results and reconciliation

1. **Webhook registration.** A webhook is registered per agent at publish time: `POST /webhooks` with `{agent, url: <WEBHOOK_BASE_URL>/engine/thinnest, events: ["call.completed","call.analysed"]}`.
   - The `signingSecret` is returned **once**. Store it sealed (envelope-encrypted like other credentials), keyed by agent.
   - Re-publishing must not create duplicates.
2. **voice-runtime `/engine/thinnest`.**
   - Verify the HMAC against the agent's secret, after looking up the agent from `data.agent.id` under the route table.
   - Dedupe in the inbox on `(event, data.id, attempt, analysedAt|endedAt)`.
   - Ack in under 500 ms (hard rule 3) and hand off to ARQ.
3. **Worker.**
   - Upsert the call row: `engine_call_id` = their `id`, our `reference` comes back.
   - Write the transcript (redaction as today), run our own extraction pass, and update CRM and leads.
   - Meter the minutes (§5).
   - Copy `recording.url` to R2 (90 days) once `ready`; it expires on their side after 30 or 75 days.
   - Fire our client webhooks, including `call.recording_ready`.
4. **Reconciliation sweep (required).** ThinnestAI sends each event **once** and switches an endpoint off after 5 failures (`webhooks.md:83-88`). So:
   - list calls since the last watermark and settle any we have not;
   - check each endpoint's `enabled` flag and `PATCH enabled:true` with an alarm when it was switched off.

## 4. Voices, models, language

- **Voices.** `GET /voices` returns tiers `standard`, `premium` and `studio`; Studio needs their Pro plan or above (`snapshots/2026-10-07/pages/api-reference/voices/list-voices.md:7`; the 6 Oct pages said Scale).
- **Price rungs.** Their tiers map to our price rungs only through an **operator-attested ₹/min per tier** (hard rule 7). Since D-687 their `studio` band is sold as our Clear rung and the voice-only BYOK leg as our Studio rung; `standard` and `premium` are not sold (§4a, §5). Until a rate is attested its voices are offered as unavailable, with the reason.
- **Models.** `GET /models` lists models with `voice:true` (fast enough for calls) and `available`.
- **Business facts as knowledge.** On publish (agent and experiment arm alike) the facts document is created, replaced only when the facts changed (sha256 on `engine_agent_routes.facts_digest`; the new document is attached before the old one is removed, and a failed removal removes the new one again and refuses with `engine_facts_replace_failed`), and removed when the script no longer has a facts block. Deleting the vendor agent deletes its knowledge (`agents.md:82`). The handle is recorded on `engine_agent_routes.facts_kb_ref`, and the KB publish gate and drift sweep count it as ours, under the same per-agent publish lock.
- **Per-agent choice (built).** `agents.engine_voice_id` and `agents.engine_model_id` (migration `b7e2d94f1a30`, NULL = the vendor default) are set through `PATCH /v1/agents/{id}` from the admin and client voice panels and sent as `voice.voice` and `model` (`agents.md:105-110,156`) only on a leg the engine dictates. `agents/engine_choice.py` checks them against a live `GET /voices` + `GET /models` before the vendor write, and on a draft at save time, refusing by name: `engine_voice_not_in_catalogue`, `engine_voice_tier_unpriced` (band not attested, through `engine_minute_is_billable`), `engine_voice_tier_unknown`, `engine_model_not_in_catalogue`, `engine_model_not_call_capable`, `engine_model_not_on_plan`, `engine_catalogue_incomplete`, and `engine_voice_choice_not_offered` / `engine_model_choice_not_offered` on an engine that runs our own voices or models. The route row's `engine_rate_key` is stamped from the chosen voice's band, or `platform` when none is chosen.
- **Clearing a published choice is refused** (`engine_choice_reset_unsupported`): the mirror documents no value that resets `voice.voice` or `model` to the default, so the vendor would keep the last one sent while our row and rate key said otherwise. UNVERIFIED until ThinnestAI says whether `null` resets either field: the 7 Oct request schema types both as a plain string (`snapshots/2026-10-07/pages/api-reference/agents/update-agent.md:442-450, :731-735`); the `null`s documented at :552-558 and :931-934 describe the response (a retired model, no voice channel), not a reset.
- **Language.** A Telugu agent is sent `language: "Telugu"`, the console's exact option (FOUNDER-RELAYED console reading, 6 Oct 2026; the console's "Match the customer" is the API's `"auto"`). A language outside the adapter's map is sent as `"auto"`.
- **BYOK.** A WORKSPACE setting (console: Settings → Your keys). The 7 Oct 2026 morning snapshot documented it as **all three legs or none**; that is **superseded by the evening snapshot**, which documents two scopes: `all` and `voice` (`snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys.md:13-24`; `bring-your-own-keys/turn-byok-on-or-off.md:7`). D-687 uses `voice` for the Studio rung (§4a). Full (`all`) BYOK is still not sold: `set_llm_credential` refuses (`byok_not_documented`), and `THINNEST_BYOK_ENABLED` still describes the developer workspace running on all three of its own keys (D-681). With it on, a per-agent catalogue voice or model does not apply: the pickers lock with a plain reason (`EngineCatalogueOut.choosable=false`, `choice_note`), a new choice is refused with `engine_choice_under_byok`, a stored one is not sent, and every publish stamps the `platform` rate key instead of a voice tier.
- **Voices (7 Oct 2026 snapshot).** Every voice speaks every supported language and the agent's language decides which; each voice carries an accent tag; Studio voices are listed on Pro and above (`api-reference/voices/list-voices.md:7,345`).
- **In-app catalogue prices (FOUNDER-RELAYED, not invoices).** Standard ₹2.00/min, Premium ₹2.50, Studio ₹3.00 (Scale plan: ₹1.90 / ₹2.375 / ₹2.85). Telugu Standard voices: Abirami Te, Anjura Te, Divya, Karthik, Tanvi. These are what an operator attests per tier; nothing in code holds them.

### 4a. Voices on this engine (D-687, 8 Oct 2026)

The founder's decision; it supersedes D-681's "Clear = Premium band" and "Studio on hold". Paths are under `thinnest-findings/mirror/snapshots/2026-10-07b/pages/`.

| Our rung | What speaks | Vendor rate (VENDOR-STATED) | Workspace |
|---|---|---|---|
| **Clear** | ThinnestAI's own stack end to end, in their **studio-band** voices: catalogue voices with `tier: studio` and the voices our admin clones (`mine: true`) | ₹3.00/min, plus the wallet top-up fee | Our developer workspace |
| **Studio** | Cartesia on **our** key through BYOK `scope: "voice"`; ThinnestAI's STT, LLM and telephony | ₹1.50/min including the line, plus Cartesia's own charge to our key | One shared customer workspace with voice-only BYOK on |

- **Studio band.** `GET /voices` lists `standard`, `premium` and `studio`, and `tier` is the band a call is billed at; studio voices (the shared catalogue and our clones) are listed only on **Pro** and above (`api-reference/voices/list-voices.md:7,436-451`). A clone is a studio voice at the same per-minute rate (`channels/voice-clone.md:9-12,81-89`). So Clear needs ThinnestAI Pro.
- **Clones are the admin's, never a client's.** The vendor makes cloning admin-only and records two separate consents against the voice, with who agreed and when (`channels/voice-clone.md:33-44,114-120`); our admin route sends both as explicit admin attestations and writes `audit_log`. A sample is 5 to 30 seconds, WAV, MP3, M4A or WebM (`:47-51`). Limits: **10 clones on Pro, 20 on Scale**, raised per workspace on request (`:93-99`). Deleting a clone moves every agent using it to a **standard** voice (`:103-112`), a band we do not sell, so the drift sweep must notice it.
- **Clients pick, they do not browse the vendor.** A client sees only voices the admin added to our catalogue AND enabled, with a preview. Previews are stored in our object store and served by us: a clone has a 60-second `previewUrl`, a BYOK voice has `POST /byok/voices/preview` (text capped at 200 characters, billed to our Cartesia key, `api-reference/bring-your-own-keys.md:219-232`), and a catalogue voice has none, so the admin may upload a short sample.
- **Workspaces.** BYOK is switched per workspace and a customer inherits the developer's scope (`bring-your-own-keys/turn-byok-on-or-off.md:7`; `bring-your-own-keys.md:105-109`). Clones belong to the workspace that made them, with no documented sharing (`api-reference/voices/list-voices.md:163-167`; `voice-clones/get-voice-clone.md:371-378`). So Clear agents stay in the developer workspace with the clones, and Studio agents go into ONE shared customer workspace with voice-only BYOK on and our Cartesia key installed. Its id is the console setting `thinnest_studio_workspace_id` (added by D-687); every call for a Studio agent carries `Thinnest-Workspace` (`bring-your-own-keys.md:113`). The workspace is resolved in one function, `thinnest_workspace_for(tenant_id, rung)`, so a customer workspace per tenant (evaluation §9) stays a one-function change.
- **Studio voice per agent.** `GET /byok/voices` lists what our Cartesia key reaches (`bring-your-own-keys.md:200-217`) and `PUT /agents/{id}/byok-voice` sets the agent's voice (`:255-258`; `agents/set-agent-byok-voice.md:7`).
- **Model on a Studio call.** With voice-only BYOK the call minute includes their model, so a call runs only on their low-cost models (Prana, Prana [Voice], GPT-OSS 120B, GPT-5 Nano, GPT-4.1 Nano today; `GET /models` marks `voiceOnlyByok`); setting another model returns 400, and an agent already on another model runs GPT-OSS 120B on calls (`bring-your-own-keys.md:44-63`). A Studio agent's model choice is therefore narrower than a Clear agent's.
- **No fallback.** If our Cartesia key fails, the voice does not speak; their own STT and LLM keep their usual backups (`bring-your-own-keys.md:98-103`).
- **Rung switch.** Agents cannot move between workspaces (VENDOR-STATED, evaluation §10 item 2b), so changing an agent's rung deletes the vendor agent in one workspace and creates it in the other on republish. A number cannot follow, so a rung switch is **refused** on an agent that holds a number.
- **Gnani is not used on this engine.** No ThinnestAI surface, label or price names it.

## 5. Money

ThinnestAI returns **no per-call cost** (`get-call.md:199-204`). Metering works as follows:
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
| `THINNEST_STUDIO_WORKSPACE_ID` (`thinnest_studio_workspace_id`) | console-managed, added by D-687 | The one shared customer workspace that holds every Studio agent, with voice-only BYOK and our Cartesia key. Set by `POST /v1/ops/voices/studio-workspace` (creates the workspace and installs the key) or by hand; an `org_…` id. Unset: Studio is not offered, and publishing a Studio agent is refused with a plain reason |
| Per-minute rates (`platform`, `standard`, `premium`, `studio`, `byok_voice`) | ops console **Per-minute rates**, attested with step-up | Hard rule 7. `studio` is sold as Clear and `byok_voice` (voice-only BYOK) as Studio (D-687); `standard` and `premium` are not sold |
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
  unpublish, and checked by the drift sweep. **UNVERIFIED:** which call an action belongs
  to (no placeholder or header is documented, gate T-4); the call is matched from the
  agent's secret plus the caller's number against a live call. No live transfer: the
  hand-over is recorded, not bridged.
- **Call lifecycle and money (phase 2).** Dispatch is held to `thinnest_max_concurrent_calls`
  (`engine/carrier_pacing.py`); a delivery whose signed `sentAt` is more than 5 minutes
  from our clock is ignored (`voice-runtime/signed_intake.REPLAY_TOLERANCE`);
  the usage call log's per-call charge is compared with what we metered and alarmed on a
  difference (`workers/engine_charges.py`), never written as a correction (hard rule 4);
  recordings are copied from the engine with its documented retention
  (`engine/recording_source.py`).
- **Product surfaces (phase 2).** The rate card says, per deployment, which voice no agent
  can be put on (`CreditPacksOut.voice_not_offered`, `billing/payment_routes.
  voice_tier_not_offered`): on this engine, Studio until the Studio workspace is ready
  (D-687; it was always Studio under D-681), and the cheaper rung on our own voices.
  `/pricing` leads with the voice that can be bought; the client "What calls cost", the
  public rate card and the ROI calculator print the server's sentence. The ops
  per-minute rate panel says which rate a client is sold (`sold_as`). Number purchase
  and transfer settings render the server's own refusals and reasons on this engine;
  client copy names no provider (D-679), held by `publicVendorNames.test.ts`.
- **Readiness and configuration (phase 2).** §7.
- **Docs.** OPERATIONS §2 T-series (questions for ThinnestAI), FLOWS §3a, this file, and
  `runbooks/thinnest-first-live-call.md`.

- **Voices (D-687).** §4a: the studio band and admin clones as Clear, voice-only BYOK
  Cartesia as Studio in one shared customer workspace, admin clone and preview routes, the
  client picker limited to admin-enabled voices. The code is in `apps/api` (the D-687 row of
  `docs/ROADMAP.md` names the files).

**Decided (D-687):** Clear agents in the developer workspace and Studio agents in one shared
customer workspace, resolved by `thinnest_workspace_for(tenant_id, rung)`. A customer
workspace per tenant (`docs/evidence/thinnest-ai-evaluation.md` §9, gate T-8) stays a
founder decision and is a change to that one function. Decided: ThinnestAI's own numbers
only on this engine.

**Gates that stay open, needing ThinnestAI's answers:** OPERATIONS §2 T-1..T-10 (T-1, BYOK
per leg, is answered by the 7 Oct evening snapshot: scopes `all` and `voice`) — whether `null` resets `voice.voice` or `model`, the webhook replay
window and redelivery, the action timeout and call identification, the DPA and training,
Telugu quality, the concurrency raise, customer workspaces, the DLT roles on our numbers,
and per-band prices on an invoice.
