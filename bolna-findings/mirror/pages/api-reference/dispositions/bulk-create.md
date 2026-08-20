> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bulk Create Dispositions API

> Atomically create and link multiple dispositions to an agent in a single request.

<Tip>
  Use bulk create when setting up a new agent with a complete set of dispositions, or when importing a disposition configuration from another source. Either all dispositions are created and linked, or none are — partial results are not possible.
</Tip>


## OpenAPI

````yaml POST /dispositions/bulk
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
  /dispositions/bulk:
    post:
      description: >-
        Atomically create and link multiple dispositions to an agent in a single
        request. Either all dispositions are created and linked, or none are.
      requestBody:
        description: Bulk-create dispositions for an agent.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/DispositionBulkCreate'
        required: true
      responses:
        '201':
          description: Dispositions created successfully
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DispositionBulkCreateResponse'
        '403':
          description: Access denied — `agent_id` does not belong to your account
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '422':
          description: >-
            Validation error — empty `dispositions` array or `is_objective`
            without `objective_options`
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '500':
          description: >-
            Failed to create dispositions — transaction rolled back, no
            dispositions were created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    DispositionBulkCreate:
      type: object
      description: >-
        Request body for atomically creating multiple dispositions linked to an
        agent.
      required:
        - agent_id
        - dispositions
      properties:
        agent_id:
          type: string
          format: uuid
          description: The agent all dispositions will be linked to.
        dispositions:
          type: array
          minItems: 1
          description: Non-empty array of disposition objects to create.
          items:
            $ref: '#/components/schemas/DispositionBulkCreateItem'
    DispositionBulkCreateResponse:
      type: object
      description: >-
        Response returned after a successful bulk-create. The `ids` array
        preserves the input order.
      properties:
        message:
          type: string
          example: Dispositions created successfully
        ids:
          type: array
          description: >-
            IDs of the newly created dispositions, in the same order as the
            input `dispositions` array.
          items:
            type: string
            format: uuid
          example:
            - 3fa85f64-5717-4562-b3fc-2c963f66afa6
            - 7cb91a23-1234-4321-b2fc-1c963f11bde4
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
    DispositionBulkCreateItem:
      type: object
      description: A single disposition entry in a bulk-create request.
      required:
        - name
        - question
      properties:
        name:
          type: string
          description: Display name shown in results.
          example: Agent Handover Needed
        question:
          type: string
          description: LLM evaluation prompt.
          example: Did the customer explicitly ask to speak with a human agent?
        category:
          type: string
          description: Grouping label.
          default: General
          example: Escalation
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
        is_objective:
          type: boolean
          description: Enable pre-defined value selection.
          default: false
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
          description: Required when `is_objective` is `true`.
          items:
            $ref: '#/components/schemas/ObjectiveOption'
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