# Bolna Platform, Changelog & API-Surface Audit — EVIDENCE ARTIFACT

Audit of Calevate against Bolna's **real** documentation, mirrored read-only at
`bolna-findings/mirror/pages/`. Scope of this lane: the 21 changelog pages + 1 self-hosted
changelog, `api-reference/{introduction,pagination,rate-limiting,errors,limits}.md`, the 7
`concepts/` pages, and the root pages (`index`, `introduction`, `platform-concepts`,
`frequently-asked-questions`, `getting-help`). Every page was read end to end.

**Evidence rule observed throughout**: every claim below cites
`bolna-findings/mirror/pages/<path>` and quotes the line. Where the vendor is ambiguous or
contradicts itself, that is reported as ambiguity — never resolved by guessing (D-31,
D-32, D-350 exist because vendor prose was once read as specification).

> `bolna-findings/**` is read-only evidence and was not modified by this audit. (One
> accidental `ruff format .` run reformatted Python blocks inside nine mirrored `.md`
> files; it was reverted with `git checkout -- bolna-findings/` and the tree is clean.
> **Do not run repo-wide `ruff format` while the mirror is present** — it rewrites the
> vendor's verbatim text that every lane cites by line number.)

---

## 1. THE TIMELINE

Every dated vendor change that touches something this repository depends on: cost/billing
fields, the execution status enum, provider credentials, knowledge bases, webhooks,
pagination, residency, concurrency, or an API deprecation. Newest first. Rows marked **⚠**
changed a fact this repo had recorded; rows marked **→** are opportunities or handoffs.

### 2026

| Date | Change | Why it matters to us |
|---|---|---|
| 19 Aug 2026 | Cartesia Sonic 3.6 beta (`sonic-preview`), 42 languages. "Sonic 3.5 remains the recommended choice for production agents while 3.6 is in beta" (`changelog/august-2026.md:12-14`) | Not our TTS (D-36 = Sarvam) |
| 12 Aug 2026 | ElevenLabs `eleven_v3_conversational`, 74 languages incl. Telugu. "`speed`, `style` and `similarity_boost` have no effect on v3, and `temperature` maps to three stability presets" (`august-2026.md:22-26`) | Not our TTS |
| **10 Aug 2026** | **Sarvam `saaras:v4` transcriber** — "the latest Saaras speech-to-text model, transcribing directly in the original spoken language with automatic language detection support. Supports all 11 Indian languages" (`august-2026.md:34`) | **→ Speech lane.** D-36 pins Saaras; v4 now exists and is newer than anything this repo names |
| 6 Aug 2026 | Bolna in viaSocket app directory (`august-2026.md:39-53`) | None |
| 5 Aug 2026 | MCP server covers batches, numbers, dispositions, SIP, sub-accounts (`august-2026.md:56-70`) | None (we integrate by REST) |
| 3 Aug 2026 | Maya `Maya 2 Native` TTS, 11 Indian languages, 2 voices (`august-2026.md:74-81`) | Not our TTS |
| 31 Jul 2026 | Docs search over MCP / `bolna docs search` CLI (`july-2026.md:12-19`) | None |
| 23 Jul 2026 | Web Call SDK `@bolna/web-call` beta, on request (`july-2026.md:25-35`) | None |
| 19 Jul 2026 | Bolna CLI public beta (`july-2026.md:41-67`) | None |
| 17 Jul 2026 | Bolna MCP server, `https://mcp.bolna.ai/api/mcp` (`july-2026.md:71-91`) | None |
| 16 Jul 2026 | GPT-5.6 (Sol/Terra/Luna) + GPT-5.5 Pro; "`gpt-5.5-pro` … its latency makes it unsuitable for real-time calls" (`july-2026.md:97`) | None — D-410 pins Azure OpenAI |
| 9 Jul 2026 | Graph agents: per-language `static_message` map (`july-2026.md:105`) | Graph agents unused (see §5) |
| **7 Jul 2026** | **Webhooks filterable by call status** — "choose which call statuses trigger your webhook… Use **Trigger on statuses**… By default, **all statuses** are sent" (`july-2026.md:119-125`) | **→ Opportunity.** We currently receive every transition and drop most; see §4.3 |
| 2 Jul 2026 | Graph agent router nodes (`july-2026.md:133-135`) | Graph agents unused |
| **29 Jun 2026** | **Per-account concurrency for sub-accounts** — `min_concurrency` ("concurrency guaranteed to an account even when the organization is at capacity") and `max_concurrency` ("the account's hard cap; leave it unset for an **elastic** account… or set `0` to pause it") (`june-2026.md:12-19`) | **→ Founder decision, §7.1.** This is engine-enforced per-tenant concurrency — the thing `campaign_dispatch` reimplements in SQL |
| 27 Jun 2026 | Soniox `stt-rt-v5` streaming transcriber, native code-switching (`june-2026.md:25-34`) | Speech lane FYI (Hinglish/code-mix) |
| 23 Jun 2026 | Graph agents: `variable_types`, per-node tool scoping (`june-2026.md:38-64`) | Graph agents unused |
| 22 Jun 2026 | Graph agent visual editor (`june-2026.md:68-72`) | Graph agents unused |
| **19 Jun 2026** | **Pre-call webhook on the built-in Transfer Call tool** — `pre_call_webhook_param` / `pre_call_webhook_url`; "fire-and-forget, so a slow or failing endpoint never blocks the transfer" (`june-2026.md:78-87`) | → Transfer/compliance lane |
| **18 Jun 2026** | **KB: global `rag_config` for graph agents; `vector_ids` (plural) searches several collections at once** (`june-2026.md:91-104`) | → KB/RAG lane (T0–T4 tiers) |
| 13 Jun 2026 | Studio — agent generation from a brief (`june-2026.md:110-121`) | None |
| **12 Jun 2026** | **Pre-call webhooks on custom function tools** (`june-2026.md:127-136`) | → Tooling lane |
| 5 Jun 2026 | Bolna Skills for AI coding assistants (`june-2026.md:142-159`) | This repo already pins `bolna-ai/skills@28b24aa` as an OAS source |
| 26 May 2026 | Custom `X-` SIP headers → prompt variables on inbound BYOT (`may-2026.md:12-16`) | None (no SIP trunk) |
| 25 May 2026 | Large CSV exports become async + emailed link (`may-2026.md:24-28`) | None (we export ourselves) |
| 21 May 2026 | Transfer a phone number between sub-accounts (`may-2026.md:34-36`) | → if sub-accounts adopted (§7.1) |
| 20 May 2026 | "Ignore user speech before welcome message" to all accounts (`may-2026.md:44`) | → interacts with our disclosure-first opening (hard rule 5) |
| 19 / 18 May 2026 | Call-history phone-number search; multi-select filters; execution detail view (`may-2026.md:52,60-63`) | None |
| 13 May 2026 | Prompt editor: typed chips, token counter; "Inserting a module from the prompt library copies its content directly… No live link is kept" (`may-2026.md:73`) | None (we compose prompts) |
| 12 May 2026 | SIP trunks over TCP/TLS + audio encryption (`may-2026.md:84`) | None |
| **11 May 2026 ⚠** | **BREAKING CHANGE — recording URLs moved to a Bolna-hosted endpoint. Deadline 1 June 2026, ALREADY PAST.** "Direct Amazon S3 recording URLs will stop working after **June 1, 2026**" (`may-2026.md:91`). New: `https://api.bolna.ai/recordings/call/{execution-id}` and `/recordings/transfer/{execution-id}` (`:99-101`). "The Bolna endpoint is permanent and stable. The **resolved pre-signed link it returns expires after 24 hours** — do not store or cache it" (`:118`) | **⚠ §4.2 — we survive it, but a code comment asserted the opposite. Corrected.** |
| 8 May 2026 | OpenAI Realtime transcriber GA on `gpt-realtime-whisper`; "`effort` parameter renamed to `delay`" (`may-2026.md:143`) | None |
| 6 May 2026 | Deepgram Flux (`flux-general-en`, `flux-general-multi`), built-in turn detection, `eot_threshold` / `eot_timeout_ms` (`may-2026.md:156-166`) | Speech lane FYI |
| **5 May 2026 →** | **Custom HTTP headers on the execution webhook** — "Toggle **Add headers**… provide a JSON object of header key-value pairs — Bolna will include them on every webhook delivery for that agent… easier to authenticate webhook requests against your own services (for example, by sending an `Authorization` token, an API key, or a tenant identifier)" (`may-2026.md:174-176`) | **→ §4.3. The one real webhook-trust upgrade available to us.** Not a signature; a shared secret we choose |
| 4 May 2026 | Graph Agents launched (`may-2026.md:186-192`) | See §5 (we use conversation agents, correctly) |
| 29 Apr 2026 | Conversation rating 1–4 + notes, "stay internal to your team" (`april-2026.md:12-14`) | None |
| 22 Apr 2026 | Import custom functions from cURL (`april-2026.md:22`) | None |
| 15 Apr 2026 | `reasoning_content` on LLM rows in `GET /executions/{id}/raw_logs` (`april-2026.md:30`) | ⚠ Reasoning text is model output over a transcript — treat as PII-bearing if ever fetched (hard rule 6) |
| **14 Apr 2026** | **Extraction gains `confidence` (0.0–1.0), `confidence_label` (High ≥0.8 / Medium ≥0.5 / Low <0.5), `reasoning_subjective`, `reasoning_objective`, and Expected-Format validation (`timestamp`/`numeric`/`boolean`/`email`/custom regex) with a `validation` field** (`april-2026.md:40-42`) | **→ Extraction/CRM lane.** A confidence score is exactly what a human-review queue needs |
| 14 Apr 2026 | Multilingual agents: per-language prompt/STT/TTS (`april-2026.md:61`) | → Telugu-first product |
| 13 Apr 2026 | Region-based Indian phone number search (`april-2026.md:69`) | → numbers lane |
| 7 Apr 2026 | Unified voice selector (`april-2026.md:77-83`) | None |
| **26 Mar 2026 ⚠** | **`ambient_noise_track` now takes an ambient-sound record ID, not a preset-name enum** — "`ambient_noise_track` now accepts the **id** of an ambient sound record instead of a preset name enum"; the three presets keep the same IDs (`march-2026.md:16-24`) | We send no ambient config — verified, no impact |
| **24 Mar 2026** | **Extractions launched.** Shape: `extracted_data → {Category → {Extraction Name → {subjective, objective}}}` (`march-2026.md:45-56`) | Our first extraction stays on Sarvam permanently (CLAUDE.md §3), so this is a comparison point, not a migration |
| 18 Mar 2026 | `{current_date}`, `{current_time}`, `{timezone}` prompt variables; `Asia/Kolkata` example (`march-2026.md:66-72`) | → prompt-composition lane |
| **16 Mar 2026** | **In-call reschedule validation.** Priority: `calling_guardrails` `call_start_hour`/`call_end_hour` → agent prompt → "**Default window (9 AM – 9 PM)**"; "If the requested reschedule time falls outside the allowed window, the request is rejected entirely" (`march-2026.md:98-104`). Also Vobiz number buying; `provider` ∈ {`twilio`,`plivo`,`vobiz`} (`:112`) | **⚠ The engine has a 9AM–9PM DEFAULT that applies when we set no guardrails** — TRAI-relevant, → compliance lane |
| 14 Mar 2026 | Gemini Flash models added (`march-2026.md:120-125`) | Explicitly OUT of this product (D-410) |
| **9 Mar 2026** | **KB `language_support: multilingual`** — "cross-lingual retrieval across 100+ languages… query in one language, retrieve from documents in another" (`march-2026.md:135-140`) | **→ KB lane. Directly serves a Telugu-first product with English source documents** |
| **3 Mar 2026** | **140 & 160 series numbers purchasable** — "Bolna agents can now be triggered with 140 & 160 series phone numbers to comply with TRAI regulations" (`march-2026.md:150`) | → numbers/compliance lane; our exact domain vocabulary |
| 15 Feb 2026 | `agent_data` override on `/call`; "Currently, overriding the `voice_id` (for the same provider) is supported" (`february-2026.md:12`) | → per-call voice without an agent edit |
| **13 Feb 2026** | **Sarvam v3: `saaras:v3` transcriber, `bulbul:v3` TTS** (`february-2026.md:34-35`) | Confirms D-36's `bulbul:v3` is real and named exactly that |
| 9 Feb 2026 | Deepgram adds Bengali, Kannada, Marathi, **Telugu** (`february-2026.md:45-48`) | Speech lane FYI |
| **7 Feb 2026 ⚠** | **API rate limiting introduced.** 500 req/min each on `/v2/agent/{agent_id}/executions`, `/v2/agent/{agent_id}`, `/call`; 1000 req/min default elsewhere; per **organization**; HTTP 429 (`february-2026.md:56-66`) | **⚠ §4.4 — a code comment said these were unpublished. Corrected. No behavioural change needed** |
| 3 Feb 2026 | Truecaller verified caller identity (`february-2026.md:72`) | → answer-rate lever, founder-facing |
| 27 Jan 2026 | Vobiz telephony integration (`january-2026.md:12-16`) | → numbers lane (D-05 names Vobiz for 140-series) |
| **26 Jan 2026 ⚠** | **Auto-retry for failed calls** — "Up to 3 automatic retry attempts", "Configurable delays", "Works with single calls and batch campaigns", "Webhook notifications include retry status" (`january-2026.md:22-30`) | **⚠ §7.2 — we run our own `retry_policy`. Two retry engines on one contact is a double-dial risk. Founder/engineering decision** |
| 26 Jan 2026 | IVR for Plivo inbound via `ivr_config` on `/inbound/setup` (`january-2026.md:37-68`) | → inbound lane |
| 6 Jan 2026 | Multilingual auto-switching of system messages (online-check, hangup, pre-function) (`january-2026.md:79-85`) | → Telugu lane |
| 5 Jan 2026 | Noise cancellation (`january-2026.md:91`) | None |
| **2 Jan 2026** | **Auto Reschedule** — "Automatically reschedule calls when a user asks to be called at a specific time" (`january-2026.md:101`) | This is the feature that emits `rescheduled`, the status D-351 found missing |

### 2025 and earlier

| Date | Change | Why it matters to us |
|---|---|---|
| 20 Dec 2025 | `@`-mention function calls in prompts (`december-2025.md:12`) | None |
| 17 / 13 / 10 Dec 2025 | Pixa, Gladia, ElevenLabs Scribe transcribers (`december-2025.md:22,28,34`) | Speech lane FYI |
| **7 Dec 2025** | **KB accepts website URLs as sources** (`december-2025.md:40`) | → KB lane |
| **4 Dec 2025** | **KB: multiple PDFs together; "Fixed issues with function calls while using knowledgebases"; retrieval accuracy + latency** (`december-2025.md:46-48`) | → KB lane |
| 26 Nov 2025 | AiSensy WhatsApp (`november-2025.md:12`) | None |
| 16 / 4 Nov 2025 | ElevenLabs style exaggeration, similarity boost, stability (`november-2025.md:18-21,49-50`) | None |
| 12 Nov 2025 | Revamped workflows and campaigns (`november-2025.md:31-33`) | We run our own campaigns |
| **7 Nov 2025** | **Per-call latency metrics**, "overall averages and percentiles such as P50, P90, and P95" (`november-2025.md:39-43`) | → gate 4 (real-call latency) can compare against `latency_data` |
| 2 Nov 2025 | Cartesia `sonic-3` voice cloning incl. Telugu (`november-2025.md:60-72`) | None |
| **29 Oct 2025** | **Stop Agent Queued Calls API** — "stop all queued calls for a specific agent… Prevents any pending calls from being executed" (`october-2025.md:12-16`) | **→ §7.3. A candidate engine-side implementation of the big red switch** |
| 28 Oct 2025 | Unsiloed + LlamaParse KB PDF parsing (`october-2025.md:22-26`) | → KB lane |
| 20 Oct 2025 | Cartesia `sonic-3-preview` Indian languages (`october-2025.md:32-44`) | None |
| 15 Oct 2025 | Exotel telephony integration (`october-2025.md:58-62`) | D-05 names Exotel — confirms it is a first-class engine integration |
| 7 Oct 2025 | Remove/unlink inbound agent API (`october-2025.md:68-70`) | → inbound lane |
| **5 Oct 2025** | **RAG: ONNX reranking, `all-mpnet-base-v2` embeddings, table extraction, "Multi-collection queries"** (`october-2025.md:76-79`) | → KB lane |
| **2 Oct 2025** | **Sub-account deletion API — "When a sub-account is deleted, **ALL** associated data is permanently removed"** incl. executions and call logs (`october-2025.md:86-95`) | **→ DPDP erasure lane if sub-accounts are adopted (§7.1): one call erases a tenant at the engine** |
| **29 Sep 2025** | **Compliance application mandatory to buy numbers** — CIN certificate + GST registration, "One-time application with 12-24 hour review process" (`september-2025.md:12-17`) | **⚠ External blocker, not ours to code around: needs a legal entity + GST. Name it as such** |
| 27 Sep 2025 | Anthropic `claude-sonnet-4`; **Sarvam** + AssemblyAI transcribers, "11 Indian languages including… Telugu" (`september-2025.md:26-32`) | Confirms Sarvam STT is first-class |
| **24 Sep 2025** | **Concurrency configurable at sub-account level**; **batch webhook notifications** on `processed`, `scheduled`, `queued`, `running`, `completed`, `stopped` (`september-2025.md:38-42`) | → §7.1; batch statuses match `api-reference/errors.md`'s batch enum |
| 15 Sep 2025 | Agent template library (`september-2025.md:52-69`) | None |
| 11 Sep 2025 | Cumulative sub-account usage API (`september-2025.md:75`) | → billing lane if sub-accounts adopted |
| 9 Sep 2025 | Stop `queued`/`scheduled` outbound calls before execution (`september-2025.md:81`) | → big red switch |
| 8 Sep 2025 | Custom `headers` on function tools (`september-2025.md:87`) | → our in-call tool endpoints can be authenticated |
| **21 Aug 2025** | **`scheduled_at` on `/call`** (`august-2025.md:12`) | We do not send it — a known adapter gap, pinned by `tests/pilot_gates_test.py::test_start_outbound_call_still_has_no_scheduled_at_parameter` |
| 20 Aug 2025 | One-click voice cloning (`august-2025.md:18-20`) | None |
| 3 Aug 2025 | OpenRouter provider + BYOK OpenRouter keys (`august-2025.md:30-44`) | Not used |
| **30 Jul 2025** | **India Data Residency introduced** (`july-2025.md:12`) | **→ Lane D (residency/legal). Not edited here** |
| 28 Jul 2025 | Phone number search / buy / delete APIs (`july-2025.md:18-20`) | → numbers lane |
| 7 Jul 2025 | Rime TTS (`july-2025.md:26-28`) | None |
| 2 Jul 2025 | Sarvam `bulbul:v2` over WebSocket (`july-2025.md:34`) | D-36's value tier |
| 29 Jun 2025 | On-premise offering, private beta (`june-2025.md:12`) | None |
| 26 Jun 2025 | `ingest_source_config` on agents for inbound data ingestion (`june-2025.md:18`) | → inbound caller-matching lane |
| 24 Jun 2025 | TTS model switching in dashboard (`june-2025.md:36`) | None |
| 20 Jun 2025 | Sub-account create / list / usage APIs (`june-2025.md:48-52`) | → §7.1 |
| **27 May 2025 ⚠** | **"Extended maximum call duration to 40 minutes"** (`may-2025.md:22`) | **⚠ §6.3 — our `CALL_CAP_MAX_S` is 3600s. Ambiguity reported, not guessed** |
| 28 May 2025 | Azure TTS latency work; Smallest.ai `lightning-v2` (`may-2025.md:12-16`) | None |
| **24 May 2025** | **Azure OpenAI clusters added: `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`, `gpt-4o`, `gpt-4o-mini`, `gpt-4`** (`may-2025.md:28-34`) | **Independently corroborates D-410: Azure OpenAI is a first-class Bolna provider and BOTH `gpt-4o-mini` (default) and `gpt-4.1-mini` (live switch) are on their list** |
| 23 May 2025 | ElevenLabs multi-context WebSocket (`may-2025.md:44-45`) | None |
| 22 May 2025 | 100+ languages (`may-2025.md:51`) | None |
| 14 May 2025 | $1000 top-up, auto-recharge, execution page filters (`may-2025.md:61-76`) | → billing lane |
| 12 May 2025 | viaSocket integration (`may-2025.md:86`) | None |
| 7 May 2025 | Sarvam `bulbul-v2` TTS (`may-2025.md:93`) | D-36 |
| 29 Apr 2025 | Inbound call frequency limiting per source number (`april-2025.md:12`) | → anti-spam lane |
| **27 Apr 2025** | **"All inbound and outbound calls to have a maximum limit of `25KB` for injecting context"** (`april-2025.md:18`) | **⚠ §6.4 — a hard payload cap on `user_data`/context. Verified we are inside it** |
| 23 Apr 2025 | Inbound whitelist control (`april-2025.md:26`) | → inbound lane |
| 20 Apr 2025 | Guardrail latency; "Tool information will now be available in the post call analysis" (`april-2025.md:32-33`) | → extraction lane |
| 17 Apr 2025 | Deepgram Aura-2 (`april-2025.md:39`) | None |
| 16 Apr 2025 | "Transcripts will now be more accurate by incorporating interruptions" (`april-2025.md:45`) | → transcript parsing (`parse_transcript`) |
| 15 Apr 2025 | GPT-4.1 family (`april-2025.md:51`) | None |
| 11 Apr 2025 | Voice removal; **"Audio recordings are now stored in `dual` (stereo) mode for both inbound & outbound calls"** (`april-2025.md:57-58`) | → recording size budget (`MAX_RECORDING_BYTES`) |
| 31 Mar 2025 | `strict` mode for custom tools (`march-2025.md:12`) | → tooling lane |
| 22 Mar 2025 | Dynamic caller identification via internal API / CSV / Google Sheets (`march-2025.md:19-22`) | → inbound lane |
| 18 Mar 2025 | Azure transcriber models (`march-2025.md:28`) | None |
| 14 Mar 2025 | Infra latency work (`march-2025.md:34`) | None |
| 9 Mar 2025 | **Status page launched — `https://status.bolna.ai`** (`march-2025.md:40`) | → runbooks: an incident check we can name |
| 7 Mar 2025 | Default `timestamp`/`timezone` context, overridable (`march-2025.md:46-47`) | → prompt lane |
| 24 Feb 2025 | Webcall support (`february-2025.md:12`) | None |
| 16 Feb 2025 | Voice import from ElevenLabs/Cartesia (`february-2025.md:18`) | None |
| 13 Feb 2025 | Deepgram `nova-3` (`february-2025.md:24`) | None |
| 8 Feb 2025 | ElevenLabs `eleven_flash_v2_5` (`february-2025.md:30`) | None |
| 3 Feb 2025 | Silence-based hangup + hangup message (`february-2025.md:36-37`) | → `hangup_after_silence`, referenced by `concepts/call-flow.md:84` |
| 16 Jan 2025 | Delete-agent API; bug: "Execution `status` wasn't getting updated for few incoming calls with connected Twilio telephony" (`january-2025.md:12-16`) | **Historical evidence that vendor status delivery has failed before — the reason the poller, not the webhook, is the guarantee of record** |
| 10 Jan 2025 | Bug: "Few executions were erroneously loosing the `batch_id` mapping" (`january-2025.md:22`) | Same |
| 24 Dec 2024 | Batch download + status breakdown (`december-2024.md:12-17`) | → campaign reporting |
| 18 Dec 2024 | Cartesia TTS; voicemail detection for Twilio & Plivo; hangup prompts (`december-2024.md:23-26`) | Voicemail is a boolean, not a status (see §6.1) |
| **10 Dec 2024** | **`execution_id` changed from `{agent_id}#{timestamp}` to a unique `{uuid}`** — "The execution ID overhaul addresses previous scaling issues" (`december-2024.md:39-40`); `agent_id` dropped as redundant from batch and execution APIs (`:53-54`) | Historical; our `engine_call_id` is a UUID string, consistent |

### Self-hosted changelog (the only entry)

| Date | Change | Why it matters |
|---|---|---|
| Sep 2025 | Container images `release-250911`. **"Enhanced Logging & Call Statuses – Added more granular logs, _additional call statuses_, and exception handling"**; Twilio/Plivo synchronous SDKs removed (`self_hosted_changelog/september-2025.md:22-24`) | **Direct corroboration that the execution status enum GREW after this repo's pinned OAS was captured — which is exactly how `prepared` came to be missing (§4.1)** |

---

## 2. DEPRECATIONS AND DEADLINES

**One breaking change with a hard date was found, and its deadline has already passed.**

| Announced | Deadline | Change | Status for us |
|---|---|---|---|
| 11 May 2026 | **1 June 2026 — PAST** | Direct Amazon S3 recording URLs stop working; recordings served from `https://api.bolna.ai/recordings/call/{execution-id}` | **We were never exposed.** See §4.2 |

Nothing else in 21 changelog pages announces a removal, sunset or retirement date. The
deprecated v1 agent API (`api-reference/agent/*` alongside `agent/v2/*`) is carried in the
mirror **without any announced removal date** — no changelog entry retires it. We call
`/v2/…` throughout.

### Proposed CLAUDE.md edit — DO NOT APPLY HERE (CLAUDE.md is owned by another lane)

CLAUDE.md currently says, of the deleted `GEMINI_DEFAULT_LLM_RETIRES`:

> `GEMINI_DEFAULT_LLM_RETIRES` and the test that turned CI red thirty days out are deleted,
> and no vendor deadline is currently running against this product.

**That statement remains TRUE and needs no edit.** The one vendor deadline this audit found
expired on 1 June 2026, before today (20 Aug 2026), and we were never subject to it — so
there is no deadline *running*. Recording the near-miss is worth one clause; the exact
proposed replacement, if the owning lane wants it:

> **DISPOSITION, 20 Aug 2026 (doc-reconciliation pass): DECLINED for CLAUDE.md, applied
> elsewhere.** Two reasons, both about what that file is for. (1) The clause's factual
> content is vendor-changelog history, and CLAUDE.md carries no such list — starting one
> means it grows with every vendor change and the next reader cannot tell which entries
> still bind. (2) The part that DOES bind is a pipeline design rule, not a date: *never
> parse, store or re-use a vendor URL; `calls.recording_url` holds our own object key*.
> That rule now sits where the code it governs is described — `docs/TRD.md` §5 (Recordings
> bullet, with the 1 Jun 2026 change, the Bolna-hosted endpoint and the 24-hour pre-signed
> ceiling quoted from `changelog/may-2026.md:91,99,118`) and `docs/SURFACES.md` §3.3 — and
> `docs/` wins over the manual anyway. CLAUDE.md's "no vendor deadline is currently running
> against this product" is left exactly as it stands: it is true, and any clause appended to
> it would read to a hurried agent as though one were.

The proposed text, kept here as the record of what was declined:

```
and no vendor deadline is currently running against this product. (Bolna's one dated
breaking change — S3 recording URLs retired 1 Jun 2026, docs/evidence/
bolna-platform-changelog.md §2 — passed without touching us because we re-host every
recording and never parse the vendor's URL.)
```

---

## 3. CHANGES MADE, FILE BY FILE

Two behavioural findings were mine to fix; one of them had already been fixed by a
concurrent lane and I deliberately did not touch it. Comment corrections follow.

### 3.1 `apps/api/engine/bolna.py` — `prepared` added to the status enum and map ✅ BEHAVIOURAL

`api-reference/errors.md` enumerates **sixteen** execution statuses. `_VENDOR_STATUSES`
held **fifteen**. The missing one is `prepared`:

> `bolna-findings/mirror/pages/api-reference/errors.md:42` —
> "| `prepared` | Intermediate | Execution record created and validated (recipient number,
> from/to number assigned) but not yet handed off to the dial queue |"

The adapter's unmapped default is `failed`, and `failed` is **terminal**. So a call the
vendor had accepted, validated and was about to dial was recorded as attempted-and-dead:
the contact settles, the line frees, and the dial the vendor had already committed to goes
ahead anyway. This is D-351 (`rescheduled`) one rung earlier, with a real call attached.

Mapped to `queued`, for the same reason `scheduled` and `rescheduled` are. The comment
block above the enum now records that the pinned OAS was the *narrower* of two first-party
statements of this enum, so the next reader does not re-derive it.

**RED (sabotage: `"prepared": "queued"` removed from `_STATUS_MAP`)**

```
>       assert snapshot.status == "queued"
E       AssertionError: assert 'failed' == 'queued'
E         - queued
E         + failed
FAILED tests/bolna_snapshot_test.py::test_every_status_the_vendor_can_send_is_mapped
FAILED tests/bolna_snapshot_test.py::test_a_prepared_call_is_waiting_not_failed
2 failed, 25 deselected, 1 warning in 0.37s
```

**GREEN (restored)**

```
2 passed, 25 deselected, 1 warning in 0.28s
```

Full file: `46 passed, 1 warning in 0.29s`.

New test: `tests/bolna_snapshot_test.py::test_a_prepared_call_is_waiting_not_failed`. The
pre-existing `test_every_status_the_vendor_can_send_is_mapped` catches it too — it was
already the right guard and simply had the wrong enum handed to it.

### 3.2 Webhook source-IP allowlist — FOUND, then found ALREADY FIXED by a concurrent lane 🤝

`DEFAULT_BOLNA_SOURCE_IPS` held one address (`13.203.39.153`) while Bolna documents
**three**, in six independent first-party places:

> `concepts/security.md:45-54` — "Bolna sends webhooks from a fixed set of source IPs:
> **`13.203.39.153`** **`13.126.9.249`** **`13.202.133.53`** … 1. Whitelist all three IPs
> on your server or firewall"
>
> `build-with-ai/agents-md.md:44` — "Whitelist all three or events will be dropped."
>
> also `api-reference/limits.md:59`, `concepts/call-flow.md:108`, `concepts/glossary.md:183`,
> and every agent create/update reference page.

Because `parse_source_ip_allowlist` fails **safe**, two of three vendor senders were being
**rejected** at the receiver.

**I did not edit this.** By the time I reached the file, another lane had landed the fix
as **D-414** — `frozenset({"13.203.39.153", "13.126.9.249", "13.202.133.53"})`, plus the
`DOCUMENTED_EGRESS_IP` → `DOCUMENTED_EGRESS_IPS` rename across `scripts/pilot/gates_api.py`,
`scripts/check_bootstrap_keys.py` and `tests/engine_name_drift_test.py`. Their write-up
additionally dates the vendor's change by comparing the mirror against the older
`llms-full.txt` snapshot, which is better evidence than I had. **Recorded here as
independent confirmation from a second reader, not as a second fix.**

> ⚠ **Handoff:** at the time of writing, `scripts/pilot/gates_api.py` is mid-edit — the
> constant is renamed at line 70 but three call sites (≈642, 660, 1203) still say
> `DOCUMENTED_EGRESS_IP`, which is a `NameError`. That is the owning lane's in-flight work
> and I deliberately left it alone rather than collide. **Somebody must confirm it lands.**

### 3.3 `apps/workers/pipeline.py` — corrected a stale vendor fact in a load-bearing comment

`_copy_recording_once`'s docstring justified its guard with "Bolna's are direct S3 links
with **no documented expiry**, TRD §5". Both halves are now false (`changelog/may-2026.md:87-119`):
the S3 shape was retired 1 Jun 2026, and the replacement's resolved link *does* expire —
"the **resolved pre-signed link it returns expires after 24 hours** — do not store or cache it".

**No code change: we already do exactly what the vendor asks.** Nothing parses, stores or
re-uses the vendor URL; `storage._fetch_recording` walks the redirect to the pre-signed
link itself (`RECORDING_REDIRECT_LIMIT = 3`, vetting every hop) and never persists it, and
`calls.recording_url` is overwritten with our own object key. The vendor's 24-hour window
only has to outlive one fetch. The comment now says so, and says which paragraph was wrong.

### 3.4 `apps/api/engine/vendor_http.py` — corrected "vendor rate limits are unpublished"

The throttle ladder's rationale opened with "Vendor rate limits are unpublished (Bolna:
pilot item; Cartesia: no account at all)". Bolna published them on 7 Feb 2026:

> `api-reference/rate-limiting.md:17-25` — 500 requests/minute each on
> `/v2/agent/{agent_id}/executions`, `/v2/agent/{agent_id}` and `/call`; "All other API
> endpoints are subject to a default rate limit of **1000 requests per minute**."
>
> `:29` — "If your account is part of an **organization**, the rate limit is shared across
> all users within that organization."

**No behavioural change, and that is the finding rather than an omission** — see §6.2. The
comment now carries the numbers, the per-organisation scope (i.e. per Bolna account, *not*
per Calevate tenant), and the reason the ladder stays as it is. Cartesia's remain unpublished.

### 3.5 `apps/workers/campaign_dispatch.py` — `PLATFORM_LINES_TOTAL` is now a verified number

The constant carried "Until engine verification item 8 produces the real numbers, the pool
is a config default sized for the pilot." The vendor states both the default and where to
read the live value:

> `frequently-asked-questions.md:51` — "By default, Bolna allows up to **10 concurrent
> calls** for paid users."
>
> `api-reference/limits.md:11-19` — "Check your current concurrency in `GET /user/me`:
> `{ "concurrency": { "max": 10, "current": 3 } }`"

So our pilot guess and the vendor default coincide, **verification item 8 is a lookup
rather than a measurement**, and `_outbound_pool()` (10 minus the inbound reserve) dials
strictly fewer lines than Bolna accepts. Comment updated; constant unchanged.

---

## 4. VERIFIED — NO GAP FOUND

These are the lane items I was asked to check that turned out to be correct. Saying so
explicitly is a real result.

### 4.1 Pagination (D-350 / D-353) — CORRECT, including the dishonest-field case ✅

The vendor's contract:

> `api-reference/pagination.md:13-14` — "`page_number` … Defaults to `1`. The first page
> starts at `1`.  `page_size` … Defaults to `20`. **You can request up to `50` results per
> page.**"
>
> `:50` — "Use `has_more` to determine if you should fetch the next page."
>
> `:34-44` — envelope is `{total, page, page_size, has_more, data}`.

Our `bolna.list_executions` asks for `page_size = _LISTING_PAGE_SIZE = 50` (the documented
maximum — verified, not exceeded), loops on `has_more`, and **never computes pages from
`total`**. On the "is `has_more` honest" question the adapter is already defensive in all
three directions: a missing/non-boolean flag falls back to "believe the page" and reports
`full_page_suspected`; a flag stuck `True` that yields no new rows reports
`next_link_no_progress`; and `_LISTING_MAX_PAGES = 20` bounds the walk with
`page_cap_reached`. `packages/shared/tests/engine_conformance/conftest.py:287` even asserts
`page_size <= 50` against the stub. **No change needed.**

> Note: the `to` parameter *is* a live gap on this endpoint, but it is **not mine** — the
> concurrent D-414 lane found and fixed it in the same file (`_LISTING_MAX_WINDOW`,
> 7-day cap) while I was reading. Not duplicated here.

### 4.2 The recording-URL breaking change — WE WERE NEVER EXPOSED ✅

The 1 June 2026 deadline passed without incident because `calls.recording_url` holds *our*
object key, never the engine's (`apps/api/crm/models.py:97`, "OUR storage, never engine's"),
and the copy path fetches through whatever URL the snapshot carries at that moment. Nothing
in the tree matches `bolna-recordings`, `s3.amazonaws`, or any parse of the vendor's URL
shape. Comment corrected (§3.3); no code change.

### 4.3 Webhook trust (TRD §5) — THE DESIGN IS CORRECT AND NOW EXPLICITLY CONFIRMED ✅

I was asked to check whether Bolna has since added a signature. **They have not, and they
say so in as many words:**

> `concepts/security.md:56` — "**There is no HMAC signature on webhook payloads in the
> current version. Source IP verification is the primary trust mechanism.**"
>
> `:51-54` — "To verify webhooks are genuinely from Bolna: 1. Whitelist all three IPs on
> your server or firewall 2. Reject webhook requests from any other IP on your webhook
> endpoint"

So hard rule 3's "for unsigned engines like Bolna: source-IP allowlist + execution-id
dedupe, payloads as hints, poller as truth" is **the vendor's own recommended design**,
verified first-hand for the first time. `WEBHOOK_AUTH_BY_ENGINE["bolna"] == "source_ip"`
is an accurate claim, not a fallback.

**But there IS an upgrade available, and it is a real one** (5 May 2026):

> `changelog/may-2026.md:174-176` — "You can now send **custom HTTP headers** along with
> your execution-data webhook from the agent's **Extractions** tab… provide a JSON object
> of header key-value pairs — Bolna will include them on every webhook delivery for that
> agent. This makes it easier to authenticate webhook requests against your own services
> (for example, by sending an `Authorization` token, an API key, or a tenant identifier)."

That is a **shared secret we choose**, carried on every delivery, and it composes with the
IP allowlist rather than replacing it — defence in depth against an attacker who can spoof
or reach us from an allowlisted address. It is **not** a signature: it does not authenticate
the *body*, so "payloads as hints, poller as truth" must stay regardless.

**Why I did not implement it:** it needs a per-agent value set in Bolna's console or via
the agent-config API, which is the other lanes' surface (`bolna._agent_body`) and an
OPERATIONS §2 gate, not a change I can complete end-to-end without colliding. **Filed as
§7.4 — engineering, not blocked on anything external.**

Also available and unused: **status-filtered webhooks** (7 Jul 2026,
`changelog/july-2026.md:119-125`) — "Use **Trigger on statuses** to select the statuses you
want webhooks for. By default, **all statuses** are sent." We receive every transition and
act on few; narrowing it at the vendor reduces receiver load inside the 500ms ack budget.

### 4.4 The error ladder vs the documented status codes — CORRECT ✅

`api-reference/errors.md:11-20` documents `200, 201, 400, 401, 403, 404, 429, 500`.
`vendor_http.vendor_request` handles each correctly per BACKEND-PATTERNS:

| Documented code | Docs say | Our ladder | Verdict |
|---|---|---|---|
| `200` / `201` | success | parsed; non-JSON 2xx → `engine_bad_response` | ✅ (P2.2) |
| `400` | "Invalid or missing parameter" | `engine_rejected`, `dependency`, terminal | ✅ our bug, must not retry |
| `401` | "Missing or invalid API key" | `engine_rejected`, terminal | ✅ retrying cannot help |
| `403` | "Valid key but insufficient permissions" | `engine_rejected`, terminal | ✅ |
| `404` | "Resource ID doesn't exist" | `engine_rejected`; `absent_is_success` only on idempotent delete | ✅ |
| `429` | "back off and retry with exponential backoff" | 3 attempts, full jitter, `Retry-After` as a floor, then `engine_rate_limited` (`transient`, retryable) | ✅ matches `limits.md:25-34`'s own `2 ** i` guidance |
| `500` | "Unexpected server error" | `engine_rejected` + `record_engine_failure(kind="server_error")`; **not** retried | ✅ deliberate — `POST /call` is not idempotent |

The one trap on that page is one we cannot hit: "`500` … also returned when `scheduled_at`
uses the `Z` suffix (use `+00:00` instead)" (`errors.md:20`, `limits.md:43`). **We never
send `scheduled_at`** — a known adapter gap already pinned by
`tests/pilot_gates_test.py::test_start_outbound_call_still_has_no_scheduled_at_parameter`.
If it is ever added, it must be `+00:00`, ≥2 minutes ahead, and it rounds up to the next
10-minute mark (`limits.md:41-43`).

### 4.5 Rate limits and the dispatch tick — WE CANNOT EXCEED THE DOCUMENTED CAPS ✅

Checked as asked, arithmetic below.

- **`POST /call`, 500/min per organisation.** The dispatcher can never have more than
  `PLATFORM_LINES_TOTAL = 10` calls in flight and dials only into free lines on a 30-second
  tick — an upper bound of ~20 dials/minute platform-wide, **25× inside the cap**.
- **`GET /v2/agent/{id}/executions`, 500/min.** The poller fans out one request per agent
  per page on a 10-minute tick. Even 300 agents × 1 page = 301 requests **per ten minutes**,
  ~30/min, **16× inside the cap**.
- **Concurrency, 10 by default.** `_outbound_pool()` = 10 − max(4, 30%) = **6 outbound
  lines**, strictly below the vendor's 10, with the remainder reserved for inbound.

**No dispatcher change required.** The one thing to watch: the limit is per *organisation*,
so if Calevate ever moves tenants onto sub-accounts under one org (§7.1), all tenants share
these 500/min — the arithmetic above must be re-run at that point, not assumed.

### 4.6 Agent type — WE CREATE CONVERSATION AGENTS, WHICH IS STILL RIGHT ✅

> `concepts/agent-types.md:15-17` — "A conversation agent follows a single system prompt for
> the entire call… **This is the default agent type.**"
>
> `:83-90` — "every Bolna agent is scoped to a set of **tasks**… A `task_type` (e.g.
> `conversation`, `extraction`), a `toolchain`… Most agents have a single `conversation`
> task."

Our adapter builds exactly that shape, and it is the correct one:

- **Graph agents** (`:38-54`) suit "multi-stage flows where behavior changes significantly
  between phases". Our per-agent behaviour comes from a client-authored prompt plus an
  extraction schema, and hard rule 5 requires `compose_engine_prompt` to append the
  compliance invariants to **the** prompt and verify them against the engine on every
  publish and drift sweep. A graph agent has *N* per-node prompts, so that invariant would
  need enforcing and verifying on every node — strictly more surface for the same product,
  and a new way to do a solved problem (quality bar: "one way per problem").
- **IVR agents** (`:62-75`) are DTMF routing that "Does not use an LLM for the IVR routing
  layer" — not a voice agent at all. Relevant only as an inbound front door (26 Jan 2026,
  Plivo only).

**No change. Revisit only if a client needs deterministic multi-stage routing**, and then
as a decision-log entry that says how the compliance invariant is enforced per node.

---

## 5. VENDOR AMBIGUITIES AND CONTRADICTIONS — REPORTED, NOT RESOLVED

Per the evidence rule, these are flagged rather than guessed.

1. **SIP support: the FAQ contradicts the changelog and the concepts pages.**
   `frequently-asked-questions.md:105-107` says "Does Bolna support SIP connectivity? **Not
   yet.** SIP connectivity is **not currently supported**… native SIP integration is on our
   roadmap." But `changelog/may-2026.md:12-16` and `:84` describe BYOT SIP trunks over
   TCP/TLS with custom `X-` headers, and `concepts/choosing-providers.md:118` lists "Custom
   SIP (BYOT)". **The FAQ is stale.** No impact on us (we use no SIP trunk) — but it is a
   worked example of why an FAQ line is not a specification.
2. **Recording retention is unstated.** `concepts/security.md:19` — call recordings
   "Available in execution record; **contact support for retention policy**". TRAI's 90-day
   floor is *our* obligation and we re-host every recording, so this does not bite; but the
   vendor makes **no retention commitment** we can cite. External question for the vendor.
3. **Maximum CSV rows for a batch is unstated.** `api-reference/limits.md:44` — "Maximum CSV
   rows | **Contact support for high-volume batches**". We build our own campaigns from our
   own contact rows, so this only matters if batch upload is ever adopted.
4. **`concepts/choosing-providers.md` names models that do not appear anywhere else** in the
   mirror (`gpt-5.4-mini`, `claude-sonnet-5`, `deepseek-v4-flash`) and warns about itself:
   "Provider model lineups change frequently. The specific model names here are current
   examples" (`:12`). Do not treat that page as a model list.

---

## 6. SMALLER FINDINGS

### 6.1 Voicemail — the docs confirm what D-260 concluded

Nothing in the changelog or `errors.md` introduces a `voicemail` status. Voicemail
detection shipped 18 Dec 2024 (`december-2024.md:24`) as a *feature*, and the status enum
has never carried it. `_STATUS_MAP["voicemail"]` remains correctly unreachable.

### 6.2 The 9AM–9PM engine default is a compliance surface we do not currently set

`changelog/march-2026.md:98-104`: when a caller asks to be rescheduled in-call, the engine
validates against `calling_guardrails` if set, else the agent prompt, else "**Default window
(9 AM – 9 PM)**". If we set no `calling_guardrails` on the agent, the *engine* is deciding
our calling-hours compliance from a default it chose. → **compliance lane.**

### 6.3 Our `CALL_CAP_MAX_S` (3600s) may exceed the platform's own ceiling — AMBIGUOUS

`changelog/may-2025.md:22` — "Extended maximum call duration to **40 minutes**" (2400s).
No later page states a current numeric ceiling; `guides/outbound/disconnect-calls.md:15`
describes a configurable maximum without a bound, and the agent OAS blocks expose
`call_terminate` with no documented maximum. **So it is unclear whether 40 minutes is still
the platform ceiling, and I have not guessed.**

**No defect either way**: our value is a cost-runaway *ceiling*, and an engine that stops
sooner is safe. `STUCK_DIALING_AFTER` (= `CALL_CAP_MAX_S` + 10min = 70 min) stays
conservative. The only cost is that a client could configure a cap the engine will never
honour. → one question for the vendor, or one gate observation on a long test call.

### 6.4 The 25KB context cap — verified, we are inside it

`changelog/april-2025.md:18` — "All inbound and outbound calls to have a maximum limit of
`25KB` for injecting context." Our `CallContext`/`user_data` carries identifiers and a
handful of CRM fields, not documents (RAG is a KB reference, not inlined text), so we are
orders of magnitude inside it. Recorded so nobody later inlines a knowledge-base excerpt
into `user_data` without knowing there is a wall.

### 6.5 Batch status enum — matches ours, if we ever adopt batches

`api-reference/errors.md:78-86` gives `created`, `processed`, `scheduled`, `running`,
`completed`, `stopped`, `failed`, which matches the batch-webhook list in
`changelog/september-2025.md:42`. We do not use Bolna batches (we dispatch per-contact), so
there is nothing to map today.

---

## 7. NEEDS A FOUNDER OR ENGINEERING DECISION

### 7.1 Sub-accounts: engine-enforced per-tenant isolation, concurrency and erasure

Three capabilities landed that together map onto problems this repo solves in SQL:

- per-account `min_concurrency` / `max_concurrency`, honoured by the vendor's own scheduler
  ("Guarantees are honored first each scheduling cycle, spare capacity is then shared
  fairly", `changelog/june-2026.md:17`);
- per-sub-account usage APIs (`september-2025.md:75`, `june-2025.md:52`);
- sub-account deletion that removes **all** agents, executions and call logs
  (`october-2025.md:91-95`) — a DPDP erasure primitive.

Against that: `concepts/security.md:79` says sub-accounts are an **Enterprise plan**
feature, and adopting them means one Bolna account per tenant, which changes credential
handling, the rate-limit denominator (§4.5) and the engine-agent routing bridge.
**Founder decision, gated on a commercial term (Enterprise plan) — an external blocker,
named.** Not an engineering task to start today.

### 7.2 Bolna's auto-retry vs our `retry_policy` — two retry engines on one contact

`changelog/january-2026.md:22-30`: "Up to 3 automatic retry attempts… Works with single
calls and batch campaigns." Our campaigns carry their own `retry_policy` and
`next_attempt_at`. If auto-retry is ever enabled on an agent we drive, a contact can be
dialled by both. **Engineering: confirm it is OFF for our agents and assert it in the agent
body, or adopt theirs and delete ours — one way per problem.** I did not change it because
I cannot verify the field name from my lane's pages (it lives in the agent-config
reference, another lane's surface), and inventing a field name is exactly what CLAUDE.md
forbids.

### 7.3 The big red switch could be engine-enforced

`changelog/october-2025.md:12-16` — Stop Agent Queued Calls API "stop all queued calls for
a specific agent… Prevents any pending calls from being executed"; plus `september-2025.md:81`,
stopping individual `queued`/`scheduled` calls. Today the big red switch stops *our*
dispatcher, which cannot recall a dial the engine has already accepted. **Engineering:
worth wiring as a second arm.**

### 7.4 Take the webhook shared-secret header (§4.3)

Engineering, unblocked, small, and a genuine security improvement over IP-only trust.
Needs a per-agent value on the engine side, so it belongs with whichever lane owns
`_agent_body` + an OPERATIONS §2 gate.

---

## 8. HANDOFFS

| To | What |
|---|---|
| **Lane D (residency/legal)** | `concepts/security.md:29-36`: "**By default, Bolna processes calls on infrastructure in the US (AWS us-east-1).** Indian data residency is available…" When enabled: "Call processing runs on servers in `ap-south-1` (Mumbai)", "Recordings and transcripts are stored in India", "**LLM inference is routed to India-region endpoints (where available)**" — note the hedge. Also `changelog/july-2025.md:12` dates India residency to 30 Jul 2025, and `security.md:71` on provider-credential storage: "your provider API keys are stored encrypted in Bolna's infrastructure… Bolna does not log or expose provider credentials in API responses" — relevant to the D-410 BYOK Azure key. **I did not edit `/legal/*` or `docs/LEGAL-SURFACE.md`.** |
| **Lane A (executions/status)** | I added `prepared` to `_VENDOR_STATUSES` and `_STATUS_MAP` in `apps/api/engine/bolna.py` (§3.1). If you also found it, it is done — please do not add it twice. Your `_LISTING_MAX_WINDOW` / `to` work is untouched by me. |
| **D-414 lane (webhooks)** | Independent confirmation of your three-IP finding (§3.2). **`scripts/pilot/gates_api.py` is currently mid-rename and will `NameError` — three call sites still say `DOCUMENTED_EGRESS_IP`.** |
| **Extraction / CRM lane** | 14 Apr 2026 confidence + reasoning + typed-format validation (timeline). A `confidence_label` of `Low` is a ready-made human-review trigger. |
| **KB / RAG lane** | 9 Mar 2026 multilingual KBs (cross-lingual retrieval), 7 Dec 2025 URL sources, 5 Oct 2025 multi-collection queries, 18 Jun 2026 `vector_ids`. |
| **Compliance lane** | §6.2 (engine's 9AM–9PM default), 3 Mar 2026 (140/160-series purchasable), 29 Sep 2025 (CIN + GST required to buy numbers — external blocker). |
| **Runbooks** | `https://status.bolna.ai` (`changelog/march-2025.md:40`, `getting-help.md:34`) and the support matrix in `getting-help.md:45-50` — `support@bolna.ai`, `enterprise@bolna.ai`, `compliance@bolna.ai` for "LOA requests and DLT/TRAI compliance for regulated Indian phone numbers". |

---

## 9. GATES

| Gate | Result |
|---|---|
| `uv run ruff check` (my files) | clean |
| `uv run ruff format --check` (my files) | clean |
| `uv run mypy apps packages` | `Success: no issues found in 238 source files` |
| `uv run pytest tests/bolna_snapshot_test.py` | `46 passed` |
| Sabotage verification | §3.1 — RED then GREEN, both pasted |

Per instruction, the full suite and `make coverage-ratchet` were **not** run (10 agents,
4 vCPU — a contention failure would be noise). Nothing was committed or pushed.
