> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Track Sub-Account Usage API

> Track usage for a specific sub-account giving you fine-grained insights into usage, consumption and billing.

<Note>
  This is an `enterprise` feature.

  You can read more about our enterprise offering here [Bolna enterprise](/docs/enterprise/plan).
</Note>


## OpenAPI

````yaml GET /sub-accounts/{sub_account_id}/usage
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
  /sub-accounts/{sub_account_id}/usage:
    get:
      description: Track usage for the sub-account upto 32 days
      parameters:
        - in: path
          name: sub_account_id
          required: true
          schema:
            type: string
            format: uuid
          description: The unique identifier of the sub-account.
        - in: query
          name: from
          required: false
          schema:
            type: string
            format: date-time
          description: >-
            The start timestamp (in ISO 8601 UTC format) from which to calculate
            usage. If not provided, the start of the current month (UTC) is used
            by default.
        - in: query
          name: to
          required: false
          schema:
            type: string
            format: date-time
          description: >-
            The end timestamp in ISO 8601 UTC format up to which usage is
            calculated. If not provided, the end of the current date (in UTC)
            will be used.
      responses:
        '200':
          description: Get all usage details for the sub-account
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SubAccountUsage'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    SubAccountUsage:
      type: object
      properties:
        from:
          type: string
          format: date
          example: '2025-06-25'
          description: The starting timestamp (in ISO 8601 UTC format) to calculate usage
        to:
          type: string
          format: date-time
          example: '2025-06-27T23:59:59.999999'
          description: The ending timestamp (in ISO 8601 UTC format) to calculate usage
        total_records:
          type: integer
          example: 12
          description: Total numbers of executions
        total_duration:
          type: number
          format: float
          description: Total duration in seconds
          example: 151
        total_cost:
          type: number
          format: float
          example: 31.754
          description: Total cumulative cost of executions **in cents**
        total_platform_cost:
          type: number
          format: float
          example: 22
          description: Total cumulative platform cost of executions **in cents**
        total_telephony_cost:
          type: number
          format: float
          example: 2.673
          description: Total cumulative telephony cost of executions **in cents**
        status_map:
          type: object
          description: |
            A map of call status with their counts. Valid status keys include:
            - scheduled
            - queued
            - rescheduled
            - initiated
            - ringing
            - in-progress
            - call-disconnected
            - completed
            - balance-low
            - busy
            - no-answer
            - canceled
            - failed
            - stopped
            - error
          additionalProperties:
            type: integer
          example:
            completed: 11
            no-answer: 1
        synthesizer_cost_map:
          type: object
          example:
            elevenlabs:
              eleven_turbo_v2_5:
                characters: 577
                cost: 5.77
          additionalProperties:
            type: object
            additionalProperties:
              type: object
              properties:
                characters:
                  type: number
                  example: 577
                cost:
                  type: number
                  example: 5.77
        transcriber_cost_map:
          type: object
          example:
            deepgram:
              nova-2:
                duration: 125.5993724
                cost: 1.233
          additionalProperties:
            type: object
            additionalProperties:
              type: object
              properties:
                duration:
                  type: number
                  example: 125.5993724
                cost:
                  type: number
                  example: 1.233
        llm_cost_map:
          type: object
          properties:
            cost:
              type: number
              example: 0.078
            tokens:
              type: object
              example:
                gpt-4o-mini:
                  input: 2698
                  output: 605
              additionalProperties:
                type: object
                properties:
                  input:
                    type: integer
                    example: 2698
                  output:
                    type: integer
                    example: 605
      title: Sub-account usage details
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