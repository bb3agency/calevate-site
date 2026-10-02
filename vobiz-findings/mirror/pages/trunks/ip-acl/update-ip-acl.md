> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update IP ACL

> Modify a Vobiz IP ACL entry to update the whitelisted IPv4 address, toggle its enabled state, or edit the description - all with a single PUT request.

```http theme={null}
PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl/{ip_acl_id}
```

Updates an existing IP ACL entry. You can change the whitelisted IP address, modify the description, or enable/disable the entry. All fields are optional - include only the fields you want to update.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Full update.** Send both `name` and `ip_address` on every update - this is a replace, not a partial patch. To preserve the label or address, resend its current value.
</Info>

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | Yes | Label for the entry. Surfaces as `description` on the returned object. |
| `ip_address` | string | Yes | IPv4 address or CIDR range (e.g., `192.168.1.200` or `10.40.50.0/24`). |

<Note>
  **Disable without deleting.** The update body accepts only `name` and `ip_address`. To toggle an entry's `enabled` state, use the Console (or delete and recreate the entry). If you only need to temporarily stop traffic, removing the entry and re-adding it later is the documented API path.
</Note>

## Response

Returns the complete IP ACL object with updated values and a new `updated_at` timestamp.

```json Response - 200 OK theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "ip_address": "192.168.1.200",
  "description": "Office static IP",
  "enabled": true,
  "created_at": "2026-05-12T05:11:51Z",
  "updated_at": "2026-05-12T05:12:30Z"
}
```

## Examples

### cURL - Update the IP address

```bash cURL Request theme={null}
curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl/c1d2e3f4-a5b6-7890-cdef-1234567890ab \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Office static IP",
    "ip_address": "192.168.1.200"
  }'
```

### cURL - Rename the entry (resend the IP)

```bash cURL Request theme={null}
curl -X PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl/c1d2e3f4-a5b6-7890-cdef-1234567890ab \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Main office - Building A",
    "ip_address": "192.168.1.200"
  }'
```

<Warning>
  **IP Address Changes:** If you update the IP address, existing authenticated connections may be disconnected. Plan IP changes during maintenance windows.
</Warning>

<Info>
  **Error Response (400 Bad Request):** If the new IP address format is invalid:

  ```json Error Response - 400 Bad Request theme={null}
  {
    "error": "Invalid IP address format",
    "code": 400
  }
  ```
</Info>

<Tip>
  **Best Practice:** When migrating to a new IP, add the new entry first with [Create IP ACL](/docs/trunks/ip-acl/create-ip-acl), test connectivity from it, then delete the old entry to avoid service interruption.
</Tip>


## OpenAPI

````yaml PUT /api/v1/Account/{auth_id}/ip-acl/{ip_acl_id}
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
    put:
      tags:
        - IP Access Control List
      summary: Update an IP ACL
      description: Update an existing IP access control rule.
      operationId: update-ip-acl
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: ip_acl_id
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
                name:
                  type: string
                ip_address:
                  type: string
              required:
                - name
                - ip_address
      responses:
        '200':
          description: IP ACL updated
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  account_id:
                    type: string
                  ip_address:
                    type: string
                  description:
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
                  - ip_address
                  - description
                  - enabled
                  - created_at
                  - updated_at
              example:
                id: aabbccdd-1234-5678-90ab-cdef12345678
                account_id: MA_XXXXXXXX
                ip_address: 192.168.1.0/24
                description: Datacenter ACL
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