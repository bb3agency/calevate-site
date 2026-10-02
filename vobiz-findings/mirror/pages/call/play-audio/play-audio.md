> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Play audio on a call

> Stream MP3 or WAV audio files to participants on an active Vobiz call - play single or multiple files in sequence, loop hold music, and target specific legs.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Play/
```

Play audio files during an active call. You can play a single file or multiple files in sequence, control which participants hear the audio, and configure looping and mixing behavior. Vobiz supports `.mp3` and `.wav` audio files.

<Note>
  Audio files must be accessible via public HTTP or HTTPS URLs. Ensure your audio hosting service has proper CORS headers configured if needed.
</Note>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz authentication ID |
| `call_uuid` | string | Yes | Unique identifier of the active call |

## Request parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `urls` | string | Yes | Public `.mp3`/`.wav` audio URL to play. To play multiple files in sequence, pass a comma-separated list of URLs in this single string. |
| `length` | integer | No | Maximum playback duration in seconds. |
| `legs` | string | No | Which leg(s) to play on. Values: `aleg` (caller), `bleg` (callee), `both`. Default: `aleg` |
| `loop` | boolean | No | Whether to loop the audio. Default: `false` |
| `mix` | boolean | No | Whether to mix audio with the live call audio. Default: `true` |

<Tip>
  * Pass comma-separated URLs to play files in sequence.
  * Set `loop=true` for hold music.
  * Set `mix=false` for important announcements so participants hear them clearly.
  * Use `legs=both` to play audio to all participants.
</Tip>

## Error responses

| Status | Meaning | How to handle |
| - | - | - |
| `400 Bad Request` | `urls` is missing/empty, or a URL is not a reachable `.mp3`/`.wav` file. | Host audio publicly over HTTP(S) and pass at least one valid URL. |
| `401 Unauthorized` | Missing/incorrect auth headers or a lowercase path. | Use both auth headers and the PascalCase path. |
| `404 Not Found` | The `call_uuid` is not an active call. | The call must be in-progress; confirm with [Retrieve a Live Call](/docs/call/retrieve-live-call). |

## Example request

<CodeGroup>
  ```json Single file theme={null}
  {
    "urls": "https://example.com/audio/greeting.mp3",
    "length": 10,
    "legs": "both",
    "loop": false,
    "mix": true
  }
  ```

  ```json Multiple files in sequence theme={null}
  {
    "urls": "https://example.com/intro.mp3,https://example.com/menu.mp3",
    "legs": "aleg"
  }
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Play/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "urls": "https://example.com/audio/greeting.mp3",
      "legs": "both"
    }'
  ```
</CodeGroup>

## Response

```json 202 Accepted theme={null}
{
  "api_id": "uuid-here",
  "message": "play started"
}
```

| Field | Description |
| - | - |
| `api_id` | Unique identifier for this API request |
| `message` | Confirmation that playback has started |


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Call/{call_uuid}/Play/
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}/Play/:
    post:
      tags:
        - Play Audio
      summary: Play audio to a call
      description: Play an audio file to a live call leg.
      operationId: play-audio-call
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
                - urls
              properties:
                urls:
                  type: string
                  example: https://example.com/audio.mp3
                legs:
                  type: string
                  enum:
                    - aleg
                    - bleg
                    - both
                  default: aleg
                loop:
                  type: boolean
                  default: false
            example:
              urls: https://example.com/audio.mp3
              legs: aleg
      responses:
        '200':
          description: Audio playback started
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