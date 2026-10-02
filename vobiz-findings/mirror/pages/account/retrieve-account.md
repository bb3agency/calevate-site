> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve Account Details

> Fetch complete Vobiz account details - auth credentials, pricing tier, verification status, and contact info - with a single authenticated GET request.

```http theme={null}
GET https://api.vobiz.ai/api/v1/auth/me
```

Returns complete account details including pricing tier information and authentication credentials.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Arguments

No arguments required.

## Request

```bash cURL theme={null}
curl -X GET https://api.vobiz.ai/api/v1/auth/me \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

## Response Example

```json Success Response (200 OK) theme={null}
{
  "type": "account",
  "id": "500000",
  "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "name": "Acme Corp",
  "email": "admin@example.com",
  "phone": "+919876543210",
  "description": null,
  "auth_id": "MA_XXXXXXXX",
  "auth_secret": "<redacted>",
  "auth_token_expire_time": null,
  "country": "IN",
  "timezone": "Asia/Kolkata",
  "city": "Bengaluru",
  "state": "KA",
  "address": "123 Example Street, Bengaluru",
  "zip_code": "560001",
  "company": "Acme Corp",
  "account_type": "standard",
  "postpaid": false,
  "auto_recharge": true,
  "auto_recharge_config": null,
  "enabled": true,
  "carrier_type": null,
  "customer_type": null,
  "credit_limit": 0.0,
  "cps_limit": 11,
  "concurrent_calls_limit": 10,
  "base_cps_limit": 1,
  "base_concurrent_calls_limit": 10,
  "purchased_cps": 10,
  "purchased_concurrent_calls": 0,
  "risk_rating": 0,
  "risk_status": null,
  "features": {
    "call_queue": true
  },
  "ip_auth_enabled": false,
  "ip_whitelist_rules": {},
  "allow_aws_ips": false,
  "role": "admin",
  "is_active": true,
  "is_verified": false,
  "is_trial_account": false,
  "created_at": "2025-09-30T08:33:24.700542+00:00",
  "updated_at": "2026-05-12T05:41:41.892287+00:00",
  "last_login": "2026-05-12T05:41:42.601005+00:00",
  "pricing_tier_id": "11223344-5566-7788-99aa-bbccddeeff00",
  "pricing_tier": {
    "id": "11223344-5566-7788-99aa-bbccddeeff00",
    "name": "Standard",
    "description": null,
    "currency": "INR",
    "rate_per_minute": 0.45,
    "billing_increment_seconds": 60,
    "minimum_duration_seconds": 0,
    "is_active": true,
    "is_default": false
  }
}
```

<Tip>
  **Pricing Tier:** Each account is associated with a pricing tier that determines the per-minute call rate and billing increments. The `pricing_tier` object provides complete details about your account's billing configuration.
</Tip>

<Note>
  This endpoint is also a convenient credential check. It returns your own identity, so the `auth_id` in the response should match the `X-Auth-ID` you sent. See [The Account Object](/docs/account/account-object) for every field.
</Note>

<Warning>
  **Error Response (401 Unauthorized):** the `X-Auth-ID` / `X-Auth-Token` pair is missing or invalid.

  ```json Error Response - 401 Unauthorized theme={null}
  {
    "error": "unauthorized",
    "message": "invalid credentials"
  }
  ```
</Warning>


## OpenAPI

````yaml GET /api/v1/auth/me
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
  /api/v1/auth/me:
    get:
      tags:
        - Account
      summary: Retrieve account
      description: >-
        Retrieve complete account details including pricing tier and
        credentials.
      operationId: retrieve-account
      responses:
        '200':
          description: Account details
          content:
            application/json:
              schema:
                type: object
                properties:
                  type:
                    type: string
                  id:
                    type: string
                  api_id:
                    type: string
                  name:
                    type: string
                  email:
                    type: string
                  phone:
                    type: string
                  description:
                    type: string
                  auth_id:
                    type: string
                  auth_secret:
                    type: string
                  auth_token_expire_time:
                    nullable: true
                  country:
                    type: string
                  timezone:
                    type: string
                  city:
                    type: string
                  state:
                    type: string
                  address:
                    type: string
                  zip_code:
                    type: string
                  company:
                    type: string
                  account_type:
                    type: string
                  postpaid:
                    type: boolean
                  auto_recharge:
                    type: boolean
                  auto_recharge_config:
                    nullable: true
                  enabled:
                    type: boolean
                  carrier_type:
                    nullable: true
                  customer_type:
                    nullable: true
                  credit_limit:
                    type: integer
                  cps_limit:
                    type: integer
                  concurrent_calls_limit:
                    type: integer
                  base_cps_limit:
                    type: integer
                  base_concurrent_calls_limit:
                    type: integer
                  purchased_cps:
                    type: integer
                  purchased_concurrent_calls:
                    type: integer
                  risk_rating:
                    type: integer
                  risk_status:
                    nullable: true
                  features:
                    type: object
                    properties:
                      call_queue:
                        type: boolean
                    required:
                      - call_queue
                  ip_auth_enabled:
                    type: boolean
                  ip_whitelist_rules:
                    type: object
                  allow_aws_ips:
                    type: boolean
                  role:
                    type: string
                  is_active:
                    type: boolean
                  is_verified:
                    type: boolean
                  is_trial_account:
                    type: boolean
                  created_at:
                    type: string
                  updated_at:
                    type: string
                  last_login:
                    type: string
                  pricing_tier_id:
                    type: string
                  pricing_tier:
                    type: object
                    properties:
                      id:
                        type: string
                      name:
                        type: string
                      description:
                        type: string
                      currency:
                        type: string
                      rate_per_minute:
                        type: number
                      billing_increment_seconds:
                        type: integer
                      minimum_duration_seconds:
                        type: integer
                      is_active:
                        type: boolean
                      is_default:
                        type: boolean
                    required:
                      - id
                      - name
                      - description
                      - currency
                      - rate_per_minute
                      - billing_increment_seconds
                      - minimum_duration_seconds
                      - is_active
                      - is_default
                required:
                  - type
                  - id
                  - api_id
                  - name
                  - email
                  - phone
                  - description
                  - auth_id
                  - auth_secret
                  - auth_token_expire_time
                  - country
                  - timezone
                  - city
                  - state
                  - address
                  - zip_code
                  - company
                  - account_type
                  - postpaid
                  - auto_recharge
                  - auto_recharge_config
                  - enabled
                  - carrier_type
                  - customer_type
                  - credit_limit
                  - cps_limit
                  - concurrent_calls_limit
                  - base_cps_limit
                  - base_concurrent_calls_limit
                  - purchased_cps
                  - purchased_concurrent_calls
                  - risk_rating
                  - risk_status
                  - features
                  - ip_auth_enabled
                  - ip_whitelist_rules
                  - allow_aws_ips
                  - role
                  - is_active
                  - is_verified
                  - is_trial_account
                  - created_at
                  - updated_at
                  - last_login
                  - pricing_tier_id
                  - pricing_tier
              example:
                type: account
                id: '500000'
                api_id: aabbccdd-1234-5678-90ab-cdef12345678
                name: Acme Corp
                email: admin@example.com
                phone: '+919876543210'
                description: null
                auth_id: MA_XXXXXXXX
                auth_secret: <redacted>
                auth_token_expire_time: null
                country: IN
                timezone: Asia/Kolkata
                city: Bengaluru
                state: KA
                address: 123 Example Street, Bengaluru
                zip_code: '560001'
                company: Acme Corp
                account_type: standard
                postpaid: false
                auto_recharge: true
                auto_recharge_config: null
                enabled: true
                carrier_type: null
                customer_type: null
                credit_limit: 0
                cps_limit: 11
                concurrent_calls_limit: 10
                base_cps_limit: 1
                base_concurrent_calls_limit: 10
                purchased_cps: 10
                purchased_concurrent_calls: 0
                risk_rating: 0
                risk_status: null
                features:
                  call_queue: true
                ip_auth_enabled: false
                ip_whitelist_rules: {}
                allow_aws_ips: false
                role: admin
                is_active: true
                is_verified: false
                is_trial_account: false
                created_at: '2025-09-30T08:33:24.700542+00:00'
                updated_at: '2026-05-12T05:41:41.892287+00:00'
                last_login: '2026-05-12T05:41:42.601005+00:00'
                pricing_tier_id: 11223344-5566-7788-99aa-bbccddeeff00
                pricing_tier:
                  id: 11223344-5566-7788-99aa-bbccddeeff00
                  name: Standard
                  description: null
                  currency: INR
                  rate_per_minute: 0.45
                  billing_increment_seconds: 60
                  minimum_duration_seconds: 0
                  is_active: true
                  is_default: false
        '401':
          description: Invalid credentials
components:
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