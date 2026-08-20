> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Add Phone Number to Trunk

> Add a DID phone number to your SIP trunk using the Bolna API. Assign numbers for inbound and outbound voice calling on your trunk.

## Next steps

After adding a phone number, [patch your agent's telephony provider to `sip-trunk`](/docs/api-reference/agent/v2/patch_update).


## OpenAPI

````yaml POST /sip-trunks/trunks/{trunk_id}/numbers
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
    post:
      description: Add a DID phone number to a SIP trunk
      parameters:
        - in: path
          name: trunk_id
          required: true
          schema:
            type: string
          description: The unique trunk ID
      requestBody:
        description: Phone number to add
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SIPTrunkPhoneNumberRequest'
            examples:
              example-1:
                summary: Add a phone number
                value:
                  phone_number: '919876543210'
                  name: Mumbai Support Line
                  e164_check_enabled: false
        required: true
      responses:
        '201':
          description: Phone number added
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SIPTrunkPhoneNumberResponse'
        '400':
          description: validation error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    SIPTrunkPhoneNumberRequest:
      type: object
      required:
        - phone_number
      properties:
        phone_number:
          type: string
          description: The DID phone number to register
          example: '919876543210'
        name:
          type: string
          description: Optional human-readable label for the number
          example: Mumbai Support Line
        e164_check_enabled:
          type: boolean
          default: false
          description: Whether to enforce E.164 format validation
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