> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Patch Update a Sub-account

> Use this Bolna API endpoint to partially modify and update sub-account properties, including its name and concurrency limits.

<Note>
  This is a partial update — send only the fields you want to change. The following can be updated:

  * `name`
  * `min_concurrency` — guaranteed concurrency floor (`0` = no guarantee)
  * `max_concurrency` — hard cap; omit to leave unchanged, send `null` to make the sub-account elastic, `0` to pause it

  Only **organization admins** can update sub-accounts. Omitting a concurrency field leaves it unchanged; the edit is rejected with `400` if it would break the organization's concurrency envelope.
</Note>

See [Concurrency management](/docs/enterprise/concurrency-management) for how guarantees, caps, and shared capacity work together.


## OpenAPI

````yaml PATCH /sub-accounts/{sub_account_id}
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
  /sub-accounts/{sub_account_id}:
    patch:
      description: Patch update a sub-account
      parameters:
        - in: path
          name: sub_account_id
          description: The sub-account ID (UUID).
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        description: Fields to patch on the sub-account.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SubAccountPatch'
        required: true
      responses:
        '200':
          description: Updated sub-account
          content:
            application/json:
              example:
                message: success
                state: updated
        '400':
          description: >-
            Bad request — the edit breaks the organization's concurrency
            envelope, or no valid fields were provided.
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
                Account maximums exceed org maximum:
                  summary: Per-account hard caps over-subscribe the organization
                  value:
                    message: >-
                      Sum of capped account maximums (120) exceeds the org
                      maximum (100) by 20; lower an account maximum or raise the
                      org maximum.
                Invalid Fields:
                  summary: No valid fields provided
                  value:
                    error: No valid fields provided
                    status: failure
        '403':
          description: Forbidden — only organization admins can update sub-accounts.
          content:
            application/json:
              example:
                message: 'Forbidden: only organization admins can manage sub-accounts'
components:
  schemas:
    SubAccountPatch:
      type: object
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