> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve a Trunk

> Fetch full configuration of a single Vobiz SIP trunk by ID - rate limits, auth mode, SIP domain, and attached credentials, IP ACLs, and origination URIs.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/{trunk_id}
```

Retrieves the complete details of a specific trunk by its unique `trunk_id`. Use this endpoint to verify trunk configuration, check rate limits, or confirm the trunk's enabled status.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Request

```bash cURL theme={null}
curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/bfab10fb-cb97-488b-9c63-989c32980b0f \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

## Response

Returns the complete trunk object with all attributes.

```json Response - 200 OK theme={null}
{
  "trunk_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "name": "Acme Production Trunk",
  "trunk_domain": "aabbccdd-1234-5678-90ab-cdef12345678.sip.vobiz.ai",
  "trunk_status": "active",
  "secure": false,
  "trunk_direction": "both",
  "concurrent_calls_limit": 10,
  "cps_limit": 2,
  "description": "",
  "transport": "udp",
  "recording": false,
  "enable_transcription": false,
  "pii_redaction": false,
  "webhook_method": "POST",
  "recording_webhook_enabled": false,
  "created_at": "2026-05-12T05:11:52.054462Z",
  "updated_at": "2026-05-12T05:11:52.054462Z"
}
```

<Note>
  **Error Response (404):** If the `trunk_id` does not exist or does not belong to your account, the API returns a 404 Not Found error.
</Note>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/trunks/{trunk_id}
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
  /api/v1/Account/{auth_id}/trunks/{trunk_id}:
    get:
      tags:
        - Trunks
      summary: Retrieve a trunk
      description: Get details of a specific SIP trunk.
      operationId: retrieve-trunk
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: trunk_id
          in: path
          required: true
          schema:
            type: string
            example: trunk_XXXXXX
      responses:
        '200':
          description: Trunk details
          content:
            application/json:
              schema:
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
              example:
                trunk_id: 11223344-1234-5678-90ab-cdef12345678
                account_id: MA_XXXXXXXX
                name: Acme Production Trunk
                trunk_domain: 11223344-1234-5678-90ab-cdef12345678.sip.vobiz.ai
                trunk_status: active
                secure: false
                trunk_direction: both
                concurrent_calls_limit: 10
                cps_limit: 2
                description: ''
                transport: udp
                recording: false
                enable_transcription: false
                pii_redaction: false
                webhook_method: POST
                recording_webhook_enabled: false
                created_at: '2026-03-25T10:00:00Z'
                updated_at: '2026-03-25T10:00:00Z'
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