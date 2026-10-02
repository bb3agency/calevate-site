> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Send digits on an active call

> Send DTMF keypad tones on any active Vobiz call to automate IVR navigation, enter access codes, and control phone systems programmatically at scale.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/DTMF/
```

This endpoint lets you send DTMF digits on an active call. DTMF (Dual-Tone Multi-Frequency) tones are the sounds generated when pressing keys on a phone keypad. Use this to automate interactions with IVR systems, enter access codes, or control phone systems programmatically.

<Note>
  The call must be in an active state for DTMF digits to be sent successfully. Invalid digits or calls that have ended will result in an error.
</Note>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz authentication ID |
| `call_uuid` | string | Yes | Unique identifier of the active call |

## Request parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `digits` | string | Yes | The DTMF digits to send. Valid characters: `0`–`9`, `*`, `#`. Insert `w` for a 0.5s pause and `W` for a 1s pause between tones (e.g. `1w2W3`). |
| `leg` | string | No | Which call leg receives the digits. Values: `aleg`, `bleg`, `both`. Default: `aleg` |

<Tip>
  `aleg` refers to the caller (A-leg); `bleg` refers to the callee (B-leg); `both` sends the tones to every leg. DTMF tones are sent in the order specified in the `digits` string. Use `w`/`W` pauses to wait for an IVR prompt before sending the next digit.
</Tip>

## Error responses

| Status | Meaning | How to handle |
| - | - | - |
| `400 Bad Request` | `digits` is missing or contains invalid characters. | Send only `0`–`9`, `*`, `#`, `w`, `W`. |
| `401 Unauthorized` | Missing/incorrect auth headers or a lowercase path. | Use both auth headers and the PascalCase path. |
| `404 Not Found` | The `call_uuid` is not an active call. | The call must be in-progress; confirm with [Retrieve a Live Call](/docs/call/retrieve-live-call). |

## Example request

<CodeGroup>
  ```json Request body theme={null}
  {
    "digits": "1234#",
    "leg": "aleg"
  }
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/DTMF/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "digits": "1234#",
      "leg": "aleg"
    }'
  ```
</CodeGroup>

## Response

```json 202 Accepted theme={null}
{
  "api_id": "uuid-here",
  "message": "digits sent"
}
```

| Field | Description |
| - | - |
| `api_id` | Unique identifier for this API request |
| `message` | Confirmation that digits were sent successfully |

<Tip>
  When automating IVR navigation, add appropriate delays between DTMF sends to allow the system time to process each input before the next prompt plays.
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Call/{call_uuid}/DTMF/
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}/DTMF/:
    post:
      tags:
        - DTMF
      summary: Send DTMF tones
      description: >-
        Send DTMF (keypad) tones on an active call. Use `w` for 0.5s pause, `W`
        for 1s pause.
      operationId: send-dtmf
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: call_uuid
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - digits
              properties:
                digits:
                  type: string
                  example: 1w2W3
                leg:
                  type: string
                  enum:
                    - aleg
                    - bleg
                    - both
                  default: aleg
            example:
              digits: '1234'
              leg: aleg
      responses:
        '200':
          description: DTMF sent
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