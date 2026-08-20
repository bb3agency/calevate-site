> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List Providers API 

> Retrieve all providers associated with your Bolna account, including their IDs, names, and creation timestamps.



## OpenAPI

````yaml GET /providers
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
  /providers:
    get:
      description: List all providers
      responses:
        '200':
          description: providers status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProviderList'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    ProviderList:
      items:
        $ref: '#/components/schemas/Provider'
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
    Provider:
      type: object
      properties:
        provider_id:
          type: string
          description: Unique provider identifier
          format: uuid
        provider_name:
          type: string
          description: Name of the provider
          example: OPENAI_API_KEY
        provider_value:
          type: string
          description: Masked secret value/key associated with the provider
          example: xxxxxxxaz
        humanized_created_at:
          type: string
          description: Human readable relative timestamp of provider addition
          example: 7 hours ago
        created_at:
          type: string
          format: date-time
          example: '2024-01-29T12:44:12Z'
          description: Timestamp of provider addition
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````