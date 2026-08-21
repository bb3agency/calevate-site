# Calevate — Operations, Quality & Runbooks

Version 1.0

---

## 1. Environments

- **local**: docker-compose (pg+redis+minio), engine mocked via adapter fakes.
- **staging**: DO BLR small; engine (Bolna) staging agents + one test number; synthetic data only.
- **prod**: DO BLR; separate engine workspace/keys; promote-only config flow.

## 2. Engine Verification Session — now executed as the BOLNA PILOT (D-31) [do FIRST]

> D-31 (Aug 2026): ThinnestAI failed due diligence before this session ran; the
> checklist below is executed against Bolna as the pilot scorecard. Adaptations:
> item 1's HMAC criteria become source-IP-allowlist + dedupe + poller verification
> (Bolna webhooks are unsigned, at-most-once — TRD §5); item 5 empirically measures
> webhook loss behavior; item 8 adds: the BYOK platform fee in writing (target
> ≤ ~₹1.5/min), sub-account/agency terms, INR/GST billing, recording
> retention/deletion API, India data-residency terms, Bulbul V3 exposure, Azure OpenAI
> support on the agent object, Telugu quality of the multilingual KB mode.
> **A MODEL-ACCOUNT gate rides along**, on our own account rather than Bolna's, and it is
> the 20-series below rather than a footnote here. Since D-410 both LLM surfaces run on
> **Azure OpenAI in South India** (`AZURE_LOCATION`), default `AZURE_OPENAI_DEFAULT_MODEL`
> — and the residency claim that used to be provable from a Vertex URL is now a property
> of the Azure RESOURCE, which no endpoint reveals. Gates 20/20b/20c are what turn that
> configuration into a verified fact; gate 20c is the one a reader underestimates, because
> Azure's DEFAULT deployment type processes worldwide. **The 14-series is retired** with
> Gemini, and BRD R-04's 16 Oct 2026 date with it.
> Items failing ⇒ the engine decision reopens (no fallback engine is designated — D-31).
> **20 AUG 2026 — TEN PARALLEL LANES READ THE VENDOR'S OWN DOCUMENTATION END TO END**
> (`bolna-findings/mirror/pages/`, one evidence file per lane in `docs/evidence/bolna-*.md`),
> and this table moved more in a day than in the month before it. **Gate 7**'s unit is
> settled by their worked example and its CURRENCY now needs an invoice rather than a
> payload; **gate 9**'s verdict is WITHDRAWN — their India residency is real, Enterprise-
> gated, and excluded by our own BYOK posture, so buying it today would move zero calls
> (D-415); **gate 16f**'s field names are settled and the default we shipped was WRONG
> (D-417). **9v and 21–28 are new.** Nothing in that sweep closed a gate by inference:
> where two of their pages disagree, the row says which two and stays open.
> **21 AUG 2026 — A SECOND WAVE (the request-, response- and failure-contract audits)
> ADDED 29–34, and two of them are H because they are compliance-load-bearing**:
> **gate 29** — which key carries the two phone numbers on an execution, and the INBOUND
> polarity, because three compliance surfaces match on columns that would otherwise be
> permanently NULL (D-425) — and **gate 31**, the wallet, whose emptying looks like a
> fleet of failed calls rather than an account out of credit (D-425). Rows 2, 3, 4, 25
> and 28 gained clauses in the same wave rather than new rows of their own.

Budget ~₹3–5k (Bolna gives $5 free signup credits + Sarvam's ₹1,000 free credits, so
most of this is real PSTN call spend). 5–7 working days alongside other work.
**H = hard gate (a red H reopens the engine decision); S = soft gate (shapes M1 scope).**

| # | Gate | Pass criteria |
|---|---|---|
| 1 H | Webhook trust | Register a tunnel URL as the agent's `webhook_url`; run calls. **THE VENDOR PUBLISHES THREE EGRESS ADDRESSES, NOT ONE, AND THIS ROW NAMED ONE UNTIL 20 AUG 2026 (D-414).** Confirm deliveries arrive ONLY from `13.203.39.153`, `13.126.9.249` and `13.202.133.53` — *"Whitelist all three IPs"* (`bolna-findings/mirror/pages/concepts/security.md`, corroborated by `guides/post-call/polling-call-status-webhooks.md`) — that **all three are ACCEPTED** and a fourth address is rejected by our allowlist (nginx + in-app). `DEFAULT_BOLNA_SOURCE_IPS` held one address and the control fails safe, so two of three senders were being refused, losing arbitrary status transitions including `completed`; score every address and name the rejected ones rather than passing on the first that works. confirm dedupe on execution_id; confirm the payload matches Get Execution. Docs claim no signing — if a signature header exists, capture it and update TRD §5. |
| 2 H | Full API provisioning | Via API only, no dashboard: create agent → update prompt → attach number → start call (`POST /call`) → `GET /executions/{id}`. Confirm /v2 agent paths, `user_data` context injection round-trips into the prompt, and `scheduled_at` works. **AND SETTLE `delete_agent`'s MARKED ASSUMPTION (D-123).** Both real adapters implement `DELETE` on the agent (`DELETE /v2/agent/{agent_id}` is published in Bolna's reference — 200 `{"message":"success","state":"deleted"}`, 400, and a note that it destroys all of the agent's batches and executions; Cartesia publishes NO agent-delete reference at all, so its `DELETE /agents/{id}` is INFERRED). What neither vendor documents is what a REPEAT delete answers, and both adapters assume **404** and fold it into the Protocol's idempotent success. If it is a 400 instead, `agents/service.py::_reclaim_orphan` raises on a compensation whose work is already done and the retry ladder DLQs it. The harness now runs this: `gates_api._delete_agent_checks` creates a THROWAWAY agent (never the gate's own — deleting that would destroy the execution this gate's own re-run instructions depend on), deletes it, re-reads it, and deletes it a SECOND time. Record the exact status and body of the repeat; if it is not 404 the fix is to narrow `absent_is_success` onto what the vendor actually sends, never to widen the accepted status range. **AND SCORE THE READ-BACK'S COMPLETENESS, because a publish is only as verified as what `GET /v2/agent/{id}` gives back (D-418).** Record, for one published agent: **(a)** does the response return `agent_welcome_message` under ANY key? `AgentV2` does not declare it, so `_agent_greeting` answers `readable=False` and **every publish lands `unreadable` rather than `applied`** — the property carrying the recording/AI-disclosure sentence is verified only in the weaker of its two places. If the live response carries it, `_agent_greeting` already finds it and this closes with no code change; if it does not, record which key holds the greeting, or that it does not round-trip at all. **(b)** does the response echo `multilingual_config` and `llm_agent.routes`? Both change what the agent SAYS without touching `agent_prompts`, which is the only surface the drift sweep reads. **(c)** does `PUT /v2/agent/{id}` really replace the whole configuration — set `calling_guardrails` by `PATCH`, then `PUT` a body that omits it, and re-read. Every "an omitted key is a field left as it was" sentence in `_agent_body` rests on the answer. **(d)** does `GET /v2/agent/{id}` echo `calling_guardrails` AT ALL? [added 21 Aug 2026, request-contract audit, F-7] Gate 21 is the console-side half of that switch; this is the API-side half, and it decides whether the drift sweep can page on a console-set calling window the way it already pages on a console-added semantic route. **(e)** [F-6] does `agent_welcome_message: ""` CLEAR a greeting the platform is already holding, or is it treated as absent? `_agent_body` sends the empty string for an agent with no greeting and the vendor documents no clearing semantics either way — the two readings differ by whether a client who removes a greeting keeps hearing the old one. |
| 3 H | Telugu quality (BYOK) | Sarvam Saaras V3 STT + Bulbul V3 TTS on OUR keys. 10-utterance Telugu script on real PSTN: names/numbers ≥90% correct; Telugu-English code-mixed handled. Confirm **Bulbul V3 (not v2) is selectable**. **AND SETTLE WHETHER `sarvam` IS AN ACCEPTED BASE `synthesizer.provider` AT ALL, AND IN WHICH KEY THE MODEL GOES [added 21 Aug 2026, request-contract audit, F-3 in `docs/evidence/bolna-request-contract.md`].** The `Synthesizer.provider` enum is `polly` / `elevenlabs` / `deepgram` / `styletts` on all three agent-body pages (`bolna-findings/mirror/pages/api-reference/agent/v2/create.md:638-645`, `update.md:556-563`, `patch_update.md:329-336`) and `Synthesizer.provider_config`'s `oneOf` has no Sarvam arm — so **as documented** our publish body matches no arm at all and `POST /v2/agent` would 400 on every agent we have ever created. Five other first-party sources say otherwise (`create.md:749-756`, `create.md:1218-1228`, `providers/voice/sarvam.md:38-44`, `cli/commands/agents-create.md:48`, `agent-setup/audio-tab.md:117`), which is why nothing was changed from the documents. Publish ONE agent with today's body and record the status. If it is accepted, record what `GET /v2/agent/{id}` echoes back under `synthesizer.provider_config` — that answers D-358's `voice`-vs-`model`-vs-`voice_id` question in the same call, and `GET /me/voices` gives the speaker list the catalogue needs. |
| 4 H | Real-call latency | 10 PSTN calls: voice-to-voice p50 ≤ 1.1s, p95 ≤ 1.8s (stopwatch + recording analysis). **Vendor latency claims are marketing — their site says "<300ms" undefined; plan only against our own measurement.** Record first-greeting delay after pickup separately (cold-start hides there). **Also capture `latency_data` from Get Execution as an adapter fixture and record whether it AGREES with the stopwatch.** Their docs describe `time_to_first_audio` plus per-component transcriber/llm/synthesizer blocks — unverified against a live account, and a different set of numbers from voice-to-voice turn latency, which would be our own arithmetic aligning three components. This capture is what re-opens durable per-call latency storage: `calls.latency` was dropped (`f1a7c39d5be2`) rather than filled with pipeline timings that are not the caller's experience, and the storage shape gets chosen from the payload we actually receive. Note the documented `transcriber.turns` entries carry recognised TEXT — hard rules 5/6 apply to wherever it lands; **that concern is now VERIFIED from the vendor's own worked payload rather than inferred, so `transcriber.turns[].turn_latency[].text` is a DO-NOT-STORE, not a caution.** **Capture `latency_data` verbatim once for a second reason: it carries `region`** (*"e.g., `in` for India"*, `concepts/call-latencies.md`) — a per-execution region field the vendor already returns, worth having while the residency claim rests on a human attestation in a portal (gates 9, 20). **And settle the two inherited defaults while the stopwatch is out**: `transcriber.endpointing` (`default: 250`, their own guide says *"Increase to 400–500ms for callers who pause mid-sentence (non-native speakers, elderly)"* — our callee population) and `synthesizer.buffer_size` (`default: 250`, while the same guide calls *"100–150 characters"* typical and says smaller buffers start audio sooner). Neither was changed from a document, because what every caller hears is not moved on an audit's say-so — it moves on this measurement. Also confirm which of `hangup_after_silence` and `check_if_user_online` / `trigger_user_online_message_after` wins when both are 10 seconds; nothing documents it (gate 23). |
| 5 H | Telugu turn-taking [NEW, D-32] | Barge-in mid-sentence, and end-of-utterance on slow/hesitant Telugu speech: does the agent cut callers off, or leave dead air? Endpointing is an ORCHESTRATION-layer property — BYOK models do NOT fix it. Measure, never assume. |
| 6 H | Webhook loss behavior | Kill the receiver mid-call: call continues; observe whether ANY retry arrives (docs + OSS code say none). Then confirm the List-Executions poller recovers every missed execution — it is the guarantee of record, so its recovery must be proven, not assumed. **Retry expectation FLIPPED (D-352): the hosted platform documents that it retries on non-2xx and fires one delivery per status transition, so a retry is the expected observation and its ABSENCE is the surprise.** **PAGINATION IS NO LONGER THE QUESTION (D-350/D-353).** The adapter used to call a global `GET /executions?created_after=`, which is not a route the vendor has, and inferred truncation from a page-size heuristic. It now walks the real endpoint — `GET /v2/agent/{agent_id}/executions`, per agent, `from`/`page_number`/`page_size` (max 50), looping on `has_more` — with the contract read in Bolna's own pinned OpenAPI document. What is left to settle is not the CONTRACT but whether the server honours it, which a spec cannot say: **(a)** the account's own execution count for the window from the dashboard, passed as `--attest gate6.executions_in_window=<n>` — more than we listed is proof of truncation and the gate goes red; **(b)** whether the `from` filter actually bounds the window rather than being ignored; **(c)** whether `has_more` ever lies. Capture one raw listing body as a fixture and compare its envelope with `AgentExecutionV2List`. A complete-looking listing on a quiet pilot window without (a) is NOT RUN, never a pass. |
| 7 **H** *(was S — raised by D-261)* | Post-call data fidelity, and **what unit is the money in** | `completed` (not `call-disconnected`) carries total_cost + cost_breakdown, recording_url, extracted_data. Transcript parses into TranscriptTurn (check `transcript_lines_unparsed == 0`; if their serializer emits `system:` / `assistant_tool_call:` / `tool_response:` lines, D-260 already skips and counts them — a non-zero count here is the signal, not a failure). Time-to-`completed` (~2–3 min claimed) against our 2-min lead SLO. **THE UNIT IS SETTLED; THE CURRENCY IS NOT, AND THIS GATE NOW SCORES ONLY THE SECOND (D-414).** Our adapter divides by 100 (`_ASSUMED_MINOR_UNITS_PER_MAJOR`). That constant used to rest on the vendor's own precedence rule between two contradicting first-party documents — a rule about which document to believe, not an observation of a server. Their hosted API reference now prints a real completed execution (`bolna-findings/mirror/pages/api-reference/executions/get_execution.md`): `conversation_duration: 16`, `total_cost: 3.23`, `cost_breakdown {platform 2, network 1, transcriber 0.23, llm 0, synthesizer 0}`. Two things fall out that no amount of prose could give. **`total_cost` is exactly the sum of the five legs** (2 + 1 + 0.23 = 3.23), which is the property `_cost` has always preserved by converting total and legs on one divisor and one rate. And **the major-unit reading is arithmetically impossible**: 3.23 over 16 s is 12.11 units/min — ~12¢/min as minor units, which sits on their published $0.06/min Voice AI rate plus telephony and platform fee, against **$12.11/min ≈ ₹1,060 for one minute of an Indian phone call** as major units. The decomposition corroborates it independently: `network` and `platform` are whole units on a 16-second call because telephony and the platform fee bill per MINUTE, while `transcriber` is fractional because STT bills per SECOND (`pricing/call-pricing.md`). **The unit no longer needs a live capture; a capture can only confirm it.** **WHAT IS STILL OPEN IS THE CURRENCY, A PAYLOAD CANNOT CLOSE IT, AND THE EXPOSURE IS WORSE THAN THIS ROW USED TO SAY.** `AgentExecution` declares seventeen properties and **`currency` is not one of them**, so `_cost`'s `payload.get("currency") or payload.get("cost_currency")` always misses, `currency_stated` is always False, and the `engine_cost_unit_unknown` refusal branch D-411 built is **UNREACHABLE** short of the vendor adding an undocumented key. This row used to say that since D-411 an INR-billed pilot account meters NOTHING until this gate closes. **It does not: it meters every call on the house USD assumption** — a quieter failure than a gap and a worse one, because the number looks fine and reaches the margin panel and every invoice with nothing downstream able to disagree. The OAS names no currency at all; `pricing/preferred-models.md` quotes "$0.06/min (₹5.52/min)" and "the 6¢/min rate", so every price they publish is primary in dollars; and `pricing/call-pricing.md` introduces a THIRD word for the same quantity — an execution consumes **"credits"**, a wallet unit that need not be one US cent. **THE TEST IS THEREFORE AN INVOICE OR WALLET STATEMENT, NOT A PAYLOAD CAPTURE:** place calls totalling a known duration, then reconcile the wallet debit against the summed `total_cost`, and name the currency the account is billed in from a document Bolna issued us. **Pass** = we can state that currency and cite that document. **WHAT TO DO WITH THE ANSWER, so this gate ends in a command rather than in "find out":** if it is not USD, add the one line to `_MINOR_UNITS_PER_MAJOR` (`INR: Decimal(1)` for rupees, `Decimal(100)` for paise) and deploy, then restate what was metered before the flip with `uv run python -m scripts.correct_cost_unit` — dry-run by default, append-only, idempotent, and it moves OUR cost only (`usage_events` is INSERT-only, hard rule 4; a client's invoice is priced off minutes and does not move). Rows carry `meta.source_currency`, `meta.source_amount`, `meta.fx_rate` and `meta.currency_stated`, which is what makes the affected population selectable afterwards. The full sequence, and what NOT to do, is `runbooks/vendor-cost-unit.md`; a call whose derived ₹/min lands outside the rate card's band pages `engine_cost_implausible` (D-411) rather than waiting for this gate — and the vendor's own ₹5.52/min sits inside that band with wide margin, so the band neither cries wolf nor misses a 100x error. **A wrong value here means every `usage_event` under-values calls 100x, no spend cap ever arms, and every margin panel reads ~₹0.00.** Blocked outside this repo on: a Bolna account with funds. Evidence: `docs/evidence/bolna-executions-cost.md` §1, `docs/vendor/bolna/`. |
| 8 S | KB + campaigns + tools + H1 handling [expanded, D-33] | **BOTH D-354 BLOCKERS RE-CONFIRMED AGAINST THE VENDOR'S OWN DOCS (20 Aug 2026, `docs/evidence/bolna-kb-extraction.md`); `BOLNA_CAPABILITIES.knowledge_base` STAYS `False`.** **(a)** `POST /knowledgebase` is still `multipart/form-data` taking `file` (PDF ≤ 20 MB) **or** `url`, "not both", with **no text field** — it cannot ingest `KBSourceRef.text` (`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md`). **(b)** The `Knowledgebase` schema still carries **no `agent_id`** (`get_knowledgebase.md`), so `list_kb`'s per-agent filter still matches nothing — but the old wording "no agent linkage" was wrong and is replaced: **the linkage exists on the AGENT**, as `llm_agent.agent_type="knowledgebase_agent"` plus `llm_config.vector_store.provider_config.vector_ids`, keyed by `vector_id` (`api-reference/agent/v2/create.md`). **NEW, and it changes the shape of any re-opening:** `POST /knowledgebase` does **not** return `vector_id`, so `attach_kb` would be create → `GET /knowledgebase/{rag_id}` → PATCH the agent — three calls, not two. **STILL UNANSWERED, AND THE ONE THING THIS GATE MUST MEASURE ON THE BUILT-IN: does `DELETE /knowledgebase/{rag_id}` clear the agent's `vector_ids`?** The delete page says only "Delete a knowledgebase" while the *dispositions* delete page in the same API explicitly promises to "remove its link to any associated agents" — the silence is conspicuous, and a dangling `vector_id` after an erasure is a DPDP finding. **Telugu + multilingual KB:** the mode is confirmed immutable at creation ("cannot be switched … create a new one", `getting-started/knowledge-base.md`) and the API claims "cross-lingual retrieval across 100+ languages" — but **no page enumerates Telugu**; the only list anywhere is the dashboard label "Multilingual (Hindi, Tamil, etc.)". So measure Telugu retrieval quality **and** latency in `multilingual` mode against the fallback in the same session. **Ingestion latency is documented nowhere** — status goes `processing` → `processed`/`error` with no SLO and no polling interval published; measure it. Note `error` is reachable but absent from the GET schema's enum, and `rag_id`'s format contradicts itself between the two pages (32-hex vs dashed UUID). **WHAT THIS GATE PRIMARILY MEASURES REMAINS THE FALLBACK** (TRD §6.2): retrieval quality and latency through OUR managed vector service behind the in-call RAG tool endpoint, whose server half is `tool_ack_ms` (`apps/voice-runtime/tool_routes.py`). Test a custom function to our endpoint and record the tool-call p95. **MEASURE THE CALLER-OBSERVED DELTA, NOT OUR SERVER'S ACK.** D-109 already puts `tool_ack_ms` at p95 1.4 ms single-flight and ~143 ms at 250 concurrent — comfortably inside TRD §6.2's 100 ms budget and **not the thing the caller waits for**. The vendor's own model says a tool call costs *"50–500ms … depending on the tool's response time"* ON TOP of our endpoint (`concepts/call-flow.md`), and their step 4 feeds the tool result back to the LLM, so a tool-using turn pays a SECOND time-to-first-token. Record `latency_data.time_to_first_audio` for a turn with a tool call and for one without, on the same agent, and report the difference; their own stated bottleneck is LLM TTFT > 1000 ms and their sample payload shows 1633 ms on turn 1. **THE TIMEOUT ABSENCE IS NOW CONFIRMED ACROSS THE WHOLE DOC SET, NOT MERELY UNCHECKED.** Every timeout Bolna documents governs something else — Total Call Timeout, `inactivity_timeout`, the transcriber's `eot_timeout_ms`, the web-call 30 s setup timeout, the IVR input timeout. There is **no documented tool-call timeout, no documented tool-call retry, and no documented statement of what the agent says to the caller while our endpoint is slow** — the only retry sentence in the doc set is about deliveries TO us. So TRD §6.2's 100 ms is OURS, unconstrained from above, and this gate is the only thing that can produce a ceiling. **AND SETTLE THE ONE QUESTION THAT DECIDES WHETHER OUR TOOL ENDPOINT CAN BE CONFIGURED AT ALL:** `guides/prompting/using-context` lists `execution_id` as a system variable, while BOTH tool-calling pages omit it from their auto-injected tables, listing only `agent_id`, `call_sid`, `from_number`, `to_number`. `call_sid` is the TELEPHONY provider's id, and `apps/workers/optout.py` resolves the tenant from an authenticated `GET /executions/{execution_id}` — so if `%(execution_id)s` does not substitute inside a custom function's `param`, `POST /tools/v1/{engine}/opt-out` 422s on every call and **the in-call opt-out path is dead**. Configure the tool as `"method": "POST"` (a GET puts `param` in the query string, which our body-reading route never sees) with `headers: {"Content-Type": "application/json"}` and `"key": "custom_task"`, then record whether `%(execution_id)s` arrived. Create a 10-contact batch; verify retry policy + per-contact statuses. Capture every response as an adapter fixture. **In-call working memory (H1, TRD §6.1):** does Bolna truncate or summarise conversation history at a window limit, and does it enable provider context caching on BYOK keys? Both drive the LLM leg on long calls. |
| 9 H | Compute region + residency [NEW, D-32; **verdict REPLACED 20 Aug 2026 from the vendor's own docs — D-415**] | **THE OLD VERDICT IS WITHDRAWN AND THE NEW ONE IS WORSE, NOT BETTER.** This row used to end *"this is the one axis where LiveKit beats Bolna on verified evidence today"*, on the strength of recordings seen at `s3.us-east-1`. Bolna's documentation, read at last (`bolna-findings/mirror/pages/`), says three things that together retire that sentence and replace it with a harder problem. **(a) The default is the United States for EVERYTHING, not just storage** — *"By default, all Bolna AI services operate in United States (US)-hosted infrastructure"* (`enterprise/data-residency.md`), *"By default, Bolna processes calls on infrastructure in the US (AWS us-east-1)"* (`concepts/security.md`). **(b) India residency exists and is well specified** — audio, transcripts, logs and configurations stored in India, and *"All inference, transcription, and response generation happens within Indian borders"*, on `ap-south-1`. It is an **Enterprise-plan purchase** (*"Data residency is an Enterprise feature"*), so it is gate 12's subject and gate 10's as well — the same SKU carries sub-accounts and elevated concurrency, so negotiate the three together rather than three times. **(c) AND OUR ARCHITECTURE EXCLUDES IT.** Their Indian-server requirements are Plivo telephony, a listed transcriber and synthesizer, and Azure OpenAI — all of which we already match — plus *"Use Bolna's default provider integrations. Do not connect your own API keys for the transcriber, synthesizer, or LLM providers"*, with the consequence stated outright: *"If you connect your own API keys for any provider (transcriber, synthesizer, or LLM), calls will automatically route through US servers regardless of other configuration settings"* (`enterprise/indian-server-configuration.md`). **BYOK on all three legs is what this product IS** (D-31/D-36/D-410), so buying residency today would move **zero calls**. A second, independent exclusion applies to the promotional half of the business and does not depend on BYOK at all: Indian-server routing names **Plivo only**, while 140-series telemarketing numbers come through **Vobiz** (`guides/inbound/obtaining-regulated-phone-numbers.md`), and outbound campaigns are the promotional product. **WHAT THIS GATE NOW TESTS IS THEREFORE A DECISION, NOT A MEASUREMENT** (`docs/evidence/bolna-compliance-residency.md` §5): keep BYOK and accept US orchestration with the DPA saying so — which is what `/legal/{subprocessors,privacy,dpa}` were corrected to say on 20 Aug 2026 — or move to their provider integrations and buy Enterprise residency, losing BYOK's cost control, D-410's Azure South India pinning on the in-call leg, and D-36's control of the Telugu speech stack. **Still to establish with the vendor, and each is a sentence in a contract rather than an experiment**: (i) whether "Indian server routing" covers STORAGE or only the media path — `enterprise/data-residency.md` describes an account-level selection covering both while `enterprise/indian-server-configuration.md` describes per-agent routing conditions, and the two pages never say how they compose; (ii) Enterprise pricing for residency, and whether it can be had without the rest of the Enterprise bundle; (iii) whether a sub-account can be residency-pinned independently of the parent (gate 10 interaction, and note providers are ORG-level, so a BYOK credential is an org-wide object and (c) would apply to every sub-account at once); (iv) the retention and deletion policy for their copies, which `concepts/security.md` answers only as *"contact support for retention policy"*. **THE OLD PARENTHETICAL ABOUT THE RECORDING BUCKET IS RETIRED WITH THE VERDICT** — it read *"(Recordings sit on S3 us-east-1 — storage ≠ compute, but both matter.)"*, and the doc set is now inconsistent about where they ever were: the OAS example is `bolna-call-recordings.s3.us-east-1.amazonaws.com/AC…/RE…` (note the Twilio account- and recording-SID shapes, so that example may be a Twilio URL rather than Bolna's own store), while the May 2026 changelog names the pre-June format as `bolna-recordings-india.s3.amazonaws.com`. **Since 1 June 2026 both are superseded** by `https://api.bolna.ai/recordings/call/{execution-id}` (and `…/recordings/transfer/…` for a transfer leg), which resolves to a pre-signed link expiring in 24 hours and must not be cached. So **ask where the bucket is rather than assuming either answer** — "observed in us-east-1" is a DATED observation nobody can re-verify by inspection any more; storage ≠ compute, and both still matter. **What survives unchanged, and is worth saying out loud:** the MODEL legs remain Indian even while the orchestration is not — Sarvam sovereign by vendor, Azure OpenAI pinned to South India by gates 20/20b/20c — so the inference does not leave the country. |
| 9v H | **The vendor's compliance-flag channel, and what it can do to us** [NEW, 20 Aug 2026, D-416] | Bolna raises VIOLATIONS against the account — *"Flagged call violations — content policy, regulatory, or fraud"* (`bolna-findings/mirror/pages/build-with-ai/mcp-tool-list.md`) — publishes them on `GET /violations/list`, pushes nothing, and documents no trigger, no deadline and no consequence. **Our half is done and does not wait on this gate**: `apps/workers/engine_violations.py` polls hourly, attributes each flag to a tenant through `engine_agent_routes`, and pages `engine_violation_open` (`runbooks/engine-violations.md`). **The gate is the five answers only they can give**, and each changes something: **(a)** what raises one — if any part of it is an automated scan over transcripts, that is a processing purpose our DPA does not describe and must; **(b)** the deadline for submitting evidence and what it runs from — this decides whether an hourly poll is generous or already too slow; **(c)** what an unanswered flag costs, specifically whether it can suspend the account's calling or only an agent (their FAQ proves they DO restrict agents over content findings, which is not proof that an unanswered flag does); **(d)** what `accepted` and `rejected` mean, since the words are undefined and could describe the flag being upheld against us or our evidence being accepted — opposite meanings for one string; **(e)** on a reseller/sub-account structure, whether a flag attaches to the ACCOUNT or the SUB-ACCOUNT, because if one client's flagged call can stop the parent account's calling that is a multi-tenant blast radius and belongs in gate 10's answer as well as this one. **Pass criteria**: all five in writing, plus one observed round trip on a live account (list → submit → list) proving the status transition and the evidence-upload path. **Refuse to infer any of the five from the four status strings.** Note the hard-rule-6 trap already handled at the boundary: their documented evidence path ends in the recipient's phone number as the FILENAME, so `EngineViolation` carries `has_evidence: bool` and no URL, no phone number and no email — do not "improve" the record by storing the path. Blocked outside this repo on: a Bolna account (and, for (e), an Enterprise sub-account structure). |
| 10 H | Agency model — and the **only** mechanism that can give one client a guaranteed floor | Confirm in writing that multiple end-clients under one Bolna account is permitted. **THE TIER DISCREPANCY IS HALF-SETTLED AND THE UNREAD HALF IS THE PRICING PAGE.** Their docs are now unanimous that sub-accounts are Enterprise-only — five of the seven `api-reference/sub-accounts/*` pages, `enterprise/sub-accounts.md`, `concepts/security.md`, `concurrency-management.md`, `mcp-tool-list.md` and `getting-help.md` all say it, with no dissent anywhere under `/docs/` (`docs/evidence/bolna-subaccounts-platform.md` §1.1). The "Sub-accounts access under Pilots" claim lives on `bolna.ai/pricing`, which is NOT a docs URL and is NOT in the mirror — so it is **unread, not refuted**. Open that page in a browser, or ask. **NO PRICE EXISTS ANYWHERE IN THEIR DOCS**, and `enterprise/plan.md`'s own feature list does not mention sub-accounts at all, so name them explicitly as a deliverable rather than assuming they ride along. **WHAT WE WOULD BE BUYING, precisely:** (a) per-tenant `min_concurrency` — a GUARANTEED FLOOR, which our `plans.concurrency_ceiling` (a cap) cannot express and which gate 13's finding says we need; (b) per-sub-account usage totals with a full cost breakdown, the first vendor-side control total our metering could reconcile against. **WHAT WE WOULD NOT BE BUYING:** phone numbers and providers stay ORG-LEVEL, so this isolates neither the calling number nor its header registration — and it is also why gate 9(c)'s BYOK exclusion would apply to every sub-account at once; billing consolidates at the org and the balance is shared (`enterprise/organization.md`), contradicted only by `concepts/security.md` — get the wallet question in writing before pricing any client as a prepaid sub-account. **DO NOT SET `multi_tenant: true`**: it hands Bolna a database host and a ROOT user and password (`api-reference/sub-accounts/create.md`), which is a processor arrangement of a different shape and needs its own DPDP assessment. **ONE QUESTION SETTLES WHETHER IT IS WORTH BUYING AT ALL:** can an Enterprise organization set `min_concurrency` on its MAIN account without sub-accounts? If yes, we get the floor without the second tenancy boundary. This gate shares a contract and an email with gates 9 and 12 — Enterprise is the same SKU that carries India data residency and elevated concurrency; negotiate once, not three times. |
| 11 H | The humans | Open two support threads (one technical, one commercial) during the pilot; record response time and answer quality. **This is the gate ThinnestAI failed** — a good product with unresponsive people is the same trap twice. |
| 12 H | Commercials in writing | **(a) the BYOK platform fee — the single number that decides ₹3–3.6/min; target ≤ ~₹1.5/min**; (b) whether volume tiers apply to BYOK; (c) INR/GST invoicing; (d) price-change notice period (60–90 days); (e) data-export commitment on exit; (f) recording retention + DPDP deletion API; **(g) is the built-in KB (`rag_id`) billed separately, or included in the platform fee? No KB line appears on the pricing page — we have INFERRED "included" and that inference is load-bearing for TRD §6.2 (D-33). Get it in writing, including any per-document/storage/query charge.** Anchors: their published bundled rate is 6.00¢→4.51¢/min; Vapi's comparable orchestration tax is ₹4.40/min (D-32). **OBSERVED Aug 2026, still ungated: the BYOK platform fee shows as 2¢/min ≈ ₹1.76 in the Bolna dashboard.** That is inside TRD §10's assumed ₹1.50–2.00 band but ~17% ABOVE this gate's ≤₹1.50 target, so the observation does NOT close (a) — a dashboard figure is not a commercial term, and the gap is worth ₹5,200/month at 20k platform-min and ₹15,600 at 60k (TRD §10.4). Open the negotiation on the ₹1.50 number with those two figures in hand. **(a) — THE PLATFORM FEE IS OBSERVED AT 2¢/MIN, AND THE FLAT RATE IS A SUM RATHER THAN A FLOOR (D-423).** Bolna's live dashboard decomposes the per-minute rate for a configured agent into **voice agent (STT + LLM + TTS) 3.5¢ + telephony 0.5¢ + Bolna platform 2.0¢ = 6.0¢/min** — VERIFIED-DASHBOARD (founder screenshot, 20 Aug 2026), which is **weaker than an invoice and stronger than prose, and is NOT the same evidence class as the mirrored docs**. At the ₹92/USD implied by their own "$0.06/min (₹5.52/min)", the platform fee is **≈₹1.84/min** — this gate's "single number that decides ₹3–3.6/min", ~23% above its ≤₹1.50 target and consistent with the 2¢ ≈ ₹1.76 dashboard figure already recorded. **It does NOT close (a):** a dashboard panel is one agent's configured models, not a universal constant and not a commercial term — **an invoice is still what confirms what is billed** (and gate 7's currency rides on the same document). **THE BUNDLE IS ENUMERATED AND OUR MODELS ARE INSIDE IT:** `pricing/preferred-models.md` lists `azure/gpt-4o-mini` and `azure/gpt-4.1-mini` (LLM), `saaras:v2.5` / `saaras:v4` (ASR) and `bulbul:v2` (TTS) at the flat rate — **but `bulbul:v3`, D-36's default TTS, is NOT on that list**, so our TTS leg falls off the flat rate onto variable billing. **AND BYOK STILL SAVES MONEY, which one lane inferred the opposite of:** *"You can significantly reduce costs by connecting your own provider accounts. When you bring your own keys (BYOK), Bolna does not charge for those components. You only pay your providers directly, plus Bolna's platform fee"* (`pricing/call-pricing.md:75`). BYOK deletes the 3.5¢ voice-agent line and replaces it with our own provider bills, so against TRD §10.1: **bundled ₹5.52/min; BYOK + Bulbul v3 ₹3.98–4.66/min; BYOK + Bulbul v2 ₹3.44–3.85/min** — only the v2 variant lands inside the ₹3–3.6/min target. Negotiate the fee with those three figures and the ₹5,200/month at 20k platform-min (₹15,600 at 60k, TRD §10.4) in hand. **(g) — the inference is STRONGER and still an inference:** `pricing/call-pricing.md` enumerates the bill twice (*"three components: Voice AI processing (STT + LLM + TTS), telephony charges, and a Bolna platform fee"*; *"the sum of five components across three parts"*) and names **no knowledge-base charge in either**, matching `cost_breakdown`'s five keys — and the dashboard panel shows the same three lines, which is corroboration rather than proof. A pricing page that omits a charge is not a commitment that none exists — still get it in writing. |
| 13 S | Concurrency ceiling | Pilots advertises 100 concurrent and two customers run 250+ in production (D-32); confirm OUR ceiling, behavior at the limit (queue vs reject + error shape), and the outbound dispatch rate limit (unpublished — measure it; it becomes our dispatcher config, FLOWS §5). Also ask Sarvam (BYOK-tier model concurrency) and Exotel/Vobiz (SIP trunk channels). **And Azure OpenAI, since D-410 (this used to be three legs and is now four).** An Azure deployment's ceiling is its own TPM/RPM quota in the subscription and the region, not a published table — gate 20b is where the number is read, and it is read for `southindia` specifically because quota is granted per region. It is the same shape as D-35's finding about Sarvam: **the binding constraint on a cheap model is the rate limit, not the price.** Effective ceiling = MIN of all four — record all four. **FOUR THINGS THE VENDOR'S OWN DOCS NOW ANSWER OR SHARPEN (`docs/evidence/bolna-subaccounts-platform.md` §2).** **(a) Queue vs reject is ANSWERED: queued.** *"Outbound calls that don't fit your concurrency limit are queued, not rejected"* (`pricing/outbound-calling-concurrency.md`). That makes an over-high `PLATFORM_LINES_TOTAL` a **COMPLIANCE** defect rather than a throughput one — the surplus dials out of a vendor queue we cannot see, cannot DNC-scrub and cannot halt, after `check_dispatch` has already cleared them, so a contact cleared at 20:55 IST can ring after 21:00. Confirm the queue exists and measure how long it holds. **(b) The ceiling no longer needs MEASURING, it needs READING:** `GET /user/me` returns `concurrency: {max, current}` (`api-reference/user/info.md`). Record `max` against `PLATFORM_LINES_TOTAL`, and `current` against our own in-flight `calls` count in the same instant — a persistent gap is stranded rows. The tier also moves without a deploy (*"Paid accounts — Starts at 10 concurrent calls, scaling automatically with monthly usage"*). **(c) Does our inbound reserve buy anything?** Two pages say inbound is never restricted or queued and the org envelope is OUTBOUND-only (`concurrency-management.md`, `pricing/outbound-calling-concurrency.md`). If true, `inbound_reserve_ratio` costs us 4 of 10 lines for nothing and the outbound pool goes 6 → 10. **TEST IT, do not infer it** — hold N outbound calls at the ceiling and place an inbound call to a platform number; it must connect. This is a vendor-prose claim about admission control, which is the exact class D-31/D-32/D-350 exist for. **(d) How many telephony providers will we dial through?** *"An account's capacity is split evenly across its providers"* (`concurrency-management.md`) — two providers with queued work means HALF the ceiling on each, and our dispatcher has no notion of a provider. BYOT SIP is **not** an independent ceiling either: *"those calls run on Bolna's SIP infrastructure, so they share platform capacity even though the trunk is yours"*, so trunk channels stack ON TOP of the platform limit rather than bypassing it — which changes how TRD §10's MIN() reads. |
| 14 H | **~~Does `asia-south1` serve our Gemini model?~~ RETIRED BY D-410 — there is no Gemini model and no Vertex account.** [closed 19 Aug 2026] | Both LLM surfaces moved to Azure OpenAI in South India, so the question this gate asked no longer has a subject. It was never answered: nobody in this repository could read Google's model-availability table (`docs.cloud.google.com`, `discuss.ai.google.dev`, `modelavailability.com`, `innfactory.ai`, `gcloud-compute.com`, `openrouter.ai` and `pricepertoken.com` were each attempted and each refused by this environment's egress proxy), and the one `generateContent` call that would have settled it was blocked on a GCP project that never existed. **What carried over is the SHAPE, not the answer**: a model is only ours to ship once someone has confirmed the region serves it, and that question is now gates 20 and 20b against Azure. **What did NOT carry over is the proof technique, and that is a real loss recorded in D-410**: `asia-south1` sat in the Vertex hostname and in the `locations/` path, so residency was provable from the AST; `<resource>.openai.azure.com` names no region and residency is now asserted by config and confirmed by a human in the portal. |
| 14b H | **~~⏰ REPLACE `gemini-2.5-flash` BEFORE 16 OCT 2026~~ RETIRED BY D-410 — the deadline is gone with the model.** [closed 19 Aug 2026] | **This is the one gate whose retirement is a BENEFIT and should be read as one.** It was a dated obligation on two live surfaces, priced into D-400 with the date in front of the founder: the constant `GEMINI_DEFAULT_LLM_RETIRES` held 16 Oct 2026 as data and `tests/sarvam_model_identifier_test.py::test_the_shipped_gemini_model_has_runway_left` was going to turn CI red on 16 Sep 2026, thirty days out, naming the remedy. The constant, the test and this gate are all deleted, and BRD R-04 closes on every leg. `AZURE_OPENAI_DEFAULT_MODEL` carries no announced retirement this product is running against; if one is announced, the replacement for this gate is a dated row here plus a date-carrying constant, which is the mechanism that worked and is worth reusing rather than reinventing. **Wrong answer if that day comes**: widening a runway constant to quiet the test. |

| 14c L | **~~Does the ~10% non-global endpoint surcharge apply to `gemini-2.5-flash`?~~ RETIRED BY D-410 — it was answered NO, and then the vendor left the product** [D-403] | The finding stands as recorded and is worth keeping for the method rather than the number: Google's pricing page, read directly on the founder's browser, scopes the non-global differential to *"the Generally available Gemini 3 and later families of models"* from 1 July 2026, and the 2.5 Flash table carried ONE unified schedule where the Gemini 3 sections carried two. **The secondary sources were the imprecise ones** — two search summaries generalised it to "Vertex charges ~10% more on non-global endpoints" and dropped the model-family qualifier, which is exactly how a REPORTED-DOCS claim becomes a false premise (D-31/D-32). **The same question exists on Azure and is NOT answered the same way.** Azure's Regional Standard deployments genuinely do cost more than Global Standard — roughly 5–10%, with published examples up to +12% and +20% — and that premium lands on the residency posture itself, exactly as this gate feared and Vertex did not charge. It is carried as gate 20c and stated in D-410, and it is deliberately not laundered into a rounding note: a surcharge nobody has seen on an invoice would make every derived figure unfalsifiable in the expensive direction. |
| 15 H | **Does anything we report actually ARRIVE?** [NEW, D-169; ours, not Bolna's] | **Not the engine's account — ours, and it rides along here for the same reason gate 14 does: it needs no pilot, only the real hosts and the real credentials.** `scripts/check_observability_ready.py` decides everything a string can decide — DSN shape, endpoint shape, sample ratio, SDKs installed, both export filters in place — and **deliberately decides nothing about delivery**, because a check that probed a vendor from a build container and reported "reachable" would be the unverified-vendor-behaviour defect D-31/D-32 exist for. So delivery is verified ONCE, by hand, on each host that runs a service. **The test, in three parts.** (a) **Sentry**: with `SENTRY_DSN` set on the api host, raise a deliberate exception through a non-production route (or `sentry_sdk.capture_message("gate15")` in a `python -m` shell using the deployed settings) and confirm the issue appears in the Sentry project within a minute, tagged `service` and carrying the deploy's `release`. **Then read it**: confirm the exception VALUE is `[message withheld]` and no transcript, phone number or header from `DROP_HEADERS` is present — the scrubbers are unit-tested, this is the only proof they are the ones the vendor actually applied. (b) **OTel**: with `OTEL_EXPORTER_OTLP_ENDPOINT` set, place one call end to end and confirm a single trace spans voice-runtime → ARQ → worker → Postgres in the collector, that `exception.message` and `exception.stacktrace` are ABSENT from every span, and that the sampled fraction matches `OTEL_TRACES_SAMPLE_RATIO`. A trace that stops at a process boundary means the traceparent is not crossing Redis and the whole 2-minute-SLO diagnosis is unavailable. (c) **Alerting**: `notify.sh probe "delivery test"` from the DATABASE host, and confirm the mail lands in a real inbox — local acceptance is not receipt, and this is the same proof OPERATIONS §8 asks for. **Record**: the three outcomes plus what each host had configured, in `docs/evidence/`, the way the drill record is. **Fail** = anything configured that does not arrive; the fix is a configuration change and a re-run, never widening the check. **Blocked outside this repo** on: a Sentry project and DSN, a collector endpoint, and a verified Resend sender domain — the same three the pre-launch checklist blocks on, so this gate is owed exactly when §8 is. |
| 16 H | **~~Does the agent object honour `provider` or `family`?~~ ANSWERED AT SOURCE — what remains is whether the HOSTED platform behaves like the open-source server** [D-260; half-closed by D-400, 18 Aug 2026] | **The half that is closed.** Re-read at source on `bolna-ai/bolna` master, 18 Aug 2026: `family` is declared on their `Llm` model and **read by nothing**; the LLM client is chosen by `provider` against `SUPPORTED_LLM_PROVIDERS` (`bolna/providers.py`), and `LLMProvider` has **no `sarvam` member** — so D-36's Sarvam 105B never had a value here, which is the audit finding that prompted D-400. Their published OpenAPI corroborates by omission: `provider` and `family` carry **no `enum`** while `agent_flow_type` in the same schema block carries one and the telephony `provider` carries another, so the author uses `enum` when they mean closed. `provider: "custom"` routes to the OpenAI client constructed with our `base_url` (`bolna/llms/openai_llm.py`). **The follow-on work this gate authorised is DONE**: `ModelConfig` has `llm_provider`/`llm_base_url` and `engine/bolna.py::_llm_routing` sends them. **The half that is open, and it is now the only reason to run this gate.** The open-source server is strong evidence about SHAPE and is not the hosted contract. **The test:** create an agent via `POST /v2/agent` exactly as our adapter does, then `GET /v2/agent/{id}` and read the `llm_agent` block back. Record (a) whether `provider` survives the round trip and with what value, (b) whether `base_url` survives, (c) whether `family` survives, (d) whether `max_tokens`/`temperature` came back as ours or as their defaults `100`/`0.1`. Then place one call and confirm from the transcript which model answered. **Pass** = the read-back carries the `provider` and `base_url` we sent. `_agent_models` already reads both back, so this gate's answer arrives as data on the first real publish rather than as a note. Blocked outside this repo on: a Bolna account. Evidence: `docs/vendor/bolna/oss-harvest.md` §1. |
| 16b H | **~~Can Bolna hold a credential that EXPIRES?~~ ANSWERED BY DESIGN, then RETIRED BY D-410 — nothing we install expires any more** [D-402; closed by D-404; retired 19 Aug 2026] | D-404's answer was that a store holding a static string can hold one we REPLACE on a schedule, so the question was the wrong one. D-410 removes even that: **Azure OpenAI authenticates with a STATIC API KEY**, so there is no expiry to hold, no cadence to argue and no ceiling to work under. Keep the reasoning, not the machinery — the general lesson is that "the vendor cannot hold X" is worth re-reading as "must it hold X at all", and the answer here turned out to be no twice over. |
| 16c H | **~~WHICH credential-store entry does the hosted platform read `llm_key` from for a `provider: "custom"` leg?~~ RETIRED BY D-410 — we no longer use `provider: "custom"`, which is WHY D-410 exists** [D-404] | **THIS GATE IS THE REASON THE PRODUCT MOVED, so read it before proposing a custom-LLM route again.** A read-only sweep of the hosted dashboard and public docs (founder's browser, 19 Aug 2026 — this environment's proxy refuses every Bolna host) found: **(1) no Provider Keys UI in the current dashboard build** — the docs describe Dashboard → Developers → Provider Keys, the live `/developers` page offers only Bolna platform API keys, and `/provider-keys` redirects to `/dashboard`; **(2) the per-agent LLM provider dropdown offers `azure, openai, google, openrouter, deepseek, anthropic` and NO `custom`**; **(3) `POST /user/model/custom` takes `custom_model_name` and `custom_model_url` and nothing else**, so no credential can be attached to a custom model; **(4) nothing anywhere states which stored credential becomes `llm_key`**; **(5) the Google entry is one row, `GOOGLE` = "Your Google Gemini API key"**, with no mention of Vertex, a project, a service account or a region. That was never a proof — it was a sweep of the UI and the docs while our code used the API — but the honest reading was that the risk went up, and a leg whose whole credential path rests on an unverified premise is not a leg to build a product on. **The same sweep is also the positive evidence for D-410**: `azure` IS in that dropdown, Azure OpenAI IS in their published provider list, and their OSS `LLMProvider` carries both `azure` and `azure-openai`. The residual question — which FIELDS their Azure provider expects — is gate 16f. |
| 16d H | **~~Does the service account hold `roles/iam.serviceAccountTokenCreator` on ITSELF, and does the org policy allow a 12-hour lifetime?~~ RETIRED BY D-410 — there is no service account and no bearer to mint** [D-404] | Two GCP grants, both external, both now irrelevant: `generateAccessToken` self-impersonation and the org policy `constraints/iam.allowServiceAccountCredentialLifetimeExtension` existed only to stretch a bearer to 12 hours. Azure OpenAI takes a static key. **The discipline this gate demonstrated is worth keeping and is applied at gate 20b**: read the granted quantity back from the vendor rather than assuming the grant succeeded, and refuse by name when it is short. |
| 16e H | **~~Is the EXTERNAL dead man armed for the rotation loop?~~ RETIRED BY D-410 — the rotation loop is deleted, so the dead man is deleted with it** [D-408] | **A watchdog over nothing is worse than no watchdog, because it reports health.** A green check beside a job that no longer exists is a false statement repeated every four hours, and the incident it causes is the one where somebody believes it. `Settings.in_call_llm_heartbeat_url` is removed, and `apps/api/core/heartbeat.py` with it — D-408 extracted the ping so two callers could share one retry policy, and with one caller left it folds back into `scripts/host_heartbeat.py`. **The backup dead man is a different check on a different failure domain and is UNAFFECTED** — D-50/D-54, §4 below and `runbooks/backup-heartbeat-silent.md`. **Retire the vendor-side check too**, or it pages forever on a job that no longer exists. Do not read this retirement as a retreat from external observers: the argument that an observer must sit outside the failure domain it watches is unchanged and still binds anything with the same shape. |
| 16f H | **Does Bolna's `azure-openai` provider, configured with the four documented credential entries, actually run a call against OUR Azure resource? — the FIELD NAMES are settled; three questions are not** [D-410, narrowed by the docs mirror, D-417] | **THE NAMING HALF IS CLOSED AND THE OLD DEFAULT WAS WRONG.** VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/providers.md`: their Azure OpenAI provider requires FOUR entries — `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_VERSION` — under *"All these keys **must** be added for the respective provider."* `Settings.bolna_llm_credential_name` defaulted to `AZURE`, which appears nowhere in that table and would have authenticated nothing; it now defaults to `AZURE_OPENAI_API_KEY`, and the full list with each key's source in our settings is `apps/api/engine/bolna.py::_AZURE_PROVIDER_KEYS`. The wire provider string moved with it: **`azure-openai`, not `azure`** (`providers/llm-model/azure-openai.md`). `POST /providers` is a flat `{provider_name, provider_value}`, so four keys means four installs and `set_llm_credential` still writes ONE — the key — because it is the only one whose value is a secret we hold. **WHAT IS STILL OPEN, and each has its own observation.** **(i) `AZURE_OPENAI_API_VERSION` has no derivable value and the vendor contradicts itself about whether it is needed** — `providers.md` calls all four mandatory, while `azure-openai.md` describes the same connection as needing *"your Azure endpoint URL, API key, and deployment name"*, three things with no api-version among them. D-410 chose the v1 surface (`…/openai/v1`) **because** it has no `api-version`; a dated string belongs to the classic `…/deployments/{id}/chat/completions?api-version=…` surface. **RECORD WHAT THE CONSOLE ACCEPTS** — whether it takes the entry empty, whether it rejects the save without it, and whether a call succeeds either way. If it demands a real dated version, their Azure client is the CLASSIC surface and D-410's endpoint choice needs re-deciding. **Do not invent a date**; that is the defect this gate exists to prevent. **(ii) Is the per-agent `base_url` read at all?** Their documented Azure `llm_config` has no `base_url` row and the endpoint is a PROVIDER-level credential, so ours may be inert — which would put one link of the residency chain in THEIR store, where no read-back of ours can see it (`_agent_models` reads the endpoint off the agent, and an ignored `base_url` reads back identically to an honoured one). **(iii) Does `provider: "azure-openai"` route as documented on the live account? THE TEST:** with `BOLNA_API_KEY` set, `uv run python -m scripts.probe_bolna_providers` (writes the key entry only); install the other three by hand in the console; `GET /providers` and confirm all four persist and read back unchanged; publish one agent and read it back (gate 2/16); place ONE call. **Pass** = the agent answers in language AND **the Azure resource's own metrics show the request** — metrics, not merely a working call, because only they prove WHICH resource served it, which is the same reason gates 20/20c exist. **On a fail, do not change code first:** `bolna_llm_credential_name` is `applies: live`, so each attempt is a console edit, not a deploy. Fallback provider strings are `azure` then `custom`, in that order, one string each — and `custom` is now MORE clearly refused, not less: its entire documented flow takes a URL and a name and has no credential field anywhere, so nothing carries the `Authorization: Bearer` our v1 endpoint requires. **Wrong answers**: inventing an api-version, and putting the key anywhere it can be logged. Blocked outside this repo on: a Bolna account AND an Azure subscription with a deployed model. |
| 17 S | **Is `voicemail` a status, or only a flag?** [NEW, D-260] | Our `_STATUS_MAP` maps a `"voicemail"` status and `CallStatus` has a `voicemail` member, but **nothing sourced says that string is ever a status**. What is reported is a separate boolean `answered_by_voice_mail` on Get Execution, and the OSS engine treats voicemail as a HANGUP REASON (`HangupReason.VOICEMAIL_DETECTED`) — both facts about a call whose status is plain `completed`. If that is how the hosted platform reports it, our `voicemail` status is **unreachable** and every voicemail reads to a client as a normal completed call, which is wrong on the campaign screen and wrong for retry logic. **The test:** dial a number that goes to voicemail (with `ConversationConfig.voicemail` detection on, and once with it off). Capture the full Get Execution payload; record the `status` string, `answered_by_voice_mail`, and the hangup fields. **THE FIELD THIS ROW USED TO NAME DOES NOT EXIST (D-414):** there is no `hangup_detail` anywhere in the vendor's documentation — the names are `hangup_by`, `hangup_reason` and `hangup_provider_code` (the OpenAPI block in `api-reference/executions/get_execution.md`), and their hangup guide calls the last one `hangup_code` (`guides/post-call/list-phone-call-hangup-status.md`). Capture whichever spelling arrives. **THE FACTUAL HALF IS ALREADY ALL BUT ANSWERED AND THIS GATE IS NARROWED TO THE PRODUCT HALF:** the hosted docs show **no `voicemail` status in any of five independent status enumerations** and **no voicemail hangup reason** — the only two Bolna-side reasons documented are `inactivity_timeout` and `llm_prompted_hangup` — so the fact almost certainly rides on the boolean. What is left to decide is whether `answered_by_voice_mail` should surface as a distinct status on a client's campaign screen. **Pass** = we can say which field carries the fact. Fix if it is a flag: `_snapshot` reads it and maps to our `voicemail` status — deliberately NOT done on inference, because it changes what a client's screen says about calls we have never seen. Blocked outside this repo on: a Bolna account. |
| 18 S | **Transfer: is the built-in reachable the way we would need it?** [NEW, D-262] | `BOLNA_CAPABILITIES.transfer=False` was "nobody checked", then "the built-in is an in-call tool, read from their OSS" (D-262). **Half of this gate is now ANSWERED from the vendor's own hosted OpenAPI document and the value still does not move.** **(a) Does the hosted `/v2/agent` body accept a transfer tool, and under which key? YES — `key: "transfer_call"`.** `ApiTools.tools` is an array of `TransferCallTools` with `tools_params` keyed by the tool's `name`, and the destination is CONFIG inside `TransferCallToolParams.<name>.param` (a *stringified* JSON blob, example `{"call_transfer_number": "+19876543210", "call_sid": "%(call_sid)s"}`). **(b) Does any REST route transfer a live execution? NO** — none exists in the published paths, so the shape `VoiceEngine.transfer(call_id, to, warm)` names remains unimplementable and `False` is right for a stronger reason than before. **What is left is four live observations, and the first two are compliance rather than plumbing.** **(c) WARM OR COLD — the vendor documents it NOWHERE**: no page uses warm, cold, attended, blind or consultative, and the only briefing channel offered (the pre-call webhook) is explicitly *"fire-and-forget … never blocks or delays the transfer"*, which cannot be a warm handoff. Observe on a real call whether the caller is held while staff are briefed, and record it. **(d) Does the caller hear anything at the handoff, and is the transferred leg recorded with the caller's knowledge?** The transferred leg is a SEPARATE object with its own `recording_url`, `cost`, `duration` and `hangup_reason` (`TransferCallData`), served from its own route `GET /recordings/transfer/{execution-id}`. Capture a full `transfer_call_data` as an adapter fixture. **(e)** Does a transfer land on Exotel/Vobiz Indian PSTN, and what does the execution record say afterwards — status, `hangup_by` / `hangup_reason` / `hangup_provider_code` (**there is no `hangup_detail`; this row named one until D-414**), and the cost of BOTH legs? **(f)** If `pre_call_webhook_param` is used, `pre_call_webhook_url` **must** be set explicitly — left blank it falls back to the agent-level webhook URL, i.e. our post-call receiver, where an `in-progress` pre-call delivery collides with the genuine `in-progress` transition on `engine_intake`'s `(execution_id, status)` dedupe key. **Pass** = we can name the mechanism AND answer (c) and (d). **This is a design decision, not a flag flip**: a per-agent escalation number becomes engine config set at publish time and is NOT covered by the drift sweep (which proves the prompt, not the tool list); carrying the second leg needs new `ExecutionSnapshot` members plus decisions on separate metering and separate retention; and the disclosure question at the handoff is legal, not engineering (`docs/evidence/bolna-tools-integrations.md` §8.1). **Until then `engine/bolna.py::_check_transfer_leg` pages `engine_transfer_leg_unhandled` if a transfer leg ever appears** — the tool is enabled by a console toggle (*"Click + Add next to any tool"*), so it can arrive without a deploy. Blocked outside this repo on: a Bolna account. Evidence: `docs/evidence/bolna-tools-integrations.md` §1, `docs/vendor/bolna/oss-harvest.md` §5. |
| 19 H | **The Cartesia control plane, the hour an API key exists** [NEW, D-270; not a Bolna gate — it is the EXIT gate] | **Everything below is blocked on exactly one thing outside this repo: a Cartesia account.** Not a legal entity, not a regulator, not a signed term — an API key. Their docs are egress-blocked here, so `docs/vendor/cartesia/` was harvested from Cartesia's own SDKs instead, and `docs/evidence/vendor-cartesia-reconciliation.md` lists what that settled. These are the residue. **(a) THE STRUCTURAL ONE. The port work is DONE (D-280…D-282); what is left is one confirmation.** Their generated clients have no `POST /agents`, and `AgentSummary` carries no prompt, greeting or model: an agent is a DEPLOYED GIT REPOSITORY. `EngineCapabilities.agent_hosting` now says so (`control_plane | external_deployment`), Cartesia's `create_agent`/`update_agent`/`get_agent` and `publish_agent` refuse by name, the conformance suite branches on the capability, and the admin console does not offer the Publish button — `docs/evidence/engine-port-neutrality.md` is the account. **What the key settles: that `POST /agents` really 404s, and that a `PATCH` carrying `system_prompt` is ignored rather than applied.** Both are currently VERIFIED-SDK absences rather than observed responses. If they hold, the next decision is whether publishing becomes ADOPTION — `GET /agents` is real and `name` is documented unique — which is deliberately not implemented, because an adopted agent runs a prompt we did not write and cannot read back, so hard rule 5 would rest on a repository nobody in this deployment can see. That decision needs (b) answered first: adoption is only safe once our prompt reaches the call. Until then no Cartesia deployment can publish an agent at all, which is the correct direction to fail in and is now a named refusal rather than a 404. **(b) The three call paths nothing could source — and one of them now gates DIALLING AT ALL.** `POST /agents/calls` (outbound; REPORTED only, and `from_number_id` with it), `POST /agents/calls/{id}/end` (INFERRED; in `line` a call is ended from INSIDE by the agent), and whether `GET /agents/calls/{id}` returns a transcript without an `expand`. **The new question, and it is the load-bearing one: does the outbound body accept a SYSTEM PROMPT, or is the WebSocket Calls API the outbound path?** On this engine the agent record holds no prompt, so `CallContext.system_prompt` is the only home hard rule 5 has (D-282) — and the REPORTED outbound shape has no field for it, so `CartesiaEngine.start_outbound_call` refuses EVERY dial today rather than placing one with no truthful-answer rule on it. Read what `POST /agents/calls` actually accepts; if it takes a prompt, that field becomes `require_call_compliance_floor`'s `prompt_on_the_wire` argument and the refusal stops firing on its own. If it does not, Cartesia is not dialable from this repository and (a)'s adoption question is closed with it. Place one call, end it from outside, read it back. Also settle the recording: audio is an AUTHENTICATED download at `/agents/calls/{id}/audio`, so `ExecutionSnapshot.recording_url` stays None — decide whether the archive fetches bytes with the engine key or the field stays empty on this engine. **(c) Cost, which is now a COMMERCIAL question rather than an endpoint.** There is no per-call cost field and usage is an account-level DAILY credit meter (`GET /usage/credits`, grouped by capability/model/voice/api_key). `_cost` returns None and hard rule 7 has nothing to convert. Get the rate card in writing (D-94 prices Scale at $0.014/min) and decide whether per-call cost is DERIVED from our own duration times a contracted rate — which is a house number and must be stamped as one. **(d) Which end of `telephony_params` is which.** They document `from` as the AGENT's number and `to` as the CALLER's, which reads inverted on an inbound call, and there is no `direction` field. Place one inbound and one outbound call and read both. Wrong here means a client's CRM shows the wrong party. **(e) The webhook scheme.** Webhooks exist (`AgentSummary.webhook_id`); no SDK carries a signing helper; one search snippet describes an `x-webhook-secret` SHARED SECRET header, which is not an HMAC. `WEBHOOK_AUTH_BY_ENGINE["cartesia"]` is `"hmac"` because it is the only value that fails CLOSED, and both halves refuse every delivery today. Read the page, capture one real delivery's headers, and if it is a shared secret add a `shared_secret` member to `WebhookAuthMethod` and implement it in BOTH halves in one change — never in the receiver alone. **(f) How a document gets INTO the knowledge base.** The QUERY path is read at source and authenticates with a per-CALL agent JWT we never hold; neither generated client has a documents resource at all, so `attach_kb`/`detach_kb`/`list_kb` at `/agents/{id}/documents` are still inference. Upload one document by whatever route exists and record it. **(g) The repeat delete.** `DELETE /agents/{id}` is confirmed; what a SECOND delete answers is not, and `AgentSummary.deleted_at` hints at soft deletion — which would make `absent_is_success` the wrong shape. Same sub-check as gate 2's, run against Cartesia. **Record**: the outcomes in `docs/vendor/cartesia/`, at the evidence classes that file defines. **Fail** = any of (a),(d),(e) unresolved while a deployment runs `ENGINE=cartesia`; the fix is code, never a widened claim. |
| 20 H | **Is the Azure OpenAI resource ACTUALLY in South India? — the endpoint cannot tell you, and this is the residency weakening D-410 records rather than papers over** [NEW, D-410] | **`<resource>.openai.azure.com` names NO region.** Vertex put `asia-south1` in the hostname and in the `locations/` path, so `scripts/check_model_residency.py` could prove residency from the AST; Azure's custom-subdomain form cannot, because the region is a property of the RESOURCE and not of the URL. `AZURE_LOCATION` (`southindia`) is therefore an ASSERTION that one human confirms once, and the code says so where a reader will look. **The test:** open the Azure portal, find the resource named in `azure_openai_resource`, and read its **Location** field on the Overview blade; confirm the same value via `az cognitiveservices account show --name <resource> --query location`. **Pass** = both read South India, and the reading is filed in `docs/evidence/` with the date and who read it, exactly as the restore drills are. **Wrong answers**: inferring the region from the hostname (it carries none), inferring it from latency, and creating a second resource in another region "for failover" — a second region is a second residency posture and needs its own decision-log entry, not a checkbox. **AND NAME THE DEPLOYMENT AFTER THE MODEL IT SERVES** (`prod-gpt-4o-mini`, not `prod-voice-01`) — VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/providers/llm-model/azure-openai.md`: Bolna resolves the deployment NAME back to a model to pick its handling, and *"a name it cannot resolve is treated as a non-GPT-5 model and gets the wrong defaults"*. Free today, because that IS the correct handling for both members of `AzureOpenAIModel`, and a silent misconfiguration the day a GPT-5 model is adopted (D-417). **What the guard still proves and is NOT a substitute for this gate**: `AZURE_LOCATION` is the only spelling of the region in shipped code, no `Settings` field can carry a region, no Azure endpoint is constructible except through `azure_openai_base_url()`, and that builder cannot emit a non-India region. Blocked outside this repo on: an Azure subscription. |
| 20b H | **Does `gpt-4o-mini` have QUOTA in South India on this subscription — and how much?** [NEW, D-410] | **Model availability in a region and model quota in your subscription are two different facts, and only the second one lets a call succeed.** `gpt-4o-mini` is documented available in South India; nothing here has read a quota page for our subscription, and Azure grants TPM/RPM per region per subscription. This is also pilot gate 13's fourth leg: the effective concurrency ceiling is the MIN of engine, Sarvam, SIP trunk and this. **The test:** in the portal, Azure OpenAI → Quotas, region South India — read the TPM available for the `gpt-4o-mini` model family; or `az cognitiveservices usage list --location southindia`. Then deploy and make one chat-completions call through `azure_openai_base_url(resource)` with `Authorization: Bearer <key>` and read the response. **Pass** = a 200, and a TPM figure recorded beside the concurrency numbers from gate 13. **Fail** = a 429 with no headroom, or the model absent from the region's list: the remedy is a quota increase request (external, Microsoft's clock) or `gpt-4.1-mini` via `azure_openai_model` — **but 4.1-mini's availability in Indian regions is NOT confirmed** (its default quotas are Sweden Central and East US 2), which is exactly why it is a live switch and not a second shipped default. **Wrong answer**: deploying into a region that does have quota. That is the residency inversion wearing a capacity costume. Blocked outside this repo on: an Azure subscription. |
| 20c H | **Is the deployment REGIONAL STANDARD and not GLOBAL? — Global is the DEFAULT, Global processes worldwide, and no hostname will ever tell you which one you picked** [NEW, D-410] | **This is the residency trap of the whole migration, and it is one dropdown.** Azure's default deployment type is **Global Standard**, which routes requests to capacity anywhere in the world; **Regional Standard** is what keeps processing in the resource's region and is therefore what buys the residency claim this product makes to its clients. The two are indistinguishable from the endpoint, from the SDK, from the response body and from anything `check_model_residency.py` can read — a Global deployment inside a South India resource passes every automated check in this tree and is a residency breach. **It also costs money, deliberately**: Regional runs roughly 5–10% above Global Standard, with published examples up to +12% and +20%. That premium is a payable cost of the posture, not an accident, and it is the Azure analogue of the question gate 14c asked about Vertex and answered NO. **The test:** portal → the Azure OpenAI resource → Deployments → the deployment named in `azure_openai_deployment` → read **Deployment type**; or `az cognitiveservices account deployment show --name <resource> --deployment-name <deployment> --query "sku.name"`. **Pass** = a Standard (regional) SKU, not a Global one, recorded in `docs/evidence/` with the date. **Record the deployment NAME here too, and make it name the model** (`prod-gpt-4o-mini`): Bolna resolves that string back to a model to choose its handling, and an unresolvable name silently gets non-GPT-5 defaults (D-417, `providers/llm-model/azure-openai.md`). **Wrong answers**: Global Standard, Global Batch, DataZone (a DataZone deployment stays in a geography, not a region, and "Asia" is not India), and "we will fix it when we get residency questions" — the client DPA names South India from the day this ships. Blocked outside this repo on: an Azure subscription. |
| 20d L | **Does the v1 surface answer on the REGIONAL hostname `southindia.api.cognitive.microsoft.com`? — because if it does, the AST proof comes back** [NEW, D-410] | **Not a blocker; the only gate here that could make the residency posture STRONGER than it is.** Azure supports a regional endpoint form alongside the custom subdomain and documents the two as interchangeable, but the OpenAI-compatible **v1** surface is documented only on the custom-subdomain form, and custom subdomains are what Entra ID requires — so D-410 ships the subdomain form and records the regional one as rejected-for-now rather than rejected. The prize is concrete: a hostname carrying `southindia` restores exactly what Vertex had, a residency claim `scripts/check_model_residency.py` can prove from a string literal instead of one a human vouches for at gate 20. **The test:** against the same resource and key, `GET`/`POST` the same v1 path on `https://southindia.api.cognitive.microsoft.com/openai/v1/...` and compare the response with the custom-subdomain call. **Pass** = identical behaviour, in which case `azure_openai_base_url()` moves to the regional form, the guard gains a literal to check, and it lands as its own decision-log entry naming this gate as the evidence. **Fail** = anything other than identical (a 404, an auth difference, a required `api-version`), in which case the current shape stands and this row records why. **Wrong answer**: shipping the regional hostname on the strength of the docs' "interchangeable" without making the call — that is the premise class D-31/D-32 exist for. Blocked outside this repo on: an Azure subscription. |
| 21 H | **The Call Tab switches our publish body cannot state — and "restrictions ON" is a HAZARD to us, not a safety feature** [NEW, 20 Aug 2026, D-419] | For every published agent, open the Bolna Call Tab and confirm **Outbound call timing restrictions is OFF** and **no ingest source is configured**. Both are console switches with no documented "off" value our publish body can send — `calling_guardrails` is a bare object with no `nullable` and no default, `ingest_source_config` is a `$ref` with neither — so `_agent_body` cannot pin them the way it pins `auto_reschedule`, `dtmf_enabled` and `multilingual_config`. **Why ON is the dangerous direction:** their guardrail does not REFUSE an out-of-window dial, it HOLDS one and fires it later from their scheduler, which never re-runs `compliance.service.check_dispatch` — so the DNC list, the big red switch, the spend cap, the agent check and the hour are evaluated once and never again, against hard rule 5's requirement that DNC additions take effect before the next dispatch tick — and `campaign_dispatch._reap_stuck_dialing` would re-dial the same person after ~70 minutes. **An ingest source set to CSV or Google Sheet** puts the client's customer list on Bolna's side, and the Sheets variant requires a *publicly accessible* sheet (`customizations/identify-incoming-callers.md`), which is a DPDP breach on data we are the processor for. **Record what each agent's tab SHOWS, not what we expect it to show** — that is the whole point of a console-side gate. **Pass** = both off on every published agent, plus a written answer on whether either can be pinned from the API at all; if one can, it moves into `_agent_body` in the same change and this gate narrows to the other. Blocked outside this repo on: a Bolna account. |
| 22 S | **Which switch `auto_reschedule` actually IS — the vendor documents one field two ways** [NEW, 20 Aug 2026, D-419] | Not blocking: we refuse it under BOTH readings, and this gate exists so the refusal has a reason on file rather than a fear. `api-reference/agent/v2/create.md` says *"Automatically reschedule the call when the user asks to be called back at a later time"*; `agent-setup/call-tab.md` says *"Automatically retry failed calls later"*. On a pilot account, set it true on a throwaway agent and observe: does a caller asking for a callback produce a scheduled execution, or does a `no-answer` produce a second one? **If it is the RETRY reading**, it is a second ladder stacked on `campaign_dispatch._record_failure` and the refusal is permanent — two retry engines on one contact is the two-ways-of-doing-one-thing defect with a phone attached. **If it is the CALLBACK reading**, the refusal is still right (an in-call callback is placed by their scheduler and passes no gate of ours) but the in-call-reschedule window question in `guides/outbound/calling-guardrails.md` §"In-Call Reschedule Validation" becomes answerable — and it matters, because with no `calling_guardrails` set the window such a request is validated against is, in the vendor's own priority order, **the agent prompt**: a tenant-authored string. Blocked outside this repo on: a Bolna account. |
| 23 S | **The silence probe we never configured — what does a Telugu agent say when nobody speaks, and who wrote that sentence?** [NEW, 20 Aug 2026] | `check_if_user_online` defaults **true** and `trigger_user_online_message_after` defaults **10 s**, and we send `hangup_after_silence: 10`. On a test call, go silent and record: **(a)** does the agent speak a probe before hanging up, and at what second? **(b)** **what language does it speak it in on a Telugu agent, and what EXACTLY does it say?** **(c)** is the probe message settable through the API, or console-only? **Until (b) is answered, every Calevate agent may be speaking a sentence nobody here wrote to a caller who is on a recorded, disclosed call** — which is a smaller cousin of the hard-rule-5 problem D-418 found in the multilingual prompt switch, and the reason this is a gate rather than a curiosity. While you are there, settle which of `hangup_after_silence` and `check_if_user_online` / `trigger_user_online_message_after` wins when both are 10 seconds; nothing documents it (gate 4 carries the same question from the latency side). **The decision that follows — `check_if_user_online: false`, or a longer `hangup_after_silence` — is a founder call, not an engineering one**, because it trades a caller's patience against a dropped call. Blocked outside this repo on: a Bolna account. |
| 24 S | **`toolchain.execution`: `parallel` or `sequential`?** [NEW, 20 Aug 2026] | We send `parallel` (VERIFIED-OSS, from their own builder); the hosted doc's "smallest body that produces a working English conversation agent" sends `sequential`, twice. Both are in the enum and neither page explains the difference. Create one agent each way, place a test call on each, and record whether first-audio latency or turn behaviour differs. Whichever wins, the value and `tests/bolna_contract_test.py::test_the_toolchain_and_prompt_envelope_match_the_spec` move together — the test pins what we send, so changing one without the other is how a contract test stops meaning anything. Blocked outside this repo on: a Bolna account. |
| 25 H | **Can `/inbound/setup` link a NON-Twilio number, and what does `phone_number_id` look like?** [NEW, 20 Aug 2026, telephony audit; the vendor half of D-420] | `api-reference/inbound/agent.md` documents `POST /inbound/setup` as `{agent_id, phone_number_id}` and documents two options as Plivo-only (`allow_multiple`, `ivr_config`), while `guides/telephony/twilio-inbound-calls.md` says *"Inbound Agent functionality using APIs currently requires connecting your **Twilio account**."* Those cannot both be current. **This decides whether inbound linkage can ever be automated for us**: Plivo is the 160-series carrier and Vobiz the 140-series one, so if the API is Twilio-only then every Indian inbound DID is a permanent manual dashboard step — on the capability CLAUDE.md calls the headline (D-38). Call `POST /inbound/setup` with an Indian Plivo number's id and record **(a)** whether it 200s, **(b)** the exact shape of `phone_number_id` — `phone-numbers/get_all.md` types it `^[0-9a-fA-F]{32}$` (bare hex) while `inbound/agent.md` types the SAME field as a dashed UUID, and `byot-setup.md` returns a ULID-looking `01HQNUMBER111222333`. Whatever comes back is what `phone_numbers.engine_number_ref` must hold. **Pass** = a non-Twilio Indian number binds through the API and we can name the id format. **Fail** = inbound binding is manual, which is a product fact the onboarding runbook must carry, not a bug to hide. **AND SETTLE `from_phone_number` FOR A CONNECTED (not purchased) NUMBER IN THE SAME SESSION [added 21 Aug 2026, request-contract audit, F-9].** `calls/make.md:64` says the value *"Must be a number purchased in your Bolna account"*; `guides/outbound/making-outgoing-calls.md:197` says *"your purchased phone number **or your own connected phone number**"*. D-05 connects numbers through provider credentials rather than buying them from Bolna, so under the first reading every DLT-headered dial is a 400 and D-420's fix never places a call. One outbound call with a connected `+91` number in `from_phone_number` settles it. Blocked outside this repo on: a Bolna account with an Indian number. |
| 26 H | **What does a phone number actually COST us per month, in what currency, and does Truecaller have a price?** [NEW, 20 Aug 2026, telephony audit] | `guides/inbound/buying-phone-numbers.md` says *"$5/month … deducted automatically from your Bolna wallet balance each month on the renewal date"*, and `guides/inbound/truecaller-verification.md` says Truecaller is *"billed as per usage … Billed monthly from the date of verification activation"* **without ever naming a price**. Buy ONE Indian number and record: the wallet debit, **its currency**, the `renewal_at` value, and what `GET /phone-numbers/all` reports in `price` (a STRING, `example: $5.0`). Then ask Bolna, in writing, for the Truecaller per-number monthly charge, and decide whether it is absorbed, passed through at cost, or a priced add-on. **Nothing writes a `number_rental` usage event today and that is correct only while we buy no numbers through Bolna** — this gate is what turns that writer on, and hard rule 7 (NUMERIC, INR, never floats) applies to both charges. **This is also the cheapest instrument for gate 7's open half**: a wallet debit is a document Bolna issued us, in a currency it had to choose. Note that the phone-number schemas describe ONE price three ways — `search.md` "in USD" example 5, `buy.md` "in cents" example 500, `get_all.md` `$5.0` — which reconcile only under "cents = USD minor units, divisor 100"; that is the house convention on a NEIGHBOURING resource, not proof about `AgentExecution.total_cost`, and gate 7 still scores its own currency. Blocked outside this repo on: a Bolna account with funds. |
| 27 S | **Does a Truecaller "Delisting Pending" number appear as anything we can READ?** [NEW, 20 Aug 2026, telephony audit] | `guides/inbound/truecaller-verification.md`: *"once opted for delisting pending outbound and inbound calls on this number will be blocked"*, for 1–3 business days. **So a number can enter a multi-day state in which every dial fails and every inbound call is dropped, triggered by a click in a dashboard we do not own, with no webhook and no status field we know of** — and our dispatcher would keep handing that number to a campaign. Check whether `GET /phone-numbers/all` exposes any verification status at all. **If it does**, `phone_numbers` grows one enum value and the dispatcher learns to skip it. **If it does not**, the control stays procedural — nobody delists a number attached to a live agent — and that belongs in the onboarding runbook, not in a column nobody can fill. Do not model it before the answer: `dlt_status` (`pending`/`registered`/`blocked`) can express "delisting" only as `pending`, which already means "nothing has happened". Blocked outside this repo on: a Bolna account with a verified number. |
| 28 H | **Does `POST /v2/agent` accept `provider: "vobiz"`, or is 140-series unpublishable?** [NEW, 20 Aug 2026, D-420 audit] | ONE create call carrying `input`/`output` `provider: "vobiz"`. The vendor contradicts itself three ways and only a real request settles it: `api-reference/agent/v2/create.md:672-681` enumerates `twilio \| plivo \| exotel` with **no `vobiz`**; `guides/telephony/vobiz-outbound-calls.md:44` prints a worked body using it, but against **v1**; `patch_update.md:62-64` accepts it as a first-class `telephony_provider`. **PASS** = 2xx, the create enum is stale, and deriving the provider from the bound number's `series` is a one-line change in `_agent_body` (D-357). **FAIL** = 400, and the publish path grows a second call (create on `plivo`, then PATCH), which opens a window where a live agent runs the wrong carrier and needs its own decision row. | **H, because it decides whether a product line exists.** 140-series is the promotional class, and promotional is what an outbound SMB campaign IS. Today every agent we publish is hardcoded `plivo`, which is correct for 160-series and wrong for 140 — so a 140-series campaign cannot be published at all, and no amount of our own code changes that until this is answered. Needs the Bolna account (gate 16f's blocker); costs one API call and no telephony spend. **THE QUESTION HAS CHANGED AND THIS ROW IS NOW TWO HALVES (21 Aug 2026, D-431).** `vobiz` IS a documented enum member — on `PATCH /v2/agent/{agent_id}`'s `agent_config.telephony_provider` (`enum: [twilio, plivo, exotel, vobiz, sip-trunk, default]`, `bolna-findings/mirror/pages/api-reference/agent/v2/patch_update.md:276-290`, restated in prose at `:64`), a field that appears in NO `POST`/`PUT` schema. So run BOTH: **(i)** the create call above, which is the original question; and **(ii)** `PATCH` a published agent to `telephony_provider: "vobiz"`, then `PUT` it the way `publish` does, and re-read. **(ii) is the half that decides the design**: `PUT` replaces the entire agent configuration (`patch_update.md:9`) and `_agent_body` always sends `input`/`output` `provider: "plivo"`, so the expected answer is that the PATCH does not survive the next publish — which makes a per-agent telephony column a PATCH sequenced AFTER every publish, not a literal edited in `_agent_body`. |
| 29 H | **Where do the two phone numbers actually live on an execution?** [NEW, 21 Aug 2026, response-contract audit] | `TelephonyData` declares `to_number`/`from_number` (`bolna-findings/mirror/pages/api-reference/executions/get_execution.md:285-294`) and ONE example carries them there — a schema-shaped one, every property in schema order with `"id": 7432382142914` and `"transcript": "<string>"` (`guides/post-call/list-phone-call-status.md:120-131`). The **three** examples that read like captured traffic put them at the TOP LEVEL as `user_number`/`agent_number` and carry NEITHER inside `telephony_data`: `executions/get_execution.md:41-42,51-58`, `quickstarts/api.md:246-247`, and `quickstarts/batch.md:138` (which has `user_number` and no `agent_number` at all). **Our half is done and does not wait on this gate**: `_party_numbers` reads the documented spelling first and the captured spelling only where that yields nothing, so a payload of either shape answers correctly today. **What the gate settles is the INBOUND polarity, which is the one thing nothing observes.** Their names are role-based — *"`recipient_data.user_number` — Referencing the caller's phone number"* (`graph-agent/variables.md:82`) — while `from`/`to` are dial-based, so the mapping flips with direction; the OUTBOUND arm is corroborated by literal (`calls/make.md:18,38` uses the same two numbers as `recipient_phone_number` and `from_phone_number`), the inbound arm is not. **Pass criteria**: fetch ONE completed INBOUND execution and one completed OUTBOUND execution and record, for each, which of the four spellings carried a number and which side it was. **Why it is H**: if both spellings can be absent, `ExecutionSnapshot.from_e164`/`to_e164` are NULL and three things fail silently — the opt-out worker has no DNC subject (`apps/workers/optout.py`), a DPDP erasure matching `calls` on those columns finds nothing (`apps/api/compliance/export.py`), and transcript redaction is handed an empty phone list. If the polarity is inverted on inbound, the opt-out worker would add OUR OWN published number to DNC. Do not infer either answer from an outbound capture. |
| 30 S | **Does `GET /v2/agent/all` paginate?** [NEW, 21 Aug 2026, request-contract audit; sharpens D-430] | With ≥3 agents on the account, call `GET /v2/agent/all?page_number=1&page_size=2` and then `?page_number=2&page_size=2`. Record: **(a)** whether the parameters are accepted at all — a 400 here means the roster walk must revert to an unparameterised single request and the truncation risk becomes a REPORTED gap again; **(b)** whether page 2 returns **different** agents; **(c)** whether an unparameterised `GET /v2/agent/all` on an account with >20 agents returns 20 or all of them. **(b)=different** closes D-430's ambiguity and makes `complete=True` earnable on a large account; **(b)=identical** confirms the endpoint does not paginate and the walk's no-progress exit (`next_link_no_progress`) is the permanent behaviour rather than a degraded one. While recording it, also `GET /providers` and count the rows against the number of keys the account has connected: if the two differ, that store paginates too and `set_llm_credential`'s before/after count is unreliable. **Why S**: nothing is blocked by the answer — the walk is already correct under both readings and refuses to claim completeness in the ambiguous case; the gate turns an unclaimable `complete=True` into a claimable one. Blocked outside this repo on: a Bolna account with ≥3 agents. |
| 31 H | **The wallet, and the fact that an empty one looks like a fleet of failed calls** [NEW, 21 Aug 2026, response-contract audit] | `GET /user/me` returns `wallet` — *"Current wallet balance of the user"* — and `concurrency: {max, current}` (`bolna-findings/mirror/pages/api-reference/user/info.md:68-87`). Nothing in this tree calls it. Two consequences, and the first is the H: **`balance-low` is a documented TERMINAL execution status** (`api-reference/errors.md:56`), so an account whose wallet empties fails every dial with a status `_STATUS_MAP` sends to `failed` — each campaign is simply recorded as having failed, with no cause anywhere and no halt. Second, `PLATFORM_LINES_TOTAL = 10` in `apps/workers/campaign_dispatch.py` is our typed-in belief about `concurrency.max`, and the vendor says that number moves without telling us: *"Starts at 10 concurrent calls, **scaling automatically with monthly usage**"* (`pricing/outbound-calling-concurrency.md:18`). **Pass criteria**: one authenticated `GET /user/me`, recording the shape and units of `wallet` (which currency? the same open question as gate 7) and the live `concurrency.max`/`current`. **BLOCKER: a Bolna account — nobody in this repo can create one.** **What it unblocks, in order**: a normalized `VoiceEngine` balance/concurrency read (hard rule 2 forbids `apps/workers/` seeing the payload), a pre-dispatch balance check that turns a silent fleet failure into a named halt, and `concurrency.current` as a free cross-check on the dispatcher's own `total_active`. |
| 32 S | **Execution `status` vocabulary on the LISTING endpoint** [NEW, 21 Aug 2026, failure-contract audit, D-426] | `api-reference/errors.md:39-56` publishes the execution enum and `_STATUS_MAP` covers all sixteen values. But `api-reference/pagination.md:34-45` shows listing rows carrying `"status": "success"` and `"status": "failed"` — a vocabulary that is not in that enum, in a code block, so schema-beats-prose cannot break the tie. `_STATUS_MAP.get(raw_status, "failed")` degrades an unmapped status **silently**, so if the pagination page is real rather than filler, every reconciled call is recorded `failed`, metered as a loss and never repaired. **Read one real page of `GET /v2/agent/{id}/executions` on the pilot account and record the exact `status` strings.** Cheap and decisive. Until then, consider logging an unmapped status rather than defaulting quietly. |
| 33 S | **Does Bolna send `Retry-After` on a 429, and what does their retry of a webhook actually do?** [NEW, 21 Aug 2026, failure-contract audit] | Neither is documented anywhere in 333 pages (searched `retry-after`: zero hits). We honour a `Retry-After` as a floor if one arrives and fall back to full-jittered exponential backoff otherwise, so the first half costs nothing to be wrong about. The second half bounds D-31: *"Bolna retries on non-2xx or timeout"* (`api-reference/limits.md:61`) with **no published count, schedule or ceiling** — so measure it on the pilot (return 500 to one delivery and record how many redeliveries arrive and over what span). It decides whether the 10-minute poller is the guarantee of record or merely the backstop. **Gate 6 already frames the same experiment** ("observe whether ANY retry arrives"); this row is the one that records the COUNT and the SPAN, which is what decides the poller's standing. |
| 34 S | **What does `agent_status: "seeding"` mean, and can a `seeding` agent take a call?** [NEW, 21 Aug 2026, response-contract audit] | `AgentV2.agent_status` is an enum of `seeding` \| `processed` (`bolna-findings/mirror/pages/api-reference/agent/v2/get.md:66-73`). The word appears in the mirror in exactly four places and all four are that enum — the vendor never defines it, never says how long it lasts, and never says whether a `seeding` agent answers. `get_agent` does not read it, so a publish read-back or a half-hourly drift sweep landing on a still-seeding agent scores its prompt, greeting and models as though the agent were settled. **Pass criteria**: create one agent, read it back immediately and then at intervals, and record (a) whether `agent_status` is ever `seeding`, (b) for how long, (c) whether `agent_prompts`/`tasks` are complete while it is, and (d) whether `POST /call` against a `seeding` agent succeeds. **What it would change**: a `seeding` verdict from the read-back would become `unreadable` rather than a scored comparison — which is a new member on `AgentSnapshot`, not an adapter tweak, so nothing is built until (a) and (c) are answered. Refuse to guess the meaning: an agent published green on a read-back taken too early is exactly the failure `AgentSnapshot.system_prompt_readable` exists to prevent. |

Parallel ask to Sarvam (not a Bolna gate): **is the Sarvam LLM genuinely free per
token** — permanent, promotional, or rate-limited? **What turns on the answer is smaller
than it once was, twice over.** D-400 moved the in-call LLM leg off Sarvam and D-410 has
moved it again, to Azure OpenAI South India, so this no longer decides the leg — it
decides how good the FALLBACK is, and how much a value tier could undercut the default
(§10.1's ladder). It is also the one route by which Sarvam could return as an in-call LLM,
and D-410 records why it would not: Sarvam has no member in Bolna's `LLMProvider`, so
reaching it means `provider: "custom"` — the credential path gate 16c put in doubt. Sarvam
continues to run the first extraction pass permanently (`GEMINI_EXTRACTION_DEFAULT is False`)
and the whole speech stack, which no answer here changes. Also pin Bulbul V3's "beta pricing" (₹30/10k chars) — beta prices move.

### Running it — 1, 2, 6 run on credentials alone; 4, 7, 8, 13 run on an inputs file; 3, 5, 9-12 are human

The table above is the specification; `scripts/pilot/` is the part of it a machine can
decide. Start with the shopping list, on day one and not on day three:

```
uv run python -m scripts.pilot reachability   # can this machine reach api.bolna.ai at all?
make pilot-preflight     # uv run python -m scripts.pilot preflight
make pilot               # DRY RUN of gates 1, 2, 6 — places no calls, spends nothing
```

**Run the reachability probe first.** It needs no key, no credit and no number, and it
answers the one question that invalidates the whole session: a sandboxed or corporate
network that refuses the CONNECT to `api.bolna.ai` blocks every API gate, for a reason
that has nothing to do with Bolna. (The environment this harness was written in is
exactly such a network.) It is also the first row of the preflight; exit 4 means
unreachable, and skipping it with `--no-network` reports it UNVERIFIABLE rather than
assuming it is fine.

Preflight names every missing credential and prerequisite, which gates each one blocks,
and where to get it; it reports a key as present or absent and never prints one. `make
pilot` executes gates **1** (webhook trust), **2** (API provisioning) and **6** (webhook
loss + poller recovery) through the `VoiceEngine` adapter — never raw HTTP, because the
pilot's job is to verify the adapter we will ship, not a curl that bypasses it.

Placing real calls requires an explicit opt-in and a ceiling, and refuses to run against
a production-shaped configuration:

```
uv run python -m scripts.pilot run --gates 2 --to +91XXXXXXXXXX \
    --yes-place-real-calls-and-spend-money --max-calls 2 --out pilot-results.json
```

Gate 1 needs the raw deliveries your tunnel received (`--webhook-capture <file>`,
repeatable); gate 6 needs the execution ids whose webhook you dropped
(`--missed-execution <id>`) plus what you saw with your own eyes
(`--attest gate6.call_continued=yes`, `--attest gate6.retries_observed=0`) — those two
are recorded as operator attestations, never as measurements — and the dashboard's own
execution count for the same window (`--attest gate6.executions_in_window=<n>`), which is
the ONE independent check on whether List-Executions truncated: our own listing cannot
testify about what it left out. **Exit 2 means "nothing
went red and nothing was verified either"**; only exit 0 is a pass. Every gate result is
PASS, FAIL or **NOT RUN**, and NOT RUN never renders as green.

What the harness found before any credentials existed, and what it therefore cannot do:

- gate 2's **`scheduled_at`** criterion is not expressible through `VoiceEngine.
  start_outbound_call`, and the Bolna adapter's `POST /call` body carries no such field.
  Gate 2 cannot report a full pass until the contract grows one.
- gate 2's **"attach number"** step cannot run through the adapter at all —
  `BolnaEngine.provision_number` raises `engine_capability_unverified` (M1 defers
  numbers to the telephony provider), so that step is a dashboard action, which is what
  "via API only, no dashboard" forbids.
- gate 2's **"update prompt"** can now be scored **APPLIED**, not only ACCEPTED. The
  contract grew a read-back (`VoiceEngine.get_agent` → `AgentSnapshot`), and gate 2 emits
  a second row, `update_prompt_applied`: `update_prompt` records that the vendor took the
  PUT, `update_prompt_applied` records that the agent the engine HOLDS carries the prompt
  we wrote (a marker in the prompt text, so the engine's own rendering — the prepended
  disclosure line — does not break the comparison). A 2xx write that changed nothing is
  now a red row instead of a green one, which matters most for the part of the prompt a
  client is legally answerable for. What it still does NOT prove is that a RUNNING call
  uses that prompt; the `user_data` round-trip row remains the live-call evidence, and
  the two are deliberately separate rows.
  **The read-back ROUTE is now VERIFIED-OAS; what it RETURNS is still worth recording
  (D-350).** `GET /v2/agent/{agent_id}` is in the vendor's pinned spec, returning
  `AgentV2` — which declares `id`, `agent_name`, `agent_type`, `agent_status`,
  `created_at`, `updated_at`, `tasks`, `ingest_source_config` and `agent_prompts` at the
  TOP LEVEL, with no `agent_config` wrapper. So the prompt really does live where
  `bolna._agent_system_prompt` looks for it (`agent_prompts.task_1.system_prompt`), and
  the model read-back really does hang off `tasks[0].tools_config` — both confirmed rather
  than inferred. **What the schema does NOT declare is `agent_welcome_message`**, which is
  the field the greeting judge needs and which the vendor's own PATCH example writes. So
  record three things from the run: whether the GET answered 2xx, whether the prompt came
  back where we look, and **whether the welcome message came back at all** — if it does
  not, `_agent_greeting` reports `unreadable` forever and no publish can ever verify the
  disclosure sentence against the engine, which is a compliance-visible gap rather than a
  cosmetic one.
- gate 8's **dangling-`rag_id`** question (D-41) is now askable through the adapter and
  is answered by the run rather than by a note. The read-back supplies gate 8's
  `agent_ref_reader` automatically (`knowledge.agent_ref_reader_from_engine`), so after
  the probe deletes the knowledge base it reads the AGENT object back and reports whether
  the handle survives. **What is still unknown is the field name**: nothing published
  says Bolna's agent object references a `rag_id` at all, so `bolna._AGENT_KB_REF_KEYS`
  is a guessed set of names and the adapter reports
  `AgentSnapshot.knowledge_base_refs_readable = False` when none of them appears. That
  declination is scored INCONCLUSIVE, never as a cleared reference — "we could not find
  the field" and "the reference was cleared" are opposite answers, and only one of them
  adds a second call to `detach_kb`. One captured agent payload settles it.
- gate 1's edge half (nginx rejecting a non-allowlisted source) needs an HTTP POST from
  another host against the deployed receiver; the harness exercises the in-app half only.
- gate 6's **pagination** criterion is now MEASURED as far as our side can measure it,
  and declared as an assumption for the rest. `list_executions` returns an
  `ExecutionListing`, not a bare list: `complete=False` plus a reason
  (`explicit_more` where the payload claims more and names no page we can fetch,
  `full_page_suspected` where a full page came back with no `has_more` at all,
  `page_cap_reached` where our own bound stopped a walk that was still producing, and
  `next_link_no_progress` where a page we had not read re-served only rows we already
  had) is what the adapter says when it cannot vouch
  for the window, and `reconcile_executions` turns that into an alert, a metric
  (`reconciliation_listing_incomplete`) and a job result that does not read as a quiet
  tick. Two former values, `next_link_loop` and `empty_page_with_next`, are GONE (D-360):
  both could only arise from following a continuation URL the vendor handed us, which no
  adapter does any more, and a documented alert value no code can emit sends an operator
  hunting a condition that cannot occur. **What the pilot still has to settle is the
  vendor's behaviour itself** — not WHETHER Bolna paginates, which their OpenAPI spec now
  answers (`page_number`/`page_size` max 50/`has_more`, D-350), but whether the server
  honours it: whether `has_more` tells the truth and whether `from` really bounds the
  window. Nothing in-process can settle that: a listing
  cannot report what it omitted, and a pilot window holds far too few executions to reach
  any plausible page size, so `complete=True` here means "nothing in the response
  suggested otherwise". The dashboard count (`gate6.executions_in_window`) is the only
  independent evidence, and until a saturated listing has been captured the page-size
  heuristic is a guess about round numbers rather than knowledge.
- gate 7's **currency** criterion is now answerable in part from our own snapshot.
  `BolnaEngine._cost` reads the currency the payload states and records
  `CostBreakdown.currency_stated` — True = the vendor said so, False = we fell back to
  the house assumption (`_ASSUMED_CURRENCY = "USD"` cents, read off docs.bolna.ai and
  never confirmed on a live account). A currency the adapter cannot convert is REFUSED
  rather than converted at the dollar rate, so a wrong cost basis cannot ship silently.
  The independent check remains the vendor's own reported total, supplied by the
  operator: a ratio of exactly 100 is the signature of the cents assumption being wrong,
  and every INR row inherits the factor. **What the pilot still has to settle is the
  `currency_stated=False` case** — if Bolna never names a currency, the assumption stays
  load-bearing and only the dashboard figure can falsify it.
- gate 7's **transcript** criterion now sees PARTIAL loss.
  `bolna.parse_transcript` returns `(turns, unparsed)` and the snapshot carries
  `transcript_lines_unparsed`, so a line the parser could not place — an unprefixed line
  before any turn exists, a prefix with an empty body — is counted rather than dropped.
  The harness scores any non-zero count, in addition to the total-failure signature (zero
  turns on a `completed` call that carried audio) and the per-turn structural defects. A
  COUNT, not the lines: transcript text does not cross the engine boundary except as a
  `TranscriptTurn` (hard rule 6).
- gate 7's **time-to-`completed`** has a post-hoc route, and it is an UPPER BOUND.
  `ExecutionSnapshot.billable_ready_at` carries the vendor's `completed_at` where the
  payload has one, otherwise the instant we OBSERVED the execution already complete —
  which is bounded by the poller's tick and by how long after the call anything looked,
  so it can only over-state. The harness therefore still prefers a LIVE poll from an
  operator-supplied disconnect instant when one is given. `now - ended_at` remains
  deliberately unused: it is a bound that grows with how long the operator took to run
  the harness.

**Which gates the harness can execute, precisely.** Nine of the thirteen are registered
in `scripts/pilot/`, in two classes, and the difference between them is what an operator
has to bring:

- **1, 2, 6 — credentials and a tunnel.** `make pilot` runs these and nothing else by
  default; they need the API key, and gates 1 and 6 additionally need the deliveries and
  execution ids named above.
- **4, 7, 8, 13 — plus one JSON inputs file each**, because their inputs are OBSERVED by
  a person rather than measurable from our side: gate 4's stopwatch samples and the
  pasted `latency_data`; gate 7's observed disconnect instant and the vendor's own cost
  figure off the dashboard (the dashboard figure is the only INDEPENDENT check on the
  currency: the adapter records whether the payload stated one, but where it did not,
  reading our own assumption back is the harness agreeing with itself);
  gate 8's Telugu retrieval scores, tool-call latencies, per-turn token counts and batch
  outcomes. Each reads `docs/evidence/gate<n>-inputs.json` (gate 4:
  `gate4-observations.json`), overridable with `CALEVATE_PILOT_GATE<n>_INPUTS`. **An
  absent file is NOT RUN with the path in the reason — never a pass, and never a zero.**
  Gate 13 also needs a call budget: it dials to find the ceiling.
- **3, 5, 9-12 are human and always will be**, and the harness says which kind rather
  than leaving a blank row: 3 and 5 are LISTENING gates (Telugu recognition quality;
  barge-in and end-of-utterance judged by ear), 9-12 are written answers and support
  threads. `--attest` records what a human observed, labelled as an attestation and never
  as a measurement.

Any gate with no implementation registered is still reported by number as NOT RUN, so a
slice that regresses out of the registry is visible rather than silently absent.

Deliverable: filled scorecard committed to `docs/evidence/bolna-pilot-scorecard.md`
(template in repo), with captured payloads saved as adapter fixtures. Passing closes the
D-31 gate and A-1/A-8; a red hard gate reopens the engine decision (no fallback engine
is designated — D-31).

## 3. Per-Client Regression & Eval Harness (the differentiator)

Principle (industry norm): run the suite on EVERY prompt/model/tool/KB change — a small
edit can break a working flow; behavioral coverage (task completed? interruption handled?
no hallucinated tool call?) is what generic uptime monitoring misses.

Structure per client:
- **Scenario suite** (start minimal, grow to 50–100): v1 mandatory five —
  (1) happy path (book/qualify end-to-end), (2) interruption/barge-in mid-sentence,
  (3) tool-call correctness (booking with valid slot), (4) out-of-scope ⇒ T4 refusal +
  follow-up tag, (5) compliance (disclosure spoken; DNC request honored; no cross-sell on
  service agent). Add per-vertical + red-team (injection attempts) as suite grows.
- **Fixtures**: 30+ recorded Telugu/Hindi/mixed utterances incl. hard names, numbers,
  addresses; replayed via engine web-call API or TTS-into-call.
- **Scoring**: transcription accuracy on entities; task success (assert on extraction
  output + tool calls); latency percentiles; LLM-judge rubric for tone/language.
- **Wiring**: suite runs in CI on prompt_versions publish and nightly against live config;
  red result blocks promote; report stored per run (client-shareable PDF = sales asset:
  "we regression-test your agent before every change").

## 4. Observability & Alerting

Dashboards: per-tenant call volume/answer rate/outcomes; latency stage breakdown
(stt/llm_ttft/tts_ttfa/turn p50/p95); post-call pipeline lag; webhook delivery health;
spend vs caps; KB retrieval hit-rates + knowledge-gap list (T4 queries).
LLM tracing (a trace per call, prompt version + token costs attached) is a **named gap,
not a component**: the Langfuse configuration was removed rather than left looking wired
(D-49, TRD §2), so nothing records per-call token cost or the latency breakdown today.

**A component that is DECLARED on and silently off is the failure this section is worst
at seeing, so it has a ladder now (D-169).** `uv run python -m
scripts.check_observability_ready` — in `make guardrails` and in CI, and runnable by an
operator against a host's own environment — reports Sentry, OTel and Langfuse one at a
time in three rungs: **not configured** skips cleanly and says what is not happening;
**configured and consistent** is ready; **configured and broken** FAILS naming the
setting. What it catches is the class nothing else could: a DSN whose project id is a
typo or a slug, `sentry-sdk` left unlisted in the deployment's dependency group, an
`OTEL_EXPORTER_OTLP_ENDPOINT` that already ends in `/v1/traces` (this repo reads the BASE
endpoint and appends the signal path, so the exporter would POST to
`/v1/traces/v1/traces` and 404 forever on a background thread), a sample ratio of 0.0,
and a `RELEASE_VERSION` still reading `dev` in production so no report names its build.
Every one of those is type-valid, so the ops console's bounds check (D-101) cannot see
any of them. The same predicates run at BOOT — `observability_component_misconfigured`,
carrying problem CODES and never values — so a host nobody ran the script against still
says it. It also holds the two filters hard rule 6 rests on (`before_send` +
`before_breadcrumb` on the error path, `_RedactingSpanExporter` on the trace path) and
the D-49 decision that no Langfuse client exists, because the v3 SDK is a second
OpenTelemetry pipeline and a direct client would export the extraction prompt — a raw
transcript — past our scrubber.

**Read its green correctly: it means "nothing in this configuration can be shown to be
broken", never "errors are arriving".** It makes no network call and never will; whether
a Sentry event is ACCEPTED, whether the collector answers, and whether a human sees
either is **§2 gate 15**, performed once against the real hosts.

**Alerts, as built (D-49).** The sinks above were "WhatsApp/email to Sri" and for a long
while were neither — `alert()` wrote a structured ERROR log and stopped. It now still
writes that log FIRST and unconditionally (the durable record) and then delivers **by
email**, through the same transport as hot-lead notifications, on a daemon thread off the
request path. No WhatsApp sink: that is a BSP decision (see the open items in ROADMAP §6),
and a second delivery mechanism is a second thing to be broken on the night it is needed.

- **Configuration**: `ALERTS_EMAIL` plus a working email transport — `EMAIL_PROVIDER`
  and its credential (`resend` + `RESEND_API_KEY`, which is ENV-ONLY on every host —
  DEPLOYMENT §6 carries the reason; `smtp` + `SMTP_HOST` remains the
  escape hatch). A non-local service booting with no recipient logs
  `alert_delivery_unconfigured`, and one with a recipient but no transport logs
  `alert_delivery_has_no_transport` **with the reason** — `no_email_provider`,
  `no_resend_api_key`, `no_sender_address` or `provider_not_implemented:<name>` — both at
  boot, so a deployment where alerts reach nobody fails §8's gate visibly rather than
  silently. Boot cannot check the one thing that is not a setting: an unverified sender
  domain is refused per send (403) and appears as `email_sender_rejected` at ERROR.
- **Noise bounds**: per-fingerprint repeat suppression keyed on `stage:code`, 15 minutes
  (Alertmanager's `repeat_interval`, tightened because there is one operator and no
  incident console), plus a global token bucket at 20/hour with a burst of 6. Both count
  what they drop and report the count in the next delivered body, so "still broken, 199
  times" never reads as "happened once". A FAILED delivery clears the suppression stamp —
  the window means "a human was told".
- **What it does not touch**: no outbox, no Redis, no database. The alarms that matter
  most are the ones saying those are broken.
- **Two alarms about the RELIABILITY path say different things and must not be confused.**
  `outbox_dead_letter` means messages need an operator (`POST /v1/ops/outbox/replay`);
  `outbox_queue_unreachable` means the dispatcher could not reach Redis at all and handed
  the batch back with a backoff, so nothing is lost and there is nothing to replay —
  fix Redis, the next tick drains it. Without the second code an outage was reported as N
  dead letters, which is a page that asks for exactly the wrong action
  (`runbooks/webhook-delivery-failures.md` §3).
- **The ops console publishes the DEFERRED count beside the DLQ depth, and the pair is
  the diagnosis.** `GET /v1/ops/platform` returns `outbox_dead_letters.deferred` from the
  same aggregate as `depth`, so they are one instant by construction. `depth: 0,
  deferred: high` is an outage in progress; `depth: high, deferred: 0` is one that already
  spent the retry budget and now needs a replay. Until this field existed the console
  showed only `depth` — so for the whole five minutes of downtime the backoff buys, an
  operator opening the ops screen mid-incident read a green "Nothing is dead-lettered",
  which was TRUE and which is the worst kind of wrong number. A small non-zero `deferred`
  on a busy platform is not an incident: a claimed in-flight message is `pending` with a
  future `locked_until` too, and telling the two apart would cost a column on the hot
  dispatch path to sharpen a figure nobody alerts on.
- **A per-message publish failure now waits as well.** `mark_outbox_failed`'s retry branch
  writes the same backoff `defer_outbox_claim` does (`OUTBOX_RETRY_BACKOFF_S`, 30s per
  attempt spent, capped at 300), so a receiver that is merely restarting no longer costs a
  message its whole five-attempt budget in fifty seconds. Poison still reaches the DLQ —
  it takes about five minutes rather than one, which is the right trade because nothing is
  waiting on a poison message. The difference from the systemic case is unchanged and is
  what `last_error` records: a systemic deferral does not count against the poison budget,
  a per-message one does.
- **`reconciliation_repairs` carries a `kind`, and the two kinds are different
  incidents.** `missing_call` is a webhook the vendor never delivered (D-31's at-most-once
  delivery doing what it does — expected at a low rate, alarming as a trend);
  `unfinished_pipeline` is a delivery we DID receive and then dropped on our own side, so
  a call had a `completed` row with no transcript, extraction, lead or usage event until
  the poller re-drove it. A non-zero rate of the second is OUR bug, and it is worth
  reading against `postcall_pipeline_stalled`, which reports the same population from the
  other end: the alarm names calls the pipeline still owes an extraction, the poller is
  what repairs them, and both are keyed off the SAME ten-minute deadline
  (`pipeline.PIPELINE_STALL_AFTER`, imported by `dispatcher.STALL_AFTER_MINUTES`) so a
  call cannot be late for one and current for the other.
- **`engine_agent_drift_detected` says a client's phone line is speaking a script nobody
  approved (D-123).** `sweep_engine_drift` reads the 25 stalest live agents back off the
  engine every half hour (:07 and :37, off the round-numbered ticks) and records what the
  vendor is actually holding. It fires on a PROVEN mismatch only. `unreadable` and
  `unreachable` are counted and recorded per agent and deliberately do NOT alert — "the
  engine is running something else" and "we could not read the answer" are different facts
  and only one is evidence, and an alarm that fires whenever the vendor has a slow
  afternoon is one somebody mutes long before it catches a real dashboard edit.
- **The sweep RE-PUBLISHES NOTHING, and the console offers no button that would (D-123).**
  Overwriting a drift overwrites whatever the vendor's own console was used to change,
  plausibly the correct emergency edit made while ours was the thing that was down. The
  output is a record and an alert; the decision is a human's, taken from the agent's own
  screen where the sentence saying what differs actually lives.
- **`GET /v1/ops/platform` carries `engine_drift`, and `oldest_checked_at` is the field to
  read first.** If the cron dies every count freezes and `out_of_sync: 0` reads as all-clear
  forever — an `oldest_checked_at` that stops moving (or is null) is the only thing on the
  payload that can say nobody is watching, so the console leads with it rather than
  burying it. `never_checked` is distinct from `in_sync` for the same reason
  `live_verify_state`'s `unverified` is distinct from `unreachable`.
- **What triggers one: `runbooks/alarm-index.md`, and this line no longer tries to be the
  list.** It was written as a design and read for months as an inventory; D-183 found that
  three of its eight entries had no call site anywhere and rewrote it to say which was
  which. D-202 closed the three and removed the reason the distinction had to be made in
  prose at all: the trigger list named no CODES, so nothing could check it.
  - **The three that were missing now exist**, each with a threshold argued at its call
    site and a runbook section: `campaign_complaint_spike`
    (`campaigns/complaint_spike.py`, D-203 — pauses the campaign as FLOWS §5 promises),
    `engine_error_spike` (`engine/health.py`, D-204), and `tls_certificate_expiring` /
    `tls_certificate_unreadable` (`workers/tls_expiry.py`, D-205).
  - **D-183's rule holds and is now enforced rather than remembered**: no alarm may depend
    on a `record_*` metric, because every recorder writes to a stream nothing reads. All
    three announce at the producing write and travel `alert()`'s D-49 email path. The two
    that need a RATE keep their state in Postgres — `platform_engine_health` for the
    engine, `calls` + `consent_ledger` for the complaints — because a rate held in a
    process means something different per process (D-160's defect), and because a counter
    that can invent a page must be as durable as what it reports on.
  - **`latency p95 breach 15-min sustained` is still not implemented**, and it is the one
    entry that genuinely needs the metrics pipeline DEPLOYMENT §8 defers: a percentile over
    a sliding window is not a counter, and computing it from the `webhook_ack_ms` /
    `tool_ack_ms` log lines would mean building the scraper inside the alarm. `webhook_ack_slow`
    and `tool_ack_slow` fire per breach today, which is the honest subset.
  - **The index is the vocabulary now**, and `scripts/check_alarm_wiring.py` fails CI in
    BOTH directions: a documented alarm with no call site (the defect above), and a raised
    alarm with no row — which was the larger half nobody had counted, 44 codes that could
    page a human and appeared in no document at all. It derives the raised set from the
    tree (every `alert()`, every `ProblemError` carrying a `failure_stage`, every `*_code`
    on an ack meter, every host-side shell alarm) and REFUSES when it matches nothing, so
    it cannot rot into a list somebody keeps.
  - **What stays external, named rather than implied**: DOMAIN-registration expiry (the
    registrar is the authority, the notice goes to the registrant, and the remedy is a
    payment no code can make — keep that address one a human reads), the Cloudflare edge
    certificate, and the Cloudflare zone settings generally.
- **The host backup chain crosses a PROCESS boundary, not a vocabulary one.** Backups run
  on the host as `postgres`, outside every Python process, so they cannot CALL `alert()` —
  they emit the same shape (`failure_stage=HOST_BACKUP` with a stable code) to journald and
  stderr, and reach the same transport by subprocess: `notify.sh` → `alert-to-app.sh` →
  `python -m scripts.host_alert` → `alert()`. One vocabulary, one recipient, one transport,
  two ways in. `BACKUP_ALERT_COMMAND` defaults to that relay, so **a host that configures
  nothing still pages**; an override stays ONE command, because two delivery paths are two
  dedupe windows and the day one stops nobody notices.

  Each relay is a fresh process, so `alert()`'s in-memory suppression window cannot apply.
  The window is therefore a stamp file per fingerprint, with the INTERVAL imported from
  `alerting` rather than copied; a failed delivery does not open one, and an unwritable
  state directory fails OPEN. Without it, a broken chain checked every fifteen minutes is
  ~96 mails a day, which becomes a filter rule, which is an alarm reaching nobody again.

  What remains to do on the host is `ALERTS_EMAIL` plus a readable email transport
  (`EMAIL_PROVIDER` + `RESEND_API_KEY`) — proved by
  `notify.sh probe "delivery test"` putting mail in a real inbox, since local delivery
  success is transport acceptance, not receipt.

- **The dead man is the harder half, and it is now built (D-54).** `backup-health.sh`
  checks the SCHEDULE (a timer missing, inactive, or armed and silent past its window —
  the failure `OnFailure=` structurally cannot see, because nothing ran so nothing failed)
  and its OWN heartbeat (a gap reported when it resumes, dated so an operator knows which
  nights to check). Neither survives the host being off or off-network, systemd not
  running, or the alert path being broken beyond us: each removes the observer along with
  the observed. So a run in which EVERY check passed pings a hosted dead-man check
  (Healthchecks.io, `BACKUP_HEARTBEAT_URL`, one GET, no payload) and **the external
  monitor pages when the pings stop**.

  **Read the polarity correctly, because it is the opposite of every other alarm here:**
  a failing run pings NOTHING, and neither does a dead box. Silence is the alarm. There is
  deliberately no failure ping — failure already has a path (journald + email), and a
  second one would mean two dedupe windows on one fact, while the failures worth having a
  dead man for cannot send anything at all.

  Configure the check at 15-minute period / 1-hour grace (three missed runs, the same
  number `MAX_HEALTH_GAP_S` uses) — see `infra/backup/README.md` §5. The URL is a
  CREDENTIAL: anyone holding it can silence the alarm, so it comes from the secrets
  manager, is never logged (operator output names a digest prefix), and unset means the
  heartbeat is a stated no-op rather than a silent pass. A heartbeat that cannot be sent
  is logged loudly as `backup_heartbeat_undelivered` and **does not** fail the backup or
  send mail — the consequence is the dead man firing, which is the correct outcome.
  What to do when it fires: `runbooks/backup-heartbeat-silent.md`.

## 5. SLOs (v1)

Lead visible post-hangup ≤ 2 min (99%); webhook ack < 500ms; dashboard p95 < 800ms;
voice p50 ≤ 1.1s; monthly voice-runtime availability 99.5%. Review monthly; tighten with
scale.

**`webhook_ack_slow` is usually a CAPACITY alert, not a bug (D-55).** The receiver's
per-delivery cost is fixed and asserted in CI; what moves the ack is how many deliveries
are in flight on one process, and `ack_p50 ≈ in-flight ÷ acks-per-second-per-process`
(≈250/s on the measurement host). A burst of them at the end of a campaign — 250 calls
hanging up together — is the designed shape of the traffic, not an incident. So triage in
this order:

1. **Is it wide or is it slow?** A FLAT distribution (p50 ≈ p95 ≈ max) is a queue: too
   many deliveries per process. A long tail with a normal p50 is a dependency —
   the `webhook.inbox_claim` span says which.
2. **Wide → add processes**, using the arithmetic and the connection budget in
   DEPLOYMENT §2a. It is a `--workers` change and a restart of one deployable, and
   voice-runtime's deploy is deliberately decoupled from `api` for exactly this.
3. **Nothing is dropped while you decide.** The 500ms budget is the alert; the 2-second
   `_DURABLE_DEADLINE_S` is the abandon, and past it the answer is a 503 and the
   reconciliation poller (D-31), never a false ack.
4. `webhook_claim_timeout` in the same window means the deadline IS firing — that is no
   longer a capacity warning, it is calls waiting on the 10-minute poller. Treat as an
   incident.

## 6. Routine Ops Calendar

Daily: alert triage; pipeline DLQ empty; spend anomalies. Weekly: regression nightly
results review; knowledge-gap report → KB updates; pipeline/latency trend. Monthly:
invoice run; margin per client; rate-card check. Quarterly: restore drill (prove RTO 4h/
RPO 15min) — `runbooks/backup-restore-drill.md`, alternating the R2 PITR chain and the
offsite dump chain, result recorded in `docs/evidence/`; access review; secret rotation
(**one credential lives in two places and both must move together** — the host backup
relay reads `SMTP_PASSWORD` from `/etc/calevate/alerts.env`, not from the console, because
an alarm saying the database is unrecoverable cannot need the database to be sent;
`infra/backup/README.md` §5); regulation/pricing re-verify; adapter conformance run against
Bolna (keep the exit door oiled).

**The quarterly line above is now enforced rather than remembered (D-166).**
`uv run python -m scripts.check_drill_freshness` reads the newest
`docs/evidence/restore-drill-<YYYY>-Q<N>.md` and REFUSES when it is more than one quarter
old, post-dated, still carrying the runbook's unfilled `**PASS | PARTIAL | FAIL**` line,
verdict-less, or recording FAIL. A PARTIAL counts — runbook §9's own words — a FAIL does
not, because a drill that proved the opposite of the claim is a finding and not a fresh
clock. **Today it reports `NOT RUN`, on every build**: no quarterly record exists, so
nothing has expired and §8's "backups verified" is untick, which the check prints rather
than passing quietly.

**The check cannot produce the evidence it reads, and that is the point.** The local
harness (`make restore-drill`) writes `restore-drill-local-*.md` into the SAME directory,
so a validator that took the newest file by date would be refreshed by the very thing it
is meant to be independent of. Local records are counted, named and never counted as a
drill; the freshness clock is read off the FILENAME rather than an mtime, which no
`touch`, checkout or reformat can renew; and the checker may import nothing that can
write, calls no writer, and proves both from its own AST on every run.

## 7. Runbooks (summaries; full steps in /runbooks)

**Written procedures.** Every fact in these is grep-verified against the tree, so where
one differs from a summary below, the runbook is the authority.

- **"Our calls have stopped"** — `runbooks/calls-stopped.md`. The ordered diagnostic for
  the eleven conditions behind one symptom: big red switch, load-shed mode, Calevate's own
  TM registration (blocks every tenant at once), the admin spend cap, the client's own
  spend cap, `spend_state.capped` and the trap in clearing it, an empty prepaid wallet,
  the client's PE registration + TM link, subscriber KYC (`self_serve`/`trial` only), the
  campaign's consent provenance, template, number or a DNC hit, and the first-campaign
  manual-review hold (D-51) — `self_serve`/`trial` only, refusing at launch AND at every
  dispatch tick as `first_campaign_review_pending` / `first_campaign_review_rejected`.
  The two human-decision holds share one step, which opens with the queue
  (`GET /v1/admin/compliance/holds`) because that answers "is a human the blocker?" for
  every account at once. Marks which of these a client can self-serve out of.
- **Campaign is not dialling** — `runbooks/campaign-stall.md`. The dispatcher's own
  failure modes: tick verdicts, line-pool exhaustion, per-tenant ceiling, contact states,
  the per-dial gate.
- **"You called someone who asked you not to"** — `runbooks/dnc-complaint.md`. DNC
  complaint or TRAI/DLT escalation; the answer is a timeline, not a fix.
- **A personal data breach** — `runbooks/data-breach-notification.md` (D-179). The
  deliverable is a set of NOTICES with statutory clocks on them, all running from
  AWARENESS: the client within 48 hours (`/legal/dpa` §7, ours), each affected data
  principal and the Board without delay, and the Board's detailed report within 72 hours
  (DPDP Rules 2025 Rule 7 — the client's for caller data, ours for client-account data).
  Rule 7 has no severity threshold, so "one record" and "no evidence of access" are facts
  to state in the notice rather than reasons to skip it. `scripts/breach_notice.py`
  renders the three documents from one incident file and refuses one with a required
  element missing or a phone number in it; it sends nothing, because who signs off is a
  named human decision. Two things it still needs from outside the repo are stated in the
  runbook's §7 rather than discovered at 4am: the Board's own reporting channel, and
  counsel's review of the wording.
- **Campaign follow-up never goes out** — `runbooks/campaign-escalation-refused.md`.
  `escalate_campaign_contact` refusals, split by the line the code itself draws: the ones
  that page a human (`no_provider_configured`, `provider_not_implemented`, template
  failures, ladder exhaustion) and the lawful ones that deliberately do not
  (`recipient_not_opted_in`, `whatsapp_disabled`, every `blocked_*` from the dispatch
  gate). Covers both states of the `messaging` consent purpose.
- **Top-ups and payments** — `runbooks/topup-payments.md`. `payment_capability()` and what
  each refusal means; the order adapter IS built (`PROVIDER_CREATES_ORDERS` is True, D-98)
  but no deployment holds a Razorpay API secret, so `creates_orders` answers False with
  reason `no_api_secret` — and what to tell a client who wants to pay today; the Razorpay
  signing scheme and payload paths are UNVERIFIED against a live account, so the first
  real payment is an attended test, not a routine.
- **Knowledge base out of sync with the engine** — `runbooks/kb-out-of-sync.md`.
  `kb_engine_ref_unknown` vs `kb_engine_out_of_sync`: same disease, different cures, and
  the wrong cure leaves a client's agent quoting old prices. Includes the manual
  vendor-side withdrawal and its two unverified pilot-gate caveats.
- **An agent is running something we did not publish** — `runbooks/agent-engine-drift.md`.
  The `engine_agent_drift_detected` alarm and the ops panel behind it (D-123). Opens with
  "do NOT start by re-publishing", because the two causes — a vendor-dashboard edit and a
  publish that failed on our side after the vendor committed — want OPPOSITE fixes and a
  count cannot tell them apart. `disclosure_applied: false` is escalated as an incident
  rather than a config drift: it is one of two properties here with a legal consequence —
  and since D-163 it reads BOTH ways, so on an agent whose owner has withdrawn both
  notices a `false` means the vendor is still speaking one. **`truthful_answer_applied:
  false` is the graver of the two and is escalated the same way**: the engine has lost
  the instruction that makes the agent admit it is an AI, which is the one property no
  client setting can explain away. Also
  covers the two things the panel says that are not the alarm — a rising `undetermined`
  (the vendor, or our own read-back shape drifting) and an `oldest_checked_at` that has
  stopped moving, which means every count on the panel is stale.
- **Local database cannot reach head** — `runbooks/stale-dev-database.md`. The
  `credit_ledger` CONCURRENTLY unique index that cannot build over permanent pre-cutoff
  duplicates hard rule 4 forbids deleting; a fresh database and `make db-reset`; and why
  `alembic stamp` past it defeats the ancestry gate the index tests depend on.
- **The backup heartbeat went silent** — `runbooks/backup-heartbeat-silent.md`. The one
  alarm here that arrives as an ABSENCE: the external dead man (D-54) pages because pings
  stopped, which means the host is gone, systemd is gone, a backup check is failing, or
  the ping cannot leave — four different incidents behind one notification, ordered by how
  fast each is to rule out. Read this one BEFORE `database-restore.md`: the dead man says
  monitoring stopped, never that data is lost.
- **Restoring the production database** — `runbooks/database-restore.md`. Point-in-time
  recovery to a chosen instant (wal-g from R2), single-table recovery from the offsite
  encrypted dump, and the whole-VPS-is-gone path. Includes the six checks that prove a
  restore actually worked rather than merely completed, the `recovery_target_time`
  timezone-abbreviation trap, and the step everyone forgets: **a restore un-erases**, so
  DPDP erasures completed after the recovery target must be replayed from the preserved
  pre-restore cluster before anyone can reach the new one. **Never executed against a real
  cluster** — the mechanism in `infra/backup/` has been applied to nothing.
- **Quarterly restore drill** — `runbooks/backup-restore-drill.md`. The §6 quarterly item,
  made executable and recordable: alternating chains (R2 PITR one quarter, offsite dump the
  next), measured RTO/RPO, a deliberate induced archiving failure to prove the detector
  fires, and a record template committed to `docs/evidence/restore-drill-YYYY-QN.md`.
- **Object-store lifecycle rule** — `runbooks/object-lifecycle.md`. Applying and
  validating the recording-expiry policy, and what it does NOT prove.
- **Events not reaching a client's CRM** — `runbooks/webhook-delivery-failures.md`. Outbox
  → ARQ → delivery forensics, plus the client-side checks to hand them.
- **A deploy failed** — `runbooks/deploy-failed.md`. Ordered by WHICH step of
  `scripts/vps-deploy.sh` failed, because the recovery for a failed build and a failed
  container swap are different procedures. The section worth reading before you need it is
  §3: a failed migration leaves the database at the last revision that fully applied, the
  old containers can serve on it (hard rule 8 is what guarantees that), and **there is no
  automatic downgrade** — downgrading can drop a column something has already written to,
  so it is a judgement rather than a step. **Never executed**; nothing in this repo has
  been deployed to anything (DEPLOYMENT §4d).

**Summaries only** (no written runbook yet):

- **Every engine webhook is 401ing** (`webhook_source_rejected`): read the alert's
  `detail`, because the two reasons have different cures and the same symptom.
  `source ip not allowlisted` = the vendor renumbered; rotate `BOLNA_WEBHOOK_SOURCE_IPS`
  and restart voice-runtime (calls are not lost, the 10-minute poller carries them —
  D-31). `client ip not established` = **the EDGE is broken, not the vendor**: outside
  `APP_ENV=local` the receiver takes the client address from `CF-Connecting-IP` and from
  nothing else, refusing when it is absent or is not a single literal IP
  (`calevate_shared.client_address.client_ip`, the one definition both deployables call).
  Two nginx facts must hold for that header to mean anything, and both live in
  `infra/nginx/snippets/`:
  `real_ip_header CF-Connecting-IP` + `real_ip_recursive on` + the `set_real_ip_from` CF
  ranges (`calevate-origin.conf`), and `proxy_set_header CF-Connecting-IP $remote_addr`
  (`calevate-proxy.conf`) so our own nginx — the single trusted hop — is what writes the
  header the app reads. Check those before touching the allowlist. A deployment that
  terminates TLS anywhere other than this nginx, or puts a second proxy in front of the
  container, breaks the hop count the control is built on and must update `client_ip`
  in the same change.
- **Engine outage**: numbers fail over to client phones (provisioned fallback); status
  banner in dashboards; reconcile calls post-recovery; if >4h, activate Bolna adapter for
  new calls (numbers re-point), inform clients.
- **Webhook signature failures**: treat as attack until proven config drift; block source,
  rotate secret, audit deliveries.
- **Data breach (suspected)**: contain (revoke keys, rotate, big red switch if needed) →
  scope via audit_log/webhook_deliveries → classify under DPDP → notify Board + affected
  principals per Rules timeline → postmortem in repo.
  - **`webhook_deliveries` answers OUTBOUND completely and INBOUND only partly**, and an
    investigator must know which half they are holding: the table records deliveries we
    CLAIMED, so a request we rejected at the door leaves no row in it. For inbound scope,
    read the alert codes instead — `webhook_source_rejected`, `webhook_payload_too_large`,
    `webhook_unkeyable`, `webhook_claim_timeout` — which is exactly where a refused,
    oversized, unkeyable or abandoned delivery lands. That list is derived from
    `integrations.service.INBOUND_REFUSAL_ALERTS`, which is where it is maintained.
  - **A `duplicate` is silent but not invisible** (D-219, correcting an earlier reading).
    It raises no alert, because ordinary vendor retries are not an incident — and
    `webhook_inbox_events.duplicate_count` counts every one of them on the transition's
    own row, so a REPLAY burst is queryable evidence. "Not evidence of anything" was
    wrong about the only inbound outcome this platform records durably without alerting.
- **Runaway campaign**: auto-pause on cap/complaint alarm; verify DNC + template status;
  client comms template ready.
- **Deletion request**: FLOWS §9 procedure; 7-day internal SLA; proof certificate issued.
- **Model retirement**: the identifier lives in ONE place per vendor
  (`calevate_shared.engine.SARVAM_DEFAULT_LLM`, `AZURE_OPENAI_DEFAULT_MODEL`) with the
  shippable set beside it — `AZURE_OPENAI_MODELS` names what MAY be shipped, while
  `SARVAM_RETIRED_LLMS` and `GEMINI_RETIRED_LLMS` name what may NOT (the latter survives
  D-410 for exactly this reason: the identifiers are dead, so no shipped module may name
  one again) — and `tests/sarvam_model_identifier_test.py` fails the build on any shipped
  module that does. So this is: move the constant, move
  the allow-list, re-derive `AZURE_LIST_PRICE_USD_PER_MTOK` from the new model's published
  rate (TRD §10.1 and the whole INR chain hang off it), run the full regression suite on
  staging → promote per client → note in the decision log. **Nothing is currently owed
  under this heading**, which is new: BRD R-04's 16 Oct 2026 Gemini retirement was the
  live worked example until D-410 removed the model, the date-carrying constant and the
  test that turned CI red thirty days out. If a dated retirement lands on an Azure model,
  reuse that mechanism — a date as DATA plus a test that fails before the date — rather
  than a calendar reminder. **Wrong answer**: widening a runway constant to quiet the test.

## 8. Pre-Launch Checklist (client #1 goes live only when all green)

Entity decided → DLT PE registered (or inbound-only mode explicitly accepted) ·
engine verification scorecard passed · agent passed test-call gate + regression five ·
disclosure + consent verified on a real recording · caps set · backups verified ·
alerts firing to Sri's phone · **error reports and traces verified as ARRIVING (§2 gate
15) — `check_observability_ready` green is the configuration half and not this item** ·
client owner trained on Leads table (15-min session) ·
DPA + privacy notice signed · invoice template ready · **the admin realm's emailed second factor proved on
staging** (it is on unconditionally — D-177; what needs proving is that the mail arrives) · **`GET /healthz/ready` answers `ready` — last, because it
is the only item on this list the platform can answer for itself**.

**`/healthz/ready` is the go-live gate and this is the line that polls it.** `core/health.py`
names it that; `runtime_config_missing_keys` behind it is the completeness check over the
credentials a deployment needs in order to serve rather than merely to boot (the list is
that function, not a number written here — engine credentials come from the engine layer,
so it moves with `ENGINE`). Until this line existed **nothing called it** — the
deploy script polls `/healthz`, compose polls `/healthz/live`, and a grep across
`scripts/`, `.github/`, `infra/` and the Makefile found one hit and it was a comment. A
gate nobody opens is not a gate.

```sh
curl -sS -i -H "Authorization: Bearer <a session holding ops:manage>" \
  https://api.calevate.tech/healthz/ready
```

200 + `"status":"ready"` is the pass. 503 + `"status":"not_ready"` names its own reason in
`degradation_mode` — `db_down`, `schema_behind`, `redis_down`, `queue_stale`,
`config_missing`, in that priority order — and `config_missing` lists the keys in
`fields[]`. `schema_behind` (D-390) means THIS IMAGE CARRIES MIGRATIONS THE DATABASE
HAS NOT APPLIED: run `uv run alembic upgrade head` against it. A database at a
revision this image has never heard of is a rollback and stays green on purpose. **Send the credential**: without
`ops:manage` the endpoint answers the status word alone and nothing else (D-128 — it used
to publish the names of the credentials this deployment had not installed yet, to anyone
who asked, which is a targeting oracle at exactly the moment it is most useful to a
stranger). The withheld detail is written to the service log instead, so an operator on the
box is never blind, but at the checklist stage you want it in the response.

It goes **last** for a reason: `config_missing` stays red until §9 step 10a's ~55 keys are
in, so running it early only teaches people to ignore it. `GET /v1/ops/config` is the
companion read — every key with its source, i.e. "is anything still on a code default in
production" — and the two together are the whole of what this repository can assert about
its own readiness. Everything else on this checklist is a human, a registration or a
vendor.

**Three of those items have a pass condition that deployed code does not satisfy on its
own**, stated here because they have previously been read as done:

- **Admin-realm MFA switched on** = **nothing to switch on any more (D-177), and this
  entry described a vendor account that does not exist (D-393).** It used to name a DASHBOARD
  change in "the ADMIN Clerk application" whose publishable key is
  `NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY`, told an operator to enable TOTP and backup
  codes, and warned that a custom JWT template dropping the `fva` claim would produce
  `403 mfa_claim_missing`. There is no Clerk, no such key, no TOTP, no `fva` claim and no
  such error code — `core/auth._require_second_factor` says so in its own docstring, and
  `apps/api/authn/` is the only thing that mints a credential. A gate naming a console
  nobody can open is worse than an unticked gate: it cannot be satisfied and it cannot be
  refused, so it is carried forward for ever.

  **What is true instead.** `authn/service.MFA_REQUIRED_REALMS` is `{"admin"}`, a frozen
  constant with no setting behind it, so the admin realm's second factor is ON, on every
  deployment, and cannot be turned off. The factor is an **emailed one-time code**
  (`LoginStatus` is `otp_required` and not `mfa_required` precisely so the next reader
  does not go looking for an authenticator app), minted in the same transaction as the
  session. An admin credential that never answered one carries `mfa_verified_at IS NULL`
  and is refused `401 second_factor_required` on the auth router and on every other
  router alike — one code, one condition.

  **So the real precondition is EMAIL, and it is the same one the alerts gate below
  needs**: `EMAIL_PROVIDER` + its credential + `NOTIFICATIONS_FROM` + a sender domain
  verified with the provider. Without them nobody can complete a sign-in, which means
  nobody can reach the console — and `RESEND_API_KEY` is in `ENV_ONLY_KEYS`, so the
  credential that fixes it cannot be installed from the console either. That is now a
  **readiness failure** rather than a boot-log warning (D-392): `/healthz/ready` answers
  503 `config_missing` and names the missing key in `fields[]`, so this line and the
  `GET /healthz/ready` item at the top of the checklist are the same question asked once.

  **Its two-person check, unchanged in shape and changed in content**: sign in to the
  admin console on staging as an operator, confirm the password step answers
  `otp_required` rather than a session, confirm `GET /v1/ops/platform` with that
  half-authenticated credential answers `401 second_factor_required`, then answer the
  emailed code and confirm the same call answers 200. `tests/authn_mfa_test.py` drives
  both directions against the database; **what staging proves and the tests cannot is
  that the mail arrives** — which is the whole of what is left outside this repo here.
  Record the result in `docs/evidence/` the way the backup drill is recorded — an
  untested auth control is a claim, not a control.

  **DONE (D-178), and this entry used to say the opposite**: requiring a FRESH second
  factor for the high-risk actions BACKEND-PATTERNS §7 lists — the big red switch, cap
  raises, raw-transcript access — was deferred because "raising a real reverification
  prompt needs a flow in `apps/web` that does not exist, and gating an incident lever on a
  prompt nobody can answer at 3am is how a control gets switched off". D-170 built the
  flow: the second factor is an emailed code, and `POST /v1/auth/admin/step-up` mails one
  to the operator who was just refused, on the screen they were refused on. So
  `core/stepup.StepUp.require` now demands the per-action `X-Confirm-Action` echo AND
  `auth_sessions.mfa_verified_at` under five minutes, at all 15 call sites.

  **Its two-person check, same shape as the one above**: hold an admin session, wait past
  five minutes, and confirm `POST /v1/ops/platform` with the correct `X-Confirm-Action`
  answers 403 `reauthentication_required`; call `/v1/auth/admin/step-up`, answer the code
  at `/step-up/verify`, and confirm the same call answers 200. `tests/authn_stepup_test.py`
  drives both directions against the database; the staging run is what proves the email
  arrives.

- **Backups verified** = `runbooks/backup-restore-drill.md` has PASSED once, with the
  record committed to `docs/evidence/`. The existence of `infra/backup/` does not tick it:
  nothing in that tree has been applied and no wal-g command has ever been run, so until a
  drill record exists the §5 RPO is a design intent rather than a measurement.
  **And ticking it once is not ticking it (D-166)**: `scripts/check_drill_freshness` reads
  the record every build and refuses one more than a quarter old, so this item is a
  standing condition rather than a box. Its verdict today is `NOT RUN` — which is what
  this bullet says, said by a machine on every build.
- **Alerts firing to Sri's phone** = `ALERTS_EMAIL` plus a working email transport
  (`EMAIL_PROVIDER=resend` and `RESEND_API_KEY`, or the `smtp` escape hatch), on the app
  hosts AND on the database host (where the same configuration is
  what lets the backup relay page). A service booting without them says so — see §4 — and
  local delivery success is transport acceptance, not receipt, so the proof is a probe
  message landing in a real inbox.

  **The sender domain is a THIRD condition and it is not a setting.** Resend refuses a
  send from a domain it has not verified (403, `email_sender_rejected`), so
  `calevate.tech` must be verified in the Resend dashboard with its DNS records live
  before this gate can be ticked — DEPLOYMENT §6 lists the records. A key that
  authenticates is not a domain that can send, and `POST /v1/ops/secrets/{key}/test`
  checks only the first of the two.

  **That gate covers alarms that are SENT. The dead man covers the ones that cannot be**
  (D-54), and it is armed separately: `BACKUP_HEARTBEAT_URL` set on the DATABASE host from
  the secrets manager, the vendor-side check created at 15-minute period / 1-hour grace
  with the notification going to the same person, and the drill's §7.8 proving both halves
  — a ping arriving when the chain is healthy, and the check going red after the pings are
  stopped on purpose. Unset is not a quiet default: `backup-health.sh` states it in the
  journal, and every backup can be perfect while nobody outside this host is watching.
