> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Deaf a Member

> Block incoming audio for conference participants via POST - deafen one member, a comma-separated list, or all members in a Vobiz multi-party call globally.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Deaf/
```

Use this endpoint to deafen members of a conference. When deafened, members cannot hear audio from other participants, but they remain connected to the conference and can still be heard by others.

<Note>
  **Deaf vs Mute:**

  * **Deaf:** Member cannot hear others (incoming audio blocked)
  * **Mute:** Others cannot hear the member (outgoing audio blocked)
</Note>

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  Deafened members can still speak and be heard by others. To prevent them from being heard, use the Mute Member endpoint.
</Warning>

<Info>
  The `member_id` can be a specific member ID, a comma-separated list, or `all` to deafen all members.
</Info>

## Request Body

```json JSON theme={null}
{}
```

No request body parameters required. Send an empty JSON object.

## Response

```json Response - 202 Accepted theme={null}
{
  "message": "deaf",
  "member_id": ["10"],
  "api_id": "API_REQUEST_ID"
}
```

## Examples

<CodeGroup>
  ```bash Deaf Specific Member theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/10/Deaf/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}'
  ```

  ```bash Deaf All Members theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/all/Deaf/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}'
  ```
</CodeGroup>

<Tip>
  **Common Use Cases:**

  * Create listen-only mode for webinar attendees
  * Prevent feedback loops during audio playback
  * Isolate members for private whisper conversations
  * Testing scenarios where member should not hear conference
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Deaf/
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
  /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Deaf/:
    post:
      tags:
        - Conference
      summary: Mute a member's audio
      description: Prevent a conference member from hearing other participants.
      operationId: deaf-member
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
      responses:
        '202':
          description: Deaf request accepted
          content:
            application/json:
              example:
                message: deaf
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