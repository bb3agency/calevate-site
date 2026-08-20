> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Knowledgebase API

> Retrieve details of a specific knowledgebase, including its ID, file name, creation time, and status, using Bolna APIs.



## OpenAPI

````yaml GET /knowledgebase/{rag_id}
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
    get:
      description: Retrieve a knowledgebase
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
          description: list knowledgebase response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Knowledgebase'
        '400':
          description: unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    Knowledgebase:
      properties:
        rag_id:
          type: string
          pattern: >-
            ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}
          example: f265b06a-7fa7-4fbf-8923-55d5ae9c4ba2
          description: The ID of the knowledgebase
        file_name:
          type: string
          description: File name of the document
          example: sample-rag.pdf
        humanized_created_at:
          type: string
          example: 5 minutes ago
          description: Human-readable relative time since knowledgebase creation
        created_at:
          type: string
          format: date-time
          example: '2024-01-23T05:14:37Z'
          description: Created timestamp of knowledgebase
        updated_at:
          type: string
          format: date-time
          example: '2024-02-28T04:22:29Z'
          description: Last updated timestamp of knowledgebase
        vector_id:
          type: string
          pattern: >-
            ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}
          example: 77a3473c-c78f-4695-ba56-95b1f4f9e80b
          description: Unique vector ID of the knowledgebase
        status:
          type: string
          enum:
            - processing
            - processed
          example: processed
          description: Current status of the knowledgebase
        chunk_size:
          type: integer
          description: Chunk size for embedding model
          default: 512
          example: 512
        similarity_top_k:
          type: integer
          description: Number of top similar nodes to return.
          default: 15
          example: 15
        overlapping:
          type: integer
          description: Number of characters which overlap in between neighboring nodes.
          default: 128
          example: 128
        language_support:
          type: string
          description: >-
            Language support mode of the knowledgebase. `multilingual` if
            enabled, `null` otherwise.
          nullable: true
          enum:
            - multilingual
          example: null
      type: object
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