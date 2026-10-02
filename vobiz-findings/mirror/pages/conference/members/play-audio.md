> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Play Audio to a Member

> Inject a private MP3 or WAV audio file to targeted Vobiz conference members via POST - whisper announcements or hold music to one participant or all.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Play/
```

Use this endpoint to queue an audio file for one or more conference members. Vobiz fetches the file from the supplied URL and targets the member IDs in the request path.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Privacy:** Audio is played exclusively to the targeted member(s). Other conference participants will not hear the audio being played.
</Info>

<Warning>
  **Supported Formats:** MP3, WAV. Audio files must be accessible via HTTPS URL.
</Warning>

<Info>
  The `member_id` can be a specific member ID, a comma-separated list, or `all` to play audio to all members.
</Info>

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `url` | string | Yes | URL of the audio file to play. Must be accessible via HTTPS. Supported formats: MP3, WAV. |

## Response

```json Response - 202 Accepted theme={null}
{
  "message": "play queued into conference",
  "api_id": "API_REQUEST_ID",
  "member_id": ["10"]
}
```

## Examples

<CodeGroup>
  ```bash Play Audio to Specific Member theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/10/Play/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/audio/welcome.mp3"}'
  ```

  ```bash Play Audio to Multiple Members theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/10,15,22/Play/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/audio/announcement.mp3"}'
  ```

  ```bash Play Audio to All Members theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/all/Play/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/audio/broadcast.mp3"}'
  ```
</CodeGroup>

<Tip>
  **Common Use Cases:**

  * Play hold music while waiting
  * Deliver private announcements to specific members
  * Play instructions or prompts during the conference
  * Broadcast alerts or notifications to all participants
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Play/
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
  /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Play/:
    post:
      tags:
        - Conference
      summary: Play audio to a member
      description: Play an audio file to a specific conference member.
      operationId: play-audio-member
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: conference_name
          in: path
          required: true
          schema:
            type: string
        - name: member_id
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
                - url
              properties:
                url:
                  type: string
                  description: URL of the audio file to play
                  example: https://example.com/audio.mp3
      responses:
        '202':
          description: Audio playback queued
          content:
            application/json:
              example:
                message: play queued into conference
                member_id:
                  - '2'
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