> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Credential

> Permanently revoke a SIP digest credential from your Vobiz trunk - every device or AI agent using that username loses authentication access immediately.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials/{credential_id}
```

Permanently deletes a credential from a trunk. Once deleted, the credential can no longer be used for SIP authentication, and any devices or applications using it will be unable to connect. This action cannot be undone.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Warning:** Deleting a credential will:

  * Immediately prevent authentication using this username and password
  * Disconnect any active calls using this credential
  * Block any devices configured with this credential from making new calls
  * Permanently remove the credential - this cannot be undone

  **Alternative:** Consider disabling the credential instead (set `enabled: false`) to temporarily prevent authentication while preserving it for future use or audit purposes.
</Warning>

## Response

Returns `204 No Content` on successful deletion. No response body is returned.

```text Response - 204 No Content theme={null}
No Content
```

<Note>
  **Error Responses:**

  * **404 Not Found:** Credential does not exist or does not belong to the specified trunk
  * **409 Conflict:** Credential is currently in use by active calls (wait for calls to end first)
</Note>

## Examples

### cURL

```bash cURL Request theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Warning>
  **Before Deleting:**

  * Verify no active calls are using this credential
  * Document the credential details (username, description) for records
  * Check if any devices or applications are configured with this credential
  * Notify affected users who may be using this credential
  * Consider disabling instead of deleting to preserve audit trail
  * Ensure you have alternative credentials configured for the trunk
</Warning>

<Info>
  **Common Use Cases:**

  * Removing credentials for decommissioned devices
  * Cleaning up test credentials after development
  * Deleting compromised credentials after creating replacements
  * Removing access for users who no longer need it
</Info>

<Note>
  **Recovery:** Deleted credentials cannot be recovered. You must create a new credential with a new username and password, then reconfigure all affected devices.
</Note>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/credentials/{credential_id}
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
  /api/v1/Account/{auth_id}/credentials/{credential_id}:
    delete:
      tags:
        - Credentials
      summary: Delete a credential
      description: Delete an existing SIP credential.
      operationId: delete-credential
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: credential_id
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
          description: Credential deleted
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