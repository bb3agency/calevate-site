> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update an Application

> Update an existing Vobiz voice application - modify webhook URLs, HTTP methods, app name, or SIP URI to change how inbound calls and messages are routed.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/{app_id}/
```

Modify an application. You can update any subset of fields (partial update).

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Important Notes:**

  * Fields not provided will remain unchanged
  * `sub_account` cannot be changed after creation
</Warning>

## Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `app_name` | string | No | New name for the application. Letters, numbers, `-`, and `_` only. |
| `answer_url` | string | No | The URL invoked when a call executes this application. Must return valid VobizXML. |
| `answer_method` | string | No | HTTP method used to call `answer_url`. One of `GET` or `POST`. Defaults to `POST`. |
| `hangup_url` | string | No | URL notified when the call hangs up. |
| `hangup_method` | string | No | HTTP method used to call `hangup_url`. One of `GET` or `POST`. Defaults to `POST`. |
| `fallback_answer_url` | string | No | Invoked by Vobiz only if `answer_url` is unreachable, times out, or returns invalid VobizXML. Must itself return valid VobizXML. |
| `fallback_method` | string | No | HTTP method used to call `fallback_answer_url`. One of `GET` or `POST`. Defaults to `POST`. |
| `message_url` | string | No | URL notified by Vobiz when an inbound message is received. |
| `message_method` | string | No | HTTP method used to call `message_url`. One of `GET` or `POST`. Defaults to `POST`. |
| `default_number_app` | boolean | No | If `true`, associates all newly created Vobiz numbers without an `app_id` to this application. Does not re-route existing numbers. |
| `default_endpoint_app` | boolean | No | If `true`, associates all newly created Vobiz endpoints without an `application` to this application. Does not re-route existing endpoints. |
| `application_type` | string | No | The type of application. Typically `XML`. |
| `default_app` | boolean | No | Whether this is the account-level default application. |
| `enabled` | boolean | No | Whether the application is enabled. |
| `log_incoming_message` | boolean | No | Controls whether incoming messages to phone numbers associated with this application are logged. |
| `public_uri` | boolean | No | Whether the application's `sip_uri` is reachable by external SIP systems. |
| `sip_transfer_method` | string | No | HTTP method used for SIP transfer callbacks. One of `GET` or `POST`. |
| `sip_transfer_url` | string | No | URL notified during a SIP transfer. |
| `sip_uri` | string | No | SIP URI associated with the application. |

<Note>
  Every field is optional; send only what you want to change. `sub_account` is set at creation and cannot be modified here.
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
  "default_endpoint_app": false
}
```

## Response Examples

<CodeGroup>
  ```json Success Response (200 OK) theme={null}
  {
    "api_id": "11223344-5566-7788-99aa-bbccddeeff00",
    "message": "changed"
  }
  ```

  ```json Error Response (400 Bad Request) theme={null}
  {
    "error": "invalid request parameters",
    "details": {
      "answer_url": "Enter a valid URL"
    }
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
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/12345678901234567/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "My Voice App (renamed)",
    "default_number_app": true
  }'
```


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Application/{app_id}/
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
    post:
      tags:
        - Applications
      summary: Update an Application
      description: |
        Modify an application using this API. You can update any subset of
        fields (partial update). Fields not provided will remain unchanged.
      operationId: update-application
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: app_id
          in: path
          required: true
          schema:
            type: string
            example: '12345678'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                app_name:
                  type: string
                default_number_app:
                  type: boolean
              required:
                - app_name
                - default_number_app
            example:
              app_name: Updated Application Name
              default_number_app: true
      responses:
        '200':
          description: Application updated
          content:
            application/json:
              example:
                api_id: 11223344-5566-7788-99aa-bbccddeeff00
                message: changed
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                  message:
                    type: string
                required:
                  - api_id
                  - message
        '400':
          description: Invalid request parameters
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
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