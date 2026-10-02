> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve All IP ACLs

> Fetch a paginated list of all IP ACL entries on your Vobiz account to audit whitelisted IPv4 addresses, enabled states, and trunk IP auth coverage globally.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/ip-acl
```

Returns a paginated list of all IP ACL entries associated with the account. Use this endpoint to view all whitelisted IP addresses, audit your IP access configuration, and manage multiple IP ACL entries.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Security Audit:** Regularly review this list to ensure only authorized IP addresses are whitelisted. Remove any entries that are no longer needed.
</Info>

## Query Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `limit` | integer | No | Number of results per page. Default: `20`. Maximum: `100`. |
| `offset` | integer | No | Number of results to skip for pagination. Default: `0`. Use with `limit` for page navigation. |

## Response

Returns a paginated list of IP ACL objects with metadata about pagination state.

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
      "ip_address": "192.168.0.0/16",
      "description": "Office IP",
      "enabled": true,
      "created_at": "2026-03-18T14:41:41Z",
      "updated_at": "2026-03-18T14:41:41Z"
    },
    {
      "id": "bbccddee-2345-6789-01bc-def234567890",
      "account_id": "",
      "ip_address": "10.20.30.0/24",
      "description": "Production SBC",
      "enabled": true,
      "created_at": "2026-04-02T09:20:30Z",
      "updated_at": "2026-04-02T09:20:30Z"
    },
    {
      "id": "ccddeeff-3456-789a-12cd-ef3456789012",
      "account_id": "",
      "ip_address": "10.40.50.0/24",
      "description": "Datacenter ACL",
      "enabled": false,
      "created_at": "2026-04-15T14:15:45Z",
      "updated_at": "2026-04-20T11:30:00Z"
    }
  ]
}
```

## Examples

### cURL - Default Pagination

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/ip-acl" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

### cURL - Custom Pagination

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/ip-acl?limit=50&offset=0" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Info>
  **Pagination Tip:** Use `total` from the meta object to calculate total pages. For page 2 with limit 20, use `offset=20`.
</Info>

<Tip>
  **Monitoring:** Review the `enabled` field for each entry. Disabled entries appear in the list but do not allow authentication. Check `updated_at` to see when entries were last modified.
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/trunks/ip-acl
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
  /api/v1/Account/{auth_id}/trunks/ip-acl:
    get:
      tags:
        - IP Access Control List
      summary: List IP ACLs
      description: Retrieve all IP access control rules on the account.
      operationId: list-ip-acls
      parameters:
        - $ref: '#/components/parameters/AuthId'
      responses:
        '200':
          description: List of IP ACLs
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
                        ip_address:
                          type: string
                        description:
                          type: string
                        enabled:
                          type: boolean
                        created_at:
                          type: string
                        updated_at:
                          type: string
                      required:
                        - id
                        - account_id
                        - ip_address
                        - description
                        - enabled
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
                    ip_address: 10.20.30.0/24
                    description: Office IP
                    enabled: true
                    created_at: '2026-03-25T10:00:00Z'
                    updated_at: '2026-03-25T10:00:00Z'
                  - id: 99887766-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    ip_address: 192.168.1.0/24
                    description: Datacenter ACL
                    enabled: true
                    created_at: '2026-03-22T09:00:00Z'
                    updated_at: '2026-03-22T09:00:00Z'
                  - id: 55667788-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    ip_address: 203.0.113.0/24
                    description: Production SBC
                    enabled: true
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