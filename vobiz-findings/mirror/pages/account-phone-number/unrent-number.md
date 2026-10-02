> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Release a Phone Number

> Release a Vobiz phone number for an account-specific fee, with a 24-hour cancellation window or an immediate-release option.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/{e164}
```

Releases a phone number from your account. Vobiz charges the number-release fee configured for your account. A standard release enters `pending_release` for 24 hours before it completes.

<Warning>
  Releasing or unrenting a number is not free. The release fee is account-specific, and the API returns the amount charged in `release_fee`.
</Warning>

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  Releasing a number detaches its trunk and voice application. Cancelling a pending release restores the number to `active`, but it does not restore those routing assignments.
</Warning>

<Info>
  During the 24-hour cooldown, use [Cancel Release](/docs/account-phone-number/cancel-release) to keep the number. An immediate release cannot be cancelled.
</Info>

<Info>
  If you cancel a standard release while it is still pending, Vobiz refunds the full release fee to your account balance.
</Info>

## Release fee

The amount charged for unrenting a number comes from your account's pricing configuration. It is separate from the recurring monthly rental fee that stops after release.

* The release operation is not free.
* The fee can differ between Vobiz accounts.
* The successful release response reports the charged amount in `release_fee`.
* Cancelling a standard release during the 24-hour pending window refunds that fee.
* An immediate release cannot be cancelled through the Cancel Release endpoint.

## Path parameters

* **`auth_id`** - Your account Auth ID.
* **`e164`** - The phone number to release in E.164 format. URL-encode `+` as `%2B`, such as `%2B919876543210`.
* **`immediate`** - Optional boolean query parameter. Set it to `true` to skip the 24-hour cooldown.

<Note>
  This path uses the capital-A `/Account/` casing. The `e164` segment must include the URL-encoded `+`. No request body is required.
</Note>

## Request

### Standard release

```bash cURL Request theme={null}
curl -X DELETE "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/%2B919876543210" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

### Immediate release

```bash cURL Request theme={null}
curl -X DELETE "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/%2B919876543210?immediate=true" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

## Response

A standard release returns `200 OK` with the cooldown, cancellation URL, and the account-specific fee charged for the release.

```json Response - 200 OK theme={null}
{
  "cancel_url": "/api/v1/account/MA_XXXXXX/numbers/+919876543210/cancel-release",
  "cooldown_ends_at": "2026-07-21T09:18:26.785758533Z",
  "message": "number release initiated",
  "note": "Number will be in pending_release for 24 hours (cancellable), then quarantined for 45 days before becoming available.",
  "release_fee": 700,
  "status": "pending_release"
}
```

The `release_fee` value above is an example. Your response contains the fee configured for your Vobiz account.

<Tip>
  **Standard release:** The number enters `pending_release` for 24 hours. You can cancel during this window.

  **Immediate release:** The number skips the cooldown and cannot be recovered through the Cancel Release endpoint.
</Tip>

<Info>
  **Error Response (403 Forbidden):** If account does not own this number:

  ```json Error Response - 403 Forbidden theme={null}
  {
    "error": "forbidden",
    "message": "account does not own this number"
  }
  ```
</Info>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/numbers/{e164}
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
  /api/v1/Account/{auth_id}/numbers/{e164}:
    delete:
      tags:
        - Phone Numbers
      summary: Release a number
      description: |
        Release a phone number from your account. Releasing a number incurs the
        number-release fee configured for the account; the response returns the
        charged amount in `release_fee`. By default, the number enters
        `pending_release` for a 24-hour cooldown. Cancelling during that window
        refunds the release fee. Set `immediate=true` to skip the cooldown; an
        immediate release cannot be cancelled.
      operationId: unrent-number
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: e164
          in: path
          required: true
          description: The URL-encoded phone number in E.164 format. Encode `+` as `%2B`.
          schema:
            type: string
            example: '%2B919876543210'
        - name: immediate
          in: query
          required: false
          description: Skip the 24-hour cooldown and release the number immediately.
          schema:
            type: boolean
            default: false
      responses:
        '200':
          description: Release initiated
          content:
            application/json:
              schema:
                type: object
                properties:
                  cancel_url:
                    type: string
                  cooldown_ends_at:
                    type: string
                    format: date-time
                  message:
                    type: string
                  note:
                    type: string
                  release_fee:
                    type: number
                    description: The account-specific fee charged for releasing the number.
                  status:
                    type: string
                required:
                  - cancel_url
                  - cooldown_ends_at
                  - message
                  - release_fee
                  - status
              example:
                cancel_url: /api/v1/account/MA_XXXXXX/numbers/+919876543210/cancel-release
                cooldown_ends_at: '2026-07-21T09:18:26.785758533Z'
                message: number release initiated
                note: >-
                  Number will be in pending_release for 24 hours (cancellable),
                  then quarantined for 45 days before becoming available.
                release_fee: 700
                status: pending_release
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