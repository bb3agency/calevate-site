> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create an Application

> Create a Vobiz voice application by registering your answer_url and hangup_url webhooks - the first step to handling inbound calls and messages programmatically.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/
```

Creates an application with webhook URLs for call handling. Creating an application is typically the first step - you then attach it to either a number or an endpoint.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Parameters

The three required fields are `app_name`, `answer_url`, and `answer_method`.

| Field | Type | Required | Description |
| - | - | - | - |
| `app_name` | string | Yes | The name of your application. Allowed values: letters (upper and lower case), numbers (0–9), and only two special characters: `-` (hyphen) and `_` (underscore). |
| `answer_url` | string | Yes | The URL fetched when a call executes this application. Must return valid VobizXML. |
| `answer_method` | string | Yes | HTTP method used to call `answer_url`. One of `GET` or `POST`. Defaults to `POST`. |
| `hangup_url` | string | No | URL notified when the call hangs up. If omitted, defaults to `answer_url` - your answer handler then also receives hangup callbacks. |
| `hangup_method` | string | No | HTTP method used to call `hangup_url`. One of `GET` or `POST`. Defaults to `POST`. |
| `fallback_answer_url` | string | No | Invoked by Vobiz only if `answer_url` is unreachable, times out, or returns invalid VobizXML. Must itself return valid VobizXML. With no fallback set, the call drops on `answer_url` failure. |
| `fallback_method` | string | No | HTTP method used to call `fallback_answer_url`. One of `GET` or `POST`. Defaults to `POST`. |
| `message_url` | string | No | URL notified when an inbound message is received. Not set by default. |
| `message_method` | string | No | HTTP method used to call `message_url`. One of `GET` or `POST`. Defaults to `POST`. |
| `default_number_app` | boolean | No | If `true`, newly created numbers without an `app_id` are routed to this application. Defaults to `false`. Does not retroactively re-route existing numbers. |
| `default_endpoint_app` | boolean | No | If `true`, newly created endpoints without an `application` are routed to this application. Defaults to `false`. Does not retroactively re-route existing endpoints. |
| `sub_account` | string | No | `auth_id` of the sub-account this application belongs to. Cannot be changed after creation. |
| `application_type` | string | No | The type of application. Typically `XML`. |
| `default_app` | boolean | No | Whether this is the account-level default application. Defaults to `false`. |
| `enabled` | boolean | No | Whether the application is enabled. Defaults to `true`. |
| `log_incoming_message` | boolean | No | If `false`, incoming messages to Vobiz phone numbers associated with this application are not logged. Defaults to `true`. |
| `public_uri` | boolean | No | Whether the application's `sip_uri` is reachable by external SIP systems. Defaults to `false`. |
| `sip_transfer_method` | string | No | HTTP method used for SIP transfer callbacks. One of `GET` or `POST`. |
| `sip_transfer_url` | string | No | URL notified during a SIP transfer. |
| `sip_uri` | string | No | SIP URI associated with the application. |

<Note>
  Creating an application is normally step one. After it returns an `app_id`, [attach a number](/docs/applications/attach-number) or set `application` on an [endpoint](/docs/endpoint/create-endpoint) to start routing calls.
</Note>

## Request Body

```json JSON theme={null}
{
  "app_name": "My Voice App",
  "answer_url": "https://example.com/answer",
  "answer_method": "POST",
  "hangup_url": "https://example.com/hangup",
  "hangup_method": "POST",
  "fallback_answer_url": "https://example.com/fallback",
  "fallback_method": "POST",
  "message_url": "https://example.com/message",
  "message_method": "POST",
  "default_number_app": false,
  "default_endpoint_app": false,
  "sub_account": null
}
```

## Response Examples

<CodeGroup>
  ```json Success Response (201 Created) theme={null}
  {
    "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
    "app_id": "12345678901234567",
    "message": "created"
  }
  ```

  ```json Error Response (400 Bad Request) theme={null}
  {
    "error": "invalid request parameters",
    "details": {
      "app_name": "This field is required",
      "answer_url": "Enter a valid URL"
    }
  }
  ```

  ```json Error Response (401 Unauthorized) theme={null}
  {
    "error": "invalid credentials"
  }
  ```
</CodeGroup>

A `400` is returned when a required field is missing or a URL is malformed; a `401` when `X-Auth-ID`/`X-Auth-Token` are missing or wrong.

### cURL Example

```bash cURL theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "My IVR System",
    "answer_url": "https://myapp.com/ivr/answer",
    "answer_method": "POST"
  }'
```


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Application/
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
  /api/v1/Account/{auth_id}/Application/:
    post:
      tags:
        - Applications
      summary: Create an Application
      description: |
        Creates an Application with webhook URLs for call handling.
        Creating an application is usually a first step, after which you
        attach the application to either a number or an endpoint.
      operationId: create-application
      parameters:
        - $ref: '#/components/parameters/AuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                app_name:
                  type: string
                answer_url:
                  type: string
                answer_method:
                  type: string
              required:
                - app_name
                - answer_url
                - answer_method
            example:
              app_name: My Voice Application
              answer_url: https://example.com/answer
              answer_method: POST
              hangup_url: https://example.com/hangup
              hangup_method: POST
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                  app_id:
                    type: string
                  message:
                    type: string
                required:
                  - api_id
                  - app_id
                  - message
              example:
                api_id: aabbccdd-1234-5678-90ab-cdef12345678
                app_id: '12345678901234567'
                message: created
        '201':
          description: Application created
          content:
            application/json:
              example:
                api_id: aabbccdd-1234-5678-90ab-cdef12345678
                app_id: '12345678901234567'
                message: created
        '400':
          description: Invalid request parameters
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Invalid credentials
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