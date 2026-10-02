> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List All Recordings

> Retrieve a paginated list of Vobiz call recordings with filters for recording type, trunk, or extension - for archival, compliance, and quality assurance.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/
```

Retrieve a paginated list of call recordings for your account. Filter by call UUID or recording type, and page through results with `limit` and `offset`.

<Warning>
  Pagination here is **offset-based** (`limit` + `offset`), not page-based. This differs from the [CDR list](/docs/cdr/list-cdrs), which uses `page` + `per_page`. To get the next page, add `limit` to `offset` (page 2 of 20 = `offset=20`), or follow the ready-made `meta.next` URL in the response.
</Warning>

<Info>
  **Use Cases:** Retrieve recordings for archival, compliance, quality assurance, or to provide playback links to customers. The response includes recording IDs, call IDs for cross-referencing with CDRs, and download URLs.
</Info>

<Warning>
  **Case Sensitivity Notice:** Note that `Account` and `Recording` are capitalized in the URL path. Some APIs are case-sensitive, so ensure the capitalization matches exactly.
</Warning>

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `MA_XXXXXXXX`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Query Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `limit` | integer | No | The number of recording records to return in one request (default: 20, max: 100). |
| `offset` | integer | No | Where to start the list for pagination. Set to 20 to see the next page after the first 20 results (default: 0). |
| `call_uuid` | string | No | Filter recordings by a specific call UUID. Returns only recordings associated with the given call. Use this to cross-reference a CDR with its recordings. |
| `recording_type` | string | No | Filter by recording type. Observed values: `call` (regular call leg), `conference`, and `trunk` (trunk-level capture). |

## Response

A successful request returns a `200 OK` status with a JSON array of recording objects.

```json Success Response - 200 OK theme={null}
{
  "api_id": "319ab584-cfc4-452c-a0ea-2f2f2f506a20",
  "meta": {
    "limit": 20,
    "next": "/v1/Account/MA_XXXXXXXX/Recording/?limit=20&offset=20",
    "offset": 0,
    "previous": null,
    "total_count": 721
  },
  "objects": [
    {
      "add_time": "2026-05-07 09:45:35.79276+05:30",
      "call_uuid": "11223344-5566-7788-99aa-bbccddeeff00",
      "conference_name": null,
      "from_number": "+919876543210",
      "monthly_recording_storage_amount": 0,
      "recording_duration_ms": "7880.00000",
      "recording_end_ms": null,
      "recording_format": "wav",
      "recording_id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "recording_start_ms": null,
      "recording_storage_duration": 6,
      "recording_storage_rate": 0.005,
      "recording_type": "trunk",
      "recording_url": "https://recordings.vobiz.ai/example/abc123.mp3",
      "resource_uri": "/v1/Account/MA_XXXXXXXX/Recording/aabbccdd-1234-5678-90ab-cdef12345678/",
      "rounded_recording_duration": 60,
      "to_number": "+918012345678"
    },
    {
      "add_time": "2026-05-02 10:12:39.347981+05:30",
      "call_uuid": "11223344-5566-7788-99aa-bbccddeeff00",
      "conference_name": "",
      "from_number": "+919876543210",
      "monthly_recording_storage_amount": 0,
      "recording_duration_ms": "31040.00000",
      "recording_end_ms": "1777696958218.00000",
      "recording_format": "mp3",
      "recording_id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "recording_start_ms": "1777696927178.00000",
      "recording_storage_duration": 11,
      "recording_storage_rate": 0.005,
      "recording_type": "call",
      "recording_url": "https://recordings.vobiz.ai/example/abc123.mp3",
      "resource_uri": "/v1/Account/MA_XXXXXXXX/Recording/aabbccdd-1234-5678-90ab-cdef12345678/",
      "rounded_recording_duration": 60,
      "to_number": "+918012345678"
    }
  ]
}
```

### Response Fields

* `recording_id` - Unique identifier for the recording (used for download)
* `call_uuid` - Cross-reference with CDR records
* `recording_url` - Link to the actual audio file (MP3/WAV)
* `add_time` - Timestamp when the recording was added
* `recording_duration_ms` - Recording length in milliseconds
* `rounded_recording_duration` - Recording length rounded up (seconds, billing basis)
* `recording_format` - File format (`mp3` or `wav`)
* `recording_type` - Type of recording (`call`, `conference`, or `trunk`)
* `from_number` / `to_number` - Caller and callee numbers on the call
* `resource_uri` - Canonical API path for the recording resource
* `meta` - Pagination metadata (`limit`, `offset`, `next`, `previous`, `total_count`)

## Examples

### cURL - List Trunk Recordings

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/?limit=20&offset=0&recording_type=trunk" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json"
```

### cURL - Filter by Call UUID

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/MA_XXXXXXXX/Recording/?call_uuid=7f8e9d2c-1a3b-4c5d-6e7f-8g9h0i1j2k3l" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: your_auth_token" \
  -H "Content-Type: application/json"
```

### Generic Template (Use Your Own Values)

```bash cURL Template theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/?limit={LIMIT}&offset={OFFSET}&recording_type={TYPE}" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json"
```

### Parameter Quick Reference

| Parameter | Example | Description |
| - | - | - |
| `limit` | 20 | Number of records to return |
| `offset` | 0 | Starting position (0 for first page, 20 for second, etc.) |
| `call_uuid` | 7f8e9d2c-1a3b-4c5d-6e7f-8g9h0i1j2k3l | Filter recordings for a specific call |
| `recording_type` | call | Filter by type: `call`, `conference`, or `trunk` |

<Tip>
  **Quick Tips:**

  * **Pagination:** Use `offset` to navigate through pages (offset = page × limit), or follow `meta.next`.
  * **Recording Type:** Filter by `call`, `conference`, or `trunk` to get specific recording types.
  * **Case Sensitive:** Ensure `Account` and `Recording` are capitalized in the URL.
  * **Filter by Call:** Use `call_uuid` to get recordings for a specific call.
  * **Cross-Reference:** Match a recording's `call_uuid` against a CDR's `uuid` to tie audio to call metadata.
</Tip>

## Edge cases

* **Empty account / no matches:** returns `200` with `objects: []` and `meta.total_count: 0` - not a `404`.
* **Last page:** `meta.next` is `null` once you reach the end; stop paging when it is `null`.
* **Timestamp fields:** `recording_start_ms` / `recording_end_ms` can be `null` (e.g. for some `trunk` captures); `recording_duration_ms` is a string of milliseconds. `rounded_recording_duration` is the integer-seconds value used for billing.
* **No cross-account access:** this endpoint returns recordings for the `auth_id` in the path only.

<Info>
  **Next Steps:**

  * Use the `recording_id` to [retrieve](/docs/recording/retrieve-recording) or [download](/docs/recording/download-recording) a specific recording.
  * Cross-reference with CDR data via `call_uuid` ↔ CDR `uuid` for complete call information.
  * Store recording URLs for playback or archival purposes.
  * Implement offset pagination (or follow `meta.next`) to retrieve all recordings efficiently.
</Info>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Recording/
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
  /api/v1/Account/{auth_id}/Recording/:
    get:
      tags:
        - Recordings
      summary: List recordings
      description: Retrieve all call recordings on the account.
      operationId: list-recordings
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
        - name: offset
          in: query
          schema:
            type: integer
            default: 0
      responses:
        '200':
          description: List of recordings
          content:
            application/json:
              example:
                objects:
                  - recording_id: rec_XXXXXXXXXX
                    recording_url: https://storage.vobiz.ai/recordings/rec_XXXXXXXXXX.mp3
                    duration: 120
                    file_format: mp3
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                  meta:
                    type: object
                    properties:
                      limit:
                        type: integer
                      next:
                        type: string
                      offset:
                        type: integer
                      previous:
                        nullable: true
                      total_count:
                        type: integer
                    required:
                      - limit
                      - next
                      - offset
                      - previous
                      - total_count
                  objects:
                    type: array
                    items:
                      type: object
                      properties:
                        add_time:
                          type: string
                        call_uuid:
                          type: string
                        conference_name:
                          type: string
                          nullable: true
                        from_number:
                          type: string
                        monthly_recording_storage_amount:
                          type: integer
                        recording_duration_ms:
                          type: string
                        recording_end_ms:
                          type: string
                          nullable: true
                        recording_format:
                          type: string
                        recording_id:
                          type: string
                        recording_start_ms:
                          type: string
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
                required:
                  - api_id
                  - meta
                  - objects
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