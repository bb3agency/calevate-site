> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Deleting a Sub-account

> Use Bolna APIs to delete a sub-account and their related data, ensuring proper cleanup of agents, batches, executions, and configurations.

<Warning>
  This deletes **ALL** the data for that sub-account's batches, executions and agents.
</Warning>


## OpenAPI

````yaml DELETE /sub-accounts/{sub_account_id}
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
    delete:
      description: Delete a sub-account
      parameters:
        - in: path
          name: sub_account_id
          required: true
          description: The ID of the sub-account
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: sub-account deleted response
          content:
            application/json:
              example:
                message: success
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