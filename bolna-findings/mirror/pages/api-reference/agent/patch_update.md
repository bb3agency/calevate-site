> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Patch Update to Voice AI Agent API (deprecated)

> Learn how to partially update properties. Update Bolna Voice AI agent name, welcome message, webhook URL, voice settings, and prompts, using this endpoint.

<Warning>
  These APIs have now been deprecated.

  Please use the latest [**v2 APIs**](/docs/api-reference/agent/v2/overview).
</Warning>


## OpenAPI

````yaml PATCH /agent/{agent_id}
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
  /agent/{agent_id}:
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