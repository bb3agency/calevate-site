> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop Agent Queued Calls API

> Use Bolna APIs to stop all queued calls for a specific agent, preventing any pending calls from being executed.

<Warning>
  This stops **ALL** the queued calls for a given agent.
</Warning>

This endpoint stops all queued calls for the specified agent. Any calls that are currently in the queue waiting to be executed will be cancelled and will not be processed.


## OpenAPI

````yaml POST /v2/agent/{agent_id}/stop
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
  /v2/agent/{agent_id}/stop:
    post:
      description: Stop all queued calls for a given agent_id
      parameters:
        - in: path
          name: agent_id
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: agent execution stopped response
          content:
            application/json:
              example:
                stopped_executions:
                  - c8098ad0-29f6-456d-1234-7b93ad224059
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