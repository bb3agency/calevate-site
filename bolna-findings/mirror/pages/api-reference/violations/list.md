> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List Violations API

> Retrieve a paginated list of violations, optionally filtered by status. Use this endpoint to monitor and manage call violations across your account.

## Pagination

This API supports pagination using the `page_number` and `page_size` query parameters. You can utilize `has_more` in the API response to determine if you should fetch the next page. You can learn more about it from the [pagination documentation](/docs/api-reference/pagination).


## OpenAPI

````yaml GET /violations/list
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
  /violations/list:
    get:
      description: Retrieve a paginated list of violations, optionally filtered by status.
      parameters:
        - in: query
          name: status
          required: false
          schema:
            type: string
            enum:
              - pending
              - accepted
              - rejected
              - submitted
          description: Filter violations by their current status.
        - in: query
          name: page_number
          required: false
          schema:
            type: integer
            default: 1
            minimum: 1
          description: The page of results to retrieve (starts from `1`).
        - in: query
          name: page_size
          required: false
          schema:
            type: integer
            default: 20
            minimum: 1
          description: Number of results per page.
      responses:
        '200':
          description: Paginated list of violations
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ViolationList'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    ViolationList:
      type: object
      description: Paginated list of violations.
      properties:
        data:
          type: array
          items:
            $ref: '#/components/schemas/Violation'
          description: Array of violation objects.
        total:
          type: integer
          description: Total number of violations matching the filter.
          example: 9
        limit:
          type: integer
          description: Number of results returned per page.
          example: 5
        offset:
          type: integer
          description: The offset of the current page in the result set.
          example: 5
        has_more:
          type: boolean
          description: Whether there are more results available beyond the current page.
          example: false
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
    Violation:
      type: object
      description: A violation record associated with a call.
      properties:
        id:
          type: string
          format: uuid
          description: Unique identifier of the violation.
          example: ce23f363-131a-47fc-8a33-258141a575b0
        from_phone_number:
          type: string
          description: The phone number that initiated the call (in E.164 format).
          example: '+918035739196'
        to_phone_number:
          type: string
          description: The phone number that received the call (in E.164 format).
          example: '+919845866566'
        date_of_call:
          type: string
          format: date-time
          description: The date of the call associated with the violation.
          example: '2026-01-05T00:00:00+00:00'
        status:
          type: string
          enum:
            - pending
            - accepted
            - rejected
            - submitted
          description: Current status of the violation.
          example: submitted
        created_at:
          type: string
          format: date-time
          description: ISO timestamp when the violation was created.
          example: '2026-03-06T08:25:53.514276+00:00'
        updated_at:
          type: string
          format: date-time
          description: ISO timestamp when the violation was last updated.
          example: '2026-03-09T07:10:29.135591+00:00'
        user_id:
          type: string
          format: uuid
          description: The unique identifier of the user associated with the violation.
          example: 9082f423-9c6c-4f19-a131-24f4cc99209a
        agent_id:
          type: string
          format: uuid
          description: The unique identifier of the agent associated with the violation.
          example: af4f2c34-4750-4d7c-97a3-4e2e27a643a2
        execution_id:
          type: string
          format: uuid
          description: >-
            The unique identifier of the call execution linked to this
            violation.
          example: 137f88ef-701e-42b6-a26a-7bc1103df5aa
        image_url:
          type: string
          nullable: true
          description: Path to the violation evidence image, if available.
          example: >-
            73b9ed7c-c255-486b-b2eb-6c21e41a8ca1/violations/ce23f363-131a-47fc-8a33-258141a575b0/9845866566.png
        email:
          type: string
          format: email
          description: Email address associated with the violation.
          example: user@example.com
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````