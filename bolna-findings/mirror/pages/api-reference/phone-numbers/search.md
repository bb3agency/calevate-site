> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Search Phone Numbers API 

> Search available phone numbers by region, locality, or pattern, with price to use them with Bolna Voice agents.



## OpenAPI

````yaml GET /phone-numbers/search
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
  /phone-numbers/search:
    get:
      description: Search available phone numbers by country and pattern
      parameters:
        - in: path
          name: country
          required: true
          schema:
            type: string
            enum:
              - US
              - IN
          description: The country code for the phone number.
        - in: path
          name: pattern
          required: false
          schema:
            type: string
          description: 3-character prefix for the phone number to search with
        - in: path
          name: provider
          required: false
          schema:
            type: string
            enum:
              - twilio
              - plivo
              - vobiz
          description: The telephony provider for the phone number.
      responses:
        '200':
          description: list phone numbers response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AvailablePhoneNumbersList'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    AvailablePhoneNumbersList:
      items:
        $ref: '#/components/schemas/AvailablePhoneNumber'
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
    AvailablePhoneNumber:
      properties:
        region:
          type: string
          pattern: ^[A-Za-z ]+$
          example: San Francisco
          description: Name of the geographic region associated with the phone number.
        friendly_name:
          type: string
          nullable: true
          pattern: ^.*$
          example: null
          description: >-
            A user-assigned friendly label for the number; may be null if not
            set.
        locality:
          type: string
          nullable: true
          pattern: ^.*$
          example: null
          description: Name of the locality or area; may be null if not available.
        phone_number:
          type: string
          pattern: ^\+[1-9][0-9]{7,14}$
          example: '+19876543210'
          description: E.164 formatted phone number, including country code.
        provider:
          type: string
          enum:
            - twilio
            - plivo
            - vobiz
          description: The telephony provider for the phone number.
        price:
          type: number
          format: float
          pattern: ^[0-9]+(\.[0-9]{1,2})?$
          example: 5
          description: Price of the number in USD.
      type: object
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````