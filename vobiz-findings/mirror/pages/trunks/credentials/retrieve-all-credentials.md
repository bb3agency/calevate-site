> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve All Credentials

> Paginated list of all SIP digest credentials on your Vobiz account - audit usernames, check enabled states, and manage authentication for global SIP trunks.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/credentials
```

Returns a paginated list of all credentials associated with the account. Use this endpoint to audit authentication credentials, review which usernames are in use, or identify disabled credentials that can be cleaned up.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Pagination Support:** Results are paginated using limit and offset parameters. The response includes metadata showing the total count, current offset, and limit applied.
</Info>

## Query Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `limit` | integer | No | Maximum number of credentials to return per page. Default: `20`. |
| `offset` | integer | No | Number of credentials to skip before returning results. Default: `0`. For example, `offset=20` with `limit=20` returns page 2. |

## Response

Returns a paginated response with metadata and an array of credential objects. Passwords are not included in the response.

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
      "account_id": "MA_XXXXXXXX",
      "username": "sipuser_demo",
      "password": "<redacted>",
      "realm": "MA_XXXXXXXX.sip.vobiz.ai",
      "enabled": true,
      "created_at": "2026-04-22T08:51:47.813889Z",
      "updated_at": "2026-04-22T08:51:47.813889Z"
    },
    {
      "id": "11223344-5566-7788-99aa-bbccddeeff00",
      "account_id": "MA_XXXXXXXX",
      "username": "acme_sip_user",
      "password": "<redacted>",
      "realm": "MA_XXXXXXXX.sip.vobiz.ai",
      "enabled": true,
      "created_at": "2026-04-09T09:02:16.450443Z",
      "updated_at": "2026-04-09T09:02:16.450443Z"
    },
    {
      "id": "99887766-5544-3322-1100-ffeeddccbbaa",
      "account_id": "MA_XXXXXXXX",
      "username": "office_phone_03",
      "password": "<redacted>",
      "realm": "MA_XXXXXXXX.sip.vobiz.ai",
      "enabled": false,
      "created_at": "2026-04-08T10:13:14.485836Z",
      "updated_at": "2026-04-20T16:30:00.000000Z"
    }
  ]
}
```

## Examples

### cURL - Default Pagination

```bash cURL Request theme={null}
curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/credentials \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

### cURL - Custom Pagination

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/credentials?limit=10&offset=0" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Tip>
  **Pagination Tips:**

  * Use `total` from metadata to calculate total pages
  * Increment offset by limit value for each subsequent page
  * Page 1: offset=0, Page 2: offset=20, Page 3: offset=40 (with limit=20)
  * Empty `objects` array indicates no more results
</Tip>

<Warning>
  This endpoint is useful for credential management interfaces, auditing which credentials are active, and identifying unused credentials that can be safely removed.
</Warning>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/trunks/credentials
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
  /api/v1/Account/{auth_id}/trunks/credentials:
    get:
      tags:
        - Credentials
      summary: List credentials
      description: Retrieve all SIP credentials on the account.
      operationId: list-credentials
      parameters:
        - $ref: '#/components/parameters/AuthId'
      responses:
        '200':
          description: List of credentials
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
                        username:
                          type: string
                        password:
                          type: string
                        realm:
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
                        - username
                        - password
                        - realm
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
                    username: acme_sip_user_01
                    password: <redacted>
                    realm: MA_XXXXXXXX.sip.vobiz.ai
                    enabled: true
                    created_at: '2026-03-25T10:00:00Z'
                    updated_at: '2026-03-25T10:00:00Z'
                  - id: 99887766-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    username: office_phone_03
                    password: <redacted>
                    realm: MA_XXXXXXXX.sip.vobiz.ai
                    enabled: true
                    created_at: '2026-03-20T08:15:00Z'
                    updated_at: '2026-03-20T08:15:00Z'
                  - id: 55667788-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    username: sipuser_demo
                    password: <redacted>
                    realm: MA_XXXXXXXX.sip.vobiz.ai
                    enabled: true
                    created_at: '2026-03-15T14:42:00Z'
                    updated_at: '2026-03-15T14:42:00Z'
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