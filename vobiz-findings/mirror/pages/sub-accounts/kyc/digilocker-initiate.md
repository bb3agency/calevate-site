> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DigiLocker Initiate

> Start a DigiLocker-based Aadhaar verification - returns the authorization link and an access_request_id for the customer to complete OAuth.

Starts a DigiLocker-based Aadhaar verification. Returns the DigiLocker authorization link and an `access_request_id`. Redirect the customer to the link to complete OAuth on the DigiLocker portal, then finalize with [DigiLocker Verify](/docs/sub-accounts/kyc/digilocker-verify).

<Info>
  Authenticate with your **parent main account's** `X-Auth-ID` and `X-Auth-Token` - the same credentials used everywhere else in the API.
</Info>

<Steps>
  <Step title="Initiate">
    Call this endpoint with your `redirect_url` (and optional `oauth_state`). Capture `access_request_id` and send the customer to the returned `auth_url`.
  </Step>

  <Step title="Customer completes OAuth">
    The customer authorizes on the DigiLocker portal and is returned to your `redirect_url`.
  </Step>

  <Step title="Verify">
    Call [DigiLocker Verify](/docs/sub-accounts/kyc/digilocker-verify) with the `access_request_id`.
  </Step>
</Steps>

## Request body

| Field | Type | Required | Description |
| - | - | - | - |
| `redirect_url` | string (URI) | Yes | Where DigiLocker returns the customer after OAuth. |
| `oauth_state` | string | No | Opaque value echoed back on the redirect - use it for CSRF protection by comparing it to a value you stored before redirecting. |

## Response example

```json 200 OK theme={null}
{
  "auth_url": "https://api.digitallocker.gov.in/public/oauth2/1/authorize?...",
  "access_request_id": "AR_xxxxxxxx"
}
```

<Note>
  Store the `access_request_id` against the customer's session before redirecting. The OAuth round-trip happens in the customer's browser; you finalize server-side in the next step using this id.
</Note>


## OpenAPI

````yaml POST /api/v1/sub-accounts/{sub_auth_id}/kyc/digilocker/initiate
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
  /api/v1/sub-accounts/{sub_auth_id}/kyc/digilocker/initiate:
    post:
      tags:
        - Sub-Account KYC
      summary: DigiLocker initiate
      description: |
        Returns the DigiLocker authorization link and an `access_request_id`.
        The customer completes the OAuth flow on the DigiLocker portal, after
        which you finalize with
        [DigiLocker verify](#operation/subaccount-digilocker-verify).
      operationId: subaccount-digilocker-initiate
      parameters:
        - $ref: '#/components/parameters/SubAuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - redirect_url
              properties:
                redirect_url:
                  type: string
                  format: uri
                  example: https://partner.example.com/kyc/callback
                oauth_state:
                  type: string
                  description: >-
                    Opaque value echoed back on the redirect for CSRF
                    protection.
                  example: opaque-state-xyz
      responses:
        '200':
          description: DigiLocker authorization link
          content:
            application/json:
              example:
                auth_url: https://api.digitallocker.gov.in/public/oauth2/1/authorize?...
                access_request_id: AR_xxxxxxxx
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