> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List all Voice AI Agents API (deprecated)

> List all Voice AI agents under your account, along with their names, statuses, and creation dates, using Bolna APIs.

<Warning>
  These APIs have now been deprecated.

  Please use the latest [**v2 APIs**](/docs/api-reference/agent/v2/overview).
</Warning>


## OpenAPI

````yaml GET /agent/all
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
  /agent/all:
    get:
      description: List all agents
      responses:
        '200':
          description: List of agents
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AgentList'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    AgentList:
      items:
        $ref: '#/components/schemas/Agent'
      type: array
      title: Items
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
    Agent:
      properties:
        id:
          type: string
          format: uuid
          description: Unique identifier for the agent
        agent_name:
          description: Human-readable agent name
          type: string
          example: Alfred
        agent_type:
          description: Type of agent
          type: string
          example: other
        agent_status:
          description: Current status of the agent
          type: string
          enum:
            - seeding
            - processed
          example: processed
        created_at:
          type: string
          format: date-time
          example: '2024-01-23T01:14:37Z'
          description: Timestamp of agent creation
        updated_at:
          type: string
          format: date-time
          example: '2024-01-29T18:31:22Z'
          description: Timestamp of last update for the agent
        tasks:
          items:
            $ref: '#/components/schemas/TasksConfig'
          type: array
          description: An array of tasks that the agent can perform
        agent_prompts:
          $ref: '#/components/schemas/AgentPrompt'
          description: >-
            Prompts to be provided to the agent. It can have multiple tasks of
            the form `task_<task_id>`
      type: object
    TasksConfig:
      properties:
        task_type:
          type: string
          description: Type of task
          enum:
            - conversation
            - extraction
            - summarization
            - webhook
        tools_config:
          $ref: '#/components/schemas/ToolsConfig'
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
    ToolsConfig:
      properties:
        llm_agent:
          $ref: '#/components/schemas/LlmAgent'
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
    LlmAgent:
      properties:
        model:
          type: string
          default: gpt-4.1-mini
          example: gpt-4.1-mini
        max_tokens:
          type: integer
          default: 350
        agent_flow_type:
          type: string
          enum:
            - streaming
            - preprocessed
          default: streaming
        family:
          type: string
          default: openai
          example: openai
        provider:
          type: string
          default: openai
          example: openai
        base_url:
          type: string
          default: null
          example: https://api.openai.com/v1
        temperature:
          type: number
          default: 0.1
          example: 0.3
        request_json:
          type: boolean
          default: false
        routes:
          $ref: '#/components/schemas/Routes'
          type: object
          description: Semantic routing layer
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
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````