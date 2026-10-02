> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Assign DID to Sub-Account

> Assign a parent-pool DID to one of your sub-accounts so it can place and receive calls on that number.

Assigns a DID from the parent account's number pool to a sub-account. Once assigned, the sub-account can place and receive calls on the number.

<Info>
  Authenticate with `X-Auth-ID` / `X-Auth-Token` (the parent account's credentials).
</Info>

<Warning>
  **Path casing:** this endpoint uses **lowercase `/account/`** and the **singular** `assign-subaccount` segment - unlike the capital-A `/Account/` used by inventory, purchase, list, trunk-assign, and release. Copy the path verbatim or you will get a `404`.
</Warning>

<Warning>
  **URL-encode the number.** Replace the `+` in the E.164 path segment with `%2B` (e.g. `%2B919876543210`).
</Warning>

## Path parameters

* **`auth_id`** - the parent (`MA_`) account's Auth ID.
* **`e164`** - the DID in E.164 format, URL-encoded (`%2B` for `+`). The number must be owned by the parent account's pool.

## Request body

| Field | Type | Required | Description |
| - | - | - | - |
| `sub_account_id` | string | Yes | The sub-account (`SA_...`) to receive the DID. |

```bash cURL Request theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{auth_id}/numbers/%2B919876543210/assign-subaccount" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{ "sub_account_id": "SA_XXXXXX" }'
```

## Response

A successful assignment returns `200` or `204` with no body.

<Info>
  **Error Response (404 Not Found):** the number is not in the parent pool, or the sub-account does not exist:

  ```json Error Response - 404 Not Found theme={null}
  {
    "error": "not_found",
    "message": "number or sub-account not found"
  }
  ```
</Info>

<Note>
  Moving the number back to the parent pool is subject to a **15-day cool-off** - see [Unassign DID](/docs/account-phone-number/unassign-subaccount).
</Note>


## OpenAPI

````yaml POST /api/v1/account/{auth_id}/numbers/{e164}/assign-subaccount
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
  /api/v1/account/{auth_id}/numbers/{e164}/assign-subaccount:
    post:
      tags:
        - Phone Numbers
      summary: Assign DID to a sub-account
      description: Assign a parent-pool DID to a sub-account.
      operationId: assign-did-to-subaccount
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: e164
          in: path
          required: true
          description: The number in E.164, URL-encoded (use %2B instead of +).
          schema:
            type: string
            example: '%2B919876543210'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - sub_account_id
              properties:
                sub_account_id:
                  type: string
                  example: SA_XXXXXX
      responses:
        '200':
          description: DID assigned to the sub-account
        '204':
          description: DID assigned to the sub-account
        '404':
          description: Number or sub-account not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
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
  schemas:
    Error:
      type: object
      properties:
        api_id:
          type: string
        error:
          type: string
        message:
          type: string
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