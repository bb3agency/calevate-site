# Bolna request contract — every field we send, diffed against their request schema

**Lane: code → docs.** Every previous wave read the vendor's pages by CATEGORY and checked
our code against what it read. This one runs the other way: enumerate every HTTP request
`apps/api/engine/bolna.py` issues — method, path, query, body — and diff each *field we
actually put on the wire* against the request schema on its own mirrored page.

That axis had never been run. The one defect ever found on it was found by accident
(D-412: `list_executions` sent `from` without `to`, both `required: true`, so the poller
D-31 appoints the guarantee of record 400'd on every tick and had never once run). **This
pass found one more of that class, and it is worse than D-412 because it is silent** —
see F-1.

**Evidence base.** `bolna-findings/mirror/pages/` (READ-ONLY, hash-manifested). Every
verdict below cites a page and a line. Where a page's OpenAPI block and its prose
disagree, the schema block is preferred **and the disagreement is reported**, never
silently resolved. Evidence classes are this repo's own (module docstring of
`apps/api/engine/bolna.py`); the mirror is a first-party HOSTED reference, so it is
**VERIFIED-VENDOR-DOCS** and outranks VERIFIED-OSS on the hosted contract.

**Scope.** 13 `self._request(...)` call sites in `apps/api/engine/bolna.py`, plus the one
delegated builder (`engine/violations.py::walk_violations`, reached from
`BolnaEngine.list_violations`). No other module in this tree issues a Bolna request —
verified by grep across `apps/`, `packages/` and `scripts/`; the pilot harness goes
through the adapter.

---

## Summary

| # | Finding | Class | Severity | State |
|---|---------|-------|----------|-------|
| **F-1** | **`GET /v2/agent/all` is paginated at 20 and we read one page.** The reconciliation fan-out silently stopped at agent 20 and still reported `complete=True` | MISSING-PARAM → silent truncation | **P0 — guarantee of record** | **FIXED**, sabotage-verified |
| F-2 | `GET /providers` is the same shape (bare array, no `has_more`) and `set_llm_credential` counts entries off it | UNDOCUMENTED | low, bounded | **REPORTED** — not fixed, reason given |
| F-3 | `synthesizer.provider_config = {"voice": …}` matches **zero** arms of the documented `oneOf`, and `provider: "sarvam"` is outside the documented enum | WRONG-ENUM / WRONG-SHAPE *as documented* | **publish-path, unverified** | **REPORTED**, evidence class raised in code |
| F-4 | `webhook_url: null` when `AgentConfig.webhook_url` is `None` — a `null` on a `type: string` with no `nullable` | WRONG-TYPE (conditional) | low — unreachable in the publish path | **REPORTED** |
| F-5 | `from`/`to` sent as `…+00:00`; every vendor example prints `…Z` | format ambiguity | low | **REPORTED**, deliberately not changed |
| F-6 | `agent_welcome_message: ""` — an empty string on a `type: string`; whether "" *clears* a stored greeting is unverified | UNDOCUMENTED | low | **REPORTED** |
| F-7 | `calling_guardrails` is omitted, has a **dashboard toggle**, and is read back by nothing — a console click parks our dials until the next `PUT` | UNDOCUMENTED-OFF | compliance-adjacent | **REPORTED** (extends lane F's F-8) |
| F-8 | `PATCH /v2/agent/{id}`'s `telephony_provider` enum **contains `vobiz`** — D-357/gate 28's premise ("no `vobiz` anywhere") is falsified | new capability | product | **REPORTED**, ROADMAP text proposed |
| F-9 | `POST /call` prose and the outbound guide contradict each other on whether `from_phone_number` must be *purchased in the Bolna account* | vendor self-contradiction | gate 25 owns it | **REPORTED** |
| F-10 | `toolchain.execution: "parallel"` — in the enum, but every hosted example of *our* task shape prints `sequential` | contradiction | inert (one pipeline) | **REPORTED**, cross-ref lane F's F-5 |

**No `additionalProperties: false` appears anywhere in the mirror** (grepped: 20 hits, all
`additionalProperties: <schema>` or `: true`). So class 2 — "sent by us, absent from their
schema" — is a *future* tightening risk, not a present 400 anywhere.

**We are on no deprecated surface.** The v1 agent API (`/agent`, `/agent/all`,
`/agent/{id}`) is deprecated in the vendor's own `<Warning>` on all six of its pages
(`api-reference/agent/overview.md:9-13`), and every agent route we send is the `/v2/`
one. This is not merely observed — `tests/bolna_contract_test.py:692-699` already fails
CI if any adapter route matches `/agent` or `/agent/…`. Verified green this pass.

**Fifty distinct payload and query keys across 13 request sites.** Two of them
(`synthesizer.provider`, `synthesizer.provider_config`) fail against the documented schema
and are argued at F-3; one — the pagination `GET /v2/agent/all` needed and did not get —
was the missing-parameter class and is fixed; every other key MATCHES with a page-and-line
citation. The table is the deliverable; findings follow it.

---

## The table

Verdicts: **MATCHES** · **MISSING-REQUIRED** · **UNKNOWN-FIELD** · **WRONG-ENUM** ·
**WRONG-TYPE** · **UNDOCUMENTED** (their docs are silent — a real, reportable state).
All citations are relative to `bolna-findings/mirror/pages/`.

### 1. `POST /v2/agent` (`create_agent`) and `PUT /v2/agent/{agent_id}` (`update_agent`)

Both bind the same `AgentRequestV2` (`api-reference/agent/v2/create.md:126`,
`.../update.md:44`), so one table covers both. Body built by `_agent_body`.

| Field | What we send | What they document | Verdict |
|---|---|---|---|
| `agent_config` | object | `create.md:154-156` `required: [agent_config, agent_prompts]` | MATCHES |
| `agent_prompts` | object | same line | MATCHES |
| `agent_config.agent_name` | `cfg.name` (str) | `create.md:181-183` `required: [agent_name, tasks]`; `:186-189` `type: string` | MATCHES |
| `agent_config.agent_type` | `"other"` | `create.md:202-205` `type: string`, `example: other`, **no enum** | MATCHES |
| `agent_config.agent_welcome_message` | `cfg.opening_line` — may be `""` | `create.md:190-193` `type: string` | MATCHES (see **F-6** for `""`) |
| `agent_config.webhook_url` | `cfg.webhook_url` — `str \| None` | `create.md:194-201` `type: string`, no `nullable` | MATCHES for `str`; **F-4** for `None` |
| `agent_config.tasks` | 1-element array | `create.md:206-210` array of `TasksConfigV2`; `:90` "The `tasks` array must have at least one entry" | MATCHES |
| `tasks[0].task_type` | `"conversation"` | `create.md:249-255` enum `[conversation, extraction, summarization]` | MATCHES |
| `tasks[0].toolchain` | object | `create.md:260-263`; `Toolchain.required: [execution, pipelines]` `:396-398` | MATCHES |
| `toolchain.execution` | `"parallel"` | `create.md:372-376` enum `[parallel, sequential]` | MATCHES — **F-10** |
| `toolchain.pipelines` | `[["transcriber","llm","synthesizer"]]` | `create.md:377-394` array-of-arrays, item enum `[transcriber, llm, synthesizer]`; `:91` names the exact 400 for the flat form | MATCHES |
| `tasks[0].tools_config` | object | `create.md:256-259`; `ToolsConfigV2.required: [llm_agent, synthesizer, transcriber, input, output]` `:364-369` | MATCHES — all five present |
| `tools_config.llm_agent` | object | `create.md:327-330`, `LlmAgentV2` `:612-635` (no `required`) | MATCHES |
| `llm_agent.agent_type` | `"simple_llm_agent"` | `create.md:614-620` enum `[simple_llm_agent, knowledgebase_agent, graph_agent]` | MATCHES |
| `llm_agent.agent_flow_type` | `"streaming"` | `create.md:621-625` enum `[streaming]` | MATCHES |
| `llm_agent.llm_config` | object | `create.md:630-634` `oneOf: [SimpleLlmAgent, KnowledgebaseAgent]` | MATCHES (binds `SimpleLlmAgent`) |
| `llm_config.agent_flow_type` | `"streaming"` | `create.md:790-794` enum `[streaming]` | MATCHES |
| `llm_config.provider` | `"azure-openai"` | `create.md:795-798` `type: string`, no enum; value from `providers/llm-model/azure-openai.md:20` (copy-pasteable body) and `:59` (`\| \`provider\` \| string \| \`"azure-openai"\` \|`) | MATCHES (D-417) |
| `llm_config.family` | `"openai"` | `create.md:799-802` `type: string`, `default: openai` | MATCHES |
| `llm_config.base_url` | `azure_openai_base_url(resource)` | `create.md:898-901` `type: string`, `default: https://api.openai.com/v1` | MATCHES — field exists. Whether the `azure-openai` arm *reads* it stays gate 16f: `azure-openai.md` carries no `base_url` row and the credential store has `AZURE_OPENAI_API_BASE` (`providers.md:101`) |
| `llm_config.model` | `Settings.azure_openai_deployment` | `create.md:803-806` `type: string`; `azure-openai.md:60` "Model/**deployment** name"; `:98` "The deployment name is what you pass as the `model` field" | MATCHES |
| `llm_config.max_tokens` | `400` (int) | `create.md:817-825` `type: integer`, `default: 100` | MATCHES |
| `llm_config.temperature` | `0.1` (float) | `create.md:826-836` `type: number/float`, `default: 0.1` | MATCHES. ⚠ `:92` and `azure-openai.md:29`: GPT-5-series **reject** any value but `1`. Our models are `gpt-4o-mini` / `gpt-4.1-mini` (`azure-openai.md:45,47` — both listed), so `0.1` is correct **today** and becomes a 400 the day anyone points `AZURE_OPENAI_DEFAULT_MODEL` at a GPT-5 deployment |
| `tools_config.synthesizer` | object | `create.md:331-334`; `Synthesizer.required: [provider, provider_config]` `:664-666` | MATCHES (both present) |
| `synthesizer.provider` | `"sarvam"` | `create.md:638-645` enum `[polly, elevenlabs, deepgram, styletts]` | **WRONG-ENUM as documented — F-3** |
| `synthesizer.provider_config` | `{"voice": "bulbul:v3"}` | `create.md:646-650` `oneOf: [ElevenLabsConfig, PollyConfig, DeepgramConfig]` — our object satisfies **none** of the three | **WRONG-SHAPE as documented — F-3** |
| `synthesizer.stream` | `True` | `create.md:651-653` `type: boolean`, `default: true` | MATCHES |
| `tools_config.transcriber` | object | `create.md:335-338`; `Transcriber` `oneOf: [Deepgram…, Sarvam…]` `:667-671` | MATCHES — binds `SarvamTranscriberConfig` uniquely (the Deepgram arm pins `provider: [deepgram]`) |
| `transcriber.provider` | `"sarvam"` | `create.md:1066-1070` enum `[sarvam]` | MATCHES |
| `transcriber.model` | `"saaras:v3"` | `create.md:1071-1077` enum `[saarika:v2.5, saaras:v2.5, saaras:v3, saaras:v4]`; corroborated `providers/transcriber/sarvam.md:63` | MATCHES |
| `transcriber.language` | `cfg.language_primary` ∈ `{te-IN, hi-IN, en-IN}` | `create.md:1078-1093` enum includes `en-IN, hi-IN, te-IN`; `providers/transcriber/sarvam.md:74` "**Telugu** - te-IN" | MATCHES — all three product languages are members |
| `transcriber.stream` | `True` | `create.md:1094-1096` `type: boolean`, `default: true` | MATCHES |
| `tools_config.input` | `{"provider": "plivo", "format": "wav"}` | `create.md:672-689`; `required: [provider, format]`; provider enum `[twilio, plivo, exotel]`, format enum `[wav]` | MATCHES (`plivo` is also their `default`) |
| `tools_config.output` | same | same schema, `create.md:341-346` | MATCHES |
| `tools_config.multilingual_config` | `None` | `create.md:353-362` `default: null`, `nullable: true` | MATCHES — `null` is the vendor's own value |
| `tasks[0].task_config` | object | `create.md:264-269` → `ConversationConfig` | MATCHES |
| `task_config.hangup_after_silence` | `10` (int) | `create.md:401-409` `anyOf: [integer]`, `default: 10` | MATCHES |
| `task_config.call_terminate` | `cfg.max_call_duration_s` (int, seconds) | `create.md:484-490` `anyOf: [integer]`, "disconnects reaching this limit", `default: 90` | MATCHES — unit is seconds on both sides |
| `task_config.auto_reschedule` | `False` | `create.md:520-525` `type: boolean`, `default: false` | MATCHES |
| `task_config.dtmf_enabled` | `False` | `create.md:514-519` `type: boolean`, `default: false` | MATCHES |
| `agent_prompts.task_1` | object | `create.md:233-245`, per-task key `task_<id>` (`:149-153`) | MATCHES |
| `agent_prompts.task_1.system_prompt` | composed prompt (str) | `create.md:238-245` `required: [system_prompt]` | MATCHES |
| *(not sent)* `calling_guardrails` | — | `create.md:207-232`, optional | **F-7** |
| *(not sent)* `ingest_source_config`, `api_tools`, `routes`, and the other 23 `ConversationConfig` keys | — | optional with defaults | out of scope here — enumerated by lane F (`docs/evidence/bolna-agent-lifecycle.md` §6) |

### 2. `POST /call` (`start_outbound_call`)

| Field | What we send | What they document | Verdict |
|---|---|---|---|
| `agent_id` | `EngineAgentRef` (str) | `api-reference/calls/make.md:93-100` `required: [agent_id, recipient_phone_number]`, `format: uuid` | MATCHES |
| `recipient_phone_number` | `E164` | `make.md:101-105` "along with country code (in E.164 format)"; `:63` names the 400 | MATCHES |
| `from_phone_number` | `ctx.from_e164`, **omitted when absent** | `make.md:106-112` "Optional — if omitted, Bolna uses the account's default number" | MATCHES — **F-9** on *which* numbers are accepted |
| `user_data` | `dict[str, str]` | `make.md:119-124` `type: object`, `additionalProperties: true` | MATCHES |
| *(not sent)* `scheduled_at`, `agent_data`, `retry_config`, `bypass_call_guardrails` | — | all optional (`make.md:113-179`) | MATCHES by omission. `bypass_call_guardrails` **must** stay unsent (hard rule 5 — it is a documented gate bypass, `calling-guardrails.md:83`) |

### 3. Everything else

| Endpoint (method + path) | Fields we send | Their schema | Verdict |
|---|---|---|---|
| `POST /call/{execution_id}/stop` (`end_call`) | path param only, no body | `calls/stop_call.md:29-39` — one required path param, no `requestBody` | MATCHES |
| `GET /v2/agent/{agent_id}` (`get_agent`) | path param only | `agent/v2/get.md:29-38` | MATCHES |
| `DELETE /v2/agent/{agent_id}` (`delete_agent`) | path param only | `agent/v2/delete.md:32-41` — `delete:`, `agent_id` `required: true`, 200 `{message: success, state: deleted}`, 400 the only other response | MATCHES — and this was **REPORTED-NOT-READ** in the adapter until this pass; corrected in place |
| `GET /v2/agent/all` (`_agent_refs`) | **was:** nothing. **now:** `page_number`, `page_size=50` | `agent/v2/get_all.md:29-51` declares **no** parameters and a bare array; `pagination.md:9,13-14` and `cli/commands/agents-list.md:9,24-25` document `page_number`/`page_size` with default page size **20** | **F-1 — FIXED** |
| `GET /v2/agent/{agent_id}/executions` (`list_executions`) | `from`, `to`, `page_number`, `page_size=50` | `agent/v2/get_all_agent_executions.md:129-152` — `from` and `to` both `required: true`; `:55-70` `page_number` (min 1), `page_size` ("Maximum allowed is `50`") | MATCHES — **F-5** on the datetime spelling |
| — window width | refuses `> 7 days` (`_LISTING_MAX_WINDOW`) | `get_all_agent_executions.md:22` "The maximum allowed range between `from` and `to` is **7 days**" | MATCHES (`>`, not `>=`, so exactly 7 days is still served) |
| `GET /executions/{execution_id}` (`get_execution`) | path param only | `executions/get_execution.md:114-124` | MATCHES |
| `POST /inbound/setup` (`bind_inbound_number`) | `agent_id`, `phone_number_id` | `inbound/agent.md:36-55` `required: [agent_id, phone_number_id]` | MATCHES |
| — `allow_multiple`, `ivr_config` | not sent | `inbound/agent.md:56-118`, both optional and Plivo-only | MATCHES by omission |
| `POST /inbound/unlink` (`unbind_inbound_number`) | `phone_number_id` | `inbound/unlink.md:36-47` `required: [phone_number_id]` | MATCHES |
| `POST /providers` (`set_llm_credential`) | `provider_name`, `provider_value` | `providers/add.md:55-68` `required: [provider_name, provider_value]`, both `type: string` | MATCHES |
| — the *value* of `provider_name` | `Settings.bolna_llm_credential_name`, default `AZURE_OPENAI_API_KEY` | `providers.md:96-102` names exactly `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_VERSION`; `:40` "All these keys **must** be added" | MATCHES (D-417). Three of four remain an operator step — gate 16f |
| `GET /providers` (`_llm_credential_ids`) | no parameters | `providers/get.md:29-51` declares none; bare `ProviderList` array, no `has_more` | MATCHES — **F-2** |
| `GET /violations/list` (`list_violations` → `walk_violations`) | `status="pending"`, `page_number`, `page_size=50` | `violations/list.md:36-62` — `status` enum `[pending, accepted, rejected, submitted]`, `page_number` min 1, `page_size` `default: 20`, **no documented maximum** | MATCHES |

### Endpoints we deliberately do **not** call

`POST /knowledgebase` (D-354: `multipart/form-data` taking `file` or `url`, no `agent_id`
and no prose field — our `KBSourceRef` carries prose), the whole `/batches` family (hard
rule 5: every campaign goes through our own compliance gate), `GET /user/me`,
`POST /user/model/custom`, `/sip-trunks/*`, `/phone-numbers/*` (D-05), `/dispositions/*`,
`POST /violations/submit`. Each is a documented route with no adapter caller — which is a
different state from a route that does not exist, and `tests/bolna_contract_test.py`'s
`_VENDOR_PATHS` already pins that distinction.

---

## F-1 — `GET /v2/agent/all` is a PAGE and we read it as an ACCOUNT  ·  **FIXED**

**This is the D-412 class, and it is worse, because it fails silently.**

`_agent_refs` sent `GET /v2/agent/all` with no query parameters and treated whatever came
back as the whole account. Two first-party pages say that is a page:

> `api-reference/pagination.md:9` — "The endpoints also support pagination using the
> `page_number` and `page_size` query parameters."
> `:13` — "`page_number` (integer, optional): The page of results to retrieve. Defaults to `1`."
> `:14` — "`page_size` (integer, optional): The number of results per page. **Defaults to
> `20`.** You can request up to `50` results per page."

> `cli/commands/agents-list.md:9` — "List every agent on the account **with pagination**."
> `:24-25` — `--page int` … Default `1` · `--page-size int` … Default `20`

The CLI is the vendor's own client for this exact route, so those flags are that route's
parameters, not a generic statement.

**Why it is worse than the two failures before it.** D-353 (wrong route) was a 404 and
D-412 (missing `to`) was a 400 — both loud, on every tick, surfacing as
`reconciliation_fetch_failed`. This one produces a **200 with fewer rows**. On the 21st
agent the fan-out simply stops asking about the rest, and `list_executions` goes on
answering `complete=True`, because completeness was decided *per agent* and never about
the agent list itself. An execution belonging to agent 21 then produces no lead, no usage
event, no recording, no error and no alarm — the exact sentence D-31 wrote this poller to
make false. **One Bolna account holds every tenant's agents** (the adapter says so in
`_agent_refs`' own docstring), so 20 agents is a handful of clients, not a distant
ceiling.

**Why the fix is safe under both readings of the vendor.** The route's own OpenAPI block
declares no parameters and answers a bare array with **no `has_more` and no `total`**
(`agent/v2/get_all.md:29-51`), so truncation is not detectable from the response and the
two pages above are the only evidence paging exists here. So the walk is written to be
correct either way — the same intersection discipline `_LISTING_MAX_WINDOW` uses for
`from`/`to`:

* if the platform **honours** `page_number`, the walk runs to a short page and the roster
  is whole;
* if it **ignores** the parameter — the shape a FastAPI handler with no declared query
  model has, and their OSS server is FastAPI — page one already carried every agent, page
  two repeats it, the walk sees no new id and stops.

Either way the roster returned is right. Only the *verdict* differs, and an ambiguous
verdict may not claim completeness (`ExecutionListing._verdict_and_reason_agree`): the
repeat case reports `next_link_no_progress`, our own bound reports `page_cap_reached`.
No new `ListingIncompleteReason` member was invented — a roster the walk could not finish
is the same operator event as a listing it could not finish, and a fifth label would be a
runbook entry for a distinction nobody acts on differently.

**Shape of the change** (`apps/api/engine/bolna.py`): `_agent_refs` returns a
`_AgentRoster` NamedTuple (`refs`, `pages_fetched`, `incomplete_reason`) instead of a bare
`list[str]` — a bare list is precisely what could not say "there may be more" —
and `list_executions` seeds both its page counter and its incompleteness from it.

**Tests** (`tests/bolna_listing_test.py`, 5 new clauses): the roster request carries the
documented parameters; an agent past the first page is still walked; a repeating page
refuses completeness; the walk is bounded; and — the clause that pins the exact old
defect — *a clean per-agent walk over an unfinished roster is still an unfinished
listing*.

## F-2 — `GET /providers` is the same shape, and is left alone on purpose

`providers/get.md:29-51` declares no parameters and returns a bare `ProviderList` array
with no `has_more` and no `total`, exactly like `/v2/agent/all`. `pagination.md:9` says
"the endpoints" support paging, so the same doubt applies, and `_llm_credential_ids`
counts entries under one name to decide replace-vs-append semantics.

**Not fixed, and the reason is that the blast radius is bounded and the failure is
visible.** The store holds *named credential keys*, not tenant data: `providers.md`
enumerates the complete vocabulary — 3 Twilio, 3 Plivo, 3 Vobiz, 7 Exotel, 4 Azure OpenAI,
1 each for the other LLM and speech vendors — so an account that has connected everything
it can connect is still comfortably inside a 20-row page, and a miscount surfaces as a
wrong `LlmCredentialPlacement` verdict in a log line rather than as lost calls. Adding a
speculative page walk to a store that cannot plausibly overflow would be inventing a
vendor contract, which is the thing this file refuses to do elsewhere. **Recorded, with
its trigger: if `providers.md`'s key vocabulary ever exceeds 20 for one account, this
becomes real.** Scored at the same gate as F-1.

## F-3 — our synthesizer block matches **no** documented arm, and the enum omits Sarvam

Sharper than "sarvam is missing from the enum", which lane F already noted in passing
(`docs/evidence/bolna-agent-lifecycle.md:421-424`). Two independent mismatches:

1. **`provider`.** `Synthesizer.provider` enumerates exactly `polly`, `elevenlabs`,
   `deepgram`, `styletts` — `create.md:638-645`, and byte-identically at
   `update.md:556-563` and `patch_update.md:329-336`. `sarvam` is in none of them.
2. **`provider_config`.** `create.md:646-650` is
   `oneOf: [ElevenLabsConfig, PollyConfig, DeepgramConfig]`. Our `{"voice": "bulbul:v3"}`
   satisfies **none**: ElevenLabs requires `[voice, voice_id, model]` with
   `voice` enum `[Nila]` (`:943-967`), Polly requires `[voice, engine, language]` with
   `voice` enum `[Matthew]` (`:968-996`), Deepgram requires `[voice, model]` with `voice`
   enum `[Asteria]` (`:997-1015`).

**Read literally, `POST /v2/agent` 400s on every publish and no Calevate agent has ever
been created.** That is the honest worst case and it is why this is stated loudly.

**Five first-party sources contradict that reading**, and three of them are on pages in
this same mirror:

* `create.md:749-756` — the multilingual example in the *same file*:
  `"provider": sarvam` with `provider_config: {voice_id: anushka, model: bulbul:v2}`;
* `create.md:1218-1228` — `MultilingualLanguageEntry.synthesizer.provider`, `example: sarvam`,
  and its `provider_config` description lists `sarvam` among the providers whose language
  is auto-resolved;
* `providers/voice/sarvam.md:38-44` — "List of Sarvam TTS models supported on Bolna AI":
  `bulbul:v3`, `bulbul:v2`, `bulbul:v1`;
* `cli/commands/agents-create.md:48` — the vendor's own CLI config example posting a
  **base-level** `"synthesizer": {"provider": "sarvam", "voice": "Maya"}`;
* `agent-setup/audio-tab.md:117` — the console's TTS provider list: "**AzureTTS**,
  **Cartesia**, **ElevenLabs**, or **Sarvam**".

**The enums are demonstrably illustrative rather than exhaustive**, and the strongest
evidence is internal: `ElevenLabsConfig.voice` is `enum: [Nila]` and `voice_id` is
`enum: [V9LCAAi4tTlqe9JadbCo]` — a single-element enum for a *speaker name* is an example
promoted to a constraint, not a real closed set. The same page's `Transcriber` union
offers two arms while ten transcriber providers have their own pages under
`providers/transcriber/`.

**Nothing changed in the request.** We cannot stop sending Sarvam (D-36), and the
alternative — moving `bulbul:v3` from `voice` to `model` — leaves `voice` unset and
changes what every client's caller *hears* on the strength of an example. What *did*
change is the evidence class recorded in the adapter beside that marked assumption: the
`{model, voice_id}` split was cited as VERIFIED-VENDOR-REPO (`create-agent/SKILL.md`) and
is now **VERIFIED-VENDOR-DOCS** with two hosted citations, and the console's three-field
Provider / Model / Voice split (`audio-tab.md:113-124`) is a third. D-358 still needs
`ModelConfig` to grow a `tts_model` and the catalogue to grow real speaker ids from
`GET /me/voices` — which needs the account. Gate 3 text proposed below.

## F-4 — `webhook_url: null` on a `type: string`

`_agent_body` sends `"webhook_url": cfg.webhook_url` unconditionally, and
`AgentConfig.webhook_url` is `str | None` (`packages/shared/src/calevate_shared/engine.py`).
`AgentConfigV2.webhook_url` is `type: string` with no `nullable` (`create.md:194-201`).

**Unreachable in the publish path** — `agents/service.py:442` builds it from
`Settings.webhook_base_url`, which is a non-optional `str` — so this is only reachable
from a hand-built `AgentConfig`. And the vendor almost certainly accepts it: the PATCH
page documents `null` as the *clearing* value for this exact field
(`patch_update.md:25`: "Pass `null` to remove it"). Left as-is: omitting the key instead
would break the property `agent_welcome_message` is deliberately built on — an omitted key
is a field left as it was, so a webhook we stopped wanting would go on being called.
**Reported, not fixed.**

## F-5 — `from`/`to` are spelled `+00:00`; every vendor example prints `Z`

We send `cutoff.isoformat()`, e.g. `2026-08-21T05:30:21.588283+00:00`. The vendor prints
`Z` three times for these two parameters:

> `get_all_agent_executions.md:23` — "Dates must be in **UTC ISO 8601** format (e.g.
> `2026-06-07T00:00:00.000Z`)."
> `:135` — `example: '2025-05-07T00:00:00.000Z'` · `:147` — `example: '2025-05-14T00:00:00.000Z'`

**Verdict MATCHES, deliberately.** The schema keyword is `format: date-time`
(`:133-134`, `:145-146`), which is RFC 3339, and `+00:00` is conformant RFC 3339 with the
"UTC indication" the field description asks for (`:138-139`). An `example` is an instance
of a format, not a narrowing of it, and this repo's own rule is to prefer the schema block
over the prose.

**Not changed, and the reason is that the swap is not free in the direction it looks.**
`+00:00` fails a naive `strptime("…%SZ")`; `Z` fails a pre-3.11 `datetime.fromisoformat`.
Neither spelling is safe under every plausible parser, so switching trades one unverified
risk for another on a live path that currently satisfies the declared format. Recorded as
the first thing to try if gate 30's listing call returns a 400 it cannot otherwise
explain.

## F-6 — `agent_welcome_message: ""`

We send `""` rather than omitting the key when a tenant volunteers neither notice (D-163),
so that a toggle switched OFF *clears* a greeting the vendor is already holding. The
schema is `type: string` (`create.md:190-193`), so `""` is a valid value and the request
cannot be rejected for it. **What is unverified is the semantic**: no page says whether
`""` clears a stored greeting or is treated as absent. This compounds with lane F's F-4 —
`AgentV2` does not declare `agent_welcome_message` at all, so `get_agent` cannot read the
answer back either. UNDOCUMENTED; folded into gate 2's read-back.

## F-7 — `calling_guardrails`: no documented "off", and a console toggle we cannot see

Lane F (`bolna-agent-lifecycle.md` F-8) already established *why we must not configure it*
— an engine-side reschedule dials without re-entering `check_dispatch`, so DNC, consent,
spend cap and the big red switch are all evaluated once and never again — and D-419
records the decision. **The code→docs axis adds one thing to it that is not in that
entry:**

`_agent_body` states `multilingual_config: null`, `auto_reschedule: false` and
`dtmf_enabled: false` *explicitly*, on the stated principle that an omitted key is a field
left as it was and every one of them has a dashboard toggle. `calling_guardrails` has a
dashboard toggle too — "Toggle on **Outbound call timing restrictions** in the Call Tab.
**It is off by default.**" (`guides/outbound/calling-guardrails.md:21`) — and it is the one
member of that set we omit rather than state. **The vendor documents no value meaning
"off"**: `create.md:207-232` types it a plain object of two integers, with no `nullable`
and no sentinel, unlike `multilingual_config` where `null` is the vendor's own value
(`:361-362`). So we *cannot* state it, and inventing `{0, 23}` would put a 24-hour calling
window on the record of a TRAI-registered telemarketer to express "we are not using your
feature".

The exposure is therefore bounded but real: **between a console click and the next
publish**, a call our gate authorised at 20:58 IST can be parked by the vendor and placed
at 09:00 the following morning without re-entering our gate. Two things bound it, and both
should be written down rather than assumed:

* `PUT` "**replaces the entire agent configuration**" (`patch_update.md:9`), so every
  `update_agent` clears a console-set guardrail — for as long as that sentence holds,
  which is gate 2;
* nothing reads it back. `AgentSnapshot` has no field for it and `_check_semantic_routes`
  — the existing precedent for paging on console drift — covers `routes` only.

**Proposed, not built** (a read-back detector lives in response-parsing code another lane
owns this session): extend the drift sweep's console-drift check from `routes` to
`calling_guardrails`, alarming on any value present. Gate text below.

## F-8 — `vobiz` **is** a documented enum member, on `PATCH`

D-357 and OPERATIONS gate 28 rest on the finding that `POST /v2/agent`'s
`InputOutput.provider` enum is `twilio | plivo | exotel` with no `vobiz`
(`create.md:674-680`) — which is why a 140-series promotional agent cannot be published.
**That premise is now falsified for the platform as a whole, though not for that field.**

> `api-reference/agent/v2/patch_update.md:64` — "Accepted values: `twilio`, `plivo`,
> `exotel`, `vobiz`, `sip-trunk`, `default`."
> `:276-290` — `telephony_provider:` `type: string` … `enum:` `- twilio` `- plivo`
> `- exotel` `- vobiz` `- sip-trunk` `- default`
> `:62` — "When changed, the agent's audio input/output format is **updated
> automatically** to match the provider (`wav` for `twilio`/`plivo`/`exotel`/`vobiz`)."

So the vendor's own answer to "how do I put an agent on Vobiz" is a *different field on a
different verb*: `agent_config.telephony_provider` via `PATCH`, which then rewrites
`input`/`output` itself. `telephony_provider` is on the closed list of eight attributes
`PATCH` accepts (`:19-30`) and appears in **no** `POST`/`PUT` schema — I grepped all four
agent-body pages.

**Two consequences, neither of them a change I made.**

1. Gate 28's question changes from "can a 140-series agent be published at all?" to "does
   `PATCH telephony_provider: vobiz` survive the next `PUT`?" — and the honest expectation
   is **no**: `PUT` replaces the entire configuration (`patch_update.md:9`) and our
   `_agent_body` always sends `input`/`output` `provider: "plivo"`. A publish would silently
   move a 140-series agent back onto the 160-series carrier.
2. Building it is D-357 as written — a per-agent telephony column, a UI control and a
   DLT-series decision — plus a *second* engine call sequenced after every publish. That
   sequencing is the new information: it is not a literal edited in `_agent_body`, and a
   design that treats it as one would be wrong on its first update. Lane G reached the
   same conclusion from the telephony side (`docs/evidence/bolna-telephony.md:418-419`,
   `:625-627`); this is the request-shape half of it.

## F-9 — the vendor contradicts itself about `from_phone_number`

> `calls/make.md:64` — "Invalid `from_phone_number` | Must be a number **purchased in your
> Bolna account**"
> `guides/outbound/making-outgoing-calls.md:197` — "Add your purchased phone number **or
> your own connected phone number** in `from_phone_number` field"

D-05 buys numbers from the telephony vendor directly and connects them to Bolna through
provider credentials (`providers.md:54-68`: `PLIVO_PHONE_NUMBER`, `VOBIZ_PHONE_NUMBER`).
Under the guide's reading that is exactly what `from_phone_number` accepts; under the
error table's reading every dial carrying our DLT-registered header is a 400 and D-420's
fix would never place a call. **The 400 table is prose in a "Common errors" section; the
guide is prose in a worked example; neither is a schema block, so this cannot be resolved
on the page.** OPERATIONS gate 25 already owns "does a non-Twilio Indian number bind at
all" — this adds the outbound half to the same question.

## F-10 — `toolchain.execution: "parallel"` (cross-reference)

Reported by lane F as its F-5. Two citations to add from this pass, both of them
first-party and both for *our exact task shape* — one conversation task, one pipeline of
`[["transcriber","llm","synthesizer"]]`:

> `quickstarts/api.md:101` — `"toolchain": { "execution": "sequential", "pipelines": [["transcriber","llm","synthesizer"]] }`
> `concepts/glossary.md:167` — "Contains `execution` (e.g. `"sequential"`) and `pipelines`"

against `create.md:27` (the minimal working example, also `sequential`). The only
`parallel` in the mirror is `graph-agent/full-example.md:29` — a *graph* agent, a different
`llm_agent.agent_type`.

Our value comes from VERIFIED-OSS (`bolna/assistant.py` and their `API.md`, recorded at
`docs/vendor/bolna/oss-harvest.md:44-45`), a class this file's own docstring ranks **below**
VERIFIED-VENDOR-DOCS on the hosted contract. **Still not changed, and the reason is that
the field is inert here**: `execution` orders *pipelines* relative to one another and we
send exactly one pipeline, so the two values cannot differ in effect. Both are enum members
(`create.md:372-376`), so neither can 400. Changing a live agent body to resolve a
contradiction that has no observable consequence would be taste, not correctness. Recorded
so the next reader inherits both citations rather than re-deriving one of them.

---

## Proposed text for central application

**APPLIED 21 Aug 2026 with centrally assigned numbers.** The two decisions below are
**D-430** and **D-431**; the gate kept the proposed number **30** (`engine/bolna.py::_agent_refs`
already cited it), and the three "extend" items landed as clauses on the existing gates 2, 3
and 25 rather than as rows of their own.

### `docs/ROADMAP.md` §6, decision log

> **D-430 — the reconciliation poller read one page of the agent roster and called it the
> account.** `BolnaEngine._agent_refs` sent `GET /v2/agent/all` with no query parameters
> and treated the response as every agent Bolna holds. The vendor documents that route as
> paginated with a **default page size of 20** — `bolna-findings/mirror/pages/
> api-reference/pagination.md:9,13-14` and, for this exact route, their own CLI's
> `--page`/`--page-size` flags at `cli/commands/agents-list.md:9,24-25`. One Bolna account
> holds every tenant's agents, so from the 21st agent onward the fan-out stopped asking
> about the rest — and `list_executions` went on answering `complete=True`, because
> completeness was decided per agent and never about the agent list itself. This is the
> D-412 class (a listing parameter the vendor requires and we omitted) with the failure
> mode inverted: D-353's wrong route 404'd and D-412's missing `to` 400'd, both loudly on
> every tick; this returned **200 with fewer rows**, so an execution belonging to agent 21
> produced no lead, no usage event, no recording, no error and no alarm — the exact
> sentence D-31 wrote the poller to make false. The walk now sends `page_number` and
> `page_size=50` and is correct under both readings of the vendor: if the platform honours
> the parameter it runs to a short page; if it ignores it (the shape a FastAPI handler with
> no declared query model has) page two repeats page one, the walk sees no new id and
> stops. Because `GET /v2/agent/all` answers a bare array with **no `has_more` and no
> `total`** (`agent/v2/get_all.md:29-51`), truncation is undetectable from the response, so
> the ambiguous case reports `next_link_no_progress` rather than claiming completeness —
> reusing the existing `ListingIncompleteReason` vocabulary rather than adding a fifth
> label for a distinction no operator acts on differently. `_agent_refs` now returns a
> roster carrying its own page count and incompleteness; a bare `list[str]` was precisely
> what could not say "there may be more". Gate 30 settles whether `page_number=2` returns
> different agents at all. Found by the code→docs field audit
> (`docs/evidence/bolna-request-contract.md`).

> **D-431 — `vobiz` is a documented enum member after all, on a verb we do not call.**
> D-357 and gate 28 rest on `POST /v2/agent`'s `InputOutput.provider` enum being
> `twilio | plivo | exotel` (`bolna-findings/mirror/pages/api-reference/agent/v2/
> create.md:674-680`), which is why a 140-series promotional agent cannot be published.
> That remains true of that field, and it is no longer the whole picture:
> `PATCH /v2/agent/{agent_id}` accepts `agent_config.telephony_provider` with
> `enum: [twilio, plivo, exotel, vobiz, sip-trunk, default]` (`patch_update.md:276-290`,
> restated in prose at `:64`) and "the agent's audio input/output format is updated
> automatically to match the provider" (`:62`). So the vendor's route to Vobiz is a
> different field on a different verb, and gate 28's question changes from "can a
> 140-series agent be published at all?" to "does a PATCHed `telephony_provider` survive
> the next `PUT`?" — where the expected answer is **no**, because `PUT` replaces the entire
> agent configuration (`patch_update.md:9`) and `_agent_body` always sends `input`/`output`
> `provider: "plivo"`. The consequence for D-357 is a design constraint rather than a
> capability: a per-agent telephony column would need a PATCH sequenced **after every
> publish**, not a literal edited in `_agent_body`. Nothing is built; recorded so the next
> attempt does not discover it on its first update. Found by the code→docs field audit.

### `docs/OPERATIONS.md` §2, gate table

> **Gate 30 — does `GET /v2/agent/all` paginate?** *(new; blocks nothing, sharpens D-430)*
> With ≥3 agents on the account, call `GET /v2/agent/all?page_number=1&page_size=2` and
> then `?page_number=2&page_size=2`. Record: (a) whether the parameters are accepted at all
> (a 400 here means the roster walk must revert to an unparameterised single request and
> the truncation risk becomes a REPORTED gap again); (b) whether page 2 returns **different**
> agents; (c) whether an unparameterised `GET /v2/agent/all` on an account with >20 agents
> returns 20 or all of them. Answer (b)=different closes D-430's ambiguity and makes
> `complete=True` earnable on a large account; (b)=identical confirms the endpoint does not
> paginate and the walk's no-progress exit is the permanent behaviour. While recording it,
> also `GET /providers` and count the rows against the number of keys the account has
> connected (F-2): if the two differ, that store paginates too and
> `set_llm_credential`'s before/after count is unreliable.

> **Gate 3 (extend) — is `sarvam` accepted as a base `synthesizer.provider`, and in which
> key does the model go?** The `Synthesizer.provider` enum is `polly | elevenlabs |
> deepgram | styletts` on all three agent-body pages
> (`create.md:638-645`, `update.md:556-563`, `patch_update.md:329-336`) and
> `Synthesizer.provider_config`'s `oneOf` has no Sarvam arm, so **as documented** our
> publish body matches nothing and `POST /v2/agent` would 400 on every agent we have ever
> created. Five other first-party sources say otherwise (`create.md:749-756`,
> `create.md:1218-1228`, `providers/voice/sarvam.md:38-44`,
> `cli/commands/agents-create.md:48`, `agent-setup/audio-tab.md:117`). Publish ONE agent
> with today's body and record the status. If it is accepted, record what `GET /v2/agent/
> {id}` echoes back under `synthesizer.provider_config` — that answers D-358's
> `voice`-vs-`model`-vs-`voice_id` question in the same call, and `GET /me/voices` gives the
> speaker list the catalogue needs.

> **Gate 2 (extend) — three read-back questions this pass added.** While the throwaway
> agent exists: (a) does `agent_welcome_message: ""` **clear** a greeting the platform is
> already holding, or is it treated as absent (F-6)? (b) does a `PUT` that omits
> `calling_guardrails` clear a value set from the Call Tab — i.e. is
> `patch_update.md:9`'s "replaces the entire agent configuration" literally true (F-7)?
> (c) does `GET /v2/agent/{id}` echo `calling_guardrails` at all, which decides whether the
> drift sweep can page on a console-set calling window the way it already pages on a
> console-added semantic route?

> **Gate 25 (extend) — `from_phone_number` and BYO numbers.** `calls/make.md:64` says the
> value "Must be a number purchased in your Bolna account"; `guides/outbound/
> making-outgoing-calls.md:197` says "your purchased phone number **or your own connected
> phone number**". D-05 connects numbers through provider credentials rather than buying
> them from Bolna, so under the first reading every DLT-headered dial is a 400 and D-420's
> fix never places a call. One outbound call with a connected `+91` number in
> `from_phone_number` settles it.

---

## What I deliberately left alone

* **`toolchain.execution`** (F-10) — inert with one pipeline, both values are enum members,
  and the contradiction is first-party on both sides.
* **`from`/`to` as `+00:00`** (F-5) — conformant to the declared `format: date-time`;
  swapping to `Z` trades one unverified parser risk for another.
* **`synthesizer.provider_config`** (F-3) — moving `bulbul:v3` to `model` leaves `voice`
  unset and changes what every client's caller hears, on the strength of an example. D-358
  owns it and needs an account.
* **`calling_guardrails`** (F-7) — the vendor documents no value meaning "off", and
  inventing a 24-hour window to express "not using your feature" would put a worse
  sentence on a telemarketer's record than the omission does.
* **`webhook_url: null`** (F-4) — unreachable in the publish path, and omitting the key
  instead would break the clearing semantics the sibling field depends on.
* **The read-back detector for `calling_guardrails`** — response-parsing code, owned by
  another lane this session. Proposed above with its citation.
