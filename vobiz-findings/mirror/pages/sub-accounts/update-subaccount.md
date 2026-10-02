> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update a Subaccount

> Update any fields on a Vobiz subaccount - rename it, toggle enabled status, adjust rate limits, or modify permissions. Unset fields remain unchanged.

```http theme={null}
PUT https://api.vobiz.ai/api/v1/accounts/{auth_id}/sub-accounts/{sub_auth_id}
```

Updates the subaccount by setting the provided parameters. Parameters that are not provided remain unchanged.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  Use this endpoint to update sub-account settings such as description, rate limits, or permissions.
</Warning>

## Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | No | Name of the sub-account. |
| `email` | string | No | Email address associated with the subaccount. |
| `phone` | string | No | Phone number associated with the subaccount. |
| `description` | string | No | Description of the sub-account purpose or usage. |
| `rate_limit` | integer | No | API rate limit for this sub-account (requests per time period). |
| `permissions` | object | No | Permissions object defining what the sub-account can access. Contains boolean fields like `calls` and `cdr`. |
| `enabled` | boolean | No | Whether the subaccount is active and enabled for use. |
| `kyc_mode` | string | No | Change the verification mode: `personal_use` or `customer_use`. Promoting to `customer_use` requires the sub-account to already have an `email`. On any change, `kyc_calls_blocked` is re-derived from the sub-account's current KYC state. |

## Request

<CodeGroup>
  ```bash cURL theme={null}
  curl -X PUT 'https://api.vobiz.ai/api/v1/accounts/{auth_id}/sub-accounts/{sub_auth_id}' \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}' \
  --header 'Content-Type: application/json' \
  --data-raw '{
    "description": "Updated permissions",
    "rate_limit": 750,
    "email": "updated@example.com",
    "enabled": true,
    "kyc_mode": "customer_use"
  }'
  ```

  ```json Request Body theme={null}
  {
    "description": "Updated permissions",
    "rate_limit": 750,
    "email": "updated@example.com",
    "enabled": true,
    "kyc_mode": "customer_use"
  }
  ```
</CodeGroup>

## Response Example

```json Success Response (200 OK) theme={null}
{
  "name": "Support Team",
  "email": "updated@example.com",
  "phone": "+1234567890",
  "description": "Updated permissions",
  "permissions": {
    "calls": true,
    "cdr": true
  },
  "rate_limit": 750,
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
  "modified": "2025-10-22T03:59:52.261439Z",
  "created_at": "2025-10-22T03:57:35.997500Z",
  "updated_at": "2025-10-22T03:59:52.261439Z",
  "account": "/v1/Account/MA_XXXXXXXX/",
  "resource_uri": "/v1/Account/MA_XXXXXXXX/Subaccount/SA_XXXXXXXX/",
  "last_used": null
}
```

<Tip>
  The response returns the full updated sub-account object. Notice the `updated_at` timestamp has changed to reflect the modification.
</Tip>

## Changing `kyc_mode`

Promoting a sub-account from `personal_use` to `customer_use` requires it to **already have an `email`** - otherwise the call fails with `400`. On any `kyc_mode` change, `kyc_calls_blocked` is re-derived from the sub-account's current KYC state:

* Promote to `customer_use` on a sub-account that has not completed its own KYC → `kyc_calls_blocked` becomes `true` and calls are blocked until it verifies.
* Demote to `personal_use` → the sub-account inherits the parent's KYC and `kyc_calls_blocked` becomes `false`.

<Warning>
  Promoting a live sub-account to `customer_use` can immediately block its calls. Run KYC (or [Test Mode](/docs/sub-accounts/kyc/test-mode)) before flipping the mode on production traffic.
</Warning>


## OpenAPI

````yaml PUT /api/v1/accounts/{auth_id}/sub-accounts/{sub_auth_id}
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
  /api/v1/accounts/{auth_id}/sub-accounts/{sub_auth_id}:
    put:
      tags:
        - Sub-Accounts
      summary: Update a sub-account
      description: |
        Update the name or status of a sub-account, or change its `kyc_mode`.

        Promoting an existing sub-account to `customer_use` requires the
        sub-account to already have an `email` (otherwise `400`). On any
        `kyc_mode` change, `kyc_calls_blocked` is re-derived from the
        sub-account's current KYC state.
      operationId: update-subaccount
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: sub_auth_id
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
                enabled:
                  type: boolean
                kyc_mode:
                  type: string
                  enum:
                    - personal_use
                    - customer_use
                  description: >-
                    Change the verification mode. Promoting to `customer_use`
                    requires the sub-account to have an `email`.
            example:
              kyc_mode: customer_use
      responses:
        '200':
          description: Sub-account updated
          content:
            application/json:
              schema:
                type: object
                properties:
                  name:
                    type: string
                  email:
                    nullable: true
                  phone:
                    nullable: true
                  description:
                    nullable: true
                  permissions:
                    nullable: true
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
              example:
                name: Acme Sub-Account Updated
                email: null
                phone: null
                description: null
                permissions: null
                rate_limit: 1000
                id: '500001'
                parent_account_id: '510762'
                parent_auth_id: MA_XXXXXXXX
                auth_id: SA_XXXXXXXX
                auth_token: <redacted>
                api_id: aabbccdd-1234-5678-90ab-cdef12345678
                email_verified: false
                enabled: false
                created: '2026-03-25'
                modified: '2026-03-25'
                is_active: true
                created_at: '2026-03-25T10:00:00Z'
                updated_at: '2026-03-25T10:30:00Z'
                last_used: null
                account: /v1/Account/MA_XXXXXXXX/
                resource_uri: /v1/Account/MA_XXXXXXXX/Subaccount/SA_XXXXXXXX/
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