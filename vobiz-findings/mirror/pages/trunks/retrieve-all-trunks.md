> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve All Trunks

> Paginated list of all SIP trunks on your Vobiz account - view configurations, monitor rate limits, and manage global SIP trunking resources in one call.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks
```

Returns a paginated list of all trunks associated with your account. Use this endpoint to view trunk configurations, monitor resource usage, and manage multiple trunks.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Query Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `limit` | integer | No | Number of results per page. Default: `20`. Maximum: `100`. |
| `offset` | integer | No | Number of results to skip for pagination. Default: `0`. Use with `limit` for page navigation. |

## Request

<CodeGroup>
  ```bash cURL - Default Pagination theme={null}
  curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks" \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```

  ```bash cURL - Custom Pagination theme={null}
  curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks?limit=50&offset=0" \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```
</CodeGroup>

## Response

Returns a paginated list of trunk objects with metadata about pagination state.

```json Response - 200 OK theme={null}
{
  "meta": {
    "limit": 20,
    "offset": 0,
    "total": 2
  },
  "objects": [
    {
      "trunk_id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "account_id": "MA_XXXXXXXX",
      "name": "Acme Production Trunk",
      "trunk_domain": "aabbccdd-1234-5678-90ab-cdef12345678.sip.vobiz.ai",
      "trunk_status": "active",
      "secure": false,
      "trunk_direction": "outbound",
      "concurrent_calls_limit": 10,
      "cps_limit": 2,
      "credential_uuid": "aabbccdd-1234-5678-90ab-cdef12345679",
      "description": "",
      "transport": "udp",
      "recording": true,
      "enable_transcription": true,
      "pii_redaction": false,
      "webhook_method": "POST",
      "recording_webhook_enabled": false,
      "created_at": "2026-04-22T08:52:02.383938Z",
      "updated_at": "2026-04-29T06:45:15.188437Z"
    },
    {
      "trunk_id": "aabbccdd-1234-5678-90ab-cdef1234567a",
      "account_id": "MA_XXXXXXXX",
      "name": "My Outbound Trunk",
      "trunk_domain": "aabbccdd-1234-5678-90ab-cdef1234567a.sip.vobiz.ai",
      "trunk_status": "active",
      "secure": false,
      "trunk_direction": "inbound",
      "concurrent_calls_limit": 10,
      "cps_limit": 2,
      "primary_uri_uuid": "aabbccdd-1234-5678-90ab-cdef1234567b",
      "description": "",
      "inbound_destination": "aabbccdd-1234-5678-90ab-cdef1234567b",
      "transport": "udp",
      "recording": true,
      "enable_transcription": true,
      "pii_redaction": false,
      "webhook_method": "POST",
      "recording_webhook_enabled": false,
      "created_at": "2026-04-17T10:28:06.112095Z",
      "updated_at": "2026-04-22T05:35:51.255094Z"
    }
  ]
}
```

<Info>
  **Pagination Tip:** Use `total` from the meta object to calculate total pages. For page 2 with limit 10, use `offset=10`.
</Info>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/trunks
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
  /api/v1/Account/{auth_id}/trunks:
    get:
      tags:
        - Trunks
      summary: List trunks
      description: Retrieve all SIP trunks configured on the account.
      operationId: list-trunks
      parameters:
        - $ref: '#/components/parameters/AuthId'
      responses:
        '200':
          description: List of trunks
          content:
            application/json:
              example:
                meta:
                  limit: 20
                  offset: 0
                  total: 2
                objects:
                  - trunk_id: aabbccdd-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    name: My Outbound Trunk
                    trunk_domain: aabbccdd-1234-5678-90ab-cdef12345678.sip.vobiz.ai
                    trunk_status: active
                    secure: false
                    trunk_direction: outbound
                    concurrent_calls_limit: 10
                    cps_limit: 2
                    credential_uuid: 11223344-5566-7788-99aa-bbccddeeff00
                    description: ''
                    transport: udp
                    recording: true
                    enable_transcription: true
                    pii_redaction: false
                    webhook_method: POST
                    recording_webhook_enabled: false
                    created_at: '2026-03-25T08:52:02.383938Z'
                    updated_at: '2026-03-25T08:52:02.383938Z'
                  - trunk_id: 99887766-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    name: Acme Production Trunk
                    trunk_domain: 99887766-1234-5678-90ab-cdef12345678.sip.vobiz.ai
                    trunk_status: active
                    secure: false
                    trunk_direction: inbound
                    concurrent_calls_limit: 10
                    cps_limit: 2
                    primary_uri_uuid: 55667788-1234-5678-90ab-cdef12345678
                    description: ''
                    inbound_destination: 55667788-1234-5678-90ab-cdef12345678
                    transport: udp
                    recording: true
                    enable_transcription: true
                    pii_redaction: false
                    pii_entity_types: ''
                    webhook_url: https://webhook.site/example
                    webhook_method: POST
                    recording_webhook_enabled: false
                    created_at: '2026-03-25T10:28:06.112095Z'
                    updated_at: '2026-03-25T10:28:06.112095Z'
              schema:
                type: object
                properties:
                  meta:
                    type: object
                    properties:
                      limit:
                        type: integer
                      offset:
                        type: integer
                      total:
                        type: integer
                    required:
                      - limit
                      - offset
                      - total
                  objects:
                    type: array
                    items:
                      type: object
                      properties:
                        trunk_id:
                          type: string
                        account_id:
                          type: string
                        name:
                          type: string
                        trunk_domain:
                          type: string
                        trunk_status:
                          type: string
                        secure:
                          type: boolean
                        trunk_direction:
                          type: string
                        concurrent_calls_limit:
                          type: integer
                        cps_limit:
                          type: integer
                        credential_uuid:
                          type: string
                        description:
                          type: string
                        transport:
                          type: string
                        recording:
                          type: boolean
                        enable_transcription:
                          type: boolean
                        pii_redaction:
                          type: boolean
                        webhook_method:
                          type: string
                        recording_webhook_enabled:
                          type: boolean
                        created_at:
                          type: string
                        updated_at:
                          type: string
                        primary_uri_uuid:
                          type: string
                        inbound_destination:
                          type: string
                        pii_entity_types:
                          type: string
                        webhook_url:
                          type: string
                      required:
                        - trunk_id
                        - account_id
                        - name
                        - trunk_domain
                        - trunk_status
                        - secure
                        - trunk_direction
                        - concurrent_calls_limit
                        - cps_limit
                        - description
                        - transport
                        - recording
                        - enable_transcription
                        - pii_redaction
                        - webhook_method
                        - recording_webhook_enabled
                        - created_at
                        - updated_at
                required:
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