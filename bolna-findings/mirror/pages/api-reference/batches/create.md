> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Batch API

> Discover how to create a batch for Bolna Voice AI agent by uploading a CSV file containing user contact numbers and prompt variable details for users.

Creates a new batch campaign by uploading a CSV of recipients. Returns HTTP **201** with a `batch_id`. The batch does not start calling until you call `POST /batches/{batch_id}/schedule`.

## CSV format

```csv theme={"system"}
contact_number,customer_name,appointment_day
+919876543210,Asha,Friday
+919812345678,Ravi,Monday
```

* `contact_number` is **required** — E.164 format
* Any other column becomes a `{variable}` available in your agent's prompt and welcome message
* The per-call execution stores these columns in `context_details.recipient_data`

## Example request

Use `multipart/form-data` — **not** JSON.

```bash curl theme={"system"}
curl https://api.bolna.ai/batches \
  -H "Authorization: Bearer $BOLNA_API_KEY" \
  -F "agent_id=123e4567-e89b-12d3-a456-426655440000" \
  -F "file=@recipients.csv"
```

```python Python (stdlib) theme={"system"}
import os, urllib.request
from io import BytesIO

# See public/examples/bolna_batch_test.py for a complete implementation
```

```json 201 Response theme={"system"}
{
  "batch_id": "3c90c3cc0d444b5088888dd25736052a",
  "state": "created"
}
```

## Next step: schedule the batch

A created batch is idle until scheduled. Call `POST /batches/{batch_id}/schedule` with a `scheduled_at` timestamp:

```json Schedule request (form-data) theme={"system"}
scheduled_at=2026-06-23T18:30:00+00:00
```

<Warning>
  Use a **numeric UTC offset** like `+00:00` — the `Z` suffix is rejected with a 500. The time must be at least 2 minutes in the future, and Bolna rounds the start up to the next 10-minute mark.
</Warning>

See the [Batch Quickstart](/docs/quickstarts/batch) for a complete walk-through including scheduling and result retrieval.


## OpenAPI

````yaml POST /batches
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
  /batches:
    post:
      description: Create batch for agent
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                agent_id:
                  type: string
                  format: uuid
                  description: The ID of the agent
                file:
                  type: string
                  format: binary
                  description: CSV file to upload
                from_phone_numbers:
                  type: array
                  items:
                    type: string
                  description: >-
                    List of phone numbers from which the batch calls will be
                    made. Each number must include the country code in
                    [E.164](https://en.wikipedia.org/wiki/E.164) format. Pass
                    multiple values to use multiple originating numbers.
                  example:
                    - '+919876543210'
                    - '+919876543211'
                retry_config:
                  type: string
                  description: >-
                    JSON string containing retry configuration for failed calls.
                    See [auto-retry documentation](/auto-retry) for details.
                    Example -
                    `{"enabled":true,"max_retries":2,"retry_intervals_minutes":[15,30]}`
                webhook_url:
                  type: string
                  format: uri
                  description: >-
                    URL that Bolna POSTs the batch payload to when the batch
                    finishes processing, and again when all of its executions
                    reach a terminal state. Use it to receive the batch's
                    executions without polling. Must be a valid URL; an invalid
                    value is ignored and no webhook is sent.
                  example: https://your-server.com/batch-webhook
              required:
                - agent_id
                - file
      responses:
        '201':
          description: batch created response
          content:
            application/json:
              schema:
                type: object
                properties:
                  batch_id:
                    type: string
                    description: The ID of the batch
                    format: ^[0-9a-fA-F]{32}$
                    example: 3c90c3cc0d444b5088888dd25736052a
                  state:
                    type: string
                    description: Status of the request
                    enum:
                      - created
                required:
                  - batch_id
                  - state
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