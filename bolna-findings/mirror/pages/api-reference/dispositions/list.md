> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List Dispositions API

> Retrieve all dispositions accessible to your account, optionally scoped to a specific agent.



## OpenAPI

````yaml GET /dispositions/
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
  /dispositions/:
    get:
      description: >-
        List dispositions accessible to your account. When `agent_id` is
        provided, only dispositions linked to that agent are returned; otherwise
        all dispositions you own are returned.
      parameters:
        - in: query
          name: agent_id
          required: false
          schema:
            type: string
            format: uuid
          description: If provided, returns only dispositions linked to this agent.
      responses:
        '200':
          description: List of dispositions
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/Disposition'
        '403':
          description: Access denied — `agent_id` does not belong to your account
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '500':
          description: Internal server error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    Disposition:
      type: object
      description: >-
        An LLM-powered post-call classifier that labels call outcomes from
        transcripts.
      properties:
        id:
          type: string
          format: uuid
          description: Unique identifier for the disposition.
          example: 3fa85f64-5717-4562-b3fc-2c963f66afa6
        name:
          type: string
          description: Display name shown in results.
          example: Call Outcome
        question:
          type: string
          description: The prompt sent to the LLM to evaluate the transcript.
          example: What was the outcome of the call?
        system_prompt:
          type: string
          nullable: true
          description: Optional system context for the LLM.
          example: You are analyzing a sales call transcript.
        category:
          type: string
          description: Grouping label for the disposition.
          default: General
          example: Lead Quality
        model:
          type: string
          description: LLM model used for evaluation.
          default: gpt-4.1-mini
          example: gpt-4.1-mini
        is_subjective:
          type: boolean
          description: Enables free-text response.
          default: false
          example: true
        is_objective:
          type: boolean
          description: Enables pre-defined value selection.
          default: false
          example: true
        subjective_type:
          type: string
          description: >-
            Format constraint for free-text responses. Only allowed when
            `is_subjective` is `true`.
          enum:
            - text
            - timestamp
            - numeric
            - boolean
            - email
            - regex
          default: text
        subjective_type_config:
          allOf:
            - $ref: '#/components/schemas/SubjectiveTypeConfig'
          nullable: true
          description: >-
            Configuration for the `regex` subjective type. Required when
            `subjective_type` is `regex`.
        objective_options:
          type: array
          nullable: true
          description: Pre-defined options. Required when `is_objective` is `true`.
          items:
            $ref: '#/components/schemas/ObjectiveOption'
        agent_ids:
          type: array
          description: List of agent IDs this disposition is linked to.
          items:
            type: string
          example:
            - agt_abc123
        created_by:
          type: string
          description: ID of the user who created this disposition.
          example: user_abc123
        created_at:
          type: string
          format: date-time
          description: ISO timestamp when the disposition was created.
          example: '2026-03-01T10:00:00Z'
        updated_at:
          type: string
          format: date-time
          description: ISO timestamp when the disposition was last updated.
          example: '2026-03-15T14:30:00Z'
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
    SubjectiveTypeConfig:
      type: object
      description: >-
        Configuration for the `regex` subjective type. Required when
        `subjective_type` is `regex`.
      required:
        - pattern
      properties:
        pattern:
          type: string
          description: The regular expression the free-text response must match.
          example: ^\d{10}$
        description:
          type: string
          description: Optional human-readable description of the expected format.
          example: 10-digit phone number
    ObjectiveOption:
      type: object
      description: >-
        A pre-defined option for an objective disposition. Supports recursive
        `sub_options` for hierarchical classifications.
      required:
        - value
        - condition
      properties:
        value:
          type: string
          description: The value returned when this option is selected.
          example: interested
        condition:
          type: string
          description: >-
            Natural-language condition describing when this option should be
            selected.
          example: Customer expressed genuine interest and agreed to a next step
        sub_options:
          type: array
          description: >-
            Optional nested options for hierarchical classifications. Each item
            has the same structure as `ObjectiveOption`.
          items:
            $ref: '#/components/schemas/ObjectiveOption'
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````