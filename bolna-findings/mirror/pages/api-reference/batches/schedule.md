> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Schedule Batch API

> Learn how to schedule a batch for calling via Bolna Voice AI agent by specifying the batch ID and the desired execution time.



## OpenAPI

````yaml POST /batches/{batch_id}/schedule
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
  /batches/{batch_id}/schedule:
    post:
      description: Schedule a batch for calling via agent
      parameters:
        - in: path
          name: batch_id
          required: true
          description: The ID of the batch
          schema:
            type: string
            format: uuid
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                scheduled_at:
                  type: string
                  example: '2026-06-23T18:30:00.000Z'
                  description: >-
                    The scheduled date and time in ISO 8601 format with a
                    numeric UTC offset (e.g. `+00:00`). **Important:** The `Z`
                    suffix is not accepted and returns a 500 — always use a
                    numeric offset like `+00:00`. The time must be at most 30
                    days in the future from the current date (later values
                    return a 400).
                bypass_call_guardrails:
                  type: boolean
                  default: false
                  description: Skip time validation for all calls in this batch
              required:
                - scheduled_at
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              example:
                message: success
                state: scheduled
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
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