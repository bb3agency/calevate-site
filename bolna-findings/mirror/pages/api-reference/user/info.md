> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# User information

> Get details like name, email, current wallet balance, concurrency limits using this API



## OpenAPI

````yaml GET /user/me
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
  /user/me:
    get:
      description: Get user information
      responses:
        '200':
          description: Your user details
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: access denied
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AccessDenied'
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
          format: uuid
          description: Unique `id` for your user associated with Bolna
        name:
          type: string
          description: Name of the user
          examples:
            - Bruce Wayne
        email:
          type: string
          format: email
          description: Email address of the user
        wallet:
          type: number
          format: float
          description: Current wallet balance of the user
          examples:
            - 42.42
        concurrency:
          type: object
          properties:
            max:
              type: integer
              format: int32
              description: Maximum concurrency limit for the user account
              examples:
                - 10
            current:
              type: integer
              format: int32
              description: Current concurrent calls from the user account
              examples:
                - 7
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
    AccessDenied:
      required:
        - error
        - message
      type: object
      properties:
        error:
          type: integer
          format: int32
          example: 401
        message:
          type: string
          example: Access denied
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````