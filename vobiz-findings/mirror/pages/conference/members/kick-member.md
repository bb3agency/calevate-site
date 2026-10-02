> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Kick a member

> Remove a conference participant via POST while continuing their XML flow - play a post-disconnect message or redirect them across Vobiz's global voice network.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Kick/
```

Disconnect a member from a conference. Unlike [Hang Up](/docs/conference/members/hang-up-member), kicking a member continues their XML execution - so you can play them a message or redirect them after they leave.

<Info>
  **Authentication required:** `X-Auth-ID`, `X-Auth-Token`, `Content-Type: application/json`
</Info>

<Tip>
  **Kick vs Hang Up:** Use Kick when you want to remove a member but play them an announcement or redirect them via XML after disconnect. Use Hang Up to terminate the call completely.
</Tip>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID |
| `conference_name` | string | Yes | Name of the conference |
| `member_id` | string | Yes | Member ID, comma-separated list of IDs, or `all` |

## XML continuation example

When a member is kicked, Vobiz executes the next element in the XML. For example:

```xml theme={null}
<Response>
    <Conference enterSound="beep:1">MyConference</Conference>
    <Speak>You have been disconnected from the conference</Speak>
</Response>
```

## Request body

No request body required. Send an empty JSON object `{}`.

## Examples

<CodeGroup>
  ```bash Kick a specific member theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/10/Kick/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}'
  ```

  ```bash Kick all members theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/all/Kick/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}'
  ```
</CodeGroup>

## Response

```json 202 Accepted theme={null}
{
  "message": "kicked",
  "member_id": ["10"],
  "api_id": "API_REQUEST_ID"
}
```

Vobiz removes the member from the room and continues the call with the next element after `<Conference>` in the participant's XML response. A later join may reuse the same member ID.


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Kick/
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
  /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Kick/:
    post:
      tags:
        - Conference
      summary: Kick a conference member
      description: >-
        Remove one or more participants from a conference while allowing their
        XML flow to continue.
      operationId: kick-member
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
          description: Kick request accepted
          content:
            application/json:
              example:
                message: kicked
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