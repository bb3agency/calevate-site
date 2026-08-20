> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Set Inbound Agent API

> Configure Bolna Voice AI agent to handle inbound calls automatically by associating it with a specific phone number using Bolna APIs.



## OpenAPI

````yaml POST /inbound/setup
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
  /inbound/setup:
    post:
      description: Add agent for inbound calls with optional IVR configuration
      requestBody:
        content:
          application/json:
            schema:
              required:
                - agent_id
                - phone_number_id
              properties:
                agent_id:
                  type: string
                  format: uuid
                  description: >-
                    Agent `id` which will handle inbound calls. Used as default
                    if no IVR option-level agent is set.
                  example: 3c90c3cc-0d44-4b50-8888-8dd25736052a
                phone_number_id:
                  type: string
                  format: uuid
                  pattern: >-
                    ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}
                  example: 123e4567-e89b-12d3-a456-426614174000
                  description: >-
                    Telephone number `id` from [Phone number list
                    API](/docs/api-reference/phone-numbers/get_all)
                allow_multiple:
                  type: boolean
                  default: false
                  example: true
                  description: >-
                    Allow this phone number to be linked to multiple phone
                    numbers for the same agent. Only applicable for Plivo phone
                    numbers.
                ivr_config:
                  type: object
                  description: >-
                    Optional IVR configuration for Plivo phone numbers. See [IVR
                    documentation](/ivr-inbound-calls) for details.
                  properties:
                    enabled:
                      type: boolean
                      description: Enable or disable IVR
                      example: true
                    voice:
                      type: string
                      description: Text-to-speech voice (e.g., Polly.Aditi, Polly.Joanna)
                      example: Polly.Aditi
                    welcome_message:
                      type: string
                      description: Message played when call connects
                      example: Welcome to Acme Corp.
                    timeout:
                      type: integer
                      description: Seconds to wait for input
                      example: 7
                    max_retries:
                      type: integer
                      description: Retry attempts on invalid input
                      example: 2
                    steps:
                      type: array
                      description: IVR flow steps (menu or collect)
                      items:
                        type: object
                        properties:
                          step_id:
                            type: string
                          type:
                            type: string
                            enum:
                              - menu
                              - collect
                          prompt:
                            type: string
                          field_name:
                            type: string
                          options:
                            type: array
                            items:
                              type: object
                          next_step:
                            type: string
                          conditional_next:
                            type: object
                    default_agent_id:
                      type: string
                      format: uuid
                      description: Fallback agent if no option-level agent is set
        required: true
      responses:
        '200':
          description: providers status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/InboundAgentResponse'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    InboundAgentResponse:
      properties:
        url:
          type: string
          description: Message displaying the voice URL
          example: >-
            https://api.bolna.ai/inbound_call?agent_id=3c90c3cc-0d44-4b50-8888-8dd25736052a&user_id=28f9c34b-8eb0-4af5-8689-c2f6c4daec22
        phone_number:
          type: string
          format: string
          example: '+19876543210'
          description: >-
            Phone number in (in [E.164](https://en.wikipedia.org/wiki/E.164)
            format)
        id:
          type: string
          pattern: ^[0-9a-fA-F]{32}$
          example: 3c90c3cc0d444b5088888dd25736052a
          description: The ID of the phone number
      type: object
      title: inboundagent
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