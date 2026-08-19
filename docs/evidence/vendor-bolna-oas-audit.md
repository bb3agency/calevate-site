# Bolna adapter — audit against the vendor's own OpenAPI specification

**Date:** 2026-08-18. **Decisions:** D-350 … D-359.
**Evidence:** `docs/vendor/bolna/hosted-oas.md` (the spec, pinned + checksummed),
`docs/vendor/bolna/README.md` (evidence classes).
**Subject:** `apps/api/engine/bolna.py`, `apps/workers/pipeline.py`,
`packages/shared/tests/engine_conformance/`, `apps/api/kb/`, `apps/api/billing/rates.py`.

**Supersedes the standing of `vendor-bolna-reconciliation.md`, not its findings.** That
pass did the best possible job under a false premise. Its rows 4, 5, 6, 7, 8 and 13 were
all marked `REPORTED-DOCS` or `STILL UNVERIFIED` on the stated grounds that "Bolna
publishes no OpenAPI spec"; every one of them is now first-hand.

## What changed about the evidence, before anything changed about the code

Bolna publishes an OpenAPI 3.1.0 document. It is `references/openapi.yml` in
**`bolna-ai/skills`** — their own GitHub organisation — pinned here at `28b24aa`,
`md5 5597f7da080d47564696bc05c12e9112`, mirrored from
`https://www.bolna.ai/docs/api-reference/openapi.yml`. The same repository carries a
`references/` set and nineteen SKILL.md files covering rate limits, webhook delivery,
call statuses, the execution payload and the provider matrix.

`docs.bolna.ai`, `www.bolna.ai`, `docs.bolna.dev` and `api.bolna.ai` remain blocked from
this environment. `github.com` and `raw.githubusercontent.com` were never blocked.
**A statement about a blocked HOST had been allowed to become a statement about an absent
DOCUMENT, and then to become the justification for six separate pieces of guesswork.**
That is the finding; the rest of this document is its consequences.

## CONTRADICTED — things the code believed that the vendor's spec says are false

| # | What we believed | What the spec says | What it would have cost | Fix |
|---|---|---|---|---|
| 1 | `GET /executions?created_after=<iso>` lists executions | **No `/executions` collection exists.** The listing is `GET /v2/agent/{agent_id}/executions`, per agent, filtered by `from`/`to`, paged by `page_number`/`page_size` (max 50) with `has_more` | The reconciliation poller — D-31's *guarantee of record*, the only mechanism that recovers a call whose webhook was lost — 404s on every tick, forever, reported as `reconciliation_fetch_failed` (an engine fault, not a wrong URL) | D-353. Rewritten as a per-agent fan-out over `GET /v2/agent/all` with the documented pagination |
| 2 | `POST /executions/{id}/stop` stops a call | The route is `POST /call/{execution_id}/stop` | Every campaign halt 404s — a lead called after a DNC addition or after the big red switch | D-353 |
| 3 | Bolna publishes no pagination contract, so truncation must be *inferred* from the row count landing on a conventional page size (`_LISTING_PAGE_SIZES`) | `page_number` / `page_size` / `has_more`, plus "Loop until `has_more == false`. Don't try to compute pages from `total` — use the flag" | Under the real contract the heuristic fires on any healthy page of 20 or 50 rows, training the operator to ignore the one alarm that means calls are being lost | D-353. Heuristic, `_claims_more` and `_next_link` deleted |
| 4 | `POST /v2/agent` accepts the flat `SimpleLlmAgent` block, and `input`/`output` are optional | `/v2/agent` binds `ToolsConfigV2`: `llm_agent` is `LlmAgentV2` with settings nested under `llm_config`, and `required` is `[llm_agent, synthesizer, transcriber, input, output]` | 400 on every create. The agent never exists, so nothing downstream of publish can be right | D-355 |
| 5 | `_agent_models` reads `llm_agent.model` | v2 keeps it at `llm_agent.llm_config.model` | `llm_model=None` with `readable=True` — the exact combination the function's docstring forbids, and what the drift judge scores | D-355 |
| 6 | `POST /knowledgebase` takes JSON `{agent_id, name, text}` | `multipart/form-data`, `file` (PDF ≤ 20 MB) **or** `url`, never both; no agent id; no text field | Every KB push rejected; and the created object has no agent, so `list_kb`'s filter on `row["agent_id"]` returned `[]` for every agent on every sweep — which `kb/reconciliation` reads as "the engine holds nothing", i.e. permanent silent drift | D-354. Capability declared absent; three methods refuse by name |
| 7 | `_STATUS_MAP` covers the vendor's statuses | The enum has fifteen members and `rescheduled` was not among ours | An auto-rescheduled call — the normal outcome for any Indian campaign hitting a calling-window boundary — read as `failed` on the client's screen | D-351. `_VENDOR_STATUSES` added; a test fails on any unmapped member |
| 8 | `direction` is a top-level execution field | No such field. Direction is `telephony_data.call_type` | The condition was never true: **every inbound call normalized as outbound**, in both `_snapshot` and `parse_webhook` | D-359 |
| 9 | Bolna webhooks are at-most-once with no retry (one of three "load-bearing" properties at the top of the adapter) | The hosted platform "retries on non-2xx" and fires one delivery per status transition; dedupe on `(execution_id, status)`, "never by `execution_id` alone" | Nothing — the receiver already keys on that pair and acks 2xx. But the premise was cited as the reason the poller exists | D-352. Corrected everywhere it was stated |
| 10 | Bolna's rate limits are unpublished | 500/min on `GET /v2/agent/{id}`, `GET /v2/agent/{id}/executions` and `POST /call`; 1000/min otherwise; per organisation | Nothing changes, but the numbers are what say the new per-agent listing fan-out is two orders of magnitude inside the ceiling | D-350 |
| 11 | No synthesizer model or character count is reported, so the TTS billing tier can only ever be an assumption about intent | `ExecutionUsageBreakdown.synthesizer_model`, `.synthesizer_characters`, `.transcriber_model`, `.transcriber_duration`, `.llm_tokens` and a per-model token map — though in the OAS that schema is an ORPHAN, `$ref`d by no path and no other schema, so only `execution-payload.md`'s prose attaches it to an execution (names VERIFIED-OAS, attachment VERIFIED-VENDOR-REPO) | A client billed premium for a call the engine served on a cheaper voice, undetectably | D-358, named. Turning it into a measurement changes `ExecutionSnapshot`, the adapter and `rates.py` together |
| 12 | Sarvam 105B is the LLM leg on this engine (D-36) | The LLM providers are OpenAI, Azure OpenAI, OpenRouter, Google Gemini and Custom (LiteLLM-compatible). **There is no Sarvam LLM provider.** Sarvam IS a first-class TTS and STT provider | The canonical stack's LLM leg has never been reachable as written; agents run on whatever OpenAI-compatible model the config names | D-356, named. The route is `POST /user/model/custom` + `provider: "custom"`, which needs the account |
| 13 | The `voice` slot takes `bulbul:v3` | The vendor's own Sarvam example is `{"model": "bulbul:v3", "voice": "Ashutosh", "voice_id": "ashutosh"}`, and `GET /me/voices` lists speakers | We are naming a model where a speaker belongs and naming no model at all | D-358, marked in place. Changing it alters what every caller hears, on one prose example |

## VERIFIED — things the code believed that the spec confirms

| Claim | Spec element |
|---|---|
| Five cost-breakdown keys `llm`/`network`/`platform`/`synthesizer`/`transcriber` | `CostBreakdown` |
| Base URL `https://api.bolna.ai`, bearer auth | `servers`, `bearerAuth`; `bolna-core.md` adds that `api.bolna.dev` is deprecated |
| `/v2/agent` for create, `PUT /v2/agent/{id}` for a full update | `manage-agents/SKILL.md`: "`PUT` requires the **full** `agent_config` body", which is what `_agent_body` always builds |
| `POST /call` body fields and `{message, status, execution_id}` response | `/call` requestBody, `MakeCallStatus` |
| Webhook source IP `13.203.39.153`, single address | `bolna-core.md`, `setup-webhook/SKILL.md`, `execution-payload.md` — matches `DEFAULT_BOLNA_SOURCE_IPS` exactly |
| Webhook payload is byte-identical to `GET /executions/{id}` | `execution-payload.md`; `parse_webhook` already reuses `_snapshot` |
| `billable_ready` ⇔ `completed`, ~2-3 min after disconnect, after recordings/transcripts/extractions | `call-statuses.md` |
| `agent_prompts.task_1.system_prompt` is where the prompt lives on a read-back | `AgentPrompt`, `AgentV2.agent_prompts` |
| `conversation_duration`, `telephony_data.recording_url`, `extracted_data`, `answered_by_voice_mail` | `AgentExecution`, `TelephonyData` |
| `toolchain: {execution: parallel, pipelines: [[transcriber, llm, synthesizer]]}` | `Toolchain` (required on `TasksConfigV2`) — D-260's fix confirmed |
| No `voicemail` STATUS exists (D-260's open question) | `AgentExecution.status` enum; voicemail is the boolean `answered_by_voice_mail` |

## The field enumeration, done exhaustively rather than opportunistically

D-359 (`direction`) and D-361 (`ended_at`) were both found the same way and the second was
found deliberately: after one invented field turns up, the move is not to fix that field
but to enumerate EVERY key the adapter reads off a vendor payload and check the whole set.
Done, and recorded here so the next reader inherits the result instead of redoing it.

Every key `apps/api/engine/bolna.py` reads from an execution payload, against the pinned
OAS and `references/execution-payload.md`:

| Key | Status |
|---|---|
| `id`, `agent_id`, `status`, `total_cost`, `cost_breakdown`, `conversation_duration`, `duration`, `transcript`, `extracted_data`, `created_at`, `updated_at`, `telephony_data`, `execution_id`, `has_more`, `data` | declared — VERIFIED-OAS |
| `telephony_data.{call_type, from_number, to_number, recording_url}` | declared — VERIFIED-OAS |
| `started_at`, `ended_at`, `completed_at` | **in neither document.** D-361: harmless because the real field is the other operand of each `or`, now documented and tested rather than lucky |
| `direction` | **in neither document.** D-359: the live defect. Retained only as an inert fallback behind `telephony_data.call_type` |
| `cost_currency`, `currency` | **in neither document, and read ON PURPOSE.** `_cost` looks for any currency field so `currency_stated` can become true the day one appears; the whole point is that our assumed currency must be falsifiable from the payload rather than read back from ourselves |
| `executions` | **in neither document, tolerated spelling** beside the declared `data` envelope key. Costs nothing and is documented at `_listing_rows` |

**No unaccounted-for reads remain.** Every key is either declared by the vendor or is a
deliberately-documented tolerated/absent spelling with a named reason.

## STILL UNVERIFIED, and exactly why

Egress to `api.bolna.ai` is refused by this environment's proxy with a gateway 403 on
CONNECT, for `curl` and for `WebFetch` alike (re-measured 2026-08-18). **No live call was
made and none is claimed.** A specification is what the vendor says the server does.

| Question | Why the spec cannot answer it | The command a human runs on an unblocked machine |
|---|---|---|
| **Is `total_cost` in cents at all?** | **THE VENDOR CONTRADICTS ITSELF.** The OAS says "in cents" on `total_cost` and all five `cost_breakdown` members; `references/execution-payload.md`, same repo same commit, says "Bolna cost in account currency" — major units. `bolna-core.md`'s own precedence rule ("treat the YAML as canonical") breaks the tie toward cents, which is what `_ASSUMED_MINOR_UNITS_PER_MAJOR = 100` already encoded, so no code changes — but reconciling two documents is not observing a server, and the error is 100x per metered call. This is why the D-261 marked assumption is NOT retired | same command as the row below: read `total_cost` beside the same call's charge on the dashboard. One observation, two orders of magnitude apart, impossible to misread |
| Which currency's cents is `total_cost`? | The spec names no currency anywhere. And if the "account currency" reading above is the true one, the answer is the ACCOUNT's currency, which for an Indian account may be INR rather than `_ASSUMED_CURRENCY`'s USD | `curl -sS -H "Authorization: Bearer $BOLNA_API_KEY" https://api.bolna.ai/executions/$EXECUTION_ID \| jq '{total_cost, cost_breakdown}'` beside the same call's charge on the dashboard |
| Does `GET /v2/agent/{id}` return `agent_welcome_message`? | `AgentV2` does not declare it, though the vendor's own PATCH example writes it. If it truly is unreadable, `_agent_greeting` reports `unreadable` forever and no publish can verify the disclosure sentence against the engine | `curl -sS -H "Authorization: Bearer $BOLNA_API_KEY" https://api.bolna.ai/v2/agent/$AGENT_ID \| jq 'keys'` |
| Does the v2 create body we now send actually validate? | Only the server can say | `curl -sS -X POST https://api.bolna.ai/v2/agent -H "Authorization: Bearer $BOLNA_API_KEY" -H 'Content-Type: application/json' -d @body.json` |
| Does `has_more` tell the truth, and does `from` really bound the window? | A flag that lies looks like a clean tick from inside | `curl -sS -H "Authorization: Bearer $BOLNA_API_KEY" "https://api.bolna.ai/v2/agent/$AGENT_ID/executions?page_number=1&page_size=50&from=2026-08-18T00:00:00Z" \| jq '{total, has_more, n: (.data\|length)}'` |
| Is `usage_breakdown` populated in practice? | Declared ≠ emitted — and here not even cleanly declared: `ExecutionUsageBreakdown` is an orphan schema in the OAS, which is the shape of a field the server dropped and the spec never cleaned up | same `GET /executions/{id}`, `jq .usage_breakdown` |
| Does `POST /call/{id}/stop` refuse an execution it is not running? | The spec documents only 200 and 400 | `curl -sS -o /dev/null -w '%{http_code}\n' -X POST -H "Authorization: Bearer $BOLNA_API_KEY" https://api.bolna.ai/call/$EXECUTION_ID/stop` |
| Which provider string routes to a Sarvam-hosted LLM? | Needs `POST /user/model/custom` on a real account first | `curl -sS -H "Authorization: Bearer $BOLNA_API_KEY" https://api.bolna.ai/providers` |

Every one of these is a named gate in OPERATIONS §2. **The API key must never appear in a
commit, a log line or this document; read it from the environment.**

## What the audit says about our test strategy

Four of the thirteen contradictions were routes or bodies the conformance stub *also*
implemented — the stub was written from the same guess as the adapter, so it agreed with
it and the suite confirmed the agreement. A round-trip test through a stub built on the
adapter's assumptions can never disagree with those assumptions.

`tests/bolna_contract_test.py` exists for that reason and is deliberately different in
kind: it asserts the URL, the method and the body KEYS against the vendor's declared
schema, so an invented route or a missing required block fails on shape rather than on
behaviour. That is the cheap half. The expensive half is a captured live payload, which is
what the OPERATIONS §2 gates are for.
