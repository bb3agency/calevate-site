> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete an Endpoint

> Permanently remove a SIP endpoint from your Vobiz account, immediately unregistering all devices and making the SIP URI permanently unavailable - irreversible.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/{endpoint_id}/
```

Permanently deletes an endpoint from your Vobiz account. Once deleted, the endpoint's SIP URI is no longer accessible, and any devices or applications registered with this endpoint will be disconnected.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Permanent Deletion:** This action is permanent and cannot be undone. Deleting an endpoint immediately unregisters it from all devices and makes the SIP URI permanently unavailable. Ensure no active calls or registrations depend on this endpoint before proceeding.
</Warning>

<Note>
  No request parameters are required for this endpoint.
</Note>

## Response

### Success Response (204 No Content)

On success, returns HTTP status code `204 No Content` with an empty response body.

```text Response - 204 No Content theme={null}
HTTP/1.1 204 No Content
```

### Error Response (404 Not Found)

If the endpoint does not exist or has already been deleted.

```text Response - 404 Not Found theme={null}
HTTP/1.1 404 Not Found
```

## Examples

### cURL

```bash cURL Request theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/87654321/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Info>
  **Before Deletion:**

  * Verify the endpoint is no longer needed
  * Check for any active registrations on SIP clients
  * Ensure no applications are routing calls to this endpoint
  * Consider updating endpoint instead if you need to change credentials
</Info>

<Warning>
  **Impact:** Deleting an endpoint immediately unregisters it from all devices and makes the SIP URI permanently unavailable. This action cannot be reversed.
</Warning>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Endpoint/{endpoint_id}/
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
  /api/v1/Account/{auth_id}/Endpoint/{endpoint_id}/:
    delete:
      tags:
        - Endpoints
      summary: Delete an Endpoint
      description: |
        Permanently delete an endpoint from your Vobiz account. Once deleted,
        the SIP URI will no longer be accessible, and any devices registered
        with this endpoint will be disconnected.
      operationId: delete-endpoint
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: endpoint_id
          in: path
          required: true
          schema:
            type: string
            example: '87654321'
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: string
        '204':
          description: Endpoint deleted
        '404':
          description: Endpoint not found
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