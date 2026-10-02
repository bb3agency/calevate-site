> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve a Recording

> Fetch full metadata for a specific Vobiz call recording by ID - file URL, duration, format, associated call UUID, and storage billing.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/{recording_id}/
```

Retrieve the details of a specific recording by its recording ID. The response includes complete information about the recording file, associated call details, storage duration, and billing.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account auth\_id (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Note>
  You can obtain the `recording_id` from the List All Recordings endpoint or from webhook notifications when recordings are created.
</Note>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your account ID. |
| `recording_id` | string | Yes | The unique recording identifier. |

## Response

Returns a complete Recording object with all attributes if the recording ID is valid. The single-recording response is a **flat object** (the fields are at the top level), unlike the [List All Recordings](/docs/recording/list-all-recordings) response, which wraps each recording inside `meta` + `objects[]`.

```json Response - 200 OK theme={null}
{
    "add_time": "2025-11-06 13:49:10.751756+00:00",
    "api_id": "668470b7-7a8f-49b6-9011-50075754a50a",
    "call_uuid": "6e558798-499c-4a68-bc77-46f2c53d1f69",
    "conference_name": null,
    "from_number": "+918071387423",
    "monthly_recording_storage_amount": 0,
    "recording_duration_ms": "10080.00000",
    "recording_end_ms": "1762436949502.00000",
    "recording_format": "mp3",
    "recording_id": "d7801b2e-e76d-4dd8-be9c-9e015a7267b8",
    "recording_start_ms": "1762436939422.00000",
    "recording_storage_duration": 1,
    "recording_storage_rate": 0.005,
    "recording_type": "call",
    "recording_url": "https://media.vobiz.ai/api/v1/Account/MA_PU0XU668/Recording/d7801b2e-e76d-4dd8-be9c-9e015a7267b8.mp3",
    "resource_uri": "/v1/Account/MA_PU0XU668/Recording/d7801b2e-e76d-4dd8-be9c-9e015a7267b8/",
    "rounded_recording_duration": 60,
    "to_number": "919624705678"
}
```

```json Response - 404 Not Found theme={null}
{
    "api_id": "correlation-id-uuid",
    "error": "Recording not found"
}
```

<Note>
  Because the body is flat, extract fields directly - e.g. `jq -r '.recording_url'`. There is no `objects[0]` wrapper on this endpoint.
</Note>

## Examples

### cURL Request

```bash cURL theme={null}
curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/abc123def456/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

### Download Recording File

Use the `recording_url` from the response to download the actual audio file. For a complete step-by-step guide including authentication details and troubleshooting, see the [Download Recording Guide](/docs/recording/download-recording).

### Using jq to Extract URL

```bash Bash Script with jq theme={null}
# Get recording URL and download in one command
RECORDING_URL=$(curl -s -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/abc123def456/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  | jq -r '.recording_url')

curl -o recording.mp3 "$RECORDING_URL"
```

<Tip>
  **Use Cases:**

  * Verify recording details before downloading
  * Check storage duration for billing purposes
  * Confirm recording format (MP3 vs WAV)
  * Get the download URL for archiving
  * Validate recording metadata (call\_uuid, phone numbers)
</Tip>

<Info>
  The `recording_url` provides direct access to the audio file and can be used in media players or downloaded programmatically. These URLs may be temporary, so download recordings promptly for permanent storage.
</Info>

<Warning>
  **Important:** Always check the `api_id` field in responses for correlation and debugging purposes. This ID is useful when contacting support about specific requests.
</Warning>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Recording/{recording_id}/
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
  /api/v1/Account/{auth_id}/Recording/{recording_id}/:
    get:
      tags:
        - Recordings
      summary: Retrieve a recording
      description: Get details and download URL for a specific recording.
      operationId: get-recording
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: recording_id
          in: path
          required: true
          schema:
            type: string
            example: rec_XXXXXXXXXX
      responses:
        '200':
          description: Recording details
          content:
            application/json:
              schema:
                type: object
                properties:
                  add_time:
                    type: string
                  api_id:
                    type: string
                  call_uuid:
                    type: string
                  conference_name:
                    nullable: true
                  from_number:
                    type: string
                  monthly_recording_storage_amount:
                    type: integer
                  recording_duration_ms:
                    type: string
                  recording_end_ms:
                    nullable: true
                  recording_format:
                    type: string
                  recording_id:
                    type: string
                  recording_start_ms:
                    nullable: true
                  recording_storage_duration:
                    type: integer
                  recording_storage_rate:
                    type: number
                  recording_type:
                    type: string
                  recording_url:
                    type: string
                  resource_uri:
                    type: string
                  rounded_recording_duration:
                    type: integer
                  to_number:
                    type: string
                required:
                  - add_time
                  - api_id
                  - call_uuid
                  - conference_name
                  - from_number
                  - monthly_recording_storage_amount
                  - recording_duration_ms
                  - recording_end_ms
                  - recording_format
                  - recording_id
                  - recording_start_ms
                  - recording_storage_duration
                  - recording_storage_rate
                  - recording_type
                  - recording_url
                  - resource_uri
                  - rounded_recording_duration
                  - to_number
              example:
                add_time: '2026-03-25 10:00:00.000000+05:30'
                api_id: 55667788-1234-5678-90ab-cdef12345678
                call_uuid: 55667788-1234-5678-90ab-cdef12345678
                conference_name: null
                from_number: '+919876543210'
                monthly_recording_storage_amount: 0
                recording_duration_ms: '7880.00000'
                recording_end_ms: null
                recording_format: wav
                recording_id: 55667788-1234-5678-90ab-cdef12345678
                recording_start_ms: null
                recording_storage_duration: 6
                recording_storage_rate: 0.005
                recording_type: trunk
                recording_url: https://recordings.vobiz.ai/example/abc123.mp3
                resource_uri: >-
                  /v1/Account/MA_XXXXXXXX/Recording/55667788-1234-5678-90ab-cdef12345678/
                rounded_recording_duration: 60
                to_number: '+918012345678'
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