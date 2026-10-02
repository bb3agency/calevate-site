> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve an Audio Stream

> Fetch full details for a specific Vobiz audio stream by stream ID - status, WebSocket URL, codec, track direction, bidirectional mode, and start/end timestamps.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/{stream_id}/
```

This endpoint returns a full [Stream object](/docs/audio-streams/stream-object) for a specific stream attached to a given call. Use it to check the current status, configuration, and timing of an ongoing or completed stream.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
</Info>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your account ID. |
| `call_uuid` | string | Yes | UUID of the call. |
| `stream_id` | string | Yes | Unique ID of the stream. |

## Response

### Success Response (200 OK)

```json Response - 200 OK theme={null}
{
  "stream_id": "728e273b-9c2c-4902-8509-2f88224cd3d5",
  "call_uuid": "c6ebf396-59c2-4f2a-8771-fbb5d981e301",
  "service_url": "wss://your-server.com/ws",
  "status_callback_url": "https://your-server.com/stream-status",
  "bidirectional": true,
  "audio_track": "both",
  "content_type": "audio/x-l16;rate=16000",
  "status": "in-progress",
  "start_time": "2026-04-24T09:25:00Z",
  "end_time": null
}
```

### Error Response (404 Not Found)

```json Response - 404 Not Found theme={null}
{
    "api_id": "correlation-id-uuid",
    "error": "Stream not found"
}
```

## Example

```bash cURL theme={null}
curl -X GET 'https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/{stream_id}/' \
  -H 'X-Auth-ID: {auth_id}' \
  -H 'X-Auth-Token: {auth_token}'
```


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/{stream_id}/
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/{stream_id}/:
    get:
      tags:
        - Audio Streams
      summary: Retrieve a stream
      description: Get details of a specific audio stream.
      operationId: get-stream
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: call_uuid
          in: path
          required: true
          schema:
            type: string
        - name: stream_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Stream details
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