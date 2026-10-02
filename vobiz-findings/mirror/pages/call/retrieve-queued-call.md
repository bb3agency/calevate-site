> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve a queued call

> Fetch details of a single pending Vobiz call by UUID before it connects - inspect destination, timestamps, and queue state via GET with status=queued.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/?status=queued
```

Retrieve information about a call that has been initiated but is not yet connected. Queued calls are waiting for the destination to answer or for resources to become available.

<Info>
  A call is in the "queued" state when it has been initiated via the API but has not been answered yet, including calls waiting for the destination to ring or answer.
</Info>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID |
| `call_uuid` | string | Yes | Unique identifier of the queued call |

## Query parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `status` | string | Yes | Must be `queued` to retrieve queued call details |

<Warning>
  If the call is no longer queued (connected or ended), this endpoint returns a 404 error. Use the standard CDR endpoint for completed calls.
</Warning>

## Example request

```bash cURL theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/?status=queued" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

## Response

```json 200 OK theme={null}
{
  "direction": "outbound",
  "from": "15856338537",
  "call_status": "queued",
  "api_id": "45223222-74f8-11e1-8ea7-12313806be9a",
  "to": "14154290945",
  "caller_name": "+15856338537",
  "call_uuid": "6653422-91b6-4716-9fad-9463daaeeec2",
  "request_uuid": "6653422-91b6-4716-9fad-9463daaeeec2"
}
```

| Field | Description |
| - | - |
| `api_id` | Unique identifier for this API request |
| `call_status` | Always `queued` for this endpoint |
| `call_uuid` | Unique identifier for the call |
| `request_uuid` | Request identifier (same as `call_uuid`) |
| `direction` | Call direction: `outbound` or `inbound` |
| `from` | Source phone number |
| `to` | Destination phone number |
| `caller_name` | Caller ID name |

<Tip>
  Combine this endpoint with [Retrieve All Queued Calls](/docs/call/retrieve-all-queued-calls) to monitor all pending calls on your account at once.
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Call/{call_uuid}/
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}/:
    get:
      tags:
        - Live Calls
      summary: Retrieve a queued call
      description: Retrieve details of a specific queued (pending) call.
      operationId: get-queued-call
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: call_uuid
          in: path
          required: true
          schema:
            type: string
            example: cdr_XXXXXXXXXX
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
          description: Queued call details
          content:
            application/json:
              example:
                api_id: 45223222-74f8-11e1-8ea7-12313806be9a
                call_status: queued
                call_uuid: 6653422-91b6-4716-9fad-9463daaeeec2
                request_uuid: 6653422-91b6-4716-9fad-9463daaeeec2
                caller_name: '+15856338537'
                direction: outbound
                from: '15856338537'
                to: '14154290945'
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                    description: Unique identifier for this API request
                  call_status:
                    type: string
                    description: Always queued for this endpoint
                  call_uuid:
                    type: string
                  request_uuid:
                    type: string
                  caller_name:
                    type: string
                  direction:
                    type: string
                  from:
                    type: string
                  to:
                    type: string
                required:
                  - api_id
                  - call_status
                  - call_uuid
                  - request_uuid
                  - caller_name
                  - direction
                  - from
                  - to
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