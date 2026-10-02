> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete IP ACL

> Permanently remove a whitelisted IPv4 address from a Vobiz SIP trunk, revoking IP-based authentication and blocking unauthenticated calls from that address.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl/{ip_acl_id}
```

Permanently deletes an IP ACL entry from a trunk. Once deleted, the IP address is no longer whitelisted for authentication, and calls from that IP will be rejected unless other authentication methods (such as credentials) are configured.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Warning:** This action is permanent and cannot be undone. Active connections from this IP address may be immediately disconnected.

  **Alternative:** Consider disabling the IP ACL entry instead of deleting it by setting `enabled: false`. This preserves the configuration for future use.
</Warning>

## Response

Returns `204 No Content` on successful deletion. No response body is returned.

```text Response - 204 No Content theme={null}
No Content
```

## Examples

### cURL - Delete IP ACL

```bash cURL Request theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl/c1d2e3f4-a5b6-7890-cdef-1234567890ab \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Info>
  **Error Response (404 Not Found):** If the IP ACL ID does not exist or was already deleted:

  ```json Error Response - 404 Not Found theme={null}
  {
    "error": "IP ACL not found",
    "code": 404
  }
  ```
</Info>

<Warning>
  **Before Deleting:**

  * Verify you have the correct IP ACL ID
  * Ensure you have alternative authentication methods configured (if needed)
  * Check if there are active connections from this IP
  * Consider temporarily disabling instead of deleting
</Warning>

<Tip>
  **After Deletion:**

  * The IP address is immediately removed from the whitelist
  * New authentication attempts from this IP will fail
  * Active calls may be terminated depending on trunk configuration
  * The IP ACL entry cannot be recovered - create a new one if needed
</Tip>

<Note>
  **Alternative - Disable Instead:** To temporarily block an IP without losing the configuration:

  ```bash Alternative - Disable IP ACL theme={null}
  curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl/IP_ACL_ID \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"enabled": false}'
  ```
</Note>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/ip-acl/{ip_acl_id}
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
  /api/v1/Account/{auth_id}/ip-acl/{ip_acl_id}:
    delete:
      tags:
        - IP Access Control List
      summary: Delete an IP ACL
      description: Remove an IP access control rule.
      operationId: delete-ip-acl
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: ip_acl_id
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
          description: IP ACL deleted
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