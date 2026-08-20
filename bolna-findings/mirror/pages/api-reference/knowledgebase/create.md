> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Knowledgebase API

> Upload a PDF document or provide a URL to create a knowledgebase, enhancing your Bolna Voice AI agent's information base and response accuracy.



## OpenAPI

````yaml POST /knowledgebase
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
  /knowledgebase:
    post:
      description: >-
        Create knowledgebase from a PDF file or URL. Provide either `file` or
        `url`, not both.
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                file:
                  type: string
                  format: binary
                  description: >-
                    PDF file to upload (max 20 MB). Required if `url` is not
                    provided.
                url:
                  type: string
                  format: uri
                  description: >-
                    URL to scrape and ingest as knowledgebase. Required if
                    `file` is not provided.
                  example: https://example.com/docs
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
                  description: >-
                    Number of characters which overlap in between neighboring
                    nodes.
                  default: 128
                  example: 128
                language_support:
                  type: string
                  description: >-
                    Enable multilingual support for the knowledgebase. When set
                    to `multilingual`, enables cross-lingual retrieval across
                    100+ languages. This allows you to upload documents in any
                    language and query them in any language. If not provided,
                    the default English-optimized configuration is used.
                  enum:
                    - multilingual
                  example: multilingual
      responses:
        '200':
          description: knowledgebase create status response
          content:
            application/json:
              schema:
                type: object
                properties:
                  rag_id:
                    type: string
                    description: The ID of the knowledgebase
                    format: ^[0-9a-fA-F]{32}$
                    example: 3c90c3xs0d444b5088228dd25736052a
                  file_name:
                    type: string
                    description: File name of the PDF uploaded or URL ingested
                    example: sample-rag.pdf
                  source_type:
                    type: string
                    description: Type of source ingested
                    enum:
                      - pdf
                      - url
                    example: pdf
                  status:
                    type: string
                    description: >-
                      Status of the knowledgebase. Initially the status would be
                      `processing`.
                    enum:
                      - processing
                      - processed
                      - error
                    example: processing
                  language_support:
                    type: string
                    description: >-
                      Language support mode of the knowledgebase. `multilingual`
                      if enabled, `null` otherwise.
                    nullable: true
                    enum:
                      - multilingual
                    example: multilingual
                required:
                  - rag_id
                  - file_name
                  - status
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