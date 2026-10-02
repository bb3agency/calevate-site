> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Concurrency

> Retrieve real-time concurrent call usage for your Vobiz account - monitor active channels, check capacity headroom, and scale voice infrastructure globally.

## Overview

The Concurrency API lets you retrieve real-time data about how many concurrent lines are active for your account. Use it to monitor line utilization and ensure you have sufficient capacity.

## Get Concurrency

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/concurrency
```

Returns the current number of concurrent lines active for a specific account.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

### Request

```bash cURL theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/YOUR_AUTH_ID/concurrency" \
--header 'X-Auth-ID: YOUR_AUTH_ID' \
--header 'X-Auth-Token: YOUR_AUTH_TOKEN' \
--header 'Accept: application/json'
```

### Response

```json JSON Response theme={null}
{
    "account_id": "MA_XXXXXXXX",
    "concurrent_calls": 0,
    "max_concurrent": 46,
    "utilization_pct": 0,
    "request_id": "aabbccdd1234567890abcdef12345678"
}
```

### Response fields

| Field | Type | Description |
| - | - | - |
| `account_id` | string | The account these counters belong to. |
| `concurrent_calls` | integer | Number of calls currently active. |
| `max_concurrent` | integer | The account's concurrent-call ceiling. Equals `concurrent_calls_limit` from the [Account object](/docs/account/account-object) (`base_concurrent_calls_limit + purchased_concurrent_calls`). |
| `utilization_pct` | integer | `concurrent_calls` as a percentage of `max_concurrent`. |
| `request_id` | string | Unique identifier for this request, useful for support. |

<Note>
  **Concurrency vs CPS.** `max_concurrent` caps how many calls can be *live at once*; the separate CPS limit (`cps_limit`) caps how many new calls you can *start per second*. Both are raised by purchasing add-ons (`purchased_concurrent_calls`, `purchased_cps`) - see [The Account Object](/docs/account/account-object). When `utilization_pct` approaches 100, new calls are rejected until channels free up.
</Note>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/concurrency
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
  /api/v1/Account/{auth_id}/concurrency:
    get:
      tags:
        - Account
      summary: Get concurrency limits
      description: Retrieve the current concurrent call usage and configured limits.
      operationId: get-concurrency
      parameters:
        - $ref: '#/components/parameters/AuthId'
      responses:
        '200':
          description: Concurrency info
          content:
            application/json:
              example:
                account_id: MA_XXXXXXXX
                concurrent_calls: 0
                max_concurrent: 46
                utilization_pct: 0
                request_id: aabbccdd1234567890abcdef12345678
              schema:
                type: object
                properties:
                  account_id:
                    type: string
                  concurrent_calls:
                    type: integer
                  max_concurrent:
                    type: integer
                  utilization_pct:
                    type: integer
                  request_id:
                    type: string
                required:
                  - account_id
                  - concurrent_calls
                  - max_concurrent
                  - utilization_pct
                  - request_id
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