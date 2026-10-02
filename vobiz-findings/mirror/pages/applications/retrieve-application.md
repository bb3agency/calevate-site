> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve an Application

> Retrieve a single Vobiz voice application by app_id - inspect its webhook URLs, HTTP methods, fallback configuration, and current number assignments.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/{app_id}/
```

Returns full details of a specific application. Pass the `app_id` as a path parameter.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Arguments

No request parameters needed.

## Response Examples

<CodeGroup>
  ```json Success Response (200 OK) theme={null}
  {
    "answer_method": "GET",
    "answer_url": "https://example.com/answer",
    "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
    "app_id": "12345678901234567",
    "app_name": "My Voice App",
    "application_type": "XML",
    "created_at": "2026-04-02 12:11:19.740666+00:00",
    "default_app": true,
    "default_endpoint_app": false,
    "enabled": true,
    "fallback_answer_url": null,
    "fallback_method": "POST",
    "hangup_method": "POST",
    "hangup_url": "https://example.com/answer",
    "log_incoming_message": true,
    "message_method": "POST",
    "message_url": null,
    "public_uri": false,
    "resource_uri": "/v1/Account/MA_XXXXXXXX/Application/12345678901234567/",
    "sip_transfer_method": "POST",
    "sip_transfer_url": null,
    "sip_uri": "sip:12345678901234567@app.vobiz.ai",
    "sub_account": null,
    "updated_at": "2026-04-02 12:11:19.740666+00:00"
  }
  ```

  ```json Error Response (404 Not Found) theme={null}
  {
    "error": "Application not found",
    "app_id": "12345678901234567"
  }
  ```
</CodeGroup>

### cURL Example

```bash cURL theme={null}
curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/12345678901234567/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Application/{app_id}/
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
    get:
      tags:
        - Applications
      summary: Retrieve an Application
      description: Get details of a particular application by passing the app_id.
      operationId: retrieve-application
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: app_id
          in: path
          required: true
          description: Unique identifier for the application
          schema:
            type: string
            example: '12345678'
      responses:
        '200':
          description: Application details
          content:
            application/json:
              schema:
                type: object
                properties:
                  answer_method:
                    type: string
                  answer_url:
                    type: string
                  api_id:
                    type: string
                  app_id:
                    type: string
                  app_name:
                    type: string
                  application_type:
                    type: string
                  created_at:
                    type: string
                  default_app:
                    type: boolean
                  default_endpoint_app:
                    type: boolean
                  enabled:
                    type: boolean
                  fallback_answer_url:
                    nullable: true
                  fallback_method:
                    type: string
                  hangup_method:
                    type: string
                  hangup_url:
                    type: string
                  log_incoming_message:
                    type: boolean
                  message_method:
                    type: string
                  message_url:
                    nullable: true
                  public_uri:
                    type: boolean
                  resource_uri:
                    type: string
                  sip_transfer_method:
                    type: string
                  sip_transfer_url:
                    nullable: true
                  sip_uri:
                    type: string
                  sub_account:
                    nullable: true
                  updated_at:
                    type: string
                required:
                  - answer_method
                  - answer_url
                  - api_id
                  - app_id
                  - app_name
                  - application_type
                  - created_at
                  - default_app
                  - default_endpoint_app
                  - enabled
                  - fallback_answer_url
                  - fallback_method
                  - hangup_method
                  - hangup_url
                  - log_incoming_message
                  - message_method
                  - message_url
                  - public_uri
                  - resource_uri
                  - sip_transfer_method
                  - sip_transfer_url
                  - sip_uri
                  - sub_account
                  - updated_at
              example:
                answer_method: GET
                answer_url: https://example.com/answer
                api_id: aabbccdd-1234-5678-90ab-cdef12345678
                app_id: '12345678901234567'
                app_name: My Voice App
                application_type: XML
                created_at: '2026-03-25 10:00:00.000000+00:00'
                default_app: true
                default_endpoint_app: false
                enabled: true
                fallback_answer_url: null
                fallback_method: POST
                hangup_method: POST
                hangup_url: https://example.com/hangup
                log_incoming_message: true
                message_method: POST
                message_url: null
                public_uri: false
                resource_uri: /v1/Account/MA_XXXXXXXX/Application/12345678901234567/
                sip_transfer_method: POST
                sip_transfer_url: null
                sip_uri: sip:12345678901234567@app.vobiz.ai
                sub_account: null
                updated_at: '2026-03-25 10:00:00.000000+00:00'
        '404':
          description: Application not found
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