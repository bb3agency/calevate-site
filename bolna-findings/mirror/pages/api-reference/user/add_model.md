> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Add a New Custom LLM Model

> Learn how to integrate your custom Large Language Model (LLM) with Bolna Voice AI agents using Bolna APIs.

This request specifies how to add your own Custom LLM Models and use it with Bolna Voice AI agents. Please read about it more from [using-custom-llm](/docs/customizations/using-custom-llm)


## OpenAPI

````yaml POST /user/model/custom
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
  /user/model/custom:
    post:
      description: Add a custom LLM Model
      requestBody:
        description: Add a custom LLM Model
        content:
          application/json:
            schema:
              required:
                - custom_model_name
                - custom_model_url
              properties:
                custom_model_name:
                  type: string
                  description: Human readable name for your custom model
                custom_model_url:
                  type: string
                  format: uri
                  description: URL endpoint for the custom LLM model
            examples:
              example-1:
                summary: Example of adding a custom LLM model
                value:
                  custom_model_name: Customer-care Model
                  custom_model_url: https://custom.llm.model/v1
        required: true
      responses:
        '200':
          description: agent status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AddModelResponse'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    AddModelResponse:
      properties:
        message:
          type: string
          example: model added successfully
          description: Success message for adding the custom model
        status:
          type: string
          enum:
            - added
          example: added
          description: status for the model sent in the request to be added
      type: object
      title: addmodelstatus
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