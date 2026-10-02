> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Partner Profile

> Retrieve your Vobiz partner identity, billing configuration, GST status, and current balance - the authoritative source for your permanent partner ID used in queries.

[← Partner API Reference](/docs/partner/api)

Retrieve your partner identity, billing configuration, GST status, and current balance. The profile endpoint is the authoritative source for your permanent partner `id` - required as a filter parameter in Transaction and CDR queries.

<Info>
  All Partner API requests use `X-Auth-ID` and `X-Auth-Token` headers. See [Authentication](/docs/partner/api/authentication) for details.
</Info>

## Get Partner Profile

Retrieve your full partner profile, including identity, balance, GST configuration, and permanent partner ID. No request body or query parameters are required.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/me" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```python theme={null}
import requests

response = requests.get(
    "https://api.vobiz.ai/api/v1/partner/me",
    headers={
        "X-Auth-ID": "{your_partner_id}",
        "X-Auth-Token": "{your_auth_token}",
        "Accept": "application/json",
    }
)

profile = response.json()
partner_id = profile["id"]  # Store this - needed for CDR/transaction queries
print(f"Partner: {profile['name']}, Balance: {profile['balance']} {profile['currency']}")
```

### Response

```json theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": 500000,
  "name": "John Doe",
  "slug": "acme-partner",
  "company": "Acme Corp",
  "auth_id": "PA_XXXXXXXX",
  "email": "admin@example.com",
  "phone": "+919876543210",
  "billing_model": "direct",
  "is_active": true,
  "is_verified": false,
  "max_accounts": 1000,
  "can_create_accounts": true,
  "can_create_pricing_tiers": true,
  "can_view_cdrs": true,
  "can_transfer_balance": true,
  "default_pricing_tier_id": "11223344-1234-5678-90ab-cdef12345678",
  "account_count": 23,
  "balance": "23906.83000",
  "created_at": "2026-01-19T18:39:14.529435Z",
  "updated_at": "2026-05-11T13:31:06.283235Z"
}
```

### Key fields

| Field | Notes |
| - | - |
| `id` | Your permanent partner UUID. Some legacy filters expect this rather than `auth_id`. |
| `auth_id` | Your partner credential identifier (e.g. `PA_…`), used in the `X-Auth-ID` header. |
| `balance` | Your master wallet balance as a **string** with 5 decimal places (e.g. `"23906.83000"`). Parse it to a number before comparing - and note that `GET /dashboard` returns partner `balance` as `null` (use `total_balance` there instead). |
| `currency` | Your partner currency. Every balance transfer's `currency` must match this. |
| `max_accounts` | Hard cap on how many customers you can create. `account_count` is your current usage. |
| `can_create_accounts` | If `false`, [`POST /accounts`](/docs/partner/api/customers#create-customer-account) returns `403`. |
| `can_transfer_balance` | If `false`, [transfer-balance](/docs/partner/api/balance) returns `403`. |
| `can_view_cdrs` | If `false`, the [CDR endpoints](/docs/partner/api/cdrs) are blocked. |
| `is_verified` | Whether your own partner KYC is complete. |

<Warning>
  **`balance` is a string, not a number.** Comparing `"200.00000" >= 500` lexicographically will give wrong results. Cast it (`float(profile["balance"])`) before any arithmetic or balance check.
</Warning>

## When to Use

* **Initial integration setup** - Call this once when your integration starts. Capture the permanent `id` field and store it - it is required as a filter parameter in Transaction and CDR endpoints.
* **Balance checks before transfers** - Check your current balance before calling the Transfer Balance endpoint to confirm sufficient funds.
* **Sync billing metadata** - Sync GSTIN, TDS status, and account status to your internal billing system to ensure correct invoice generation.


## OpenAPI

````yaml GET /api/v1/partner/me
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
  /api/v1/partner/me:
    get:
      tags:
        - Partner API
      summary: Get partner profile
      description: Returns the authenticated partner's profile and balance.
      operationId: get-partner-profile
      responses:
        '200':
          description: Partner profile
          content:
            application/json:
              example:
                auth_id: PA_ABC123
                name: Acme Reseller
                email: partner@acme.com
                balance: 50000
                currency: INR
                country: IN
                created_at: '2025-01-15T10:00:00Z'
              schema:
                type: object
                properties:
                  id:
                    type: string
                  account_id:
                    type: integer
                  name:
                    type: string
                  slug:
                    type: string
                  company:
                    type: string
                  auth_id:
                    type: string
                  email:
                    type: string
                  phone:
                    type: string
                  billing_model:
                    type: string
                  is_active:
                    type: boolean
                  is_verified:
                    type: boolean
                  max_accounts:
                    type: integer
                  can_create_accounts:
                    type: boolean
                  can_create_pricing_tiers:
                    type: boolean
                  can_view_cdrs:
                    type: boolean
                  can_transfer_balance:
                    type: boolean
                  default_pricing_tier_id:
                    type: string
                  account_count:
                    type: integer
                  balance:
                    type: string
                  created_at:
                    type: string
                  updated_at:
                    type: string
                required:
                  - id
                  - account_id
                  - name
                  - slug
                  - company
                  - auth_id
                  - email
                  - phone
                  - billing_model
                  - is_active
                  - is_verified
                  - max_accounts
                  - can_create_accounts
                  - can_create_pricing_tiers
                  - can_view_cdrs
                  - can_transfer_balance
                  - default_pricing_tier_id
                  - account_count
                  - balance
                  - created_at
                  - updated_at
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