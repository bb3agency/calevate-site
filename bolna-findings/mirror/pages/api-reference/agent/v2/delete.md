> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Voice AI Agent API

> Use Bolna APIs to delete agents and their related data, ensuring proper cleanup of batches, executions, and configurations.

<Warning>
  This deletes **ALL** agent data including all batches, all executions, etc.
</Warning>


## OpenAPI

````yaml DELETE /v2/agent/{agent_id}
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
  /v2/agent/{agent_id}:
    delete:
      description: Delete an agent
      parameters:
        - in: path
          name: agent_id
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: agent deleted response
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