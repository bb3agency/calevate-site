> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Origination URI

> Permanently remove a SIP destination URI from a Vobiz trunk, halting outbound routing to that endpoint - keep at least one active URI to avoid call failures.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris/{uri_id}
```

Permanently deletes an origination URI from your trunk. Once deleted, the trunk will no longer route outbound calls to this destination. This action cannot be undone.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Warning:** Deleting an origination URI is permanent and cannot be reversed. Ensure you have at least one active URI remaining for outbound calls to continue functioning.

  **Important:** If you delete all origination URIs, your trunk will not be able to route any outbound calls. Always maintain at least one active URI for production trunks.
</Warning>

<Warning>
  **Alternative:** Consider setting `enabled: false` to temporarily disable the URI without losing the configuration. This allows you to re-enable it later without needing to reconfigure the SIP destination, priority, and weight.
</Warning>

## Response

Returns `204 No Content` on successful deletion. No response body is returned.

```text Response - 204 No Content theme={null}
No Content
```

## Examples

### cURL - Delete Origination URI

```bash cURL Request theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/origination-uris/aabbccdd-1234-5678-90ab-cdef12345678 \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Info>
  **Error Response (404 Not Found):** If the origination URI does not exist:

  ```json Error Response - 404 Not Found theme={null}
  {
    "error": "Origination URI not found",
    "code": 404
  }
  ```
</Info>

<Note>
  **Before Deleting:**

  * List all origination URIs to verify the correct one is being deleted
  * Ensure at least one other active URI exists for outbound call routing
  * Consider the impact on failover and load balancing configuration
  * Save URI configuration details if you might need to recreate it later
</Note>

<Tip>
  **Safe Deletion Workflow:**

  1. First, set `enabled: false` on the URI to disable it
  2. Monitor outbound calls to ensure remaining URIs handle traffic correctly
  3. Wait for a testing period (e.g., 24 hours) to confirm no issues
  4. If no problems occur, proceed with permanent deletion
  5. If issues arise, re-enable the URI before it's deleted
</Tip>

<Warning>
  **Production Best Practices:**

  * Never delete the last remaining active origination URI on a production trunk
  * Always maintain at least 2 URIs (one primary, one backup) for redundancy
  * Document the reason for deletion and the URI configuration in your change log
  * Plan deletions during maintenance windows to minimize potential impact
</Warning>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/origination-uris/{uri_id}
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
  /api/v1/Account/{auth_id}/origination-uris/{uri_id}:
    delete:
      tags:
        - Origination URI
      summary: Delete an origination URI
      description: Delete an origination URI from a trunk.
      operationId: delete-origination-uri
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: uri_id
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
          description: Origination URI deleted
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