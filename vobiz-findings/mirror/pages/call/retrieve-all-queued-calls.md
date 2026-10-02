> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve all queued calls

> List UUIDs for all pending outbound calls on your Vobiz account waiting to connect - returns up to 20 queued calls per request for full queue visibility.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/?status=queued
```

Returns an array of call UUIDs for all calls currently in the queued state. Maximum 20 results per request.

<Info>
  Calls are in the "queued" state when they have been initiated but are waiting to be connected - either waiting for the destination to ring or for resources to become available.
</Info>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID |

## Query parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `status` | string | Yes | Must be set to `queued` to retrieve queued calls |

<Note>
  This endpoint returns a maximum of 20 call UUIDs per request. Poll periodically if you have more than 20 queued calls.
</Note>

## Example request

```bash cURL theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/?status=queued" \
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
| `calls` | Array of call UUIDs for all queued calls (max 20) |

## Common use cases

* Monitor queue depth and detect call backlogs.
* Identify calls stuck in queue for troubleshooting.
* Build queue management dashboards.
* Cancel all queued calls in bulk during maintenance.

<Tip>
  Use the returned call UUIDs with [Retrieve a Queued Call](/docs/call/retrieve-queued-call) to get details on each one, or use the Hang Up Call endpoint to cancel them.
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Call/
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
  /api/v1/Account/{auth_id}/Call/:
    get:
      tags:
        - Live Calls
      summary: List queued calls
      description: Retrieve all queued (pending, not yet connected) calls on the account.
      operationId: list-queued-calls
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
            default: queued
          example: queued
      responses:
        '200':
          description: List of queued call UUIDs
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
                    description: Array of call UUIDs for all queued calls (max 20)
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