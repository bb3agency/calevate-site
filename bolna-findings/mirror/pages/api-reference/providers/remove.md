> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Remove a Provider API

> Delete a previously added provider from your Bolna account, ensuring your integrations remain current.



## OpenAPI

````yaml DELETE /providers/{provider_key_name}
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
  /providers/{provider_key_name}:
    delete:
      description: Remove provider
      parameters:
        - in: path
          name: provider_key_name
          required: true
          description: Name of the provider
          schema:
            type: string
            example: OPENAI_API_KEY
      responses:
        '200':
          description: agent status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProviderRemoveStatus'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    ProviderRemoveStatus:
      properties:
        message:
          type: string
          enum:
            - successful
        status:
          type: string
          enum:
            - removed
          example: removed
      type: object
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