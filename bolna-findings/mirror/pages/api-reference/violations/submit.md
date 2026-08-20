> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Submit Violation API

> Submit a violation along with an evidence file (e.g., a screenshot or document). This endpoint updates the violation status and attaches the uploaded file.



## OpenAPI

````yaml POST /violations/submit
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
  /violations/submit:
    post:
      description: >-
        Submit a violation with an associated file (e.g., screenshot or evidence
        image).
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                violation_id:
                  type: string
                  description: The unique identifier of the violation to submit.
                  example: ce23f363-131a-47fc-8a33-258141a575b0
                violation_file:
                  type: string
                  format: binary
                  description: >-
                    The evidence file to attach to the violation (e.g., an image
                    or document).
              required:
                - violation_id
                - violation_file
      responses:
        '200':
          description: Violation submitted successfully
          content:
            application/json:
              example:
                message: success
                state: submitted
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