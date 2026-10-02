> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Phone Numbers (DIDs)

> View and monitor DID phone number assignments for each customer in your Vobiz partner ecosystem - list per-customer numbers or get a global inventory overview.

[← Partner API Reference](/docs/partner/api)

View and monitor the DID (Direct Inward Dialing) phone number inventory assigned to each customer, or get a global view across all accounts. Customers need at least one active DID to receive inbound calls.

<Info>
  All Partner API requests use `X-Auth-ID` and `X-Auth-Token` headers. See [Authentication](/docs/partner/api/authentication) for details.
</Info>

## Overview

These endpoints are **read-only**. They show you what numbers are assigned to each customer. To assign or release numbers, use the Vobiz Console or contact your account manager.

<Note>
  **Read-only inventory.** The Partner API does not currently support assigning, purchasing, or releasing phone numbers programmatically. Use the [Vobiz Partner Console](https://console.vobiz.ai) to manage number inventory, or contact [support@vobiz.ai](mailto:support@vobiz.ai) for bulk number provisioning.
</Note>

## Customer Numbers

Returns all phone numbers assigned to a specific customer account. Use to verify a customer's number inventory, check allocation status, and identify the application each number is routed to.

### Query Parameters

| Parameter | Default | Description |
| - | - | - |
| `page` | `1` | Page number (1-indexed) |
| `per_page` | `20` | Items per page (max `100`) |
| `search` | - | Filter by partial number match |

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/numbers?page=1&per_page=20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/numbers?search=9122712" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```json theme={null}
{
  "items": [
    {
      "id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "account_id": "MA_XXXXXXXX",
      "e164": "+918012345678",
      "country": "IN",
      "region": "Karnataka",
      "capabilities": { "voice": true, "sms": false, "mms": false, "fax": false },
      "status": "active",
      "provider": "",
      "setup_fee": 100,
      "monthly_fee": 300,
      "currency": "INR",
      "application_id": "20577609616603585",
      "voice_enabled": true,
      "tags": [],
      "purchased_at": "2026-03-25T06:58:38Z",
      "is_blocked": false,
      "created_at": "2025-03-31T18:30:00Z",
      "updated_at": "2026-03-25T06:58:54Z",
      "is_trial_number": false,
      "last_billing_date": "2026-03-25T06:58:38Z",
      "next_billing_date": "2026-04-25T06:58:38Z",
      "minimum_commitment_months": 0,
      "aadhaar_verification_required": false,
      "aadhaar_verified": false,
      "source": "purchased"
    }
  ],
  "page": 1,
  "per_page": 20,
  "total": 1,
  "account_auth_id": "MA_XXXXXXXX"
}
```

### Response fields

| Field | Notes |
| - | - |
| `e164` | The number in E.164 format. |
| `status` | `active` once the number is routing. |
| `capabilities` | Per-channel flags - `voice`, `sms`, `mms`, `fax`. Indian DIDs are typically voice-only. |
| `application_id` | The Vobiz application the number is routed to. A number with no application has nowhere to route inbound calls. |
| `setup_fee` / `monthly_fee` | One-time and recurring rental cost in `currency`. Add `monthly_fee` to the customer's invoice. |
| `last_billing_date` / `next_billing_date` | When the DID was last charged and when it next renews. There is no separate `expires_at`; a number stops routing only when released or when the account can't cover the next rental. |
| `aadhaar_verification_required` / `aadhaar_verified` | Indian regulatory flag. If `aadhaar_verification_required` is `true` and `aadhaar_verified` is `false`, the number may be restricted until the customer completes KYC. |
| `source` | How the number was obtained, e.g. `purchased`. |

## All Numbers (Global)

Returns all phone numbers across every customer account under your partner umbrella. Use to audit your complete DID inventory, identify unassigned numbers, or find numbers that are expiring soon.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/numbers?page=1&per_page=50" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

The global response uses the same item schema as the per-customer endpoint, paginated across every account under your umbrella.

## Number Management Guide

* **Every customer needs at least one active number** - A customer with no assigned numbers cannot receive inbound calls. After creating a customer account, assign at least one DID via the Vobiz Console.
* **Monitor renewals** - Watch `next_billing_date`. A DID stops routing only when it is released or when the customer's wallet can't cover the next rental. Build a weekly check that flags numbers renewing within 14 days against customers whose balance is low.
* **Verify application routing after assignment** - After assigning a number, confirm `application_id` is set. A number with no application receives calls but has nowhere to route them, causing immediate hangups for callers.
* **Track costs for billing** - Use `monthly_fee` (recurring) and `setup_fee` (one-time) for the DID rental cost per number. Add these to the customer invoice alongside call usage from the [CDR endpoint](/docs/partner/api/cdrs).
* **Watch Aadhaar status (India)** - If `aadhaar_verification_required` is `true` but `aadhaar_verified` is `false`, the number may be regulatorily restricted until the customer completes [KYC](/docs/partner/api/kyc-sessions).


## OpenAPI

````yaml GET /api/v1/partner/accounts/{customer_auth_id}/numbers
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
  /api/v1/partner/accounts/{customer_auth_id}/numbers:
    get:
      tags:
        - Partner API
      summary: List customer numbers
      description: Phone numbers currently assigned to a customer account.
      operationId: list-customer-numbers
      parameters:
        - name: customer_auth_id
          in: path
          required: true
          schema:
            type: string
        - name: search
          in: query
          description: Substring match against the E.164 number.
          schema:
            type: string
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
      responses:
        '200':
          description: Customer numbers
          content:
            application/json:
              schema:
                type: object
                properties:
                  items:
                    type: array
                  page:
                    type: integer
                  per_page:
                    type: integer
                  total:
                    type: integer
                  account_auth_id:
                    type: string
                required:
                  - items
                  - page
                  - per_page
                  - total
                  - account_auth_id
              example:
                items:
                  - id: aabbccdd-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    e164: '+918012345678'
                    country: IN
                    region: Karnataka
                    capabilities:
                      voice: true
                      sms: false
                      mms: false
                      fax: false
                    status: active
                    provider: ''
                    setup_fee: 100
                    monthly_fee: 300
                    currency: INR
                    application_id: '20577609616603585'
                    voice_enabled: true
                    tags: []
                    purchased_at: '2026-03-25T06:58:38Z'
                    is_blocked: false
                    created_at: '2025-03-31T18:30:00Z'
                    updated_at: '2026-03-25T06:58:54Z'
                    is_trial_number: false
                    last_billing_date: '2026-03-25T06:58:38Z'
                    next_billing_date: '2026-04-25T06:58:38Z'
                    minimum_commitment_months: 0
                    aadhaar_verification_required: false
                    aadhaar_verified: false
                    source: purchased
                  - id: 11223344-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    e164: '+919876543210'
                    country: IN
                    region: Mumbai
                    capabilities:
                      voice: true
                      sms: false
                      mms: false
                      fax: false
                    status: active
                    provider: ''
                    setup_fee: 100
                    monthly_fee: 200
                    currency: INR
                    application_id: '31985999331899218'
                    voice_enabled: true
                    tags: []
                    purchased_at: '2026-02-17T10:25:30Z'
                    is_blocked: false
                    created_at: '2026-02-14T09:30:04Z'
                    updated_at: '2026-02-17T10:29:35Z'
                    is_trial_number: false
                    last_billing_date: '2026-02-17T10:25:30Z'
                    next_billing_date: '2026-03-17T10:25:30Z'
                    minimum_commitment_months: 0
                    aadhaar_verification_required: false
                    aadhaar_verified: false
                    source: purchased
                page: 1
                per_page: 20
                total: 2
                account_auth_id: MA_XXXXXXXX
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