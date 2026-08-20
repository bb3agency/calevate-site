> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Batch API

> Understand how to delete a specific batch using its ID, effectively removing it from your scheduled or active batches.



## OpenAPI

````yaml DELETE /batches/{batch_id}
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
  /batches/{batch_id}:
    delete:
      description: Delete a batch
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
          description: batch deleted response
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