> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Remove Phone Number from Trunk

> Remove a phone number from a SIP trunk. If the number was mapped to an agent, the mapping is also removed.



## OpenAPI

````yaml DELETE /sip-trunks/trunks/{trunk_id}/numbers/{phone_number_id}
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
  /sip-trunks/trunks/{trunk_id}/numbers/{phone_number_id}:
    delete:
      description: >-
        Remove a phone number from a SIP trunk. If the number was mapped to an
        agent, the mapping is also removed.
      parameters:
        - in: path
          name: trunk_id
          required: true
          schema:
            type: string
          description: The unique trunk ID
        - in: path
          name: phone_number_id
          required: true
          schema:
            type: string
          description: The phone number ID to remove
      responses:
        '200':
          description: Phone number removed
          content:
            application/json:
              example:
                message: Phone number removed successfully
        '404':
          description: not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
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