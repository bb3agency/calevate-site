> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List Phone Numbers on Trunk

> List all phone numbers associated with a SIP trunk. View assigned DID numbers and manage your trunk number inventory.



## OpenAPI

````yaml GET /sip-trunks/trunks/{trunk_id}/numbers
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
  /sip-trunks/trunks/{trunk_id}/numbers:
    get:
      description: List all phone numbers associated with a SIP trunk
      parameters:
        - in: path
          name: trunk_id
          required: true
          schema:
            type: string
          description: The unique trunk ID
      responses:
        '200':
          description: List of phone numbers
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/SIPTrunkPhoneNumberResponse'
        '404':
          description: trunk not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    SIPTrunkPhoneNumberResponse:
      type: object
      description: Phone number (DID) registered on a SIP trunk.
      properties:
        id:
          type: string
          description: Unique phone number identifier.
        phone_number:
          type: string
          description: The DID phone number stored on the trunk.
        name:
          type: string
          description: Optional label for the phone number.
        byot_trunk_id:
          type: string
          description: The SIP trunk ID that this phone number belongs to.
        telephony_provider:
          type: string
          description: Provider type for BYOT numbers.
          example: sip-trunk
        deleted:
          type: boolean
          description: Whether the phone number is deleted.
        created_at:
          type: string
          format: date-time
          description: ISO timestamp when the phone number was created.
        updated_at:
          type: string
          format: date-time
          description: ISO timestamp when the phone number was last updated.
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