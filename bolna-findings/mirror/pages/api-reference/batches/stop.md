> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop Batch API

> Understand how to stop a running batch using its ID, allowing you to halt ongoing calls in the batch.



## OpenAPI

````yaml POST /batches/{batch_id}/stop
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
  /batches/{batch_id}/stop:
    post:
      description: Stop a running batch
      parameters:
        - in: path
          name: batch_id
          required: true
          description: The ID of the batch
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: batch status response
          content:
            application/json:
              example:
                message: success
                state: stopped
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '404':
          description: batch status response
          content:
            application/json:
              example:
                message: Batch is not queued or running
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