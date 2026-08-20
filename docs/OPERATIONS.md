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

Budget ~₹3–5k (Bolna gives $5 free signup credits + Sarvam's ₹1,000 free credits, so
most of this is real PSTN call spend). 5–7 working days alongside other work.
**H = hard gate (a red H reopens the engine decision); S = soft gate (shapes M1 scope).**

| # | Gate | Pass criteria |
|---|---|---|
| 1 H | Webhook trust | Register a tunnel URL as the agent's `webhook_url`; run calls. Confirm deliveries arrive ONLY from 13.203.39.153 and our allowlist (nginx + in-app) rejects anything else; confirm dedupe on execution_id; confirm the payload matches Get Execution. Docs claim no signing — if a signature header exists, capture it and update TRD §5. |
| 2 H | Full API provisioning | Via API only, no dashboard: create agent → update prompt → attach number → start call (`POST /call`) → `GET /executions/{id}`. Confirm /v2 agent paths, `user_data` context injection round-trips into the prompt, and `scheduled_at` works. **AND SETTLE `delete_agent`'s MARKED ASSUMPTION (D-123).** Both real adapters implement `DELETE` on the agent (`DELETE /v2/agent/{agent_id}` is published in Bolna's reference — 200 `{"message":"success","state":"deleted"}`, 400, and a note that it destroys all of the agent's batches and executions; Cartesia publishes NO agent-delete reference at all, so its `DELETE /agents/{id}` is INFERRED). What neither vendor documents is what a REPEAT delete answers, and both adapters assume **404** and fold it into the Protocol's idempotent success. If it is a 400 instead, `agents/service.py::_reclaim_orphan` raises on a compensation whose work is already done and the retry ladder DLQs it. The harness now runs this: `gates_api._delete_agent_checks` creates a THROWAWAY agent (never the gate's own — deleting that would destroy the execution this gate's own re-run instructions depend on), deletes it, re-reads it, and deletes it a SECOND time. Record the exact status and body of the repeat; if it is not 404 the fix is to narrow `absent_is_success` onto what the vendor actually sends, never to widen the accepted status range. |
| 3 H | Telugu quality (BYOK) | Sarvam Saaras V3 STT + Bulbul V3 TTS on OUR keys. 10-utterance Telugu script on real PSTN: names/numbers ≥90% correct; Telugu-English code-mixed handled. Confirm **Bulbul V3 (not v2) is selectable**. |
| 4 H | Real-call latency | 10 PSTN calls: voice-to-voice p50 ≤ 1.1s, p95 ≤ 1.8s (stopwatch + recording analysis). **Vendor latency claims are marketing — their site says "<300ms" undefined; plan only against our own measurement.** Record first-greeting delay after pickup separately (cold-start hides there). **Also capture `latency_data` from Get Execution as an adapter fixture and record whether it AGREES with the stopwatch.** Their docs describe `time_to_first_audio` plus per-component transcriber/llm/synthesizer blocks — unverified against a live account, and a different set of numbers from voice-to-voice turn latency, which would be our own arithmetic aligning three components. This capture is what re-opens durable per-call latency storage: `calls.latency` was dropped (`f1a7c39d5be2`) rather than filled with pipeline timings that are not the caller's experience, and the storage shape gets chosen from the payload we actually receive. Note the documented `transcriber.turns` entries carry recognised TEXT — hard rules 5/6 apply to wherever it lands. |
| 5 H | Telugu turn-taking [NEW, D-32] | Barge-in mid-sentence, and end-of-utterance on slow/hesitant Telugu speech: does the agent cut callers off, or leave dead air? Endpointing is an ORCHESTRATION-layer property — BYOK models do NOT fix it. Measure, never assume. |
| 6 H | Webhook loss behavior | Kill the receiver mid-call: call continues; observe whether ANY retry arrives (docs + OSS code say none). Then confirm the List-Executions poller recovers every missed execution — it is the guarantee of record, so its recovery must be proven, not assumed. **Retry expectation FLIPPED (D-352): the hosted platform documents that it retries on non-2xx and fires one delivery per status transition, so a retry is the expected observation and its ABSENCE is the surprise.** **PAGINATION IS NO LONGER THE QUESTION (D-350/D-353).** The adapter used to call a global `GET /executions?created_after=`, which is not a route the vendor has, and inferred truncation from a page-size heuristic. It now walks the real endpoint — `GET /v2/agent/{agent_id}/executions`, per agent, `from`/`page_number`/`page_size` (max 50), looping on `has_more` — with the contract read in Bolna's own pinned OpenAPI document. What is left to settle is not the CONTRACT but whether the server honours it, which a spec cannot say: **(a)** the account's own execution count for the window from the dashboard, passed as `--attest gate6.executions_in_window=<n>` — more than we listed is proof of truncation and the gate goes red; **(b)** whether the `from` filter actually bounds the window rather than being ignored; **(c)** whether `has_more` ever lies. Capture one raw listing body as a fixture and compare its envelope with `AgentExecutionV2List`. A complete-looking listing on a quiet pilot window without (a) is NOT RUN, never a pass. |
| 7 **H** *(was S — raised by D-261)* | Post-call data fidelity, and **what unit is the money in** | `completed` (not `call-disconnected`) carries total_cost + cost_breakdown, recording_url, extracted_data. Transcript parses into TranscriptTurn (check `transcript_lines_unparsed == 0`; if their serializer emits `system:` / `assistant_tool_call:` / `tool_response:` lines, D-260 already skips and counts them — a non-zero count here is the signal, not a failure). Time-to-`completed` (~2–3 min claimed) against our 2-min lead SLO. **THE ONE THAT RAISED THIS TO A HARD GATE: is `total_cost` in DOLLARS or CENTS?** Our adapter divides by 100 (`_ASSUMED_MINOR_UNITS_PER_MAJOR`). **THE EVIDENCE MOVED WITH D-350 AND STILL DOES NOT CLOSE THIS.** The old argument here — their OSS cost function returns a rounded *dollar* float (`analytics_helpers.py`, bolna-ai/bolna@cd2e192), and published prices are quoted in dollars per minute — is RETIRED: both readings are about a program that is not the hosted biller. What replaced it is a contradiction inside the vendor's own first-party documentation, at one commit: the OpenAPI spec says "in cents" on `total_cost` and on all five `cost_breakdown` members, while `references/execution-payload.md` says "Bolna cost in **account currency**", i.e. major units. Their own `bolna-core.md` breaks the tie ("treat the YAML as the canonical schema if a SKILL.md and the spec disagree") toward cents, which is what our constant already does — so nothing changed on inference, and nothing is settled either, because a precedence rule between two documents is not an observation of a server. This is the money path (hard rule 7) and a 100x error in either direction is unacceptable. **The test is one observation:** place one call, read `total_cost` from Get Execution, and put it beside the same call's charge on their dashboard. Two orders of magnitude apart, impossible to misread. Also record whether ANY currency field appears in the payload — `currency_stated=False` on every row today, and no first-party document names a currency at all. Note the second half of the contradiction above: if "account currency" is the true reading, the currency is the ACCOUNT's, which for an Indian account may be INR rather than the `_ASSUMED_CURRENCY` USD this adapter assumes — so this one observation scores the UNIT and the CURRENCY together. **AND SCORE THE `INR` BRANCH SEPARATELY, because it is the half neither signal above covers — and since D-411 an INR-billed pilot account METERS NOTHING until you do.** `_cost` converts a payload that STATES `INR` at `rate = 1` (added so a stated-INR figure is not multiplied by the USD rate, the 83x error) and then used to divide it by the cents divisor anyway — a constant argued end to end in dollars. It no longer does: `_MINOR_UNITS_PER_MAJOR` keys the divisor by CURRENCY, `USD` is its only entry, and a stated currency with no entry is refused with `engine_cost_unit_unknown` rather than priced on another currency's unit story. So if the pilot account is billed in INR, every call logs that warning and pages `call_billable_without_cost`, and THIS observation is what unblocks it. **WHAT TO DO WITH THE ANSWER, so this gate ends in a command rather than in "find out":** add the one line to `_MINOR_UNITS_PER_MAJOR` (`INR: Decimal(1)` for rupees, `Decimal(100)` for paise) and deploy, then restate what was metered before the flip with `uv run python -m scripts.correct_cost_unit` — dry-run by default, append-only, idempotent, and it moves OUR cost only (`usage_events` is INSERT-only, hard rule 4; a client's invoice is priced off minutes and does not move). Rows carry `meta.source_currency`, `meta.source_amount`, `meta.fx_rate` and `meta.currency_stated`, which is what makes the population selectable and this gate's currency criterion answerable from the ledger afterwards. The full sequence, and what NOT to do, is `runbooks/vendor-cost-unit.md`; a call whose derived ₹/min lands outside the rate card's band pages `engine_cost_implausible` (D-411) rather than waiting for this gate. **A wrong value here means every `usage_event` under-values calls 100x, no spend cap ever arms, and every margin panel reads ~₹0.00.** Evidence: `docs/vendor/bolna/`. |
| 8 S | KB + campaigns + tools + H1 handling [expanded, D-33] | Upload a Telugu FAQ to the rag_id KB (multilingual mode); measure retrieval quality + latency on-call. **Telugu is NOT named in their multilingual mode (Hindi/Tamil are) and the mode is immutable at KB creation** — if Telugu retrieval is poor, the external custom-function route is the fallback (TRD §6.2), so measure both in the same session. Test a custom function to our endpoint and record the tool-call p95 (**no timeout is documented — the ceiling is unmeasured**). Create a 10-contact batch; verify retry policy + per-contact statuses. **KB lifecycle — BOTH QUESTIONS ARE ANSWERED AND THE ANSWER RETIRED THE CAPABILITY (D-354).** (a) does `GET /knowledgebase/all` carry the AGENT LINKAGE we filter on? **No.** The `Knowledgebase` schema has no `agent_id` of any kind, so `list_kb`'s strict per-agent filter matched nothing and reported every agent as holding no knowledge base, on every sweep, forever. (b) does `DELETE /knowledgebase/{rag_id}` clear the AGENT's reference? **The question does not arise the way it was posed**: the agent references a knowledge base by `vector_id` inside `llm_agent.llm_config.vector_store.provider_config.vector_ids`, not by `rag_id`, and our `attach_kb` never wrote that field at all. Add to this that `POST /knowledgebase` is multipart taking a PDF or a URL and cannot ingest our `KBSourceRef.text`, and `BOLNA_CAPABILITIES.knowledge_base` is now `False` with all three methods refusing by name. **What this gate now measures is the FALLBACK**, which was always the plan for Telugu (TRD §6.2): retrieval quality and latency through OUR managed vector service behind the in-call RAG tool endpoint. Re-opening the engine built-in needs `KBSourceRef` to carry a document or a URL and `attach_kb` to patch the agent's `vector_ids` — D-354 names both. Capture both responses as adapter fixtures. **In-call working memory (H1, TRD §6.1):** does Bolna truncate or summarise conversation history at a window limit, and does it enable provider context caching on BYOK keys? Both drive the LLM leg on long calls. |
| 9 H | Compute region + residency [NEW, D-32] | Where does the call actually execute? (Recordings sit on S3 us-east-1 — storage ≠ compute, but both matter.) Get India data-residency terms + price in writing. This is the one axis where LiveKit beats Bolna on verified evidence today. |
| 10 H | Agency model | Confirm in writing that multiple end-clients under one account is permitted. **Verify the sub-accounts tier discrepancy**: the pricing page lists "Sub-accounts access" under Pilots, the docs call it Enterprise-only. If Pilots includes it, our tenancy model lands far earlier. |
| 11 H | The humans | Open two support threads (one technical, one commercial) during the pilot; record response time and answer quality. **This is the gate ThinnestAI failed** — a good product with unresponsive people is the same trap twice. |
| 12 H | Commercials in writing | **(a) the BYOK platform fee — the single number that decides ₹3–3.6/min; target ≤ ~₹1.5/min**; (b) whether volume tiers apply to BYOK; (c) INR/GST invoicing; (d) price-change notice period (60–90 days); (e) data-export commitment on exit; (f) recording retention + DPDP deletion API; **(g) is the built-in KB (`rag_id`) billed separately, or included in the platform fee? No KB line appears on the pricing page — we have INFERRED "included" and that inference is load-bearing for TRD §6.2 (D-33). Get it in writing, including any per-document/storage/query charge.** Anchors: their published bundled rate is 6.00¢→4.51¢/min; Vapi's comparable orchestration tax is ₹4.40/min (D-32). **OBSERVED Aug 2026, still ungated: the BYOK platform fee shows as 2¢/min ≈ ₹1.76 in the Bolna dashboard.** That is inside TRD §10's assumed ₹1.50–2.00 band but ~17% ABOVE this gate's ≤₹1.50 target, so the observation does NOT close (a) — a dashboard figure is not a commercial term, and the gap is worth ₹5,200/month at 20k platform-min and ₹15,600 at 60k (TRD §10.4). Open the negotiation on the ₹1.50 number with those two figures in hand. |
| 13 S | Concurrency ceiling | Pilots advertises 100 concurrent and two customers run 250+ in production (D-32); confirm OUR ceiling, behavior at the limit (queue vs reject + error shape), and the outbound dispatch rate limit (unpublished — measure it; it becomes our dispatcher config, FLOWS §5). Also ask Sarvam (BYOK-tier model concurrency) and Exotel/Vobiz (SIP trunk channels). **And Azure OpenAI, since D-410 (this used to be three legs and is now four).** An Azure deployment's ceiling is its own TPM/RPM quota in the subscription and the region, not a published table — gate 20b is where the number is read, and it is read for `southindia` specifically because quota is granted per region. It is the same shape as D-35's finding about Sarvam: **the binding constraint on a cheap model is the rate limit, not the price.** Effective ceiling = MIN of all four — record all four. |
| 14 H | **~~Does `asia-south1` serve our Gemini model?~~ RETIRED BY D-410 — there is no Gemini model and no Vertex account.** [closed 19 Aug 2026] | Both LLM surfaces moved to Azure OpenAI in South India, so the question this gate asked no longer has a subject. It was never answered: nobody in this repository could read Google's model-availability table (`docs.cloud.google.com`, `discuss.ai.google.dev`, `modelavailability.com`, `innfactory.ai`, `gcloud-compute.com`, `openrouter.ai` and `pricepertoken.com` were each attempted and each refused by this environment's egress proxy), and the one `generateContent` call that would have settled it was blocked on a GCP project that never existed. **What carried over is the SHAPE, not the answer**: a model is only ours to ship once someone has confirmed the region serves it, and that question is now gates 20 and 20b against Azure. **What did NOT carry over is the proof technique, and that is a real loss recorded in D-410**: `asia-south1` sat in the Vertex hostname and in the `locations/` path, so residency was provable from the AST; `<resource>.openai.azure.com` names no region and residency is now asserted by config and confirmed by a human in the portal. |
| 14b H | **~~⏰ REPLACE `gemini-2.5-flash` BEFORE 16 OCT 2026~~ RETIRED BY D-410 — the deadline is gone with the model.** [closed 19 Aug 2026] | **This is the one gate whose retirement is a BENEFIT and should be read as one.** It was a dated obligation on two live surfaces, priced into D-400 with the date in front of the founder: the constant `GEMINI_DEFAULT_LLM_RETIRES` held 16 Oct 2026 as data and `tests/sarvam_model_identifier_test.py::test_the_shipped_gemini_model_has_runway_left` was going to turn CI red on 16 Sep 2026, thirty days out, naming the remedy. The constant, the test and this gate are all deleted, and BRD R-04 closes on every leg. `AZURE_OPENAI_DEFAULT_MODEL` carries no announced retirement this product is running against; if one is announced, the replacement for this gate is a dated row here plus a date-carrying constant, which is the mechanism that worked and is worth reusing rather than reinventing. **Wrong answer if that day comes**: widening a runway constant to quiet the test. |

| 14c L | **~~Does the ~10% non-global endpoint surcharge apply to `gemini-2.5-flash`?~~ RETIRED BY D-410 — it was answered NO, and then the vendor left the product** [D-403] | The finding stands as recorded and is worth keeping for the method rather than the number: Google's pricing page, read directly on the founder's browser, scopes the non-global differential to *"the Generally available Gemini 3 and later families of models"* from 1 July 2026, and the 2.5 Flash table carried ONE unified schedule where the Gemini 3 sections carried two. **The secondary sources were the imprecise ones** — two search summaries generalised it to "Vertex charges ~10% more on non-global endpoints" and dropped the model-family qualifier, which is exactly how a REPORTED-DOCS claim becomes a false premise (D-31/D-32). **The same question exists on Azure and is NOT answered the same way.** Azure's Regional Standard deployments genuinely do cost more than Global Standard — roughly 5–10%, with published examples up to +12% and +20% — and that premium lands on the residency posture itself, exactly as this gate feared and Vertex did not charge. It is carried as gate 20c and stated in D-410, and it is deliberately not laundered into a rounding note: a surcharge nobody has seen on an invoice would make every derived figure unfalsifiable in the expensive direction. |
| 15 H | **Does anything we report actually ARRIVE?** [NEW, D-169; ours, not Bolna's] | **Not the engine's account — ours, and it rides along here for the same reason gate 14 does: it needs no pilot, only the real hosts and the real credentials.** `scripts/check_observability_ready.py` decides everything a string can decide — DSN shape, endpoint shape, sample ratio, SDKs installed, both export filters in place — and **deliberately decides nothing about delivery**, because a check that probed a vendor from a build container and reported "reachable" would be the unverified-vendor-behaviour defect D-31/D-32 exist for. So delivery is verified ONCE, by hand, on each host that runs a service. **The test, in three parts.** (a) **Sentry**: with `SENTRY_DSN` set on the api host, raise a deliberate exception through a non-production route (or `sentry_sdk.capture_message("gate15")` in a `python -m` shell using the deployed settings) and confirm the issue appears in the Sentry project within a minute, tagged `service` and carrying the deploy's `release`. **Then read it**: confirm the exception VALUE is `[message withheld]` and no transcript, phone number or header from `DROP_HEADERS` is present — the scrubbers are unit-tested, this is the only proof they are the ones the vendor actually applied. (b) **OTel**: with `OTEL_EXPORTER_OTLP_ENDPOINT` set, place one call end to end and confirm a single trace spans voice-runtime → ARQ → worker → Postgres in the collector, that `exception.message` and `exception.stacktrace` are ABSENT from every span, and that the sampled fraction matches `OTEL_TRACES_SAMPLE_RATIO`. A trace that stops at a process boundary means the traceparent is not crossing Redis and the whole 2-minute-SLO diagnosis is unavailable. (c) **Alerting**: `notify.sh probe "delivery test"` from the DATABASE host, and confirm the mail lands in a real inbox — local acceptance is not receipt, and this is the same proof OPERATIONS §8 asks for. **Record**: the three outcomes plus what each host had configured, in `docs/evidence/`, the way the drill record is. **Fail** = anything configured that does not arrive; the fix is a configuration change and a re-run, never widening the check. **Blocked outside this repo** on: a Sentry project and DSN, a collector endpoint, and a verified Resend sender domain — the same three the pre-launch checklist blocks on, so this gate is owed exactly when §8 is. |
| 16 H | **~~Does the agent object honour `provider` or `family`?~~ ANSWERED AT SOURCE — what remains is whether the HOSTED platform behaves like the open-source server** [D-260; half-closed by D-400, 18 Aug 2026] | **The half that is closed.** Re-read at source on `bolna-ai/bolna` master, 18 Aug 2026: `family` is declared on their `Llm` model and **read by nothing**; the LLM client is chosen by `provider` against `SUPPORTED_LLM_PROVIDERS` (`bolna/providers.py`), and `LLMProvider` has **no `sarvam` member** — so D-36's Sarvam 105B never had a value here, which is the audit finding that prompted D-400. Their published OpenAPI corroborates by omission: `provider` and `family` carry **no `enum`** while `agent_flow_type` in the same schema block carries one and the telephony `provider` carries another, so the author uses `enum` when they mean closed. `provider: "custom"` routes to the OpenAI client constructed with our `base_url` (`bolna/llms/openai_llm.py`). **The follow-on work this gate authorised is DONE**: `ModelConfig` has `llm_provider`/`llm_base_url` and `engine/bolna.py::_llm_routing` sends them. **The half that is open, and it is now the only reason to run this gate.** The open-source server is strong evidence about SHAPE and is not the hosted contract. **The test:** create an agent via `POST /v2/agent` exactly as our adapter does, then `GET /v2/agent/{id}` and read the `llm_agent` block back. Record (a) whether `provider` survives the round trip and with what value, (b) whether `base_url` survives, (c) whether `family` survives, (d) whether `max_tokens`/`temperature` came back as ours or as their defaults `100`/`0.1`. Then place one call and confirm from the transcript which model answered. **Pass** = the read-back carries the `provider` and `base_url` we sent. `_agent_models` already reads both back, so this gate's answer arrives as data on the first real publish rather than as a note. Blocked outside this repo on: a Bolna account. Evidence: `docs/vendor/bolna/oss-harvest.md` §1. |
| 16b H | **~~Can Bolna hold a credential that EXPIRES?~~ ANSWERED BY DESIGN, then RETIRED BY D-410 — nothing we install expires any more** [D-402; closed by D-404; retired 19 Aug 2026] | D-404's answer was that a store holding a static string can hold one we REPLACE on a schedule, so the question was the wrong one. D-410 removes even that: **Azure OpenAI authenticates with a STATIC API KEY**, so there is no expiry to hold, no cadence to argue and no ceiling to work under. Keep the reasoning, not the machinery — the general lesson is that "the vendor cannot hold X" is worth re-reading as "must it hold X at all", and the answer here turned out to be no twice over. |
| 16c H | **~~WHICH credential-store entry does the hosted platform read `llm_key` from for a `provider: "custom"` leg?~~ RETIRED BY D-410 — we no longer use `provider: "custom"`, which is WHY D-410 exists** [D-404] | **THIS GATE IS THE REASON THE PRODUCT MOVED, so read it before proposing a custom-LLM route again.** A read-only sweep of the hosted dashboard and public docs (founder's browser, 19 Aug 2026 — this environment's proxy refuses every Bolna host) found: **(1) no Provider Keys UI in the current dashboard build** — the docs describe Dashboard → Developers → Provider Keys, the live `/developers` page offers only Bolna platform API keys, and `/provider-keys` redirects to `/dashboard`; **(2) the per-agent LLM provider dropdown offers `azure, openai, google, openrouter, deepseek, anthropic` and NO `custom`**; **(3) `POST /user/model/custom` takes `custom_model_name` and `custom_model_url` and nothing else**, so no credential can be attached to a custom model; **(4) nothing anywhere states which stored credential becomes `llm_key`**; **(5) the Google entry is one row, `GOOGLE` = "Your Google Gemini API key"**, with no mention of Vertex, a project, a service account or a region. That was never a proof — it was a sweep of the UI and the docs while our code used the API — but the honest reading was that the risk went up, and a leg whose whole credential path rests on an unverified premise is not a leg to build a product on. **The same sweep is also the positive evidence for D-410**: `azure` IS in that dropdown, Azure OpenAI IS in their published provider list, and their OSS `LLMProvider` carries both `azure` and `azure-openai`. The residual question — which FIELDS their Azure provider expects — is gate 16f. |
| 16d H | **~~Does the service account hold `roles/iam.serviceAccountTokenCreator` on ITSELF, and does the org policy allow a 12-hour lifetime?~~ RETIRED BY D-410 — there is no service account and no bearer to mint** [D-404] | Two GCP grants, both external, both now irrelevant: `generateAccessToken` self-impersonation and the org policy `constraints/iam.allowServiceAccountCredentialLifetimeExtension` existed only to stretch a bearer to 12 hours. Azure OpenAI takes a static key. **The discipline this gate demonstrated is worth keeping and is applied at gate 20b**: read the granted quantity back from the vendor rather than assuming the grant succeeded, and refuse by name when it is short. |
| 16e H | **~~Is the EXTERNAL dead man armed for the rotation loop?~~ RETIRED BY D-410 — the rotation loop is deleted, so the dead man is deleted with it** [D-408] | **A watchdog over nothing is worse than no watchdog, because it reports health.** A green check beside a job that no longer exists is a false statement repeated every four hours, and the incident it causes is the one where somebody believes it. `Settings.in_call_llm_heartbeat_url` is removed, and `apps/api/core/heartbeat.py` with it — D-408 extracted the ping so two callers could share one retry policy, and with one caller left it folds back into `scripts/host_heartbeat.py`. **The backup dead man is a different check on a different failure domain and is UNAFFECTED** — D-50/D-54, §4 below and `runbooks/backup-heartbeat-silent.md`. **Retire the vendor-side check too**, or it pages forever on a job that no longer exists. Do not read this retirement as a retreat from external observers: the argument that an observer must sit outside the failure domain it watches is unchanged and still binds anything with the same shape. |
| 16f H | **WHICH credential FIELDS does Bolna's Azure OpenAI provider expect, and does the agent object accept `provider: "azure"` with our base URL? — the ONE unverified premise in D-410, and it is a MARKED ASSUMPTION, not a fact** [NEW, D-410] | **Treated exactly as `bolna_llm_credential_name` was, and for the same reason: their docs are egress-blocked from this environment, so nothing here may invent a field name and present it as fact.** What IS known and is not in question: Azure OpenAI is on Bolna's published provider list (`OpenAI, OpenRouter, Azure OpenAI, Google Gemini, Custom LLM`), `azure` is in the live per-agent LLM provider dropdown (founder's browser sweep, 19 Aug 2026), and their OSS `LLMProvider` carries both `azure` and `azure-openai`. What is NOT known: which fields their credential store wants for that provider — an Azure deployment needs a resource or endpoint, a key, and a deployment id, and a store shaped for OpenAI may take one string, three, or a different spelling of each. **The test, and it is one call plus one call.** With `BOLNA_API_KEY` set: `GET /providers` — does the endpoint exist and what shape does it return for an Azure entry? Then `POST /providers` with our values and `GET` again — does the entry persist and read back unchanged? Then publish an agent with `provider: "azure"` and place ONE call. **Pass** = the agent answers in language, from our Azure deployment, and the Azure resource's own metrics show the request. **On a fail, do not change code first**: the credential-store entry name is `Settings.bolna_llm_credential_name` (default `AZURE`, `applies: live`), so each attempt is a console edit and a re-publish, no deploy. Record the shape that works and settle the marked assumption in `apps/api/engine/bolna.py::_llm_routing` in the same change. **Wrong answers**: falling back to `provider: "custom"` (gate 16c is why this leg exists), and putting the key anywhere it can be logged. Blocked outside this repo on: a Bolna account AND an Azure subscription with a deployed model. |
| 17 S | **Is `voicemail` a status, or only a flag?** [NEW, D-260] | Our `_STATUS_MAP` maps a `"voicemail"` status and `CallStatus` has a `voicemail` member, but **nothing sourced says that string is ever a status**. What is reported is a separate boolean `answered_by_voice_mail` on Get Execution, and the OSS engine treats voicemail as a HANGUP REASON (`HangupReason.VOICEMAIL_DETECTED`) — both facts about a call whose status is plain `completed`. If that is how the hosted platform reports it, our `voicemail` status is **unreachable** and every voicemail reads to a client as a normal completed call, which is wrong on the campaign screen and wrong for retry logic. **The test:** dial a number that goes to voicemail (with `ConversationConfig.voicemail` detection on, and once with it off). Capture the full Get Execution payload; record the `status` string, `answered_by_voice_mail`, and any `hangup_detail`. **Pass** = we can say which field carries the fact. Fix if it is a flag: `_snapshot` reads it and maps to our `voicemail` status — deliberately NOT done on inference, because it changes what a client's screen says about calls we have never seen. Blocked outside this repo on: a Bolna account. |
| 18 S | **Transfer: is the built-in reachable the way we would need it?** [NEW, D-262] | `BOLNA_CAPABILITIES.transfer=False` was "nobody checked". It is now a statement, and the value is unchanged. Read at source: Bolna DOES implement transfer, as a **`transfer_call` function the LLM invokes mid-conversation** (`bolna/agent_manager/task_manager.py`), latched by `has_transfer`, with the destination from **config** (`transfer_call_params` / `call_transfer_number`), not from the model. That is a different shape from `VoiceEngine.transfer(call_id, to, warm)`, which instructs an execution already in flight; nothing sourced exposes THAT over REST. **The test:** (a) does the hosted `/v2/agent` body accept a transfer tool definition, and under which key? (b) does any REST route transfer a live execution? (c) does a transfer land on Exotel/Vobiz Indian PSTN, and what does the execution record say afterwards (status, `hangup_detail`, cost of both legs)? **Pass** = we can name the mechanism. **This is a design decision, not a flag flip**: using the built-in makes a per-agent escalation number into engine config set at publish time, so it needs a decision-log entry, not just `transfer=True`. Blocked outside this repo on: a Bolna account. Evidence: `docs/vendor/bolna/oss-harvest.md` §5. |
| 19 H | **The Cartesia control plane, the hour an API key exists** [NEW, D-270; not a Bolna gate — it is the EXIT gate] | **Everything below is blocked on exactly one thing outside this repo: a Cartesia account.** Not a legal entity, not a regulator, not a signed term — an API key. Their docs are egress-blocked here, so `docs/vendor/cartesia/` was harvested from Cartesia's own SDKs instead, and `docs/evidence/vendor-cartesia-reconciliation.md` lists what that settled. These are the residue. **(a) THE STRUCTURAL ONE. The port work is DONE (D-280…D-282); what is left is one confirmation.** Their generated clients have no `POST /agents`, and `AgentSummary` carries no prompt, greeting or model: an agent is a DEPLOYED GIT REPOSITORY. `EngineCapabilities.agent_hosting` now says so (`control_plane | external_deployment`), Cartesia's `create_agent`/`update_agent`/`get_agent` and `publish_agent` refuse by name, the conformance suite branches on the capability, and the admin console does not offer the Publish button — `docs/evidence/engine-port-neutrality.md` is the account. **What the key settles: that `POST /agents` really 404s, and that a `PATCH` carrying `system_prompt` is ignored rather than applied.** Both are currently VERIFIED-SDK absences rather than observed responses. If they hold, the next decision is whether publishing becomes ADOPTION — `GET /agents` is real and `name` is documented unique — which is deliberately not implemented, because an adopted agent runs a prompt we did not write and cannot read back, so hard rule 5 would rest on a repository nobody in this deployment can see. That decision needs (b) answered first: adoption is only safe once our prompt reaches the call. Until then no Cartesia deployment can publish an agent at all, which is the correct direction to fail in and is now a named refusal rather than a 404. **(b) The three call paths nothing could source — and one of them now gates DIALLING AT ALL.** `POST /agents/calls` (outbound; REPORTED only, and `from_number_id` with it), `POST /agents/calls/{id}/end` (INFERRED; in `line` a call is ended from INSIDE by the agent), and whether `GET /agents/calls/{id}` returns a transcript without an `expand`. **The new question, and it is the load-bearing one: does the outbound body accept a SYSTEM PROMPT, or is the WebSocket Calls API the outbound path?** On this engine the agent record holds no prompt, so `CallContext.system_prompt` is the only home hard rule 5 has (D-282) — and the REPORTED outbound shape has no field for it, so `CartesiaEngine.start_outbound_call` refuses EVERY dial today rather than placing one with no truthful-answer rule on it. Read what `POST /agents/calls` actually accepts; if it takes a prompt, that field becomes `require_call_compliance_floor`'s `prompt_on_the_wire` argument and the refusal stops firing on its own. If it does not, Cartesia is not dialable from this repository and (a)'s adoption question is closed with it. Place one call, end it from outside, read it back. Also settle the recording: audio is an AUTHENTICATED download at `/agents/calls/{id}/audio`, so `ExecutionSnapshot.recording_url` stays None — decide whether the archive fetches bytes with the engine key or the field stays empty on this engine. **(c) Cost, which is now a COMMERCIAL question rather than an endpoint.** There is no per-call cost field and usage is an account-level DAILY credit meter (`GET /usage/credits`, grouped by capability/model/voice/api_key). `_cost` returns None and hard rule 7 has nothing to convert. Get the rate card in writing (D-94 prices Scale at $0.014/min) and decide whether per-call cost is DERIVED from our own duration times a contracted rate — which is a house number and must be stamped as one. **(d) Which end of `telephony_params` is which.** They document `from` as the AGENT's number and `to` as the CALLER's, which reads inverted on an inbound call, and there is no `direction` field. Place one inbound and one outbound call and read both. Wrong here means a client's CRM shows the wrong party. **(e) The webhook scheme.** Webhooks exist (`AgentSummary.webhook_id`); no SDK carries a signing helper; one search snippet describes an `x-webhook-secret` SHARED SECRET header, which is not an HMAC. `WEBHOOK_AUTH_BY_ENGINE["cartesia"]` is `"hmac"` because it is the only value that fails CLOSED, and both halves refuse every delivery today. Read the page, capture one real delivery's headers, and if it is a shared secret add a `shared_secret` member to `WebhookAuthMethod` and implement it in BOTH halves in one change — never in the receiver alone. **(f) How a document gets INTO the knowledge base.** The QUERY path is read at source and authenticates with a per-CALL agent JWT we never hold; neither generated client has a documents resource at all, so `attach_kb`/`detach_kb`/`list_kb` at `/agents/{id}/documents` are still inference. Upload one document by whatever route exists and record it. **(g) The repeat delete.** `DELETE /agents/{id}` is confirmed; what a SECOND delete answers is not, and `AgentSummary.deleted_at` hints at soft deletion — which would make `absent_is_success` the wrong shape. Same sub-check as gate 2's, run against Cartesia. **Record**: the outcomes in `docs/vendor/cartesia/`, at the evidence classes that file defines. **Fail** = any of (a),(d),(e) unresolved while a deployment runs `ENGINE=cartesia`; the fix is code, never a widened claim. |
| 20 H | **Is the Azure OpenAI resource ACTUALLY in South India? — the endpoint cannot tell you, and this is the residency weakening D-410 records rather than papers over** [NEW, D-410] | **`<resource>.openai.azure.com` names NO region.** Vertex put `asia-south1` in the hostname and in the `locations/` path, so `scripts/check_model_residency.py` could prove residency from the AST; Azure's custom-subdomain form cannot, because the region is a property of the RESOURCE and not of the URL. `AZURE_LOCATION` (`southindia`) is therefore an ASSERTION that one human confirms once, and the code says so where a reader will look. **The test:** open the Azure portal, find the resource named in `azure_openai_resource`, and read its **Location** field on the Overview blade; confirm the same value via `az cognitiveservices account show --name <resource> --query location`. **Pass** = both read South India, and the reading is filed in `docs/evidence/` with the date and who read it, exactly as the restore drills are. **Wrong answers**: inferring the region from the hostname (it carries none), inferring it from latency, and creating a second resource in another region "for failover" — a second region is a second residency posture and needs its own decision-log entry, not a checkbox. **What the guard still proves and is NOT a substitute for this gate**: `AZURE_LOCATION` is the only spelling of the region in shipped code, no `Settings` field can carry a region, no Azure endpoint is constructible except through `azure_openai_base_url()`, and that builder cannot emit a non-India region. Blocked outside this repo on: an Azure subscription. |
| 20b H | **Does `gpt-4o-mini` have QUOTA in South India on this subscription — and how much?** [NEW, D-410] | **Model availability in a region and model quota in your subscription are two different facts, and only the second one lets a call succeed.** `gpt-4o-mini` is documented available in South India; nothing here has read a quota page for our subscription, and Azure grants TPM/RPM per region per subscription. This is also pilot gate 13's fourth leg: the effective concurrency ceiling is the MIN of engine, Sarvam, SIP trunk and this. **The test:** in the portal, Azure OpenAI → Quotas, region South India — read the TPM available for the `gpt-4o-mini` model family; or `az cognitiveservices usage list --location southindia`. Then deploy and make one chat-completions call through `azure_openai_base_url(resource)` with `Authorization: Bearer <key>` and read the response. **Pass** = a 200, and a TPM figure recorded beside the concurrency numbers from gate 13. **Fail** = a 429 with no headroom, or the model absent from the region's list: the remedy is a quota increase request (external, Microsoft's clock) or `gpt-4.1-mini` via `azure_openai_model` — **but 4.1-mini's availability in Indian regions is NOT confirmed** (its default quotas are Sweden Central and East US 2), which is exactly why it is a live switch and not a second shipped default. **Wrong answer**: deploying into a region that does have quota. That is the residency inversion wearing a capacity costume. Blocked outside this repo on: an Azure subscription. |
| 20c H | **Is the deployment REGIONAL STANDARD and not GLOBAL? — Global is the DEFAULT, Global processes worldwide, and no hostname will ever tell you which one you picked** [NEW, D-410] | **This is the residency trap of the whole migration, and it is one dropdown.** Azure's default deployment type is **Global Standard**, which routes requests to capacity anywhere in the world; **Regional Standard** is what keeps processing in the resource's region and is therefore what buys the residency claim this product makes to its clients. The two are indistinguishable from the endpoint, from the SDK, from the response body and from anything `check_model_residency.py` can read — a Global deployment inside a South India resource passes every automated check in this tree and is a residency breach. **It also costs money, deliberately**: Regional runs roughly 5–10% above Global Standard, with published examples up to +12% and +20%. That premium is a payable cost of the posture, not an accident, and it is the Azure analogue of the question gate 14c asked about Vertex and answered NO. **The test:** portal → the Azure OpenAI resource → Deployments → the deployment named in `azure_openai_deployment` → read **Deployment type**; or `az cognitiveservices account deployment show --name <resource> --deployment-name <deployment> --query "sku.name"`. **Pass** = a Standard (regional) SKU, not a Global one, recorded in `docs/evidence/` with the date. **Wrong answers**: Global Standard, Global Batch, DataZone (a DataZone deployment stays in a geography, not a region, and "Asia" is not India), and "we will fix it when we get residency questions" — the client DPA names South India from the day this ships. Blocked outside this repo on: an Azure subscription. |
| 20d L | **Does the v1 surface answer on the REGIONAL hostname `southindia.api.cognitive.microsoft.com`? — because if it does, the AST proof comes back** [NEW, D-410] | **Not a blocker; the only gate here that could make the residency posture STRONGER than it is.** Azure supports a regional endpoint form alongside the custom subdomain and documents the two as interchangeable, but the OpenAI-compatible **v1** surface is documented only on the custom-subdomain form, and custom subdomains are what Entra ID requires — so D-410 ships the subdomain form and records the regional one as rejected-for-now rather than rejected. The prize is concrete: a hostname carrying `southindia` restores exactly what Vertex had, a residency claim `scripts/check_model_residency.py` can prove from a string literal instead of one a human vouches for at gate 20. **The test:** against the same resource and key, `GET`/`POST` the same v1 path on `https://southindia.api.cognitive.microsoft.com/openai/v1/...` and compare the response with the custom-subdomain call. **Pass** = identical behaviour, in which case `azure_openai_base_url()` moves to the regional form, the guard gains a literal to check, and it lands as its own decision-log entry naming this gate as the evidence. **Fail** = anything other than identical (a 404, an auth difference, a required `api-version`), in which case the current shape stands and this row records why. **Wrong answer**: shipping the regional hostname on the strength of the docs' "interchangeable" without making the call — that is the premise class D-31/D-32 exist for. Blocked outside this repo on: an Azure subscription. |

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
