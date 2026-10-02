> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete a Subaccount

> Permanently delete a Vobiz subaccount and revoke its authentication credentials - irreversible operation for offboarding tenants or closing reseller accounts.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/accounts/{auth_id}/sub-accounts/{sub_auth_id}
```

Permanently deletes a subaccount and all its associated credentials.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Warning:** Deleting a subaccount is permanent. This action cannot be undone. Ensure you have backed up any necessary data before proceeding.
</Warning>

## Parameters

No request body or parameters required. The sub-account ID is specified in the URL path.

## Request

```bash cURL theme={null}
curl -X DELETE 'https://api.vobiz.ai/api/v1/accounts/{auth_id}/sub-accounts/{sub_auth_id}' \
--header 'X-Auth-ID: {auth_id}' \
--header 'X-Auth-Token: {auth_token}'
```

## Response Example

```json Success Response (200 OK) theme={null}
{
  "message": "Sub-account deleted successfully"
}
```

<Tip>
  **Success:** The API returns a 200 OK status with a confirmation message when the sub-account is successfully deleted.
</Tip>

## Lost the sub-account credentials?

You do **not** need the sub-account's own `auth_id` / `auth_token` to delete it. This endpoint authenticates as the **parent** (`X-Auth-ID` / `X-Auth-Token` of your `MA_…` account), and the sub-account is identified by the `{sub_auth_id}` in the path. So even if the credentials returned at creation were lost, the parent can still find and remove the sub-account.

<Steps>
  <Step title="List your sub-accounts to find the SA_ id">
    Call [List Sub-Accounts](/docs/sub-accounts/list-all-subaccounts) and identify the one to remove by its `name`, `email`, or `created` timestamp.

    ```bash theme={null}
    curl -X GET 'https://api.vobiz.ai/api/v1/accounts/{MA_AUTH_ID}/sub-accounts/?active_only=true' \
    --header 'X-Auth-ID: {MA_AUTH_ID}' \
    --header 'X-Auth-Token: {MA_AUTH_TOKEN}'
    ```
  </Step>

  <Step title="Delete it by its SA_ auth id">
    Use the `auth_id` (`SA_…`) from the listing as `{sub_auth_id}`:

    ```bash theme={null}
    curl -X DELETE 'https://api.vobiz.ai/api/v1/accounts/{MA_AUTH_ID}/sub-accounts/{SA_AUTH_ID}' \
    --header 'X-Auth-ID: {MA_AUTH_ID}' \
    --header 'X-Auth-Token: {MA_AUTH_TOKEN}'
    ```
  </Step>
</Steps>


## OpenAPI

````yaml DELETE /api/v1/accounts/{auth_id}/sub-accounts/{sub_auth_id}
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
  /api/v1/accounts/{auth_id}/sub-accounts/{sub_auth_id}:
    delete:
      tags:
        - Sub-Accounts
      summary: Delete a sub-account
      description: Permanently delete a sub-account and revoke its credentials.
      operationId: delete-subaccount
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: sub_auth_id
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
                type: object
                properties:
                  message:
                    type: string
                required:
                  - message
        '204':
          description: Sub-account deleted
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