> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Transactions

> Retrieve a full Vobiz transaction ledger - credits, debits, call charges, DID rentals, and invoice history with per-day totals and reference-type breakdowns.

## Get Transactions

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/transactions
```

Returns a list of transactions for a specific account.

<Info>
  **Authentication** - either scheme works:

  * `X-Auth-ID` + `X-Auth-Token` headers, or
  * HTTP Basic, `curl -u 'YOUR_AUTH_ID:YOUR_AUTH_TOKEN'`

  The `{auth_id}` in the path must match the authenticated account. Passing another account's ID returns `403 Access denied: account ID mismatch`.
</Info>

### Request

```bash cURL theme={null}
curl --location 'https://api.vobiz.ai/api/v1/Account/YOUR_AUTH_ID/transactions?page=1&per_page=50' \
--header 'X-Auth-ID: YOUR_AUTH_ID' \
--header 'X-Auth-Token: YOUR_AUTH_TOKEN' \
--header 'Accept: application/json'
```

### Response

```json JSON Response theme={null}
{
    "transactions": [
        {
            "id": "aabbccdd-1234-5678-90ab-cdef12345678",
            "account_id": "MA_XXXXXX",
            "balance_id": "11223344-5566-7788-99aa-bbccddeeff00",
            "type": "debit",
            "amount": 0.9,
            "currency": "INR",
            "description": "Stream session (70s)",
            "reference": "cdr:e565c2de-975c-4ba5-b115-44b1042cd397",
            "reference_type": "cdr",
            "status": "completed",
            "processed_at": "2025-12-08T09:38:06.923988Z",
            "created_at": "2025-12-08T09:38:06.923988Z",
            "updated_at": "2025-12-08T09:38:06.923988Z"
        }
    ],
    "summary": {
        "total_transactions": 125,
        "total_debit": 150.75,
        "total_credit": 500.00,
        "net_amount": 349.25,
        "by_reference_type": [
            {
                "reference_type": "cdr",
                "total_debit": 140.25,
                "total_credit": 0,
                "count": 110
            },
            {
                "reference_type": "did_rental",
                "total_debit": 10.50,
                "total_credit": 0,
                "count": 14
            },
            {
                "reference_type": "payment",
                "total_debit": 0,
                "total_credit": 500.00,
                "count": 1
            }
        ]
    },
    "total": 125,
    "page": 1,
    "per_page": 50,
    "total_pages": 3
}
```

<Note>
  Each transaction is keyed to the owning account by `account_id`. The `reference_type` groups spend by source - `cdr` (per-call charges), `did_rental` (phone-number setup and monthly fees), `manual_adjustment`, `payment`, and `refund`. DID purchases and recurring monthly number fees appear here as `did_rental` debits.
</Note>

### Query parameters

Every filter is optional and they are AND-ed together.

| Field | Type | Description |
| - | - | - |
| `page` | integer | Page number, 1-indexed. Default: 1. |
| `per_page` | integer | Records per page. Default: 50. Maximum: 1000. |
| `from_date` | string | Start of the window, inclusive. Matches on `created_at`. |
| `to_date` | string | End of the window, inclusive. Matches on `created_at`. |
| `type` | string | `credit` or `debit` as a broad classification, or any literal type for an exact match. |
| `status` | string | `completed`, `pending`, `failed`, or `cancelled`. Exact match. |
| `currency` | string | Currency code, e.g. `INR`. Uppercased server-side. |
| `reference_type` | string | Spend source, e.g. `cdr`, `did_rental`, `recording`. Exact match. |
| `description` | string | Case-insensitive substring match on the description. |
| `reference` | string | Case-insensitive substring match on the reference. |
| `transaction_id` | string | Fetch one entry by its UUID. |

Results are always ordered by `created_at` descending. There is no sort override.

<Warning>
  **`limit` and `offset` are not supported.** Unknown query parameters are silently dropped, so `?limit=100&offset=0` returns the default 50 rows on page 1 and never advances. Use `page` and `per_page`.

  Likewise, a `per_page` above 1000 **falls back to 50** rather than clamping to the maximum - `per_page=5000` returns 50 rows. The only signal is the `per_page` value echoed in the response, so assert on it.
</Warning>

### Fetch all transactions for one date

Set `from_date` and `to_date` to the same date. A bare `YYYY-MM-DD` in `to_date` is expanded to `23:59:59`, so both bounds are inclusive and one request covers the whole day:

```bash cURL theme={null}
curl -sS -G 'https://api.vobiz.ai/api/v1/account/YOUR_AUTH_ID/transactions' \
--header 'X-Auth-ID: YOUR_AUTH_ID' \
--header 'X-Auth-Token: YOUR_AUTH_TOKEN' \
--header 'Accept: application/json' \
--data-urlencode 'from_date=2026-08-28' \
--data-urlencode 'to_date=2026-08-28' \
--data-urlencode 'per_page=1000' \
--data-urlencode 'page=1'
```

If a day exceeds 1000 rows, read `total_pages` from the response and walk `page=2`, `page=3`, and so on.

### Daily totals without paging

The `summary` block is computed over the **entire filtered set**, not just the current page. For reconciliation totals you can request a single row and read `summary` alone:

```bash cURL theme={null}
curl -sS -G 'https://api.vobiz.ai/api/v1/account/YOUR_AUTH_ID/transactions' \
--header 'X-Auth-ID: YOUR_AUTH_ID' \
--header 'X-Auth-Token: YOUR_AUTH_TOKEN' \
--data-urlencode 'from_date=2026-08-28' \
--data-urlencode 'to_date=2026-08-28' \
--data-urlencode 'per_page=1'
```

`summary.total_debit`, `summary.total_credit`, `summary.net_amount`, and the `by_reference_type` breakdown all cover the full day.

### Pinning a day to a specific timezone

`created_at` is stored with a timezone and a bare date is resolved in the server's timezone (UTC). For a true IST calendar day, send explicit offsets:

```bash cURL theme={null}
curl -sS -G 'https://api.vobiz.ai/api/v1/account/YOUR_AUTH_ID/transactions' \
--header 'X-Auth-ID: YOUR_AUTH_ID' \
--header 'X-Auth-Token: YOUR_AUTH_TOKEN' \
--data-urlencode 'from_date=2026-08-28T00:00:00+05:30' \
--data-urlencode 'to_date=2026-08-28T23:59:59+05:30' \
--data-urlencode 'per_page=1000'
```

<Warning>
  Use `-G` with `--data-urlencode` (or URL-encode `+` as `%2B` yourself). A raw `+` in a query string decodes as a space, and the malformed timestamp returns `500 {"error": "Failed to retrieve transactions"}`.

  The automatic `23:59:59` expansion only applies to a bare 10-character date, so an explicit timestamp must carry its own end-of-day time.
</Warning>

### Discovering reference types

To list the `reference_type` values actually present on an account:

```bash cURL theme={null}
curl -sS 'https://api.vobiz.ai/api/v1/account/YOUR_AUTH_ID/transactions/reference-types' \
--header 'X-Auth-ID: YOUR_AUTH_ID' \
--header 'X-Auth-Token: YOUR_AUTH_TOKEN'
```

```json JSON Response theme={null}
{
  "reference_types": ["cdr", "did_purchase", "did_rental", "manual_adjustment", "ncc", "recording", "stream_cdr", "transcription"]
}
```

### Integration notes

<Note>
  * **`type=debit` is a classification, not an equality test.** It sweeps in legacy entry types stored directly in the `type` column - a `type=debit` query on an account with DID rentals returns rows whose `type` is `did_rental` alongside the `debit` rows. Totals from this filter will not match a naive `type = 'debit'` comparison.
  * **`reference` is omitted when null**, rather than being sent as `null`. Treat it as an optional key.
  * **Sub-account IDs (`SA_...`) resolve to the parent account's ledger.** A sub-account query returns the parent's full transaction list, not a sub-account-scoped slice.
  * **A zeroed `summary` alongside a non-empty `transactions` array is a degraded response**, not an empty day - summary computation failing does not fail the request.
</Note>

### Errors

| Status | Body | Cause |
| - | - | - |
| `400` | `{"error": "accountID is required"}` | Missing account ID in the path. |
| `401` | `{"error": {"code": 401, "message": "Invalid token"}}` | Bad or missing credentials. |
| `403` | `{"error": {"code": 403, "message": "Access denied: account ID mismatch"}}` | The path account ID is not the authenticated account. |
| `500` | `{"error": "Failed to retrieve transactions"}` | Unparseable date - check formatting before treating it as an empty day. |

## Related

<CardGroup cols={2}>
  <Card title="Account Balance" icon="wallet" href="/docs/account/balance">
    Check available balance, reserved funds, and credit limit by currency.
  </Card>

  <Card title="Call Detail Records" icon="file-lines" href="/docs/cdr/list-cdrs">
    Trace a `cdr` reference back to the call that generated the charge.
  </Card>
</CardGroup>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/transactions
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
  /api/v1/Account/{auth_id}/transactions:
    get:
      tags:
        - Balance
      summary: List transactions
      description: |
        Retrieve paginated transaction history for the account, ordered by
        `created_at` descending. Filter to a single day by setting `from_date`
        and `to_date` to the same date - a bare `YYYY-MM-DD` in `to_date` is
        expanded to `23:59:59`, so both bounds are inclusive. Bare dates resolve
        in the server timezone (UTC); send an explicit offset such as
        `2026-08-28T00:00:00+05:30` to pin a local calendar day.

        `limit` and `offset` are not supported - unknown parameters are silently
        dropped. `total` and `summary` are computed over the whole filtered set
        and ignore pagination, so `per_page=1` returns full-window totals.
      operationId: list-transactions
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: page
          in: query
          description: Page number, 1-indexed.
          schema:
            type: integer
            default: 1
        - name: per_page
          in: query
          description: >-
            Records per page. A value above the maximum falls back to the
            default of 50 rather than clamping.
          schema:
            type: integer
            default: 50
            maximum: 1000
        - name: from_date
          in: query
          description: >-
            Start of the window, inclusive. Date-only or full ISO 8601
            timestamp. Day boundaries are UTC.
          schema:
            type: string
            example: '2026-08-25'
        - name: to_date
          in: query
          description: >-
            End of the window, inclusive. A date-only value covers the whole
            day.
          schema:
            type: string
            example: '2026-08-25'
        - name: type
          in: query
          description: >-
            `credit` or `debit` act as broad classifications and sweep in legacy
            entry types such as `did_rental`; any other value is an exact match
            on `transactions[].type`.
          schema:
            type: string
            example: debit
        - name: status
          in: query
          description: Exact match on transaction status.
          schema:
            type: string
            enum:
              - completed
              - pending
              - failed
              - cancelled
        - name: currency
          in: query
          description: Currency code. Uppercased server-side, exact match.
          schema:
            type: string
            example: INR
        - name: reference_type
          in: query
          description: Spend source, matching `transactions[].reference_type`.
          schema:
            type: string
            example: cdr
        - name: description
          in: query
          description: Case-insensitive substring match on the description.
          schema:
            type: string
        - name: reference
          in: query
          description: Case-insensitive substring match on the reference.
          schema:
            type: string
        - name: transaction_id
          in: query
          description: Fetch a single ledger entry by its UUID.
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Transaction list
          content:
            application/json:
              example:
                transactions:
                  - id: aabbccdd-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    balance_id: 11223344-5566-7788-99aa-bbccddeeff00
                    type: debit
                    amount: 0.08
                    currency: INR
                    description: Call to 919876543210 (1s)
                    reference: cdr:99887766-aabb-ccdd-eeff-001122334455
                    reference_type: cdr
                    status: completed
                    processed_at: '2026-05-11T06:59:32.806790Z'
                    created_at: '2026-05-11T06:59:32.806790Z'
                    updated_at: '2026-05-11T06:59:32.806790Z'
                summary:
                  total_transactions: 5657
                  total_debit: 138901.97
                  total_credit: 350806
                  net_amount: 211904.03
                  by_reference_type:
                    - reference_type: cdr
                      total_debit: 932.93
                      total_credit: 0
                      count: 1866
                    - reference_type: did_rental
                      total_debit: 18100
                      total_credit: 0
                      count: 44
                    - reference_type: manual_adjustment
                      total_debit: 0
                      total_credit: 2455
                      count: 6
                total: 5657
                page: 1
                per_page: 50
                total_pages: 114
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
                          type: number
                        currency:
                          type: string
                        description:
                          type: string
                        reference:
                          type: string
                        reference_type:
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
                        type: number
                      total_credit:
                        type: integer
                      net_amount:
                        type: number
                      by_reference_type:
                        type: array
                        items:
                          type: object
                          properties:
                            reference_type:
                              type: string
                            total_debit:
                              type: number
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
                required:
                  - transactions
                  - summary
                  - total
                  - page
                  - per_page
                  - total_pages
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