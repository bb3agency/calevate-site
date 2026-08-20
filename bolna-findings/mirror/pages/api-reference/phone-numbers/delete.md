> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Phone Numbers API 

> Delete a purchased phone number to stop billing and remove it permanently from your active inventory.



## OpenAPI

````yaml DELETE /phone-numbers/{phone_number_id}
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
  /phone-numbers/{phone_number_id}:
    delete:
      description: Delete a batch
      parameters:
        - in: path
          name: phone_number_id
          required: true
          description: The ID of the `phone_number` to be deleted
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: phone number deleted response
          content:
            application/json:
              example:
                message: The phone number has been removed from your account
                state: deleted
        '400':
          description: unexpected error
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