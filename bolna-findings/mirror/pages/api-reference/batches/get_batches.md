> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List All Batches API

> Explore how to list all batches associated with a particular Bolna Voice AI agent, providing an overview of their statuses, schedules and other relevant details



## OpenAPI

````yaml GET /batches/{agent_id}/all
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
  /batches/{agent_id}/all:
    get:
      description: List all batches for agent
      parameters:
        - in: path
          name: agent_id
          required: true
          description: The ID of the agent
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: list batches response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BatchList'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    BatchList:
      items:
        $ref: '#/components/schemas/Batch'
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
    Batch:
      properties:
        batch_id:
          type: string
          pattern: ^[0-9a-fA-F]{32}$
          example: 3c90c3cc0d444b5088888dd25736052a
          description: The ID of the batch
        humanized_created_at:
          type: string
          example: 5 minutes ago
          description: Human-readable relative time since batch creation
        created_at:
          type: string
          format: date-time
          example: '2024-01-23T05:14:37Z'
          description: Created timestamp of batch
        updated_at:
          type: string
          format: date-time
          example: '2024-02-28T04:22:29Z'
          description: Last updated timestamp of batch
        status:
          type: string
          enum:
            - created
            - scheduled
            - running
            - completed
            - stopped
            - failed
          example: scheduled
          description: >-
            Current status of the batch. Progression: `created → scheduled →
            running → completed`. `stopped` means manually halted; `failed`
            means an error prevented execution.
        scheduled_at:
          type: string
          format: date-time
          example: '2024-01-29T08:30:00Z'
          description: The scheduled batch timestamp in UTC
        from_phone_number:
          type: string
          deprecated: true
          description: >-
            **Deprecated.** Use `from_phone_numbers` instead. Phone number of
            the sender along with country code (in
            [E.164](https://en.wikipedia.org/wiki/E.164) format).
          example: '+19876543007'
        from_phone_numbers:
          type: array
          items:
            type: string
          description: >-
            List of phone numbers from which the batch calls are made. Each
            number includes the country code in
            [E.164](https://en.wikipedia.org/wiki/E.164) format.
          example:
            - '+19876543007'
            - '+19876543007'
        file_name:
          type: string
          description: Name of the CSV batch file uploaded
          example: customers.csv
        valid_contacts:
          type: integer
          format: int32
          description: Count of all valid contacts found in the CSV file
          example: 7
        total_contacts:
          type: integer
          format: int32
          description: Count of all contacts mentioned in the CSV file
          example: 11
        execution_status:
          type: object
          description: >-
            Provides a count-wise breakdown of executions based on their current
            status. [View all possible statuses](/list-phone-call-status)
          additionalProperties:
            type: integer
            description: The count of users for a specific execution status.
          example:
            completed: 1
            ringing: 10
            in-progress: 15
      type: object
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````