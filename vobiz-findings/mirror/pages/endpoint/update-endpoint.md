> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update an Endpoint

> Modify a Vobiz SIP endpoint - rotate its password, update the alias, swap the attached application, or toggle voice and video permissions; no re-provisioning.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/{endpoint_id}/
```

Updates an existing endpoint's configuration. You can change the password, update the alias, or modify the application that handles incoming calls to this endpoint.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Cannot Update:** The following fields are locked after endpoint creation: `username`, `endpoint_id`, `domain`, `allow_same_domain`, `allow_other_domains`, `allow_phones`, `allow_apps`. To change these values, create a new endpoint and delete the old one.
</Warning>

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `password` | string | No | SIP password (minimum 8 characters). Use this to reset or update the endpoint password. |
| `alias` | string | No | Friendly name for the endpoint. |
| `application` | integer | No | Application ID for call routing. This application will handle incoming calls to the endpoint. |
| `allow_voice` | boolean | No | Allow voice calls (default: `true`). |
| `allow_message` | boolean | No | Allow messaging (default: `true`). |
| `allow_video` | boolean | No | Allow video calls (default: `false`). |

<Note>
  All parameters are optional. You only need to include the fields you want to update. Fields not provided will remain unchanged.
</Note>

<Note>
  Setting `application` to a different numeric `app_id` swaps which application handles this endpoint's calls. An unknown `app_id` returns a `400`. An endpoint binds to exactly one application at a time.
</Note>

## Response

### Success Response (202 Accepted)

On success, returns HTTP status code `202 Accepted` with no response body.

```text Response - 202 Accepted theme={null}
HTTP/1.1 202 Accepted
```

### Error Response (400 Bad Request)

```json Response - 400 Bad Request theme={null}
{
  "error": "invalid request parameters",
  "details": {
    "password": "Password must be at least 8 characters"
  }
}
```

### Error Response (404 Not Found)

```text Response - 404 Not Found theme={null}
HTTP/1.1 404 Not Found
```

## Examples

### Update Alias

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/87654321/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "alias": "John'\''s Updated Desktop Phone"
  }'
```

### Update Password

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/87654321/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "password": "NewSecurePassword456!"
  }'
```

### Update Multiple Fields

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/87654321/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "alias": "John'\''s Updated Desktop Phone",
    "password": "NewSecurePassword456!",
    "application": 98765432,
    "allow_voice": true,
    "allow_message": true,
    "allow_video": true
  }'
```

<Tip>
  **Common Use Cases:**

  * Reset forgotten endpoint passwords
  * Update aliases to reflect role changes
  * Switch applications for different call routing logic
  * Rotate passwords regularly for security
  * Enable or disable video/messaging capabilities
</Tip>

<Info>
  After updating a password, SIP clients using this endpoint must re-register with the new credentials. Plan updates during maintenance windows to minimize disruption.
</Info>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Endpoint/{endpoint_id}/
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
    post:
      tags:
        - Endpoints
      summary: Update an Endpoint
      description: |
        Update an existing endpoint's configuration. You can change the
        password, alias, or attached application. The fields `username`,
        `endpoint_id`, `domain`, `allow_same_domain`, `allow_other_domains`,
        `allow_phones`, and `allow_apps` are locked after creation.
      operationId: update-endpoint
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: endpoint_id
          in: path
          required: true
          schema:
            type: string
            example: '87654321'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                alias:
                  type: string
                password:
                  type: string
              required:
                - alias
                - password
            example:
              alias: John's Updated Desktop Phone
              password: NewSecurePassword456!
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: string
              example: ''
        '202':
          description: Endpoint updated
          content:
            text/plain:
              schema:
                type: string
              example: ''
        '400':
          description: Invalid request parameters
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
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