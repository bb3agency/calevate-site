> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Make an Outbound Call

> Initiate an international outbound call to any PSTN number or SIP endpoint across 130+ countries, with bulk dialing, AMD, and recording in one API request.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/
```

Initiate an outbound call to a PSTN number or a SIP endpoint, and make simultaneous bulk calls.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Tip>
  Use `<` to separate multiple destinations (max 1000). Example: `14157654321<14153464321<sip:john1234@api.vobiz.ai`
</Tip>

## Required Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `from` | string | Yes | The caller ID phone number in E.164 format (e.g., 14157654321). |
| `to` | string | Yes | Destination number(s) or SIP URI(s). Use `<` to separate multiple destinations (max 1000). Examples: 14157654321, sip:[john1234@api.vobiz.ai](mailto:john1234@api.vobiz.ai) |
| `answer_url` | string | Yes | URL called when the call is answered. Must return valid XML. |

## Callback Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `answer_method` | string | No | HTTP verb for answer\_url. Default is POST. |
| `ring_url` | string | No | Optional URL notified when the call starts ringing. |
| `ring_method` | string | No | HTTP verb for ring\_url. Default is POST. |
| `hangup_url` | string | No | Optional URL notified when the call is hung up. |
| `hangup_method` | string | No | HTTP verb for hangup\_url. Default is POST. |
| `fallback_url` | string | No | Invoked if answer\_url fails after 3 retries or 60s timeout. |
| `fallback_method` | string | No | HTTP verb for fallback\_url. Default is POST. |

## Machine Detection Parameters

<Note>
  For detailed machine detection documentation, see the [Machine Detection page](/docs/call/machine-detection).
</Note>

| Field | Type | Required | Description |
| - | - | - | - |
| `machine_detection` | string | No | Detect machine on answer. Values: true, hangup. |
| `machine_detection_time` | integer | No | Time in ms to detect machine. Default: 5000. Allowed: 2000–10000. |
| `machine_detection_url` | string | No | Callback URL for asynchronous machine detection. |
| `machine_detection_method` | string | No | HTTP verb for machine\_detection\_url. Default: POST. |
| `machine_detection_maximum_speech_length` | integer | No | Max speech duration in ms. Default: 5000. Allowed: 1000–6000. |
| `machine_detection_initial_silence` | integer | No | Max silence after answer (ms). Default: 4500. Allowed: 2000–10000. |
| `machine_detection_maximum_words` | integer | No | Max number of sentences. Default: 3. Allowed: 2–10. |
| `machine_detection_initial_greeting` | integer | No | Max greeting length (ms). Default: 1500. Allowed: 1000–5000. |

## Advanced Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `caller_name` | string | No | Sets caller name (up to 50 characters). Defaults to caller's name. |
| `send_digits` | string | No | DTMF digits to send after the call connects. Use `w` (0.5s wait) or `W` (1s wait). Example: `1w2W3` or `123@1000` (1000ms tone). |
| `send_on_preanswer` | boolean | No | If true, sends send\_digits during pre-answer. Default: false. |
| `time_limit` | integer | No | Max duration of call in seconds (after answered). Default: 14400 (4 hours). Calls ≥ 86400s are disconnected at 24h. |
| `hangup_on_ring` | integer | No | Max duration (in seconds) from start of ringing to hangup. |

## Request Example

<CodeGroup>
  ```json Request Body theme={null}
  {
    "from": "14155551234",
    "to": "14155555678",
    "answer_url": "https://example.com/answer",
    "answer_method": "POST",
    "ring_timeout": "30",
    "time_limit": "3600",
    "hangup_url": "https://example.com/hangup",
    "hangup_method": "POST",
    "caller_name": "John Doe",
    "machine_detection": "false"
  }
  ```

  ```bash cURL Example theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "from": "14155551234",
      "to": "14155555678",
      "answer_url": "https://example.com/answer",
      "answer_method": "POST"
    }'
  ```
</CodeGroup>

## Response Example

```json Success Response (200 OK) theme={null}
{
  "api_id": "5a9fcfee-3d4c-11ef-bef9-0242ac110005",
  "message": "Call fired",
  "request_uuid": "5a9fd4a0-3d4c-11ef-bef9-0242ac110005"
}
```

| Field | Type | Description |
| - | - | - |
| `api_id` | string | Unique identifier for this API request. |
| `message` | string | Confirmation message. `Call fired` on success. |
| `request_uuid` | string | Unique identifier for the call. Equivalent to `call_uuid`. For bulk dials, each destination is delivered its own UUID via the callback URLs. |

<Note>
  The `call_uuid` (also referred to as `request_uuid`) is the unique identifier for the call. Both are equivalent and can be used interchangeably. A `200` response means the call was **accepted and queued**, not that the callee answered - watch the `ring_url` and `answer_url` callbacks for the live state.
</Note>

## Error responses

| Status | Meaning | How to handle |
| - | - | - |
| `400 Bad Request` | A required field (`from`, `to`, `answer_url`, `answer_method`) is missing or malformed, or `to` exceeds 1000 destinations. | Validate the body before sending. Confirm `to` is E.164 or a valid SIP URI. |
| `401 Unauthorized` | Missing or incorrect `X-Auth-ID` / `X-Auth-Token`, or a lowercase path (`/account/.../call/`). | Send both auth headers and use the PascalCase path `/Account/{auth_id}/Call/`. |
| `402 Payment Required` | Account balance is too low to place the call. | Top up the balance, then retry. |
| `404 Not Found` | The `auth_id` does not exist or the path is wrong. | Verify the `auth_id` and the trailing slash on `/Call/`. |
| `429 Too Many Requests` | You exceeded your calls-per-second (CPS) or concurrent-call limit. | Back off and retry with jitter; spread bulk dials over time. |

<Warning>
  Use `<` (not a comma) to separate bulk destinations. A comma is treated as part of a single destination and the call fails to route.
</Warning>

## Parameters Sent to Callback URLs

For every voice call you make and receive, Vobiz sends a status update to your configured callback URLs. Read and store this information for analysis, and use the values to change the flow of ongoing calls.

### Parameters Sent to ring\_url

| Field | Type | Description |
| - | - | - |
| `From` | string | Caller ID number used to initiate the call. |
| `To` | string | The destination being called. |
| `RequestUUID` | string | Unique identifier for the call request. |
| `ALegRequestUUID` | string | Identifier for the first leg of the call (multi-leg calls). |
| `CallUUID` | string | Unique identifier for the call. |
| `Direction` | string | Direction of the call. Always `"outbound"`. |
| `Event` | string | Event that triggered this notification. Always `"Ring"`. |
| `CallStatus` | string | Status of the call. Always `"ringing"`. |
| `SessionStart` | string | Timestamp when early media started. Format: YYYY-MM-DD HH:mm:ss.sssss UTC. |
| `STIRAttestation` | string | Attestation details assigned to the call by Vobiz. |

### Parameters Sent to answer\_url and fallback\_url

| Field | Type | Description |
| - | - | - |
| `From` | string | Caller ID number used to initiate the call. |
| `To` | string | The destination being called. |
| `CallerName` | string | Caller display name, present when the call originates from a SIP endpoint. |
| `RequestUUID` | string | Unique identifier for the call request. |
| `ALegRequestUUID` | string | Identifier for the first leg of the call (multi-leg calls). |
| `CallUUID` | string | Unique identifier for the call. |
| `Direction` | string | Direction of the call. Always `"outbound"`. |
| `ALegUUID` | string | Unique identifier for the A leg of the call. |
| `Event` | string | Event that triggered this notification. Always `"StartApp"`. |
| `STIRVerification` | string | Attestation details. Possible values: Verified, Not Verified, Not Applicable. |
| `CallStatus` | string | Status of the call. Always `"in-progress"`. |
| `SessionStart` | string | Timestamp when early media started. Format: YYYY-MM-DD HH:mm:ss.sssss UTC. |
| `STIRAttestation` | string | Attestation details assigned to the call by Vobiz. |

### Parameters Sent to hangup\_url

| Field | Type | Description |
| - | - | - |
| `From` | string | Caller ID number used to initiate the call. |
| `To` | string | The destination being called. |
| `RequestUUID` | string | Unique identifier for the call request. |
| `ALegRequestUUID` | string | Identifier for the first leg of the call (multi-leg calls). |
| `CallUUID` | string | Unique identifier for the call. |
| `Direction` | string | Direction of the call. Always `"outbound"`. |
| `ALegUUID` | string | Unique identifier for the A leg of the call. |
| `Event` | string | Event that triggered this notification. Always `"Hangup"`. |
| `stir_verification` | string | Attestation details. Possible values: Verified, Not Verified, Not Applicable. |
| `CallStatus` | string | Status of the call. Always `"completed"`. |
| `StartTime` | string | Timestamp when the call was initiated. Format: yyyy-MM-dd HH:mm:ss (local time). |
| `AnswerTime` | string | Timestamp when the call was answered. Format: yyyy-MM-dd HH:mm:ss (local time). |
| `SessionStart` | string | Timestamp when early media started. Format: YYYY-MM-DD HH:mm:ss.sssss UTC. |
| `EndTime` | string | Timestamp when the call ended. Format: yyyy-MM-dd HH:mm:ss (local time). |
| `STIRAttestation` | string | Attestation details assigned to the call by Vobiz. |


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Call/
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
    post:
      tags:
        - Calls
      summary: Make an outbound call
      description: |
        Initiate an outbound call to a PSTN number or SIP endpoint.
        Use `<` to separate multiple destinations (max 1000).
      operationId: make-call
      parameters:
        - $ref: '#/components/parameters/AuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                from:
                  type: string
                to:
                  type: string
                  description: >
                    Destination PSTN number or SIP endpoint. Separate multiple
                    destinations with

                    the `<` character to fan out a single request to up to 1000
                    destinations,

                    for example `+919876543210<+919876543211`.
                  example: '+919876543210'
                answer_url:
                  type: string
                answer_method:
                  type: string
              required:
                - from
                - to
                - answer_url
                - answer_method
            examples:
              single:
                summary: Call one destination
                value:
                  from: '14155551234'
                  to: '+919876543210'
                  answer_url: https://example.com/answer
                  answer_method: POST
                  time_limit: 3600
              bulk:
                summary: Fan out to multiple destinations with `<`
                value:
                  from: '14155551234'
                  to: +919876543210<+919876543211<+919876543212
                  answer_url: https://example.com/answer
                  answer_method: POST
      responses:
        '200':
          description: Call initiated
          content:
            application/json:
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                  message:
                    type: string
                  request_uuid:
                    type: string
                required:
                  - api_id
                  - message
                  - request_uuid
              example:
                api_id: 5a9fcfee-3d4c-11ef-bef9-0242ac110005
                request_uuid: 5a9fd4a0-3d4c-11ef-bef9-0242ac110005
                message: Call fired
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