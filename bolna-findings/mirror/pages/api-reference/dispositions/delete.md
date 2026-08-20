> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Disposition API

> Delete a disposition from your account. Only the owner can delete a disposition.

<Warning>
  Deletion is permanent and cannot be undone. Historical call execution results that already contain this disposition's output are not affected — only future calls will stop evaluating it.
</Warning>

### Authorization

* **Regular users** can only delete dispositions they own (`created_by` matches their user ID).
* **Admins** can delete any disposition.


## OpenAPI

````yaml DELETE /dispositions/{disposition_id}
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
  /dispositions/{disposition_id}:
    delete:
      description: >
        Permanently delete a disposition and remove its link to any associated
        agents.


        Regular users can only delete dispositions they own (`created_by`
        matches their user ID). Admins can delete any disposition. Historical
        call execution results already containing this disposition's output are
        not affected — only future calls will stop evaluating it.
      parameters:
        - in: path
          name: disposition_id
          required: true
          schema:
            type: string
            format: uuid
          description: The ID of the disposition to delete.
      responses:
        '200':
          description: Disposition deleted successfully
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DispositionCreateResponse'
              example:
                message: Disposition deleted successfully
                id: 3fa85f64-5717-4562-b3fc-2c963f66afa6
        '403':
          description: Access denied — you do not own this disposition
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '404':
          description: Disposition not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '500':
          description: Internal server error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    DispositionCreateResponse:
      type: object
      description: >-
        Standard response for create/update/delete operations on a single
        disposition.
      properties:
        message:
          type: string
          example: Disposition created successfully
        id:
          type: string
          format: uuid
          example: 3fa85f64-5717-4562-b3fc-2c963f66afa6
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