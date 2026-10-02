> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve an Endpoint

> Fetch a Vobiz SIP endpoint by ID - returns live registration status, SIP contact, expiry, user agent string, and attached application details for call routing.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/{endpoint_id}/
```

Retrieves the details of an existing endpoint. The response includes all endpoint attributes and, if the endpoint is currently registered on a SIP client, additional registration details.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Note>
  No request parameters are required for this endpoint.
</Note>

## Response

Returns an Endpoint object for valid parameters, or an error otherwise.

### Success Response (200 OK)

```json Response - 200 OK theme={null}
{
  "api_id": "550e8400-e29b-41d4-a716-446655440000",
  "endpoint_id": "87654321",
  "username": "john_doe",
  "alias": "John's Desktop Phone",
  "sip_uri": "sip:john_doe@registrar.vobiz.ai",
  "sip_registered": "true",
  "sip_registration": {
    "contact": "192.168.1.100:5060",
    "expires": "2025-10-28T11:30:00Z",
    "user_agent": "Zoiper v5.4.5",
    "received": "203.0.113.42:5060",
    "path": null
  },
  "application": {
    "app_id": "12345678",
    "app_name": "Customer Service App",
    "answer_url": "https://example.com/answer",
    "answer_method": "POST"
  },
  "allow_voice": true,
  "allow_message": true,
  "allow_video": false,
  "allow_same_domain": true,
  "allow_other_domains": false,
  "allow_phones": true,
  "allow_apps": true,
  "sub_account": null,
  "resource_uri": "/v1/Account/{auth_id}/Endpoint/87654321/",
  "created_at": "2025-10-27T10:30:00Z",
  "updated_at": "2025-10-28T09:15:00Z"
}
```

<Note>
  **Registration Details:** The `sip_registration` object contains detailed information about the endpoint's current SIP registration including contact address, expiration time, user agent, and received address. This object is only present when `sip_registered` is `"true"`.
</Note>

### Error Response (404 Not Found)

```json Response - 404 Not Found theme={null}
{
  "error": "Endpoint not found",
  "endpoint_id": "99999999"
}
```

## Examples

### cURL

```bash cURL Request theme={null}
curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/87654321/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Tip>
  **Use Cases:**

  * Verify endpoint registration status before making calls
  * Check which application is attached to an endpoint
  * Monitor SIP client registration expiration times
  * Retrieve SIP URI for sharing with external users
  * View detailed permission settings for an endpoint
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Endpoint/{endpoint_id}/
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
    get:
      tags:
        - Endpoints
      summary: Retrieve an Endpoint
      description: |
        Retrieve the details of an existing endpoint. The response includes
        all endpoint attributes and, if the endpoint is currently registered
        on a SIP client, additional registration details.
      operationId: retrieve-endpoint
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
          description: Endpoint details
          content:
            application/json:
              schema:
                type: object
                properties:
                  alias:
                    type: string
                  application:
                    type: string
                  endpoint_id:
                    type: string
                  resource_uri:
                    type: string
                  sip_registered:
                    type: string
                  sip_uri:
                    type: string
                  sub_account:
                    nullable: true
                  username:
                    type: string
                required:
                  - alias
                  - application
                  - endpoint_id
                  - resource_uri
                  - sip_registered
                  - sip_uri
                  - sub_account
                  - username
              example:
                alias: Acme Desktop Phone
                application: /v1/Account/MA_XXXXXXXX/Application/12345678901234567/
                endpoint_id: '147322537258167'
                resource_uri: /v1/Account/MA_XXXXXXXX/Endpoint/147322537258167/
                sip_registered: 'false'
                sip_uri: sip:acme_sip_user_01@registrar.vobiz.ai
                sub_account: null
                username: acme_sip_user_01
        '404':
          description: Endpoint not found
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