> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Patch Update to Voice AI Agent API

> Learn how to partially update properties. Update Bolna Voice AI agent name, welcome message, webhook URL, voice settings, calling guardrails, telephony provider, and prompts, using this endpoint.

Partially update an existing agent. Unlike the [full update](/docs/api-reference/agent/v2/update) (`PUT`), which replaces the entire agent configuration, `PATCH` only touches the attributes you include in the request body — everything else is left unchanged.

Returns HTTP **200** with `{ "message": "success", "state": "updated" }`.

<Tip>
  Use `PATCH` for small, targeted edits (renaming an agent, swapping a voice, updating a webhook URL). Use [`PUT`](/docs/api-reference/agent/v2/update) when you need to rewrite tasks, toolchains, or the full prompt structure.
</Tip>

## Updatable attributes

Only the following attributes can be updated via `PATCH`. Any other field in the body is ignored.

| Attribute               | Location       | Description                                                                                                                                                                                                    |
| ----------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent_name`            | `agent_config` | Display name of the agent.                                                                                                                                                                                     |
| `agent_welcome_message` | `agent_config` | First message the agent speaks when a call connects.                                                                                                                                                           |
| `webhook_url`           | `agent_config` | URL that receives the [execution payload](/docs/api-reference/executions/get_execution) as call status changes. Whitelist source IPs `13.203.39.153`, `13.126.9.249` and `13.202.133.53`. Pass `null` to remove it. |
| `synthesizer`           | `agent_config` | Text-to-speech configuration (provider, voice, model, etc.).                                                                                                                                                   |
| `ingest_source_config`  | `agent_config` | CRM ingestion source for inbound agents (`api`, `csv`, or `google_sheet`).                                                                                                                                     |
| `telephony_provider`    | `agent_config` | Telephony provider. Changing it auto-updates the audio format.                                                                                                                                                 |
| `calling_guardrails`    | `agent_config` | Time-based restrictions for outbound calls.                                                                                                                                                                    |
| `agent_prompts`         | top-level      | Prompts per task, keyed as `task_1`, `task_2`, …                                                                                                                                                               |

<Note>
  All agent-config attributes go inside the `agent_config` object. `agent_prompts` is a top-level key, a sibling of `agent_config`.
</Note>

## calling\_guardrails

Restrict when your agent places outbound calls. Calls triggered outside the allowed window are automatically rescheduled to the next allowed start time in the **recipient's** timezone. It accepts two keys:

| Key               | Type           | Description                                                                     |
| ----------------- | -------------- | ------------------------------------------------------------------------------- |
| `call_start_hour` | integer (0–23) | Start of the allowed calling window, 24-hour format.                            |
| `call_end_hour`   | integer (0–23) | End of the allowed calling window, 24-hour format. Must be `≥ call_start_hour`. |

```json Update calling guardrails theme={"system"}
{
  "agent_config": {
    "calling_guardrails": {
      "call_start_hour": 9,
      "call_end_hour": 21
    }
  }
}
```

<Note>
  Hours use 24-hour format: `0` = midnight, `9` = 9 AM, `17` = 5 PM, `21` = 9 PM. See the [Calling Guardrails guide](/docs/guides/outbound/calling-guardrails) for rescheduling behavior and regional calling regulations.
</Note>

## telephony\_provider

Switch the telephony provider the agent uses. When changed, the agent's audio input/output format is updated automatically to match the provider (`wav` for `twilio`/`plivo`/`exotel`/`vobiz`, `ulaw` for `sip-trunk`).

Accepted values: `twilio`, `plivo`, `exotel`, `vobiz`, `sip-trunk`, `default`.

```json Switch to SIP trunk theme={"system"}
{
  "agent_config": {
    "telephony_provider": "sip-trunk"
  }
}
```

<Note>
  If you patch `telephony_provider` to `sip-trunk`, the next step is to [set the inbound agent](/docs/api-reference/inbound/agent) so your SIP trunk phone number maps to this agent for receiving inbound calls.
</Note>

## Examples

<CodeGroup>
  ```json Rename + new welcome message theme={"system"}
  {
    "agent_config": {
      "agent_name": "Support Agent v2",
      "agent_welcome_message": "Hi! Thanks for calling. How can I help?"
    }
  }
  ```

  ```json Update webhook URL theme={"system"}
  {
    "agent_config": {
      "webhook_url": "https://your-server.com/bolna-webhook"
    }
  }
  ```

  ```json Change the voice theme={"system"}
  {
    "agent_config": {
      "synthesizer": {
        "provider": "elevenlabs",
        "provider_config": {
          "voice": "Nila",
          "voice_id": "V9LCAAi4tTlqe9JadbCo",
          "model": "eleven_turbo_v2_5"
        },
        "stream": true,
        "buffer_size": 250,
        "audio_format": "wav"
      }
    }
  }
  ```

  ```json Update a task prompt theme={"system"}
  {
    "agent_prompts": {
      "task_1": {
        "system_prompt": "You are a helpful support agent. Keep replies short."
      }
    }
  }
  ```
</CodeGroup>

You can also combine multiple attributes in a single request:

```json Combined patch theme={"system"}
{
  "agent_config": {
    "agent_name": "Sales Agent",
    "webhook_url": "https://your-server.com/bolna-webhook",
    "telephony_provider": "plivo",
    "calling_guardrails": {
      "call_start_hour": 9,
      "call_end_hour": 21
    }
  },
  "agent_prompts": {
    "task_1": {
      "system_prompt": "You are an outbound sales agent. Be concise and friendly."
    }
  }
}
```

```json 200 Response theme={"system"}
{
  "message": "success",
  "state": "updated"
}
```

## Next steps

<CardGroup cols={2}>
  <Card title="Full update (PUT)" icon="pen-to-square" href="/docs/api-reference/agent/v2/update">
    Replace the entire agent configuration, tasks, and prompts.
  </Card>

  <Card title="Calling Guardrails" icon="clock" href="/docs/guides/outbound/calling-guardrails">
    Control outbound call timing and rescheduling.
  </Card>

  <Card title="Set inbound agent" icon="phone-arrow-down-left" href="/docs/api-reference/inbound/agent">
    Map a phone number to an agent for inbound calls.
  </Card>

  <Card title="Webhooks" icon="webhook" href="/docs/guides/post-call/polling-call-status-webhooks">
    Receive call results without polling.
  </Card>
</CardGroup>


## OpenAPI

````yaml PATCH /v2/agent/{agent_id}
openapi: 3.1.0
info:
  title: Bolna API
  description: >-
    Use and leverage Bolna Voice AI using APIs through HTTP requests from any
    language in your applications and workflows.
  license:
    name: MIT
  version: 1.0.0
servers:
  - url: https://api.bolna.ai
    description: Production server
security:
  - bearerAuth: []
paths:
  /v2/agent/{agent_id}:
    patch:
      description: Patch update an agent
      parameters:
        - in: path
          name: agent_id
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        description: Update an agent
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/AgentPatchRequest'
        required: true
      responses:
        '200':
          description: agent status response
          content:
            application/json:
              example:
                message: success
                state: updated
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    AgentPatchRequest:
      properties:
        agent_config:
          $ref: '#/components/schemas/AgentConfigPatchRequest'
          description: Configuration of the agent
        agent_prompts:
          $ref: '#/components/schemas/AgentPrompt'
          description: >-
            Prompts to be provided to the agent. It can have multiple tasks of
            the form `task_<task_id>`
      type: object
    Error:
      required:
        - error
        - message
      type: object
      properties:
        error:
          type: integer
          format: int32
        message:
          type: string
    AgentConfigPatchRequest:
      type: object
      properties:
        agent_name:
          description: The name of the agent
          type: string
          example: Alfred
        agent_welcome_message:
          description: Initial welcome message by agent
          type: string
          example: How are you doing Bruce?
        webhook_url:
          description: >-
            Webhook URL to receive execution data for all conversations as
            [get_execution API](/api-reference/executions/get_execution). Bolna
            POSTs the execution payload as the call status changes (multiple
            events per call). **Whitelist source IPs `13.203.39.153`,
            `13.126.9.249` and `13.202.133.53`** on your server to ensure
            delivery.
          type: string
          example: null
        synthesizer:
          $ref: '#/components/schemas/Synthesizer'
          type: object
          description: Configuration of Synthesizer model for the agent task
        ingest_source_config:
          $ref: '#/components/schemas/IngestSourceConfig'
        telephony_provider:
          type: string
          description: >-
            The telephony provider to use for this agent. When changed, the
            agent's audio input/output format is automatically updated to match
            the provider (e.g., `wav` for twilio/plivo/exotel/vobiz, `ulaw` for
            sip-trunk).
          enum:
            - twilio
            - plivo
            - exotel
            - vobiz
            - sip-trunk
            - default
          example: sip-trunk
        calling_guardrails:
          type: object
          description: >-
            Time-based restrictions for outbound calls. See the [Calling
            Guardrails guide](/guides/outbound/calling-guardrails) for details.
          properties:
            call_start_hour:
              type: integer
              minimum: 0
              maximum: 23
              description: >-
                Start of allowed calling window in 24-hour format (recipient's
                timezone)
              example: 9
            call_end_hour:
              type: integer
              minimum: 0
              maximum: 23
              description: >-
                End of allowed calling window in 24-hour format (recipient's
                timezone)
              example: 21
    AgentPrompt:
      properties:
        task_1:
          type: object
          properties:
            system_prompt:
              description: The system prompt fed into the agent
              type: string
              example: >-
                What is the Ultimate Question of Life, the Universe, and
                Everything?
          required:
            - system_prompt
      type: object
    Synthesizer:
      properties:
        provider:
          type: string
          enum:
            - polly
            - elevenlabs
            - deepgram
            - styletts
          example: elevenlabs
        provider_config:
          oneOf:
            - $ref: '#/components/schemas/ElevenLabsConfig'
            - $ref: '#/components/schemas/PollyConfig'
            - $ref: '#/components/schemas/DeepgramConfig'
        stream:
          type: boolean
          default: true
        buffer_size:
          type: integer
          default: 250
          example: 250
        audio_format:
          type: string
          default: wav
          enum:
            - wav
      type: object
      required:
        - provider
        - provider_config
    IngestSourceConfig:
      type: object
      description: >-
        Configuration for ingestion source used for inbound agents. Required
        fields vary by `source_type`.
      properties:
        source_type:
          type: string
          enum:
            - api
            - csv
            - google_sheet
          description: Type of CRM ingestion source
          example: api
        source_url:
          type: string
          format: uri
          nullable: true
          description: API or Google Sheet URL
          example: https://example.com/api/data
        source_auth_token:
          type: string
          nullable: true
          description: Bearer token for API authentication
          example: abc123
        source_name:
          type: string
          nullable: true
          description: File or sheet name
          example: leads_sheet_june.csv
      allOf:
        - if:
            properties:
              source_type:
                const: api
          then:
            required:
              - source_url
              - source_auth_token
        - if:
            properties:
              source_type:
                const: csv
          then:
            required:
              - source_name
        - if:
            properties:
              source_type:
                const: google_sheet
          then:
            required:
              - source_name
              - source_url
    ElevenLabsConfig:
      title: ElevenLabs
      properties:
        voice:
          type: string
          description: Name of voice
          enum:
            - Nila
        voice_id:
          type: string
          description: Unique voice id
          enum:
            - V9LCAAi4tTlqe9JadbCo
        model:
          type: string
          description: Model to be used
          enum:
            - eleven_turbo_v2_5
            - eleven_flash_v2_5
            - eleven_v3_conversational
          example: eleven_turbo_v2_5
      required:
        - voice
        - voice_id
        - model
    PollyConfig:
      title: Polly
      properties:
        voice:
          type: string
          description: Name of voice
          enum:
            - Matthew
        engine:
          type: string
          description: Engine of voice
          enum:
            - generative
        sampling_rate:
          type: string
          description: Sampling rate of voice
          default: '8000'
          enum:
            - '8000'
            - '16000'
        language:
          type: string
          description: Language of voice
          enum:
            - en-US
      required:
        - voice
        - engine
        - language
    DeepgramConfig:
      title: Deepgram
      properties:
        voice:
          type: string
          description: Name of voice
          enum:
            - Asteria
        model:
          type: string
          description: Model of voice
          example: aura-asteria-en
        sampling_rate:
          type: string
          description: Sampling rate of voice
          default: '24000'
      required:
        - voice
        - model
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````