> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List Voices

> Get a paginated list of voices for a specific TTS provider and model. Requires provider_id and model_id from the List Providers endpoint.



## OpenAPI

````yaml GET /api/v1/voice-config/tts/voices
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
  /api/v1/voice-config/tts/voices:
    get:
      summary: List voices for a provider and model
      description: >-
        Returns a paginated list of voices available for a specific TTS provider
        and model. Voices include both platform-curated voices and any custom
        voices created by your account.
      parameters:
        - name: language
          in: query
          required: false
          schema:
            type: string
            example: hi
          description: BCP-47 language code to filter voices
        - name: provider_id
          in: query
          required: true
          schema:
            type: string
            format: uuid
            example: 7a3f4573-7548-5b34-80f9-5edf23bed79b
          description: Provider UUID from the `/api/v1/voice-config/tts` response
        - name: model_id
          in: query
          required: true
          schema:
            type: string
            format: uuid
            example: f1b5c9cc-72e1-56a4-be8c-f3ee37d38309
          description: Model UUID from the `/api/v1/voice-config/tts` response
        - name: page
          in: query
          required: false
          schema:
            type: integer
            default: 1
            example: 1
          description: Page number (1-indexed)
        - name: page_size
          in: query
          required: false
          schema:
            type: integer
            default: 100
            example: 100
          description: Number of voices per page
      responses:
        '200':
          description: Paginated list of voices
          content:
            application/json:
              schema:
                type: object
                properties:
                  items:
                    type: array
                    items:
                      $ref: '#/components/schemas/VoiceItem'
              example:
                items:
                  - id: 21d4333d-39f9-5894-8987-f957a664b456
                    provider_id: 7a3f4573-7548-5b34-80f9-5edf23bed79b
                    voice_id: iWNf11sz1GrUE4ppxTOL
                    name: Viraj - Warm, Energetic and Lively
                    gender: male
                    accent: standard
                    age_range: young
                    use_case:
                      - conversational
                    is_native: true
                    preview_url: https://storage.googleapis.com/eleven-public-prod/...
                    source: platform
                  - id: fc092b1c-0f6e-4900-8468-e11133fd95b2
                    provider_id: 7a3f4573-7548-5b34-80f9-5edf23bed79b
                    voice_id: sXlZ9Juk5Ji8sZiFjRUV
                    name: my-custom-voice
                    gender: null
                    accent: null
                    age_range: null
                    use_case: null
                    is_native: false
                    preview_url: null
                    source: custom
        '400':
          description: Missing or invalid parameters
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Access denied
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AccessDenied'
components:
  schemas:
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
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````