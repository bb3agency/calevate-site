> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Get All Sub-Accounts Usage API

> Retrieve usage, consumption, and billing details for all sub-accounts under the authenticated organization.

<Note>
  This is an `enterprise` feature.

  You can read more about our enterprise offering here [Bolna enterprise](/docs/enterprise/plan).
</Note>

## Summary

This endpoint returns aggregated usage data for **all sub-accounts** associated with the authenticated user's organization.\
It provides fine-grained insight into usage, consumption, and cost breakdowns for each sub-account.

## Endpoint

```yaml theme={"system"}
GET /sub-accounts/all/usage
```


## OpenAPI

````yaml GET /sub-accounts/all/usage
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
  /sub-accounts/all/usage:
    get:
      description: >-
        Retrieve usage details for all sub-accounts under the authenticated
        organization for up to 32 days.
      parameters:
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
          description: Get usage details for all sub-accounts, including cost breakdown.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AllSubAccountUsage'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    AllSubAccountUsage:
      type: array
      description: >-
        A list of usage data objects, with each object providing a breakdown for
        a single sub-account.
      items:
        type: object
        title: Sub-account usage details
        properties:
          from:
            type: string
            format: date
            description: >-
              The starting timestamp (in ISO 8601 UTC format) to calculate
              usage.
          to:
            type: string
            format: date-time
            description: The ending timestamp (in ISO 8601 UTC format) to calculate usage.
          total_records:
            type: integer
            description: Total numbers of executions.
          total_duration:
            type: number
            format: float
            description: Total duration in seconds.
          total_cost:
            type: number
            format: float
            description: Total cumulative cost of executions **in cents**.
          total_platform_cost:
            type: number
            format: float
            description: Total cumulative platform cost of executions **in cents**.
          total_telephony_cost:
            type: number
            format: float
            description: Total cumulative telephony cost of executions **in cents**.
          status_map:
            type: object
            description: |
              A map of call status with their counts.
            additionalProperties:
              type: integer
          synthesizer_cost_map:
            type: object
            additionalProperties:
              type: object
              additionalProperties:
                type: object
                properties:
                  characters:
                    type: number
                  cost:
                    type: number
          transcriber_cost_map:
            type: object
            additionalProperties:
              type: object
              additionalProperties:
                type: object
                properties:
                  duration:
                    type: number
                  cost:
                    type: number
          llm_cost_map:
            type: object
            properties:
              cost:
                type: number
              tokens:
                type: object
          sub_account_id:
            type: string
            format: uuid
            description: Unique identifier for the sub-account.
          sub_account_name:
            type: string
            description: Human-readable name of the sub-account.
      example:
        - from: '2025-09-01T00:00:00'
          to: '2025-09-25T23:59:59.999999'
          total_records: 0
          total_duration: 0
          total_cost: 0
          total_platform_cost: 0
          total_telephony_cost: 0
          status_map: {}
          synthesizer_cost_map: {}
          transcriber_cost_map: {}
          llm_cost_map:
            cost: 0
            tokens: {}
          sub_account_id: 5416892b-9052-47d6-92e3-85ac51426903
          sub_account_name: test-one
        - from: '2025-09-01T00:00:00'
          to: '2025-09-25T23:59:59.999999'
          total_records: 7
          total_duration: 22
          total_cost: 4.864
          total_platform_cost: 4
          total_telephony_cost: 0.826
          status_map:
            busy: 5
            completed: 2
          synthesizer_cost_map:
            elevenlabs:
              eleven_turbo_v2_5:
                characters: 129
                cost: 0
          transcriber_cost_map:
            deepgram:
              nova-2:
                duration: 15.199938
                cost: 0
          llm_cost_map:
            cost: 0.038
            tokens:
              gpt-4o-mini:
                input: 17
                output: 127
          sub_account_id: 33204bca-0902-4b90-b6d2-6ee0b65e7ef9
          sub_account_name: test-2
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