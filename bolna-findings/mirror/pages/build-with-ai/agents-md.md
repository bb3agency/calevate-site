> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# AGENTS.md

> Machine-readable API guidance for AI coding assistants generating Bolna API code.

[AGENTS.md](/docs/AGENTS.md) encodes the non-obvious facts and gotchas an AI coding assistant needs to generate correct Bolna API code — the things most likely to produce broken code if missed. The [OpenAPI spec](/docs/api-reference/introduction) is the authoritative reference; AGENTS.md surfaces what it's easy to miss.

## Highlights

<AccordionGroup>
  <Accordion title="Base URL and authentication" icon="key">
    ```
    Base URL:  https://api.bolna.ai
    Auth:      Authorization: Bearer <api_key>
    ```

    A missing or invalid key returns `401 Access denied`.
  </Accordion>

  <Accordion title="POST /v2/agent and POST /batches return 201, not 200" icon="circle-check">
    Both return `201 Created`. The agent-create response field is `state`, not `status`. The legacy v1 `/agent` endpoint returns `200` — only v2 returns `201`.
  </Accordion>

  <Accordion title="scheduled_at must use +00:00, not Z" icon="clock">
    A trailing `Z` for UTC is rejected with a `500` error. Use a numeric offset instead, e.g. `2026-06-23T15:30:00+00:00`. Scheduling must also be at least 2 minutes in the future, and Bolna rounds up to the next 10-minute mark.
  </Accordion>

  <Accordion title="Wait for completed, not call-disconnected" icon="phone-hangup">
    `call-disconnected` fires the instant the line drops — at that moment `conversation_duration`, `total_cost`, `recording_url`, and `extracted_data` are still null or 0. The `completed` event arrives a few seconds later with all fields populated.
  </Accordion>

  <Accordion title="toolchain.pipelines is an array of arrays" icon="diagram-project">
    Not an array of strings. Correct shape: `"pipelines": [["transcriber", "llm", "synthesizer"]]`.
  </Accordion>

  <Accordion title="GET /batches/{batch_id}/executions returns a bare array" icon="list">
    Not wrapped in `{ "data": [...] }` — the response is the array directly.
  </Accordion>

  <Accordion title="Webhook source IP" icon="globe">
    Bolna sends webhooks from `13.203.39.153`, `13.126.9.249` and `13.202.133.53`. Whitelist all three or events will be dropped.
  </Accordion>
</AccordionGroup>

## What else is in the file

* The full execution status lifecycle (`queued → initiated → ringing → in-progress → call-disconnected → completed`, plus terminal states)
* The batch status lifecycle
* A minimal working agent creation body
* A key endpoint summary table

Read the complete file at [/AGENTS.md](/docs/AGENTS.md).
