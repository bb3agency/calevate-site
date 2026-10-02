> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Start conference recording

> Start recording a Vobiz conference via POST - capture all participants in MP3 or WAV format, set a callback URL, and meet compliance requirements globally.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/Record/
```

Start recording an active conference. The recording captures conference audio and continues until you stop it or the conference ends.

<Warning>
  **Legal notice** - Ensure you comply with local recording consent laws. Consider playing an announcement to participants before starting the recording.
</Warning>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID |
| `conference_name` | string | Yes | Name of the conference to record |

## Request parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `file_format` | string | No | Recording format. Values: `mp3`, `wav`. Default: `mp3` |
| `callback_url` | string | No | URL to receive the recording completion callback. |

## Example requests

<CodeGroup>
  ```bash Basic recording theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Record/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json"
  ```

  ```bash Recording with WAV format and callback theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Record/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "file_format": "wav",
      "callback_url": "https://yourapp.example/recording-complete"
    }'
  ```
</CodeGroup>

## Response

```json 200 OK theme={null}
{
  "message": "async api spawned",
  "api_id": "API_REQUEST_ID"
}
```

The response confirms that Vobiz queued the recording operation. It does not include a recording ID or download URL.

## Error responses

| Status | Meaning | How to handle |
| - | - | - |
| `401 Unauthorized` | Missing/incorrect auth headers or a lowercase path. | Use both auth headers and the PascalCase path. |
| `404 Not Found` | The conference does not exist (no participant has joined the room yet). | Conferences are created on join via the `<Conference>` XML element - start one before recording. URL-encode names with spaces. |

## Recording callback

<Warning>
  **Known limitation:** Delivery to `callback_url` is not currently guaranteed. Do not depend on this callback to obtain a recording ID or recording URL.
</Warning>

Use [Stop Conference Recording](/docs/conference/recording/stop-recording) to stop the active recording. Manage recording retrieval independently because the start response does not provide a file location.


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Conference/{conference_name}/Record/
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
  /api/v1/Account/{auth_id}/Conference/{conference_name}/Record/:
    post:
      tags:
        - Conference Recording
      summary: Start conference recording
      description: >-
        Queue recording for all audio in a conference room. The response does
        not include a recording ID or download URL.
      operationId: start-conference-recording
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: conference_name
          in: path
          required: true
          schema:
            type: string
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                file_format:
                  type: string
                  enum:
                    - mp3
                    - wav
                  default: mp3
                callback_url:
                  type: string
      responses:
        '200':
          description: Recording request queued
          content:
            application/json:
              example:
                message: async api spawned
                api_id: API_REQUEST_ID
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