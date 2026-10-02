> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# CIN Confirm

> Confirm the CIN selected from the search results to complete company identity verification.

Confirms the CIN you selected from the [CIN Search](/docs/sub-accounts/kyc/cin-search) results. Pass the `company_name` and the chosen `selected_cin`.

<Info>
  Authenticate with your **parent main account's** `X-Auth-ID` and `X-Auth-Token` - the same credentials used everywhere else in the API.
</Info>

## Request body

| Field | Type | Required | Description |
| - | - | - | - |
| `company_name` | string | Yes | The company name (should match the chosen search result). |
| `selected_cin` | string | Yes | The exact `cin` chosen from the [CIN Search](/docs/sub-accounts/kyc/cin-search) results. |

## Response example

```json 200 OK theme={null}
{
  "verification_type": "cin",
  "status": "verified",
  "cin": "U72900KA2024PTC123456"
}
```

<Note>
  Pass the `selected_cin` **verbatim** from a search result - don't hand-type it. Confirming a CIN that wasn't returned by search will not verify. This step persists the `cin` verification and recomputes `kyc_calls_blocked`.
</Note>


## OpenAPI

````yaml POST /api/v1/sub-accounts/{sub_auth_id}/kyc/cin/confirm
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
  /api/v1/sub-accounts/{sub_auth_id}/kyc/cin/confirm:
    post:
      tags:
        - Sub-Account KYC
      summary: CIN confirm
      description: Confirm the CIN selected from the search results.
      operationId: confirm-subaccount-cin
      parameters:
        - $ref: '#/components/parameters/SubAuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - company_name
                - selected_cin
              properties:
                company_name:
                  type: string
                  example: ACME PRIVATE LIMITED
                selected_cin:
                  type: string
                  example: U72900KA2024PTC123456
      responses:
        '200':
          description: Verification result
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/KycVerificationResult'
              example:
                verification_type: cin
                status: verified
                cin: U72900KA2024PTC123456
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