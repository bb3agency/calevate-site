> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop conference recording

> Stop an active Vobiz conference recording and handle the empty success response.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/Record/
```

Stop an active conference recording. Vobiz stops media capture and returns an empty success response.

<Note>
  This endpoint does not return a recording ID or download URL.
</Note>

<Warning>
  Treat only `204 No Content` as a successful stop response. Handle any other status as an error in your application.
</Warning>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID |
| `conference_name` | string | Yes | Name of the conference |

## Request body

No request body required.

## Example request

<CodeGroup>
  ```bash cURL theme={null}
  curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Record/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```

  ```javascript JavaScript theme={null}
  async function stopRecording(conferenceName) {
    const response = await fetch(
      `https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/${encodeURIComponent(conferenceName)}/Record/`,
      {
        method: 'DELETE',
        headers: {
          'X-Auth-ID': '{auth_id}',
          'X-Auth-Token': 'YOUR_AUTH_TOKEN'
        }
      }
    );

    if (response.status === 204) {
      console.log('Recording stopped successfully');
    }
  }

  stopRecording('MyConf');
  ```
</CodeGroup>

## Response

```text 204 No Content theme={null}
HTTP Status Code: 204
```

A `204` response indicates that Vobiz stopped the recording. Recording callback delivery and recording retrieval are not currently guaranteed by this flow.


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Conference/{conference_name}/Record/
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
    delete:
      tags:
        - Conference Recording
      summary: Stop conference recording
      description: Stop recording a conference room.
      operationId: stop-conference-recording
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: conference_name
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