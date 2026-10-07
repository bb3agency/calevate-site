# ThinnestAI engine: integration plan (D-678)

## Status

- **Decided 6 Oct 2026 by the founder.**
- **Phase 1 built 6 Oct 2026; phase 2 (D-682) built 7 Oct 2026** against the 7 Oct snapshot of their docs (`thinnest-findings/mirror/snapshots/2026-10-07/pages/`). No real ThinnestAI call has been placed; `runbooks/thinnest-first-live-call.md` is the founder's checklist for the first one.

The founder decided three things:

1. ThinnestAI becomes a third selectable voice engine, `ENGINE=thinnest`, behind the existing **deployment-wide** switch.
2. ThinnestAI's own numbers are used: rented and attached in their console. Confirmed 7 Oct 2026: Vobiz is isolated to `ENGINE=pipecat`, bringing a carrier account to ThinnestAI is not used, by decision, and a move back to Pipecat would give clients new numbers (no portability between engines).
3. Voices and models come from their catalogue now, with a clearly marked slot for BYOK once ThinnestAI documents how it works.

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
| STT / LLM / TTS | Sarvam / Gemini-Azure-OpenAI / Cartesia-Gnani, our keys | Their catalogue (`GET /models`, `GET /voices`), or the workspace's own keys (BYOK, console-only; see §4) |
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
| `set_llm_credential` | **The BYOK slot**: refuse with `byok_not_documented` until ThinnestAI documents it | One marked place to change |
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
- **Price rungs.** Their tiers map to our price rungs only through an **operator-attested ₹/min per tier** (hard rule 7). Since D-681 only the Premium tier is sold, as our Clear rung; Standard and Studio are shown and refused (§5). Until a tier is attested its voices are offered as unavailable, with the reason, through the existing offer-seam pattern (`agents/voice_offer.py`).
- **Models.** `GET /models` lists models with `voice:true` (fast enough for calls) and `available`.
- **Business facts as knowledge.** On publish (agent and experiment arm alike) the facts document is created, replaced only when the facts changed (sha256 on `engine_agent_routes.facts_digest`; the new document is attached before the old one is removed, and a failed removal removes the new one again and refuses with `engine_facts_replace_failed`), and removed when the script no longer has a facts block. Deleting the vendor agent deletes its knowledge (`agents.md:82`). The handle is recorded on `engine_agent_routes.facts_kb_ref`, and the KB publish gate and drift sweep count it as ours, under the same per-agent publish lock.
- **Per-agent choice (built).** `agents.engine_voice_id` and `agents.engine_model_id` (migration `b7e2d94f1a30`, NULL = the vendor default) are set through `PATCH /v1/agents/{id}` from the admin and client voice panels and sent as `voice.voice` and `model` (`agents.md:105-110,156`) only on a leg the engine dictates. `agents/engine_choice.py` checks them against a live `GET /voices` + `GET /models` before the vendor write, and on a draft at save time, refusing by name: `engine_voice_not_in_catalogue`, `engine_voice_tier_unpriced` (band not attested, through `engine_minute_is_billable`), `engine_voice_tier_unknown`, `engine_model_not_in_catalogue`, `engine_model_not_call_capable`, `engine_model_not_on_plan`, `engine_catalogue_incomplete`, and `engine_voice_choice_not_offered` / `engine_model_choice_not_offered` on an engine that runs our own voices or models. The route row's `engine_rate_key` is stamped from the chosen voice's band, or `platform` when none is chosen.
- **Clearing a published choice is refused** (`engine_choice_reset_unsupported`): the mirror documents no value that resets `voice.voice` or `model` to the default, so the vendor would keep the last one sent while our row and rate key said otherwise. UNVERIFIED until ThinnestAI says whether `null` resets either field: the 7 Oct request schema types both as a plain string (`snapshots/2026-10-07/pages/api-reference/agents/update-agent.md:442-450, :731-735`); the `null`s documented at :552-558 and :931-934 describe the response (a retired model, no voice channel), not a reset.
- **Language.** A Telugu agent is sent `language: "Telugu"`, the console's exact option (FOUNDER-RELAYED console reading, 6 Oct 2026; the console's "Match the customer" is the API's `"auto"`). A language outside the adapter's map is sent as `"auto"`.
- **BYOK.** A WORKSPACE setting (console: Settings → Your keys). Since the 7 Oct 2026 snapshot it also has an API (`api-reference/bring-your-own-keys.md:85-152`) and a per-agent BYOK model and voice (`api-reference/agents/set-agent-byok-*.md`); a customer workspace may hold its own set (`bring-your-own-keys.md:74-76`). It is still **all three legs or none** (`:18-19`; `agents/set-agent-byok-voice.md:155-157`) with no fallback to their providers (`:68`); calls are then ₹1/min all-in. Gnani is not a voice provider (`:56`), and Azure OpenAI goes in as an OpenAI-compatible URL (`:62-63`). We do not drive the BYOK API: BYOK calls are not on sale (D-681), so `set_llm_credential` still refuses (`byok_not_documented`, the one marked place to change), and an operator who has configured the keys sets the console-managed `THINNEST_BYOK_ENABLED` (needs republish). With it on, a per-agent catalogue voice or model does not apply: the pickers lock with a plain reason (`EngineCatalogueOut.choosable=false`, `choice_note`), a new choice is refused with `engine_choice_under_byok`, a stored one is not sent, and every publish stamps the `platform` rate key (the ₹1 BYOK rate) instead of a voice tier.
- **Voices (7 Oct 2026 snapshot).** Every voice speaks every supported language and the agent's language decides which; each voice carries an accent tag; Studio voices are listed on Pro and above (`api-reference/voices/list-voices.md:7,345`).
- **In-app catalogue prices (FOUNDER-RELAYED, not invoices).** Standard ₹2.00/min, Premium ₹2.50, Studio ₹3.00 (Scale plan: ₹1.90 / ₹2.375 / ₹2.85). Telugu Standard voices: Abirami Te, Anjura Te, Divya, Karthik, Tanvi. These are what an operator attests per tier; nothing in code holds them.

## 5. Money

ThinnestAI returns **no per-call cost** (`get-call.md:199-204`). Metering works as follows:
- **Billed minutes:** `ceil(seconds / 30) × 0.5`.
- **Rate:** an operator-attested `THINNEST_INR_PER_MIN`, in NUMERIC INR and console-managed, plus a per-tier rate if we use their voices.
- **Meaning of ₹1/min:** BYOK including telephony. Their own models are ₹1.5 or ₹2.5 (FOUNDER-RELAYED).
- **Unit cost:** `unit_cost_paid` = billed minutes × attested rate.
- **No rate, no sale:** an unattested rate refuses to sell the minute, exactly as the LLM price door does today.
- **Client billing (D-681):** the client is billed in the same 30-second steps on every engine (`rates.client_billed_minutes`), separately from this cost metering.
- **What is sold (D-681):** only Premium-band voices, as the Clear rung (₹4.00 on every pack). Standard and Studio voices are refused ("This voice is not on offer yet"), and publish refuses an agent with no voice chosen (`engine_voice_required`) and the workspace-keys mode (`engine_own_keys_not_on_sale`). The client rung comes from the stamped `engine_agent_routes.engine_rate_key`, never from `agents.tts_voice`.
- **Cost floors (D-681):** the Clear floor on this engine is ₹2.50 Premium × 1.10 wallet top-up fee = **₹2.75/min** (`rates.THINNEST_CLEAR_COST_FLOOR_INR_PER_MIN`, FOUNDER-RELAYED §2a), and the card is judged against it on `ENGINE=thinnest` (31.3% at ₹4.00). The floors were built on Pipecat's ₹0.95 engine leg, not Bolna's ₹1.76. A floor is a margin guard and never the billed cost.
- **Studio is ON HOLD** pending ThinnestAI's answer on per-sub-workspace BYOK. No BYOK-Studio routing is built.

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
| `THINNEST_BYOK_ENABLED` | console-managed (needs republish), default off | The workspace runs on its own keys; such calls are not on sale (D-681) |
| Per-minute rates (`platform`, `standard`, `premium`, `studio`) | ops console **Per-minute rates**, attested with step-up | Hard rule 7; only `premium` is sold, as Clear (`sold_as`, D-681) |
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
  voice_tier_not_offered`): Studio on this engine, the cheaper rung on our own voices.
  `/pricing` leads with the voice that can be bought; the client "What calls cost", the
  public rate card and the ROI calculator print the server's sentence. The ops
  per-minute rate panel says which rate a client is sold (`sold_as`). Number purchase
  and transfer settings render the server's own refusals and reasons on this engine;
  client copy names no provider (D-679), held by `publicVendorNames.test.ts`.
- **Readiness and configuration (phase 2).** §7.
- **Docs.** OPERATIONS §2 T-series (questions for ThinnestAI), FLOWS §3a, this file, and
  `runbooks/thinnest-first-live-call.md`.

**Open, for the founder:** one ThinnestAI workspace for every tenant (today) or a customer
workspace per tenant (`docs/evidence/thinnest-ai-evaluation.md` §9, gate T-8). Decided:
ThinnestAI's own numbers only on this engine.

**Gates that stay open, needing ThinnestAI's answers:** OPERATIONS §2 T-1..T-10 — BYOK per
leg and per customer, whether `null` resets `voice.voice` or `model`, the webhook replay
window and redelivery, the action timeout and call identification, the DPA and training,
Telugu quality, the concurrency raise, customer workspaces, the DLT roles on our numbers,
and per-band prices on an invoice.
