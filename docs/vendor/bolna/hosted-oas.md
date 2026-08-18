# Bolna's hosted OpenAPI specification — the document this repo said did not exist

**Class: VERIFIED-OAS.** First-party, versioned, machine-checkable, and about the HOSTED
platform rather than the self-hosted framework. It outranks every other class in this
directory, including `VERIFIED-OSS`.

## What was found, and why it matters more than any single fix

Until D-350, thirty-one places across this repository asserted that **"Bolna publishes no
OpenAPI spec"**. That sentence was the stated justification for:

- the executions listing's page-size truncation heuristic (`_LISTING_PAGE_SIZES`);
- the refusal to send a pagination parameter (`_next_link`'s "we invent no name");
- the hand-maintained call-status list and its "the count was a fiction" note;
- the marked assumption on the money unit (`_ASSUMED_MINOR_UNITS_PER_MAJOR`);
- the guessed knowledge-base request body;
- the agent read-back's field-name guesswork;
- several OPERATIONS §2 pilot gates whose only job was to learn a documented fact.

It was false. Bolna publishes a full OpenAPI 3.1.0 document.

## Where it is, and how to re-fetch it

| | |
|---|---|
| Repository | `github.com/bolna-ai/skills` — **Bolna's own GitHub organisation** |
| Path | `references/openapi.yml` |
| Pinned commit | `28b24aa504389ec69584301ea32545946e256409` (2026-05-27) |
| `md5sum` of the file at that commit | `5597f7da080d47564696bc05c12e9112` |
| Size | 5977 lines, `openapi: 3.1.0`, `info.title: Bolna API`, `info.version: 1.0.0` |
| Declared server | `https://api.bolna.ai` (exactly one) |
| Security | `bearerAuth` |

```bash
curl -sS -o openapi.yml \
  https://raw.githubusercontent.com/bolna-ai/skills/28b24aa504389ec69584301ea32545946e256409/references/openapi.yml
md5sum openapi.yml   # 5597f7da080d47564696bc05c12e9112
```

The repo's own `references/bolna-core.md` states its provenance and its standing:

> **OpenAPI spec** — Pinned in `references/openapi.yml` (mirror of
> `https://www.bolna.ai/docs/api-reference/openapi.yml`). Treat the YAML as the canonical
> schema if a SKILL.md and the spec disagree.

That last clause is why this file, and not the SKILL.md prose, is the top of the evidence
ladder — and why `VERIFIED-VENDOR-REPO` (the prose files) is a separate, lower class.

## Why it was missed for so long, and the lesson that generalises

The block is real and is still in force: `docs.bolna.ai`, `www.bolna.ai`, `docs.bolna.dev`
and `api.bolna.ai` are all refused by this environment's egress proxy with a gateway 403 on
CONNECT, for `curl` and for `WebFetch` alike. Every earlier attempt to read the vendor's
documentation went at a `bolna.ai` host, was refused, and the refusal was correctly recorded
as "no hosted documentation page in this repository has been read by anyone here".

What nobody did was ask whether the documentation existed **somewhere reachable**.
`github.com` and `raw.githubusercontent.com` are not blocked — the OSS harvest in
`oss-harvest.md` is a full clone read at source, which proves it — and the vendor publishes
its API contract on GitHub. One code search for `"api.bolna.ai/v2/agent"` surfaced
`bolna-ai/skills` in seconds.

**The generalisable lesson: "the vendor's docs host is blocked" is a statement about a
HOST, and it was allowed to stand in for a statement about the DOCUMENTS.** Before a
vendor fact is filed as UNVERIFIED, the question is not "did the docs site answer" but
"does this vendor publish this anywhere I can reach" — their GitHub org, their SDK
packages, their published spec, PyPI, npm. This directory's own README had the shape of
the mistake in it: it listed exactly three evidence classes, none of which was "read the
vendor's own machine-readable contract", so there was no slot to file one in.

## Endpoint inventory (the complete `paths` list, verbatim keys)

Recorded here so a future reader can tell "the vendor has no such route" from "we did not
look". Routes this adapter calls are marked.

```
/agent  /agent/all  /agent/{agent_id}                       (v1, deprecated)
/agent/{agent_id}/executions  /agent/{agent_id}/execution/{execution_id}   (v1)
/v2/agent                                   <- create_agent
/v2/agent/all                               <- list_executions' fan-out
/v2/agent/{agent_id}                        <- get_agent / update_agent / delete_agent
/v2/agent/{agent_id}/stop
/v2/agent/{agent_id}/executions             <- list_executions
/v2/agent/{agent_id}/dispositions/test
/executions/{execution_id}                  <- get_execution
/executions/{execution_id}/log
/call                                       <- start_outbound_call
/call/{execution_id}/stop                   <- end_call
/batches  /batches/{agent_id}/all  /batches/{batch_id}  /batches/{batch_id}/executions
/batches/{batch_id}/stop  /batches/{batch_id}/schedule
/knowledgebase  /knowledgebase/all  /knowledgebase/{rag_id}
/providers  /providers/{provider_key_name}
/inbound/setup  /inbound/unlink
/me/voices  /user/model/custom  /user/me
/sip-trunks/trunks  /sip-trunks/trunks/{trunk_id}
/sip-trunks/trunks/{trunk_id}/numbers  /sip-trunks/trunks/{trunk_id}/numbers/{phone_number_id}
/extractions  /extractions/{template_id}
/phone-numbers/all  /phone-numbers/search  /phone-numbers/buy  /phone-numbers/{phone_number_id}
/sub-accounts/create  /sub-accounts/{sub_account_id}  /sub-accounts/all
/sub-accounts/{sub_account_id}/usage  /sub-accounts/all/usage
/violations/list  /violations/submit
/dispositions/  /dispositions/bulk  /dispositions/{disposition_id}
```

**There is no `/executions` collection.** The adapter called one until D-353.

## Facts this settles, with the spec element that settles each

| Fact | Spec element |
|---|---|
| Stop a call: `POST /call/{execution_id}/stop` | path `/call/{execution_id}/stop`, "Stop a queued or scheduled call" |
| Executions listing is PER AGENT | path `/v2/agent/{agent_id}/executions`, "Retrieve all executions by an agent" |
| Pagination: `page_number` (default 1), `page_size` (default 20, "Maximum allowed is 50"), `has_more` | listing query params; `AgentExecutionV2List` |
| Time filter is `from` / `to` on `created_at`, UTC ISO 8601 | listing query params `from`, `to` |
| Call statuses: fifteen values incl. `rescheduled`; **no `voicemail`** | `AgentExecution.status` enum; listing `status` filter enum |
| Voicemail is a boolean, not a status | `AgentExecution.answered_by_voice_mail` |
| Costs are **in cents** | `AgentExecution.total_cost`, `.cost_breakdown`, and all five `CostBreakdown` members |
| Cost breakdown keys: `llm`, `network`, `platform`, `synthesizer`, `transcriber` | `CostBreakdown` |
| Recording URL is nested under `telephony_data` | `TelephonyData.recording_url` |
| Duration field is `conversation_duration` (float seconds) | `AgentExecution.conversation_duration` |
| `POST /v2/agent` binds `ToolsConfigV2`, requiring `input` and `output` | `ToolsConfigV2.required` |
| v2 `llm_agent` nests model settings under `llm_config` | `LlmAgentV2`, `SimpleLlmAgent` |
| KB create is multipart `file` OR `url`; no agent id; no text | path `/knowledgebase` requestBody |
| KB objects carry `rag_id` AND `vector_id`; agents reference the latter | `Knowledgebase`, `LanceDbConfig.vector_ids` |
| `GET /knowledgebase/all` and `GET /v2/agent/all` return BARE ARRAYS | `KnowledgebaseList`, `AgentListV2` (`type: array`) |
| Error shape is `{error: int, message: str}` | `Error` (both members required) |
| `POST /call` returns `{message, status, execution_id}` | `MakeCallStatus` |

## Facts the prose files add (class: VERIFIED-VENDOR-REPO)

From the same repo at the same commit, `references/` and the SKILL.md set:

- **Webhook source IP is a single address, `13.203.39.153`** (`bolna-core.md`,
  `setup-webhook/SKILL.md`, `execution-payload.md`). Matches
  `calevate_shared.config.DEFAULT_BOLNA_SOURCE_IPS` exactly.
- **Webhooks are retried on non-2xx**, and fire once per status transition
  (`execution-payload.md` §"Webhook delivery"). This CONTRADICTS the repo's long-standing
  "at-most-once, no retry" claim, which came from the OSS framework's one-shot `aiohttp`
  delivery — a different program from the hosted deliverer. D-352.
- **Dedupe by `(execution_id, status)`, "never by `execution_id` alone, or you'll discard
  later updates"** (`setup-webhook/SKILL.md`). `apps/voice-runtime/engine_intake.py`
  already keys on exactly that pair.
- **Webhook payload is byte-for-byte the `GET /executions/{id}` response**
  (`execution-payload.md`, `setup-webhook/SKILL.md`).
- **Rate limits**: `GET /v2/agent/{id}`, `GET /v2/agent/{id}/executions` and `POST /call`
  at 500/min; everything else 1000/min; per organisation or per user (`bolna-core.md`).
- **`completed` is terminal and fires after post-processing** — recordings, transcripts and
  extractions — "~2-3 minutes after disconnect" (`call-statuses.md`). This is the claim
  `ExecutionSnapshot.billable_ready` encodes, now first-hand.
- **`scheduled_at` and other datetimes must carry a timezone offset**; without one they are
  "rejected or silently run in UTC" (`bolna-core.md`).
- **LLM providers are OpenAI, Azure OpenAI, OpenRouter, Google Gemini, and Custom
  (LiteLLM-compatible)** (`providers-matrix.md`). **There is no Sarvam LLM provider.**
  D-36's Sarvam 105B leg is reachable only by registering the model through
  `POST /user/model/custom` and sending `provider: "custom"` — D-356.
- **Sarvam IS a supported TTS and STT provider** (`providers-matrix.md`), covering Telugu on
  both legs. So two thirds of the D-36 stack is confirmed available on this engine.
- **Plivo is the India 160-series (transactional) carrier and Vobiz the 140-series
  (promotional) carrier** (`providers-matrix.md`) — which is the same split D-05 makes, from
  the vendor's side.

## What this does NOT settle

A specification is what the vendor says the server does. It is not the server.

- Nothing here has been exercised against `api.bolna.ai`: egress to that host is refused by
  this environment's proxy, so every live gate in OPERATIONS §2 stands.
- The OAS's provider enums are demonstrably NOT exhaustive — `Synthesizer.provider`
  enumerates four providers and the vendor's own `create-agent/SKILL.md` posts
  `"provider": "sarvam"`. So an absent enum member is not evidence of an unsupported value.
- Which currency's cents `total_cost` is denominated in is stated nowhere.
- Whether the hosted platform tolerates the legacy v1 `tools_config` at `/v2/agent` is
  unknown; the fix assumes it does not, which is the safe direction.
