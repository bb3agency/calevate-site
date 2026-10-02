> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Speak text on a call

> Convert text to speech on any active Vobiz call - choose from 29 languages including Hindi, and WOMAN or MAN voice, for dynamic in-call messages.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Speak/
```

Convert text to speech and play it during an active call. Choose from 29 languages and multiple voice options (WOMAN and MAN) to deliver dynamic messages without pre-recording audio files.

<Note>
  Default language is English (US) with WOMAN voice. Voice availability varies by language - see the table below.
</Note>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz authentication ID |
| `call_uuid` | string | Yes | Unique identifier of the active call |

## Request parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `text` | string | Yes | The text to convert to speech |
| `voice` | string | No | Voice type. Values: `WOMAN`, `MAN`, `Polly`. Default: `WOMAN` |
| `language` | string | No | Language code (e.g., `en-US`, `es-ES`). Default: `en-US` |
| `legs` | string | No | Which leg(s) to speak on. Values: `aleg`, `bleg`, `both`. Default: `aleg` |
| `loop` | boolean | No | Whether to loop the speech. Default: `false` |
| `mix` | boolean | No | Whether to mix with call audio. Default: `true` |

<Tip>
  * Keep text under 500 characters for optimal speech quality.
  * Use periods and commas to control pacing and natural pauses.
  * Set `mix=false` for important announcements so the caller hears them clearly.
</Tip>

## Supported languages

| Language | Code | Voices |
| - | - | - |
| Arabic | `arb` | WOMAN |
| Chinese Mandarin | `cmn-CN` | WOMAN |
| Danish | `da-DK` | WOMAN, MAN |
| Dutch | `nl-NL` | WOMAN, MAN |
| English (Australia) | `en-AU` | WOMAN, MAN |
| English (India) | `en-IN` | WOMAN |
| English (UK) | `en-GB` | WOMAN, MAN |
| English (US) | `en-US` | WOMAN, MAN |
| English (Wales) | `en-GB-WLS` | WOMAN, MAN |
| French | `fr-FR` | WOMAN, MAN |
| French (Canadian) | `fr-CA` | WOMAN |
| German | `de-DE` | WOMAN, MAN |
| Hindi | `hi-IN` | WOMAN |
| Icelandic | `is-IS` | WOMAN, MAN |
| Italian | `it-IT` | WOMAN, MAN |
| Japanese | `ja-JP` | WOMAN, MAN |
| Korean | `ko-KR` | WOMAN, MAN |
| Norwegian | `nb-NO` | WOMAN |
| Polish | `pl-PL` | WOMAN, MAN |
| Portuguese (Brazilian) | `pt-BR` | WOMAN, MAN |
| Portuguese (European) | `pt-PT` | WOMAN, MAN |
| Romanian | `ro-RO` | WOMAN |
| Russian | `ru-RU` | WOMAN, MAN |
| Spanish (European) | `es-ES` | WOMAN, MAN |
| Spanish (US) | `es-US` | WOMAN, MAN |
| Swedish | `sv-SE` | WOMAN |
| Turkish | `tr-TR` | WOMAN |
| Welsh | `cy-GB` | WOMAN, MAN |
| Yue Chinese | `yue-CN` | WOMAN |

<Note>
  If you request MAN voice for a language that only supports WOMAN, the API automatically falls back to WOMAN.
</Note>

## Example requests

<CodeGroup>
  ```json Request body theme={null}
  {
    "text": "Hello, this is a test message from the text-to-speech system.",
    "voice": "WOMAN",
    "language": "en-US",
    "legs": "both",
    "loop": false,
    "mix": true
  }
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Speak/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "text": "Hello, this is a test message.",
      "voice": "WOMAN",
      "language": "en-US"
    }'
  ```
</CodeGroup>

## Response

```json 202 Accepted theme={null}
{
  "api_id": "uuid-here",
  "message": "speak started"
}
```

| Field | Description |
| - | - |
| `api_id` | Unique identifier for this API request |
| `message` | Confirmation that text-to-speech has started |

## Error responses

| Status | Meaning | How to handle |
| - | - | - |
| `400 Bad Request` | `text` is missing/empty, or an unsupported `language`/`voice` combination was sent. | Send non-empty `text`; pick a `language` code from the table. Unsupported `MAN` voices fall back to `WOMAN` automatically. |
| `401 Unauthorized` | Missing/incorrect auth headers or a lowercase path. | Use both auth headers and the PascalCase path. |
| `404 Not Found` | The `call_uuid` is not an active call. | The call must be in-progress; confirm with [Retrieve a Live Call](/docs/call/retrieve-live-call). |

<Tip>
  Combine the Speak Text API with DTMF input capture to create interactive voice response systems that respond to user selections in real-time. Use `legs=bleg` to address only the callee, or `both` for everyone.
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Call/{call_uuid}/Speak/
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}/Speak/:
    post:
      tags:
        - Speak Text
      summary: Speak text on a call
      description: Convert text to speech and play it on a live call.
      operationId: speak-text-call
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
                - text
              properties:
                text:
                  type: string
                  example: Hello, your appointment is confirmed.
                voice:
                  type: string
                  default: WOMAN
                language:
                  type: string
                  default: en-US
                legs:
                  type: string
                  enum:
                    - aleg
                    - bleg
                    - both
                  default: aleg
            example:
              text: Hello, your appointment is confirmed for tomorrow at 3 PM.
              voice: WOMAN
              language: en-US
      responses:
        '200':
          description: TTS started
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