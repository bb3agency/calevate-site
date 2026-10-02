> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Start an Audio Stream

> Fork live call audio over a WebSocket connection to your AI pipeline in near real time - configure codec, track direction, and bidirectional mode per stream.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/
```

This endpoint starts a new audio stream on a call that is currently in progress. Vobiz opens a WebSocket connection to the URL you provide and begins forwarding audio frames in near real time. You can start multiple concurrent streams on the same call - each one returns its own `stream_id`.

<Tip>
  **REST `POST .../Stream/` vs the `<Stream>` XML verb**

  * Use **REST** to attach a stream to a call that is *already live* - for example, to start transcription after a transfer, or fork a second pipeline mid-call. It returns a `stream_id` you can later [list](/docs/audio-streams/list-audio-streams), [retrieve](/docs/audio-streams/retrieve-audio-stream), or [stop](/docs/audio-streams/stop-audio-stream).
  * Use the [`<Stream>` XML verb](/docs/xml/stream) when your answer handler is setting up the call from the start. The XML verb is the path for full-duplex AI voice agents.

  Both share the same WebSocket event protocol once connected (`start`, `media`, `playAudio`, `checkpoint`, `clearAudio`, `stop`). See [Stream Events Overview](/docs/xml/stream/stream-events).
</Tip>

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Important:** The target WebSocket URL must be reachable from Vobiz and must accept connections over `wss://` in production.
</Info>

<Warning>
  **On this REST route, `bidirectional` must be the string `"true"`.** A JSON boolean
  `true` is accepted and silently produces a **one-way** stream - no error, no warning,
  and your `playAudio` events are discarded. The [`<Stream>`](/docs/xml/stream) XML verb
  accepts either form; this route does not.

  ```json theme={null}
  "bidirectional": "true"     // correct
  "bidirectional": true       // accepted, but streams one way only
  ```
</Warning>

<Note>
  **Attaching to a leg that is in a conference.** This route is the way to stream from
  a call that is also in a [`<Conference>`](/docs/xml/conference) - XML verbs execute in
  sequence and a bidirectional `<Stream>` holds its leg, so a `<Conference>` placed
  after it is never reached. The REST route attaches the stream as a media bug on the
  channel, outside XML sequencing.

  Wait for the `ConferenceEnter` callback and allow roughly **two seconds** before
  attaching. The leg has to settle in the room first, or the stream receives no audio.
</Note>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz authentication ID. |
| `call_uuid` | string | Yes | UUID of the active call to attach the stream to. |

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `service_url` | string | Yes | WebSocket URL (wss\:// or ws\://) to which Vobiz forwards the call audio. Must be reachable from the public internet; use `wss://` in production. |
| `audio_track` | string | No | Track of the call to fork to the WebSocket. One of "inbound", "outbound", "both". Default: "both". When `bidirectional` is true, set `audio_track` to "inbound" - "both"/"outbound" are not supported with bidirectional. |
| `bidirectional` | string | No | If `"true"`, the WebSocket may send audio back into the call using playAudio events. **Send this as the string `"true"`, not a JSON boolean** - see the warning below. Default: `"false"`. |
| `content_type` | string | No | Format for inbound audio sent from Vobiz to your WebSocket. Options: "audio/x-l16;rate=8000", "audio/x-l16;rate=16000", or "audio/x-mulaw;rate=8000". Default: "audio/x-l16;rate=8000". Vobiz reports the selected format in `start.mediaFormat`. |
| `stream_timeout` | integer | No | Maximum stream duration in seconds. Vobiz automatically stops the stream when this limit is reached. Default: 86400 (24 hours). |
| `status_callback_url` | string | No | URL invoked when the stream status changes (connected, stopped, timeout, failed). |
| `status_callback_method` | string | No | HTTP method for status\_callback\_url. One of "GET", "POST". Default: "POST". |
| `extra_headers` | string | No | Comma-separated list of additional HTTP headers (header:value) sent when opening the WebSocket connection. Useful for auth tokens. |

<Tip>
  Choose the inbound `content_type` that your speech or media processor accepts. L16 carries raw 16-bit PCM; μ-law uses less bandwidth at 8 kHz.
</Tip>

## Status Callback Events

When the stream changes state, Vobiz sends a form-encoded HTTP request to your `status_callback_url`. The `Event` field is one of:

| `Event` value | Meaning |
| - | - |
| `StartStream` | The WebSocket connected and audio is being forwarded. Carries `ServiceURL`. |
| `PlayedStream` | Audio queued before a `checkpoint` finished playing. Carries `Name`. Only fires if playback completed. |
| `StopStream` | Streaming ended. **Reliably observed only for server-initiated stops** - not for caller hangup or mid-call kill. |

These HTTP callbacks are a separate channel from the WebSocket events. For the exact payload fields and examples, see [Status callback events](/docs/xml/stream#status-callback-events).

<Warning>
  The authoritative "call is over" signal across *all* termination paths (caller hangup, carrier drop, timeout, server stop) is the `Event=Hangup` POST to your call's `hangup_url`, not `StopStream`. See [Detecting end of stream](/docs/xml/stream/stream-events#detecting-end-of-stream).
</Warning>

## Bidirectional streaming

When `bidirectional=true`, your WebSocket server can send outbound playback audio to the call. This format is independent of the inbound REST `content_type`.

```json Send audio from WebSocket to call theme={null}
{
  "event": "playAudio",
  "streamId": "STREAM_ID",
  "media": {
    "contentType": "audio/x-l16",
    "sampleRate": 24000,
    "payload": "<base64-encoded-audio>"
  }
}
```

| Field | Values |
| - | - |
| `contentType` | audio/x-l16, audio/x-mulaw |
| `sampleRate` | L16: 8000, 16000, or 24000. μ-law: 8000. The bytes must match the declared rate. |
| `payload` | Base64-encoded raw mono audio without a WAV or other container header. |

For the full bidirectional protocol - `checkpoint`, `clearAudio` (barge-in), `stop`, and the inbound `media`/`start` events - see [Stream Events Overview](/docs/xml/stream/stream-events) and [Play Audio Event](/docs/xml/stream/play-audio).

<Warning>
  Do not set REST `content_type` to L16/24 kHz to play a 24 kHz TTS response. `content_type` configures inbound Vobiz-to-application audio. Set `sampleRate: 24000` on a `playAudio` event that contains genuine L16/24 kHz audio.
</Warning>

## Response

Returns a confirmation along with the generated `stream_id`.

```json Response - 202 Accepted theme={null}
{
  "message": "audio streaming started",
  "stream_id": "728e273b-9c2c-4902-8509-2f88224cd3d5"
}
```

## Example Request

```bash cURL theme={null}
curl -X POST 'https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/' \
  -H 'X-Auth-ID: {auth_id}' \
  -H 'X-Auth-Token: {auth_token}' \
  -H 'Content-Type: application/json' \
  -d '{
    "service_url": "wss://your-server.com/ws",
    "bidirectional": true,
    "audio_track": "inbound",
    "content_type": "audio/x-l16;rate=16000",
    "status_callback_url": "https://your-server.com/stream-status"
  }'
```


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/:
    post:
      tags:
        - Audio Streams
      summary: Start audio stream
      description: Start streaming raw audio from a live call to a WebSocket URL.
      operationId: start-stream
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
                - service_url
              properties:
                service_url:
                  type: string
                  example: wss://your-server.com/ws
                bidirectional:
                  type: boolean
                  default: false
                audio_track:
                  type: string
                  enum:
                    - inbound
                    - outbound
                    - both
                  default: both
                audio_format:
                  type: string
                  enum:
                    - pcm
                    - mulaw
                  default: mulaw
            example:
              service_url: wss://your-server.com/ws
              bidirectional: true
              audio_track: both
      responses:
        '200':
          description: Stream started
          content:
            application/json:
              example:
                stream_id: str_XXXXXXXXXX
                message: Stream started
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