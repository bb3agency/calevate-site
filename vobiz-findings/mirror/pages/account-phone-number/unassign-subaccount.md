> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Unassign DID (15-Day Cool-Off)

> Move a DID back to the parent pool. A 15-day cool-off blocks numbers that had a call in the last 15 days; admins can bypass with force=true.

Moves a DID back to the parent account's pool from a sub-account.

<Info>
  Authenticate with `X-Auth-ID` / `X-Auth-Token` (the parent account's credentials).
</Info>

<Warning>
  **Path casing:** this endpoint uses **lowercase `/account/`** and the **singular** `assign-subaccount` segment (the same path as the assign call, with `DELETE`). The other number endpoints use capital-A `/Account/`. Copy it verbatim or you will get a `404`.
</Warning>

<Warning>
  **URL-encode the number.** Replace the `+` in the E.164 path segment with `%2B` (e.g. `%2B919876543210`).
</Warning>

## Path parameters

* **`auth_id`** - the parent (`MA_`) account's Auth ID.
* **`e164`** - the DID in E.164 format, URL-encoded (`%2B` for `+`).

## Query parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `force` | boolean | No | Admin-only cool-off bypass. Requires an admin-role account; writes a `did_assignment_audit` row. |

## Response

On success the DID returns to the parent pool and the endpoint responds with `200` or `204` (no body).

## 15-day cool-off

To prevent a number that was actively used by one customer from being reassigned to another too quickly, unassignment enforces a **15-day cool-off**:

| Situation | Behavior |
| - | - |
| DID had a call within the last 15 days | Rejected with `409` and `did_cool_off_in_effect`. |
| DID never used (`last_call_at` is `NULL`) | Moves back to the parent pool immediately. |

The `409` response tells you exactly how long is left:

```json theme={null}
{
  "error": "did_cool_off_in_effect",
  "cool_off_until": "2026-06-09T10:00:00Z",
  "cool_off_remaining_seconds": 1209600
}
```

## Admin bypass

Admins can override the cool-off with the `force=true` query parameter:

```bash theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/account/{auth_id}/numbers/%2B919876543210/assign-subaccount?force=true" \
  -H "X-Auth-ID: {admin_auth_id}" \
  -H "X-Auth-Token: {admin_auth_token}"
```

<Warning>
  `force=true` requires an **admin-role account** (enforced at the gateway) and writes a `did_assignment_audit` row. A non-admin account using `force=true` is rejected with `403`.
</Warning>


## OpenAPI

````yaml DELETE /api/v1/account/{auth_id}/numbers/{e164}/assign-subaccount
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
    delete:
      tags:
        - Phone Numbers
      summary: Unassign DID (15-day cool-off enforced)
      description: |
        Move the DID back to the parent pool.

        A **15-day cool-off** is enforced: if the DID had a call within the last
        15 days, the request is rejected with `409` and a
        `did_cool_off_in_effect` error that includes `cool_off_until` and
        `cool_off_remaining_seconds`. Never-used DIDs (`last_call_at` is `NULL`)
        move back immediately.

        Admins can bypass the cool-off with `?force=true` (see below); the
        bypass writes a `did_assignment_audit` row and requires an
        admin-role account.
      operationId: unassign-did-from-subaccount
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: e164
          in: path
          required: true
          description: The number in E.164, URL-encoded (use %2B instead of +).
          schema:
            type: string
            example: '%2B919876543210'
        - name: force
          in: query
          required: false
          description: |
            Admin-only cool-off bypass. Requires an admin-role account
            (enforced at the gateway) and writes a `did_assignment_audit` row.
          schema:
            type: boolean
            example: true
      responses:
        '200':
          description: DID moved back to the parent pool
        '204':
          description: DID moved back to the parent pool
        '403':
          description: '`force=true` requested without an admin-role account'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '409':
          description: Cool-off in effect - the DID had a call within the last 15 days
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: did_cool_off_in_effect
                cool_off_until: '2026-06-09T10:00:00Z'
                cool_off_remaining_seconds: 1209600
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