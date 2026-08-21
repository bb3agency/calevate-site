# Bolna agent lifecycle — audit against the mirrored vendor docs

**Lane F.** Subject: the agent create/update/publish/read-back path — `apps/api/engine/bolna.py`
(`_agent_body`, `create_agent`, `update_agent`, `get_agent`, `BOLNA_CAPABILITIES`),
`apps/api/agents/service.py::in_call_llm`, `apps/api/agents/verification.py`,
`packages/shared/tests/engine_conformance/`.

**Evidence base.** Every claim below cites a file under `bolna-findings/mirror/pages/` with a
line number and a quote. Pages read end to end:
`api-reference/agent/{overview,create,update,patch_update,get,get_all,get_all_agent_executions}.md`
(the deprecated v1 set) · `api-reference/agent/v2/{overview,create,update,patch_update,get,get_all,
get_agent_execution,get_all_agent_executions,delete,stop}.md` ·
`agent-setup/{overview,agent-tab,llm-tab,audio-tab,engine-tab,call-tab,tools-tab,analytics-tab,
inbound-tab,call-history,agent-builder,copy-import-agent}.md` — 29 pages.

**Evidence classes** are this repo's own (module docstring of `apps/api/engine/bolna.py`).
The mirror is a first-party HOSTED reference, so it is cited as **VERIFIED-VENDOR-DOCS** and
outranks VERIFIED-OSS on every question about the hosted contract.

---

## Summary

| # | Finding | Severity | State |
|---|---------|----------|-------|
| F-1 | Multilingual per-language `system_prompt` can replace the running prompt, dropping `TRUTHFUL_ANSWER_DIRECTIVE` while the read-back still scores it applied | **compliance, hard rule 5** | **FIXED** (adapter now states it off; sabotage-verified) |
| F-2 | `LlmAgentV2.routes` returns a **static response** without consulting the LLM — a second config surface that can answer "are you an AI?" | **compliance, hard rule 5** | **REPORTED** — needs a shared-model change (Lane B) |
| F-3 | Webhook source-IP allowlist holds **1 of the vendor's 3 documented egress IPs** | **P0, cross-lane** | **REPORTED** with exact diff — `config.py` is not my lane |
| F-4 | `AgentV2` (the read-back schema) does **not** declare `agent_welcome_message`, so every Bolna publish lands `unreadable`, never `applied` | operational | **RECORDED** in the adapter; gate text proposed |
| F-5 | `toolchain.execution` — we send `parallel`, the vendor's own minimal working example sends `sequential` | ambiguity | **REPORTED**, not guessed |
| F-6 | `check_if_user_online` defaults **true** at 10 s while we set `hangup_after_silence: 10` — an unscripted utterance in an unknown language, at a threshold that races ours | product | **REPORTED**, founder decision |
| F-7 | `knowledge_base=False` — the two D-354 facts are still true for the *create* path, but `KnowledgebaseAgent`/`vector_ids`/the LLM-tab multi-select are all real | — | **REPORTED to Lane G**, flag not touched |
| F-8 | `calling_guardrails` / `auto_reschedule` are engine built-ins we deliberately do **not** configure — and the reason is now a hard one | — | **RECORDED**, decision-log entry proposed |

**No gap found** on: v1-vs-v2 (item 1), PATCH-vs-PUT (item 2), agent read-back for the *prompt*
(item 5), and the `campaigns` / `number_series` / `transfer` / `stt` / `tts` / `llm` /
`agent_hosting` / `webhook_auth`(method) capability flags. Each is argued below rather than
asserted.

---

## 1. v1 vs v2 — we are on v2. No gap.

**The v1 set is deprecated in the vendor's own words.**
`api-reference/agent/overview.md:5,10`:

> `# Bolna Voice AI Agent APIs Overview (deprecated)`
> "These APIs have now been deprecated."

The same `<Warning>` block heads all five v1 pages (`create.md:9-13`, `update.md:9-13`,
`patch_update.md:9-13`, `get.md:9-13`, `get_all.md:9-13`).

**Every agent route this adapter calls is the v2 one**, verified by reading the call sites:

| Adapter call site | Path sent | v2 doc |
|---|---|---|
| `create_agent` | `POST /v2/agent` | `v2/create.md:102` |
| `update_agent` | `PUT /v2/agent/{ref}` | `v2/update.md:13` |
| `get_agent` | `GET /v2/agent/{ref}` | `v2/get.md:13` |
| `delete_agent` | `DELETE /v2/agent/{ref}` | `v2/delete.md:16` |
| `list_agent_refs` | `GET /v2/agent/all` | `v2/get_all.md:13` |
| `list_executions` | `GET /v2/agent/{ref}/executions` | `v2/get_all_agent_executions.md:28` |

`create_agent` even carries the standing instruction as a comment: *"legacy unversioned agent
paths are deprecated, never call them."*

**The body shape is the v2 one too**, which is the half that actually matters — the paths would
404 loudly, the body would not. `v2/create.md:625-632` nests the model settings under
`llm_config`:

```
        routes:
          $ref: '#/components/schemas/Routes'
          type: object
          description: Semantic routing layer
        llm_config:
          oneOf:
            - $ref: '#/components/schemas/SimpleLlmAgent'
```

against the v1 `LlmAgent`, which is flat (`api-reference/agent/create.md`, diffed: v1 declares
`model`, `provider`, `family`, `base_url`, `temperature`, `max_tokens` directly on `llm_agent`).
D-355 already moved us; `tests/bolna_contract_test.py::test_the_llm_block_uses_the_v2_nesting_the_v2_endpoint_requires`
pins it. **No live migration is outstanding and no vendor deadline is running against this
product on the agent surface** — the v1 pages carry no sunset date at all.

Two v2-only affordances we do not use and do not need: `ingest_source_config` (CRM ingestion for
inbound matching — ours is `apps/api/crm`) and `calling_guardrails` (F-8).

**One ambiguity, recorded not guessed.** `v2/get_agent_execution.md:13` declares its path as
`GET /agent/{agent_id}/execution/{execution_id}` — *unversioned*, despite living under `v2/`.
Every other page in the `v2/` directory declares a `/v2/`-prefixed path. That is an execution
route (Lane A's surface), noted here only because it is inside my page set.

---

## 2. PATCH vs PUT — `PUT` is correct for us, and the doc says why. No gap.

`v2/patch_update.md:9` is explicit about the semantics:

> "Partially update an existing agent. Unlike the [full update](...) (`PUT`), which **replaces
> the entire agent configuration**, `PATCH` only touches the attributes you include in the
> request body — everything else is left unchanged."

**`PATCH` cannot carry what a publish must carry.** `v2/patch_update.md:19-33` closes the set:

> "Only the following attributes can be updated via `PATCH`. **Any other field in the body is
> ignored.**" — `agent_name`, `agent_welcome_message`, `webhook_url`, `synthesizer`,
> `ingest_source_config`, `telephony_provider`, `calling_guardrails`, `agent_prompts`.

`tasks` is not on that list, so `PATCH` cannot change the transcriber, the LLM leg, `max_tokens`,
`call_terminate` or `hangup_after_silence`. `publish_agent` republishes the whole
`AgentConfig` (script, disclosure, all three model legs, call cap) in one transaction, so `PUT`
is the only verb that can express it. The `AgentRequestV2` schema on `PUT` is byte-identical to
the one on `POST` — I diffed the two `components:` blocks and the only difference is the response
name (`AgentCreateStatus`/`state: created` vs `AgentUpdateStatus`/`status: updated`).

**The "silently wipes dashboard config" hazard is real but points the other way, and it is the
reason F-1's fix is written the way it is.** Because `PUT` replaces, a field an operator set in
the Bolna console and we never send *is* dropped at the next publish — which for `routes`,
`multilingual_config`, `voicemail`, `dtmf_enabled` and `auto_reschedule` is the outcome we want
(our layer is the authority). What we must not do is *rely* on that: nobody here has observed
`PUT` against a live account (OPERATIONS §2 gate 2), the adapter's own `agent_welcome_message`
comment already assumes the opposite ("an omitted key is a field left as it was"), and a
compliance floor is not a thing to rest on unobserved merge semantics. Hence F-1.

Note also `v2/patch_update.md:25`: `webhook_url` accepts `null` "to remove it" — so a nullable
key on this vendor is a real clearing value, not a validation error. That is the precedent the
F-1 fix stands on.

---

## 3. Compliance invariants (hard rule 5)

### F-1 — multilingual switches the **active system prompt** mid-call. **FIXED.**

`v2/create.md:708-716`:

> `MultilingualConfig:` … "Multilingual configuration for an agent. When `enabled` is true, Bolna
> keeps a transcriber and synthesizer per language and **switches them, along with the active
> system prompt, during the call.**"

`v2/create.md:1230-1238`, `MultilingualLanguageEntry.system_prompt`:

> "Prompt activated while the agent speaks this language. Write it in the language's native
> script."

The console equivalent, `agent-setup/agent-tab.md:39`:

> "Each language gets its own prompt. Select a language tab and write the prompt for that
> language. **The agent activates the matching prompt when speaking in that language during a
> call.**"

**Why this is hard rule 5 and not a feature note.** `compose_engine_prompt` puts
`TRUTHFUL_ANSWER_DIRECTIVE` into `agent_prompts.task_1.system_prompt` and nowhere else;
`verification.judge` reads `TRUTHFUL_ANSWER_MARKER` back from exactly there. An agent with
multilingual enabled would, for every language but the base one, run a prompt carrying **none**
of the floor — while the read-back scored `truthful_answer_applied=True` off a prompt that is
not the one in use. A caller asking "మీరు AI నా?" in Telugu would be answered by a prompt with
no rule requiring the truth. That is precisely the shape the rule forbids: *a config row
withdrawing the directive*, invisible to every instrument we have.

This is not hypothetical for a Telugu-first product: `agent-setup/audio-tab.md:38-58` lists
Telugu (`te`), Hindi (`hi`), Tamil, Kannada, Marathi and eleven more, and the Agent tab's
`+ Add Language` is two clicks from any agent we publish.

**Fix applied** — `apps/api/engine/bolna.py::_agent_body` now states the key rather than
omitting it:

```python
"multilingual_config": None,
```

`v2/create.md:353-362` makes `null` the vendor's own value for this key —
`default: null`, `nullable: true` on `ToolsConfigV2.multilingual_config` — so stating it can
neither be rejected nor mean anything but single-language, and it clears a console-enabled
multilingual config on every publish without depending on `PUT` replace semantics we have never
observed. Red-then-green evidence below.

**What is NOT closed.** If this product ever wants a genuinely multilingual agent, the composer
has to run per language: `compose_engine_prompt` would render one prompt per entry in
`multilingual_config.languages`, each carrying `TRUTHFUL_ANSWER_DIRECTIVE` *in that language*,
and the judge would have to read every one of them back. That is a shared-model change and a
translation question (the directive is English prose today), so it is a decision, not a flag —
proposed decision-log entry **D-418** below (applied centrally 20 Aug 2026).

### F-2 — `routes` answers **without the LLM**. REPORTED (needs Lane B).

`v2/create.md:625-629`, on `LlmAgentV2`:

> `routes:` `$ref: '#/components/schemas/Routes'` — "Semantic routing layer"

`v2/create.md:767-785`:

> "These are **predefined routes** that can be used to answer FAQs, or set basic guardrails, or
> do a static function call."

`v2/create.md:1247-1282`, on one `Route`:

> `utterances:` "This is an array of utterances which when spoken you want to send a **static
> response**"
> `response:` example `Hey, thanks but I do not have opinions on politics`
> `score_threshold:` "Similarity score threshold", `default: 0.85`

**The hazard.** A route whose `utterances` include "are you a robot", "am I talking to a human",
"is this recorded" would answer from configuration, with a semantic match at 0.85 similarity, and
the system prompt would never be consulted. `TRUTHFUL_ANSWER_DIRECTIVE` is an instruction to a
model that is not asked. Our drift judge scores the prompt, the greeting and the voice; nothing
in `AgentSnapshot` can see a route layer, so this would be invisible indefinitely — the exact
failure mode `agents/verification.py`'s own docstring describes ("somebody edits the agent in the
VENDOR'S OWN DASHBOARD … every table we own agrees with itself and is wrong").

**Why it was not fixed on the write side.** Unlike `multilingual_config`, `routes` is declared
`$ref: Routes` with **no `nullable` and no `default`** (`v2/create.md:625-629`). Sending `null`
is therefore not a documented value, and sending `{"routes": []}` is a guess about what their
semantic router does with an empty layer — a guess that could 400 every publish. D-31/D-32/D-350
are what happens when this repo guesses a vendor shape. Reported, not guessed.

**Proposed fix — exact diff.** The read half is the one that matters, and it needs one field on
a shared model. `packages/shared/src/calevate_shared/engine.py` is Lane B's this wave, so the
diff is written out rather than applied:

```diff
--- a/packages/shared/src/calevate_shared/engine.py
+++ b/packages/shared/src/calevate_shared/engine.py
@@ class AgentSnapshot(BaseModel):
     models_readable: bool = False
+    #: **Can this agent speak WITHOUT consulting the prompt?** (hard rule 5.)
+    #:
+    #: Some engines carry a static-response layer beside the model — Bolna's
+    #: `LlmAgentV2.routes` matches a caller utterance semantically and returns a
+    #: configured string, the LLM never asked. `TRUTHFUL_ANSWER_DIRECTIVE` is an
+    #: instruction to a model, so a layer that answers instead of the model can
+    #: answer "are you an AI?" untruthfully while `carries_prompt_marker` still
+    #: reports the floor present. The prompt read-back cannot see that, which is
+    #: why this is a field and not a derivation.
+    #:
+    #: The COUNT, never the routes: their utterances and responses are vendor
+    #: config we have no reason to carry across the boundary (hard rule 2), and
+    #: "how many" is the whole of what a verdict needs.
+    static_response_routes: int = 0
+    #: True only when the adapter positively located the layer's field. The
+    #: `*_readable` tri-state for the fifth time and for the same reason: "this
+    #: engine has no route layer" and "we could not find it" are different facts.
+    static_response_routes_readable: bool = False
```

then in `apps/api/engine/bolna.py` (mine, ready to apply the moment the field lands):

```python
def _agent_static_routes(agent: dict[str, Any]) -> tuple[int, bool]:
    """`(count, readable)` — configured static-response routes on this agent.

    `LlmAgentV2.routes` is a `Routes` object whose `routes[]` each answer a matched
    utterance with a `Route.response` string, the LLM never consulted
    (`bolna-findings/mirror/pages/api-reference/agent/v2/create.md`). Nothing this
    tree publishes sends one, so any count above zero is config that arrived from
    the vendor's console — and it can answer a caller who asks whether they are
    talking to an AI.
    """
    config = agent.get("agent_config")
    source = config if isinstance(config, dict) else agent
    tasks = source.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return 0, False
    tools = tasks[0].get("tools_config") if isinstance(tasks[0], dict) else None
    llm_agent = tools.get("llm_agent") if isinstance(tools, dict) else None
    if not isinstance(llm_agent, dict) or "routes" not in llm_agent:
        return 0, False
    layer = llm_agent.get("routes")
    if layer is None:
        return 0, True
    routes = layer.get("routes") if isinstance(layer, dict) else None
    return (len(routes) if isinstance(routes, list) else 0), True
```

and in `apps/api/agents/verification.py::judge`, one more entry in `checked`:

```python
routes = (
    None if not snapshot.static_response_routes_readable else (snapshot.static_response_routes == 0)
)
checked = (
    ("greeting disclosure", disclosure),
    ("truthful-answer rule", truthful),
    ("no static-response layer", routes),
    ("script", prompt),
    ("voice", voice),
)
```

`False` there is a REFUSAL, which is correct: an agent that can answer from config instead of
from the prompt must not be published or left running. `fake.py` returns `(0, True)` and the
conformance clause asserts an adapter that cannot see the layer reports `readable=False` rather
than a confident zero.

### Everything else in their config model that could withdraw our sentences — checked, clear

| Field | Page | Verdict |
|---|---|---|
| `agent_welcome_message` | `v2/create.md:190-193` | **Ours.** `_agent_body` sends `cfg.opening_line`, and `""` when both D-163 toggles are off, so a withdrawn notice actually clears. |
| `call_hangup_message` | `v2/create.md:546-559` | "Final message the agent speaks before disconnecting." A closing utterance; cannot answer a mid-call question. We do not send it; default `null`. No withdrawal. |
| `hangup_after_LLMCall` + Agent-tab "Hangup Using Prompt" | `v2/create.md:410-416`, `agent-tab.md:158-206` | Lets the model end the call on a condition. Could in principle end a call *after* an awkward question, but it cannot make the agent answer untruthfully — the floor is still in the prompt. Default `false`; we do not send it. Recorded, not a finding. |
| `call_cancellation_prompt` | `v2/create.md:437-441` | **Undocumented** — a title and `example: null`, no description anywhere in my page set. We do not send it. Reported as an unknown, not guessed. |
| `MultilingualLanguageEntry.handoff_message` / `agent_name` | `v2/create.md:1239-1246` | Per-language static strings. Unreachable once F-1's fix states multilingual off. |
| `switch_tool_description` | `v2/create.md:758-765` | Overrides the description of the `switch_language` tool. Same — unreachable with multilingual off. |
| `ApiTools` / `TransferCallTools` | `v2/create.md:347-352, 690-706` | Tools the LLM may call. They act, they do not answer identity questions. Handled by `_check_transfer_leg` (added by the executions lane, using this lane's pages). |
| `agent_prompts.task_N` for N>1 | `v2/create.md:233-247` | We create exactly one task. `_agent_system_prompt` prefers `task_1` and refuses to guess between several — already correct. |

**`compose_engine_prompt` itself is unchanged and correct**: opening prepended, script, directive
appended last. The one thing the vendor docs add is that appending-last is the *riskier* end —
`agent-tab.md:82` shows the prompt editor carrying "a **token count** in the bottom-right to help
you stay within LLM limits", i.e. long prompts are a real condition on this platform, and
`verification.py` already scores the directive separately for exactly that reason.

---

## 4. Capability constants — verified flag by flag

`BOLNA_CAPABILITIES` in `apps/api/engine/bolna.py`.

| Flag | Value | Verdict against the mirror |
|---|---|---|
| `stt` / `tts` / `llm` | `"ours"` (BYOK) | **Correct.** `llm-tab.md:40`: "Connect your own provider keys in [Providers] to reduce costs and access more models." `audio-tab.md:84-94` lists nine STT providers and `:117` four TTS providers, as per-agent, per-language choices. |
| `agent_hosting` | `"control_plane"` | **Correct.** `v2/overview.md:12-15` — `POST /v2/agent`, `GET /v2/agent`, `PUT /v2/agent/:agent_id`, `GET /v2/agent/all`. The agent is a record on their platform and the prompt is part of it. |
| `campaigns` | `False` | **Correct as the field is defined** ("is there an engine-side campaign object OUR code depends on"). Their batches exist — `call-history.md:70` filters by "Batch", `get_all_agent_executions` takes `batch_id` — and we deliberately do not use them (hard rule 5; the compliance gate cannot be delegated). |
| `number_series` | `frozenset()` | **Correct.** Nothing in my page set sells numbers. `v2/patch_update.md:66-70` enumerates telephony providers (`twilio`, `plivo`, `exotel`, `vobiz`, `sip-trunk`, `default`) — a carrier choice, not a number series. |
| `transfer` | `False` | **Correct, and the evidence class rises** — see below. |
| `webhook_auth` | `"source_ip"` | **Method correct; the ADDRESS SET IS WRONG.** F-3. |
| `knowledge_base` | `False` | Lane G's. See F-7. |

### `transfer=False` — comment upgraded, gate 18's vendor half answered

The comment claimed VERIFIED-OSS only and left gate 18 asking "does the hosted agent object
accept a transfer tool, and is there any REST route that transfers a live execution?" My pages
answer both.

**Yes to the first.** `v2/create.md:347-352, 690-696` — `ToolsConfigV2.api_tools` → `ApiTools.tools[]`
`oneOf` `TransferCallTools` (`v2/create.md:1114-1156`), `key: transfer_call`;
`v2/create.md:1157-1180` — `TransferCallToolParams.param`, "Stringified JSON of the tool schema", example
`{"call_transfer_number": "+19876543210","call_sid": "%(call_sid)s"}`. The destination is fixed
when the agent is configured, exactly the OSS shape. `agent-setup/tools-tab.md:31` is the
console equivalent: "Transfer Call — Route the call to a human agent or another phone number".

**No to the second.** The complete v2 agent surface is `POST /v2/agent`, `GET /v2/agent/{id}`,
`GET /v2/agent/all`, `PUT /v2/agent/{id}`, `PATCH /v2/agent/{id}`, `DELETE /v2/agent/{id}`,
`POST /v2/agent/{id}/stop` and the two executions reads. **No route transfers a live execution**,
and `stop` is not one: `v2/stop.md:10` — "This stops **ALL** the queued calls for a given agent."

So `VoiceEngine.transfer(call_id, to, warm)` — an out-of-band instruction to an execution in
flight — remains something this vendor does not offer, and `False` is right. What is left for
gate 18 is a design question (does a per-agent escalation number become engine config? who meters
and retains the transferred leg?), not a vendor one. The comment in `bolna.py` now says that.

### F-7 — `knowledge_base=False`: reported to Lane G, flag untouched

D-354's two facts, as the adapter states them: (a) `POST /knowledgebase` is multipart and takes a
PDF or a URL, never our `KBSourceRef.text`; (b) the created object carries no agent, so the link
is made on the agent's `vector_ids`. **My pages corroborate (b) and are silent on (a)** (the
knowledgebase routes are not in my page set):

- `v2/create.md:1302-1320`, `LanceDbConfig`: `vector_id` — "Vector id of a single knowledgebase
  (**legacy**, use `vector_ids` for multiple)"; `vector_ids` — "Array of vector ids to use
  multiple knowledgebases simultaneously".
- `v2/create.md:930-941`, `KnowledgebaseAgent` = `SimpleLlmAgent` + `vector_store`, selected by
  `LlmAgentV2.agent_type: knowledgebase_agent` (`v2/create.md:612-620`).
- `agent-setup/llm-tab.md:75-95`: a "Select knowledge bases" multi-select on the LLM tab.

**So the agent-side attachment is well documented and would be a two-line change to
`_agent_body`** (`agent_type: "knowledgebase_agent"` plus
`llm_config.vector_store = {"provider": "lancedb", "provider_config": {"vector_ids": [...]}}`).
The blocker is entirely on the *source* side — whether `KBSourceRef` can carry a PDF or a public
URL instead of prose — which is D-354's own framing and a KB-tier decision (T0–T4, TRD §6).
Lane G owns the flag; I have not touched it.

---

## 5. Agent read-back — the prompt is readable, the greeting is not

**The gate "VoiceEngine cannot read an agent back" is genuinely closed for the property the
drift sweep is built on.** `v2/get.md:88-95`, `AgentV2`:

```
        agent_prompts:
          $ref: '#/components/schemas/AgentPrompt'
          description: >-
            Prompts to be provided to the agent. It can have multiple tasks of
            the form `task_<task_id>`
```

and `AgentPrompt.task_1.system_prompt` is `required` within it (`v2/get.md:187-200`). So
`_agent_system_prompt` reads a real declared field, `carries_prompt_marker` works, and
`truthful_answer_applied` / `prompt_applied` are genuine measurements. `AgentV2.tasks` is a
`TasksConfigV2` array carrying `tools_config`, so `_agent_models` (transcriber, synthesizer,
`llm_agent.llm_config.model`, `llm_agent.llm_config.base_url`) is reading declared fields too —
which is what makes the D-410 residency read-back real rather than aspirational.

`AgentV2.id` (not `agent_id`) is what the response carries; `get_agent` and `list_agent_refs`
both already handle `id` first. Correct.

### F-4 — but `agent_welcome_message` is **not in `AgentV2`**

`v2/get.md:54-95` declares exactly nine properties: `id`, `agent_name`, `agent_type`,
`agent_status`, `created_at`, `updated_at`, `tasks`, `ingest_source_config`, `agent_prompts`.
`agent_welcome_message` is in none of them — nor is `webhook_url`, nor `calling_guardrails`.
(`v2/get_all.md` declares the identical `AgentV2`.)

**Consequence, stated plainly.** `_agent_greeting` returns `readable=False`, so
`_greeting_verdict` returns `None`, so `"greeting disclosure"` lands in `unread`, so
**every Bolna publish for an agent that volunteers any notice — which is every new agent, both
D-163 toggles start `true` — lands `unreadable`, never `applied`.** `live_verify_state` will
read `unreadable` across the fleet and `live_verified_at` will stay NULL.

That is the honest verdict, not a defect to code around: the adapter's own `_agent_greeting`
docstring already anticipated it ("an adapter that cannot find the field must not be able to fail
a publish on a compliance ground"), and the disclosure is still *recorded* in the prompt copy via
`prompt_disclosure_applied`. What it means operationally is that the one property with a legal
consequence is verified only in the weaker of its two places until a live account says otherwise.
`get_agent`'s docstring now says this in the file. Gate text proposed below.

Two readings remain open and only an account settles them: the schema is incomplete (likely — the
same spec's `Synthesizer.provider` enum omits `sarvam` while `agent-setup/audio-tab.md:117` and
the multilingual example both use it, so the enums are demonstrably not exhaustive), or the
greeting genuinely does not round-trip.

---

## 6. `engine-tab.md` / `call-tab.md` — which built-ins we duplicate

`_agent_body` sends exactly two `task_config` keys: `hangup_after_silence: 10` and
`call_terminate: cfg.max_call_duration_s`. Everything else in `ConversationConfig`
(`v2/create.md:399-607` — 25 keys) runs on the vendor's default.

| Built-in (default) | Do we rebuild it? | Verdict |
|---|---|---|
| `calling_guardrails` (`v2/create.md:213-231`), `auto_reschedule` (`:520-525`) | **Yes — deliberately.** `compliance/service.within_calling_hours` enforces TRAI's 09:00–21:00 IST at every dial; `campaigns/service` lets a campaign narrow it. | **Keep ours. F-8 — and the reason is now hard, see below.** |
| `voicemail` + 4 tuning keys (`:572-606`) | No. `CallStatus.voicemail` exists in our enum but the adapter already records that no `voicemail` status exists in the vendor's set, so it is unreachable from this engine. | Not a duplicate. Enabling it would *hang up* on voicemail, not report it. |
| `dtmf_enabled` (`:514-519`) | No — zero hits for DTMF/keypad in `apps/`. | Not a duplicate. |
| `noise_cancellation_level` (`:535-545`) | No — zero hits. | Not a duplicate. |
| `ambient_noise` / `ambient_noise_track` (`:467-483`) | No. Plivo/Vobiz only (`call-tab.md:85`). | Not a duplicate. |
| `inbound_limit`, `whitelist_phone_numbers`, `disallow_unknown_numbers` (`:491-513`; `inbound-tab.md:151-157`) | Partially — our DNC and consent gates are a different obligation (TRAI/DPDP), theirs is spam throttling. | Not a duplicate; different subjects. |
| `backchanneling` (`:442-466`), `welcome_message_delay` (`:526-534`), `incremental_delay` (`:418-427`), `number_of_words_for_interruption` (`:428-436`), transcriber `endpointing` | No. | Not duplicates. Their recommended values (`engine-tab.md:64`: endpointing 200–300 ms, linear delay 400–500 ms) match the schema defaults 250/400 — we inherit sane numbers. |
| `check_if_user_online` / `trigger_user_online_message_after` (`:560-571`) | No — and the default is **on**. | **F-6.** |

### F-8 — why configuring `calling_guardrails` would *break* a hard rule

`v2/patch_update.md:38`:

> "Restrict when your agent places outbound calls. **Calls triggered outside the allowed window
> are automatically rescheduled to the next allowed start time** in the **recipient's**
> timezone."

CLAUDE.md says to configure engine built-ins over rebuilding them, so this looks like the
textbook case for delegating. It is not, and the reason is worth recording rather than leaving as
an omission:

1. **An engine-side reschedule dials without re-entering our gate.** Hard rule 5: "DNC additions
   propagate before next dispatch tick." A dial the engine parks at 22:00 and places at 09:00 the
   next morning has not passed `check_dispatch` at the moment it is placed — no DNC re-read, no
   consent re-read, no spend cap, no big red switch. It is precisely the "bypass for testing"
   shape the rule forbids, arrived at by delegation instead of by code.
2. **Their window is validated in the recipient's timezone detected from the number**
   (`call-tab.md:149`); ours is IST by name (`compliance/service`, `agents/business_hours`). For
   `+91` those coincide, so the second window buys nothing and adds a second authority for one
   concept — the drift CLAUDE.md names as a defect even when both work.
3. **Our window is not a constant.** A campaign may narrow it (`campaigns/service`), so the
   correct per-agent value does not exist.

`auto_reschedule` fails on (1) for the same reason and stays `false`.

**Defence in depth is still available and is a founder decision, not an engineering one**: send
`calling_guardrails: {call_start_hour: 9, call_end_hour: 21}` *and* accept that a dial we
mistakenly authorise at 21:30 gets parked to 09:00 rather than refused. That trades a
loud failure for a silent 12-hour-late call to a lead who may have gone on DNC in between.
I did not send it. Proposed decision-log entry **D-419** (applied centrally 20 Aug 2026, merged with a sibling lane's `auto_reschedule`/`dtmf_enabled` finding).

### F-6 — the engine speaks a line we did not write, in a language we did not choose

`v2/create.md:560-571`:

> `check_if_user_online:` `type: boolean` **`default: true`** — "Check whether the user is still
> on the call when they go silent"
> `trigger_user_online_message_after:` `default: 10` — "Seconds of user silence after which the
> agent asks whether the user is still there."

`engine-tab.md:69-92` shows the console message field ("Hey, are you still there?", "with
multi-language support") and `engine-tab.md:92`: "Set the timer between **8-15 seconds**".

Three things follow:

1. **It is ON for every agent we publish**, because we do not send it and the default is `true`.
2. **The message itself has no documented API field.** `ConversationConfig` carries the boolean
   and the delay and nothing else. So on a Telugu clinic's line the engine may speak an English
   sentence nobody at Calevate wrote, and our read-back cannot see it — `AgentSnapshot` has no
   place for it.
3. **The threshold races ours.** We send `hangup_after_silence: 10`; the probe fires at 10 s too.
   `call-tab.md:128` recommends 6–10 s for hangup and `engine-tab.md:92` recommends 8–15 s for
   the probe, i.e. the vendor's own guidance has the probe firing *first*. At equal values the
   ordering is undefined in every page I read.

Not fixed, because both plausible fixes are product decisions with no vendor answer:
`check_if_user_online: false` (never speak an unwritten line, but hang up on a caller who is
thinking) or raise `hangup_after_silence` above the probe (a longer, costlier silence). Proposed
gate + decision-log entry below.

---

## 7. F-3 — the webhook allowlist holds one of three documented IPs. **P0, cross-lane.**

`packages/shared/src/calevate_shared/config.py:114`:

```python
DEFAULT_BOLNA_SOURCE_IPS: frozenset[str] = frozenset({"13.203.39.153"})
```

described in the comment above it as "Bolna's documented egress address (D-31, TRD §5)". The
vendor documents **three**, in four separate places inside my page set alone:

- `v2/create.md:196-199` (`AgentConfigV2.webhook_url`): "Bolna sends webhooks from source IPs
  `13.203.39.153`, `13.126.9.249` and `13.202.133.53` — **whitelist all three** on your server."
- `v2/update.md:114-117` — identical sentence.
- `v2/patch_update.md:25`: "Whitelist source IPs `13.203.39.153`, `13.126.9.249` and
  `13.202.133.53`."
- `v2/patch_update.md:262-267`: "**Whitelist source IPs `13.203.39.153`, `13.126.9.249` and
  `13.202.133.53`** on your server to ensure delivery."

The same three appear in `api-reference/executions/get_execution.md`, `api-reference/limits.md`,
`concepts/security.md`, `guides/post-call/polling-call-status-webhooks.md` and `quickstarts/api.md`
— pages belonging to other lanes, which is why this is reported rather than applied.

**Impact.** `apps/voice-runtime/engine_intake.verify_source` refuses deliveries from the other two
addresses, and `BolnaEngine.verify_webhook` returns the same verdict. Two-thirds of webhook
deliveries would be rejected. TRD §5's "poller as truth" means calls are still reconciled within
one 10-minute tick, so this degrades rather than breaks — but it converts a real-time path into a
polled one and fills the alerting channel with authenticity refusals for legitimate traffic.

**Exact diff (apply if no other lane has):**

```diff
--- a/packages/shared/src/calevate_shared/config.py
+++ b/packages/shared/src/calevate_shared/config.py
-# Bolna's documented egress address (D-31, TRD §5). THE only copy of this literal on any
+# Bolna's documented egress addresses (D-31, TRD §5). ALL THREE — this held one, and the
+# vendor documents three, saying "whitelist all three on your server" on the very field
+# our adapter sends (`AgentConfigV2.webhook_url`). VERIFIED-VENDOR-DOCS:
+# `bolna-findings/mirror/pages/api-reference/agent/v2/create.md:196-199`, repeated at
+# `v2/update.md:114-117` and twice in `v2/patch_update.md` (:25, :262-267). Two of every
+# three deliveries were refused by `engine_intake.verify_source`; the executions poller
+# covered the loss (TRD §5, "poller as truth"), which is exactly why nobody saw it.
+# THE only copy of this literal on any
 # runtime path — `Settings.bolna_webhook_source_ips` defaults to it, and both the
 # receiver (`apps/voice-runtime/engine_intake.py`) and the adapter
 # (`apps/api/engine/bolna.py`) resolve their effective allowlist through
 # `bolna_source_ips()` below. `scripts/pilot/gates_api.DOCUMENTED_EGRESS_IP` restates it
 # ON PURPOSE and argues why: a gate that imported the value it tests would be asking the
 # code whether it agrees with itself.
-DEFAULT_BOLNA_SOURCE_IPS: frozenset[str] = frozenset({"13.203.39.153"})
+DEFAULT_BOLNA_SOURCE_IPS: frozenset[str] = frozenset(
+    {"13.203.39.153", "13.126.9.249", "13.202.133.53"}
+)
```

`scripts/pilot/gates_api.DOCUMENTED_EGRESS_IP` should become `DOCUMENTED_EGRESS_IPS: tuple[str, ...]`
and gate 1 should assert every one of the three is accepted — it currently probes one. The module
docstring of `apps/api/engine/bolna.py` also says "a SINGLE documented address, `13.203.39.153`"
and needs the same correction. I have touched none of these: three of the four files are outside
my lane and `config.py` is shared infrastructure another lane is editing this wave.

---

## 8. F-5 — `toolchain.execution`: `parallel` vs `sequential`. Reported, not guessed.

`_agent_body` sends `{"execution": "parallel", "pipelines": [["transcriber","llm","synthesizer"]]}`,
sourced VERIFIED-OSS from their own builder. The vendor's hosted doc example uses the other value.
`v2/create.md:18-19`, heading the body it calls **"The smallest body that produces a working
English conversation agent"**:

```json
      "toolchain": {
        "execution": "sequential",
        "pipelines": [["transcriber", "llm", "synthesizer"]]
      },
```

and the OpenAPI example at `v2/create.md:373-377` also renders `sequential`.

`Toolchain.execution` enumerates both (`v2/create.md:372-376`: `enum: [parallel, sequential]`), so
neither is invalid, and for a single pipeline the two may well be identical. But this repo's own
evidence ladder puts VERIFIED-VENDOR-DOCS above VERIFIED-OSS on the hosted contract, and the
hosted doc says `sequential` twice. **Not changed**: switching the execution mode of every agent
on the strength of an example, with no way to observe the difference, is a guess in the other
direction. `tests/bolna_contract_test.py::test_the_toolchain_and_prompt_envelope_match_the_spec`
currently pins `parallel`; whichever way this resolves, that test moves with it. Gate text below.

---

## 9. Incidental confirmations worth keeping

- **Azure is a first-class LLM provider on the hosted platform, first-party.** CLAUDE.md's D-410
  note rests partly on "their published provider list, the live agent dropdown". Now in writing:
  `llm-tab.md:7` — "Choose from OpenAI, **Azure**, Anthropic, and connect knowledge bases";
  `llm-tab.md:31` — "Choose from **Azure**, OpenAI, Anthropic, Groq, and more"; `llm-tab.md:26`
  image alt — "Choose LLM model with **Azure** provider and gpt-4.1-mini cluster selected". And
  structurally, five `SimpleLlmAgent` fields say "Accepted for backwards compatibility. **Not
  sent to OpenAI or Azure models.**" (`v2/create.md:883-891, 892-897, 902-911, 912-917, 918-923`)
  — the platform's own request builder branches on Azure.
- **`SimpleLlmAgent.base_url`** is a declared field with `default: https://api.openai.com/v1`
  (`v2/create.md:898-901`), i.e. pointing an agent at an arbitrary OpenAI-compatible endpoint is
  the designed extension point. That is the premise `_llm_routing` and the D-410 residency
  read-back stand on, and it now has a hosted-doc citation rather than an OSS one.
- **`max_tokens` / `temperature` defaults confirmed on the hosted contract**: `default: 100` and
  `default: 0.1` (`v2/create.md:817-825` and `:826-838`), matching what D-283 read in the OSS models and sends
  explicitly. Our 400/0.1 stands unchanged.
- **`agent_status: seeding | processed`** (`v2/get.md:66-73`) is a read-back field we do not use.
  A publish that read back `seeding` would be an agent the platform has not finished building —
  which is a candidate cause of a future `not_applied` verdict and worth knowing exists.
- **`agent-setup/overview.md:142`**: "**Remember to save!** Your changes won't apply until you
  click **Save agent**." Console edits are not live until saved — relevant to any incident where
  an operator "fixed it in the dashboard".

---

## Proposed text for the central files (I did not edit ROADMAP.md or OPERATIONS.md)

### docs/ROADMAP.md — decision log

> **D-418 — Bolna agents are published single-language, and multilingual is a composer change
> rather than a toggle.** `MultilingualConfig` keeps a `system_prompt` per language and the
> platform "switches them, along with the active system prompt, during the call"
> (`bolna-findings/mirror/pages/api-reference/agent/v2/create.md`). `compose_engine_prompt` puts
> `TRUTHFUL_ANSWER_DIRECTIVE` in `agent_prompts.task_1.system_prompt` and `verification.judge`
> reads it back from there, so an agent switched to multilingual would run a per-language prompt
> carrying none of hard rule 5's floor while the read-back scored it applied — a config row
> withdrawing the directive, invisible to every instrument we have. `_agent_body` therefore sends
> `multilingual_config: null` on every publish (the vendor's own default and an explicitly
> nullable key), so a console-enabled multilingual config is cleared rather than inherited.
> WHAT CLOSES IT: a composer that renders one prompt per language, each carrying the directive
> **in that language**, and a judge that reads every one of them back. That needs the directive
> translated and reviewed (it is English prose today) and `AgentSnapshot` to carry per-language
> prompts. Until then a Telugu-first agent speaks Telugu because its script and its voice are
> Telugu, not because the engine switches languages mid-call.

> **D-419 — Calling-hours enforcement stays ours; Bolna's `calling_guardrails` is deliberately
> unset.** Their built-in reschedules an out-of-window dial to the next allowed start in the
> recipient's timezone. A dial parked at 22:00 and placed at 09:00 has not passed
> `compliance.check_dispatch` at the moment it is placed — no DNC re-read, no consent re-read, no
> spend cap, no big red switch — which is the bypass hard rule 5 forbids, arrived at by
> delegation rather than by code. Our window is also not a constant (a campaign may narrow it),
> so no single per-agent value is correct. `auto_reschedule` stays `false` for the same reason.
> This is the documented exception to CLAUDE.md's "configure engine built-ins over rebuilding
> them": the built-in cannot run the compliance gate. WHAT WOULD REVERSE IT: nothing the vendor
> can ship — it would take our gate becoming reachable from their scheduler.

### docs/OPERATIONS.md — §2 gate table

> **Gate 2 (extend) — agent read-back completeness.** In addition to the existing sub-checks,
> record for one published agent: (a) does `GET /v2/agent/{id}` return `agent_welcome_message`
> under any key? `AgentV2` does not declare it, so `_agent_greeting` answers `readable=False` and
> **every publish lands `unreadable` rather than `applied`** — the property with the legal
> consequence is verified only in the weaker of its two places. If the live response carries it,
> `_agent_greeting` already finds it and the gate closes with no code change. If it does not,
> record which key holds the greeting, or record that it does not round-trip. (b) does the
> response echo `multilingual_config` and `llm_agent.routes`? Both are config surfaces that can
> change what the agent says without touching `agent_prompts` (see
> `docs/evidence/bolna-agent-lifecycle.md` F-1/F-2). (c) does `PUT /v2/agent/{id}` really replace
> the whole configuration — set `calling_guardrails` via `PATCH`, then `PUT` a body that omits
> it, and re-read.

> **Gate 24 (new; applied as 24 — three lanes proposed a "21") — `toolchain.execution`.** We send `parallel` (VERIFIED-OSS, their own
> builder); the hosted doc's "smallest body that produces a working English conversation agent"
> sends `sequential`, twice. Both are in the enum. Create one agent each way, place a test call on
> each, and record whether first-audio latency or turn behaviour differs. Whichever wins, the
> value and `tests/bolna_contract_test.py::test_the_toolchain_and_prompt_envelope_match_the_spec`
> move together.

> **Gate 23 (new; applied as 23) — the silence probe we did not configure.** `check_if_user_online` defaults
> **true** and `trigger_user_online_message_after` defaults **10 s**, and we send
> `hangup_after_silence: 10`. On a test call, go silent and record: (a) does the agent speak a
> probe before hanging up, and at what second? (b) **what language does it speak it in on a
> Telugu agent, and what exactly does it say?** (c) is the probe message settable anywhere in the
> API, or console-only? Until (b) is answered, every Calevate agent may be speaking a sentence
> nobody here wrote. The decision that follows — `check_if_user_online: false`, or a longer
> `hangup_after_silence` — is a founder call, not an engineering one.

> **Gate 1 (correct) — webhook egress.** The vendor documents **three** source IPs
> (`13.203.39.153`, `13.126.9.249`, `13.202.133.53`) and instructs "whitelist all three".
> `DEFAULT_BOLNA_SOURCE_IPS` holds one and `DOCUMENTED_EGRESS_IP` probes one. See
> `docs/evidence/bolna-agent-lifecycle.md` F-3 for the diff. The gate should assert all three are
> accepted and that a fourth address is refused.

---

## Changes made, file by file, with red-then-green evidence

### `apps/api/engine/bolna.py` — `_agent_body`: `"multilingual_config": None` (behavioural)

Plus a comment block giving the vendor quote, why the floor is at stake, why explicit null rather
than omission, and why `routes` is deliberately **not** given the same treatment.

**GREEN (before sabotage):**

```
$ uv run pytest tests/bolna_contract_test.py -q -p no:randomly \
    -k "single_language or toolchain or telephony_input or v2_nesting"
.....                                                                    [100%]
5 passed, 15 deselected, 1 warning in 0.23s
```

**RED (key replaced by a comment):**

```
$ uv run pytest tests/bolna_contract_test.py -q -p no:randomly -k "single_language"
        tools = (await _created_body())["agent_config"]["tasks"][0]["tools_config"]

>       assert "multilingual_config" in tools, (
            "an omitted key leaves the vendor's stored value alone; the floor is not a thing "
            "to rest on unobserved PUT merge semantics"
        )
E       AssertionError: an omitted key leaves the vendor's stored value alone; the floor is not
        a thing to rest on unobserved PUT merge semantics
E       assert 'multilingual_config' in {'llm_agent': {...}, 'input': {...}, ...}

tests/bolna_contract_test.py:201: AssertionError
=========================== short test summary info ============================
FAILED tests/bolna_contract_test.py::test_every_publish_states_the_agent_is_single_language
1 failed, 19 deselected, 1 warning in 0.26s
```

**GREEN (restored):**

```
$ uv run pytest tests/bolna_contract_test.py -q -p no:randomly -k "single_language"
1 passed, 19 deselected, 1 warning in 0.23s
```

### `apps/api/engine/bolna.py` — `get_agent` docstring (documentation)

Two statements in it were false and one contradicted this file's own module docstring: "NOT READ,
ONLY REPORTED … the page ITSELF could not be fetched" and "Bolna publishes no OpenAPI spec (module
docstring)" — which D-350 rewrote to say the opposite. Both halves are now first-hand from the
mirror, and the bullet now states what `AgentV2` does and does not declare, and what follows for
the verdict (F-4). Documentation only; no behaviour changed.

### `apps/api/engine/bolna.py` — `BOLNA_CAPABILITIES` `transfer=False` comment (documentation)

Evidence class raised from VERIFIED-OSS to VERIFIED-VENDOR-DOCS and gate 18's *vendor* question
answered in both halves (§4 above). The flag value is unchanged and correct.

### `tests/bolna_contract_test.py` — one new clause

`test_every_publish_states_the_agent_is_single_language`. Asserts the key is present **and** null
— present, because an absent key is a field left as it was, which is the whole point.

### Regression run

```
$ uv run pytest tests/bolna_contract_test.py tests/bolna_snapshot_test.py \
    packages/shared/tests/engine_conformance -q -p no:randomly
261 passed, 1 warning in 2.14s

$ uv run ruff check apps/api/engine/bolna.py tests/bolna_contract_test.py
All checks passed!
$ uv run ruff format --check apps/api/engine/bolna.py tests/bolna_contract_test.py
2 files already formatted
$ uv run mypy apps packages
Success: no issues found in 238 source files
```

Both adapters still pass the conformance suite. `make coverage-ratchet` and the full suite were
deliberately **not** run (ten agents, four vCPU — a contention failure is not a signal).

---

## Deliberately left alone

- **`toolchain.execution`** — see F-5. Two valid enum values, one OSS source and one hosted-doc
  example disagreeing, no way to observe the difference here. Gate 24.
- **`LlmAgentV2.routes`** — see F-2. Not nullable, no default; a `null` or `[]` would be a guess
  that could 400 every publish.
- **`calling_guardrails` / `auto_reschedule`** — see F-8/D-419. Configuring them would move a dial
  outside the compliance gate.
- **`check_if_user_online`** — see F-6. Both plausible values are product decisions.
- **`BOLNA_CAPABILITIES.knowledge_base`** — Lane G's, as instructed. Reported in §4.
- **`packages/shared/src/calevate_shared/config.py` (F-3)** — the webhook allowlist is not this
  lane's, the same IPs appear on three other lanes' pages, and the fix spans four files including
  a pilot gate and its test. Exact diff supplied.
- **`packages/shared/src/calevate_shared/engine.py`** — Lane B's this wave. F-2's `AgentSnapshot`
  diff is written out above.
- **`_agent_greeting`'s two-place lookup, `_agent_system_prompt`'s `task_1` preference,
  `_agent_models`' dual v1/v2 spelling, `agents/service.py::in_call_llm`** — all read correctly
  against the mirrored schemas. No change needed.

## Needs a founder decision

1. **F-6 / Gate 23** — what an agent says when a caller goes quiet. Today it is the vendor's
   default probe, at 10 s, in a language nobody here chose, on a Telugu-first product, with no
   API field for the text.
2. **F-8 / D-419** — whether to send `calling_guardrails` as belt-and-braces knowing an
   out-of-window dial is *parked for twelve hours* rather than refused, and could be placed to a
   lead who went on DNC in between.
3. **F-1's successor** — whether this product ever wants engine-side multilingual agents. If yes,
   the truthful-answer directive needs a reviewed Telugu (and Hindi) rendering before any of it
   is built; that is a legal-review item, not an engineering one.
4. **F-7** — whether `KBSourceRef` grows a PDF/URL form so Bolna's knowledge base becomes usable.
   The agent-side attachment is two lines; the source side is a KB-tier decision. Lane G's call.
