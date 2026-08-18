# VERIFIED-OSS — facts read at source in `bolna-ai/bolna`

**Source:** https://github.com/bolna-ai/bolna
**Pinned commit:** `cd2e192600ae94daeeb627d26c604b69cfc50de4` (branch `master`), cloned and
read in full on 2026-08-18. 185 Python files.

**Standing caveat, applies to every row below.** This is the open-source **self-hosted
framework**. The hosted platform (`api.bolna.ai`) is built on it but is a different
deployment with a different REST surface. Everything here is authoritative about how the
engine BEHAVES and about the SHAPES its config models accept. Nothing here proves a hosted
route, status code or field name. See `README.md` for why that distinction is load-bearing.

---

## 1. Agent config — the object we POST

Read in `bolna/models.py`, `API.md`, `bolna/assistant.py`.

### `Task` requires `toolchain`, and the runtime dereferences it unguarded

```python
class Task(BaseModel):
    tools_config: ToolsConfig
    toolchain: ToolsChainModel  # no default
    task_type: Optional[str] = "conversation"
    task_config: ConversationConfig = dict()


class ToolsChainModel(BaseModel):
    execution: str = Field(..., pattern="^(parallel|sequential)$")
    pipelines: List[List[str]]
```

Consumed with bare subscripts in two places — a `KeyError`, not a defaulted field:

- `bolna/agent_manager/task_manager.py`: `self.pipelines = task["toolchain"]["pipelines"]`
- `bolna/helpers/utils.py::get_required_input_types`:
  `for i, chain in enumerate(task["toolchain"]["pipelines"])` — and this is the function
  that decides whether the task consumes **audio** or **text**, from `chain[0]`.

The canonical value for a voice conversation task, from their own builder
(`bolna/assistant.py`) and their `API.md` example:

```json
{"execution": "parallel", "pipelines": [["transcriber", "llm", "synthesizer"]]}
```

**Our adapter was not sending it.** Fixed — D-260.

### `llm_agent`: our flat shape is valid, but `family` is not the selector

`ToolsConfig.llm_agent` is `Optional[Union[LlmAgent, SimpleLlmAgent]]`. `LlmAgent` requires
`agent_type` **and** `llm_config`; our flat block supplies neither, so it binds to
`SimpleLlmAgent` — the legacy shape — and **validates**. That much is fine.

What is not fine: `Llm` declares **both** `family` (default `"openai"`) and `provider`
(default `"openai"`), and the client is chosen by **`provider`**:

```python
# bolna/agent_manager/task_manager.py::__setup_llm
if llm_config["provider"] in SUPPORTED_LLM_PROVIDERS.keys():
    llm_class = SUPPORTED_LLM_PROVIDERS.get(llm_config["provider"])
```

`family` is **read by nothing in the engine.** (The `model_family` properties in
`bolna/llms/*.py` are an unrelated computed thing about GPT-5 model-name prefixes.)

The config assembly is also all bare subscripts, on the no-`agent_type` branch our body takes:

```python
self.llm_config = {
    "model": self.llm_agent_config["model"],
    "max_tokens": self.llm_agent_config["max_tokens"],  # we do not send
    "provider": self.llm_agent_config["provider"],  # we do not send
    "temperature": self.llm_agent_config["temperature"],  # we do not send
}
```

Those three survive only because the OSS server stores `agent_config.model_dump()`, which
fills the Pydantic defaults. Consequence: an agent configured our way runs at
`provider="openai"`, `max_tokens=100`, `temperature=0.1` **whatever `model` says.**

`LLMProvider` (`bolna/enums.py`) has **no `sarvam` member** — openai, cohere, ollama,
deepinfra, together, fireworks, azure-openai, perplexity, vllm, anyscale, custom, ola,
groq, anthropic, deepseek, openrouter, azure, google. So D-36's Sarvam 105B leg has no
obvious value here, which is why nothing was guessed. **OPERATIONS §2 gate 16.**

### Sarvam is first-class on the speech legs

`bolna/enums.py` + `bolna/providers.py`: `SynthesizerProvider.SARVAM` → `SarvamSynthesizer`,
`TranscriberProvider.SARVAM` → `SarvamTranscriber`. Confirms the BYOK STT/TTS claim in
`BOLNA_CAPABILITIES`. **Not** confirmed on the LLM leg — see above.

### Telephony providers include Exotel and Vobiz

`TelephonyProvider`: twilio, exotel, plivo, vobiz, sip-trunk, freeswitch, default,
database. Consistent with D-05's Exotel/Vobiz pick.

### `ConversationConfig` — the two knobs we send are real

`hangup_after_silence` (default 20) and `call_terminate` (default 90) both exist. Also
present and unset by us: `voicemail` detection, `backchanneling`, `ambient_noise`,
`dtmf_enabled`, `number_of_words_for_interruption`, `optimize_latency`.

---

## 2. Agent lifecycle — reading an agent back

Read in `local_setup/quickstart_server.py`, `API.md`.

- `POST /agent` → `{"agent_id": "<uuid>", "state": "created"}`
- `PUT /agent/{id}` → `{"agent_id": ..., "state": "updated"}`
- `DELETE /agent/{id}` → `{"agent_id": ..., "state": "deleted"}`
- `GET /all` → `{"agents": [{"agent_id": ..., "data": {...}}]}` — the envelope our
  `_AGENT_ENVELOPE_KEYS` tolerates.

**`GET /agent/{id}` returns `agent_config.model_dump()` — the STORED AGENT OBJECT with no
`agent_config` wrapper.** So `agent_name`, `agent_welcome_message` and **`tasks`** all come
back at the ROOT. `_agent_name` and `_agent_greeting` already fell back to the root;
`_agent_models` did not, and reported `models_readable=False` for a readable agent. Fixed
— D-260.

**`agent_prompts` is NOT in the GET response.** The server stores prompts separately
(`store_file(f"{agent_uuid}/conversation_details.json")`). On this server
`_agent_system_prompt` would honestly return `None` → `system_prompt_readable=False`.
Whether the hosted GET echoes prompts is exactly what OPERATIONS §2 gate 2 measures.

### The 404-that-is-a-500 — why VERIFIED-OSS is not proof of hosted

```python
@app.delete("/agent/{agent_id}")
async def delete_agent(agent_id: str):
    try:
        agent_exists = await redis_client.exists(agent_id)
        if not agent_exists:
            raise HTTPException(status_code=404, detail="Agent not found")
        ...
    except Exception as e:  # HTTPException IS an Exception
        raise HTTPException(status_code=500, detail="Internal server error")
```

The **intent** is 404 for an absent agent — which supports our `absent_is_success` reading.
The **behaviour** is 500, because the 404 raise is swallowed by the broad handler.
`get_agent` has the identical defect. This is the cleanest example in the harvest of a
source that tells you the semantics and shows the implementation missing them. It upgrades
`delete_agent`'s marked assumption from *guessed* to *OSS-backed intent*; it does not close
it. **OPERATIONS §2 gate 2** (`delete_agent` sub-check).

---

## 3. Transcript construction — `format_messages`

`bolna/helpers/utils.py::format_messages` is the function that builds the prefix-tagged
transcript string. It emits, one per line:

| Prefix | Emitted when |
|---|---|
| `assistant: ` | always, for assistant turns |
| `user: ` | always, for user turns |
| `system: ` | `use_system_prompt=True` |
| `assistant_tool_call: ` | `include_tools=True` — value is `str(tool_call)`, i.e. **function name and arguments** |
| `tool_response: (<tool_call_id>): ` | `include_tools=True` |

Confirms our `assistant:`/`user:` parse. **Also revealed a live defect**: none of the last
three matches `_TURN_RE` (`assistant_tool_call` is not `assistant` + colon), so each fell
into the parser's *continuation* branch and was **appended to the previous speaker's
turn** — splicing serialized tool-call arguments and the system prompt into the text the
transcript attributed to the agent. Extraction reads that text. Fixed — D-260.

`agent:`, `bot:`, `human:` in our `_SPEAKER_MAP` appear **nowhere** in this emitter. They
are tolerated spellings, not observed ones.

---

## 4. Cost — the unit question

`bolna/helpers/analytics_helpers.py::calculate_total_cost_of_llm_from_transcript`:

```python
total_cost = (total_input_tokens * cost_per_input_token) + (
    total_output_tokens * cost_per_output_token
)
return round(total_cost, 5), llm_token_usage
```

Per-token rates are **dollars**, and the result is a major-unit figure carried to five
decimals. `run_details["cost_breakdown"]` is read with keys `transcriber`, `synthesizer`,
`llm` (`analytics_helpers.py`) — three of the five keys our adapter reads.

**This argues against our `USD cents` reading and does not settle it**: the hosted billing
figure is not this function (it adds telephony and the platform fee and is computed by a
service not in this repo). The adapter's `/100` is therefore **unchanged**, and promoted
from a bare literal to a named, documented constant with the counter-evidence attached —
`_ASSUMED_MINOR_UNITS_PER_MAJOR`. **OPERATIONS §2 gate 7.**

---

## 5. Transfer — a built-in, but not the shape our Protocol names

`bolna/agent_manager/task_manager.py` implements `transfer_call` as a **function the LLM
invokes mid-conversation**:

- dispatched on `called_fun.startswith("transfer_call")`;
- latched by `self.has_transfer` so a re-firing LLM cannot transfer twice (their comment
  records the bug that caused: the model kept re-emitting the tool and looped until the
  call dropped);
- destination comes from **config** — `transfer_call_params`, and the tool's
  `call_transfer_number` — not from the model;
- optional `pre_call_webhook_url` fires before the handoff;
- emits a `transfer_start` event; `bolna/constants.py` carries the spoken filler
  (`"Sure, I'll transfer the call for you. Please wait a moment..."`).

**This is a different shape from `VoiceEngine.transfer(call_id, to, warm)`**, which is an
out-of-band instruction to an execution already in flight. Nothing sourced exposes that
over REST. So `BOLNA_CAPABILITIES.transfer=False` stays correct — and its *reason* changes
from "nobody checked" to "the built-in is an in-call tool configured at publish time".
**OPERATIONS §2 gate 18.**

---

## 6. Status values — what the OSS repo does NOT contain

`bolna/enums.py` has **no call-status enum**. Its enums are `ChatRole`, `TelephonyProvider`,
`SynthesizerProvider`, `TranscriberProvider`, `LLMProvider`, `ReasoningEffort`, `Verbosity`,
`ResponseStreamEvent`, `ResponseItemType`, `HangupReason`, `LogComponent`, `LogDirection`,
`ExpressionOperator`, `ExpressionLogic`, `VariableType`, `EdgeConditionType`, `NodeType`,
`ToolScope`, `UsageSource`.

So the adapter's claim of "their 15-value status enum" had **no source at all**, in this
repo or anywhere. Corrected in the code comment — D-260.

`HangupReason` is documented in-source as *"Enum for `hangup_detail` values"*, which names a
hosted field: `llm_prompted_hangup`, `voicemail_detected`, `web_call_max_duration_reached`,
`inactivity_timeout`, `transcriber_error`, `transcriber_connection_error`,
`synthesizer_error`, `llm_error`, `end_call_tool`.

Note `voicemail_detected` is a **hangup reason**, not a status — see `hosted-reported.md`
on `answered_by_voice_mail`, and OPERATIONS §2 gate 17.
