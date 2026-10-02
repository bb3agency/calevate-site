> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Verify PAN

> Run a real-time PAN verification for a customer_use sub-account. Persists the result and recomputes the sub-account's aggregated KYC status.

Runs a real PAN verification for the sub-account. `pan` must be exactly 10 characters. The result is persisted and the sub-account's aggregated [KYC status](/docs/sub-accounts/kyc/kyc-status) is recomputed.

<Info>
  Authenticate with your **parent main account's** `X-Auth-ID` and `X-Auth-Token` - the same credentials used everywhere else in the API.
</Info>

<Tip>
  Testing? Use the [mock endpoint](/docs/sub-accounts/kyc/test-mode) with magic inputs like `TESTSUCCESS0001` instead of a real PAN.
</Tip>

## Request body

| Field | Type | Required | Description |
| - | - | - | - |
| `pan` | string | Yes | The PAN. Must be exactly 10 characters (e.g. `ABCDE1234F`). |

## Response example

```json 200 OK theme={null}
{
  "verification_type": "pan",
  "status": "verified",
  "pan": "ABCDE1234F",
  "registered_name": "ACME PRIVATE LIMITED",
  "name_match": true,
  "kyc_calls_blocked": true
}
```

* `status` is `verified`, `failed`, or `pending` (some providers return asynchronously).
* `kyc_calls_blocked` is the sub-account's recomputed gate after this step - it may still be `true` if other required documents are outstanding.
* A `400` is returned when `pan` is not exactly 10 characters.


## OpenAPI

````yaml POST /api/v1/sub-accounts/{sub_auth_id}/kyc/verify-pan
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
  /api/v1/sub-accounts/{sub_auth_id}/kyc/verify-pan:
    post:
      tags:
        - Sub-Account KYC
      summary: Verify PAN
      description: |
        Runs a real PAN verification (Perfios) for the sub-account. `pan` must
        be exactly 10 characters. Persists a `kyc_verifications` row and
        recomputes the sub-account's aggregated `kyc_status`.
      operationId: verify-subaccount-pan
      parameters:
        - $ref: '#/components/parameters/SubAuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - pan
              properties:
                pan:
                  type: string
                  minLength: 10
                  maxLength: 10
                  example: ABCDE1234F
      responses:
        '200':
          description: Verification result
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/KycVerificationResult'
              example:
                verification_type: pan
                status: verified
                pan: ABCDE1234F
                registered_name: ACME PRIVATE LIMITED
                name_match: true
                kyc_calls_blocked: true
        '400':
          description: Invalid PAN format
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
    KycVerificationResult:
      type: object
      description: Outcome of a single KYC verification step.
      properties:
        verification_type:
          type: string
          enum:
            - pan
            - gst
            - cin
            - aadhaar
        status:
          type: string
          enum:
            - verified
            - failed
            - pending
        kyc_calls_blocked:
          type: boolean
          description: Recomputed sub-account call-blocking state after this verification.
        mock:
          type: boolean
          description: Present and `true` on responses from the test-mode endpoints.
      required:
        - verification_type
        - status
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