> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Partner Transactions

> Access detailed financial ledgers for every credit and debit event across your Vobiz reseller ecosystem - essential for monthly billing reconciliation and dispute resolution.

[← Partner API Reference](/docs/partner/api)

Detailed financial ledgers for every credit and debit event across your partner ecosystem. Use these for monthly billing reconciliation, dispute resolution, and auditing balance movements between your account and your customers.

<Info>
  All Partner API requests use `X-Auth-ID` and `X-Auth-Token` headers. See [Authentication](/docs/partner/api/authentication) for details.
</Info>

## Overview

Two endpoints cover different scopes of transaction data:

* **Customer Transactions** - All debits and credits for one specific customer. Use for per-customer invoicing and customer-facing statements.
* **All Transactions (Global)** - Global ledger across every customer under your partner account. Use for platform-wide reconciliation and monthly financial close.

## Customer Transactions

Returns a paginated transaction ledger for one specific customer. Filter by transaction type and date range to generate statements for a specific billing period.

### Query Parameters

| Parameter | Default | Description |
| - | - | - |
| `page` | `1` | Page number (1-indexed) |
| `per_page` | `20` | Items per page (max `200`). Validated - an over-limit value returns `422`, it does not silently fall back. |
| `from_date` | - | Start date in `YYYY-MM-DD` format |
| `to_date` | - | End date in `YYYY-MM-DD` format |
| `transaction_type` | - | Filter to `recharge`, `debit`, `refund`, or `transfer` |

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transactions?page=1&per_page=20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transactions?from_date=2026-03-01&to_date=2026-03-31&per_page=100" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transactions?transaction_type=recharge&per_page=50" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```json theme={null}
{
  "transactions": [
    {
      "id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "account_id": "MA_XXXXXXXX",
      "balance_id": "11223344-1234-5678-90ab-cdef12345678",
      "type": "credit",
      "amount": 200,
      "currency": "INR",
      "description": "Transfer from partner John Doe: Balance transfer",
      "reference": "ptc:aabbccdd-1234-5678-90ab-cdef12345678:MA_XXXXXXXX:1778140310",
      "status": "completed",
      "processed_at": "2026-05-07T07:51:50.402147Z",
      "created_at": "2026-05-07T07:51:50.402147Z",
      "updated_at": "2026-05-07T07:51:50.402147Z"
    },
    {
      "id": "99887766-1234-5678-90ab-cdef12345678",
      "account_id": "MA_XXXXXXXX",
      "balance_id": "11223344-1234-5678-90ab-cdef12345678",
      "type": "credit",
      "amount": 100,
      "currency": "INR",
      "description": "Transfer from partner John Doe: Balance transfer",
      "reference": "ptc:aabbccdd-1234-5678-90ab-cdef12345678:MA_XXXXXXXX:1778051898",
      "status": "completed",
      "processed_at": "2026-05-06T07:18:18.945506Z",
      "created_at": "2026-05-06T07:18:18.945506Z",
      "updated_at": "2026-05-06T07:18:18.945506Z"
    },
    {
      "id": "55667788-1234-5678-90ab-cdef12345678",
      "account_id": "MA_XXXXXXXX",
      "balance_id": "11223344-1234-5678-90ab-cdef12345678",
      "type": "credit",
      "amount": 1000,
      "currency": "INR",
      "description": "Transfer from partner John Doe: Balance transfer",
      "reference": "ptc:aabbccdd-1234-5678-90ab-cdef12345678:MA_XXXXXXXX:1778051770",
      "status": "completed",
      "processed_at": "2026-05-06T07:16:10.657945Z",
      "created_at": "2026-05-06T07:16:10.657945Z",
      "updated_at": "2026-05-06T07:16:10.657945Z"
    }
  ],
  "summary": {
    "total_transactions": 3,
    "total_debit": 0,
    "total_credit": 1300,
    "net_amount": 1300,
    "by_reference_type": [
      {
        "reference_type": "unknown",
        "total_debit": 0,
        "total_credit": 1300,
        "count": 3
      }
    ]
  },
  "total": 3,
  "page": 1,
  "per_page": 20,
  "total_pages": 1,
  "account_auth_id": "MA_XXXXXXXX"
}
```

## All Transactions (Global)

Global reconciliation log - all transaction events across every customer under your partner account in a single paginated response. Same filter parameters as the per-customer endpoint. Essential for platform-wide monthly financial close.

<Note>
  The global endpoint additionally accepts `account` to drill into one customer, and `search` which spans description, reference, account ID, and account name.
</Note>

<Note>
  If you only need a single customer's ledger, prefer the per-customer endpoint above - it returns a `summary` block scoped to that customer. To reconcile across all customers when the global endpoint is unavailable to you, page through [`GET /accounts`](/docs/partner/api/customers#list-customer-accounts) and call the per-customer ledger for each `auth_id`.
</Note>

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/transactions?page=1&per_page=50" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/transactions?from_date=2026-03-01&to_date=2026-03-31&transaction_type=debit&per_page=100" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

### Response fields

| Field | Notes |
| - | - |
| `transactions[].id` | UUID of the ledger entry. |
| `transactions[].account_id` | The customer `auth_id` the entry belongs to. |
| `transactions[].type` | Ledger direction - **`credit`** or **`debit`**. This is *not* the same vocabulary as the `transaction_type` filter (see below). |
| `transactions[].amount` | Positive integer in the account currency. The sign is implied by `type`, not by the number. |
| `transactions[].reference` | Machine reference. Partner balance transfers use the form `ptc:<partner_id>:<customer_auth_id>:<unix_ts>`. |
| `transactions[].status` | `completed` for settled entries. |
| `summary` | Aggregates for the filtered window: `total_transactions`, `total_debit`, `total_credit`, `net_amount`, and a `by_reference_type` breakdown. |
| `total` / `page` / `per_page` / `total_pages` | Pagination over the full filtered result set. |

<Warning>
  **Two different "type" vocabularies.** The `transaction_type` **query filter** accepts `recharge`, `debit`, `refund`, `transfer`. The `type` **field in each response row** is the ledger direction `credit` or `debit`. Don't filter on `credit`/`debit` as a `transaction_type` value - use the dedicated filter values.
</Warning>

## Transaction types (filter values)

* **`recharge`** - Wallet top-up credited to the customer. Reflected as a `credit` row. Amount is positive.
* **`debit`** - Automatic usage deduction for completed calls and DID fees. Reflected as a `debit` row. Generated per call or in daily batches depending on configuration.
* **`refund`** - Credit issued for a disputed charge or service outage. Reflected as a `credit` row.
* **`transfer`** - A partner-to-customer balance transfer. On the **customer** ledger this lands as a `credit` (with description `Transfer from partner …`); on **your** partner ledger the matching `debit` appears.

## Monthly Billing Guide

Use transactions to generate accurate invoices for your customers:

* **Pull all debits for the billing period** - Filter by `transaction_type=debit` and the billing window dates. Sum the absolute amounts.
* **Add your margin** - Apply your reseller markup on top of the raw usage cost before invoicing.
* **Check recharge history** - Confirm the customer has covered their previous balance transfers before issuing the next invoice.
* **Global reconciliation** - Use the global endpoint at month-end to reconcile your master ledger against the sum of all customer ledgers.


## OpenAPI

````yaml GET /api/v1/partner/accounts/{customer_auth_id}/transactions
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
  /api/v1/partner/accounts/{customer_auth_id}/transactions:
    get:
      tags:
        - Partner API
      summary: List customer transactions
      description: |
        Returns the customer's transaction ledger. Filter by date range or
        transaction type. Useful for billing reconciliation.
      operationId: list-customer-transactions
      parameters:
        - name: customer_auth_id
          in: path
          required: true
          schema:
            type: string
        - name: from_date
          in: query
          schema:
            type: string
            format: date
            example: '2026-03-01'
        - name: to_date
          in: query
          schema:
            type: string
            format: date
            example: '2026-03-31'
        - name: transaction_type
          in: query
          schema:
            type: string
            enum:
              - recharge
              - debit
              - refund
              - transfer
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
          description: Transactions list
          content:
            application/json:
              schema:
                type: object
                properties:
                  transactions:
                    type: array
                    items:
                      type: object
                      properties:
                        id:
                          type: string
                        account_id:
                          type: string
                        balance_id:
                          type: string
                        type:
                          type: string
                        amount:
                          type: integer
                        currency:
                          type: string
                        description:
                          type: string
                        reference:
                          type: string
                        status:
                          type: string
                        processed_at:
                          type: string
                        created_at:
                          type: string
                        updated_at:
                          type: string
                      required:
                        - id
                        - account_id
                        - balance_id
                        - type
                        - amount
                        - currency
                        - description
                        - reference
                        - status
                        - processed_at
                        - created_at
                        - updated_at
                  summary:
                    type: object
                    properties:
                      total_transactions:
                        type: integer
                      total_debit:
                        type: integer
                      total_credit:
                        type: integer
                      net_amount:
                        type: integer
                      by_reference_type:
                        type: array
                        items:
                          type: object
                          properties:
                            reference_type:
                              type: string
                            total_debit:
                              type: integer
                            total_credit:
                              type: integer
                            count:
                              type: integer
                          required:
                            - reference_type
                            - total_debit
                            - total_credit
                            - count
                    required:
                      - total_transactions
                      - total_debit
                      - total_credit
                      - net_amount
                      - by_reference_type
                  total:
                    type: integer
                  page:
                    type: integer
                  per_page:
                    type: integer
                  total_pages:
                    type: integer
                  account_auth_id:
                    type: string
                required:
                  - transactions
                  - summary
                  - total
                  - page
                  - per_page
                  - total_pages
                  - account_auth_id
              example:
                transactions:
                  - id: aabbccdd-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    balance_id: 11223344-1234-5678-90ab-cdef12345678
                    type: credit
                    amount: 200
                    currency: INR
                    description: 'Transfer from partner Acme: Balance transfer'
                    reference: >-
                      ptc:99887766-1234-5678-90ab-cdef12345678:MA_XXXXXXXX:1778140310
                    status: completed
                    processed_at: '2026-03-25T10:00:00Z'
                    created_at: '2026-03-25T10:00:00Z'
                    updated_at: '2026-03-25T10:00:00Z'
                  - id: 55667788-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    balance_id: 11223344-1234-5678-90ab-cdef12345678
                    type: credit
                    amount: 100
                    currency: INR
                    description: 'Transfer from partner Acme: Balance transfer'
                    reference: >-
                      ptc:99887766-1234-5678-90ab-cdef12345678:MA_XXXXXXXX:1778051898
                    status: completed
                    processed_at: '2026-03-24T07:18:18Z'
                    created_at: '2026-03-24T07:18:18Z'
                    updated_at: '2026-03-24T07:18:18Z'
                  - id: aabbccdd-9999-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    balance_id: 11223344-1234-5678-90ab-cdef12345678
                    type: credit
                    amount: 1000
                    currency: INR
                    description: 'Transfer from partner Acme: Balance transfer'
                    reference: >-
                      ptc:99887766-1234-5678-90ab-cdef12345678:MA_XXXXXXXX:1778051770
                    status: completed
                    processed_at: '2026-03-24T07:16:10Z'
                    created_at: '2026-03-24T07:16:10Z'
                    updated_at: '2026-03-24T07:16:10Z'
                summary:
                  total_transactions: 3
                  total_debit: 0
                  total_credit: 1300
                  net_amount: 1300
                  by_reference_type:
                    - reference_type: unknown
                      total_debit: 0
                      total_credit: 1300
                      count: 3
                total: 3
                page: 1
                per_page: 20
                total_pages: 1
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