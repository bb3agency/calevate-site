> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Cancel a Number Release

> Cancel a pending phone number release during the 24-hour cooldown and restore the number to active.

Cancels a pending number release during the 24-hour cooldown and restores the number to `active`.

<Info>
  Cancelling a pending release refunds the full release fee to your account balance. The response reports the refund in `refund_amount` and `currency`.
</Info>

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/numbers/{e164}/cancel-release
```

<Warning>
  You can cancel only while the number is in `pending_release`. After the 24-hour cooldown ends, this endpoint returns `400` and recovery requires manual intervention.
</Warning>

## Authentication

The API playground uses the same authentication fields as the other Vobiz API pages:

* `X-Auth-ID` - Your account Auth ID.
* `X-Auth-Token` - Your account Auth Token.

The endpoint also accepts HTTP Basic authentication in direct requests. Use your Auth ID as the username and your Auth Token as the password, as shown in the cURL example below.

<Warning>
  Do not send the Auth Token as `Authorization: Bearer {auth_token}`. Bearer authentication is for JWT access tokens and returns `401 Invalid token` when used with an account Auth Token.
</Warning>

## Path parameters

| Parameter | Required | Description |
| - | - | - |
| `account_id` | Yes | Your account Auth ID, such as `MA_XXXXXX`. |
| `e164` | Yes | The phone number in E.164 format. URL-encode `+` as `%2B`, such as `%2B919876543210`. |

## Request

<CodeGroup>
  ```bash Basic authentication theme={null}
  curl -X POST \
    "https://api.vobiz.ai/api/v1/account/{account_id}/numbers/%2B919876543210/cancel-release" \
    -u "{account_id}:{auth_token}"
  ```

  ```bash X-Auth headers theme={null}
  curl -X POST \
    "https://api.vobiz.ai/api/v1/account/{account_id}/numbers/%2B919876543210/cancel-release" \
    -H "X-Auth-ID: {account_id}" \
    -H "X-Auth-Token: {auth_token}"
  ```
</CodeGroup>

## Behavior

When the number belongs to your account and is still in `pending_release`, Vobiz:

1. Verifies that your account owns the number.
2. Changes its status from `pending_release` to `active` and clears the cooldown timer.
3. Refunds the release fee to your account balance.
4. Returns `200 OK`.

<Warning>
  The original release already detached the trunk and voice application. Cancellation does not re-attach them. [Assign the number to a trunk](/docs/trunks/assign-number) or [attach it to an application](/docs/applications/attach-number) before routing calls again.
</Warning>

## Responses

| HTTP | Meaning |
| - | - |
| `200` | The release was cancelled and the number was restored to `active`. The response includes the refunded amount and currency. |
| `400` | The number is not in `pending_release`, so there is nothing to cancel. |
| `401` | Authentication failed. Verify the authentication method and credentials. |
| `403` | The number does not belong to this account. |
| `404` | The number was not found. |

### Release cancelled and refunded

```json Response - 200 OK theme={null}
{
  "currency": "INR",
  "message": "release cancelled, number restored to active status",
  "refund_amount": 700,
  "status": "active"
}
```

### Number restored but refund failed

The number is active even when the refund fails. Contact [Vobiz Support](https://vobiz.ai/contact-us) with the number and account details.

```json Response - 200 OK theme={null}
{
  "message": "release cancelled, number restored to active status",
  "status": "active",
  "refund_status": "failed",
  "refund_error": "could not process refund, please contact support"
}
```

### Error examples

<CodeGroup>
  ```json 400 Not Pending Release theme={null}
  {
    "error": "number is not pending release"
  }
  ```

  ```json 401 Invalid Token theme={null}
  {
    "error": {
      "code": 401,
      "message": "Invalid token"
    }
  }
  ```

  ```json 403 Access Denied theme={null}
  {
    "error": "access denied"
  }
  ```

  ```json 404 Number Not Found theme={null}
  {
    "error": "number not found"
  }
  ```
</CodeGroup>


## OpenAPI

````yaml POST /api/v1/account/{account_id}/numbers/{e164}/cancel-release
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
  /api/v1/account/{account_id}/numbers/{e164}/cancel-release:
    post:
      tags:
        - Phone Numbers
      summary: Cancel a number release
      description: >
        Cancel a pending number release during the 24-hour cooldown. The number
        is

        restored to `active`, the cooldown timer is cleared, and the release fee
        is

        refunded in full to the account balance. Any trunk or voice application

        detached by the release is not re-attached automatically.
      operationId: cancel-number-release
      parameters:
        - name: account_id
          in: path
          required: true
          description: Your account Auth ID.
          schema:
            type: string
            example: MA_XXXXXX
        - name: e164
          in: path
          required: true
          description: The URL-encoded phone number in E.164 format. Encode `+` as `%2B`.
          schema:
            type: string
            example: '%2B919876543210'
      responses:
        '200':
          description: Release cancelled and number restored to active
          content:
            application/json:
              schema:
                type: object
                properties:
                  message:
                    type: string
                  status:
                    type: string
                    enum:
                      - active
                  currency:
                    type: string
                  refund_amount:
                    type: number
                  refund_status:
                    type: string
                    enum:
                      - success
                      - failed
                  refund_error:
                    type: string
                    description: Present when the refund could not be processed.
                required:
                  - message
                  - status
              examples:
                refunded:
                  summary: Number restored and fee refunded
                  value:
                    message: release cancelled, number restored to active status
                    status: active
                    currency: INR
                    refund_amount: 700
                refundFailed:
                  summary: Number restored but refund failed
                  value:
                    message: release cancelled, number restored to active status
                    status: active
                    refund_status: failed
                    refund_error: could not process refund, please contact support
        '400':
          description: The number is not pending release
          content:
            application/json:
              example:
                error: number is not pending release
        '401':
          description: Authentication failed
          content:
            application/json:
              example:
                error:
                  code: 401
                  message: Invalid token
        '403':
          description: The number does not belong to this account
          content:
            application/json:
              example:
                error: access denied
        '404':
          description: Number not found
          content:
            application/json:
              example:
                error: number not found
      security:
        - AuthID: []
          AuthToken: []
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