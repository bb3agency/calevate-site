> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Hang Up a Conference

> Terminate an active Vobiz conference by name via DELETE - instantly disconnects all participants and stops any in-progress recordings across 130+ countries.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/
```

This endpoint terminates a specific conference identified by its name. All participants in the conference will be disconnected immediately.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  The current conference instance ends and its members disconnect. A later call using `<Conference>` with the same name can create a new conference instance.
</Warning>

<Tip>
  **Use Cases:** End scheduled meetings on time, terminate conferences due to emergencies, clean up abandoned conference rooms, administrative conference management.
</Tip>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID (e.g., `{auth_id}`) |
| `conference_name` | string | Yes | Name of the conference to terminate |

<Tip>
  **No request body needed.** Simply use the DELETE method with the conference name in the URL path.
</Tip>

## Request Body

```json JSON theme={null}
{}
```

No request body parameters required. Send an empty JSON object.

## Response

Returns an acknowledgment that the conference has been terminated.

```text Response - 204 No Content theme={null}
HTTP Status Code: 204
```

<Tip>
  **What Happens:**

  1. All participants are immediately disconnected from the conference
  2. The current conference instance ends. A later call using `<Conference>` with the same name can create a new conference instance
  3. Vobiz sends exit callbacks for disconnected members when a callback URL is configured
</Tip>

<Info>
  If the conference has already ended or does not exist, you may receive an error response. Always handle 404 errors gracefully in your application.
</Info>

## Example Request

### Hang Up Conference by Name

```bash cURL Request theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/My%20Conf%20Room/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

URL-encode conference names that contain spaces or special characters.

<Warning>
  **Common Use Cases:**

  * **Scheduled end time:** Automatically terminate meetings at their scheduled end time
  * **Emergency termination:** End conferences immediately due to security or policy violations
  * **Admin control:** Allow moderators to end conferences from admin panels
  * **Cleanup:** Terminate abandoned conference rooms to free resources
  * **Time limits:** Enforce maximum conference duration limits
  * **Workflow triggers:** End conference when specific conditions are met
</Warning>

<Tip>
  **Best Practices:**

  * Notify participants before hanging up a conference (e.g., play announcement first)
  * Track the room name in your application; the retrieve endpoint is not reliable for preflight checks
  * Log conference terminations for audit trails and analytics
  * Implement confirmation dialogs in admin UIs before terminating active conferences
  * Handle errors gracefully - conference may have already ended naturally
  * Consider using Kick Member instead if you only need to remove specific participants
</Tip>

<Note>
  **Alternative: Hang Up All Conferences**

  If you need to terminate all conferences at once (e.g., for system maintenance), use the [Hang Up All Conferences](/docs/conference/hang-up-all-conferences) endpoint instead.
</Note>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Conference/{conference_name}/
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
  /api/v1/Account/{auth_id}/Conference/{conference_name}/:
    delete:
      tags:
        - Conferences
      summary: Delete a conference
      description: Terminate a specific conference room and disconnect all members.
      operationId: delete-conference
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: conference_name
          in: path
          required: true
          schema:
            type: string
      responses:
        '204':
          description: Conference deleted
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