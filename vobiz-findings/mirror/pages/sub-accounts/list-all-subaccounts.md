> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List All Subaccounts

> Retrieve a paginated list of all Vobiz subaccounts sorted by creation date - enumerate tenants across your multi-tenant SaaS or reseller platform.

```http theme={null}
GET https://api.vobiz.ai/api/v1/accounts/{auth_id}/sub-accounts/
```

Returns a paginated list of subaccounts sorted by creation date, most recently created first.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `page` | integer | No | Page number for pagination. Defaults to 1. |
| `size` | integer | No | Number of results per page. Defaults to 25. |
| `active_only` | boolean | No | When set to `true`, returns only active sub-accounts. |

## Request

```bash cURL theme={null}
curl -X GET 'https://api.vobiz.ai/api/v1/accounts/{auth_id}/sub-accounts/?page=1&size=25&active_only=true' \
--header 'X-Auth-ID: {auth_id}' \
--header 'X-Auth-Token: {auth_token}'
```

## Response Example

```json Success Response (200 OK) theme={null}
{
  "sub_accounts": [
    {
      "name": "Support Team",
      "email": "support@example.com",
      "phone": "+1234567890",
      "description": "Support-facing voice workload",
      "permissions": {
        "calls": true,
        "cdr": true
      },
      "rate_limit": 500,
      "id": "500001",
      "parent_account_id": "510762",
      "parent_auth_id": "MA_XXXXXXXX",
      "auth_id": "SA_XXXXXXXX",
      "auth_token": "<redacted>",
      "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "email_verified": false,
      "enabled": true,
      "is_active": true,
      "created": "2025-10-22T03:57:35.997500Z",
      "modified": "2025-10-22T03:57:35.997500Z",
      "created_at": "2025-10-22T03:57:35.997500Z",
      "updated_at": "2025-10-22T03:57:35.997500Z",
      "account": "/v1/Account/MA_XXXXXXXX/",
      "resource_uri": "/v1/Account/MA_XXXXXXXX/Subaccount/SA_XXXXXXXX/",
      "last_used": null
    }
  ],
  "total": 1,
  "page": 1,
  "size": 25
}
```

<Info>
  **Pagination:** The response includes pagination metadata at the root level:

  * **total** - Total number of sub-accounts matching the filter
  * **page** - Current page number
  * **size** - Number of results per page
</Info>


## OpenAPI

````yaml GET /api/v1/accounts/{auth_id}/sub-accounts/
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
  /api/v1/accounts/{auth_id}/sub-accounts/:
    get:
      tags:
        - Sub-Accounts
      summary: List sub-accounts
      description: Retrieve all sub-accounts under the master account.
      operationId: list-subaccounts
      parameters:
        - $ref: '#/components/parameters/AuthId'
      responses:
        '200':
          description: List of sub-accounts
          content:
            application/json:
              example:
                sub_accounts:
                  - name: Acme Corp
                    email: null
                    phone: null
                    description: null
                    permissions: null
                    rate_limit: 1000
                    id: '500001'
                    parent_account_id: '500000'
                    parent_auth_id: MA_XXXXXXXX
                    auth_id: SA_XXXXXXXX
                    auth_token: <redacted>
                    api_id: aabbccdd-1234-5678-90ab-cdef12345678
                    email_verified: false
                    enabled: true
                    created: '2026-03-25'
                    modified: '2026-03-25'
                    is_active: true
                    created_at: '2026-03-25T08:33:24.700542Z'
                    updated_at: '2026-03-25T08:33:24.700542Z'
                    last_used: null
                    account: /v1/Account/MA_XXXXXXXX/
                    resource_uri: /v1/Account/MA_XXXXXXXX/Subaccount/SA_XXXXXXXX/
                  - name: John Doe
                    email: john@example.com
                    phone: null
                    description: null
                    permissions:
                      cdr: true
                      calls: true
                    rate_limit: 5000
                    id: '500002'
                    parent_account_id: '500000'
                    parent_auth_id: MA_XXXXXXXX
                    auth_id: SA_YYYYYYYY
                    auth_token: <redacted>
                    api_id: 11223344-5566-7788-99aa-bbccddeeff00
                    email_verified: false
                    enabled: true
                    created: '2026-03-25'
                    modified: '2026-03-25'
                    is_active: true
                    created_at: '2026-03-25T11:56:03.796409Z'
                    updated_at: '2026-03-25T11:56:03.796409Z'
                    last_used: null
                    account: /v1/Account/MA_XXXXXXXX/
                    resource_uri: /v1/Account/MA_XXXXXXXX/Subaccount/SA_YYYYYYYY/
                total: 28
                page: 1
                size: 10
              schema:
                type: object
                properties:
                  sub_accounts:
                    type: array
                    items:
                      type: object
                      properties:
                        name:
                          type: string
                        email:
                          type: string
                          nullable: true
                        phone:
                          nullable: true
                        description:
                          nullable: true
                        permissions:
                          anyOf:
                            - nullable: true
                            - type: object
                              properties:
                                cdr:
                                  type: boolean
                                calls:
                                  type: boolean
                        rate_limit:
                          type: integer
                        id:
                          type: string
                        parent_account_id:
                          type: string
                        parent_auth_id:
                          type: string
                        auth_id:
                          type: string
                        auth_token:
                          type: string
                        api_id:
                          type: string
                        email_verified:
                          type: boolean
                        enabled:
                          type: boolean
                        created:
                          type: string
                        modified:
                          type: string
                        is_active:
                          type: boolean
                        created_at:
                          type: string
                        updated_at:
                          type: string
                        last_used:
                          type: string
                          nullable: true
                        account:
                          type: string
                        resource_uri:
                          type: string
                      required:
                        - name
                        - email
                        - phone
                        - description
                        - permissions
                        - rate_limit
                        - id
                        - parent_account_id
                        - parent_auth_id
                        - auth_id
                        - auth_token
                        - api_id
                        - email_verified
                        - enabled
                        - created
                        - modified
                        - is_active
                        - created_at
                        - updated_at
                        - last_used
                        - account
                        - resource_uri
                  total:
                    type: integer
                  page:
                    type: integer
                  size:
                    type: integer
                required:
                  - sub_accounts
                  - total
                  - page
                  - size
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