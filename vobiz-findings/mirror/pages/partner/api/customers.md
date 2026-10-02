> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Customer Accounts

> Provision, list, and manage SIP-enabled customer sub-accounts under your Vobiz partner account - each customer gets a unique auth_id for all subsequent API operations.

[← Partner API Reference](/docs/partner/api)

The core of the Partner API. Provision SIP-enabled sub-accounts for your clients, inspect their profiles, and monitor their real-time wallet balances. Each customer receives an `auth_id` that serves as the primary key for all subsequent operations.

<Info>
  All Partner API requests use `X-Auth-ID` and `X-Auth-Token` headers. See [Authentication](/docs/partner/api/authentication) for details.
</Info>

## Overview

| Method | Endpoint | Description |
| - | - | - |
| POST | `/accounts` | Create a new customer sub-account |
| GET | `/accounts` | List all customer accounts (paginated) |
| GET | `/accounts/{customer_auth_id}` | Get full profile for a specific customer |
| GET | `/accounts/{customer_auth_id}/balance` | Get real-time wallet balance for a customer |

## Create Customer Account

Provisions a new SIP-enabled Vobiz account under your partner umbrella. The customer is created instantly and can start receiving calls as soon as you assign a phone number and fund their wallet.

### Request Body

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | Required | Customer's full name |
| `email` | string | Required | Customer email - used for login and KYC notifications |
| `password` | string | Required | Customer login password (min 8 chars, must include number and special char) |
| `phone` | string | Optional | E.164 phone number, e.g. `+919876543210` |
| `description` | string | Optional | Free-text description of the customer's use case |
| `company` | string | Optional | Legal company or business name |
| `address` | string | Optional | Street address |
| `city` | string | Optional | City |
| `state` | string | Optional | State or region |
| `zip_code` | string | Optional | Postal/ZIP code |
| `country` | string | Required | ISO 2-letter country code, e.g. `IN` |
| `timezone` | string | Optional | IANA timezone, e.g. `Asia/Kolkata` |
| `gstin` | string | Optional | GSTIN for tax invoicing (India) |
| `gst_status` | string | Optional | `active` or `inactive` |
| `account_type` | string | Optional | `standard` (default) or other plan tier |

<Note>
  The minimum verified field set is `name`, `email`, `phone`, `password`, and `country`. `company` is the only documented optional field guaranteed by the API contract; the remaining optional fields above are accepted on a best-effort basis - if your call rejects one, drop it and set it later via the Console.
</Note>

**Validation rules**

* `email` must be unique across the whole Vobiz platform - reusing an email returns `422`.
* `password` must be at least 8 characters and contain a number and a special character. A weaker password returns `422`.
* `phone` must be E.164 (leading `+` and country code).
* `country` must be a valid ISO 3166-1 alpha-2 code. The customer's wallet currency is derived from it (`IN` → `INR`).
* Creating a customer counts against your `max_accounts` limit (see [Profile](/docs/partner/api/profile)). Exceeding it returns `403`.

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/partner/accounts" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "email": "admin@example.com",
    "password": "<redacted>",
    "phone": "+919876543210",
    "description": "Outbound collections calling team",
    "company": "Acme Corp",
    "address": "1 MG Road",
    "city": "Bengaluru",
    "state": "KA",
    "zip_code": "560001",
    "country": "IN",
    "timezone": "Asia/Kolkata",
    "gstin": "29AAPFU0939F1ZV",
    "gst_status": "active",
    "account_type": "standard"
  }'
```

### Response

```json theme={null}
{
  "auth_id": "MA_XXXXXXXX",
  "auth_token": "<redacted>",
  "name": "John Doe",
  "email": "john@example.com",
  "status": "active",
  "balance": 0.00,
  "currency": "INR",
  "country": "IN",
  "created_at": "2026-03-25T10:00:00Z"
}
```

A successful create returns **`201 Created`**. The new customer starts with `balance: 0.00` and `status: active`, but `kyc_status` is `pending` and the wallet is empty - you must [transfer balance](/docs/partner/api/balance) and (for India) run [KYC](/docs/partner/api/kyc-sessions) before the account is fully usable.

<Warning>
  **Store both `auth_id` and `auth_token` immediately - the `auth_token` is shown only once.** The `auth_id` is the customer's permanent identifier for every partner operation (balance transfers, CDR lookups, transaction queries, number assignments). The `auth_token` is the customer's own API secret - the only way to retrieve it again later is [Get Customer Account](#get-customer-account). Treat the `auth_token` like a password: store it encrypted server-side and never expose it in client-side code, URLs, or logs.
</Warning>

### Errors

| Status | Cause |
| - | - |
| `401` / `403` | Missing/invalid partner credentials, or `can_create_accounts` is `false` on your partner profile. |
| `403` | You have hit your `max_accounts` limit. |
| `409` / `422` | Email already in use, or a field failed validation (weak password, malformed phone, bad country code). |

## List Customer Accounts

Returns a paginated list of all customer accounts under your partner umbrella. Use `search` to find a specific customer by name or email.

### Query Parameters

| Parameter | Default | Description |
| - | - | - |
| `page` | `1` | Page number (1-indexed) |
| `per_page` | `20` | Items per page (max `100`) |
| `search` | - | Substring match on customer name **or** email |

<Note>
  The **request** uses `per_page`, but the **response** echoes it back as `size`. They are the same value under two different keys.
</Note>

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts?page=1&per_page=20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts?page=1&per_page=20&search=Acme" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```json theme={null}
{
  "accounts": [
    {
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+919876543210",
      "description": null,
      "gstin": null,
      "gst_status": null,
      "tds_enabled": false,
      "tds_percentage": 2,
      "business_type": "individual",
      "id": "500000",
      "auth_id": "MA_XXXXXXXX",
      "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "account_type": "standard",
      "role": "user",
      "postpaid": false,
      "address": "1 MG Road",
      "city": "Bengaluru",
      "state": "KA",
      "timezone": "Asia/Kolkata",
      "country": "IN",
      "zip_code": "560001",
      "company": "Acme Corp",
      "billing_mode": "prepaid",
      "auto_recharge": false,
      "cash_credits": "1300.00000",
      "cps_limit": 1,
      "concurrent_calls_limit": 4,
      "base_cps_limit": null,
      "base_concurrent_calls_limit": null,
      "purchased_cps": null,
      "purchased_concurrent_calls": null,
      "is_active": true,
      "is_verified": false,
      "is_trial_account": false,
      "enabled": true,
      "kyc_status": "pending",
      "google_id": null,
      "referral_code": null,
      "referral_disabled": false,
      "custom_referrer_reward_amount": null,
      "custom_referee_reward_amount": null,
      "created_at": "2026-05-06T07:12:40.437143+00:00",
      "updated_at": "2026-05-07T11:54:13.620089+00:00",
      "last_login": "2026-05-06T07:16:47.457817+00:00",
      "pricing_tier_id": "11223344-1234-5678-90ab-cdef12345678",
      "pricing_tier": {
        "id": "11223344-1234-5678-90ab-cdef12345678",
        "name": "Standard",
        "currency": "INR",
        "rate_per_minute": 0.45,
        "streaming_rate_per_minute": 0.2,
        "recording_rate_per_minute": 0.1,
        "whatsapp_voice_rate": 0.45,
        "transcription_rate_per_minute": 0.1,
        "pii_redaction_rate_per_minute": 0.3,
        "charge_non_connected_calls": true,
        "non_connected_call_fee": 0.02,
        "did_release_fee": 700,
        "is_active": true,
        "is_default": false,
        "partner_id": null
      },
      "partner_id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "auto_recharge_config": null,
      "resource_uri": "/v1/Account/MA_XXXXXXXX/",
      "auth_token": "<redacted>"
    }
  ],
  "total": 23,
  "page": 1,
  "size": 20
}
```

## Get Customer Account

Returns the full technical profile for a specific customer, including their auth token (required to make API calls on their behalf), billing configuration, GST details, and current status.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```json theme={null}
{
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+919876543210",
  "description": null,
  "gstin": null,
  "gst_status": null,
  "tds_enabled": false,
  "tds_percentage": 2,
  "business_type": "individual",
  "id": "500000",
  "auth_id": "MA_XXXXXXXX",
  "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_type": "standard",
  "role": "user",
  "postpaid": false,
  "address": "1 MG Road",
  "city": "Bengaluru",
  "state": "KA",
  "timezone": "Asia/Kolkata",
  "country": "IN",
  "zip_code": "560001",
  "company": "Acme Corp",
  "billing_mode": "prepaid",
  "auto_recharge": false,
  "cash_credits": "1300.00000",
  "cps_limit": 1,
  "concurrent_calls_limit": 4,
  "is_active": true,
  "is_verified": false,
  "is_trial_account": false,
  "enabled": true,
  "kyc_status": "pending",
  "created_at": "2026-05-06T07:12:40.437143+00:00",
  "updated_at": "2026-05-07T11:54:13.620089+00:00",
  "last_login": "2026-05-06T07:16:47.457817+00:00",
  "pricing_tier_id": "11223344-1234-5678-90ab-cdef12345678",
  "pricing_tier": {
    "id": "11223344-1234-5678-90ab-cdef12345678",
    "name": "Standard",
    "currency": "INR",
    "rate_per_minute": 0.45,
    "is_active": true,
    "is_default": false,
    "partner_id": null
  },
  "partner_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "auto_recharge_config": null,
  "resource_uri": "/v1/Account/MA_XXXXXXXX/",
  "auth_token": "<redacted>"
}
```

## Get Customer Balance

Returns the real-time wallet balance for a specific customer. Check this before deciding whether to top up a customer's wallet. A customer with zero or near-zero balance will start experiencing call failures.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/balance" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```json theme={null}
{
  "auth_id": "MA_XXXXXXXX",
  "name": "John Doe",
  "cash_credits": "1300.00000",
  "currency": "INR",
  "updated_at": "2026-05-07T11:54:13.620089+00:00"
}
```

## Provisioning Workflow

Follow this sequence when onboarding a new customer:

* **Create the account** - Provision the sub-account. Store the returned `auth_id` in your database.
* **[Fund the wallet](/docs/partner/api/balance)** - Transfer an opening balance from your master account. The customer cannot make calls without balance.
* **[Assign phone numbers](/docs/partner/api/numbers)** - Assign one or more DID phone numbers to the customer account. Customers need a DID to receive inbound calls.
* **[Monitor usage](/docs/partner/api/cdrs)** - Pull CDRs and transaction logs regularly for billing and quality monitoring.


## OpenAPI

````yaml GET /api/v1/partner/accounts
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
  /api/v1/partner/accounts:
    get:
      tags:
        - Partner API
      summary: List customer accounts
      description: Returns all customer sub-accounts under your partner account.
      operationId: list-customer-accounts
      parameters:
        - name: page
          in: query
          schema:
            type: integer
            default: 1
        - name: per_page
          in: query
          schema:
            type: integer
            default: 20
        - name: search
          in: query
          description: Substring match on name or email.
          schema:
            type: string
      responses:
        '200':
          description: Customer accounts
          content:
            application/json:
              schema:
                type: object
                properties:
                  accounts:
                    type: array
                    items:
                      type: object
                      properties:
                        name:
                          type: string
                        email:
                          type: string
                        phone:
                          type: string
                        description:
                          type: string
                          nullable: true
                        gstin:
                          type: string
                          nullable: true
                        gst_status:
                          type: string
                          nullable: true
                        tds_enabled:
                          type: boolean
                        tds_percentage:
                          type: integer
                        business_type:
                          type: string
                        id:
                          type: string
                        auth_id:
                          type: string
                        api_id:
                          type: string
                        account_type:
                          type: string
                        role:
                          type: string
                        postpaid:
                          type: boolean
                        address:
                          type: string
                          nullable: true
                        city:
                          type: string
                          nullable: true
                        state:
                          type: string
                          nullable: true
                        timezone:
                          type: string
                          nullable: true
                        country:
                          type: string
                        zip_code:
                          type: string
                          nullable: true
                        company:
                          type: string
                        billing_mode:
                          type: string
                        auto_recharge:
                          type: boolean
                        cash_credits:
                          type: string
                        cps_limit:
                          type: integer
                        concurrent_calls_limit:
                          type: integer
                        base_cps_limit:
                          nullable: true
                        base_concurrent_calls_limit:
                          nullable: true
                        purchased_cps:
                          nullable: true
                        purchased_concurrent_calls:
                          nullable: true
                        is_active:
                          type: boolean
                        is_verified:
                          type: boolean
                        is_trial_account:
                          type: boolean
                        enabled:
                          type: boolean
                        kyc_status:
                          type: string
                        google_id:
                          nullable: true
                        referral_code:
                          type: string
                          nullable: true
                        referral_disabled:
                          type: boolean
                        custom_referrer_reward_amount:
                          nullable: true
                        custom_referee_reward_amount:
                          nullable: true
                        created_at:
                          type: string
                        updated_at:
                          type: string
                        last_login:
                          type: string
                          nullable: true
                        pricing_tier_id:
                          type: string
                        pricing_tier:
                          type: object
                          properties:
                            id:
                              type: string
                            name:
                              type: string
                            currency:
                              type: string
                            rate_per_minute:
                              type: number
                            streaming_rate_per_minute:
                              type: number
                            recording_rate_per_minute:
                              type: number
                            whatsapp_voice_rate:
                              type: number
                            transcription_rate_per_minute:
                              type: number
                            pii_redaction_rate_per_minute:
                              type: number
                            charge_non_connected_calls:
                              type: boolean
                            non_connected_call_fee:
                              type: number
                            did_release_fee:
                              type: integer
                            is_active:
                              type: boolean
                            is_default:
                              type: boolean
                            partner_id:
                              nullable: true
                          required:
                            - id
                            - name
                            - currency
                            - rate_per_minute
                            - streaming_rate_per_minute
                            - recording_rate_per_minute
                            - whatsapp_voice_rate
                            - transcription_rate_per_minute
                            - pii_redaction_rate_per_minute
                            - charge_non_connected_calls
                            - non_connected_call_fee
                            - did_release_fee
                            - is_active
                            - is_default
                            - partner_id
                        partner_id:
                          type: string
                        auto_recharge_config:
                          nullable: true
                        resource_uri:
                          type: string
                        auth_token:
                          type: string
                      required:
                        - name
                        - email
                        - phone
                        - description
                        - gstin
                        - gst_status
                        - tds_enabled
                        - tds_percentage
                        - business_type
                        - id
                        - auth_id
                        - api_id
                        - account_type
                        - role
                        - postpaid
                        - address
                        - city
                        - state
                        - timezone
                        - country
                        - zip_code
                        - company
                        - billing_mode
                        - auto_recharge
                        - cash_credits
                        - cps_limit
                        - concurrent_calls_limit
                        - base_cps_limit
                        - base_concurrent_calls_limit
                        - purchased_cps
                        - purchased_concurrent_calls
                        - is_active
                        - is_verified
                        - is_trial_account
                        - enabled
                        - kyc_status
                        - google_id
                        - referral_code
                        - referral_disabled
                        - custom_referrer_reward_amount
                        - custom_referee_reward_amount
                        - created_at
                        - updated_at
                        - last_login
                        - pricing_tier_id
                        - pricing_tier
                        - partner_id
                        - auto_recharge_config
                        - resource_uri
                        - auth_token
                  total:
                    type: integer
                  page:
                    type: integer
                  size:
                    type: integer
                required:
                  - accounts
                  - total
                  - page
                  - size
              example:
                accounts:
                  - name: Acme Corp
                    email: admin@acme-corp.com
                    phone: '+919876543210'
                    description: null
                    gstin: null
                    gst_status: null
                    tds_enabled: false
                    tds_percentage: 2
                    business_type: individual
                    id: '500000'
                    auth_id: MA_XXXXXXXX
                    api_id: aabbccdd-1234-5678-90ab-cdef12345678
                    account_type: standard
                    role: user
                    postpaid: false
                    address: 221B Baker Street
                    city: Mumbai
                    state: null
                    timezone: Asia/Kolkata
                    country: IN
                    zip_code: '400001'
                    company: Acme Corp
                    billing_mode: prepaid
                    auto_recharge: false
                    cash_credits: '1300.00000'
                    cps_limit: 1
                    concurrent_calls_limit: 4
                    base_cps_limit: null
                    base_concurrent_calls_limit: null
                    purchased_cps: null
                    purchased_concurrent_calls: null
                    is_active: true
                    is_verified: false
                    is_trial_account: false
                    enabled: true
                    kyc_status: pending
                    google_id: null
                    referral_code: null
                    referral_disabled: false
                    custom_referrer_reward_amount: null
                    custom_referee_reward_amount: null
                    created_at: '2026-03-25T10:00:00Z'
                    updated_at: '2026-03-26T11:54:13Z'
                    last_login: '2026-03-25T10:16:47Z'
                    pricing_tier_id: 11223344-1234-5678-90ab-cdef12345678
                    pricing_tier:
                      id: 11223344-1234-5678-90ab-cdef12345678
                      name: Standard
                      currency: INR
                      rate_per_minute: 0.45
                      streaming_rate_per_minute: 0.2
                      recording_rate_per_minute: 0.1
                      whatsapp_voice_rate: 0.45
                      transcription_rate_per_minute: 0.1
                      pii_redaction_rate_per_minute: 0.3
                      charge_non_connected_calls: true
                      non_connected_call_fee: 0.02
                      did_release_fee: 700
                      is_active: true
                      is_default: false
                      partner_id: null
                    partner_id: 99887766-1234-5678-90ab-cdef12345678
                    auto_recharge_config: null
                    resource_uri: /v1/Account/MA_XXXXXXXX/
                    auth_token: <redacted>
                  - name: John Doe
                    email: john@example.com
                    phone: '+918012345678'
                    description: null
                    gstin: null
                    gst_status: null
                    tds_enabled: false
                    tds_percentage: 2
                    business_type: individual
                    id: '500001'
                    auth_id: MA_YYYYYYYY
                    api_id: 55667788-1234-5678-90ab-cdef12345678
                    account_type: standard
                    role: user
                    postpaid: false
                    address: null
                    city: null
                    state: null
                    timezone: null
                    country: IN
                    zip_code: null
                    company: Acme Corp
                    billing_mode: prepaid
                    auto_recharge: false
                    cash_credits: '1107.00000'
                    cps_limit: 1
                    concurrent_calls_limit: 3
                    base_cps_limit: null
                    base_concurrent_calls_limit: null
                    purchased_cps: null
                    purchased_concurrent_calls: null
                    is_active: true
                    is_verified: false
                    is_trial_account: false
                    enabled: true
                    kyc_status: pending
                    google_id: null
                    referral_code: null
                    referral_disabled: false
                    custom_referrer_reward_amount: null
                    custom_referee_reward_amount: null
                    created_at: '2026-03-20T05:58:46Z'
                    updated_at: '2026-03-21T05:13:16Z'
                    last_login: null
                    pricing_tier_id: 11223344-1234-5678-90ab-cdef12345678
                    pricing_tier:
                      id: 11223344-1234-5678-90ab-cdef12345678
                      name: Standard
                      currency: INR
                      rate_per_minute: 0.45
                      streaming_rate_per_minute: 0.2
                      recording_rate_per_minute: 0.1
                      whatsapp_voice_rate: 0.45
                      transcription_rate_per_minute: 0.1
                      pii_redaction_rate_per_minute: 0.3
                      charge_non_connected_calls: true
                      non_connected_call_fee: 0.02
                      did_release_fee: 700
                      is_active: true
                      is_default: false
                      partner_id: null
                    partner_id: 99887766-1234-5678-90ab-cdef12345678
                    auto_recharge_config: null
                    resource_uri: /v1/Account/MA_YYYYYYYY/
                    auth_token: <redacted>
                total: 2
                page: 1
                size: 20
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