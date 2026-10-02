> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Origination URI

> Add a SIP destination URI to your Vobiz trunk for outbound routing - set priority and weight for load balancing and carrier failover across 130+ countries.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris
```

Creates a new origination URI (SIP destination) for routing outbound calls from your trunk. The URI must be a valid SIP endpoint in the format `sip:user@host:port` or `sip:host:port`.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Valid SIP URI Formats:** The URI must start with the `sip:` scheme. A port is optional - the default SIP port (`5060`) is assumed when omitted.

  * `sip:sbc.example.com` - Host only (default port)
  * `sip:provider@sip.example.com:5060` - Host with user and explicit port
  * `sip:192.168.1.100:5060` - IP address with port
  * `sip:trunk@sip.carrier.net:5061` - Custom port

  **Invalid Formats:**

  * `http://sip.example.com` - Wrong scheme
  * `provider@sip.example.com:5060` - Missing `sip:` prefix
</Warning>

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | Yes | Label for the destination, such as "Primary SBC" or "US East carrier". Surfaces as `description` on the returned object. |
| `sip_uri` | string | Yes | SIP URI destination, e.g. `sip:provider@sip.example.com:5060` or `sip:sbc.example.com`. Returned on the object as `uri`. |
| `priority` | integer | Yes | Routing priority (lower = higher priority). Use priority `1` for primary routes and `2`+ for backup/failover routes. |

<Note>
  **`weight` and `transport` are set after creation.** New URIs default to `weight: 10` and an inferred `transport`. To split traffic across same-priority URIs (load balancing) or change priority later, use [Update Origination URI](/docs/trunks/origination-uri/update-origination-uri) or the Console. The create endpoint accepts only `name`, `sip_uri`, and `priority`.
</Note>

## Response

Returns the complete origination URI object, including the auto-generated `id` UUID and timestamps.

```json Response - 201 Created theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "uri": "sip:provider@sip.example.com:5060",
  "priority": 1,
  "weight": 10,
  "enabled": true,
  "transport": "udp",
  "description": "Primary SBC",
  "created_at": "2026-05-12T05:11:51.914685Z",
  "updated_at": "2026-05-12T05:11:51.914685Z"
}
```

<Note>
  **Field name change between request and response.** You send `sip_uri` and `name`; the response returns them as `uri` and `description`. The `weight` and `transport` fields appear on the response with their defaults even though you cannot set them at creation.
</Note>

## Examples

### cURL - Primary Origination URI

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Primary SBC",
    "sip_uri": "sip:provider@sip.example.com:5060",
    "priority": 1
  }'
```

### cURL - Failover URI with Lower Priority

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Backup SBC",
    "sip_uri": "sip:backup@sip-backup.example.com:5060",
    "priority": 2
  }'
```

### cURL - Load Balancing Configuration

Create two URIs at the **same** priority, then set their `weight` with [Update Origination URI](/docs/trunks/origination-uri/update-origination-uri) to split traffic (e.g. 70/30). Both come back with the default `weight: 10` (an even split) until you adjust them.

<CodeGroup>
  ```bash Server 1 (priority 1) theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Server 1",
      "sip_uri": "sip:server1@sip.example.com:5060",
      "priority": 1
    }'
  ```

  ```bash Server 2 (priority 1) theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Server 2",
      "sip_uri": "sip:server2@sip.example.com:5060",
      "priority": 1
    }'
  ```
</CodeGroup>

<Info>
  **Error Response (400 Bad Request):** If SIP URI format is invalid:

  ```json Error Response - 400 Bad Request theme={null}
  {
    "error": "Invalid SIP URI format. Expected: sip:user@host:port",
    "code": 400
  }
  ```
</Info>

<Tip>
  **Best Practices:**

  * Configure at least 2 origination URIs for redundancy (one primary, one failover)
  * Use priority 1 for primary destinations, priority 2 for backup/failover
  * Adjust weights to distribute load across multiple carriers or servers
  * Test connectivity to each URI before enabling in production
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/origination-uris
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
  /api/v1/Account/{auth_id}/origination-uris:
    post:
      tags:
        - Origination URI
      summary: Create an origination URI
      description: Add an inbound SIP endpoint (origination URI) to a trunk.
      operationId: create-origination-uri
      parameters:
        - $ref: '#/components/parameters/AuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                sip_uri:
                  type: string
                priority:
                  type: integer
              required:
                - name
                - sip_uri
                - priority
            example:
              name: Primary SBC
              sip_uri: sip:sbc.example.com
              priority: 1
      responses:
        '200':
          description: Success
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
                priority: 1
                weight: 10
                enabled: true
                transport: TCP
                description: Primary SBC
                created_at: '2026-03-25T10:00:00Z'
                updated_at: '2026-03-25T10:00:00Z'
        '201':
          description: Origination URI created
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