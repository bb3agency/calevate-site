# ThinnestAI docs snapshot of 13 Oct 2026, checked against Ashutosh's 13 Oct email

The snapshot is `thinnest-findings/mirror/snapshots/2026-10-13/`. It is a full re-fetch of every `.md` link in
`https://docs.thinnest.ai/llms.txt`. The UTC run was 15:17–15:22, and `generated_at` is in its
`MANIFEST.json`. 282 of 282 pages were fetched with 0 failures, and every page was served as
`text/markdown`. As before, the example account id of the form `AC` + 32 hex was masked at fetch
time to the same byte length. That is one file, `api-reference/phone-numbers/save-carrier-account.md`,
at lines 430 and 534, and the manifest hashes are of the masked file.

Against `2026-10-08/`: 11 pages added, 0 removed, 212 changed. The added pages are
`api-reference/contact-groups/*` (7), `api-reference/phone-numbers/move-phone-number` and
`whats-new/{index,early-october,late-september}`. `whats-new/index.md` is the vendor's changelog
for 6–13 Oct and lists most of the items below.

The claims checked are those in `docs/vendor/thinnest-replies-2026-10-12.md` §11.1–§11.2 (**VENDOR-STATED**).
Every path below is under `thinnest-findings/mirror/snapshots/2026-10-13/pages/`, and everything
quoted here is **VERIFIED-VENDOR-DOCS** as of 13 Oct 2026.

## Verdicts

| Claim (email) | Verdict | Evidence |
|---|---|---|
| `PUT /api/v1/byok/credentials/llm` with provider `google` and a model | **CONTRADICTED (path).** The key is added with `PUT /api/v1/byok/credentials` and a body of `{kind: "llm", provider, credentials: {apiKey, model}}`. `PATCH /api/v1/byok/credentials/llm` exists, but it only changes the model or refreshes the list. `google` is a listed LLM provider. | `api-reference/bring-your-own-keys.md:227-238`, `:250-259`, `:156`; `api-reference/bring-your-own-keys/add-byok-key.md:399-430`, `:561-601` |
| `PATCH /api/v1/byok {scope:"llm", enabled:true}` | **CONFIRMED.** The scope enum is `all`, `voice`, `llm` and `llm_voice`. | `api-reference/bring-your-own-keys/turn-byok-on-or-off.md:399-417`, `:542-555`; `api-reference/bring-your-own-keys.md:264-274` |
| Scope `llm` is inherited by customer workspaces like `voice` | **CONFIRMED.** Customers use the developer's keys and scope unless they hold a complete set of their own. `using` reads `developer`. | `api-reference/bring-your-own-keys.md:180-184`, `:219-221`; `turn-byok-on-or-off.md:415-417` |
| Can an agent opt out of an inherited llm key? (email: not stated) | **ANSWERED: yes.** The agent's `byok` is `null`/`workspace`, `off`, `all`, `voice`, `llm` or `llm_voice`. `off` puts that one agent on ThinnestAI's voices, models and pricing. A scope the keys cannot serve is refused with `409`. If a key is later lost, the agent falls back to the workspace scope at the next call. | `api-reference/agents/update-agent.md:746-768`; `api-reference/bring-your-own-keys.md:80-125`, `:421-447` |
| Price of scope `llm`: the normal voice plan, nothing extra for the model; chat ₹0.02 | **CONFIRMED.** | `api-reference/bring-your-own-keys.md:21-24`, `:28-33` |
| ₹1/min only with all three keys; voice-only ₹1.50 | **CONTRADICTED / superseded.** A new scope, `llm_voice` (our LLM key and our voice key, their recogniser), is a flat **₹1.00/min** with chat at ₹0.02. This answers §11.5 question 1. Voice-only stays ₹1.50 ($0.02). | `api-reference/bring-your-own-keys.md:18-20`, `:26-29`; `whats-new/index.md:16-21` |
| Top-ups 2.36% | **NOT MENTIONED.** "2.36" appears nowhere in the snapshot. | — |
| No backup model on our own keys; the caller hears an apology | **CONFIRMED.** "There is no fallback to our providers". Under scope `llm`, "the caller hears our apology and the call is flagged". The exact wording of the apology is not given. | `api-reference/bring-your-own-keys.md:171-178`, `:53-54` |
| `call.problem` `kind: byok_failed`, once per call | **CONFIRMED.** It fires at most once per kind per call. The payload is `{callId, agentId, kind, detail, at}`. | `api-reference/webhooks.md:86`, `:99-132` (`:127`) |
| A critical `byok.failed` notification naming the reason | **PARTLY CONFIRMED; no such webhook event.** The docs say "a notification naming the provider and the reason, at most once a day per provider" (an in-app notification). Notifications have a **Connections** category for own provider keys failing. `byok.failed` appears nowhere in the snapshot, and the subscribable events are `lead.captured`, `conversation.escalated`, `conversation.resolved`, `call.completed`, `call.analysed`, `campaign.finished`, `contact.opted_out` and `call.problem`. Whether the notification is "critical" is UNKNOWN. This answers §11.5 question 4: **no subscribable `byok.failed`**, so use `call.problem`/`byok_failed`. | `api-reference/bring-your-own-keys.md:174-175`; `workspace/notifications.md:30`, `:34-35`; `api-reference/webhooks.md:77-86` |
| Thinking levels (Gemini 3 `minimal`, 3 Pro `low`, 2.5 Flash/Flash-Lite off, 2.5 Pro smallest budget) | **PARTLY CONFIRMED.** The docs say only that a Gemini 2.5 or 3 model "is asked to think less", and that a Pro model, which cannot switch thinking off, is asked for the least it allows. Chat replies are unchanged. The per-model levels are UNKNOWN. | `api-reference/bring-your-own-keys.md:167-169`; `whats-new/index.md:120-121` |
| `PUT /agents/{id}/byok-model`, any model the key offers | **CONFIRMED.** The model must be one the key reaches (`byok.models` on List Models), and `null` returns to the key's model. `gemini-2.5-flash-lite` is not named, nor is any specific model. Temperature on calls is NOT MENTIONED in the BYOK pages. | `api-reference/agents/set-agent-byok-model.md:399-418`; `api-reference/bring-your-own-keys.md:311-330` |
| `maxReplyTokens` on calls (§11.5 q6) | **ANSWERED: applies "for chat and calls alike"**, clamped to 100–800. This text was already present in `2026-10-08` (`update-agent.md:558`). | `api-reference/agents/update-agent.md:703-709` |
| byok-voice: speed 0.6–1.5, volume 0.5–2.0, emotion (English only), Sonic model incl. `sonic-3.6`, pronunciation dictionary id | **CONFIRMED.** The field is `pronunciationDictId`. `model` takes `sonic-3.6`, `sonic-3.6-2026-08-27`, `sonic-3.5`, `sonic-3` or `sonic-2`. The defaults are speed 1, volume 1, emotion "the words decide", model = the key's model and dictionary none. | `api-reference/bring-your-own-keys.md:362-407`; `api-reference/agents/set-agent-byok-voice.md:425-440`, `:587-627` |
| A PATCH that omits them keeps them | **CONFIRMED, but the method is `PUT`** (`PUT /agents/{id}/byok-voice`, partial semantics). `null` resets a field. Sending a setting before a voice is chosen, or with `voice: null`, is refused. `GET` returns the agent's own model as `agentModel`. | `api-reference/bring-your-own-keys.md:388-395`; `set-agent-byok-voice.md:431-440` |
| Speed not on a Professional Voice Clone; speed, volume and emotion refused on Sonic 2 | **CONFIRMED.** A refusal is `400 code: validation_failed` with `field`. If the key's model later becomes `sonic-2`, they are "simply not sent". | `api-reference/bring-your-own-keys.md:399-403`, `:392-393` |
| `POST /byok/voices/preview` plays a setting before saving | **CONFIRMED.** It takes the same fields, "only the fields you send are spoken; the agent's saved settings are not read". It returns audio (`audio/mpeg`, or `audio/wav` for Sarvam), and `text` is capped at 200 characters. | `api-reference/bring-your-own-keys.md:296-309`, `:409-419`; `api-reference/bring-your-own-keys/preview-byok-voice.md:399`, `:539-561` |
| Settings sent on every speech request | **NOT MENTIONED** in those words. A call that names its own voice in `overrides` keeps the agent's settings. | `api-reference/bring-your-own-keys.md:406` |
| `voice.turnDetection`: `smart`, `timer` or `ear`; platform default Timer | **CONFIRMED.** `null` follows the platform's setting, which is "Timer today", and a read shows `null` until one is chosen. `ear` falls back to `timer` where the recogniser cannot mark end-of-speech. | `api-reference/agents/update-agent.md:1349-1369`; `channels/voice.md:871-884` |
| `turnSilenceSeconds`: the silence that ends a turn in Timer (0.25 s), a ceiling in Smart (0.6 s) | **CONFIRMED.** The range is 0.2–3, and out of range is a 400 on the API. | `api-reference/agents/update-agent.md:1370-1381`; `channels/voice.md:886-895` |
| `voice.recordDoNotCall` turns their DNC tool off per agent | **CONFIRMED.** Boolean, **default `true`**. Numbers added by API or console are unaffected. | `api-reference/agents/update-agent.md:1168-1175`; `whats-new/index.md:94-97` |
| `contact.opted_out` carries the caller's words as `reason` | **CONFIRMED.** `data` is `{phone, callId, source:"call", optedOutAt, reason}`, where `reason` is up to 160 characters in the caller's language, or `null`. | `api-reference/webhooks.md:85`, `:496-513` |
| DNC tool asks first; "that's all, you can hang up" excluded | **CONFIRMED.** | `whats-new/index.md:105-107` |
| `callInstructions` replaces only the 16 speaking rules; hang-up, interruption, clock and DNC rules stay | **PARTLY CONFIRMED.** It "REPLACES the built-in call rules" and is added after the agent's instructions, with a maximum of 4,000 characters (longer is a 400, never cut). Which rules survive is NOT MENTIONED. The rules' text is not in the docs: the console box "comes filled in", but `GET` returns `callInstructions: null` "for the built-in call rules". §11.5 q5 stays open. | `api-reference/agents/update-agent.md:1505-1516`; `api-reference/agents/get-agent.md:1149-1153`; `channels/voice.md:162-191` |
| Text that is not speech is stripped before speech and saving | **CONFIRMED.** | `channels/voice.md:178-183`; `whats-new/index.md:112-115` |
| Interruptions: a cut-off turn is trimmed to what was heard; the glued-retry bug is fixed | **CONFIRMED.** That a sentence may already be synthesised on our Cartesia account is NOT MENTIONED. | `whats-new/index.md:108-110`, `:126-127` |
| Goodbyes in Te/Ta/Kn/Ml/Bn/Mr; fallback lines in Hindi and Telugu | **CONFIRMED.** | `whats-new/index.md:116-119` |
| Voice-only BYOK with a disallowed model runs on GPT-OSS 120B | **CONFIRMED in prose, CONTRADICTED in the OpenAPI tag text.** The prose says "runs on GPT-OSS 120B on calls". The BYOK tag description embedded in every API page says "an agent on any other model runs on Prana on calls". The vendor's docs disagree with themselves, so this is UNKNOWN until asked. The allowed list is now Prana, Prana [Voice], GPT-OSS 120B, GPT-5 Nano and GPT-4.1 Nano, plus any cheap-enough model marked `voiceOnlyByok`. | `api-reference/bring-your-own-keys.md:56-78`; `api-reference/agents/update-agent.md:179-181` |
| Test chat `tools[].output.result` is our body as a raw string, cut at 4,000 characters | **CONTRADICTED / NOT MENTIONED.** `TestChatToolUse` is `{name, input, output, error}`. `output` is untyped ("What it answered, when it succeeded"), and the example's `output` is a plain string. No `result` sub-field and no 4,000-character cut on `output` are documented. The only 4,000 limit is on the request `message`. Our parser reading `output` itself matches the docs. | `api-reference/agents/test-chat.md:449-453`, `:577-581`, `:703-718` |
| Test chat replies in the customer's script with "Match the customer" | **CONFIRMED.** | `whats-new/index.md:98-101` |
| Per-call token usage, including our own keys (§11.5 q3) | **ANSWERED: yes.** Get Call and `call.analysed` carry `usage {inputTokens, outputTokens, cachedInputTokens}`, "whether the model is ours or your own key's (BYOK)". The input count is estimated where a provider reports none ("a close guide rather than an invoice"). The post-call summary and extraction are not counted. | `api-reference/calls/get-call.md:1105-1135`, `:322-325`; `whats-new/index.md:30-33` |
| Greeting latency 1.0–1.1 s → 0.4–0.5 s | **NOT MENTIONED.** | — |
| Telugu recogniser is Sarvam; recogniser per agent only with all three keys | **NOT MENTIONED** in the BYOK or voice pages checked. | — |

## Other priority pages

- **`voice.surfaces`.** This takes `phone`, `web` and `whatsapp`. A new agent starts on `["web","whatsapp"]`, and `phone` is added when a number is attached. Adding `phone` with no number is a `400` (`phone_number_required`) (`api-reference/agents/update-agent.md:1269-1281`, `:1695-1707`, `:566-578`; `channels/voice.md:55`).
- **Phone number rental.** `POST /phone-numbers` takes only the `Thinnest-Workspace` parameter, and **no `Idempotency-Key` is documented** for it. That header is documented only on `place-call` and `place-batch-calls`. Rent charges the first month at once. It refuses with `402` when the balance cannot cover the rent, and with `409` when the number is taken or Indian business details are not approved (`api-reference/phone-numbers/rent-phone-number.md:399-437`, `:449-478`; `api-reference/calls/place-call.md:418`).

## What still goes to the next email

1. The Prana or GPT-OSS 120B contradiction for voice-only BYOK on a disallowed model.
2. The text of the built-in call rules, and which rules survive `callInstructions`.
3. The exact Gemini thinking level per model.
4. The 4,000-character / `output.result` shape in test chat: the docs show neither.
5. The 2.36% top-up fee.
6. Idempotency on rent.
