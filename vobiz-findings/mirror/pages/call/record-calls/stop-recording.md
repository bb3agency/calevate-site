> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop recording a call

> Stop one or all active recordings on a Vobiz call - finalize the audio file, trigger the callback URL, and make the recording available for download.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Record/
```

Stop active recordings on a call. Since a call can have multiple ongoing recordings, you can stop a specific recording by providing its URL, or stop all recordings by omitting the parameter.

<Note>
  When a recording is stopped, it is finalized and made available for download. If you configured a `callback_url`, it will be invoked with the recording details.
</Note>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz authentication ID |
| `call_uuid` | string | Yes | Unique identifier of the call being recorded |

## Request parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `URL` | string | No | The recording URL to stop. If omitted, all active recordings on the call are stopped. |

<Tip>
  To stop only one specific recording, provide the `url` returned by the [Start Recording](/docs/call/record-calls/start-recording) response. Omit it to stop all ongoing recordings.
</Tip>

## Example requests

<CodeGroup>
  ```bash Stop all recordings theme={null}
  curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Record/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```

  ```json Stop a specific recording theme={null}
  {
    "URL": "http://s3.amazonaws.com/recordings_2013/48dfaf60-3b2a-11e3.mp3"
  }
  ```
</CodeGroup>

## Response

```text 204 No Content theme={null}
HTTP Status Code: 204
```

A `204` status code means the recording has been stopped and will be finalized. There is no response body.

<Tip>
  After stopping a recording, retrieve it using the [Recordings API](/docs/recording) or wait for the callback to receive the download URL.
</Tip>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Call/{call_uuid}/Record/
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
    delete:
      tags:
        - Record Calls
      summary: Stop recording a call
      description: Stop an active recording on an in-progress call.
      operationId: stop-recording
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: call_uuid
          in: path
          required: true
          schema:
            type: string
      responses:
        '204':
          description: Recording stopped
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