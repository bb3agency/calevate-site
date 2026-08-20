> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Add a New Provider API

> Learn how to securely add a new provider to your Bolna account by specifying the provider's name and associated credentials.

You can add your own providers securely in Bolna. Please [read this page](/docs/providers) for more information about all current supported providers.


## OpenAPI

````yaml POST /providers
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
    post:
      description: Add provider
      requestBody:
        description: Add a new provider
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ProviderRequest'
        required: true
      responses:
        '200':
          description: agent status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProviderAddedStatus'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    ProviderRequest:
      type: object
      properties:
        provider_name:
          type: string
          description: Name of the provider
          example: OPENAI_API_KEY
        provider_value:
          type: string
          description: Secret value/key associated with the provider
          example: sk-0123456789az
      required:
        - provider_name
        - provider_value
    ProviderAddedStatus:
      properties:
        message:
          type: string
          enum:
            - successful
        status:
          type: string
          enum:
            - added
          example: added
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