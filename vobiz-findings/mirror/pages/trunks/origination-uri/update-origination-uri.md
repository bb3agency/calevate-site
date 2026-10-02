> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Origination URI

> Update a Vobiz origination URI - change SIP destination, routing priority, load-balancing weight, or enabled state with a partial PUT; no re-creation needed.

```http theme={null}
PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris/{uri_id}
```

Updates an existing origination URI. You can modify the SIP destination, adjust priority and weight for routing optimization, or enable/disable the URI without deleting it. All fields are optional - include only the fields you want to change.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Common Use Cases:**

  * Change URI priority to implement failover strategies or promote a backup URI to primary
  * Adjust weights to rebalance traffic distribution across multiple carriers
  * Update the SIP destination when switching carriers or changing server addresses
  * Temporarily disable a URI (`enabled: false`) without deleting it for maintenance windows
</Info>

## Request Parameters

Send both fields on every update - this is a replace, not a partial patch. To keep the current label, resend it.

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | Yes | Label for the destination. Surfaces as `description` on the returned object. |
| `priority` | integer | Yes | Routing priority (lower = higher priority). Adjust to promote or demote a URI in the failover hierarchy. |

<Note>
  **What this endpoint cannot change.** The SIP destination (`uri`), `weight`, and `enabled` are not part of the update body. To point at a different carrier or host, delete the URI and [create a new one](/docs/trunks/origination-uri/create-origination-uri). To rebalance `weight` or toggle `enabled`, use the Console.
</Note>

## Response

Returns the complete origination URI object with updated values and a new `updated_at` timestamp.

```json Response - 200 OK theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "uri": "sip:provider@sip.example.com:5060",
  "priority": 1,
  "weight": 10,
  "enabled": true,
  "transport": "udp",
  "description": "Primary SBC",
  "created_at": "2026-05-12T05:11:51.914686Z",
  "updated_at": "2026-05-12T05:11:51.964357Z"
}
```

## Examples

### cURL - Promote a backup to primary

Change a backup URI from priority 2 to priority 1 (resend its `name`):

```bash cURL Request theme={null}
curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris/aabbccdd-1234-5678-90ab-cdef12345678 \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Backup SBC",
    "priority": 1
  }'
```

### cURL - Demote a primary to failover

```bash cURL Request theme={null}
curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris/aabbccdd-1234-5678-90ab-cdef12345678 \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Primary SBC",
    "priority": 3
  }'
```

<Tip>
  **Failover Strategy:**

  * Promote a backup to primary by lowering its `priority` to 1, then raise the failed carrier's number so it becomes the fallback.
  * To switch SIP destinations entirely, create the new URI first, confirm calls route through it, then delete the old one.
</Tip>


## OpenAPI

````yaml PUT /api/v1/Account/{auth_id}/origination-uris/{uri_id}
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
  /api/v1/Account/{auth_id}/origination-uris/{uri_id}:
    put:
      tags:
        - Origination URI
      summary: Update an origination URI
      description: Update an existing origination URI.
      operationId: update-origination-uri
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: uri_id
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
              properties:
                name:
                  type: string
                priority:
                  type: integer
              required:
                - name
                - priority
      responses:
        '200':
          description: Origination URI updated
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  account_id:
                    type: string
                  uri:
                    type: string
                  priority:
                    type: integer
                  weight:
                    type: integer
                  enabled:
                    type: boolean
                  transport:
                    type: string
                  description:
                    type: string
                  created_at:
                    type: string
                  updated_at:
                    type: string
                required:
                  - id
                  - account_id
                  - uri
                  - priority
                  - weight
                  - enabled
                  - transport
                  - description
                  - created_at
                  - updated_at
              example:
                id: aabbccdd-1234-5678-90ab-cdef12345678
                account_id: MA_XXXXXXXX
                uri: sip:sbc1.example.com
                priority: 2
                weight: 10
                enabled: true
                transport: TCP
                description: Primary SBC
                created_at: '2026-03-25T10:00:00Z'
                updated_at: '2026-03-25T11:30:00Z'
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