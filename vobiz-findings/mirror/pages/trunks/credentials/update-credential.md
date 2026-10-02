> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Credential

> Rotate the password, toggle the enabled state, or update the description of a Vobiz SIP credential without interrupting other active trunk authentications.

```http theme={null}
PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials/{credential_id}
```

Updates an existing credential's password, enabled status, or description. Use this endpoint to rotate passwords, enable or disable credentials, or update descriptive information.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Important Limitation:** The username cannot be changed after credential creation. To use a different username, create a new credential and delete the old one.

  **Security Note:** When updating the password, ensure it meets minimum security requirements (8+ characters). The new password is not returned in the response.
</Warning>

## Request Parameters

All parameters are optional. Include only the fields you want to update.

| Field | Type | Required | Description |
| - | - | - | - |
| `password` | string | No | New SIP password. Minimum 8 characters. Recommended: 12+ characters with mixed case, numbers, and special characters. |
| `enabled` | boolean | No | Whether the credential is active. Set to `false` to temporarily disable authentication without deleting the credential. Set to `true` to re-enable. |
| `description` | string | No | Updated description for the credential (e.g., "Rotated password on 2025-01-22" or "Assigned to new device"). |

<Warning>
  **Note:** The `username` field cannot be updated. It is immutable after credential creation.
</Warning>

## Response

Returns the updated credential object. The password is not included in the response. The `updated_at` timestamp reflects when the change was made.

```json Response - 200 OK theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "username": "sipuser_demo",
  "password": "<redacted>",
  "realm": "MA_XXXXXXXX.sip.vobiz.ai",
  "enabled": true,
  "created_at": "2026-05-12T05:11:51.635107Z",
  "updated_at": "2026-05-12T05:11:51.683393Z"
}
```

## Examples

### cURL - Update Password

```bash cURL Request theme={null}
curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "password": "UpdatedSecurePassword456!",
    "description": "Password rotated on 2025-01-22"
  }'
```

### cURL - Disable Credential

```bash cURL Request theme={null}
curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": false,
    "description": "Temporarily disabled for maintenance"
  }'
```

### cURL - Re-enable Credential

```bash cURL Request theme={null}
curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/credentials/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "description": "Re-enabled after maintenance"
  }'
```

<Info>
  **Best Practices:**

  * Rotate passwords quarterly or when a device is compromised
  * Use the `enabled` flag to disable credentials temporarily instead of deleting them
  * Update the description when making changes to document the reason
  * Notify affected users before changing passwords to prevent service disruption
</Info>

<Note>
  **Error Response (404):** If the `credential_id` does not exist or does not belong to the specified trunk, the API returns a 404 Not Found error.
</Note>


## OpenAPI

````yaml PUT /api/v1/Account/{auth_id}/credentials/{credential_id}
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
    put:
      tags:
        - Credentials
      summary: Update a credential
      description: Update the password for an existing SIP credential.
      operationId: update-credential
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: credential_id
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                password:
                  type: string
              required:
                - password
      responses:
        '200':
          description: Credential updated
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
                updated_at: '2026-03-25T11:30:00Z'
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