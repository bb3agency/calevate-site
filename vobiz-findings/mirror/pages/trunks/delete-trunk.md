> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete a Trunk

> Permanently delete a Vobiz SIP trunk and all associated credentials, IP ACLs, and origination URIs - this action is irreversible and stops all trunk traffic.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/{trunk_id}
```

Permanently deletes a trunk and all its associated resources, including credentials, IP ACL entries, and origination URIs. This action cannot be undone.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Warning:** Deleting a trunk will:

  * Permanently delete all credentials associated with this trunk
  * Remove all IP ACL entries
  * Delete all origination URIs
  * Immediately stop all active calls on this trunk
  * Make the trunk's SIP domain unavailable for inbound calls

  **Alternative:** Consider disabling the trunk instead (set `enabled: false`) to preserve its configuration while preventing new calls.
</Warning>

## Request

```bash cURL theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/bfab10fb-cb97-488b-9c63-989c32980b0f \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

## Response

Returns `204 No Content` on successful deletion. No response body is returned.

```text Response - 204 No Content theme={null}
No Content
```

<Note>
  **Error Responses:**

  * **404 Not Found:** Trunk does not exist or does not belong to your account
  * **409 Conflict:** Trunk has active calls (wait for calls to end first)
</Note>

<Warning>
  **Before Deleting:**

  * Verify no active calls are using this trunk
  * Document any credentials or routing configurations
  * Check if phone numbers are associated with this trunk
  * Consider exporting trunk configuration for backup
  * Notify users who may be affected by the deletion
</Warning>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/trunks/{trunk_id}
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
  /api/v1/Account/{auth_id}/trunks/{trunk_id}:
    delete:
      tags:
        - Trunks
      summary: Delete a trunk
      description: Permanently delete a SIP trunk.
      operationId: delete-trunk
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: trunk_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: string
        '204':
          description: Trunk deleted
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