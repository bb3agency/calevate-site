> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List all Sub-Accounts API

> Retrieve all sub-accounts linked to your main account enabling centralized visibility and management.

<Note>
  This is an `enterprise` feature.

  You can read more about our enterprise offering here [Bolna enterprise](/docs/enterprise/plan).
</Note>


## OpenAPI

````yaml GET /sub-accounts/all
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
  /sub-accounts/all:
    get:
      description: List all sub-accounts
      responses:
        '200':
          description: List of all sub-accounts
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SubAccountList'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    SubAccountList:
      items:
        $ref: '#/components/schemas/SubAccount'
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
    SubAccount:
      type: object
      properties:
        id:
          type: string
          format: uuid
          description: Unique `id` for the associated sub-account
        name:
          type: string
          description: Name of the sub-account
          example: alpha-007
        organization_id:
          type: string
          format: uuid
          description: Organization ID the sub-account belongs to
        api_key:
          type: string
          pattern: ^sa-[a-f0-9]{32}$
          example: sa-b33f4fbf011d4661a273a46b11d185f8
          description: >-
            Sub-account API Key used to interact with sub-account resources like
            agents, executions, batches, etc.
        multi_tenant:
          type: boolean
          description: Whether the sub-account is being stored in a separate database
          example: false
        min_concurrency:
          type: integer
          description: >-
            Guaranteed concurrency reserved for this sub-account even when the
            organization is at capacity. 0 means no guarantee.
          example: 5
        max_concurrency:
          type: integer
          description: >-
            Hard cap on this sub-account's concurrency. Omit (or send null) for
            an elastic account that can burst into the organization's unused
            capacity. 0 pauses the sub-account.
          example: 20
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````