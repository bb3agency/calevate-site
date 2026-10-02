> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create IP ACL

> Add an IPv4 address to your Vobiz SIP trunk allowlist so PBX systems, SBCs, or carriers authenticate calls without SIP digest credentials - 130+ countries.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl
```

Creates a new IP ACL entry to whitelist an IPv4 address or CIDR range for authentication on the account. Once added, calls originating from the whitelisted address are allowed without requiring credential authentication (unless both authentication methods are required).

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | Yes | Label for the entry, such as "Office static IP", "PBX server", or "Carrier connection". Surfaces as `description` on the returned object. |
| `ip_address` | string | Yes | A single IPv4 address (e.g., `198.51.100.42`) or an IPv4 CIDR block (e.g., `10.20.30.0/24`). |

<Note>
  **CIDR is supported.** Whitelist a whole range with CIDR notation (e.g., `10.20.30.0/24`) or a single host. The entry is created `enabled: true`; to disable it later or change the IP, use [Update IP ACL](/docs/trunks/ip-acl/update-ip-acl).
</Note>

<Warning>
  **IPv4 only.** IPv6 addresses are not supported and are rejected. Whitelist your **public** IP or range - if you are behind NAT, use the router's public IP. The API also rejects RFC 5737 documentation prefixes (such as `203.0.113.0/24`); use a real or RFC 1918 (`10.0.0.0/24`) range.
</Warning>

## Response

Returns the complete IP ACL object, including the auto-generated `id` UUID and timestamps.

```json Response - 201 Created theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "ip_address": "10.20.30.0/24",
  "description": "FreePBX server in data center",
  "enabled": true,
  "created_at": "2026-05-12T05:11:51Z",
  "updated_at": "2026-05-12T05:11:51Z"
}
```

## Examples

### cURL - Basic IP ACL

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Office static IP",
    "ip_address": "198.51.100.42"
  }'
```

### cURL - PBX Server IP

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/ip-acl \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "FreePBX server in data center",
    "ip_address": "10.20.30.0/24"
  }'
```

<Info>
  **Error Response (400 Bad Request):** If the IP address format is invalid:

  ```json Error Response - 400 Bad Request theme={null}
  {
    "error": "Invalid IP address format",
    "code": 400
  }
  ```
</Info>

<Tip>
  **Next Steps:**

  * Save the IP ACL `id` for future operations
  * Verify the IP address is correct before testing
  * Test connectivity by making a call from the whitelisted IP
  * Monitor authentication logs to confirm IP-based auth is working
</Tip>

<Note>
  **NAT Tip:** If you are behind NAT or a firewall, determine your public IP with: `curl https://api.ipify.org`
</Note>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/ip-acl
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
  /api/v1/Account/{auth_id}/ip-acl:
    post:
      tags:
        - IP Access Control List
      summary: Create an IP ACL
      description: Add an IP access control rule to restrict SIP trunk access.
      operationId: create-ip-acl
      parameters:
        - $ref: '#/components/parameters/AuthId'
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
            example:
              name: Office IP
              cidr_ip: 203.0.113.0/24
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
                ip_address: 10.20.30.0/24
                description: ''
                enabled: true
                created_at: '2026-03-25T10:00:00Z'
                updated_at: '2026-03-25T10:00:00Z'
        '201':
          description: IP ACL created
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