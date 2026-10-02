> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Get KYC Status

> Retrieve the aggregated KYC state for a customer_use sub-account - which verifications have passed, whether calls are still blocked, and the business type.

Returns the aggregated KYC state for a `customer_use` sub-account: the per-document verification states, whether calls are still blocked (`kyc_calls_blocked`), and the `business_type`.

<Info>
  Authenticate with your **parent main account's** `X-Auth-ID` and `X-Auth-Token` - the same credentials used everywhere else in the API. The caller must own the sub-account (or be an admin).
</Info>

## Response fields

| Field | Type | Description |
| - | - | - |
| `sub_account_id` | string | The sub-account's `auth_id` (`SA_…`). |
| `kyc_mode` | string | `personal_use` or `customer_use`. |
| `business_type` | string | The legal constitution that drives required documents. |
| `overall_status` | string | Aggregate state: `not_started`, `pending`, `verified`, or `failed`. |
| `kyc_calls_blocked` | boolean | `true` while the sub-account still needs KYC before it can place calls. |
| `verifications` | object | Per-document state keyed by type (`pan`, `gst`, `cin`, `aadhaar`), each `not_started` / `pending` / `verified` / `failed`. |

## Response example

```json 200 OK theme={null}
{
  "sub_account_id": "SA_XXXXXX",
  "kyc_mode": "customer_use",
  "business_type": "private_limited",
  "overall_status": "pending",
  "kyc_calls_blocked": true,
  "verifications": {
    "pan": "verified",
    "gst": "pending",
    "aadhaar": "not_started",
    "cin": "not_started"
  }
}
```

| Status | Cause |
| - | - |
| `403` | The caller is not the parent of this sub-account. |
| `404` | Sub-account not found. |

<Tip>
  Poll this endpoint after each verification (or on each webhook) and gate the customer's "go live" on `kyc_calls_blocked === false`.
</Tip>


## OpenAPI

````yaml GET /api/v1/sub-accounts/{sub_auth_id}/kyc/status
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
  /api/v1/sub-accounts/{sub_auth_id}/kyc/status:
    get:
      tags:
        - Sub-Account KYC
      summary: Get sub-account KYC status
      description: |
        Returns the aggregated KYC state for a `customer_use` sub-account —
        which verifications have passed, whether calls are still blocked, and
        the business type. The caller must be the parent main account that owns
        the sub-account (or an admin).
      operationId: get-subaccount-kyc-status
      parameters:
        - $ref: '#/components/parameters/SubAuthId'
      responses:
        '200':
          description: Aggregated KYC state
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SubAccountKycStatus'
              example:
                sub_account_id: SA_XXXXXX
                kyc_mode: customer_use
                business_type: private_limited
                overall_status: pending
                kyc_calls_blocked: true
                verifications:
                  pan: verified
                  gst: pending
                  aadhaar: not_started
                  cin: not_started
        '403':
          description: Caller is not the parent of this sub-account
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '404':
          description: Sub-account not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  parameters:
    SubAuthId:
      name: sub_auth_id
      in: path
      required: true
      description: The sub-account's Auth ID.
      schema:
        type: string
        example: SA_XXXXXX
  schemas:
    SubAccountKycStatus:
      type: object
      description: Aggregated KYC state for a sub-account.
      properties:
        sub_account_id:
          type: string
        kyc_mode:
          type: string
          enum:
            - personal_use
            - customer_use
        business_type:
          type: string
        overall_status:
          type: string
          enum:
            - not_started
            - pending
            - verified
            - failed
        kyc_calls_blocked:
          type: boolean
          description: >-
            True while the sub-account still needs KYC before it can place
            calls.
        verifications:
          type: object
          description: Per-document state keyed by verification type.
          additionalProperties:
            type: string
            enum:
              - not_started
              - pending
              - verified
              - failed
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