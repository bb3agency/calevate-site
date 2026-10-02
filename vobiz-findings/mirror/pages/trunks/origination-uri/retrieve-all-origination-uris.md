> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve All Origination URIs

> List all SIP destination URIs on a Vobiz trunk - review routing priority, load-balancing weights, and enabled status to audit outbound call configuration.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/origination-uris
```

Returns all origination URIs configured for a specific trunk. The response includes routing configuration such as priority, weight, and enabled status for each URI. Use pagination parameters to control the number of results returned.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Use Case:** List all routing destinations to audit your trunk's outbound call routing configuration, verify failover setup, or analyze load balancing distribution across multiple carriers.
</Info>

## Query Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `limit` | integer | No | Maximum number of URIs to return per page. Default: `20`. Range: `1`–`100`. |
| `offset` | integer | No | Number of URIs to skip before returning results. Default: `0`. Used for pagination. |

## Response

Returns a paginated list of origination URI objects with metadata about the result set.

```json Response - 200 OK theme={null}
{
  "meta": {
    "limit": 20,
    "offset": 0,
    "total": 3
  },
  "objects": [
    {
      "id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "account_id": "",
      "uri": "sip:sbc1.example.com:5060",
      "priority": 1,
      "weight": 10,
      "enabled": true,
      "transport": "udp",
      "description": "",
      "created_at": "2026-05-10T10:45:30Z",
      "updated_at": "2026-05-10T10:45:30Z"
    },
    {
      "id": "bbccddee-2345-6789-01bc-def234567890",
      "account_id": "",
      "uri": "sip:sbc2.example.com:5060",
      "priority": 2,
      "weight": 10,
      "enabled": true,
      "transport": "udp",
      "description": "",
      "created_at": "2026-05-10T11:00:00Z",
      "updated_at": "2026-05-10T11:00:00Z"
    },
    {
      "id": "ccddeeff-3456-789a-12cd-ef3456789012",
      "account_id": "",
      "uri": "sip:sbc1.example.com:5061",
      "priority": 1,
      "weight": 20,
      "enabled": true,
      "transport": "udp",
      "description": "",
      "created_at": "2026-05-10T11:15:00Z",
      "updated_at": "2026-05-10T11:15:00Z"
    }
  ]
}
```

<Note>
  **Example Routing Logic:**

  * Priority 1 URIs (first and third) handle primary traffic
  * Among priority 1, traffic is split 33% to first URI (weight 10) and 67% to third URI (weight 20)
  * Priority 2 URI (second) serves as failover if all priority 1 URIs fail
</Note>

## Examples

### cURL - List All URIs

```bash cURL Request theme={null}
curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/origination-uris \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

### cURL - Paginated Results

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/origination-uris?limit=10&offset=0" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Tip>
  **Pagination:**

  * Use `limit` to control page size
  * Use `offset` to skip to a specific page
  * Check `total` in meta to determine total URIs
  * Calculate total pages: `Math.ceil(total / limit)`
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/trunks/origination-uris
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
  /api/v1/Account/{auth_id}/trunks/origination-uris:
    get:
      tags:
        - Origination URI
      summary: List origination URIs
      description: Retrieve all origination URIs on the account.
      operationId: list-origination-uris
      parameters:
        - $ref: '#/components/parameters/AuthId'
      responses:
        '200':
          description: List of origination URIs
          content:
            application/json:
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
                required:
                  - meta
                  - objects
              example:
                meta:
                  limit: 20
                  offset: 0
                  total: 3
                objects:
                  - id: 11223344-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    uri: sip:sbc1.example.com
                    priority: 1
                    weight: 10
                    enabled: true
                    transport: udp
                    description: Primary SBC
                    created_at: '2026-03-25T10:00:00Z'
                    updated_at: '2026-03-25T10:00:00Z'
                  - id: 99887766-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    uri: sip:sbc2.example.com
                    priority: 2
                    weight: 10
                    enabled: true
                    transport: tcp
                    description: US East SBC
                    created_at: '2026-03-22T09:00:00Z'
                    updated_at: '2026-03-22T09:00:00Z'
                  - id: 55667788-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    uri: sip:sbc3.example.com
                    priority: 10
                    weight: 10
                    enabled: true
                    transport: tls
                    description: ''
                    created_at: '2026-03-18T14:41:41Z'
                    updated_at: '2026-03-18T14:41:41Z'
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