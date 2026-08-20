> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create a new Sub-Account API

> Create a new sub-account using the Bolna API to define separate workspaces with custom configurations for enterprise-level management.

<Note>
  This is an `enterprise` feature.

  You can read more about our enterprise offering here [Bolna enterprise](/docs/enterprise/plan).
</Note>

Only **organization admins** can create sub-accounts.

## Concurrency

Every sub-account is created with a concurrency envelope:

* **`min_concurrency`** — concurrency guaranteed to this sub-account even when the organization is at capacity. Use `0` for no guarantee.
* **`max_concurrency`** — the sub-account's hard cap. **Omit it for an elastic** sub-account that can burst into the organization's unused capacity; set `0` to pause the sub-account.

The request is rejected with `400` if the per-account minimums or maximums would exceed the organization's envelope. See [Concurrency management](/docs/enterprise/concurrency-management) for how guarantees, caps, and shared capacity work together.


## OpenAPI

````yaml POST /sub-accounts/create
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
  /sub-accounts/create:
    post:
      description: Creates a new sub-account
      requestBody:
        description: Payload for creating a new sub-account
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SubAccountRequest'
        required: true
      responses:
        '200':
          description: Sub-account create response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SubAccountResponse'
        '400':
          description: >-
            Validation error — missing name/concurrency, or the per-account
            minimums/maximums over-subscribe the organization's concurrency
            envelope.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                Account minimums exceed org minimum:
                  summary: >-
                    Per-account guaranteed minimums over-subscribe the
                    organization
                  value:
                    message: >-
                      Sum of account minimums (60) exceeds the org minimum (50)
                      by 10; lower an account minimum first.
                Missing concurrency:
                  summary: Neither min_concurrency nor max_concurrency provided
                  value:
                    message: >-
                      Bad request. Please provide min_concurrency and/or
                      max_concurrency.
        '403':
          description: >-
            Forbidden — only organization admins can create or update
            sub-accounts.
          content:
            application/json:
              example:
                message: >-
                  Forbidden: only organization admins can manage sub-account
                  concurrency
components:
  schemas:
    SubAccountRequest:
      properties:
        name:
          type: string
          description: Name of the sub-account
          example: alpha-007
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
        multi_tenant:
          type: boolean
          default: false
          description: The sub-account is stored in a separate database
        db_host:
          type: string
          default: null
          example: prod-alpha-007-db-east-1.my-database.com
          description: Database host for `multi_tenant` sub-account
        db_name:
          type: string
          default: null
          example: alpha-007_db
          description: Database name for `multi_tenant` sub-account
        db_port:
          type: string
          default: null
          example: 5432
          description: Database port for `multi_tenant` sub-account
        db_user:
          type: string
          default: null
          example: alpha-007_user
          description: Database root user for `multi_tenant` sub-account
        db_password:
          type: string
          default: null
          example: alpha-007_password
          description: Database root password for `multi_tenant` sub-account
      type: object
      required:
        - name
        - min_concurrency
    SubAccountResponse:
      properties:
        id:
          type: string
          format: uuid
          description: Unque identifier for the created sub-account
        name:
          type: string
          description: Name of the sub-account
          example: alpha-007
        user_id:
          type: string
          format: uuid
          description: ID of the user who created the sub-account
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
        db_host:
          type: string
          description: Database host if the sub-account is `multi_tenant:true`
          example: null
        db_name:
          type: string
          description: Database name if the sub-account is `multi_tenant:true`
          example: null
        db_port:
          type: string
          description: Database port if the sub-account is `multi_tenant:true`
          example: null
        db_user:
          type: string
          description: Database root user if the sub-account is `multi_tenant:true`
          example: null
        db_password:
          type: string
          description: Database root password if the sub-account is `multi_tenant:true`
          example: null
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
        created_at:
          type: string
          format: date-time
          example: '2025-01-23T01:14:37Z'
          description: Timestamp of sub-account creation
        updated_at:
          type: string
          format: date-time
          example: '2025-01-23T01:14:37Z'
          description: Timestamp of sub-account updation
      type: object
      title: Sub-account status
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