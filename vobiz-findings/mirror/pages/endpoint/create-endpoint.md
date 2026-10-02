> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create an Endpoint

> Provision a new SIP endpoint on Vobiz to register IP phones, softphones, or AI voice agents - assign a SIP URI, credentials, and call permissions in one call.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/
```

Creates a new SIP endpoint for making and receiving calls through IP phones, softphones, or SIP clients. Each endpoint is assigned a unique SIP URI and endpoint ID.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Note>
  **SIP registration:** Your endpoint SIP URI follows `sip:username@registrar.vobiz.ai`. Configure `registrar.vobiz.ai` as the registrar or server in your softphone, desk phone, or custom WebRTC SIP client. Authenticate with the endpoint `username` and `password`.

  Your account Auth ID and Auth Token authenticate REST API requests and the hosted WebRTC Playground. They do not authenticate SIP endpoint registration. SIP endpoints do not require a separate token or JWT.
</Note>

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `username` | string | Yes | SIP username, **unique per account** and **immutable** after creation. Only alphanumeric characters are accepted - hyphens, underscores, spaces, and other symbols may be rejected with a `400`. A duplicate username returns a `409` conflict. |
| `password` | string | Yes | SIP password. Minimum 8 characters recommended. Write-only - never returned in any response. |
| `alias` | string | Yes | Friendly name for the endpoint. Accepts alphabets, numbers (0-9), hyphen (-), and underscore (\_) only. |
| `application` | integer | Recommended | Numeric `app_id` for call routing. If omitted, the endpoint falls back to the account's `default_endpoint_app` (if one is set); otherwise it has no call-handling application. |
| `allow_voice` | boolean | No | Allow voice calls (default: `true`). |
| `allow_message` | boolean | No | Allow messaging (default: `true`). |
| `allow_video` | boolean | No | Allow video calls (default: `false`). |
| `allow_same_domain` | boolean | No | Allow calls to same domain (default: `true`). |
| `allow_other_domains` | boolean | No | Allow calls to other domains (default: `false`). |
| `allow_phones` | boolean | No | Allow calls to phone numbers (default: `true`). |
| `allow_apps` | boolean | No | Allow calls to apps (default: `true`). |
| `sub_account` | string | No | Sub-account `auth_id` (if creating for sub-account). |

## Response

On success, returns `"created"` in the message field along with the `endpoint_id`, `sip_uri`, and `resource_uri`.

<CodeGroup>
  ```json Response - 201 Created theme={null}
  {
    "api_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "created",
    "endpoint_id": "87654321",
    "sip_uri": "sip:john_doe@registrar.vobiz.ai",
    "resource_uri": "/v1/Account/{auth_id}/Endpoint/87654321/"
  }
  ```

  ```json Error Response - 400 Bad Request theme={null}
  {
    "error": "invalid request parameters",
    "details": {
      "username": "Only alphanumeric characters are allowed",
      "password": "Password must be at least 8 characters"
    }
  }
  ```

  ```json Error Response - 409 Conflict theme={null}
  {
    "error": "username already exists",
    "username": "john_doe"
  }
  ```
</CodeGroup>

A `400` is returned for invalid field values (non-alphanumeric username, short password, missing required field); a `409` when the `username` is already taken on your account.

## Examples

### Basic Endpoint Creation

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "sales_desk",
    "password": "VerySecurePass123!",
    "alias": "Sales Team Desk Phone",
    "allow_voice": true
  }'
```

### Create with Application and Permissions

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john_doe",
    "password": "SecurePassword123!",
    "alias": "John'\''s Desktop Phone",
    "application": 12345678,
    "allow_voice": true,
    "allow_message": true,
    "allow_video": false,
    "allow_same_domain": true,
    "allow_other_domains": false,
    "allow_phones": true,
    "allow_apps": true
  }'
```

<Tip>
  **Best Practices:**

  * Use strong passwords (minimum 8 characters, mix of letters/numbers/symbols)
  * Use descriptive aliases to easily identify endpoints
  * Store the `endpoint_id` and `sip_uri` securely for future operations
  * Only enable permissions your endpoints actually need
  * Attach applications for automatic call routing
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Endpoint/
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
  /api/v1/Account/{auth_id}/Endpoint/:
    post:
      tags:
        - Endpoints
      summary: Create an Endpoint
      description: |
        Create a new SIP endpoint that can be used to make and receive calls
        through IP phones, softphones, or SIP clients. Each endpoint is
        assigned a unique SIP URI and endpoint ID.
      operationId: create-endpoint
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
                alias:
                  type: string
                application:
                  type: integer
              required:
                - username
                - password
                - alias
                - application
            example:
              username: john_doe
              password: SecurePassword123!
              alias: John's Desktop Phone
              application: 12345678
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  alias:
                    type: string
                  endpoint_id:
                    type: string
                  username:
                    type: string
                required:
                  - alias
                  - endpoint_id
                  - username
              example:
                alias: Acme Desktop Phone
                endpoint_id: '193962768711692'
                username: acme_sip_user_01
        '201':
          description: Endpoint created
          content:
            application/json:
              example:
                alias: Acme Desktop Phone
                endpoint_id: '193962768711692'
                username: acme_sip_user_01
        '400':
          description: Invalid request parameters
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