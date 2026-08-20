> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Test Dispositions API

> Test all dispositions linked to an agent against a transcript to preview results before live calls.

Runs **all dispositions linked to the specified agent** against a provided transcript and returns the grouped results. Useful for validating your disposition setup before going live.

The response `extracted_data` is grouped by category and disposition name, in the same format as post-call execution data.


## OpenAPI

````yaml POST /v2/agent/{agent_id}/dispositions/test
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
  /v2/agent/{agent_id}/dispositions/test:
    post:
      description: >-
        Run all dispositions linked to the specified agent against a provided
        transcript and return the grouped results. Useful for validating your
        disposition setup before going live.
      parameters:
        - in: path
          name: agent_id
          required: true
          schema:
            type: string
            format: uuid
          description: The agent whose dispositions will be evaluated.
      requestBody:
        description: Transcript to evaluate against the agent's dispositions.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/DispositionTestRequest'
        required: true
      responses:
        '200':
          description: Grouped disposition results
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DispositionTestResponse'
        '403':
          description: Access denied — agent does not belong to your account
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '404':
          description: Invalid or unknown `agent_id`
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
    DispositionTestRequest:
      type: object
      description: Request body for testing an agent's dispositions against a transcript.
      required:
        - transcript
      properties:
        transcript:
          type: string
          maxLength: 50000
          description: The call transcript to run dispositions against.
          example: >-
            Agent: Hi, how can I help you today? Customer: I am interested in
            your enterprise plan and would like to know more about pricing.
        call_date:
          type: string
          format: date-time
          description: Optional ISO 8601 date/datetime string for temporal context.
          example: '2026-04-01T10:00:00Z'
    DispositionTestResponse:
      type: object
      description: >-
        Grouped disposition results in the same format as post-call execution
        data.
      properties:
        extracted_data:
          type: object
          description: >-
            Results grouped by category and disposition name. Each leaf contains
            `subjective` (free-text) and/or `objective` (pre-defined value)
            fields.
          additionalProperties:
            type: object
            additionalProperties:
              type: object
              properties:
                subjective:
                  type: string
                objective:
                  type: string
          example:
            Lead Quality:
              Call Outcome:
                subjective: >-
                  Customer expressed strong interest and asked about enterprise
                  pricing.
                objective: interested
            Escalation:
              Agent Handover Needed:
                subjective: ''
                objective: 'No'
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
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````