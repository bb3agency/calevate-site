> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create a Subaccount

> Provision an isolated Vobiz subaccount with its own auth credentials for multi-tenant SaaS apps, white-label resellers, or departmental resource separation.

```http theme={null}
POST https://api.vobiz.ai/api/v1/accounts/{auth_id}/sub-accounts/
```

Provision isolated subaccounts under your main account for multi-tenant SaaS applications, reseller models, or departmental resource segregation.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | Yes | A human-readable name for the subaccount. The only required field. |
| `email` | string | Conditional | Email address for the subaccount. **Required when `kyc_mode` is `customer_use`** (the KYC link and reminders are sent here). Optional otherwise. |
| `phone` | string | No | Phone number associated with the subaccount. |
| `description` | string | No | Description of the sub-account purpose or usage. |
| `rate_limit` | integer | No | API rate limit for this sub-account (requests per time period). Defaults to `1000` when omitted. |
| `permissions` | object | No | Permissions object defining what the sub-account can access. Contains boolean fields like `calls` and `cdr`. When omitted, the sub-account inherits the parent's default access. |
| `password` | string | No | Login password for the sub-account console. The API credentials (`auth_id` / `auth_token`) are generated regardless and are what you use for REST/telephony calls. |
| `enabled` | boolean | No | Whether the subaccount is active and enabled for use. Defaults to `true`. |
| `kyc_mode` | string | No | `personal_use` (default) inherits the parent's KYC; `customer_use` requires the sub-account to complete its own KYC. `customer_use` **requires** `email`. |
| `business_type` | string | No | Legal constitution of the customer: `individual`, `proprietorship`, `private_limited`, `llp`, `partnership`, `public_limited`, `trust`, `society`, `huf`, or `government`. Drives which KYC documents are required - see the [document matrix](/docs/sub-accounts/kyc/overview#document-requirements-by-entity). |

<Info>
  **Authenticate as the parent.** Send your parent main account's `X-Auth-ID` / `X-Auth-Token`; the `{auth_id}` in the path is your parent (`MA_…`) account. The sub-account does not have credentials until this call returns them.
</Info>

<Note>
  Creating a sub-account with `kyc_mode: "customer_use"` returns it with `kyc_calls_blocked: true` - the sub-account **cannot place calls** until it completes KYC. If you omit `email` while setting `customer_use`, the request fails with `400`. See [Sub-Account KYC](/docs/sub-accounts/kyc/overview) for the full create → KYC → unblock recipe.
</Note>

## Request

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST 'https://api.vobiz.ai/api/v1/accounts/{auth_id}/sub-accounts/' \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}' \
  --header 'Content-Type: application/json' \
  --data-raw '{
    "name": "Support Team",
    "email": "support@example.com",
    "phone": "+1234567890",
    "description": "Support-facing voice workload",
    "rate_limit": 500,
    "permissions": {
      "calls": true,
      "cdr": true
    },
    "password": "S0pport123!",
    "enabled": true,
    "kyc_mode": "customer_use"
  }'
  ```

  ```json Request Body theme={null}
  {
    "name": "Support Team",
    "email": "support@example.com",
    "phone": "+1234567890",
    "description": "Support-facing voice workload",
    "rate_limit": 500,
    "permissions": {
      "calls": true,
      "cdr": true
    },
    "password": "S0pport123!",
    "enabled": true,
    "kyc_mode": "customer_use"
  }
  ```
</CodeGroup>

## Response Example

```json Success Response (201 Created) theme={null}
{
  "message": "Sub-account created successfully",
  "sub_account": {
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
    "auth_token": "sub_account_auth_token_shown_once",
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
  },
  "auth_credentials": {
    "auth_id": "SA_XXXXXXXX",
    "auth_token": "sub_account_auth_token_shown_once"
  },
  "tokens": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

<Tip>
  **Success!** The response contains three sections:

  * **sub\_account** - The created sub-account object with all details.
  * **auth\_credentials** - The sub-account's own `auth_id` and `auth_token`. These are its primary API credentials - used as the `X-Auth-ID` / `X-Auth-Token` headers on every REST and telephony API call, exactly like a main account. Save them securely.
  * **tokens** - Optional JWT access/refresh tokens for signing the sub-account into the console/dashboard. They are **not** required to call the REST or telephony API - use the `auth_id` / `auth_token` above for that.
</Tip>

<Warning>
  **Security Note:** The `auth_token` is only returned once during creation. Store it securely - you will not be able to retrieve it again. If lost, you will need to regenerate credentials.
</Warning>

## `business_type` and required documents

For a `customer_use` sub-account, `business_type` sets which KYC documents the sub-account must clear before `kyc_calls_blocked` flips to `false`:

| `business_type` | Typical documents to verify |
| - | - |
| `individual`, `proprietorship`, `huf` | PAN + Aadhaar (via DigiLocker) |
| `private_limited`, `public_limited`, `llp`, `partnership` | PAN + GST and/or CIN |
| `trust`, `society`, `government` | PAN + supporting registration (CIN/GST as applicable) |

You can set `business_type` at creation or later via [Update](/docs/sub-accounts/update-subaccount). See [Sub-Account KYC](/docs/sub-accounts/kyc/overview) for the per-document endpoints.

## Common errors

| Status | Cause |
| - | - |
| `400` | `kyc_mode: "customer_use"` set without an `email`. |
| `401` | Missing or wrong `X-Auth-ID` / `X-Auth-Token`, or the path uses the wrong casing (`/accounts/`, plural and lowercase). |
| `404` | The `{auth_id}` in the path is not a main account you own. |


## OpenAPI

````yaml POST /api/v1/accounts/{auth_id}/sub-accounts/
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
    post:
      tags:
        - Sub-Accounts
      summary: Create a sub-account
      description: |
        Create a new sub-account under the master account.

        Set `kyc_mode` to control how the sub-account is verified:

        - `personal_use` *(default)* - the sub-account inherits the parent's
          KYC; no separate verification is required.
        - `customer_use` - the sub-account must complete its own KYC before it
          can place calls. A fresh `customer_use` sub-account is returned with
          `kyc_calls_blocked: true`. `customer_use` **requires** `email`.
      operationId: create-subaccount
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
                  description: Human-readable name for the sub-account.
                email:
                  type: string
                  format: email
                  description: Required when `kyc_mode` is `customer_use`.
                password:
                  type: string
                  description: Login password for the sub-account.
                kyc_mode:
                  type: string
                  enum:
                    - personal_use
                    - customer_use
                  default: personal_use
                  description: >
                    `personal_use` inherits parent KYC. `customer_use` requires

                    the sub-account to complete its own KYC and requires
                    `email`.
                business_type:
                  type: string
                  enum:
                    - individual
                    - proprietorship
                    - private_limited
                    - llp
                    - partnership
                    - public_limited
                    - trust
                    - society
                    - huf
                    - government
                  description: >-
                    Legal constitution of the customer. Drives which KYC
                    documents are required.
                enabled:
                  type: boolean
              required:
                - name
            example:
              name: Customer Co
              email: customer@example.com
              password: Customer@12345
              kyc_mode: customer_use
              business_type: private_limited
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  message:
                    type: string
                  sub_account:
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
                  auth_credentials:
                    type: object
                    properties:
                      auth_id:
                        type: string
                      auth_token:
                        type: string
                    required:
                      - auth_id
                      - auth_token
                  tokens:
                    type: object
                    properties:
                      access_token:
                        type: string
                      refresh_token:
                        type: string
                      token_type:
                        type: string
                      expires_in:
                        type: integer
                    required:
                      - access_token
                      - refresh_token
                      - token_type
                      - expires_in
                required:
                  - message
                  - sub_account
                  - auth_credentials
                  - tokens
        '201':
          description: Sub-account created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SubAccount'
              example:
                message: Sub-account created successfully
                sub_account:
                  name: Acme Sub-Account
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
                  enabled: true
                  created: '2026-03-25'
                  modified: '2026-03-25'
                  is_active: true
                  created_at: '2026-03-25T10:00:00Z'
                  updated_at: '2026-03-25T10:00:00Z'
                  last_used: null
                  account: /v1/Account/MA_XXXXXXXX/
                  resource_uri: /v1/Account/MA_XXXXXXXX/Subaccount/SA_XXXXXXXX/
                auth_credentials:
                  auth_id: SA_XXXXXXXX
                  auth_token: <redacted>
                tokens:
                  access_token: <redacted>
                  refresh_token: <redacted>
                  token_type: bearer
                  expires_in: 1800
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
  schemas:
    SubAccount:
      type: object
      properties:
        auth_id:
          type: string
        auth_token:
          type: string
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
            Verification mode. `customer_use` sub-accounts must complete their
            own KYC before placing calls.
        business_type:
          type: string
          description: Legal constitution of the customer (e.g. `private_limited`).
        kyc_calls_blocked:
          type: boolean
          description: >-
            True while a `customer_use` sub-account has not yet completed the
            KYC required to place calls.
        created_at:
          type: string
          format: date-time
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