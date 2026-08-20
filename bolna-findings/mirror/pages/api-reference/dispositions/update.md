> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Disposition API

> Update a disposition. When scoped to an agent, shared dispositions are copied before editing to protect other agents.

## Scoped vs. Unscoped Mode

### Scoped mode (recommended) — `agent_id` provided

The API checks whether the disposition is **exclusive** to the specified agent (i.e., not shared with other agents):

* **Case 1: Disposition is exclusive to this agent → Edit in place.** Returns `200 OK`.
* **Case 2: Disposition is shared → Copy-on-write.** A new private copy is created for this agent, and the agent is re-linked to the copy. The original disposition is unchanged. Returns `201 Created`.

<Warning>
  A `201` response means a **new disposition ID was created**. If you're storing the disposition ID (e.g., in your own database), update your reference to the new ID returned in the response. The original `disposition_id` now belongs to other agents; your agent uses the new copy.
</Warning>

### Unscoped mode — no `agent_id`

* Admins can update any disposition in place.
* Non-admin users can only update dispositions they own.


## OpenAPI

````yaml PUT /dispositions/{disposition_id}
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
  /dispositions/{disposition_id}:
    put:
      description: >
        Update an existing disposition. All fields in the request body are
        optional — only fields you include are changed.


        When `agent_id` is provided (scoped mode), the API checks whether the
        disposition is exclusive to that agent:

        - If exclusive, it is edited in place and `200 OK` is returned.

        - If shared, a new private copy is created for this agent and the agent
        is re-linked to the copy; the original disposition is unchanged and `201
        Created` is returned with the new ID.


        When `agent_id` is not provided (unscoped mode), admins can update any
        disposition; non-admin users can only update dispositions they own.
      parameters:
        - in: path
          name: disposition_id
          required: true
          schema:
            type: string
            format: uuid
          description: The ID of the disposition to update.
      requestBody:
        description: Fields to update on the disposition.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/DispositionUpdate'
        required: true
      responses:
        '200':
          description: Disposition updated in place
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DispositionCreateResponse'
              example:
                message: Disposition updated successfully
                id: 3fa85f64-5717-4562-b3fc-2c963f66afa6
        '201':
          description: >-
            Copy-on-write — a new disposition copy was created and linked to the
            agent
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DispositionCreateResponse'
              example:
                message: Disposition copy created and linked to agent
                id: 9ab12c34-5678-4321-b3fc-7d852f33caf1
        '400':
          description: No valid fields provided to update
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '403':
          description: Access denied
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '404':
          description: Disposition not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '422':
          description: Validation error
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
    DispositionUpdate:
      type: object
      description: >-
        Request body for updating a disposition. All fields are optional — only
        included fields are changed.
      properties:
        agent_id:
          type: string
          format: uuid
          description: If provided, enables scoped (copy-on-write) mode.
        name:
          type: string
          description: New display name.
          example: Next Step Agreed
        question:
          type: string
          description: Updated LLM evaluation prompt.
        category:
          type: string
          description: New category label.
          example: Conversion
        system_prompt:
          type: string
          description: Updated LLM system context.
        model:
          type: string
          description: Updated LLM model.
          example: gpt-4.1-mini
        is_subjective:
          type: boolean
          description: Enable or disable free-text response.
        is_objective:
          type: boolean
          description: Enable or disable pre-defined value selection.
        subjective_type:
          type: string
          description: Format constraint for free-text responses.
          enum:
            - text
            - timestamp
            - numeric
            - boolean
            - email
            - regex
        subjective_type_config:
          allOf:
            - $ref: '#/components/schemas/SubjectiveTypeConfig'
          nullable: true
          description: Configuration for the `regex` subjective type.
        objective_options:
          type: array
          description: Updated list of pre-defined options.
          items:
            $ref: '#/components/schemas/ObjectiveOption'
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