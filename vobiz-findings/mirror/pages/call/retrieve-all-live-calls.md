> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve all live calls

> List UUIDs of every active call on your Vobiz account in real time - power monitoring dashboards, concurrent capacity audits, and bulk operations.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/?status=live
```

Returns an array of call UUIDs for all calls currently in progress on your account. Use this for a quick overview of active calls without fetching full call details.

<Info>
  Use this endpoint to monitor concurrent call volume or to get call UUIDs for batch operations like transfer or hangup.
</Info>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID |

## Query parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `status` | string | Yes | Must be set to `live` to retrieve only active calls |

## Example request

```bash cURL theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/?status=live" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

## Response

```json 200 OK theme={null}
{
  "api_id": "c9527676-5839-11e1-86da-6ff39efcb949",
  "calls": [
    "eac94337-b1cd-499b-82d1-b39bca50dc31",
    "0a70a7fb-168e-4944-a846-4f3f4d2f96f1"
  ]
}
```

| Field | Description |
| - | - |
| `api_id` | Unique identifier for this API request |
| `calls` | Array of call UUIDs for all active calls |

## Common use cases

* Monitor concurrent call volume in real-time.
* Build live dashboards showing active call count.
* Implement call capacity alerts and monitoring.
* Get call UUIDs for batch operations (transfer, hangup).
* Audit active calls for compliance or troubleshooting.

<Tip>
  Once you have the call UUIDs, use [Retrieve a Live Call](/docs/call/retrieve-live-call) to get detailed information about each active call.
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Call
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
  /api/v1/Account/{auth_id}/Call:
    get:
      tags:
        - Live Calls
      summary: List live calls
      description: Retrieve all currently active (live) calls on the account.
      operationId: list-live-calls
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: status
          in: query
          required: true
          schema:
            type: string
            enum:
              - live
              - queued
            default: live
          example: live
      responses:
        '200':
          description: List of live call UUIDs
          content:
            application/json:
              example:
                api_id: c9527676-5839-11e1-86da-6ff39efcb949
                calls:
                  - eac94337-b1cd-499b-82d1-b39bca50dc31
                  - 0a70a7fb-168e-4944-a846-4f3f4d2f96f1
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                    description: Unique identifier for this API request
                  calls:
                    type: array
                    description: Array of call UUIDs for all active calls
                    items:
                      type: string
                required:
                  - api_id
                  - calls
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