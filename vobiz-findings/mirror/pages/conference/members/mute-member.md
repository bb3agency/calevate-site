> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Mute a Member

> Silence outgoing audio for conference participants via POST - mute one member, a comma-separated list, or all members in a Vobiz multi-party call globally.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Mute/
```

Use this endpoint to mute members of a conference. Other members in the conference will not be able to hear the muted caller.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Tip>
  Muted members can still hear other participants, but cannot be heard by others. To prevent a member from hearing, use the Deaf Member endpoint.
</Tip>

<Info>
  The `member_id` can be a specific member ID, a comma-separated list, or `all` to mute all members.
</Info>

## Request Body

```json JSON theme={null}
{}
```

No request body parameters required. Send an empty JSON object.

## Response

```json Response - 202 Accepted theme={null}
{
  "message": "muted",
  "member_id": ["10"],
  "api_id": "API_REQUEST_ID"
}
```

## Error responses

| Status | Meaning | How to handle |
| - | - | - |
| `401 Unauthorized` | Missing/incorrect auth headers or a lowercase path. | Use both auth headers and the PascalCase path. |
| `404 Not Found` | The conference does not exist, or the `member_id` is not in it (e.g. they already left). | Re-fetch members with [Retrieve a Conference](/docs/conference/retrieve-conference). URL-encode names with spaces. |

## Examples

<CodeGroup>
  ```bash Mute Specific Member theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/10/Mute/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json"
  ```

  ```bash Mute All Members theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/MyConf/Member/all/Mute/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json"
  ```
</CodeGroup>

<Warning>
  **Common Use Cases:**

  * Mute all members during presenter mode
  * Silence disruptive participants
  * Temporary mute during announcements
  * Q\&A session control
</Warning>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Conference/{conference_name}/Member/{member_id}/Mute/
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
    post:
      tags:
        - Conference Members
      summary: Mute a conference member
      description: Prevent a member from speaking. Use `all` as member_id to mute everyone.
      operationId: mute-member
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
          description: Member ID, comma-separated IDs, or `all`
          schema:
            type: string
      responses:
        '202':
          description: Mute request accepted
          content:
            application/json:
              example:
                message: muted
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