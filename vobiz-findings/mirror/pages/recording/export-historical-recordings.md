> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Export Historical Recordings

> Export Vobiz call recordings matching filter criteria as a downloadable archive delivered via email - async background job for bulk historical data retrieval.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/export/recording/
```

Export recordings matching your filter criteria. Recordings are packaged as a downloadable archive and sent via email. This is an asynchronous operation that processes in the background.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account auth\_id (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Note>
  **Async Operation Workflow:**

  1. Request is validated and queued as async task
  2. System processes recordings matching your filters
  3. Recordings are packaged as downloadable archive
  4. Download link is emailed to all recipient addresses
  5. Archive typically available within 15-60 minutes depending on volume
</Note>

<Warning>
  **Important:** Only one export request can run at a time per account. If an export is already in progress, you must wait for it to complete before starting a new one.
</Warning>

## Request Body

### Required Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `recipient.customer_account` | array | Yes | Array of email addresses to receive the download link. All emails must be in valid format. Example: `["admin@example.com", "user@example.com"]` |

### Date Range Filters (Option 1)

| Field | Type | Required | Description |
| - | - | - | - |
| `from` | string | No | Start date for export. Format: YYYY-MM-DD HH:MM:SS. Defaults to 7 days ago if not specified. |
| `to` | string | No | End date for export. Format: YYYY-MM-DD HH:MM:SS. Defaults to current time if not specified. |

### Storage Duration Filters (Option 2 - Alternative to Date Range)

| Field | Type | Required | Description |
| - | - | - | - |
| `recording_storage_duration` | string | No | Export recordings exactly N days old. Example: `"7"` = recordings from exactly 7 days ago. |
| `recording_storage_duration__gte` | string | No | Export recordings N days old or older. Example: `"7"` = recordings 7+ days old. |
| `recording_storage_duration__gt` | string | No | Export recordings older than N days. Example: `"7"` = recordings 8+ days old. |
| `recording_storage_duration__lte` | string | No | Export recordings N days old or newer. Example: `"30"` = recordings 0-30 days old. |
| `recording_storage_duration__lt` | string | No | Export recordings newer than N days. Example: `"30"` = recordings 0-29 days old. |

### Additional Filters (Only for ranges ≤ 30 days)

| Field | Type | Required | Description |
| - | - | - | - |
| `from_number` | string | No | Filter by caller phone number. |
| `to_number` | string | No | Filter by destination phone number. |
| `call_uuid` | string | No | Filter by call UUID (also use for conference\_uuid or mpc\_uuid). |
| `conference_name` | string | No | Filter by conference name (also use for mpc\_name). |
| `recording_format` | string | No | Filter by format. Values: "mp3", "wav". |
| `recording_id` | string | No | Filter by specific recording ID. |

<Info>
  Additional filters (`from_number`, `to_number`, etc.) only apply when your date range or storage duration range is 30 days or less.
</Info>

## Constraints & Validation

<Warning>
  * Cannot combine `from`/`to` with storage duration filters
  * Cannot use `__gt` and `__gte` together (choose one)
  * Cannot use `__lt` and `__lte` together (choose one)
  * Maximum date range: 1 year (366 days)
  * Maximum storage duration range: 30 days
  * Filters only apply for ranges ≤ 30 days
  * When using range filters (`__gte`/`__lte`), both must be provided
  * Only one export can run at a time per account
</Warning>

## Response

### Success Response (202 Accepted)

The export request has been queued and will be processed in the background.

```json Response - 202 Accepted theme={null}
{
    "api_id": "correlation-id-uuid",
    "status": "success"
}
```

### Error Response (403 Forbidden)

Another export is already in progress.

```json Response - 403 Forbidden theme={null}
{
    "status": "failure",
    "message": "An Export Historic Recording request is already in process. Please try again in sometime."
}
```

### Error Response (400 Bad Request)

Invalid request parameters.

```json Response - 400 Bad Request theme={null}
{
    "status": "failure",
    "message": "From/To cannot be used with recording storage duration"
}
```

## Examples

### Export Last 7 Days (Date Range)

```bash cURL theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/export/recording/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "2025-01-23 00:00:00",
    "to": "2025-01-30 23:59:59",
    "recipient": {
      "customer_account": ["admin@example.com"]
    }
  }'
```

### Export Using Storage Duration

Export recordings exactly 7 days old.

```bash cURL theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/export/recording/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "recording_storage_duration": "7",
    "recipient": {
      "customer_account": ["admin@example.com"]
    }
  }'
```

### Export with Storage Duration Range

Export recordings between 7 and 30 days old.

```bash cURL theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/export/recording/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "recording_storage_duration__gte": "7",
    "recording_storage_duration__lte": "30",
    "recipient": {
      "customer_account": ["admin@example.com"]
    }
  }'
```

### Export with Filters (Conference Recordings)

Export conference recordings in MP3 format from last 30 days.

```bash cURL theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/export/recording/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "2025-01-01 00:00:00",
    "to": "2025-01-30 23:59:59",
    "conference_name": "TeamMeeting",
    "recording_format": "mp3",
    "recipient": {
      "customer_account": ["admin@example.com", "backup@example.com"]
    }
  }'
```

### Export with Phone Number Filter

```bash cURL theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/export/recording/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "2025-01-15 00:00:00",
    "to": "2025-01-30 23:59:59",
    "from_number": "+14155551234",
    "recipient": {
      "customer_account": ["admin@example.com"]
    }
  }'
```

<Tip>
  **Use Cases:**

  * Backup recordings to external storage before deletion
  * Archive old recordings for compliance
  * Export specific conference recordings for review
  * Download recordings for specific phone numbers
  * Create monthly recording backups
</Tip>

<Info>
  For large date ranges (greater than 30 days), do not use additional filters. Export in smaller batches if you need filtered results.
</Info>

<Note>
  **Email Delivery:**

  * Check spam/junk folders if not received within 1 hour
  * Verify email addresses are valid before requesting
  * Use multiple recipients for redundancy
  * Wait for completion email before starting another export
</Note>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/export/recording/
openapi: 3.0.3
info:
  title: Vobiz API
  description: >
    The Vobiz API lets you make calls, manage phone numbers, configure SIP
    trunks, 

    and access account data programmatically.


    **Base URL:** `https://api.vobiz.ai`


    **Authentication:** Most requests require `X-Auth-ID` and `X-Auth-Token`
    headers.

    Selected account endpoints also accept an account access token as a Bearer
    token.

    Obtain account credentials from your [Vobiz
    Console](https://console.vobiz.ai).
  version: '1.0'
  contact:
    email: support@vobiz.ai
    url: https://vobiz.ai
servers:
  - url: https://api.vobiz.ai
    description: Production
security:
  - AuthID: []
    AuthToken: []
tags:
  - name: Account
    description: Manage your account details and credentials
  - name: Balance
    description: Retrieve balance and transaction history
  - name: Calls
    description: Make and manage outbound calls
  - name: Live Calls
    description: Retrieve and control in-progress calls
  - name: CDR
    description: Call detail records and history
  - name: Sub-Accounts
    description: Create and manage sub-accounts
  - name: Phone Numbers
    description: Manage phone numbers on your account
  - name: Trunks
    description: Configure SIP trunks for inbound and outbound calling
  - name: Conference
    description: Manage conference calls and members
  - name: Applications
    description: Manage voice and messaging applications with webhook URLs
  - name: Endpoints
    description: Manage SIP endpoints for IP phones, softphones, and SIP clients
  - name: Partner API
    description: >-
      Reseller and white-label endpoints for managing customer sub-accounts,
      balance transfers, transactions, CDRs, and DIDs across your partner
      ecosystem
  - name: Sub-Account KYC
    description: >-
      Per-sub-account KYC verification (PAN, GST, CIN, Aadhaar, DigiLocker) and
      hosted email/redirect KYC sessions. Authenticated as the parent main
      account.
  - name: Sub-Account KYC (Test Mode)
    description: >-
      Mock KYC endpoints that never call the upstream provider. Drive verified /
      failed / pending / error outcomes with magic inputs for integration
      testing.
  - name: Bulk Operations
    description: >-
      Endpoints that act on many records in one request. These accept the
      request, process it in the background, and deliver the result by email.
paths:
  /api/v1/Account/{auth_id}/export/recording/:
    post:
      tags:
        - Bulk Operations
      summary: Bulk export historical recordings
      description: >
        Queue a bulk export of the recordings matching your filter criteria. The
        request is

        validated and accepted for background processing, and the resulting
        archive is emailed

        as a download link to every address in `recipient.customer_account`. The
        archive is

        typically available within 15-60 minutes depending on volume.


        Results are delivered by email only; the export runs to completion in
        the background

        after the `202` response.


        One export runs at a time per account. While an export is in progress,
        further requests

        return `403`.


        Filter rules:

        - Use either `from`/`to` or the `recording_storage_duration*` filters,
        not both.

        - Use one of `__gt` or `__gte`, and one of `__lt` or `__lte`.

        - When using range filters (`__gte`/`__lte`), provide both.

        - Maximum date range is 1 year (366 days); maximum storage duration
        range is 30 days.

        - The additional filters (`from_number`, `to_number`, `call_uuid`,
        `conference_name`,
          `recording_format`, `recording_id`) apply when the range is 30 days or less.
      operationId: bulk-export-recordings
      parameters:
        - $ref: '#/components/parameters/AuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                recipient:
                  type: object
                  description: Email delivery targets for the export archive.
                  properties:
                    customer_account:
                      type: array
                      description: >-
                        Email addresses that receive the download link. All
                        addresses must be in valid format.
                      items:
                        type: string
                        format: email
                  required:
                    - customer_account
                from:
                  type: string
                  description: >-
                    Start date for the export. Format: YYYY-MM-DD HH:MM:SS.
                    Defaults to 7 days ago.
                  example: '2025-01-23 00:00:00'
                to:
                  type: string
                  description: >-
                    End date for the export. Format: YYYY-MM-DD HH:MM:SS.
                    Defaults to the current time.
                  example: '2025-01-30 23:59:59'
                recording_storage_duration:
                  type: string
                  description: >-
                    Export recordings exactly N days old. `"7"` exports
                    recordings from exactly 7 days ago.
                  example: '7'
                recording_storage_duration__gte:
                  type: string
                  description: >-
                    Export recordings N days old or older. `"7"` exports
                    recordings 7 days old and older.
                  example: '7'
                recording_storage_duration__gt:
                  type: string
                  description: >-
                    Export recordings older than N days. `"7"` exports
                    recordings 8 days old and older.
                  example: '7'
                recording_storage_duration__lte:
                  type: string
                  description: >-
                    Export recordings N days old or newer. `"30"` exports
                    recordings 0-30 days old.
                  example: '30'
                recording_storage_duration__lt:
                  type: string
                  description: >-
                    Export recordings newer than N days. `"30"` exports
                    recordings 0-29 days old.
                  example: '30'
                from_number:
                  type: string
                  description: >-
                    Filter by caller phone number. Applies when the range is 30
                    days or less.
                  example: '+14155551234'
                to_number:
                  type: string
                  description: >-
                    Filter by destination phone number. Applies when the range
                    is 30 days or less.
                call_uuid:
                  type: string
                  description: >-
                    Filter by call UUID. Also use this field for a
                    conference_uuid or mpc_uuid. Applies when the range is 30
                    days or less.
                conference_name:
                  type: string
                  description: >-
                    Filter by conference name. Also use this field for an
                    mpc_name. Applies when the range is 30 days or less.
                  example: TeamMeeting
                recording_format:
                  type: string
                  description: >-
                    Filter by recording format. Applies when the range is 30
                    days or less.
                  enum:
                    - mp3
                    - wav
                recording_id:
                  type: string
                  description: >-
                    Filter by a specific recording ID. Applies when the range is
                    30 days or less.
              required:
                - recipient
            examples:
              date-range:
                summary: Export the last 7 days by date range
                value:
                  from: '2025-01-23 00:00:00'
                  to: '2025-01-30 23:59:59'
                  recipient:
                    customer_account:
                      - admin@example.com
              storage-duration:
                summary: Export recordings exactly 7 days old
                value:
                  recording_storage_duration: '7'
                  recipient:
                    customer_account:
                      - admin@example.com
              storage-duration-range:
                summary: Export recordings between 7 and 30 days old
                value:
                  recording_storage_duration__gte: '7'
                  recording_storage_duration__lte: '30'
                  recipient:
                    customer_account:
                      - admin@example.com
              filtered:
                summary: Export MP3 conference recordings with multiple recipients
                value:
                  from: '2025-01-01 00:00:00'
                  to: '2025-01-30 23:59:59'
                  conference_name: TeamMeeting
                  recording_format: mp3
                  recipient:
                    customer_account:
                      - admin@example.com
                      - backup@example.com
      responses:
        '202':
          description: >-
            Export request queued. The archive download link is emailed to the
            recipients when processing completes.
          content:
            application/json:
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                  status:
                    type: string
              example:
                api_id: correlation-id-uuid
                status: success
        '400':
          description: >-
            Invalid request parameters, such as combining `from`/`to` with
            storage duration filters.
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  message:
                    type: string
              example:
                status: failure
                message: From/To cannot be used with recording storage duration
        '403':
          description: Another export is already in progress for this account.
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  message:
                    type: string
              example:
                status: failure
                message: >-
                  An Export Historic Recording request is already in process.
                  Please try again in sometime.
components:
  parameters:
    AuthId:
      name: auth_id
      in: path
      required: true
      description: Your account Auth ID
      schema:
        type: string
        example: MA_XXXXXX
  securitySchemes:
    AuthID:
      type: apiKey
      in: header
      name: X-Auth-ID
      description: Your Vobiz account Auth ID
    AuthToken:
      type: apiKey
      in: header
      name: X-Auth-Token
      description: Your Vobiz account Auth Token

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.