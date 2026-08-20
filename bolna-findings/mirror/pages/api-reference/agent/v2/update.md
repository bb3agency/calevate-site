> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Voice AI Agent API

> Update agent configurations, tasks, and prompts to refine behavior and capabilities using Bolna Voice AI agent APIs.



## OpenAPI

````yaml PUT /v2/agent/{agent_id}
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
    put:
      description: Update an agent
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
              $ref: '#/components/schemas/AgentRequestV2'
        required: true
      responses:
        '200':
          description: agent status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AgentUpdateStatus'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    AgentRequestV2:
      properties:
        agent_config:
          $ref: '#/components/schemas/AgentConfigV2'
          description: Configuration of the agent
        agent_prompts:
          $ref: '#/components/schemas/AgentPrompt'
          description: >-
            Prompts to be provided to the agent. It can have multiple tasks of
            the form `task_<task_id>`
      type: object
      required:
        - agent_config
        - agent_prompts
    AgentUpdateStatus:
      properties:
        agent_id:
          type: string
          format: uuid
        status:
          type: string
          enum:
            - updated
          example: updated
      type: object
      title: agentstatus
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
    AgentConfigV2:
      required:
        - agent_name
        - tasks
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
            Webhook URL to receive data for all conversations as [get_execution
            API](/api-reference/executions/get_execution). Bolna sends webhooks
            from source IPs `13.203.39.153`, `13.126.9.249` and `13.202.133.53`
            — whitelist all three on your server.
          type: string
          example: https://your-server.com/webhook
        agent_type:
          description: Agent type
          type: string
          example: other
        tasks:
          items:
            $ref: '#/components/schemas/TasksConfigV2'
          type: array
          description: An array of tasks that the agent can perform
        ingest_source_config:
          $ref: '#/components/schemas/IngestSourceConfig'
        calling_guardrails:
          type: object
          description: Time-based restrictions for outbound calls
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
              example: 17
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
    TasksConfigV2:
      properties:
        task_type:
          type: string
          description: Type of task
          enum:
            - conversation
            - extraction
            - summarization
        tools_config:
          $ref: '#/components/schemas/ToolsConfigV2'
          type: object
          description: Configuration of multiple tools that form a task
        toolchain:
          $ref: '#/components/schemas/Toolchain'
          type: object
          description: Agent will execute these tools in the specified order
        task_config:
          $ref: '#/components/schemas/ConversationConfig'
          type: object
          description: >-
            Should be used only in conversation task for now and it consists of
            all the required configuration for conversational nuances
      type: object
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
    ToolsConfigV2:
      properties:
        llm_agent:
          $ref: '#/components/schemas/LlmAgentV2'
          type: object
          description: Configuration of LLM model for the agent task
        synthesizer:
          $ref: '#/components/schemas/Synthesizer'
          type: object
          description: Configuration of Synthesizer model for the agent task
        transcriber:
          $ref: '#/components/schemas/Transcriber'
          type: object
          description: Configuration of Transcriber model for the agent task
        input:
          $ref: '#/components/schemas/InputOutput'
          type: object
          description: Configuration of Input handler
        output:
          $ref: '#/components/schemas/InputOutput'
          type: object
          description: Configuration of Output handler
        api_tools:
          $ref: '#/components/schemas/ApiTools'
          type: object
          description: Api tools you'd like the agents to have access to
          default: null
          nullable: true
        multilingual_config:
          $ref: '#/components/schemas/MultilingualConfig'
          description: >-
            Enables a multilingual agent that can understand and respond in
            multiple languages within a single call. The top-level `transcriber`
            and `synthesizer` act as the base; each language overrides them. See
            the [Multilingual Config
            Reference](/customizations/multilingual-config-reference).
          default: null
          nullable: true
      type: object
      required:
        - llm_agent
        - synthesizer
        - transcriber
        - input
        - output
    Toolchain:
      properties:
        execution:
          type: string
          enum:
            - parallel
            - sequential
        pipelines:
          type: array
          description: >-
            Array of pipeline stages. Each element is itself an array of stage
            names, representing one pipeline (e.g.
            `[["transcriber","llm","synthesizer"]]`).
          items:
            type: array
            items:
              type: string
              enum:
                - transcriber
                - llm
                - synthesizer
          example:
            - - transcriber
              - llm
              - synthesizer
      type: object
      required:
        - execution
        - pipelines
    ConversationConfig:
      properties:
        hangup_after_silence:
          anyOf:
            - type: integer
          title: Hangup After Silence
          description: >-
            Time to wait in seconds before hanging up in case user doesn't speak
            a thing
          default: 10
          example: 10
        hangup_after_LLMCall:
          type: boolean
          title: Hangup After Llmcall
          description: >-
            Whether to use LLM prompt to hang up or not. Pretty soon this will
            be replaced by predefined function
          default: false
          example: false
        incremental_delay:
          anyOf:
            - type: integer
          title: Incremental Delay
          description: >-
            Since we work with interim results, this will dictate the linear
            delay to add before speaking everytime we get a partial transcript
            from ASR
          default: 400
          example: 400
        number_of_words_for_interruption:
          anyOf:
            - type: integer
          title: Number Of Words For Interruption
          description: >-
            To avoid accidental interruption, how many words should we wait for
            before interrupting
          default: 2
          example: 2
        call_cancellation_prompt:
          anyOf:
            - type: string
          title: Call Cancellation Prompt
          example: null
        backchanneling:
          anyOf:
            - type: boolean
          title: Backchanneling
          description: >-
            This will enable agent to acknowledge when user is speaking long
            sentences
          default: false
          example: false
        backchanneling_message_gap:
          anyOf:
            - type: integer
          title: Backchanneling Message Gap
          description: >-
            Gap between every successive acknowledgement. We will also add a
            random jitter to this value to make it more random
          default: 5
          example: 5
        backchanneling_start_delay:
          anyOf:
            - type: integer
          title: Backchanneling Start Delay
          description: Basic delay after which we should start with backchanneling
          default: 5
          example: 5
        ambient_noise:
          type: boolean
          default: false
          description: >-
            Whether ambient background noise is played during the call. The
            track is selected using `ambient_noise_track`
        ambient_noise_track:
          type: string
          title: Ambient Noise Track
          description: >-
            ID of the ambient noise track to play during calls. Use a preset
            track ID (e.g. `coffee-shop`, `office-ambience`, `call-center`) or
            the ID of a custom track uploaded via `POST /ambient-sounds/custom`.
            Set to `null` to disable ambient noise. Only supported with Plivo
            and Vobiz telephony providers.
          default: null
          example: coffee-shop
        call_terminate:
          anyOf:
            - type: integer
          title: Terminate a call after specified number of seconds
          description: The call automatically disconnects reaching this limit
          default: 90
          example: 90
        inbound_limit:
          type: integer
          default: -1
          description: >-
            Set the number of times each phone number is allowed to call. Put
            `-1` to allow unlimited calls.
        whitelist_phone_numbers:
          type: array
          example: null
          items:
            type: string
            format: uuid
          description: >-
            Add phone numbers here that should never be restricted by the call
            limits (ideal for internal or testing numbers). Phone number should
            have a country code (in [E.164](https://en.wikipedia.org/wiki/E.164)
            format)
        disallow_unknown_numbers:
          type: boolean
          default: false
          description: >-
            Only allow incoming calls from the numbers you've sourced using
            IngestSourceConfig.
        dtmf_enabled:
          type: boolean
          default: false
          description: >-
            Allow the agent to accept keypad (DTMF) input during the call. See
            [DTMF input](/guides/inbound/dtmf)
        auto_reschedule:
          type: boolean
          default: false
          description: >-
            Automatically reschedule the call when the user asks to be called
            back at a later time
        welcome_message_delay:
          type: integer
          minimum: 0
          maximum: 1000
          default: 0
          example: 0
          description: >-
            Delay in milliseconds before the agent plays the welcome message
            once the call is connected. Accepts a value between `0` and `1000`
        noise_cancellation_level:
          type: integer
          nullable: true
          minimum: 60
          maximum: 100
          default: null
          example: null
          description: >-
            Level of background noise cancellation applied to the call audio.
            Accepts a value between `60` and `100`. Set to `null` to disable
            noise cancellation
        call_hangup_message:
          nullable: true
          default: null
          example: null
          description: >-
            Final message the agent speaks before disconnecting the call.
            Accepts a string, or a map of language code to message for
            multilingual agents (see [multilingual
            messages](/customizations/auto-switch-multilingual-messages))
          oneOf:
            - type: string
            - type: object
              additionalProperties:
                type: string
        check_if_user_online:
          type: boolean
          default: true
          description: Check whether the user is still on the call when they go silent
        trigger_user_online_message_after:
          type: integer
          default: 10
          example: 10
          description: >-
            Seconds of user silence after which the agent asks whether the user
            is still there. Applicable only when `check_if_user_online` is
            `true`
        voicemail:
          type: boolean
          default: false
          description: >-
            Enable voicemail detection. Agent will automatically disconnect the
            call if voicemail is detected
        voicemail_detection_duration:
          type: number
          format: float
          default: 30
          example: 30
          description: >-
            Time window in seconds from the start of the call during which
            voicemail detection runs. Applicable only when `voicemail` is `true`
        voicemail_check_interval:
          type: number
          format: float
          default: 7
          example: 7
          description: >-
            Minimum time in seconds between two successive voicemail detection
            checks
        voicemail_min_transcript_length:
          type: integer
          default: 7
          example: 7
          description: >-
            Minimum number of words in the transcript before a voicemail
            detection check is run
        voicemail_detection_time:
          type: number
          format: float
          nullable: true
          default: null
          example: null
          description: >-
            Optional override for the voicemail detection timing. Set to `null`
            to use the default behaviour
      type: object
      title: ConversationConfig
    LlmAgentV2:
      properties:
        agent_type:
          type: string
          enum:
            - simple_llm_agent
            - knowledgebase_agent
            - graph_agent
          default: simple_llm_agent
        agent_flow_type:
          type: string
          enum:
            - streaming
          default: streaming
        routes:
          $ref: '#/components/schemas/Routes'
          type: object
          description: Semantic routing layer
        llm_config:
          oneOf:
            - $ref: '#/components/schemas/SimpleLlmAgent'
            - $ref: '#/components/schemas/KnowledgebaseAgent'
          description: LLM configuration
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
    Transcriber:
      oneOf:
        - $ref: '#/components/schemas/DeepgramTranscriberConfig'
        - $ref: '#/components/schemas/SarvamTranscriberConfig'
      type: object
    InputOutput:
      properties:
        provider:
          type: string
          default: plivo
          enum:
            - twilio
            - plivo
            - exotel
        format:
          type: string
          default: wav
          enum:
            - wav
      type: object
      required:
        - provider
        - format
    ApiTools:
      type: object
      properties:
        tools:
          type: array
          items:
            oneOf:
              - $ref: '#/components/schemas/TransferCallTools'
          description: >-
            Description of all the tools you'd like to add to the agent. It
            needs to be a JSON string as this will be passed to LLM.
        tools_params:
          $ref: '#/components/schemas/TransferCallToolParams'
          type: object
          description: >-
            Parameters for each tool, where keys must match the `name` field in
            the `tools` array.
      default: null
    MultilingualConfig:
      type: object
      description: >-
        Multilingual configuration for an agent. When `enabled` is true, Bolna
        keeps a transcriber and synthesizer per language and switches them,
        along with the active system prompt, during the call.
      required:
        - enabled
        - languages
      properties:
        enabled:
          type: boolean
          description: >-
            Must be `true` for multilingual to take effect. When `false` or
            omitted, the agent runs single-language and this object is ignored.
          default: false
          example: true
        active_language:
          type: string
          description: >-
            Language code the agent starts the call in. Must be one of the keys
            in `languages`.
          default: en
          example: en
        languages:
          type: object
          description: >-
            Map of ISO 639-1 language code to its per-language configuration.
            Must contain at least 2 languages.
          minProperties: 2
          additionalProperties:
            $ref: '#/components/schemas/MultilingualLanguageEntry'
          example:
            en:
              synthesizer:
                provider: elevenlabs
                provider_config:
                  voice_id: 21m00Tcm4TlvDq8ikWAM
                  model: eleven_turbo_v2_5
              system_prompt: You are a helpful assistant. Keep replies short.
              agent_name: Alex
            hi:
              transcriber:
                language: hi
              synthesizer:
                provider: sarvam
                provider_config:
                  voice_id: anushka
                  model: bulbul:v2
              system_prompt: आप एक सहायक एजेंट हैं। हिंदी में संक्षेप में उत्तर दें।
              handoff_message: ठीक है, मैं हिंदी में बात करता हूँ।
              agent_name: राज
        switch_tool_description:
          type: string
          description: >-
            Overrides the description of the `switch_language` tool the LLM uses
            to change languages mid-call.
          nullable: true
          example: Switch the conversation language when the caller changes language.
    Routes:
      properties:
        embedding_model:
          type: string
          title: Embedding Model
          default: snowflake/snowflake-arctic-embed-m
          example: snowflake/snowflake-arctic-embed-m
          description: >-
            Since we use fastembed all models supported by fastembed are
            supported by us
        routes:
          items:
            $ref: '#/components/schemas/Route'
          type: array
          title: route
          description: >-
            These are predefined routes that can be used to answer FAQs, or set
            basic guardrails, or do a static function call.
      type: object
      title: Routes
    SimpleLlmAgent:
      title: SimpleLlmAgent
      properties:
        agent_flow_type:
          type: string
          enum:
            - streaming
          default: streaming
        provider:
          type: string
          default: openai
          example: openai
        family:
          type: string
          default: openai
          example: openai
        model:
          type: string
          default: gpt-5.4-mini
          example: gpt-5.4-mini
        summarization_details:
          type: string
          default: null
          example: null
          nullable: true
        extraction_details:
          type: string
          default: null
          example: null
          nullable: true
        max_tokens:
          type: integer
          default: 100
          example: 150
          description: >
            Cap on the tokens generated per response. On GPT-5-series models
            this is sent as `max_completion_tokens`, and reasoning tokens are
            drawn from the same budget, so raise it above the default when
            running `reasoning_effort` higher than `none`/`minimal`.
        temperature:
          type: number
          format: float
          default: 0.1
          example: 1
          description: >
            Sampling temperature. **GPT-5-series models require exactly `1`** —
            any other value is rejected with `400 For GPT-5 models, temperature
            must be 1`. The field defaults to `0.1`, so a GPT-5 agent must send
            `1` explicitly rather than omitting it.
        reasoning_effort:
          type: string
          nullable: true
          default: null
          example: low
          enum:
            - none
            - minimal
            - low
            - medium
            - high
            - xhigh
          description: >
            How much the model reasons before answering. GPT-5-series models
            only. The accepted values differ per model and an unsupported value
            is rejected — see
            [OpenAI](/providers/llm-model/openai#reasoning-effort) for the
            per-model table. Omit it to get the lowest-latency effort the model
            supports, which is what voice agents usually want.
        verbosity:
          type: string
          nullable: true
          default: null
          example: low
          enum:
            - low
            - medium
            - high
          description: >
            How long the model's answers run. GPT-5-series models only. Defaults
            to `low`, which suits voice.
        use_responses_api:
          type: boolean
          default: false
          description: >
            Route the model through OpenAI's Responses API. Always on for
            `gpt-5.4`, `gpt-5.5` and `gpt-5.6` regardless of this field, since
            function calling with `reasoning_effort` is not accepted on chat
            completions for those models.
        compact_threshold:
          type: integer
          nullable: true
          default: null
          description: >
            Token count at which the provider compacts conversation context.
            Applies only when the model runs through the Responses API.
        presence_penalty:
          type: number
          format: float
          default: 0
          example: 0
          description: >-
            Accepted for backwards compatibility. Not sent to OpenAI or Azure
            models.
        frequency_penalty:
          type: number
          format: float
          default: 0
          example: 0
          description: >-
            Accepted for backwards compatibility. Not sent to OpenAI or Azure
            models.
        base_url:
          type: string
          default: https://api.openai.com/v1
          example: https://api.openai.com/v1
        top_p:
          type: number
          format: float
          default: 0.9
          example: 0.9
          description: >-
            Accepted for backwards compatibility. Not sent to OpenAI or Azure
            models.
        min_p:
          type: number
          format: float
          default: 0.1
          example: 0.1
          description: >-
            Accepted for backwards compatibility. Not sent to OpenAI or Azure
            models.
        top_k:
          type: number
          format: integer
          default: 0
          example: 0
          description: >-
            Accepted for backwards compatibility. Not sent to OpenAI or Azure
            models.
        request_json:
          type: boolean
          default: false
      type: object
    KnowledgebaseAgent:
      title: KnowledgebaseAgent
      allOf:
        - type: object
          properties:
            vector_store:
              $ref: '#/components/schemas/VectorStore'
              type: object
              description: >-
                Vector Store for knowledgebase. Use [Knowledgebase
                APIs](/knowledgebase/create) to upload PDFs or URLs. You can
                select multiple knowledgebases using `vector_ids`.
        - $ref: '#/components/schemas/SimpleLlmAgent'
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
    DeepgramTranscriberConfig:
      title: Deepgram
      properties:
        provider:
          type: string
          description: Identification provider for Deepgram
          enum:
            - deepgram
        model:
          enum:
            - nova-3
            - nova-2
            - nova-2-meeting
            - nova-2-phonecall
            - nova-2-finance
            - nova-2-conversationalai
            - nova-2-medical
            - nova-2-drivethru
            - nova-2-automotive
          example: nova-3
        language:
          enum:
            - en
            - hi
            - es
            - fr
          example: hi
        stream:
          type: boolean
          default: true
        sampling_rate:
          type: integer
          default: 16000
          example: 16000
        encoding:
          type: string
          default: linear16
          enum:
            - linear16
        endpointing:
          type: integer
          default: 250
          example: 250
      required:
        - provider
        - model
        - language
    SarvamTranscriberConfig:
      title: Sarvam
      properties:
        provider:
          type: string
          description: Identification provider for Sarvam
          enum:
            - sarvam
        model:
          enum:
            - saarika:v2.5
            - saaras:v2.5
            - saaras:v3
            - saaras:v4
          example: saaras:v4
        language:
          description: Language code, or `unknown` for automatic language detection
          enum:
            - en-IN
            - hi-IN
            - bn-IN
            - ta-IN
            - te-IN
            - gu-IN
            - kn-IN
            - ml-IN
            - mr-IN
            - pa-IN
            - od-IN
            - unknown
          example: hi-IN
        stream:
          type: boolean
          default: true
        sampling_rate:
          type: integer
          default: 16000
          example: 16000
        encoding:
          type: string
          default: linear16
          enum:
            - linear16
        endpointing:
          type: integer
          default: 250
          example: 250
      required:
        - provider
        - model
        - language
    TransferCallTools:
      title: transfer_call
      properties:
        name:
          type: string
          description: Any unique name for this function tool
          example: transfer_call_support
        key:
          type: string
          enum:
            - transfer_call
          default: transfer_call
        description:
          type: string
          description: Use this tool to transfer the call
          example: Use this tool to transfer the call
        parameters:
          type: object
          properties:
            type:
              type: string
              example: object
            properties:
              type: object
              properties:
                call_sid:
                  type: object
                  properties:
                    type:
                      type: string
                      example: string
                    description:
                      type: string
                      description: unique call id
                      example: unique call id
            required:
              type: array
              items:
                type: string
                enum:
                  - call_sid
              example:
                - - call_sid
    TransferCallToolParams:
      type: object
      properties:
        transfer_call_support:
          type: object
          properties:
            method:
              type: string
              enum:
                - POST
                - GET
              default: GET
              description: Type of request
              example: POST
            url:
              type: string
              format: uri
              description: Link of the URL to control the transferring of call
              example: null
              nullable: true
            api_token:
              type: string
              example: null
              nullable: true
              description: API Token in case the URL needs authentication
            param:
              description: Stringified JSON of the tool schema
              type: string
              example: >-
                {"call_transfer_number": "+19876543210","call_sid":
                "%(call_sid)s"}
    MultilingualLanguageEntry:
      type: object
      description: >-
        Per-language configuration. Starts from the base transcriber and
        synthesizer and applies these overrides.
      required:
        - synthesizer
      properties:
        transcriber:
          type: object
          description: >-
            Speech-to-text override for this language. If omitted, the base
            transcriber is reused with this language code applied. Extra
            provider fields (for example `model`, `language_hints`) are allowed.
          required:
            - language
          properties:
            language:
              type: string
              description: Language code for this entry's transcriber.
              example: hi
        synthesizer:
          type: object
          description: >-
            Text-to-speech configuration for this language. Extra provider
            fields are allowed.
          required:
            - provider
            - provider_config
          properties:
            provider:
              type: string
              description: TTS provider for this language.
              example: sarvam
            provider_config:
              type: object
              description: >-
                Provider-specific TTS configuration (for example `voice_id`,
                `model`). For `sarvam`, `smallest`, `cartesia`, `openai`,
                `pixa`, and `polly`, the language is resolved into
                `provider_config.language` automatically.
            buffer_size:
              type: integer
              nullable: true
              description: Optional synthesizer buffer size for this language.
        system_prompt:
          type: string
          description: >-
            Prompt activated while the agent speaks this language. Write it in
            the language's native script.
          nullable: true
        handoff_message:
          type: string
          description: Message played when the agent switches to this language.
          nullable: true
        agent_name:
          type: string
          description: Agent name used while speaking this language.
          nullable: true
    Route:
      properties:
        route_name:
          type: string
          title: Route Name
          example: politics
        utterances:
          items:
            type: string
          type: array
          title: Utterances
          example:
            - Who do you think will win the elections?
            - Whom would you vote for?
          description: >-
            This is an array of utterances which when spoken you want to send a
            static response
        response:
          anyOf:
            - items:
                type: string
              type: array
            - type: string
          example: Hey, thanks but I do not have opinions on politics
          title: Response
          description: >-
            It can be a stand alone string or array of responses. If it's an
            array the length should be same as number of utterances and a
            particular index will be matched before returning
        score_threshold:
          description: Similarity score threshold
          type: number
          title: Score Threshold
          default: 0.85
          example: 0.9
      type: object
      required:
        - route_name
        - utterances
        - response
      title: Route
    VectorStore:
      properties:
        provider:
          type: string
          enum:
            - lancedb
          default: lancedb
          description: Provider vector store database
        provider_config:
          $ref: '#/components/schemas/LanceDbConfig'
          type: object
          description: Configuration of the vector store database
      type: object
      title: VectorStore
    LanceDbConfig:
      properties:
        vector_id:
          type: string
          format: uuid
          description: >-
            Vector id of a single knowledgebase (legacy, use `vector_ids` for
            multiple)
        vector_ids:
          type: array
          items:
            type: string
            format: uuid
          description: Array of vector ids to use multiple knowledgebases simultaneously
          example:
            - 3c90c3cc-0d44-4b50-8822-8dd25736052a
            - 4d91c4dd-1e55-5c61-9933-9ee36847163b
      type: object
      title: LanceDbConfig
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````