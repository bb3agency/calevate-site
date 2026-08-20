> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop a Previously Initiated Voice AI Call API

> Learn how to stop a call when its status is `queued` or `scheduled` This API allows you to cancel pending calls before they are executed.



## OpenAPI

````yaml POST /call/{execution_id}/stop
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
  /call/{execution_id}/stop:
    post:
      description: Stop a queued or scheduled call
      parameters:
        - in: path
          name: execution_id
          required: true
          description: The ID of the call
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: call status response
          content:
            application/json:
              example:
                message: done
                status: stopped
                execution_id: 123e4567-e89b-12d3-a456-426655440000
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