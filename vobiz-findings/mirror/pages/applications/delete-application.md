> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete an Application

> Permanently delete a Vobiz voice application by app_id - removes all webhook configuration and disassociates attached phone numbers and SIP endpoints.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/{app_id}/
```

Permanently deletes an application.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Warning:** Deletion is permanent and cannot be undone. If the application is associated with phone numbers, the deletion is blocked with a `409` until those associations are removed.
</Warning>

<Note>
  **Delete an app that is in use:** first [detach every number](/docs/applications/detach-number) bound to it (and repoint any endpoints whose `application` is this app, via [update endpoint](/docs/endpoint/update-endpoint)), then call delete. Deleting a `default_number_app`/`default_endpoint_app` removes the auto-routing default - set a new default on another application beforehand if you rely on it.
</Note>

## Arguments

No request parameters needed.

## Response Examples

**Success Response (204 No Content)** - No response body.

<CodeGroup>
  ```json Error Response (404 Not Found) theme={null}
  {
    "error": "Application not found",
    "app_id": "12345678901234567"
  }
  ```

  ```json Error Response (409 Conflict) theme={null}
  {
    "error": "Cannot delete application",
    "message": "Application is currently in use by 5 phone numbers"
  }
  ```
</CodeGroup>

### cURL Example

```bash cURL theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/12345678901234567/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Application/{app_id}/
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
  /api/v1/Account/{auth_id}/Application/{app_id}/:
    delete:
      tags:
        - Applications
      summary: Delete an Application
      description: |
        Permanently delete an Application. If the application is associated
        with phone numbers, the deletion may be blocked unless those
        associations are removed first.
      operationId: delete-application
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: app_id
          in: path
          required: true
          schema:
            type: string
            example: '12345678'
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: string
        '204':
          description: Application deleted
        '404':
          description: Application not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '409':
          description: Cannot delete application (in use)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
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
  schemas:
    Error:
      type: object
      properties:
        api_id:
          type: string
        error:
          type: string
        message:
          type: string
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