> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List TTS Providers and Models

> Get all supported TTS providers and their models for a given language. Returns provider IDs and model IDs needed to fetch voices.



## OpenAPI

````yaml GET /api/v1/voice-config/tts
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
  /api/v1/voice-config/tts:
    get:
      summary: List TTS providers and models
      description: >-
        Returns all TTS providers with their supported models for a given
        language. Use this to discover available providers and their model IDs
        before fetching voices.
      parameters:
        - name: language
          in: query
          required: false
          schema:
            type: string
            example: hi
          description: >-
            BCP-47 language code to filter providers by language support (e.g.
            `en`, `hi`, `ta`). Omit for all languages.
      responses:
        '200':
          description: TTS provider and model configuration
          content:
            application/json:
              schema:
                type: object
                properties:
                  language:
                    type: string
                    example: hi
                  providers:
                    type: array
                    items:
                      $ref: '#/components/schemas/TTSProvider'
                  custom_voices:
                    type: object
                    description: >-
                      Map of provider_id to array of custom voices created by
                      the account
                    additionalProperties:
                      type: array
                      items:
                        $ref: '#/components/schemas/VoiceItem'
                  default:
                    type: string
                    nullable: true
                    description: Default provider ID for this account, if set
              example:
                language: hi
                providers:
                  - id: 7a3f4573-7548-5b34-80f9-5edf23bed79b
                    name: ElevenLabs
                    is_supported: true
                    models:
                      - id: f1b5c9cc-72e1-56a4-be8c-f3ee37d38309
                        model_id: eleven_turbo_v2_5
                        display_name: Eleven Turbo v2.5
                        description: Our high quality, low latency model in 32 languages.
                        display_order: 3
                        quality_tier: turbo
                        is_supported: true
                        default: false
                  - id: 9e675bdf-00e5-5bd5-b858-f1b088a48dbd
                    name: Sarvam
                    is_supported: true
                    models:
                      - id: 5d82c5f4-458f-5ff6-ae2b-a5e692b77a2c
                        model_id: bulbul:v3
                        display_name: Bulbul v3
                        description: >-
                          Latest Sarvam TTS model with 30+ speakers, pace
                          control, and temperature control.
                        display_order: 1
                        quality_tier: standard
                        is_supported: true
                        default: false
                custom_voices: {}
                default: null
        '401':
          description: Access denied
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AccessDenied'
components:
  schemas:
    TTSProvider:
      type: object
      properties:
        id:
          type: string
          format: uuid
          description: Provider UUID (use as `provider_id` when fetching voices)
        name:
          type: string
          example: ElevenLabs
        is_supported:
          type: boolean
          description: Whether this provider is available for your account
        models:
          type: array
          items:
            $ref: '#/components/schemas/TTSModel'
    VoiceItem:
      type: object
      properties:
        id:
          type: string
          format: uuid
          description: Internal voice UUID
        provider_id:
          type: string
          format: uuid
          description: UUID of the provider this voice belongs to
        voice_id:
          type: string
          description: Provider-specific voice identifier (use this in agent config)
          example: iWNf11sz1GrUE4ppxTOL
        name:
          type: string
          example: Viraj - Warm, Energetic and Lively
        gender:
          type: string
          nullable: true
          example: male
        accent:
          type: string
          nullable: true
          example: standard
        age_range:
          type: string
          nullable: true
          example: young
        use_case:
          type: array
          nullable: true
          items:
            type: string
          example:
            - conversational
        is_native:
          type: boolean
          description: Whether this is a natively curated voice on the platform
        preview_url:
          type: string
          nullable: true
          format: uri
          description: URL to a short audio preview of the voice
        source:
          type: string
          enum:
            - platform
            - custom
          description: >-
            `platform` = curated by Bolna; `custom` = cloned/added by your
            account
    AccessDenied:
      required:
        - error
        - message
      type: object
      properties:
        error:
          type: integer
          format: int32
          example: 401
        message:
          type: string
          example: Access denied
    TTSModel:
      type: object
      properties:
        id:
          type: string
          format: uuid
          description: Internal model UUID
        model_id:
          type: string
          description: Provider-specific model identifier (use this in agent config)
          example: eleven_turbo_v2_5
        display_name:
          type: string
          example: Eleven Turbo v2.5
        description:
          type: string
          nullable: true
        display_order:
          type: integer
        quality_tier:
          type: string
          nullable: true
          example: turbo
        is_supported:
          type: boolean
        is_deprecated:
          type: boolean
        default:
          type: boolean
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````