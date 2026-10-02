> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Start recording a call

> Begin recording an active Vobiz call in MP3 or WAV format with optional auto-transcription, multiple concurrent recordings, and callback on completion.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Record/
```

Start recording a call that is currently in progress. You can create multiple recordings on the same call, customize the audio format, enable automated transcription, and receive a callback when recording completes.

<Note>
  Transcription is available only in English, for calls between 500ms and 4 hours in duration, and under 2GB in file size.
</Note>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz authentication ID |
| `call_uuid` | string | Yes | Unique identifier of the call to record |

## Request parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `time_limit` | integer | No | Maximum recording duration in seconds. Default: `60`. Increase for longer calls (e.g., `300`, `900`). |
| `file_format` | string | No | Audio format. Values: `mp3`, `wav`. Default: `mp3` |
| `transcription_type` | string | No | Set to `auto` to enable automated transcription. Turnaround under 5 minutes. |
| `transcription_url` | string | No | URL to receive transcription data via HTTP POST |
| `callback_url` | string | No | URL invoked when recording ends with recording details |
| `callback_method` | string | No | HTTP method for `callback_url`. Values: `GET`, `POST`. Default: `POST` |
| `record_channel_type` | string | No | Recording channel type. Values: `mono`, `stereo`. Default: `mono` |

<Tip>
  Use MP3 format for smaller file sizes. Stereo recording separates caller and callee into left/right channels for easier analysis.
</Tip>

## Example requests

<CodeGroup>
  ```json Basic recording theme={null}
  {
    "time_limit": 120,
    "file_format": "mp3"
  }
  ```

  ```json Recording with callback theme={null}
  {
    "time_limit": 60,
    "file_format": "mp3",
    "callback_url": "https://example.com/recording_callback",
    "callback_method": "POST"
  }
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Record/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "time_limit": 60,
      "file_format": "mp3"
    }'
  ```
</CodeGroup>

## Response

```json 200 OK theme={null}
{
  "api_id": "uuid-here",
  "message": "recording started",
  "recording_id": "recording-uuid-here",
  "url": "https://recordings.example.com/recording-uuid.mp3"
}
```

| Field | Description |
| - | - |
| `api_id` | Unique identifier for this API request |
| `message` | Confirmation that recording has started |
| `recording_id` | Unique identifier for this recording. Save it to stop or correlate this specific recording later. |
| `url` | URL where the recording file will be available once finalized. |

<Note>
  A single call can have multiple recordings running at once. Each `POST` starts a new one with its own `recording_id` and `url`. Recording stops automatically when `time_limit` is reached, when you call [Stop Recording](/docs/call/record-calls/stop-recording), or when the call ends.
</Note>

## Error responses

| Status | Meaning | How to handle |
| - | - | - |
| `401 Unauthorized` | Missing/incorrect auth headers or a lowercase path. | Use both auth headers and the PascalCase path. |
| `404 Not Found` | The `call_uuid` is not an active call. | The call must be in-progress; confirm with [Retrieve a Live Call](/docs/call/retrieve-live-call). |

## Callback URL parameters

When recording ends, these fields are sent to your `callback_url` via HTTP POST:

| Field | Type | Description |
| - | - | - |
| `api_id` | string | The API ID returned by the Record API |
| `record_url` | string | URL where the recorded file can be accessed |
| `call_uuid` | string | The call UUID of the recorded call |
| `recording_id` | string | Unique identifier for this recording |
| `recording_duration` | integer | Duration of the recording in seconds |
| `recording_duration_ms` | integer | Duration of the recording in milliseconds |
| `recording_start_ms` | integer | Start time since epoch in milliseconds |
| `recording_end_ms` | integer | End time since epoch in milliseconds |

## Transcription callback parameters

When transcription completes, these fields are sent to your `transcription_url`:

| Field | Type | Description |
| - | - | - |
| `transcription_charge` | number | Credit deducted for the transcription |
| `transcription` | string | The transcribed text |
| `duration` | integer | Recording duration in seconds |
| `call_uuid` | string | The call UUID that was transcribed |
| `transcription_rate` | number | Rate of transcription per minute |
| `recording_id` | string | Recording ID of the transcribed recording |
| `error` | string | Error message if transcription failed; empty on success |

<Note>
  If you see "Recording file size too large for transcription", switch to `mp3` format - MP3 files are significantly smaller than WAV.
</Note>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Call/{call_uuid}/Record/
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}/Record/:
    post:
      tags:
        - Record Calls
      summary: Start recording a call
      description: >-
        Begin recording an active call. Set format, enable transcription, and
        configure a callback URL.
      operationId: start-recording
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: call_uuid
          in: path
          required: true
          schema:
            type: string
            example: cdr_XXXXXXXXXX
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                time_limit:
                  type: integer
                  default: 60
                file_format:
                  type: string
                  enum:
                    - mp3
                    - wav
                  default: mp3
                transcription_type:
                  type: string
                  description: Set to `auto` to enable transcription
                callback_url:
                  type: string
                record_channel_type:
                  type: string
                  enum:
                    - mono
                    - stereo
                  default: mono
            example:
              time_limit: 120
              file_format: mp3
      responses:
        '200':
          description: Recording started
          content:
            application/json:
              example:
                recording_id: rec_XXXXXXXXXX
                message: Recording started
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