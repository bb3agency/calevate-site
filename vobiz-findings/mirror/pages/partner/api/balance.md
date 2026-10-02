> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Balance Transfer

> Transfer credits from your Vobiz partner master wallet to a customer's wallet - the primary mechanism for funding reseller sub-accounts with prepaid voice minutes.

[← Partner API Reference](/docs/partner/api)

Transfer credits from your partner master wallet to a customer's wallet. This is the primary mechanism for reselling voice minutes - you fund your customers, who then spend from their allocated balance on calls.

<Info>
  All Partner API requests use `X-Auth-ID` and `X-Auth-Token` headers. See [Authentication](/docs/partner/api/authentication) for details.
</Info>

## Overview

| Property | Behavior |
| - | - |
| Atomic | Transfers complete or fail entirely - no partial states |
| Permanent | Cannot be reversed via API - verify amount before submitting |
| Instant | Customer wallet is credited immediately on success |

## How Balance Transfer Works

When you call the transfer endpoint, Vobiz atomically debits the specified amount from your partner master balance and credits it to the target customer's wallet. Both debit and credit are recorded as separate transaction entries in each account's ledger.

* **Your Master Balance** - debited by the transfer amount (e.g. `-₹500.00`).
* **Customer Wallet** - credited by the same amount (e.g. `+₹500.00`).

## Transfer Balance

Transfer credits from your partner master balance to a customer wallet. Transfers are **atomic and permanent** - verify the amount and target customer before submitting.

### Request Body

| Field | Type | Required | Description |
| - | - | - | - |
| `amount` | number | Required | Amount to transfer in the partner's currency |
| `currency` | string | Required | ISO 4217 currency code, e.g. `INR` |
| `description` | string | Optional | Free-text note recorded in both transaction ledgers |

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transfer-balance" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 500.00,
    "currency": "INR",
    "description": "April recharge - Credresolve"
  }'
```

```python theme={null}
import requests

BASE = "https://api.vobiz.ai/api/v1/partner"
HEADERS = {
    "X-Auth-ID": "{your_partner_id}",
    "X-Auth-Token": "{your_auth_token}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# Check your own balance first - `balance` is a STRING, cast before comparing
profile = requests.get(f"{BASE}/me", headers=HEADERS).json()
if float(profile["balance"]) >= 500.00:
    response = requests.post(
        f"{BASE}/accounts/MA_48149cf4/transfer-balance",
        headers=HEADERS,
        json={
            "amount": 500.00,
            "currency": "INR",
            "description": "April recharge - Credresolve",
        },
    )
    print(response.json())
```

### Response (200)

```json theme={null}
{
  "transaction_id": "txn_aabbccdd1234",
  "from_account": "PA_XXXXXXXX",
  "to_account": "MA_XXXXXXXX",
  "amount": 500.00,
  "currency": "INR",
  "description": "April recharge - Credresolve",
  "status": "completed",
  "partner_balance_after": 47750.00,
  "customer_balance_after": 2950.00,
  "timestamp": "2026-03-25T11:00:00Z"
}
```

| Field | Notes |
| - | - |
| `transaction_id` | The transfer's ledger reference. Store it for reconciliation - it ties the debit on your ledger to the credit on the customer's. |
| `from_account` | Your partner `auth_id` (the debited account). |
| `to_account` | The customer `auth_id` (the credited account). |
| `status` | `completed` on success. The transfer is atomic - there is no `pending` state. |
| `partner_balance_after` | Your master balance after the debit. Assert this is non-negative as a sanity check. |
| `customer_balance_after` | The customer's wallet balance after the credit. |

### Errors

```json theme={null}
{
  "error": "insufficient_balance",
  "message": "Your partner balance (₹200.00) is insufficient for this transfer (₹500.00).",
  "current_balance": 200.00,
  "requested_amount": 500.00,
  "currency": "INR"
}
```

| Status | Cause |
| - | - |
| `400` | Insufficient partner balance (payload above), non-positive `amount`, or a `currency` that doesn't match your partner account currency. |
| `401` / `403` | Invalid partner credentials, or `can_transfer_balance` is `false` on your partner profile. |
| `404` | `customer_auth_id` not found, or it belongs to a different partner. |

### Notes

* **Transfers are permanent and cannot be reversed** - Once a transfer completes, there is no API endpoint to reverse it. If you transfer the wrong amount or to the wrong customer, contact Vobiz support. Always verify the `customer_auth_id` and amount before calling this endpoint.
* **Transfers are atomic - your balance is checked at submission time** - The API checks your master balance at the moment the request is received. Both legs (your debit, the customer's credit) commit together or not at all. If concurrent transfers cause your balance to drop below the required amount between your own check and the actual transfer, the request fails with a `400` and **neither** ledger is touched.
* **Currency must match your partner account** - The `currency` you send must equal your partner account currency (`GET /me` → `currency`). A mismatched currency is rejected; the API does **not** convert between currencies.
* **No built-in idempotency key** - Retrying a transfer after a network timeout can double-credit the customer, because each call is a fresh transfer. Before retrying a request whose response you never saw, poll the customer's [transactions](/docs/partner/api/transactions) (match on `amount` + recent `created_at`) to confirm whether the first attempt landed.
* **Description appears in both ledgers** - The `description` field is recorded in your partner transaction ledger as a debit and in the customer's transaction ledger as a credit (prefixed `Transfer from partner …`). Use clear notes for easier reconciliation during billing cycles.

## Before Transferring - Checklist

* Verify the target `customer_auth_id` is correct.
* Confirm the transfer `amount` and `currency`.
* Confirm your master balance is sufficient.
* Add a clear `description` for ledger reconciliation.
* Remember that transfers are permanent and cannot be reversed via API.


## OpenAPI

````yaml POST /api/v1/partner/accounts/{customer_auth_id}/transfer-balance
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
  /api/v1/partner/accounts/{customer_auth_id}/transfer-balance:
    post:
      tags:
        - Partner API
      summary: Transfer balance to customer
      description: |
        Atomically debits your partner master balance and credits the customer's
        wallet. Both legs are recorded in each account's ledger. Transfers are
        **permanent and cannot be reversed.**
      operationId: partner-transfer-balance
      parameters:
        - name: customer_auth_id
          in: path
          required: true
          schema:
            type: string
            example: MA_ZKITB8Z2
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - amount
                - currency
              properties:
                amount:
                  type: number
                  description: Positive decimal. Your master balance must be ≥ this amount.
                  example: 500
                currency:
                  type: string
                  description: Must match your partner account currency.
                  example: INR
                description:
                  type: string
                  description: Note for your records. Appears in both ledgers.
                  example: April recharge - Credresolve
      responses:
        '200':
          description: Transfer completed
          content:
            application/json:
              example:
                transaction_id: txn_aabbccdd1234
                from_account: PA_XXXXXXXX
                to_account: MA_XXXXXXXX
                amount: 500
                currency: INR
                description: April recharge
                status: completed
                partner_balance_after: 47750
                customer_balance_after: 2950
                timestamp: '2026-03-25T11:00:00Z'
        '400':
          description: Insufficient partner balance
          content:
            application/json:
              example:
                error: insufficient_balance
                message: >-
                  Your partner balance (₹200.00) is insufficient for this
                  transfer (₹500.00).
                current_balance: 200
                requested_amount: 500
                currency: INR
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