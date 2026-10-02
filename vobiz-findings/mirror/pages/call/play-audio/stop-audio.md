> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop playing audio on a call

> Interrupt audio playback on an active Vobiz call instantly - stop hold music, end looping files, or cancel announcements when an agent becomes available.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Play/
```

Stop audio playback that is currently playing on an active call. Useful for ending hold music when an agent becomes available, stopping looping audio, or interrupting announcements based on user input.

<Note>
  If no audio is currently playing on the call, this endpoint returns success without performing any action.
</Note>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz authentication ID |
| `call_uuid` | string | Yes | Unique identifier of the active call |

## Request body

No request body is required. Send an empty JSON object `{}` or omit the body entirely.

## Example request

```bash cURL theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Play/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

## Response

```text 204 No Content theme={null}
HTTP Status Code: 204
```

A `204` status code indicates audio playback was stopped successfully. There is no response body.

## Common use cases

* Stop hold music when an agent becomes available.
* End looping audio based on user DTMF input.
* Interrupt announcements when a call is answered.
* Stop IVR prompts when a user makes a selection.
* End audio playback before transferring a call.

<Tip>
  Use this endpoint together with [Play Audio](/docs/call/play-audio/play-audio) to create dynamic audio experiences that respond to user actions or call events.
</Tip>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Call/{call_uuid}/Play/
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
    delete:
      tags:
        - Play Audio
      summary: Stop audio playback on a call
      description: Stop audio playing on a live call.
      operationId: stop-audio-call
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: call_uuid
          in: path
          required: true
          schema:
            type: string
      responses:
        '204':
          description: Playback stopped
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