> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Balance

> Check your Vobiz account balance by currency - available balance, reserved funds, promotional credit, credit limit, and low-balance thresholds.

## Get Balance

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/balance/{currency}
```

Returns the balance for a specific account and currency.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

### Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your account Auth ID. |
| `currency` | string | Yes | Currency code to query (e.g., `INR`, `USD`). Must match a currency the account holds a balance in. |

### Response fields

| Field | Type | Description |
| - | - | - |
| `balance` | number | Total ledger balance. |
| `reserved_funds` | number | Funds held against in-progress calls or pending charges. |
| `promotional_balance` | number | Non-withdrawable promotional credit. |
| `available_balance` | number | Spendable amount (`balance` minus reservations). Check this before purchasing a number. |
| `credit_limit` | number | Postpaid credit line. |
| `is_postpaid` | boolean | Whether the account bills postpaid. |
| `credit_limit_type` | string | `soft` or `hard`. A `hard` limit blocks new calls/purchases once exhausted. |
| `low_balance_threshold` | number | Threshold below which low-balance alerts fire. |
| `status` | string | Balance status (e.g., `active`). |

### Request

```bash cURL theme={null}
curl --location 'https://api.vobiz.ai/api/v1/Account/YOUR_AUTH_ID/balance/INR' \
--header 'X-Auth-ID: YOUR_AUTH_ID' \
--header 'X-Auth-Token: YOUR_AUTH_TOKEN' \
--header 'Accept: application/json'
```

### Response

```json JSON Response theme={null}
{
    "id": "aabbccdd-1234-5678-90ab-cdef12345678",
    "account_id": "MA_XXXXXXXX",
    "currency": "INR",
    "balance": 1000.00,
    "reserved_funds": 0,
    "promotional_balance": 0,
    "promotional_reserved_balance": 0,
    "available_balance": 1000.00,
    "credit_limit": 1000,
    "is_postpaid": true,
    "credit_limit_type": "soft",
    "low_balance_threshold": 50,
    "status": "active",
    "created_at": "2026-01-19T18:39:15.050543Z",
    "updated_at": "2026-05-11T06:59:32.802705Z"
}
```

## Related

<CardGroup cols={2}>
  <Card title="Transactions" icon="receipt" href="/docs/account/transactions">
    Retrieve the credit and debit ledger behind the balance, with per-day totals.
  </Card>

  <Card title="Channel Pricing Preview" icon="tags" href="/docs/account/channel-pricing-preview">
    Preview what a channel subscription will cost before it debits the balance.
  </Card>
</CardGroup>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/balance/{currency}
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
  /api/v1/Account/{auth_id}/balance/{currency}:
    get:
      tags:
        - Balance
      summary: Get balance
      description: Retrieve the current account balance for a specific currency.
      operationId: get-balance
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: currency
          in: path
          required: true
          description: Currency code (e.g. INR, USD)
          schema:
            type: string
            example: INR
      responses:
        '200':
          description: Account balance
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  account_id:
                    type: string
                  currency:
                    type: string
                  balance:
                    type: number
                  reserved_funds:
                    type: integer
                  promotional_balance:
                    type: integer
                  promotional_reserved_balance:
                    type: integer
                  available_balance:
                    type: number
                  credit_limit:
                    type: integer
                  is_postpaid:
                    type: boolean
                  credit_limit_type:
                    type: string
                  low_balance_threshold:
                    type: integer
                  status:
                    type: string
                  created_at:
                    type: string
                  updated_at:
                    type: string
                required:
                  - id
                  - account_id
                  - currency
                  - balance
                  - reserved_funds
                  - promotional_balance
                  - promotional_reserved_balance
                  - available_balance
                  - credit_limit
                  - is_postpaid
                  - credit_limit_type
                  - low_balance_threshold
                  - status
                  - created_at
                  - updated_at
              example:
                id: aabbccdd-1234-5678-90ab-cdef12345678
                account_id: MA_XXXXXXXX
                currency: INR
                balance: 23906.83
                reserved_funds: 0
                promotional_balance: 0
                promotional_reserved_balance: 0
                available_balance: 23906.83
                credit_limit: 1000
                is_postpaid: true
                credit_limit_type: soft
                low_balance_threshold: 50
                status: active
                created_at: '2026-01-19T18:39:15.050543Z'
                updated_at: '2026-05-11T06:59:32.802705Z'
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