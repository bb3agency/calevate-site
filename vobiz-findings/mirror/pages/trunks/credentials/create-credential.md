> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Credential

> Add a SIP digest credential to a Vobiz trunk to authenticate softphones, IP phones, or AI voice agents - unique username required, password is write-only.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials
```

Creates a new set of SIP credentials (username and password) for authenticating calls on a specific trunk. The username must be unique within the trunk, and the password must meet minimum security requirements.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Important:** Save the password securely after creation. The API never returns the password in future responses - it is write-only for security purposes.

  **Note:** The username cannot be changed after creation. To use a different username, create a new credential and delete the old one.
</Warning>

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `username` | string | Yes | SIP username for authentication. Must be unique within the account. Cannot be changed after creation. Use alphanumeric names like `office_phone_01` or `user_john_mobile`. |
| `password` | string | Yes | SIP password for authentication. Minimum 8 characters. Recommended: 12+ characters with mixed case, numbers, and special characters. |

<Note>
  **Only `username` and `password` are accepted at creation.** The credential is created `enabled: true` by default. To disable it later, or to add a description, use [Update Credential](/docs/trunks/credentials/update-credential). The response also returns a `realm` (`{account_id}.sip.vobiz.ai`) - the SIP authentication realm your softphone or PBX must present alongside the username and password.
</Note>

<Warning>
  **Username characters.** Keep usernames alphanumeric. Dashes, underscores, and other punctuation can be rejected with a `400`. The `username` is immutable - to change it, create a new credential and delete the old one.
</Warning>

## Response

Returns the complete credential object, including the auto-generated `id` UUID. The password is not included in the response for security reasons.

```json Response - 201 Created theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "username": "sipuser_demo",
  "password": "<redacted>",
  "realm": "MA_XXXXXXXX.sip.vobiz.ai",
  "enabled": true,
  "created_at": "2026-05-12T05:11:51.635106Z",
  "updated_at": "2026-05-12T05:11:51.635106Z"
}
```

## Examples

### cURL - Basic Credential

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "trunk_user_001",
    "password": "SecurePassword123!"
  }'
```

### cURL - Credential with Strong Password

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "office_phone_main",
    "password": "Vbz!2025$SecureP@ss"
  }'
```

<Info>
  **Error Response (409 Conflict):** If the username already exists on the account:

  ```json Error Response theme={null}
  {
    "error": "Username already exists",
    "code": 409
  }
  ```
</Info>

<Tip>
  **Next Steps:**

  * Save the credential `id` for future operations
  * Store the password securely in your password manager
  * Configure your SIP client with the username and password
  * Test authentication by making a test call
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/credentials
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
  /api/v1/Account/{auth_id}/credentials:
    post:
      tags:
        - Credentials
      summary: Create a credential
      description: Create SIP credentials for trunk authentication.
      operationId: create-credential
      parameters:
        - $ref: '#/components/parameters/AuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                username:
                  type: string
                password:
                  type: string
              required:
                - username
                - password
            example:
              username: myuser
              password: securepassword123
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  account_id:
                    type: string
                  username:
                    type: string
                  password:
                    type: string
                  realm:
                    type: string
                  enabled:
                    type: boolean
                  created_at:
                    type: string
                  updated_at:
                    type: string
                required:
                  - id
                  - account_id
                  - username
                  - password
                  - realm
                  - enabled
                  - created_at
                  - updated_at
              example:
                id: aabbccdd-1234-5678-90ab-cdef12345678
                account_id: MA_XXXXXXXX
                username: acme_sip_user_01
                password: <redacted>
                realm: MA_XXXXXXXX.sip.vobiz.ai
                enabled: true
                created_at: '2026-03-25T10:00:00Z'
                updated_at: '2026-03-25T10:00:00Z'
        '201':
          description: Credential created
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