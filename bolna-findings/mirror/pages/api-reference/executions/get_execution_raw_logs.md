> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve Voice AI Execution Raw Logs API

> Fetch raw logs of a specific phone call execution by its ID using Bolna APIs. This includes prompts, requests, responses, and optional LLM reasoning summaries when available.

For each item in `data`, when **`component`** is **`llm`** and **`type`** is **`response`**, the assistant text is in **`data`**. If the model exposed traceable reasoning for that turn, **`reasoning_content`** is also set; otherwise the field is omitted. Use this to debug or display model thinking alongside the spoken reply.


## OpenAPI

````yaml GET /executions/{execution_id}/log
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
  /executions/{execution_id}/log:
    get:
      description: Retrieve raw logs of specific `execution_id`
      parameters:
        - in: path
          name: execution_id
          required: true
          schema:
            type: string
            format: uuid
          description: The unique `execution_id`
      responses:
        '200':
          description: Retrieve specific execution raw logs
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AgentExecutionLogList'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    AgentExecutionLogList:
      properties:
        status:
          type: string
          example: success
          description: Status of the API response
        data:
          items:
            $ref: '#/components/schemas/AgentExecutionLog'
          type: array
      title: Items
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
    AgentExecutionLog:
      properties:
        created_at:
          type: string
          format: date-time
          example: '2024-01-23T05:14:37Z'
          description: Created timestamp of the log
        type:
          type: string
          enum:
            - request
            - response
          description: The log direction
        component:
          type: string
          description: type of component
          example: synthesizer
        provider:
          type: string
          example: openai
          description: The provider name
        data:
          type: string
          example: Hello world
          description: The log content or message
        reasoning_content:
          type: string
          description: >-
            Optional model reasoning or thinking summary for this log entry.
            Present only when `component` is `llm`, `type` is `response`, and
            the provider returned traceable reasoning (e.g. OpenAI reasoning
            summaries or Gemini thoughts). Omitted when not available.
          example: '**Defining the topic**\n\nPlanning a short, conversational reply...'
      type: object
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````