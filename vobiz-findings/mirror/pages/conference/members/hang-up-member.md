> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Hang up a member

> Terminate a conference member's call via DELETE - disconnect one participant, a list of IDs, or all members from a Vobiz multi-party voice call globally.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/
```

Terminate an active conference member's call. For a normal active member, Vobiz removes the member from the room, sends the conference exit callback, and ends the call.

<Info>
  **Authentication required:** `X-Auth-ID`, `X-Auth-Token`, `Content-Type: application/json`
</Info>

<Warning>
  **Reused-member-ID edge case:** If a member is kicked, continues its XML flow, and rejoins with the same numeric member ID, a later hang-up request can return `204 No Content` without removing the rejoined leg. Use the most recent `enter` callback, make cleanup idempotent, and confirm removal through an `exit` or call hangup callback.
</Warning>

<Note>
  [Kick a Member](/docs/conference/members/kick-member) is not a direct replacement for hang up. Kick removes the member from the room but continues the participant's XML flow after `<Conference>`; hang up ends the call.
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
  ```bash Hang up a specific member theme={null}
  curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/10/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```

  ```bash Hang up all members theme={null}
  curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/all/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"
  ```
</CodeGroup>

## Response

```text 204 No Content theme={null}
HTTP Status Code: 204
```

For a normal active member, `204 No Content` is followed by a conference exit callback and call termination. In the reused-member-ID edge case described above, confirm the final state through callbacks.


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/
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
  /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/:
    delete:
      tags:
        - Conference
      summary: Hang up a member
      description: >-
        Terminate one or more active conference member calls. A normal
        active-member request disconnects the member. If a member was kicked,
        continued its XML flow, and rejoined with the same numeric member ID,
        confirm removal through conference exit or call hangup callbacks.
      operationId: hangup-member
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
          description: Active member hung up
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