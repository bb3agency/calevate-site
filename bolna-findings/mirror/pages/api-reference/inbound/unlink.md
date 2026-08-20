> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Remove Inbound Agent API

> Remove and unlink a Bolna Voice AI agent from a specific phone number to disable automated inbound voice call answering by AI agents.



## OpenAPI

````yaml POST /inbound/unlink
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
  /inbound/unlink:
    post:
      description: Remove agent for inbound calls
      requestBody:
        content:
          application/json:
            schema:
              required:
                - phone_number_id
              properties:
                phone_number_id:
                  type: string
                  format: uuid
                  pattern: >-
                    ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}
                  example: 123e4567-e89b-12d3-a456-426614174000
                  description: >-
                    Telephone number `id` from [Phone number list
                    API](/docs/api-reference/phone-numbers/get_all)
        required: true
      responses:
        '200':
          description: Unlink inbound agent response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/InboundUnlinkAgentResponse'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    InboundUnlinkAgentResponse:
      properties:
        url:
          type: string
          description: >-
            Message displaying the voice URL. This will be `null` if the
            unlinking is successful.
          example: null
        phone_number:
          type: string
          format: string
          example: '+19876543210'
          description: >-
            Phone number in (in [E.164](https://en.wikipedia.org/wiki/E.164)
            format)
        id:
          type: string
          pattern: ^[0-9a-fA-F]{32}$
          example: 3c90c3cc0d444b5088888dd25736052a
          description: The ID of the phone number
      type: object
      title: unlinkinboundagent
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