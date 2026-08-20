> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete SIP Trunk

> Permanently delete a SIP trunk and all associated resources including gateways, IP identifiers, and phone numbers.



## OpenAPI

````yaml DELETE /sip-trunks/trunks/{trunk_id}
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
  /sip-trunks/trunks/{trunk_id}:
    delete:
      description: >-
        Permanently delete a SIP trunk and all associated resources (gateways,
        IP identifiers, phone numbers)
      parameters:
        - in: path
          name: trunk_id
          required: true
          schema:
            type: string
          description: The unique trunk ID
      responses:
        '200':
          description: Trunk deleted
          content:
            application/json:
              example:
                message: Trunk deleted successfully. 3 phone number(s) removed.
        '404':
          description: trunk not found
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