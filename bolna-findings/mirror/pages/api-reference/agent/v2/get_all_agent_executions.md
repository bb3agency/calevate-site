> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Get All Voice AI Agent Executions API

> Access all execution records for a specific agent, providing insights into performance and past interactions with Bolna APIs.

## Pagination

This API supports pagination using the `page_number` and `page_size` query parameters. You can utilize `has_more` in the API response to determine if you should fetch the next page. You can learn more about it from the [pagination documentation](/docs/api-reference/pagination).

## Date filtering

<Warning>
  The `from` and `to` query parameters are **required** to filter executions by date.
</Warning>

You can filter executions by their `created_at` timestamp using the `from` and `to` query parameters. The following rules apply:

* Both `from` and `to` are **required** and must be passed **together**.
* The maximum allowed range between `from` and `to` is **7 days**.
* Dates must be in **UTC ISO 8601** format (e.g. `2026-06-07T00:00:00.000Z`).


## OpenAPI

````yaml GET /v2/agent/{agent_id}/executions
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
  /v2/agent/{agent_id}/executions:
    get:
      description: Retrieve all executions by an agent
      parameters:
        - in: path
          name: agent_id
          required: true
          schema:
            type: string
            format: uuid
          description: The unique `id` of the agent
        - in: query
          name: page_number
          required: false
          schema:
            type: integer
            default: 1
            minimum: 1
          description: The page number to retrieve (starts from `1`)
        - in: query
          name: page_size
          required: false
          schema:
            type: integer
            default: 20
            minimum: 1
          description: Number of results per page. Maximum allowed is `50`.
        - in: query
          name: status
          required: false
          schema:
            type: string
            enum:
              - scheduled
              - queued
              - rescheduled
              - ringing
              - initiated
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
            description: >-
              Fetch executions filtered by call status. [List of all call
              statuses](/list-phone-call-status).
        - in: query
          name: call_type
          required: false
          schema:
            type: string
            enum:
              - inbound
              - outbound
            description: Filter `inbound` calls or `outbound` calls.
        - in: query
          name: provider
          required: false
          schema:
            type: string
            enum:
              - plivo
              - twilio
              - websocket
              - web-call
            description: Filter by conversation provider.
        - in: query
          name: answered_by_voice_mail
          required: false
          schema:
            type: boolean
            default: false
            description: Filter by voicemail.
        - in: query
          name: batch_id
          required: false
          schema:
            type: string
            default: null
            description: Filter executions by a specific `batch_id`.
        - in: query
          name: from
          required: true
          schema:
            type: string
            format: date-time
            example: '2025-05-07T00:00:00.000Z'
            description: >-
              Fetch executions where the `created_at` timestamp is greater than
              or equal to this UTC datetime in ISO 8601 format with UTC
              indication. **Required** — `from` and `to` must be passed
              together, and the range between them cannot exceed 7 days.
        - in: query
          name: to
          required: true
          schema:
            type: string
            format: date-time
            example: '2025-05-14T00:00:00.000Z'
            description: >-
              Fetch executions where the `created_at` timestamp is less than or
              equal to this UTC datetime in ISO 8601 format with UTC indication.
              **Required** — `from` and `to` must be passed together, and the
              range between them cannot exceed 7 days.
      responses:
        '200':
          description: List of all executions by an agent sorted by last run
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AgentExecutionV2List'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    AgentExecutionV2List:
      properties:
        page_number:
          type: number
          format: integer
          description: >-
            The current page number returned in the response. Matches the
            `page_number` requested in the query.
        page_size:
          type: number
          format: integer
          description: >-
            The number of records returned per page. Matches the `page_size`
            specified in the request.
        total:
          type: number
          format: integer
          description: Number of total executions
        has_more:
          type: boolean
          description: Whether there are more records or not
        data:
          items:
            $ref: '#/components/schemas/AgentExecution'
          type: array
      title: Items
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
    AgentExecution:
      properties:
        id:
          type: string
          format: uuid
          example: 4c06b4d1-4096-4561-919a-4f94539c8d4a
          description: Unique identifier for the execution
        agent_id:
          type: string
          format: uuid
          description: Unique `id` of the agent
        batch_id:
          type: string
          pattern: ^[a-f0-9]{32}$
          example: baab7cdc833145bf8dd260ff1f0a3f21
          description: Unique `id` of the batch
        conversation_duration:
          type: number
          format: float
          description: Total time duration for the conversation (in seconds)
        total_cost:
          type: number
          format: float
          description: Total cost incurred by this execution in cents
        status:
          type: string
          enum:
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
          description: >-
            Current status of the call. Typical progression: `queued → initiated
            → ringing → in-progress → call-disconnected → completed`.
            **Important:** `call-disconnected` fires the instant the line drops,
            before duration, cost, recording URL, and extracted_data are
            finalized. The true terminal state is `completed` (or `no-answer`,
            `busy`, `failed`, `canceled`, `stopped`, `error`, `balance-low`).
            Always wait for `completed` before reading those fields.
        error_message:
          type: string
          description: Associated error message (if any)
        answered_by_voice_mail:
          type: boolean
          description: If the call was answered by voice mail
        transcript:
          type: string
          description: Transcription of the execution
        created_at:
          type: string
          format: date-time
          example: '2024-01-23T01:14:37Z'
          description: Timestamp of agent execution
        updated_at:
          type: string
          format: date-time
          example: '2024-01-29T18:31:22Z'
          description: Last updated timestamp for the execution
        cost_breakdown:
          $ref: '#/components/schemas/CostBreakdown'
          description: Breakdown of the costs in cents
        telephony_data:
          $ref: '#/components/schemas/TelephonyData'
          description: Telephony call data
        transfer_call_data:
          $ref: '#/components/schemas/TransferCallData'
          description: Telephony call data
        batch_run_details:
          $ref: '#/components/schemas/BatchRunData'
          description: Batch information
        extracted_data:
          type: object
          nullable: true
          description: >-
            Extracted data in JSON format which was mentioned in the agent
            `extraction_prompt`
          example:
            user_interested: true
            callback_user: false
            address: 42 world lane
            salary_expected: 42 bitcoins
        context_details:
          type: object
          description: >-
            Custom variable data injected in the call. For batch executions, the
            sub-object `context_details.recipient_data` contains every
            non-`contact_number` column from the uploaded CSV row (e.g.
            `{"customer_name": "Asha", "appointment_day": "Friday"}`).
      type: object
    CostBreakdown:
      properties:
        llm:
          type: number
          format: float
          description: Total cost incurred by the LLM in cents
          example: 4.2
        network:
          type: number
          format: float
          description: Total telephony cost in cents
          example: 1.2
        platform:
          type: number
          format: float
          description: Bolna platform cost in cents
          example: 2
        synthesizer:
          type: number
          format: float
          description: Total cost incurred by the Synthesizer provider in cents
          example: 6.8
        transcriber:
          type: number
          format: float
          description: Total cost incurred by the Transcriber provider in cents
          example: 0.7
    TelephonyData:
      properties:
        duration:
          type: string
          pattern: ^\d+$
          description: Total duration of the call in seconds
          example: 42
        to_number:
          type: string
          example: '+10123456789'
          description: >-
            Phone number of the recipient along with country code (in
            [E.164](https://en.wikipedia.org/wiki/E.164) format)
        from_number:
          type: string
          example: '+19876543007'
          description: Phone number of the sender
        recording_url:
          type: string
          format: uri
          description: Recording URL for the telephone call
          example: >-
            https://bolna-call-recordings.s3.us-east-1.amazonaws.com/ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX/REb1c182ccde4ddf7969a511a267d3c669
        hosted_telephony:
          type: boolean
          description: Whether the call was made using Bolna telephony
        provider_call_id:
          type: string
          description: >-
            Unique ID of the call from the Telephony Provider (like Twilio,
            Plivo, Vonage, etc.)
          example: CA42fb13614bfcfeccd94cf33befe14s2f
        call_type:
          type: string
          enum:
            - outbound
            - inbound
          description: The call was an incoming or outgoing call
        provider:
          type: string
          enum:
            - twilio
            - plivo
          description: The telephony call provider
        hangup_by:
          type: string
          description: Source for call hungup
          example: Caller
        hangup_reason:
          type: string
          example: Normal Hangup
          description: Reason of the hungup
        hangup_provider_code:
          type: integer
          example: 4000
          description: Provider specific code for hangup
        ring_duration:
          type: integer
          description: >-
            Duration in seconds the phone rang before it was answered or the
            call ended
          example: 17
        post_dial_delay:
          type: integer
          description: Delay in seconds between dialing and the first ring
          example: 1
        to_number_carrier:
          type: string
          description: The telecom carrier of the recipient's phone number
          example: Reliance Jio Infocomm Ltd (RJIL)
    TransferCallData:
      properties:
        provider_call_id:
          type: string
          description: >-
            Unique ID of the call from the Telephony Provider (like Twilio,
            Plivo, Vonage, etc.)
          example: CA42fb13614bfcfeccd94cf33befe14s2f
        status:
          type: string
          description: Status of this transferred call
          enum:
            - completed
            - call-disconnected
            - no-answer
            - busy
            - failed
            - in-progress
            - canceled
            - balance-low
            - queued
            - ringing
            - initiated
        duration:
          type: string
          description: Total duration of this transferred call in seconds
          example: 42
        cost:
          type: number
          format: float
          description: Total cost incurred for this transferred call
        to_number:
          type: string
          example: '+10123456789'
          description: >-
            Phone number of the recipient along with country code (in
            [E.164](https://en.wikipedia.org/wiki/E.164) format)
        from_number:
          type: string
          example: '+19876543007'
          description: Phone number which is making the transfer call
        recording_url:
          type: string
          format: uri
          description: Recording URL for the transferred call
          example: >-
            https://bolna-call-recordings.s3.us-east-1.amazonaws.com/ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX/REb1c182ccde4ddf7969a511a267d3c669
        hangup_by:
          type: string
          description: Source for transfer call hungup
          example: Caller
        hangup_reason:
          type: string
          example: Normal Hangup
          description: Reason of the transfer call hungup
        hangup_provider_code:
          type: integer
          example: 4000
          description: Provider specific code for transfer call hangup
    BatchRunData:
      properties:
        status:
          type: string
          enum:
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
          description: Status of the call initiated using batch
          example: completed
        created_at:
          type: string
          format: date-time
          example: '2024-01-23T01:14:37Z'
          description: Timestamp of the execution created by the batch
        updated_at:
          type: string
          format: date-time
          example: '2024-01-29T18:31:22Z'
          description: Last updated timestamp for the execution
        retried:
          type: number
          format: integer
          description: Number of retries made by the batch after initial attempt
          example: 0
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````