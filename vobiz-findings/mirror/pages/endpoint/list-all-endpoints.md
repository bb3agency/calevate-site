> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List all endpoints

> Retrieve all SIP endpoints on your Vobiz account with pagination - filter by username or alias, check registration status, and audit application assignments.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/
```

Returns a paginated list of all endpoints configured in your account. The response includes complete details for each endpoint, including registration status and attached applications.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Query Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `limit` | integer | No | Number of results per page (max 100, default: 20). |
| `offset` | integer | No | Number of results to skip (default: 0). |
| `username__contains` | string | No | Filter by username (partial match). |
| `username__exact` | string | No | Filter by exact username. |
| `username__startswith` | string | No | Filter by username prefix. |
| `alias__contains` | string | No | Filter by alias (partial match). |
| `alias__exact` | string | No | Filter by exact alias. |
| `application_id__exact` | integer | No | Filter by application ID. |
| `application_id__isnull` | boolean | No | Filter endpoints without application. |
| `sub_account` | string | No | Filter by sub-account `auth_id`. |

## Response

Returns a dictionary with an `objects` array of Endpoint objects and a `meta` object with pagination information.

```json Response - 200 OK theme={null}
{
  "api_id": "550e8400-e29b-41d4-a716-446655440000",
  "meta": {
    "limit": 20,
    "offset": 0,
    "total_count": 45,
    "next": null,
    "previous": null
  },
  "objects": [
    {
      "endpoint_id": "87654321",
      "username": "john_doe",
      "alias": "John's Desktop Phone",
      "sip_uri": "sip:john_doe@registrar.vobiz.ai",
      "sip_registered": "true",
      "sip_contact": "192.168.1.100:5060",
      "sip_expires": "2025-10-28T11:30:00Z",
      "sip_user_agent": "Zoiper v5.4.5",
      "application": {
        "app_id": "12345678",
        "app_name": "Customer Service App"
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
    },
    {
      "endpoint_id": "87654322",
      "username": "jane_smith",
      "alias": "Jane's Mobile",
      "sip_uri": "sip:jane_smith@registrar.vobiz.ai",
      "sip_registered": "false",
      "sip_contact": null,
      "sip_expires": null,
      "sip_user_agent": null,
      "application": null,
      "allow_voice": true,
      "allow_message": true,
      "allow_video": true,
      "allow_same_domain": true,
      "allow_other_domains": false,
      "allow_phones": true,
      "allow_apps": true,
      "sub_account": null,
      "resource_uri": "/v1/Account/{auth_id}/Endpoint/87654322/",
      "created_at": "2025-10-26T14:20:00Z",
      "updated_at": "2025-10-26T14:20:00Z"
    }
  ]
}
```

<Info>
  **Note:** The response includes both registered and unregistered endpoints. Registered endpoints have `sip_contact`, `sip_expires`, and `sip_user_agent` populated, while unregistered endpoints have these fields set to `null`.
</Info>

## Examples

### cURL - List All Endpoints

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/?limit=20&offset=0" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

### cURL - Filter by Username

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/?username__contains=john" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

### Build Endpoint Dashboard

```javascript JavaScript Example theme={null}
async function getEndpointDashboard() {
  const response = await fetch(
    'https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/',
    {
       headers: {
         'X-Auth-ID': '{auth_id}',
         'X-Auth-Token': '{access_token}'
       }
     }
  );

  const data = await response.json();

  const dashboard = {
    total: data.meta.total_count,
    registered: data.objects.filter(ep => ep.sip_registered === 'true').length,
    unregistered: data.objects.filter(ep => ep.sip_registered === 'false').length,
    endpoints: data.objects.map(ep => ({
      id: ep.endpoint_id,
      alias: ep.alias,
      username: ep.username,
      registered: ep.sip_registered === 'true',
      expires: ep.sip_expires || null
    }))
  };

  return dashboard;
}

getEndpointDashboard().then(console.log);
```

<Tip>
  **Use Cases:**

  * Build endpoint management dashboards
  * Monitor registration status across all endpoints
  * Audit endpoint configurations and attached applications
  * Identify unregistered endpoints for troubleshooting
  * Filter endpoints by username or alias for quick searches
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Endpoint/
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
    get:
      tags:
        - Endpoints
      summary: List All Endpoints
      description: Retrieve a paginated list of all SIP endpoints in your account.
      operationId: list-endpoints
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
            maximum: 100
        - name: offset
          in: query
          schema:
            type: integer
            default: 0
        - name: username__contains
          in: query
          schema:
            type: string
        - name: username__exact
          in: query
          schema:
            type: string
        - name: username__startswith
          in: query
          schema:
            type: string
        - name: alias__contains
          in: query
          schema:
            type: string
        - name: alias__exact
          in: query
          schema:
            type: string
        - name: application_id__exact
          in: query
          schema:
            type: integer
        - name: application_id__isnull
          in: query
          schema:
            type: boolean
        - name: sub_account
          in: query
          schema:
            type: string
      responses:
        '200':
          description: List of endpoints
          content:
            application/json:
              example:
                api_id: aabbccdd-1234-5678-90ab-cdef12345678
                meta:
                  limit: 20
                  offset: 0
                  total_count: 4
                  next: null
                  previous: null
                objects:
                  - alias: Acme Desktop Phone
                    application: /v1/Account/MA_XXXXXXXX/Application/12345678901234567/
                    endpoint_id: '147322537258167'
                    resource_uri: /v1/Account/MA_XXXXXXXX/Endpoint/147322537258167/
                    sip_registered: 'false'
                    sip_uri: sip:acme_sip_user_01@registrar.vobiz.ai
                    sub_account: null
                    username: acme_sip_user_01
                  - alias: SIP Demo Phone
                    application: null
                    endpoint_id: '125649946800674'
                    resource_uri: /v1/Account/MA_XXXXXXXX/Endpoint/125649946800674/
                    sip_registered: 'false'
                    sip_uri: sip:sipuser_demo@registrar.vobiz.ai
                    sub_account: null
                    username: sipuser_demo
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                  meta:
                    type: object
                    properties:
                      limit:
                        type: integer
                      offset:
                        type: integer
                      total_count:
                        type: integer
                      next:
                        nullable: true
                      previous:
                        nullable: true
                    required:
                      - limit
                      - offset
                      - total_count
                      - next
                      - previous
                  objects:
                    type: array
                    items:
                      type: object
                      properties:
                        alias:
                          type: string
                        application:
                          type: string
                          nullable: true
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
                required:
                  - api_id
                  - meta
                  - objects
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