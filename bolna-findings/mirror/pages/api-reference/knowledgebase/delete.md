> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Knowledgebase API

> Remove and delete an existing knowledgebase from your Bolna account maintaining your Bolna Voice AI agents upto date.



## OpenAPI

````yaml DELETE /knowledgebase/{rag_id}
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
  /knowledgebase/{rag_id}:
    delete:
      description: Delete a knowledgebase
      parameters:
        - in: path
          name: rag_id
          required: true
          description: The ID of the knowledgebase
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: knowledgebase status response
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