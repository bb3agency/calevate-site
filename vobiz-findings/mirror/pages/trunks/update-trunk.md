> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update a Trunk

> Modify an existing Vobiz SIP trunk - update name, description, concurrent-call limits, CPS caps, or webhook URL without recreating the trunk resource.

```http theme={null}
PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/{trunk_id}
```

Use this endpoint to update the configuration of an existing trunk. You can modify the name, description, and rate limits. Include only the fields you want to update; other fields will remain unchanged.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Note:** `trunk_id` and `auth_id` cannot be changed after creation.
</Warning>

## Request Parameters

Send all three fields on every update - this is a replace, not a partial patch. To keep a value unchanged, resend its current value (fetch it first with [Retrieve a Trunk](/docs/trunks/retrieve-trunk)).

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | Yes | Name for the trunk. Maximum 255 characters. |
| `max_concurrent_calls` | integer | Yes | Maximum number of simultaneous calls. Surfaces as `concurrent_calls_limit` on the trunk object. |
| `enabled` | boolean | Yes | Whether the trunk is active. Set to `false` to disable without deleting. |

## Examples

<CodeGroup>
  ```bash cURL - Rename the trunk theme={null}
  curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/bfab10fb-cb97-488b-9c63-989c32980b0f \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Updated Production Trunk",
      "max_concurrent_calls": 10,
      "enabled": true
    }'
  ```

  ```bash cURL - Disable the trunk theme={null}
  curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/bfab10fb-cb97-488b-9c63-989c32980b0f \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Acme Production Trunk",
      "max_concurrent_calls": 10,
      "enabled": false
    }'
  ```

  ```bash cURL - Raise the concurrent-call limit theme={null}
  curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/bfab10fb-cb97-488b-9c63-989c32980b0f \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Acme Production Trunk",
      "max_concurrent_calls": 25,
      "enabled": true
    }'
  ```
</CodeGroup>

## Response

Returns the complete trunk object with updated values and a new `updated_at` timestamp.

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
  "updated_at": "2026-05-12T05:12:18.147340Z"
}
```

<Tip>
  **Best Practice:** Disable a trunk instead of deleting it if you might need the configuration later. Disabled trunks do not handle calls but preserve all settings, credentials, and routing rules.
</Tip>


## OpenAPI

````yaml PUT /api/v1/Account/{auth_id}/trunks/{trunk_id}
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
    put:
      tags:
        - Trunks
      summary: Update a trunk
      description: Update a SIP trunk's name, configuration, or status.
      operationId: update-trunk
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: trunk_id
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              description: >-
                All fields are optional - send only what you want to change.
                Does not accept `username`/`password` (rotate credentials via
                the credentials subresource endpoint).
              properties:
                name:
                  type: string
                  maxLength: 100
                trunk_direction:
                  type: string
                  enum:
                    - inbound
                    - outbound
                  description: Direction of the trunk - `inbound` or `outbound` only.
                trunk_status:
                  type: string
                  enum:
                    - enabled
                    - disabled
                secure:
                  type: boolean
                trunk_domain:
                  type: string
                  maxLength: 255
                transport:
                  type: string
                  enum:
                    - udp
                    - tcp
                    - tls
                inbound_destination:
                  type: string
                  maxLength: 255
                description:
                  type: string
                  maxLength: 500
                concurrent_calls_limit:
                  type: integer
                  minimum: 0
                  maximum: 1000
                cps_limit:
                  type: integer
                  minimum: 0
                  maximum: 100
                credential_uuid:
                  type: string
                ipacl_uuid:
                  type: string
                primary_uri_uuid:
                  type: string
                fallback_uri_uuid:
                  type: string
                recording:
                  type: boolean
                enable_transcription:
                  type: boolean
                pii_redaction:
                  type: boolean
                pii_entity_types:
                  type: string
                webhook_url:
                  type: string
                  maxLength: 500
                  description: >-
                    Customer webhook for call-admission events (`CallInitiated`
                    / `Hangup`). Public http/https URL; SSRF-validated. See
                    [Trunk Webhooks](/trunks/webhook).
                webhook_method:
                  type: string
                  enum:
                    - POST
                    - GET
                  default: POST
                recording_webhook_enabled:
                  type: boolean
      responses:
        '200':
          description: Trunk updated
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
                trunk_id: 99887766-1234-5678-90ab-cdef12345678
                account_id: MA_XXXXXXXX
                name: Acme Production Trunk Updated
                trunk_domain: 99887766-1234-5678-90ab-cdef12345678.sip.vobiz.ai
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
                updated_at: '2026-03-25T10:05:00Z'
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