# Cartesia — the agents control plane

Primary source: `cartesia-ai/cartesia-python`, `api.md` (the generated reference) and
`src/cartesia/resources/agents/agents.py`. Cross-checked against
`cartesia-ai/cartesia-js`, `src/resources/agents/agents.ts`. Both are generated from
Cartesia's OpenAPI spec — the file headers say so verbatim: *"File generated from our
OpenAPI spec by Stainless."*

## Every agent operation the official clients expose

| Method | Path | Returns | Source |
|---|---|---|---|
| GET | `/agents/{agent_id}` | `AgentSummary` | `api.md`, `resources/agents/agents.py` |
| PATCH | `/agents/{agent_id}` | `AgentSummary` | `api.md`, `resources/agents/agents.py:157` |
| GET | `/agents` | `AgentListResponse` = `{"summaries": [AgentSummary]}` | `api.md`, `agents.py:~185`, `types/agent_list_response.py` |
| DELETE | `/agents/{agent_id}` | *(no body)* | `api.md`, `agents.py:~215` |
| GET | `/agents/{agent_id}/phone-numbers` | `AgentListPhoneNumbersResponse` | `api.md` |
| GET | `/agents/templates` | `AgentListTemplatesResponse` | `api.md` |
| GET | `/agents/{agent_id}/deployments` | `DeploymentListResponse` | `api.md` |
| GET | `/agents/deployments/{deployment_id}` | `Deployment` | `api.md` |
| POST | `/agents/metrics`, GET `/agents/metrics/{id}`, GET `/agents/metrics`, POST/DELETE `/agents/{agent_id}/metrics/{metric_id}`, GET `/agents/metrics/results`, GET `/agents/metrics/results/export` | LLM-as-a-judge evaluation metrics | `api.md` |

### There is no `POST /agents`

**VERIFIED-SDK, and this is the load-bearing negative.** A Stainless client emits one
method per operation in the spec; `AgentsResource` has `retrieve`, `update`, `list`,
`delete`, `list_phone_numbers`, `list_templates` and no `create`. `cartesia-js` matches.

Corroborated by how agents are actually made — **REPORTED-DOCS + VERIFIED-SDK
(`cartesia-ai/skills`, `skills/line-voice-agent/SKILL.md:60-86`)**:

```
cartesia create [project-name]   # Create project from template
cartesia init                    # Link existing directory to an agent
cartesia deploy                  # Deploy to Cartesia cloud
cartesia agents ls               # List all agents
cartesia call <phone> [agent-id] # Make outbound call
```

and by `AgentSummary` carrying `git_repository` and `git_deploy_branch`: the agent's
identity is a repository, and its behaviour is the code in it.

## `AgentSummary` — the whole agent object

`cartesia-python/src/cartesia/types/agent_summary.py` (VERIFIED-SDK):

| Field | Type | Note |
|---|---|---|
| `id` | str | |
| `name` | str | "The unique name of the agent, which can be used to identify the agent in the CLI." |
| `created_at`, `updated_at` | datetime | |
| `deleted_at` | datetime? | soft-delete is visible |
| `description` | str? | |
| `deployment_count` | int | |
| `has_text_to_agent_run` | bool | |
| `tts_language` | str | |
| `tts_voice` | str | |
| `git_repository` | `{account, name, provider}`? | |
| `git_deploy_branch` | str? | |
| `phone_numbers` | `[{id, number}]`? | *"Currently, you can only have one phone number per agent."* |
| `webhook_id` | str? | *"Add or customize a webhook to your agent to receive events when calls are made to your agent via the Playground."* |

**What is absent, and it is the whole story**: no `system_prompt`, no `introduction`, no
`model`, no `documents`. The prompt and the greeting live in the deployed program —
`line/voice_agent_app.py:88-96` defines the per-call `AgentConfig(id, system_prompt,
introduction)` that Cartesia's harness *delivers to* the agent, and
`cartesia-ai/skills/.../calls-api.md:56-73` shows a caller supplying
`agent: {system_prompt, introduction}` on the `start` event of a single call. On this
platform the prompt is **per-call data or deployed code, never agent-record state.**

## `PATCH /agents/{agent_id}` accepts exactly four fields

`cartesia-python/src/cartesia/types/agent_update_params.py` (VERIFIED-SDK):

```python
class AgentUpdateParams(TypedDict, total=False):
    description: Optional[str]
    name: Optional[str]
    tts_language: Optional[str]
    tts_voice: Optional[str]
```

So of the six keys our `_agent_body` used to send — `name`, `system_prompt`,
`introduction`, `language`, `model`, `webhook_url` — exactly one (`name`) is accepted
under the name we sent it, one (`language`) is accepted under a different name
(`tts_language`), and four are not accepted at all.

`tts_voice` being writable does **not** make TTS ours: the value is a Cartesia voice id
addressing Sonic, and nothing in D-36's Bulbul catalogue names one. `stt`/`tts` stay
`"engine"` in `CARTESIA_CAPABILITIES` (see `line/_harness_types.py:132-139`, where
`TTSConfig(voice_id, pronunciation_dict_id, language)` and `STTConfig(language)` carry no
provider field at all).

## Consequences for `VoiceEngine`

* `create_agent` — **contradicted**. No endpoint. Since D-281 it REFUSES by name
  (`engine_lacks("agent_hosting")`) rather than POSTing; OPERATIONS §2 gate 19(a) is now
  the confirmation that it really 404s, not the work.
* `update_agent` — path and verb **confirmed**; the body is four fields, and the prompt
  is not among them. Our compliance prompt cannot reach a Cartesia agent this way, so it
  refuses too: its only caller is a publish whose `create_agent` already refused, and
  leaving it live would make it reachable only by an adoption path that does not exist.
* `get_agent` — path **confirmed**; `system_prompt`, `greeting` and `model` can never be
  read back. It refuses rather than answering `readable=False` for ever: the
  `AgentSnapshot._readable` tri-state means *the adapter could not FIND the field*, which
  is a reason to go and look at the adapter, and there is nothing here to find.
* **Where the prompt goes instead** — nowhere, on this adapter, today. The port's answer
  for this shape is `CallContext.system_prompt` riding the dial; `POST /agents/calls`
  (REPORTED-DOCS) has no field for one, and the per-call `agent: {system_prompt,
  introduction}` read at source belongs to the WebSocket Calls API. So the adapter refuses
  every dial rather than placing a call with no truthful-answer rule on it (D-282), and
  gate 19(b) is the observation that changes it.
* `llm` speech control — **`ours` → `engine`** (D-281). The vendor runs Sarvam through
  LiteLLM inside the DEPLOYED PROGRAM; `AgentSummary` has no `model` and
  `AgentUpdateParams` is four fields none of which is one, so no `ModelConfig` value can
  reach this engine through this port. Same argument as `transfer=False`.
* `delete_agent` — path and verb **confirmed** (previously marked "no public
  documentation found"). What a repeat delete answers is still unverified.
* `provision_number` — `GET /agents/{id}/phone-numbers` exists, so numbers are attached
  to agents; nothing sourced sells an Indian DLT 140/160 number, and whether Line accepts
  BYOC SIP from an Indian carrier remains THE question (`docs/evidence/cartesia-byoc-question.md`).
