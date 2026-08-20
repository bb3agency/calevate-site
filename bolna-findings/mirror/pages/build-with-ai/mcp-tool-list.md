> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Tool List

> Every tool the Bolna MCP server exposes, grouped by agents, calls, batches, dispositions, knowledgebases, phone numbers, SIP trunks, sub-accounts, voice, violations, and account.

57 tools. 55 are backed one-to-one by the [Bolna REST API](/docs/api-reference/introduction) and act on your account. The remaining 2 (`search_docs`, `get_doc`) read Bolna's public documentation instead — no account data involved.

| Type      | Meaning                                                                                                                                                                                                                                            |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Read`    | Looks something up. No side effects.                                                                                                                                                                                                               |
| `Write`   | Creates or changes something. Reversible or low-risk (e.g. `create_agent` just adds a new agent).                                                                                                                                                  |
| `Write ⚠` | Flagged **destructive** in the tool's own definition (`destructiveHint: true`) — irreversible, or has a real-world effect like spending balance or breaking something still in use. Most clients pause for your confirmation before running these. |

The 12 `⚠` tools are `update_agent`, `delete_agent`, `start_outbound_call`, `schedule_batch`, `delete_batch`, `delete_disposition`, `buy_phone_number`, `delete_phone_number`, `delete_sip_trunk`, `delete_sub_account`, `remove_provider`, and `delete_knowledgebase` — see each one's row below for what makes it destructive.

## Calling tools with a different account

Every tool below also accepts an optional `api_key` argument. Pass it on any single call to run that call against a different account than the one your client connected with — without reconnecting.

This is for [sub-accounts](/docs/api-reference/sub-accounts/overview): call `list_sub_accounts` to get a sub-account's key (`sa-...`), then pass it as `api_key` on any later tool call to act as that sub-account for just that call. A sub-account key also works as the primary connection credential from the start, exactly like a main account's `bn-...` key — see the [Quickstart](/docs/build-with-ai/mcp-quickstart).

## Agents

| Tool                      | Type    | Description                                                        | API                                                     |
| ------------------------- | ------- | ------------------------------------------------------------------ | ------------------------------------------------------- |
| `list_agents`             | Read    | List agents in the account — ID, name, status, created date        | [List Agents](/docs/api-reference/agent/v2/get_all)          |
| `get_agent`               | Read    | Full config of one agent — prompts, LLM, voice, telephony, tools   | [Get Agent](/docs/api-reference/agent/v2/get)                |
| `create_agent`            | Write   | Create a new agent, returns its ID                                 | [Create Agent](/docs/api-reference/agent/v2/create)          |
| `update_agent`            | Write ⚠ | Patch an agent's name, prompts, welcome message, webhook, or voice | [Patch Update](/docs/api-reference/agent/v2/patch_update)    |
| `delete_agent`            | Write ⚠ | Permanently delete an agent and its history                        | [Delete Agent](/docs/api-reference/agent/v2/delete)          |
| `stop_agent_queued_calls` | Write   | Cancel every queued or scheduled call for one agent                | [Stop Agent Queued Calls](/docs/api-reference/agent/v2/stop) |

## Calls & executions

| Tool                     | Type    | Description                                                                         | API                                                                |
| ------------------------ | ------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `start_outbound_call`    | Write ⚠ | Place a real outbound call, spends account balance                                  | [Make Call](/docs/api-reference/calls/make)                             |
| `stop_call`              | Write   | Cancel a single queued or scheduled call                                            | [Stop Call](/docs/api-reference/calls/stop_call)                        |
| `list_agent_executions`  | Read    | Call history for one agent, defaults to the last 7 days                             | [Get Executions](/docs/api-reference/agent/v2/get_all_agent_executions) |
| `get_execution`          | Read    | Full call detail — transcript, status, cost, telephony data                         | [Get Execution](/docs/api-reference/executions/get_execution)           |
| `get_execution_raw_logs` | Read    | Raw per-component pipeline logs for one call — transcriber, LLM, synthesizer timing | [Raw Logs](/docs/api-reference/executions/get_execution_raw_logs)       |
| `list_batch_executions`  | Read    | Every call execution within one batch                                               | [Batch Executions](/docs/api-reference/executions/get_batch_executions) |

## Batches

| Tool             | Type    | Description                                                      | API                                               |
| ---------------- | ------- | ---------------------------------------------------------------- | ------------------------------------------------- |
| `list_batches`   | Read    | Batch campaigns for one agent — status and schedule              | [Get Batches](/docs/api-reference/batches/get_batches) |
| `create_batch`   | Write   | Create a batch of outbound calls from a recipient list           | [Create Batch](/docs/api-reference/batches/create)     |
| `get_batch`      | Read    | One batch's status, schedule, and contact counts                 | [Get Batch](/docs/api-reference/batches/get_batch)     |
| `schedule_batch` | Write ⚠ | Start calling every recipient in a batch, spends account balance | [Schedule Batch](/docs/api-reference/batches/schedule) |
| `stop_batch`     | Write   | Halt a running or scheduled batch                                | [Stop Batch](/docs/api-reference/batches/stop)         |
| `delete_batch`   | Write ⚠ | Permanently delete a batch and its recipient list                | [Delete Batch](/docs/api-reference/batches/delete)     |

## Dispositions

Dispositions turn a call transcript into structured, typed data — lead qualified, appointment time, sentiment — surfaced as `extracted_data` on executions and webhook payloads.

| Tool                       | Type    | Description                                                                              | API                                                                 |
| -------------------------- | ------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `list_dispositions`        | Read    | Dispositions configured for one agent                                                    | [List Dispositions](/docs/api-reference/dispositions/list)               |
| `get_disposition`          | Read    | One disposition's field type, validation, and prompt                                     | [Get Disposition](/docs/api-reference/dispositions/get)                  |
| `create_disposition`       | Write   | Add a single disposition to an agent                                                     | [Create Disposition](/docs/api-reference/dispositions/create)            |
| `bulk_create_dispositions` | Write   | Add several dispositions to an agent in one call                                         | [Bulk Create Dispositions](/docs/api-reference/dispositions/bulk-create) |
| `update_disposition`       | Write   | Change a disposition's field, validation, or prompt                                      | [Update Disposition](/docs/api-reference/dispositions/update)            |
| `delete_disposition`       | Write ⚠ | Permanently delete a disposition                                                         | [Delete Disposition](/docs/api-reference/dispositions/delete)            |
| `test_dispositions`        | Write   | Run an agent's dispositions against a sample transcript and preview the extracted output | [Test Dispositions](/docs/api-reference/dispositions/test)               |

## Knowledgebase (RAG)

| Tool                   | Type    | Description                                                                                                     | API                                                                        |
| ---------------------- | ------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `list_knowledgebases`  | Read    | Every knowledgebase on the account                                                                              | [List All Knowledgebases](/docs/api-reference/knowledgebase/get_knowledgebases) |
| `get_knowledgebase`    | Read    | One knowledgebase's file name, status, and settings, by ID                                                      | [Get Knowledgebase](/docs/api-reference/knowledgebase/get_knowledgebase)        |
| `create_knowledgebase` | Write   | Create a knowledgebase by scraping a URL for RAG. Processing is async — check progress with `get_knowledgebase` | [Create Knowledgebase](/docs/api-reference/knowledgebase/create)                |
| `delete_knowledgebase` | Write ⚠ | Permanently delete a knowledgebase                                                                              | [Delete Knowledgebase](/docs/api-reference/knowledgebase/delete)                |

<Note>
  `create_knowledgebase` only accepts a URL to scrape — the Bolna API also supports uploading a PDF directly, but a raw file doesn't map cleanly to a chat tool argument. For PDF-based knowledgebases, use the [dashboard](https://platform.bolna.ai) or call the [Create Knowledgebase API](/docs/api-reference/knowledgebase/create) directly.
</Note>

## Phone numbers & inbound

| Tool                   | Type    | Description                                                       | API                                                         |
| ---------------------- | ------- | ----------------------------------------------------------------- | ----------------------------------------------------------- |
| `list_phone_numbers`   | Read    | Phone numbers on the account and their linked agent               | [Get All](/docs/api-reference/phone-numbers/get_all)             |
| `search_phone_numbers` | Read    | Search available numbers to buy, by country or pattern            | [Search Phone Numbers](/docs/api-reference/phone-numbers/search) |
| `buy_phone_number`     | Write ⚠ | Purchase a phone number, spends account balance (flat \$5/month)  | [Buy Phone Numbers](/docs/api-reference/phone-numbers/buy)       |
| `delete_phone_number`  | Write ⚠ | Permanently release a phone number back to the pool               | [Delete Phone Numbers](/docs/api-reference/phone-numbers/delete) |
| `setup_inbound_agent`  | Write   | Route inbound calls on a number to an agent, with an optional IVR | [Set Inbound Agent](/docs/api-reference/inbound/agent)           |
| `unlink_inbound_agent` | Write   | Remove the inbound routing from a phone number                    | [Remove Inbound Agent](/docs/api-reference/inbound/unlink)       |

## SIP trunks

For bringing your own telephony (BYOT) — Twilio Elastic SIP, Plivo Zentrunk, Telnyx, and other standards-compliant trunks.

| Tool                  | Type    | Description                                             | API                                                                 |
| --------------------- | ------- | ------------------------------------------------------- | ------------------------------------------------------------------- |
| `create_sip_trunk`    | Write   | Register a SIP trunk with its gateway and auth settings | [Create SIP Trunk](/docs/api-reference/sip-trunks/create)                |
| `get_sip_trunk`       | Read    | One trunk's gateway, auth, and transport config         | [Get SIP Trunk](/docs/api-reference/sip-trunks/get)                      |
| `list_sip_trunks`     | Read    | SIP trunks on the account                               | [List SIP Trunks](/docs/api-reference/sip-trunks/get_all)                |
| `update_sip_trunk`    | Write   | Change a trunk's gateway, auth, or transport settings   | [Update SIP Trunk](/docs/api-reference/sip-trunks/update)                |
| `delete_sip_trunk`    | Write ⚠ | Permanently delete a SIP trunk                          | [Delete SIP Trunk](/docs/api-reference/sip-trunks/delete)                |
| `add_trunk_number`    | Write   | Attach a DID number to a trunk                          | [Add Number to Trunk](/docs/api-reference/sip-trunks/add_number)         |
| `remove_trunk_number` | Write   | Detach a DID number from a trunk                        | [Remove Number from Trunk](/docs/api-reference/sip-trunks/remove_number) |
| `list_trunk_numbers`  | Read    | DID numbers attached to one trunk                       | [List Numbers on Trunk](/docs/api-reference/sip-trunks/list_numbers)     |

## Sub-accounts

Enterprise feature — isolated workspaces with their own auto-provisioned API key (`sa-...`), agents, calls, and phone numbers, for agencies, multi-tenant platforms, or regulated data boundaries.

| Tool                         | Type    | Description                                               | API                                                      |
| ---------------------------- | ------- | --------------------------------------------------------- | -------------------------------------------------------- |
| `create_sub_account`         | Write   | Create a sub-account and provision its API key            | [Create Sub-Account](/docs/api-reference/sub-accounts/create) |
| `list_sub_accounts`          | Read    | Sub-accounts on the account, including their API keys     | [List Sub-Accounts](/docs/api-reference/sub-accounts/get_all) |
| `update_sub_account`         | Write   | Patch a sub-account's name or settings                    | [Patch Update](/docs/api-reference/sub-accounts/patch_update) |
| `delete_sub_account`         | Write ⚠ | Permanently delete a sub-account and everything inside it | [Delete Sub-Account](/docs/api-reference/sub-accounts/delete) |
| `get_sub_account_usage`      | Read    | Call volume and cost for one sub-account                  | [Track Usage](/docs/api-reference/sub-accounts/usage)         |
| `get_all_sub_accounts_usage` | Read    | Usage for every sub-account on the account, in one call   | [All Usage](/docs/api-reference/sub-accounts/all_usage)       |

## Voice & providers

| Tool                 | Type    | Description                                                             | API                                                                 |
| -------------------- | ------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `list_tts_providers` | Read    | Text-to-speech providers and models available to the account            | [List TTS Providers and Models](/docs/api-reference/voice/get_providers) |
| `list_voices`        | Read    | Voices available across connected TTS providers                         | [List Voices](/docs/api-reference/voice/get_all)                         |
| `list_providers`     | Read    | Telephony, LLM, transcriber, and TTS providers connected to the account | [List Providers](/docs/api-reference/providers/get)                      |
| `remove_provider`    | Write ⚠ | Disconnect a provider's credentials — breaks any agent still using it   | [Remove a Provider](/docs/api-reference/providers/remove)                |

## Violations

| Tool              | Type | Description                                                                                                                                             | API                                               |
| ----------------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `list_violations` | Read | Flagged call violations — content policy, regulatory, or fraud — optionally filtered by status (`pending`/`accepted`/`rejected`/`submitted`), paginated | [List Violations](/docs/api-reference/violations/list) |

## Account

| Tool            | Type | Description                                         | API                                   |
| --------------- | ---- | --------------------------------------------------- | ------------------------------------- |
| `get_user_info` | Read | Account profile, wallet balance, concurrency limits | [User Info](/docs/api-reference/user/info) |

## Documentation

These two don't touch your account at all — they read Bolna's own docs, so the assistant can look things up instead of guessing.

| Tool          | Type | Description                                                                                                                                         | Source                   |
| ------------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| `search_docs` | Read | Searches Bolna's documentation index ([`llms.txt`](https://www.bolna.ai/docs/llms.txt)) and returns ranked matches with title, URL, and description | `llms.txt`               |
| `get_doc`     | Read | Fetches a documentation page's full Markdown content, given a bare path (e.g. `/docs/build-with-ai/mcp`) or a full URL                              | `www.bolna.ai/docs/*.md` |

Not connected yet? See the [Quickstart](/docs/build-with-ai/mcp-quickstart) for setup and troubleshooting.

<Card title="Bolna MCP Server Repository" icon="github" href="https://github.com/bolna-ai/mcp">
  Full source, endpoint-verification notes, and issue tracker
</Card>
