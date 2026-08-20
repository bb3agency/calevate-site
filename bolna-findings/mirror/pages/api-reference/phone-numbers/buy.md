> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Buy Phone Numbers API 

> Buy virtual phone numbers with full purchase, pricing, and provider details to use with Bolna Voice agents for outbound and inbound calls.



## OpenAPI

````yaml POST /phone-numbers/buy
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
  /phone-numbers/buy:
    post:
      description: Buy a phone number
      requestBody:
        description: Purchase a phone number
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/PurchasePhoneNumberRequest'
        required: true
      responses:
        '200':
          description: Sub-account create response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PurchasePhoneNumberResponse'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    PurchasePhoneNumberRequest:
      properties:
        country:
          type: string
          enum:
            - US
            - IN
          description: The country code for the phone number.
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
      type: object
      required:
        - country
        - phone_number
    PurchasePhoneNumberResponse:
      properties:
        id:
          type: string
          format: uuid
          example: 133b9a7d-59b1-49c4-b62a-c4924503e38b
          description: Unique identifier for the purchased phone number record.
        agent_id:
          type: string
          format: uuid
          nullable: true
          example: null
          description: Identifier of the agent associated with the number, if applicable.
        bolna_owned:
          type: boolean
          example: true
          description: Indicates if the number is owned by Bolna.
        deleted:
          type: boolean
          example: false
          description: Indicates whether the number record is deleted.
        renewal:
          type: boolean
          example: true
          description: Indicates if the phone number subscription will auto-renew.
        payment_uuid:
          type: string
          format: uuid
          example: de36c363-6a2d-4e83-ba5b-fbb8d0ac8c32
          description: Unique identifier for the payment transaction.
        phone_number:
          type: string
          pattern: ^\+[1-9][0-9]{7,14}$
          example: '+19876543210'
          description: E.164 formatted purchased phone number.
        price:
          type: number
          format: float
          example: 500
          description: Price for the phone number in cents.
        telephony_provider:
          type: string
          enum:
            - twilio
            - plivo
            - vonage
            - telnyx
          description: Name of the telephony provider for the number.
        telephony_sid:
          type: string
          example: '19876543210'
          description: >-
            Unique identifier or SID for the phone number within the telephony
            provider.
        created_at:
          type: string
          format: date-time
          example: '2025-07-27T20:51:49.468787'
          description: Timestamp when the record was created.
        updated_at:
          type: string
          format: date-time
          example: '2025-07-27T20:51:49.468796'
          description: Timestamp when the record was last updated.
      type: object
      title: purchase phone number status
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