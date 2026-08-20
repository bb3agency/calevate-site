> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Make Voice AI Call API

> Learn how to initiate outbound phone calls using Bolna Voice AI agents. Start making phone calls using the agent ID and recipient's phone number.

Places an outbound call from a Bolna agent to a phone number. Returns an `execution_id` you use to track and retrieve the call result.

## Minimal example

Only two fields are required — `agent_id` and `recipient_phone_number`. Omit `from_phone_number` to use your account's default number.

```json Minimal request theme={"system"}
{
  "agent_id": "123e4567-e89b-12d3-a456-426655440000",
  "recipient_phone_number": "+919876543210"
}
```

```json Response theme={"system"}
{
  "message": "done",
  "status": "queued",
  "execution_id": "b7140255-af33-4608-8e97-04dd944b8e48"
}
```

## Realistic example with personalization

Pass `user_data` to inject variables into your agent's prompt and welcome message (e.g. `{customer_name}` in the prompt becomes "Asha"):

```json Request with personalization theme={"system"}
{
  "agent_id": "123e4567-e89b-12d3-a456-426655440000",
  "recipient_phone_number": "+919876543210",
  "from_phone_number": "+918035739222",
  "user_data": {
    "customer_name": "Asha",
    "appointment_day": "Friday"
  }
}
```

## Tracking the call

Use the returned `execution_id` to poll `GET /executions/{execution_id}` for status. The call goes through these stages:

```
queued → initiated → ringing → in-progress → call-disconnected → completed
```

<Warning>
  **Wait for `completed`, not `call-disconnected`.** The `call-disconnected` event fires the instant the line drops, but `conversation_duration`, `total_cost`, `recording_url`, and `extracted_data` are not yet populated. The `completed` event (a few seconds later) has all finalized fields. See [Get Execution](/docs/api-reference/executions/get_execution).
</Warning>

## Common 400 errors

| Message                              | Fix                                                     |
| ------------------------------------ | ------------------------------------------------------- |
| `agent_id is required`               | Include a valid UUID `agent_id`                         |
| `recipient_phone_number is required` | Phone number must be E.164 format, e.g. `+919876543210` |
| Invalid `from_phone_number`          | Must be a number purchased in your Bolna account        |


## OpenAPI

````yaml POST /call
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
  /call:
    post:
      description: Initiate calls
      requestBody:
        description: Make a phone call from agent
        content:
          application/json:
            schema:
              required:
                - agent_id
                - recipient_phone_number
              properties:
                agent_id:
                  type: string
                  format: uuid
                  description: Agent `id` which will initiate the outbound call
                recipient_phone_number:
                  type: string
                  description: >-
                    Phone number of the recipient along with country code (in
                    [E.164](https://en.wikipedia.org/wiki/E.164) format)
                from_phone_number:
                  type: string
                  description: >-
                    Phone number of the sender along with country code (in
                    [E.164](https://en.wikipedia.org/wiki/E.164) format).
                    Optional — if omitted, Bolna uses the account's default
                    number.
                scheduled_at:
                  type: string
                  example: '2024-06-05T16:35:00.000+05:30'
                  description: >-
                    The scheduled date and time in ISO 8601 format with time
                    zone
                user_data:
                  type: object
                  description: >-
                    Additional user dynamic variables as defined in the agent
                    prompt
                  additionalProperties: true
                agent_data:
                  type: object
                  description: >-
                    Agent configuration to override the default configuration.
                    Currently, only `voice_id` for the same provider is
                    supported.
                retry_config:
                  type: object
                  description: >-
                    Configuration for auto-retry of failed calls. See
                    [auto-retry documentation](/auto-retry) for details.
                  properties:
                    enabled:
                      type: boolean
                      default: false
                      description: Enable auto-retry for this call
                    max_retries:
                      type: integer
                      minimum: 1
                      maximum: 3
                      default: 3
                      description: Maximum retry attempts (1-3)
                    retry_on_statuses:
                      type: array
                      items:
                        type: string
                        enum:
                          - no-answer
                          - busy
                          - failed
                          - error
                      default:
                        - no-answer
                        - busy
                        - failed
                      description: Call statuses that trigger a retry
                    retry_on_voicemail:
                      type: boolean
                      default: false
                      description: Whether to retry if call reaches voicemail
                    retry_intervals_minutes:
                      type: array
                      items:
                        type: integer
                      default:
                        - 30
                        - 60
                        - 120
                      description: Delay in minutes before each retry attempt
                bypass_call_guardrails:
                  type: boolean
                  default: false
                  description: >-
                    Skip time validation checks and make call immediately
                    regardless of agent's calling_guardrails configuration
            examples:
              example-1:
                summary: Example of initiating a call
                value:
                  agent_id: 123e4567-e89b-12d3-a456-426655440000
                  recipient_phone_number: '+10123456789'
                  from_phone_number: '+19876543007'
                  scheduled_at: '2025-08-21T10:35:00+00:00'
                  user_data:
                    variable1: value1
                    variable2: value2
                    variable3: some phrase as value
                  agent_data:
                    voice_id: Sam
        required: true
      responses:
        '200':
          description: agent status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MakeCallStatus'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    MakeCallStatus:
      properties:
        message:
          type: string
          example: done
          description: Response message for the call initiated
        status:
          type: string
          enum:
            - queued
          example: queued
          description: Status of the call.
        execution_id:
          pattern: >-
            ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}
          type: string
          example: 123e4567-e89b-12d3-a456-426614174000
          description: Unique `execution_id` or `call_id` identifier of the call.
      type: object
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