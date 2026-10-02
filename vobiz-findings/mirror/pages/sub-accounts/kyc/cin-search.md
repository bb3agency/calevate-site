> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# CIN Search

> Look up a company's CIN by name. Returns candidate matches to confirm in the next step.

Performs a name-based CIN (Corporate Identity Number) lookup. Returns a list of candidate company matches; select one and pass it to [CIN Confirm](/docs/sub-accounts/kyc/cin-confirm).

<Info>
  Authenticate with your **parent main account's** `X-Auth-ID` and `X-Auth-Token` - the same credentials used everywhere else in the API.
</Info>

## Request body

| Field | Type | Required | Description |
| - | - | - | - |
| `company_name` | string | Yes | The company name to look up. |

## Response example

```json 200 OK theme={null}
{
  "matches": [
    {
      "cin": "U72900KA2024PTC123456",
      "company_name": "ACME PRIVATE LIMITED",
      "status": "Active"
    }
  ]
}
```

Search is name-based and may return multiple candidates (or none). Pick the exact match and pass both its `cin` (as `selected_cin`) and the `company_name` to [CIN Confirm](/docs/sub-accounts/kyc/cin-confirm) - confirm is what actually persists the verification.


## OpenAPI

````yaml POST /api/v1/sub-accounts/{sub_auth_id}/kyc/cin/search
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
  /api/v1/sub-accounts/{sub_auth_id}/kyc/cin/search:
    post:
      tags:
        - Sub-Account KYC
      summary: CIN search
      description: |
        Name-based CIN lookup. Returns candidate company matches; pick one and
        pass it to [CIN confirm](#operation/confirm-subaccount-cin).
      operationId: search-subaccount-cin
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
              properties:
                company_name:
                  type: string
                  example: ACME PRIVATE LIMITED
      responses:
        '200':
          description: Candidate matches
          content:
            application/json:
              example:
                matches:
                  - cin: U72900KA2024PTC123456
                    company_name: ACME PRIVATE LIMITED
                    status: Active
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