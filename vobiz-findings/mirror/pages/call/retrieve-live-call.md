> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve a live call

> Fetch real-time state, direction, duration, and per-leg metadata for a single active Vobiz call by UUID using a GET request with status=live.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/?status=live
```

Retrieve detailed information about an in-progress call. Unlike the standard CDR endpoint which returns finalized records, this endpoint provides real-time status for active calls including current state, call flow position, and live duration metrics.

<Note>
  This endpoint only returns data for calls currently in progress. For completed calls, use the standard call CDR endpoint instead.
</Note>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID |
| `call_uuid` | string | Yes | Unique identifier of the live call |

## Query parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `status` | string | Yes | Must be `live` to retrieve real-time call information |

<Warning>
  The `status=live` query parameter is required. Without it, the endpoint returns the finalized CDR (if the call ended) or a 404 error.
</Warning>

## Example request

```bash cURL theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/?status=live" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

## Response

```json 200 OK theme={null}
{
  "api_id": "c9cab827-d7e6-4ab8-b521-f29e593a1c26",
  "call_status": "in-progress",
  "call_uuid": "2ded13fe-4f9b-4958-9bfb-093ea2f29f91",
  "caller_name": "",
  "direction": "outbound",
  "from": "919262171438",
  "request_uuid": "2ded13fe-4f9b-4958-9bfb-093ea2f29f91",
  "session_start": "2026-06-11 16:03:28.586839",
  "stir_attestation": "Not Applicable",
  "stir_verification": "Not Applicable",
  "to": "919148227303"
}
```

### Response fields

| Field | Description |
| - | - |
| `api_id` | Unique identifier for this API request |
| `call_status` | Current state of the call (e.g. `in-progress`) |
| `call_uuid` | Unique identifier of the live call |
| `caller_name` | Caller ID name, if available (empty string otherwise) |
| `direction` | Call direction: `inbound` or `outbound` |
| `from` | Originating number |
| `request_uuid` | Identifier of the request that initiated the call |
| `session_start` | Timestamp when the call session started |
| `stir_attestation` | STIR/SHAKEN attestation level, or `Not Applicable` |
| `stir_verification` | STIR/SHAKEN verification result, or `Not Applicable` |
| `to` | Destination number |

<Tip>
  Poll this endpoint periodically to track a call's status while it is in progress.
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Call/{call_uuid}
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}:
    get:
      tags:
        - Live Calls
      summary: Retrieve a live call
      description: Retrieve details of a specific live or queued call.
      operationId: get-live-call
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
            default: live
      responses:
        '200':
          description: Live call details
          content:
            application/json:
              example:
                api_id: c9cab827-d7e6-4ab8-b521-f29e593a1c26
                call_status: in-progress
                call_uuid: 2ded13fe-4f9b-4958-9bfb-093ea2f29f91
                caller_name: ''
                direction: outbound
                from: '919262171438'
                request_uuid: 2ded13fe-4f9b-4958-9bfb-093ea2f29f91
                session_start: '2026-06-11 16:03:28.586839'
                stir_attestation: Not Applicable
                stir_verification: Not Applicable
                to: '919148227303'
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                    description: Unique identifier for this API request
                  call_status:
                    type: string
                    description: Current state of the call (e.g. in-progress)
                  call_uuid:
                    type: string
                  caller_name:
                    type: string
                  direction:
                    type: string
                  from:
                    type: string
                  request_uuid:
                    type: string
                  session_start:
                    type: string
                  stir_attestation:
                    type: string
                  stir_verification:
                    type: string
                  to:
                    type: string
                required:
                  - api_id
                  - call_status
                  - call_uuid
                  - caller_name
                  - direction
                  - from
                  - request_uuid
                  - session_start
                  - stir_attestation
                  - stir_verification
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