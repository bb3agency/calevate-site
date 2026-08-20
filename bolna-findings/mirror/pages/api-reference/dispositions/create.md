> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Disposition API

> Create a new disposition and link it to an agent in a single request. `agent_id` is required.

<Note>
  At least one of `is_subjective` or `is_objective` must be `true`. When `is_objective` is `true`, you must provide `objective_options`. See the [ObjectiveOption schema](/docs/api-reference/dispositions/overview#objectiveoption-schema) for the full structure including nested `sub_options`.
</Note>


## OpenAPI

````yaml POST /dispositions/
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
    post:
      description: >-
        Create a new disposition and link it to an agent. `agent_id` is required
        and the disposition is automatically linked to that agent upon creation.
      requestBody:
        description: Disposition to create.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/DispositionCreate'
        required: true
      responses:
        '201':
          description: Disposition created successfully
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DispositionCreateResponse'
        '403':
          description: Access denied for the given `agent_id`
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '422':
          description: >-
            Validation error — e.g., `is_objective` is `true` but
            `objective_options` is missing or empty
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
    DispositionCreate:
      type: object
      description: >
        Request body for creating a disposition.


        `agent_id` is required — the disposition is linked to that agent on
        creation. At least one of `is_subjective` or `is_objective` must be
        `true`. When `is_objective` is `true`, `objective_options` is required
        and must be non-empty. When `subjective_type` is `regex`,
        `subjective_type_config` with a `pattern` is required.
      required:
        - agent_id
        - name
        - question
      properties:
        name:
          type: string
          description: Display name shown in results.
          example: Call Outcome
        question:
          type: string
          description: The prompt sent to the LLM to evaluate the transcript.
          example: What was the final outcome of this call?
        category:
          type: string
          description: Grouping label for the disposition.
          default: General
          example: Lead Quality
        agent_id:
          type: string
          format: uuid
          description: The agent the disposition will be linked to on creation.
        system_prompt:
          type: string
          description: Optional system context for the LLM.
        model:
          type: string
          description: LLM model to use for evaluation.
          default: gpt-4.1-mini
          example: gpt-4.1-mini
        is_subjective:
          type: boolean
          description: Enable free-text response.
          default: false
          example: true
        is_objective:
          type: boolean
          description: Enable pre-defined value selection.
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
          description: Required when `subjective_type` is `regex`.
        objective_options:
          type: array
          description: Required when `is_objective` is `true`. Must be non-empty.
          items:
            $ref: '#/components/schemas/ObjectiveOption'
          example:
            - value: interested
              condition: Customer expressed genuine interest and agreed to a next step
            - value: not_interested
              condition: Customer declined or was unresponsive to all proposals
            - value: follow_up
              condition: Customer asked to be contacted again at a later time
    DispositionCreateResponse:
      type: object
      description: >-
        Standard response for create/update/delete operations on a single
        disposition.
      properties:
        message:
          type: string
          example: Disposition created successfully
        id:
          type: string
          format: uuid
          example: 3fa85f64-5717-4562-b3fc-2c963f66afa6
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