> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Unmute a member

> Restore outgoing audio for muted Vobiz conference members via DELETE - unmute one participant, a list of IDs, or all members in a multi-party call globally.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Mute/
```

Unmute members who were previously muted. Once unmuted, their audio is transmitted to all other participants in the conference.

<Info>
  **Authentication required:** `X-Auth-ID`, `X-Auth-Token`, `Content-Type: application/json`
</Info>

<Note>
  If a member was never muted, this call has no effect but returns success.
</Note>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID |
| `conference_name` | string | Yes | Name of the conference |
| `member_id` | string | Yes | Member ID, comma-separated list of IDs, or `all` |

## Request body

No request body required.

## Examples

<CodeGroup>
  ```bash Unmute a specific member theme={null}
  curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/10/Mute/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```

  ```bash Unmute multiple members theme={null}
  curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/10,15,22/Mute/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```

  ```bash Unmute all members theme={null}
  curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/all/Mute/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```
</CodeGroup>

## Response

```text 204 No Content theme={null}
HTTP Status Code: 204
```

Vobiz restores the member's ability to speak and returns an empty response body.

## Common use cases

* End presenter mode and allow audience participation.
* Restore audio after temporary mute during announcements.
* Enable Q\&A session participation.
* Unmute after disruptive behavior has ceased.


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Mute/
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
  /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Mute/:
    delete:
      tags:
        - Conference Members
      summary: Unmute a conference member
      description: Allow a muted member to speak again.
      operationId: unmute-member
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
        '204':
          description: Member unmuted
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