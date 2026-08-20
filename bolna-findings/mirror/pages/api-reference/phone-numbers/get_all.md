> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List Phone Numbers API 

> Retrieve all phone numbers associated with your account, including details like creation date and telephony provider like Twilio, Plivo, etc.



## OpenAPI

````yaml GET /phone-numbers/all
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
  /phone-numbers/all:
    get:
      description: List all phone numbers for your account
      responses:
        '200':
          description: list phone numbers response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PhoneNumbersList'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    PhoneNumbersList:
      items:
        $ref: '#/components/schemas/PhoneNumber'
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
    PhoneNumber:
      properties:
        id:
          type: string
          pattern: ^[0-9a-fA-F]{32}$
          example: 3c90c3cc0d444b5088888dd25736052a
          description: The ID of the phone number
        humanized_created_at:
          type: string
          example: 5 minutes ago
          description: Human-readable relative time since the phone number creation
        created_at:
          type: string
          format: date-time
          example: '2024-01-23T05:14:37Z'
          description: Created timestamp of phone number
        humanized_updated_at:
          type: string
          example: 5 minutes ago
          description: Human-readable relative time since the phone number last update
        updated_at:
          type: string
          format: date-time
          example: '2024-02-28T04:22:29Z'
          description: Last updated timestamp of phone number
        renewal_at:
          type: string
          example: 17th Dec, 2024
          description: Human readable renewal date for the phone number
        phone_number:
          type: string
          format: string
          example: '+19876543210'
          description: >-
            Phone number in (in [E.164](https://en.wikipedia.org/wiki/E.164)
            format)
        agent_id:
          type: string
          format: uuid
          description: Agent `id` associated with the phone number
        price:
          type: string
          description: Monthly rental price of the phone number
          example: $5.0
        telephony_provider:
          type: string
          enum:
            - twilio
            - plivo
            - vonage
          example: twilio
          description: Telephony provider of the phone number
        rented:
          type: boolean
          description: If the phone number was bought from Bolna
          example: true
      type: object
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````