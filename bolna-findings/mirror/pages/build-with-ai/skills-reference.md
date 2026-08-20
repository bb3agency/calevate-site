> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Skills Reference

> All 19 Bolna Skills, grouped by build, call, monitor, and advanced categories.

Every skill below can be installed on its own with `npx skills add bolna-ai/skills --skill <name>`, or all together per [Installation](/docs/build-with-ai/installation).

## Build agents

| Skill            | Description                                                                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `setup-api-key`  | Generate, store, and verify your `BOLNA_API_KEY`                                                                                                              |
| `add-provider`   | Bring your own OpenAI, Anthropic, Azure, ElevenLabs, Cartesia, Sarvam, Deepgram, Twilio, Plivo, Vobiz, or Exotel credentials                                  |
| `create-agent`   | Create a voice agent end-to-end — LLM, voice, transcriber, telephony, knowledge bases, and function tools                                                     |
| `manage-agents`  | List, update, delete, or stop queued calls for an agent                                                                                                       |
| `prompt-writing` | Author production voice prompts — sectioned structure, Hindi-first/English-second scripted lines, FAQ in YAML, multilingual entries with per-language STT/TTS |

## Make calls

| Skill                  | Description                                                                                                    |
| ---------------------- | -------------------------------------------------------------------------------------------------------------- |
| `make-call`            | Place a single outbound call — immediate or scheduled, with dynamic variables, voice overrides, and auto-retry |
| `create-batch`         | Run CSV-driven outbound campaigns at scale — schedule, monitor, stop                                           |
| `setup-inbound`        | Wire phone numbers to agents, with IVR menus, caller identification, and multilingual auto-switching           |
| `manage-phone-numbers` | Search and buy US (Twilio) or India (Plivo, Vobiz) phone numbers                                               |
| `setup-sip-trunk`      | Bring your own SIP trunk — Twilio Elastic, Plivo Zentrunk, Telnyx, Vonage, and any standards-compliant carrier |

## Monitor and improve

| Skill                | Description                                                                                                                      |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `get-executions`     | Pull transcripts, recordings, costs, hangup codes, and raw logs from any call                                                    |
| `setup-webhook`      | Stream call updates to your backend in real time for CRM sync and dashboards                                                     |
| `create-disposition` | Extract structured data from every transcript — lead quality, appointment times, sentiment, consent captured                     |
| `manage-violations`  | List compliance flags and submit evidence files for review                                                                       |
| `debug-bolna-calls`  | Symptom-to-fix runbook for slow responses, robotic voice, interruptions, missed webhooks, SIP no-audio, batch failures, and more |

## Advanced

| Skill                  | Description                                                                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `bolna-graph-agents`   | Build deterministic, node-based call flows with LLM, expression, and event-driven transitions; push real-time events into live calls |
| `setup-tools`          | Give agents function-calling tools — live transfer, Cal.com booking, any HTTP API, and DTMF keypad input                             |
| `create-knowledgebase` | Add RAG over PDFs or URLs, including multilingual document support                                                                   |
| `manage-subaccounts`   | Multi-tenant workspaces for agencies and enterprise teams, with auto-provisioned API keys                                            |

<Card title="Skills Repository" icon="github" href="https://github.com/bolna-ai/skills">
  Browse the full source of every skill, report issues, or contribute
</Card>
