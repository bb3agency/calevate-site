# Bolna response contract — every field we READ, diffed against their schemas

**Lane:** the reverse axis. Earlier waves read Bolna's docs by CATEGORY and checked our code
against them. This one starts from `apps/api/engine/bolna.py` (plus its one helper module
`apps/api/engine/violations.py`) and asks, for every payload key the adapter pulls out of a
response, what the vendor's own schema for that endpoint says.

**Evidence class throughout: VERIFIED-VENDOR-DOCS** — `bolna-findings/mirror/pages/`, the
read-only 333-page mirror with a per-page SHA-256 manifest. Every verdict below cites a page
and a line. Where a page's OpenAPI block and its prose or its examples disagree, **both are
reported and the schema is preferred but never silently** — three of the findings below exist
precisely because the disagreement, not the schema, is where the defect was.

**Scope note.** Only RESPONSE parsing is audited here. `_agent_body` and the other
request-building code is another lane's; where a request field is mentioned it is as evidence
about a response, never as a proposal.

---

## 1. The field table

`R` = how we read it. Verdicts: **MATCHES** · **PHANTOM-FIELD** (we read a key their schema
does not have) · **UNREAD-BUT-MATTERS** · **ENUM-INCOMPLETE** · **WRONG-NESTING** ·
**WRONG-TYPE** · **UNDOCUMENTED** (we read it, they neither declare nor deny it) ·
**DISAGREEMENT** (their own pages contradict each other on this field).

Citation shorthand: `exec/get` = `api-reference/executions/get_execution.md`, `exec/list` =
`api-reference/executions/get_executions.md`, `agent/get` = `api-reference/agent/v2/get.md`,
`status-list` = `guides/post-call/list-phone-call-status.md`. All paths are relative to
`bolna-findings/mirror/pages/`.

### 1.1 `GET /executions/{id}` · listing rows · webhook body — all one `AgentExecution`

Their own words for why these are one shape: *"The payloads for all status events follow the
same structure as the Get Execution API response"* (`status-list.md:82`).

| # | Field | How we read it | What they document | Verdict |
|---|---|---|---|---|
| 1 | `status` | `_snapshot` → `_STATUS_MAP`, default `failed` | `exec/get:164-181` enum of 15; `api-reference/errors.md:41-56` the same table **plus `prepared`** | MATCHES + DISAGREEMENT (16 handled, see §3.1) |
| 2 | `id` | `str(...)` → `engine_call_id` | `exec/get:142-146` uuid | MATCHES |
| 3 | `execution_id` | id fallback | not on `AgentExecution` | PHANTOM (harmless; it is `POST /call`'s name, `calls/make.md:222`) |
| 4 | `transcript` | `parse_transcript` | `exec/get:196-198` string | MATCHES |
| 5 | `created_at` | → `started_at` | `exec/get:199-203` "Timestamp of agent execution" | MATCHES, with the caveat in §4.2 |
| 6 | `started_at` | `created_at` fallback | absent | PHANTOM (known, D-361) |
| 7 | `ended_at` | primary for `ended_at` | absent | PHANTOM (known, D-361) |
| 8 | `updated_at` | `ended_at` fallback | `exec/get:204-208` | MATCHES |
| 9 | `completed_at` | `billable_ready_at` | absent | PHANTOM (known, D-361) |
| 10 | `conversation_duration` | `int(...)` → `duration_s` | `exec/get:156-159` `number/float`, seconds | MATCHES (float→int truncation is deliberate) |
| 11 | `duration` (top level) | `conversation_duration` fallback | absent at top level; **`telephony_data.duration` exists** (`exec/get:280-284`) | PHANTOM — see §4.3 |
| 12 | `telephony_data` | object | `exec/get:212-214` | MATCHES |
| 13 | `telephony_data.call_type` | direction | `exec/get:310-315` enum `outbound`/`inbound` | MATCHES, enum 2/2 |
| 14 | `direction` (top level) | `call_type` fallback | absent | PHANTOM (known, D-359) |
| 15 | `agent_id` | `engine_agent_ref` | `exec/get:147-150` | MATCHES |
| 16 | `telephony_data.from_number` | `from_e164` | `exec/get:291-294` | MATCHES — **but absent from all three captured examples**, §2.1 |
| 17 | `telephony_data.to_number` | `to_e164` | `exec/get:285-290` | MATCHES — same caveat |
| 18-19 | `from_number` / `to_number` (top level) | fallback | absent at top level | PHANTOM |
| 20 | `user_number` (top level) | **NEW** — human party, direction-mapped | not in any schema; in 3 captures (`exec/get:41`, `quickstarts/api.md:246`, `quickstarts/batch.md:138`) | DISAGREEMENT — **FIXED**, §2.1 |
| 21 | `agent_number` (top level) | **NEW** — our end, direction-mapped | not in any schema; `exec/get:42`, `quickstarts/api.md:247` | DISAGREEMENT — **FIXED**, §2.1 |
| 22 | `telephony_data.recording_url` | `recording_url` | `exec/get:295-300` | MATCHES |
| 23 | `recording_url` (top level) | fallback | absent at top level | PHANTOM |
| 24 | `extracted_data` | `flatten_extracted_data` | `exec/get:221-231` object, category-nested per `dispositions/test.md:98-128` | MATCHES |
| 25 | `…{cat}{disp}.objective` | preferred value | `dispositions/test.md:117` string | MATCHES — **but blank handling was wrong**, §2.2 |
| 26 | `…{cat}{disp}.subjective` | fallback value | `dispositions/test.md:115` string | MATCHES |
| 27 | `total_cost` | `_cost` | `exec/get:160-163` "in cents" | MATCHES (unit/currency: D-350/D-411/D-412, unchanged here) |
| 28 | `cost_breakdown` | `_cost` legs | `exec/get:209-211` | MATCHES |
| 29 | `cost_breakdown.{llm,network,platform,synthesizer,transcriber}` | five legs | `exec/get:251-277` | MATCHES, 5/5 |
| 30-31 | `currency` / `cost_currency` | defensive | absent — `AgentExecution` declares no currency | PHANTOM, deliberately kept (hard rule 7 / gate 7) |
| 32 | `transfer_call_data` | `_check_transfer_leg` | `exec/get:215-217`, `348-406` | MATCHES |
| 33 | `transfer_call_data.status` | alarm text | `exec/get:356-370` enum of 11 | MATCHES (not mapped — alarm only) |
| 34 | `transfer_call_data.recording_url` | alarm boolean | `exec/get:389-394` | MATCHES |
| 35 | `transfer_call_data.cost` | alarm boolean | `exec/get:375-378` | MATCHES |

### 1.2 Executions listing envelope — `GET /v2/agent/{agent_id}/executions`

| # | Field | How we read it | What they document | Verdict |
|---|---|---|---|---|
| 36 | `data` | `_listing_rows` | `exec/list:187-191` array of `AgentExecution` | MATCHES |
| 37 | `executions` | tolerated spelling | absent | PHANTOM (harmless) |
| 38 | `has_more` | loop condition | `exec/list:183-186` boolean | MATCHES — see §4.1 on what it does and does not promise |
| — | `total`, `page_number`, `page_size` | **not read** | `exec/list:168-182` | Correctly unread: `references/bolna-core.md` — *"Don't try to compute pages from `total` — use the flag."* |

### 1.3 `GET /v2/agent/{agent_id}` — `AgentV2`

| # | Field | How we read it | What they document | Verdict |
|---|---|---|---|---|
| 39 | `data` / `agent` / `agent_data` envelopes | `_agent_object` | not on the hosted GET (VERIFIED-OSS only) | PHANTOM (harmless, load-bearing for the OSS shape) |
| 40 | `agent_config` wrapper | two-place lookup in 4 readers | **not** on `AgentV2` (`agent/get:54-93`); IS the documented wrapper on write (`agent/v2/patch_update.md:22-33`) and in the object overview (`agent/v2/overview.md:20-32`) | DISAGREEMENT — we already read both places, which is the intersection |
| 41 | `agent_name` | `_agent_name` | `agent/get:58-62` | MATCHES |
| 42 | `name` | fallback | absent | PHANTOM (harmless) |
| 43 | `agent_prompts` | `_agent_system_prompt` | `agent/get:92-97` | MATCHES |
| 44 | `agent_prompts.task_1` | preferred key | `agent/get:187-199` — `AgentPrompt` declares **only** `task_1` | MATCHES |
| 45 | `…task_1.system_prompt` | the prompt | `agent/get:190-197`, required | MATCHES |
| 46 | `agent_welcome_message` | `_agent_greeting` | **not** on `AgentV2`; `cli/commands/agents-view.md:9` says the read *"Returns name, status, welcome message, and system prompt"* | DISAGREEMENT — we answer `readable=False` honestly; gate 2 settles it |
| 47 | `tasks` | `_agent_models`, `_check_semantic_routes` | `agent/get:83-87` | MATCHES |
| 48 | `tasks[].task_type` | **NEW** — pick the conversation task | `agent/get:109-116` enum `conversation`/`extraction`/`summarization` | UNREAD-BUT-MATTERS — **FIXED**, §2.4 |
| 49 | `tools_config` | model + route reads | `agent/get:201-243`, required members | MATCHES |
| 50 | `llm_agent` | model + route reads | `agent/get:203-206` | MATCHES |
| 51 | `llm_agent.llm_config.model` | `llm_model` | `agent/get:506-511`, `679-682` | MATCHES |
| 52 | `llm_agent.model` | v1 fallback | v1 `Llm` (`agent/get_all.md`) | MATCHES on v1 |
| 53 | `llm_agent.llm_config.base_url` | residency read-back | `agent/get:774-777` — `SimpleLlmAgent.base_url` | MATCHES |
| 54 | `llm_agent.base_url` | v1 fallback | `agent/get.md:444` (v1) | MATCHES on v1 |
| 55 | `transcriber.provider` / `.model` | STT read-back | `agent/get:939-953` (`SarvamTranscriberConfig`) | MATCHES |
| 56 | `synthesizer.provider` | TTS read-back | `agent/get:512-521` | MATCHES |
| 57 | `synthesizer.provider_config.voice` | voice read-back | `agent/get:819-828` and the Polly/Deepgram siblings | MATCHES |
| 58 | `llm_agent.routes` → `.routes[]` → `route_name` | compliance alarm | `agent/get:643-661`, `1123-1131` | MATCHES (both the wrapped and bare shapes) |
| 59 | `vector_ids` / `vector_id` | **NEW** — KB reference | `agent/get:806-817` (`KnowledgebaseAgent.vector_store`), `1164-1195` (`LanceDbConfig`) | PHANTOM-in-reverse — **FIXED**, §2.3 |
| 60 | `rag_id`, `rag_ids`, `knowledgebase_id`, `knowledge_base_id`, `vector_store_id` | KB reference guesses | absent everywhere | PHANTOM, retained (a disjunction; an extra name cannot cost an answer) |
| 61 | `id` / `agent_id` for `returned_id` | identity cross-check | `id` at `agent/get:56-59`; `agent_id` absent on v2 | MATCHES / PHANTOM |

### 1.4 The small endpoints

| # | Endpoint | Field | How we read it | What they document | Verdict |
|---|---|---|---|---|---|
| 62 | `POST /v2/agent` | `agent_id` | `create_agent` | `agent/v2/create.md:157-166` `AgentCreateStatus` | MATCHES |
| 63 | `POST /v2/agent` | `id` | fallback | absent | PHANTOM |
| 64 | `POST /call` | `execution_id` | `start_outbound_call` | `calls/make.md:222-227` `MakeCallStatus` | MATCHES |
| 65 | `POST /call` | `id` | fallback | absent | PHANTOM |
| — | `POST /call` | `status`, `message` | **not read** | `calls/make.md:216-221` — `status` enum has ONE member, `queued` | Correctly unread |
| 66 | `GET /providers` | `data` (array wrapper) | `_llm_credential_ids` | `providers/get.md:47-51` — `ProviderList` is a bare array; `vendor_request` wraps it | MATCHES |
| 67 | `GET /providers` | `provider_id` | identity | `providers/get.md:66-69` | MATCHES |
| 68 | `GET /providers` | `provider_name` | filter | `providers/get.md:70-73` | MATCHES |
| — | `GET /providers` | `provider_value` | **not read** | `providers/get.md:74-77` — *"Masked secret value"*, example `xxxxxxxaz` | Correctly unread; masking is why identity is `provider_id` |
| 69 | `GET /v2/agent/all` | `id` | `_agent_refs` | `agent/v2/get_all.md:47-51,64-67` — bare array of `AgentV2` | MATCHES |
| 70 | `GET /v2/agent/all` | `agent_id` | fallback | absent on v2 (VERIFIED-OSS on v1 `GET /all`) | PHANTOM (harmless) |
| 71-78 | `GET /violations/list` | `data`, `has_more`, `id`, `status`, `agent_id`, `execution_id`, `date_of_call`, `created_at`, `updated_at`, `image_url` | `walk_violations` / `parse_violation` | `violations/list.md:78-102` (`ViolationList`), `114-182` (`Violation`) | MATCHES, every one; status enum 4/4 (`violations/list.md:136-144`) |
| — | `GET /violations/list` | `from_phone_number`, `to_phone_number`, `email`, `user_id` | **read and dropped by name** | same page | Correct, and hard-rule-6 load-bearing (`_DISCARDED_FIELDS`) |

### 1.5 Endpoints whose response body we deliberately do not parse

`DELETE /v2/agent/{id}`, `POST /inbound/setup`, `POST /inbound/unlink`, `POST /call/{id}/stop`,
`POST /providers`. In each case the postcondition is a fact about the engine's state, not a
string in a body, and the next read-back is what would catch a 200 that changed nothing. The
adapter says so at each site. **Verdict: correct**, and specifically:
`ProviderAddedStatus.status` has exactly one enum member `added` (`providers/add.md:75-79`),
so parsing it could not distinguish an add from a replace — which is why
`set_llm_credential` counts before and after instead.

### 1.6 Endpoints we do not call at all

| Endpoint | Why not | Verdict |
|---|---|---|
| `GET /user/me` | `wallet`, `concurrency.max`, `concurrency.current` (`user/info.md:68-87`). `PLATFORM_LINES_TOTAL` is a typed-in constant standing in for `concurrency.max`; nothing reads `wallet` | UNREAD-BUT-MATTERS — §3.3, external blocker |
| `GET /knowledgebase/*` | `BOLNA_CAPABILITIES.knowledge_base=False` (D-354). All three KB methods refuse | Correct |
| `GET /batches/*` | We dispatch campaigns ourselves through the compliance gate (`campaigns=False`) | Correct |
| `GET /executions/{id}/log` | Raw engine logs; `raw_document` already archives the execution | Correct |
| `/dispositions/*`, `/phone-numbers/*`, `/voice/*`, `/sip-trunks/*` | No caller | Correct |

---

## 2. Findings that were fixed

### 2.1 `from_e164` / `to_e164` are absent from every captured payload the vendor prints — FIXED

**Class: DISAGREEMENT → permanently-`None` field. The most serious finding in this pass.**

`TelephonyData` declares `to_number` *"Phone number of the recipient"* and `from_number`
*"Phone number of the sender"* (`exec/get:285-294`), and the adapter read exactly there. One
payload example agrees (`status-list.md:120-131`) — and that example is **schema-shaped**: it
lists every declared property in schema order with placeholder values (`"id": 7432382142914`,
`"transcript": "<string>"`), i.e. it is generated from the spec, not captured from traffic.

**The three examples that read like captured traffic put both numbers at the TOP LEVEL under
different names and carry NEITHER inside `telephony_data`:**

- `exec/get:41-42` — the "Completed execution example" on the page for the exact endpoint
  `get_execution` calls:
  ```
  "user_number": "+919876543210",
  "agent_number": "+918035739222",
  ```
  with (`exec/get:51-58`) a `telephony_data` holding only
  `duration`/`recording_url`/`call_type`/`provider`/`hangup_by`/`hangup_reason`.
- `quickstarts/api.md:246-247` — the same pair, same shape, same absence.
- `quickstarts/batch.md:138` — `"user_number"` alone (no `agent_number`) on a batch row whose
  `telephony_data` carries only `recording_url`.

**What it costs if the captures are the live shape, and nothing raises either way.** Three
obligations stop working silently:

- `apps/workers/optout.py:115` picks the opt-out subject as
  `snapshot.from_e164 if inbound else snapshot.to_e164`. `None` → a caller who asked to be
  removed is never added to DNC (hard rule 5).
- `apps/api/compliance/export.py:221` locates a data subject's calls with
  `WHERE from_e164 = :phone OR to_e164 = :phone`. NULL columns → a DPDP erasure finds nothing
  and reports success.
- `apps/workers/pipeline.py:1056` hands `phones=(from_e164, to_e164)` to redaction. Empty →
  the numbers in the transcript are not redacted.

**The fix, and why it cannot make anything worse.** `_party_numbers` reads the documented
`telephony_data` spelling FIRST, then the top-level `from_number`/`to_number` this adapter
already tolerated, and only then the captured spelling. No branch can overwrite a number the
schema path produced, so a payload of either documented shape gets exactly the answer it gets
today; only a payload that answers `None` today changes.

**Why the fallback needs the direction.** Their names are ROLE-based where `from`/`to` are
dial-based, so the two only line up once you know which way the call went. That the human end
is `user_number` is stated first-party outside any example: *"`recipient_data.user_number` —
Referencing the **caller's** phone number"* (`graph-agent/variables.md:82`). The outbound arm
is corroborated by literal: the same two numbers appear as
`recipient_phone_number: "+919876543210"` and `from_phone_number: "+918035739222"` in
`calls/make.md:18,38`, and the capture's `call_type` is `outbound`. The inbound arm is the
role names applied the other way round, which is the only coherent reading of role names —
and it is the one that is not observed, so it is what the proposed gate asks for.

**Tests** (`tests/bolna_snapshot_test.py`): the documented spelling still wins; an
outbound capture yields both numbers; an inbound capture swaps them; a batch row with only
`user_number` yields one side and leaves the other `None`; a blank string in the documented
place does not shadow a real value; `parse_webhook` carries the same two numbers.

### 2.2 A blank `objective` erased the extracted answer — FIXED

**Class: WRONG-TYPE / nullable-assumed-present.**

A Bolna disposition is `is_subjective` and/or `is_objective`
(`dispositions/get.md:112,117`), so one of the two leaf fields belongs to a half the operator
never configured — and the vendor demonstrably emits that half as an **empty string** rather
than omitting it:

```
Escalation:
  Agent Handover Needed:
    subjective: ''
    objective: 'No'
```

(`dispositions/test.md:127-129`, whose response is documented at `:98-101` as *"the same
format as post-call execution data"*.)

That is the objective-only case. Its mirror is the subjective-only one,
`{"subjective": "<the answer>", "objective": ""}`, and `_extraction_value`'s
`if objective is not None` returned `""` for it. So the free text the model extracted never
reached the CRM column, on every call of that shape — with the field name still PRESENT in
`engine_extracted`, so pilot gate 7 (which compares field NAMES) passed it and nothing
downstream could tell.

The fix treats a blank string as absent **for strings only**. `False` and `0` stay answers:
they are what the older flat shape carries (`"user_interested": true, "callback_user": false`,
`exec/get:227-231`), and a truthiness test would have dropped a real extracted answer one type
over. Both directions are tested and both sabotages are shown in §5.

### 2.3 The KB reference key set contained five guesses and not the documented name — FIXED

**Class: PHANTOM-FIELD, all five of them.**

`_AGENT_KB_REF_KEYS` shipped as `{rag_id, rag_ids, knowledgebase_id, knowledge_base_id,
vector_store_id}` under the comment *"Pure guesswork — nothing in their published
documentation says the agent object carries one at all"*. That premise is retired by the
mirror: `tools_config.llm_agent.llm_config` may be a `KnowledgebaseAgent`
(`agent/get:806-817`) whose `vector_store.provider_config` is a `LanceDbConfig`
(`agent/get:1164-1195`) declaring exactly two names —

- `vector_id` — *"Vector id of a single knowledgebase (legacy, use `vector_ids` for multiple)"*
- `vector_ids` — *"Array of vector ids to use multiple knowledgebases simultaneously"*

**Neither was in the set**, so `_agent_kb_refs` answered `readable=False` for every agent that
HAS a knowledge base, permanently — and D-41's question ("does deleting a knowledge base leave
the agent pointing at a dead handle?") could not be answered from a payload that contained the
answer. Note the shape of the failure: not a wrong reference, an unreadable one, which the
adapter is careful never to report as "the reference was cleared".

The adapter's own KB block already named both keys in prose two hundred lines away
(`"llm_config.vector_store.provider_config.vector_ids = [...]`, keyed by the knowledge base's
`vector_id`"`) while the reader looked for five other spellings. That is the whole finding.

**A second half of the same defect, arriving by arithmetic.** `_AGENT_WALK_MAX_DEPTH` was `8`,
described as "four or five levels" with room to spare. The documented path is
`agent_config → tasks[] → [item] → tools_config → llm_agent → llm_config → vector_store →
provider_config → vector_ids` — depth 8 exactly, counting the list as its own level (it is;
`walk` recurses through it). The bound landed on the last dict it had to open, so one more
envelope would have turned a present reference into an absent one. Raised to 10, with the
count written down. The nested test uses the vendor's full depth including the `agent_config`
wrapper, and the shallow-bound sabotage in §5 shows it catching exactly that.

The five guesses stay: `found_key` is a disjunction, an account may still hold agents written
by the older `rag_id` path this adapter itself used, and an extra name can only turn "we could
not find it" into an answer.

### 2.4 `_agent_models` read `tasks[0]`, not the conversation task — FIXED

**Class: WRONG-NESTING (an index assumption where the vendor gives a discriminator).**

`TasksConfigV2.task_type` is an enum of `conversation` / `extraction` / `summarization`
(`agent/get:109-116`) and **every** task carries its own required `tools_config` with its own
`llm_agent`, `synthesizer` and `transcriber` (`agent/get:201-243`). `_agent_body` sends exactly
one task and it is the conversation one, so index 0 is right for every agent this tree
publishes — and wrong the moment a console adds a second, because an extraction task's LLM is
not the model the caller is talking to and its synthesizer is not the voice they hear.

That would be a confident wrong answer with `readable=True` beside it, which
`_agent_models`' own docstring names as the one outcome it must never produce. The fix picks
the task that says `conversation` and falls back to `tasks[0]` where nothing declares a type —
so nothing changes for any agent we publish, and a multi-task agent stops being misreported.

### 2.5 `cost_raw` reported a stated zero as silence — FIXED (minor)

`parse_webhook` read `total_cost` twice and gated on truthiness, so `total_cost: 0` produced
the same `None` as a payload carrying no cost key. Those are different facts — "the engine says
this call cost nothing" versus "the engine has not said yet" — and `billable_ready` is what
separates them everywhere else in this adapter. Zero is not hypothetical: the vendor's own
worked example carries `"llm": 0, "synthesizer": 0` on a 16-second call (`exec/get:59-65`).
Read once, `is None` is the question, matching `_cost`'s treatment of the same key.
`cost_raw` has no consumer today, so this is a correctness tidy, not a behaviour repair.

---

## 3. Findings NOT fixed here, with reasons

### 3.1 The status enum is 16 and their pages print three different lists

Not a defect — recorded because the audit is meant to state where they disagree:

| Source | Members |
|---|---|
| `exec/get:164-181` (OpenAPI) | 15 — no `prepared` |
| `exec/list:71-89` (the `status` FILTER enum) | 15 — no `prepared` |
| `errors.md:41-56` (table) | **16** — includes `prepared` |
| `exec/get:15-29` (prose table) | 13 — no `scheduled`, no `rescheduled`, no `prepared` |
| `status-list.md:51-78` (tabs) | 15 |
| `quickstarts/batch.md:151` (prose) | corroborates `prepared`: *"Per-call `status` starts at `prepared` before the call is placed"* |

`_VENDOR_STATUSES` is the union (16) and
`test_every_status_the_vendor_can_send_is_mapped` proves `_STATUS_MAP` covers it. **Verdict:
already correct, and the widest reading is the right one** — an unmapped member falls to
`failed`, which is terminal, which frees a campaign line under a live call.

Every other enum we touch was checked: `telephony_data.call_type` 2/2; violation `status` 4/4;
`TransferCallData.status` 11 members, read only into an alarm string and correctly not mapped;
`BatchRunData.status` and `AgentV2.agent_status` are not read (see §3.2).

### 3.2 `agent_status` — an enum on the read-back that we ignore

`AgentV2.agent_status` is `seeding` | `processed` (`agent/get:66-73`). `get_agent` does not
read it, so a publish read-back or a drift sweep landing on an agent that is still `seeding`
scores its prompt, greeting and models as though the agent were settled.

**Not fixed, and this is the honest call rather than laziness.** `seeding` appears in the
mirror in exactly four places and all four are the enum itself — the vendor never says what it
means, how long it lasts, or whether a `seeding` agent will answer a call. Building on an
undefined meaning is the D-31/D-32 defect. It also needs a new member on `AgentSnapshot`,
which is a shared model. **Proposed below, and APPLIED as gate 34 (S).**

### 3.3 `GET /user/me` — `wallet` and `concurrency` are readable and unread

`user/info.md:68-87` declares `wallet` (*"Current wallet balance"*) and
`concurrency: {max, current}`. Two things follow:

- `PLATFORM_LINES_TOTAL = 10` in `apps/workers/campaign_dispatch.py` is a typed-in belief about
  `concurrency.max`, which the vendor's own tier text says drifts without a deploy — *"Starts
  at 10 concurrent calls, **scaling automatically with monthly usage**"*
  (`pricing/outbound-calling-concurrency.md:18`). That file already says all of this and names
  the blocker.
- **Nothing reads `wallet`, and `balance-low` is a documented TERMINAL status.** An account
  whose wallet empties fails every dial with a status we map to `failed`; the campaign is
  simply recorded as having failed. A pre-dispatch balance read would turn that into a halt
  with a cause.

**Not built.** It needs a normalized `VoiceEngine` method (hard rule 2 forbids
`apps/workers/` seeing a vendor payload), a new shared model, and a caller in
`campaign_dispatch.py` — two of the three are other lanes' files this session, and the value
cannot be verified without a Bolna account. **Blocker: a vendor account.** Proposed below, and APPLIED as gate 31 (H).

### 3.4 `error_message`, `hangup_by`, `hangup_reason`, `hangup_provider_code` — unread

`AgentExecution.error_message` (`exec/get:190-192`) is one of the two fields the vendor's own
status page calls *"key … throughout its lifecycle"* (`status-list.md:11-16`), and
`TelephonyData` carries a three-field hangup account (`exec/get:322-333`) with a whole page
documenting its values (`guides/post-call/list-phone-call-hangup-status.md`, including the
Bolna-side reasons `inactivity_timeout` and `llm_prompted_hangup`).

**Reported, not built**, and the reason is CLAUDE.md's own rule against half-wired features:
`ExecutionSnapshot` has no member for any of them, `calls` has no column, and no screen or
report asks. Adding a column nobody reads is the defect that looks like progress. Meanwhile
nothing is LOST — `get_execution` seals the whole vendor document into
`ExecutionSnapshot.raw_document` and the pipeline archives it, so the day a failure-reason
column is designed the history is there to backfill from.

One doc contradiction worth having on record for whoever builds it: the OAS calls the numeric
field `hangup_provider_code` (`exec/get:330-333`); the hangup guide calls it `hangup_code`
(`list-phone-call-hangup-status.md:18`).

### 3.5 `answered_by_voice_mail` — unread by decision, not by omission

`exec/get:193-195`. There is no `voicemail` status (D-260 settled this); voicemail is this
boolean on an execution whose status is plain `completed`. Surfacing it is a product decision
about what a client's screen says, and OPERATIONS §2 gate 17 already holds it. **No change.**

### 3.6 `batch_id`, `batch_run_details`, `context_details`, `latency_data`, `usage_breakdown`, `extraction_webhook_status`

Unread, correctly. `batch_*` because we dispatch campaigns ourselves; `context_details` because
we already know what we injected; `latency_data` because it is OPERATIONS §2 gate 4 and its
transcriber entries carry recognised text (hard rules 5/6). Note that `latency_data`,
`usage_breakdown` and `extraction_webhook_status` appear in vendor EXAMPLES
(`exec/get:66-68`, `status-list.md:103-119,157`) and in **no** schema — more evidence, beside
§2.1, that their `AgentExecution` schema is not an exhaustive description of the payload.

### 3.7 `apps/workers/kb_reconciliation.py:36` carries a stale claim

Its docstring says *"`bolna.list_kb` reads `GET /knowledgebase/all`"*. Since D-354 `list_kb`
refuses via `require_capability` and calls nothing. **Not fixed: `apps/workers/` is outside
this lane and the file is being edited concurrently.** It is a comment, not behaviour.

---

## 4. Pagination and type honesty

### 4.1 `has_more` is documented and truthful; the ORDERING is the softer spot

`AgentExecutionV2List.has_more` — *"Whether there are more records or not"*
(`exec/list:183-186`) — and the operating instruction is the vendor's own: *"Loop until
`has_more == false`. Don't try to compute pages from `total` — use the flag."*
(`references/bolna-core.md`). `list_executions` does exactly that, treats an ABSENT flag on a
full page as `full_page_suspected`, and bounds the walk. **Verdict: MATCHES.**

Two things worth stating rather than assuming:

- **It is offset pagination over an unstable sort.** *"The API uses offset-based pagination
  under the hood"* (`pagination.md:18`) and the listing is *"sorted by last run"*
  (`exec/list:156`) — i.e. ordered by something that CHANGES while a call is in flight. A row
  that moves from page 2 to page 1 between our two requests is never returned. Our dedupe by
  execution id handles the duplicate direction and not this one. **It is mitigated rather than
  unhandled**: `reconcile_executions` polls every 10 minutes over a 30-minute window, so a
  skipped row is offered again on each of the next two ticks. Recorded because a future change
  that narrows the window would silently remove that mitigation.
- **`pagination.md`'s example contradicts the schema twice** — it prints `"page": 2` where
  `AgentExecutionV2List` declares `page_number`, and `"status": "success"` which is in no
  execution enum. We read neither field, so it costs nothing; it is one more reason to prefer
  the schema blocks over the narrative pages on this vendor.

### 4.2 `started_at` is their `created_at`, which is not when the phone rang

`created_at` is *"Timestamp of agent execution"* (`exec/get:199-203`) — the row's creation. For
a `scheduled` call, or one auto-rescheduled out of an agent's `calling_guardrails` window, the
row exists hours before the dial. There is **no** documented dial instant anywhere on the
payload: `TelephonyData` offers `ring_duration` and `post_dial_delay` (durations, not
instants). So `created_at` is the best field available and the adapter is right to use it —
but nobody should read `ExecutionSnapshot.started_at` on this engine as "when the call
started". **No fix exists; recorded so the next reader does not assume a precision we do not
have.**

### 4.3 One type trap that is currently harmless and would not stay harmless

`telephony_data.duration` is declared `type: string, pattern: ^\d+$` (`exec/get:280-284`) and
printed as a bare integer `42` in one example (`status-list.md:121`) and `16` in another
(`exec/get:52`) — a schema/example type disagreement. **We do not read it**: `duration_s` comes
from `conversation_duration`, which is a proper `number/float`. The top-level `duration`
fallback (table row 11) is a phantom that never matches.

Left alone deliberately. Switching the fallback to `telephony_data.duration` would need string
coercion for a field that means something different — the CALL's length including ring time,
versus the CONVERSATION's — and `duration_s` feeds the cost-plausibility alarm and the `calls`
row. Changing which quantity that column holds is a decision, not a parser fix.

---

## 5. Sabotage verification

Every behavioural fix was broken, watched RED, restored, watched GREEN. Adapter restored from
a `cp` backup each time (never `git checkout`); post-restore md5 confirmed identical.

**§2.1 — captured-spelling fallback removed** (`return (documented_from, documented_to)`):
```
FAILED tests/bolna_snapshot_test.py::test_an_outbound_execution_shaped_like_the_vendors_own_capture_still_has_numbers
FAILED tests/bolna_snapshot_test.py::test_an_inbound_execution_swaps_the_two_roles
FAILED tests/bolna_snapshot_test.py::test_a_batch_row_carrying_only_the_human_still_yields_the_side_it_names
FAILED tests/bolna_snapshot_test.py::test_a_blank_number_is_not_a_number
FAILED tests/bolna_snapshot_test.py::test_the_webhook_carries_the_same_two_numbers_the_snapshot_derived
5 failed, 57 deselected
```

**§2.1b — direction ignored in the role mapping** (`(ours, human)` on both arms):
```
FAILED tests/bolna_snapshot_test.py::test_an_inbound_execution_swaps_the_two_roles
FAILED tests/bolna_snapshot_test.py::test_the_webhook_carries_the_same_two_numbers_the_snapshot_derived
2 failed, 3 passed, 57 deselected
```

**§2.2 — `if objective is not None:` restored:**
```
FAILED tests/bolna_snapshot_test.py::test_an_empty_predefined_value_does_not_erase_the_free_text
FAILED tests/bolna_snapshot_test.py::test_any_blank_predefined_value_falls_through[]
FAILED tests/bolna_snapshot_test.py::test_any_blank_predefined_value_falls_through[   ]
FAILED tests/bolna_snapshot_test.py::test_any_blank_predefined_value_falls_through[\n]
4 failed, 5 passed, 53 deselected
```

**§2.2b — the over-correction, `if objective:` (drops `False`/`0`):**
```
FAILED tests/bolna_snapshot_test.py::test_any_blank_predefined_value_falls_through[   ]
FAILED tests/bolna_snapshot_test.py::test_any_blank_predefined_value_falls_through[\n]
FAILED tests/bolna_snapshot_test.py::test_a_falsy_but_real_predefined_value_survives[False]
FAILED tests/bolna_snapshot_test.py::test_a_falsy_but_real_predefined_value_survives[0]
4 failed, 5 passed, 53 deselected
```

**§2.3 — `vector_id`/`vector_ids` removed from the key set:**
```
FAILED tests/engine_agent_readback_test.py::test_kb_refs_are_found_at_the_name_the_vendor_actually_documents
FAILED tests/engine_agent_readback_test.py::test_the_legacy_single_vector_id_is_read_too
2 failed, 23 deselected
```

**§2.3b — walk bound back to one level too shallow (`_AGENT_WALK_MAX_DEPTH = 7`):**
```
FAILED tests/engine_agent_readback_test.py::test_kb_refs_are_found_at_the_name_the_vendor_actually_documents
1 failed, 1 passed, 23 deselected
```

**§2.4 — `chosen = tasks[0]` restored:**
```
FAILED tests/engine_agent_readback_test.py::test_the_conversation_task_decides_the_models_not_the_first_task
1 failed, 1 passed, 23 deselected
```

**§2.5 — `if total_cost else None` restored:**
```
FAILED tests/bolna_snapshot_test.py::test_a_stated_zero_cost_is_reported_as_a_cost_and_not_as_silence
1 failed, 61 deselected
```

**Restored, GREEN:**
```
tests/bolna_snapshot_test.py tests/engine_agent_readback_test.py
tests/engine_audit_test.py packages/shared/tests/engine_conformance
  -> 344 passed

tests/pilot_fidelity_test.py tests/publish_verification_test.py
tests/reconciliation_listing_test.py tests/engine_drift_reconciliation_test.py
tests/call_optout_test.py                       -> 127 passed
tests/bolna_contract_test.py tests/engine_violations_test.py
tests/in_call_llm_provider_test.py              -> included in 278 passed
tests/vendor_evidence_guard_test.py             -> 3 passed (mirror unmodified)

uv run ruff check --fix . && ruff format   -> clean
uv run mypy apps packages                  -> Success: no issues found in 238 source files
```

The engine-isolation guard did its job during this change: adding the three new reads failed
`test_every_payload_key_an_adapter_reads_is_classified` with
`['agent_number', 'task_type', 'user_number']` until each was classified. All three went into
`_VENDOR_ONLY_KEYS` (they are role/structure nouns with no Calevate counterpart), which also
bans them repo-wide outside `apps/api/engine/`.

---

## 6. Exact proposed text for OPERATIONS §2 and ROADMAP

**Numbers were proposed; they have since been ASSIGNED centrally and this section carries the
assigned ones.** The highest gate when this lane wrote was 28 and five sibling lanes proposed
rows concurrently. As applied: the decision below is **D-425**; the phone-number gate kept
**29** (the one docstring reference outside this document, in `_party_numbers`, names gate 29);
the wallet gate kept **31**; and `agent_status` moved from the proposed 30 to **34**, because
`engine/bolna.py::_agent_refs` already cited gate 30 for the roster-pagination question a
sibling lane filed.

### OPERATIONS §2 — new row, gate 29 (H) — APPLIED as gate 29

> | 29 H | **Where do the two phone numbers actually live on an execution?** [NEW, 21 Aug 2026, response-contract audit] | `TelephonyData` declares `to_number`/`from_number` (`bolna-findings/mirror/pages/api-reference/executions/get_execution.md:285-294`) and ONE example carries them there — a schema-shaped one, every property in schema order with `"id": 7432382142914` and `"transcript": "<string>"` (`guides/post-call/list-phone-call-status.md:120-131`). The **three** examples that read like captured traffic put them at the TOP LEVEL as `user_number`/`agent_number` and carry NEITHER inside `telephony_data`: `executions/get_execution.md:41-42,51-58`, `quickstarts/api.md:246-247`, and `quickstarts/batch.md:138` (which has `user_number` and no `agent_number` at all). **Our half is done and does not wait on this gate**: `_party_numbers` reads the documented spelling first and the captured spelling only where that yields nothing, so a payload of either shape answers correctly today. **What the gate settles is the INBOUND polarity, which is the one thing nothing observes.** Their names are role-based — *"`recipient_data.user_number` — Referencing the caller's phone number"* (`graph-agent/variables.md:82`) — while `from`/`to` are dial-based, so the mapping flips with direction; the OUTBOUND arm is corroborated by literal (`calls/make.md:18,38` uses the same two numbers as `recipient_phone_number` and `from_phone_number`), the inbound arm is not. **Pass criteria**: fetch ONE completed INBOUND execution and one completed OUTBOUND execution and record, for each, which of the four spellings carried a number and which side it was. **Why it is H**: if both spellings can be absent, `ExecutionSnapshot.from_e164`/`to_e164` are NULL and three things fail silently — the opt-out worker has no DNC subject (`apps/workers/optout.py`), a DPDP erasure matching `calls` on those columns finds nothing (`apps/api/compliance/export.py`), and transcript redaction is handed an empty phone list. If the polarity is inverted on inbound, the opt-out worker would add OUR OWN published number to DNC. Do not infer either answer from an outbound capture. |

### OPERATIONS §2 — new row, proposed gate 30 (S) — APPLIED as gate 34

> | 30 S | **What does `agent_status: "seeding"` mean, and can a `seeding` agent take a call?** [NEW, 21 Aug 2026, response-contract audit] | `AgentV2.agent_status` is an enum of `seeding` \| `processed` (`bolna-findings/mirror/pages/api-reference/agent/v2/get.md:66-73`). The word appears in the mirror in exactly four places and all four are that enum — the vendor never defines it, never says how long it lasts, and never says whether a `seeding` agent answers. `get_agent` does not read it, so a publish read-back or a half-hourly drift sweep landing on a still-seeding agent scores its prompt, greeting and models as though the agent were settled. **Pass criteria**: create one agent, read it back immediately and then at intervals, and record (a) whether `agent_status` is ever `seeding`, (b) for how long, (c) whether `agent_prompts`/`tasks` are complete while it is, and (d) whether `POST /call` against a `seeding` agent succeeds. **What it would change**: a `seeding` verdict from the read-back would become `unreadable` rather than a scored comparison — which is a new member on `AgentSnapshot`, not an adapter tweak, so nothing is built until (a) and (c) are answered. Refuse to guess the meaning: an agent published green on a read-back taken too early is exactly the failure `AgentSnapshot.system_prompt_readable` exists to prevent. |

### OPERATIONS §2 — new row, gate 31 (H) — APPLIED as gate 31

> | 31 H | **The wallet, and the fact that an empty one looks like a fleet of failed calls** [NEW, 21 Aug 2026, response-contract audit] | `GET /user/me` returns `wallet` — *"Current wallet balance of the user"* — and `concurrency: {max, current}` (`bolna-findings/mirror/pages/api-reference/user/info.md:68-87`). Nothing in this tree calls it. Two consequences, and the first is the H: **`balance-low` is a documented TERMINAL execution status** (`api-reference/errors.md:56`), so an account whose wallet empties fails every dial with a status `_STATUS_MAP` sends to `failed` — each campaign is simply recorded as having failed, with no cause anywhere and no halt. Second, `PLATFORM_LINES_TOTAL = 10` in `apps/workers/campaign_dispatch.py` is our typed-in belief about `concurrency.max`, and the vendor says that number moves without telling us: *"Starts at 10 concurrent calls, **scaling automatically with monthly usage**"* (`pricing/outbound-calling-concurrency.md:18`). **Pass criteria**: one authenticated `GET /user/me`, recording the shape and units of `wallet` (which currency? the same open question as gate 7) and the live `concurrency.max`/`current`. **BLOCKER: a Bolna account — nobody in this repo can create one.** **What it unblocks, in order**: a normalized `VoiceEngine` balance/concurrency read (hard rule 2 forbids `apps/workers/` seeing the payload), a pre-dispatch balance check that turns a silent fleet failure into a named halt, and `concurrency.current` as a free cross-check on the dispatcher's own `total_active`. |

### ROADMAP §Decision log — new entry, proposed D-421 — APPLIED as D-425

> **D-425 — The vendor's execution schema is not an exhaustive description of the payload, and one field that is missing from it is compliance-load-bearing.** (21 Aug 2026, response-contract audit.) A field-by-field diff of every response key `apps/api/engine/bolna.py` reads against the schema on its own mirrored page found four defects of one class — we read something that is not shaped how we thought, and nothing errors. (1) `from_e164`/`to_e164`: the OAS puts both numbers on `telephony_data`, but all three of the vendor's CAPTURED examples put them at the top level as `user_number`/`agent_number` and carry neither on `telephony_data` — so on a live payload of that shape both columns would be NULL forever, which silently disables DNC opt-out subjects, DPDP erasure lookups and transcript phone redaction. `_party_numbers` now reads the documented spelling first and the captured spelling as a direction-aware fallback, which is additive under both readings; the INBOUND polarity is the one unobserved half and is gate 29. (2) `_extraction_value` treated an empty `objective` as an answer, and the vendor demonstrably emits the unconfigured half of a disposition as `""` (`dispositions/test.md:127-129`) — so a subjective-only disposition's free text never reached the CRM, with the field name still present so gate 7 passed it. (3) `_AGENT_KB_REF_KEYS` held five guessed spellings and not the two the vendor documents (`vector_id`/`vector_ids`, `agent/v2/get.md:1164-1195`), so every agent that HAS a knowledge base read back `readable=False` and D-41 could not be answered from a payload containing the answer; the walk bound was also exactly one level short of the documented nesting. (4) `_agent_models` took `tasks[0]` where the vendor gives a `task_type` discriminator, so a console-added extraction task would have made the read-back report the wrong model and voice with `readable=True` beside it. **The generalisable lesson, and the reason this is a decision and not four bug fixes: on this vendor an OpenAPI block is a floor, not a ceiling.** `latency_data`, `usage_breakdown`, `extraction_webhook_status`, `prepared` and `user_number`/`agent_number` all appear in first-party examples and in no schema. Prefer the schema where they conflict on a value; do NOT treat schema silence as absence, and read both spellings when the fallback is additive. Fields deliberately still unread, each with its reason, and the three new gates are recorded in `docs/evidence/bolna-response-contract.md`.

---

## 7. What was left alone, and why

- **`error_message` and the three hangup fields** — no member on `ExecutionSnapshot`, no column,
  no reader. `raw_document` already archives them, so the history exists to backfill from when
  a failure-reason surface is designed. §3.4.
- **`answered_by_voice_mail`** — a product decision held by gate 17, not an adapter gap. §3.5.
- **`agent_status`** — the vendor defines neither member; gate 34. §3.2.
- **`GET /user/me`** — external blocker (a vendor account); gate 31. §3.3.
- **`started_at` precision** — no better field exists on the payload. §4.2.
- **`telephony_data.duration`** — reading it would change WHICH quantity `calls.duration_s`
  holds. A decision, not a parser fix. §4.3.
- **The offset-pagination-over-unstable-sort skip window** — mitigated by the poller's
  overlapping windows; recorded so a future narrowing does not remove the mitigation silently.
  §4.1.
- **`apps/workers/kb_reconciliation.py:36`'s stale docstring** — another lane's file. §3.7.
- **Every phantom fallback that costs nothing** (`executions`, `agent`/`agent_data`, top-level
  `from_number`/`to_number`/`recording_url`/`direction`/`duration`, `id` beside `execution_id`,
  the five KB guesses) — each is one dict lookup, each degrades rather than flips, and removing
  them would trade nothing for a risk on shapes nobody has observed live.
