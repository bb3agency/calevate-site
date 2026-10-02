> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dashboard & Analytics

> Access aggregated usage metrics and date-range analytics across your Vobiz reseller ecosystem - live dashboard summary and flexible reporting endpoints.

[← Partner API Reference](/docs/partner/api)

Two endpoints provide aggregated intelligence across your entire reseller ecosystem - a live dashboard summary for high-level health checks, and a flexible analytics endpoint for date-range performance reporting.

<Info>
  All Partner API requests use `X-Auth-ID` and `X-Auth-Token` headers. See [Authentication](/docs/partner/api/authentication) for details.
</Info>

## Overview

| Endpoint | What it returns | Best for |
| - | - | - |
| `/dashboard` | Live counts, balances, today's call volume | Main UI landing page, health checks |
| `/analytics` | Aggregated call metrics, cost, top spenders | Billing cycles, customer reports, trend analysis |

## Partner Dashboard

Returns a high-level snapshot of your partner account, including total active customer accounts, combined wallet balances, total calls today, and platform-level status indicators.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/dashboard" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```json theme={null}
{
  "partner": {
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
    "balance": null,
    "created_at": "2026-01-19T18:39:14.529435Z",
    "updated_at": "2026-05-11T13:31:06.283235Z"
  },
  "period": {
    "from": "2026-04-12",
    "to": "2026-05-12"
  },
  "accounts": {
    "total": 23,
    "active": 23,
    "customers": [
      {
        "auth_id": "MA_XXXXXXXX",
        "name": "John Doe",
        "email": "john@example.com",
        "phone": "+919876543210",
        "is_active": true,
        "created_at": "2026-02-06T06:50:07.722963+00:00"
      },
      {
        "auth_id": "MA_YYYYYYYY",
        "name": "Acme Corp",
        "email": "admin@example.com",
        "phone": "+919876543210",
        "is_active": true,
        "created_at": "2026-02-09T09:34:48.330015+00:00"
      }
    ]
  },
  "total_balance": "1003058.82000",
  "currency": "INR",
  "calls": {
    "total_calls": 210,
    "answered_calls": 178,
    "total_minutes": 157.2,
    "total_cost": "108.24"
  },
  "traffic": {
    "inbound": {
      "total_calls": 28,
      "answered_calls": 20,
      "total_minutes": 25.5,
      "total_cost": "17.26"
    },
    "outbound": {
      "total_calls": 182,
      "answered_calls": 158,
      "total_minutes": 131.7,
      "total_cost": "90.98"
    }
  },
  "by_product": {
    "sip_trunking": {
      "total_calls": 8,
      "answered_calls": 0,
      "total_minutes": 0,
      "total_cost": "0.16"
    },
    "voice_api": {
      "total_calls": 202,
      "answered_calls": 178,
      "total_minutes": 157.2,
      "total_cost": "108.08"
    }
  },
  "time_series": [
    {
      "date": "2026-04-15",
      "total_calls": 38,
      "answered_calls": 23,
      "total_minutes": 5.8,
      "total_cost": "7.21",
      "inbound": {
        "total_calls": 2,
        "answered_calls": 0,
        "total_minutes": 0
      },
      "outbound": {
        "total_calls": 36,
        "answered_calls": 23,
        "total_minutes": 5.8
      }
    },
    {
      "date": "2026-04-16",
      "total_calls": 69,
      "answered_calls": 60,
      "total_minutes": 30.7,
      "total_cost": "26.48",
      "inbound": {
        "total_calls": 2,
        "answered_calls": 0,
        "total_minutes": 0
      },
      "outbound": {
        "total_calls": 67,
        "answered_calls": 60,
        "total_minutes": 30.7
      }
    }
  ]
}
```

### Response fields

| Field | Notes |
| - | - |
| `partner` | Your partner profile snapshot. Note `partner.balance` is **`null`** here - read `total_balance` (below) for the aggregate held across customers. |
| `period` | The `from` / `to` window the metrics cover. |
| `accounts` | `total`, `active`, and a `customers[]` list (each with `auth_id`, `name`, `email`, `phone`, `is_active`, `created_at`). |
| `total_balance` | Combined wallet balance held across all customers, as a string. |
| `calls` | Roll-up: `total_calls`, `answered_calls`, `total_minutes`, `total_cost`. |
| `traffic` | The same roll-up split into `inbound` and `outbound`. |
| `by_product` | The same roll-up split into `sip_trunking` and `voice_api`. |
| `time_series[]` | Per-day metrics with nested `inbound` / `outbound` counts. |

<Tip>
  To find customers at risk of running out of balance, there is no single "low balance" field - page through [`GET /accounts`](/docs/partner/api/customers#list-customer-accounts) (each row carries `cash_credits`) or call [Get Customer Balance](/docs/partner/api/customers#get-customer-balance) per account, then recharge proactively so calls don't start failing.
</Tip>

## Partner Analytics

Returns aggregated call analytics across all customer accounts. Defaults to the last 30 days. Pass `from_date` and `to_date` for a custom window. Use for billing cycle audits, identifying top-spending customers, and call volume trend analysis.

### Query Parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `from_date` | string | Optional | Start date in `YYYY-MM-DD` format. Defaults to 30 days ago. |
| `to_date` | string | Optional | End date in `YYYY-MM-DD` format. Defaults to today. |

### Default - Last 30 Days

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/analytics" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

### Custom Date Range

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/analytics?from_date=2026-01-01&to_date=2026-03-31" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

### Response

```json theme={null}
{
  "partner": {
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
    "balance": null,
    "created_at": "2026-01-19T18:39:14.529435Z",
    "updated_at": "2026-05-11T13:31:06.283235Z"
  },
  "period": {
    "from": "2026-01-01",
    "to": "2026-03-31"
  },
  "accounts": {
    "total": 23,
    "active": 23,
    "customers": [
      {
        "auth_id": "MA_XXXXXXXX",
        "name": "John Doe",
        "email": "john@example.com",
        "phone": "+919876543210",
        "is_active": true,
        "created_at": "2026-02-06T06:50:07.722963+00:00"
      }
    ]
  },
  "total_balance": "1003058.82000",
  "currency": "INR",
  "calls": {
    "total_calls": 210,
    "answered_calls": 178,
    "total_minutes": 157.2,
    "total_cost": "108.24"
  },
  "traffic": {
    "inbound": {
      "total_calls": 28,
      "answered_calls": 20,
      "total_minutes": 25.5,
      "total_cost": "17.26"
    },
    "outbound": {
      "total_calls": 182,
      "answered_calls": 158,
      "total_minutes": 131.7,
      "total_cost": "90.98"
    }
  },
  "by_product": {
    "sip_trunking": {
      "total_calls": 8,
      "answered_calls": 0,
      "total_minutes": 0,
      "total_cost": "0.16"
    },
    "voice_api": {
      "total_calls": 202,
      "answered_calls": 178,
      "total_minutes": 157.2,
      "total_cost": "108.08"
    }
  },
  "time_series": [
    {
      "date": "2026-01-15",
      "total_calls": 38,
      "answered_calls": 23,
      "total_minutes": 5.8,
      "total_cost": "7.21",
      "inbound": {
        "total_calls": 2,
        "answered_calls": 0,
        "total_minutes": 0
      },
      "outbound": {
        "total_calls": 36,
        "answered_calls": 23,
        "total_minutes": 5.8
      }
    }
  ]
}
```

## Use Cases

* **Monthly billing cycle** - Pull analytics for the billing month to calculate total usage (`calls.total_cost`, `calls.total_minutes`), generate invoices, and reconcile against your [transaction ledger](/docs/partner/api/transactions).
* **Answer-rate analysis** - Track `calls.answered_calls / calls.total_calls` over time (or per-day via `time_series`) to spot network quality or configuration problems.
* **Inbound vs. outbound split** - Use `traffic.inbound` vs `traffic.outbound` to understand your base - outbound-heavy customers have different pricing and capacity needs than inbound-heavy ones.
* **Product mix** - Use `by_product` to see how usage splits between `sip_trunking` and `voice_api` across your ecosystem.


## OpenAPI

````yaml GET /api/v1/partner/dashboard
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
  /api/v1/partner/dashboard:
    get:
      tags:
        - Partner API
      summary: Get dashboard summary
      description: |
        Aggregated partner metrics - total customers, active accounts, balance
        held across the partner ecosystem, MTD revenue, etc.
      operationId: get-partner-dashboard
      responses:
        '200':
          description: Dashboard summary
          content:
            application/json:
              example:
                total_customers: 42
                active_customers: 38
                pending_kyc: 4
                total_balance_held: 250000
                currency: INR
                mtd_revenue: 18450.5
              schema:
                type: object
                properties:
                  partner:
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
                        nullable: true
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
                  period:
                    type: object
                    properties:
                      from:
                        type: string
                      to:
                        type: string
                    required:
                      - from
                      - to
                  accounts:
                    type: object
                    properties:
                      total:
                        type: integer
                      active:
                        type: integer
                      customers:
                        type: array
                        items:
                          type: object
                          properties:
                            auth_id:
                              type: string
                            name:
                              type: string
                            email:
                              type: string
                            phone:
                              type: string
                            is_active:
                              type: boolean
                            created_at:
                              type: string
                          required:
                            - auth_id
                            - name
                            - email
                            - phone
                            - is_active
                            - created_at
                    required:
                      - total
                      - active
                      - customers
                  total_balance:
                    type: string
                  currency:
                    type: string
                  calls:
                    type: object
                    properties:
                      total_calls:
                        type: integer
                      answered_calls:
                        type: integer
                      total_minutes:
                        type: number
                      total_cost:
                        type: string
                    required:
                      - total_calls
                      - answered_calls
                      - total_minutes
                      - total_cost
                  traffic:
                    type: object
                    properties:
                      inbound:
                        type: object
                        properties:
                          total_calls:
                            type: integer
                          answered_calls:
                            type: integer
                          total_minutes:
                            type: number
                          total_cost:
                            type: string
                        required:
                          - total_calls
                          - answered_calls
                          - total_minutes
                          - total_cost
                      outbound:
                        type: object
                        properties:
                          total_calls:
                            type: integer
                          answered_calls:
                            type: integer
                          total_minutes:
                            type: number
                          total_cost:
                            type: string
                        required:
                          - total_calls
                          - answered_calls
                          - total_minutes
                          - total_cost
                    required:
                      - inbound
                      - outbound
                  by_product:
                    type: object
                    properties:
                      sip_trunking:
                        type: object
                        properties:
                          total_calls:
                            type: integer
                          answered_calls:
                            type: integer
                          total_minutes:
                            type: integer
                          total_cost:
                            type: string
                        required:
                          - total_calls
                          - answered_calls
                          - total_minutes
                          - total_cost
                      voice_api:
                        type: object
                        properties:
                          total_calls:
                            type: integer
                          answered_calls:
                            type: integer
                          total_minutes:
                            type: number
                          total_cost:
                            type: string
                        required:
                          - total_calls
                          - answered_calls
                          - total_minutes
                          - total_cost
                    required:
                      - sip_trunking
                      - voice_api
                  time_series:
                    type: array
                    items:
                      type: object
                      properties:
                        date:
                          type: string
                        total_calls:
                          type: integer
                        answered_calls:
                          type: integer
                        total_minutes:
                          type: number
                        total_cost:
                          type: string
                        inbound:
                          type: object
                          properties:
                            total_calls:
                              type: integer
                            answered_calls:
                              type: integer
                            total_minutes:
                              type: number
                          required:
                            - total_calls
                            - answered_calls
                            - total_minutes
                        outbound:
                          type: object
                          properties:
                            total_calls:
                              type: integer
                            answered_calls:
                              type: integer
                            total_minutes:
                              type: number
                          required:
                            - total_calls
                            - answered_calls
                            - total_minutes
                      required:
                        - date
                        - total_calls
                        - answered_calls
                        - total_minutes
                        - total_cost
                        - inbound
                        - outbound
                required:
                  - partner
                  - period
                  - accounts
                  - total_balance
                  - currency
                  - calls
                  - traffic
                  - by_product
                  - time_series
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