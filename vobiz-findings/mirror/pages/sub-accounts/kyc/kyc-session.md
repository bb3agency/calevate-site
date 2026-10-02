> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create KYC Session

> Hand off sub-account KYC to a Vobiz-hosted widget - either email the customer a signed link or redirect them inline. The sub-account-scoped equivalent of the partner KYC Sessions endpoint.

Creates a Vobiz-hosted KYC session for the sub-account. Instead of driving each verification step yourself, you hand the customer off to the Vobiz-hosted KYC widget.

<Info>
  Authenticate with your **parent main account's** `X-Auth-ID` and `X-Auth-Token` - the same credentials used everywhere else in the API.
</Info>

## Flow types

| `flow_type` | Behavior | Required field |
| - | - | - |
| `email` *(default)* | Vobiz emails the customer a signed link (from `kyc@vobiz.ai`, hosted at `kyc.vobiz.ai`). The session sits in `email_sent` until they open it. | `customer_email` |
| `redirect` | The response returns a `widget_url` directly - redirect the customer's browser to it. No email is sent. | `redirect_url` |

## Body fields

| Field | Type | Required | Description |
| - | - | - | - |
| `account_auth_id` | string | Yes | The sub-account's `auth_id` (`SA_…`), normally equal to the `{sub_auth_id}` in the path. |
| `flow_type` | string | Yes | `email` (default) or `redirect`. |
| `customer_email` | string | Conditional | Required when `flow_type` is `email`. Where the signed link is sent. |
| `redirect_url` | string (URI) | Conditional | Required when `flow_type` is `redirect`. The customer is returned here after verification. |
| `webhook_url` | string (URI) | No | HTTPS endpoint Vobiz POSTs the KYC result to. Omit it and no callbacks are sent. |
| `expires_in_days` | integer | No | Days before the link expires. Defaults to `7`. |

<Note>
  This is the sub-account–scoped equivalent of the partner-level [KYC Sessions](/docs/partner/api/kyc-sessions) endpoint. For session lifecycle, webhook events, and the `verified_data` shape, see that page - the hosted widget and status model are the same. The partner endpoint additionally accepts `reminder_schedule` and `metadata`; see the [email](/docs/sub-accounts/kyc/email-flow-webhook) and [redirect](/docs/sub-accounts/kyc/redirect-flow-webhook) flow walkthroughs for how those carry through to webhook payloads.
</Note>

## Responses

<CodeGroup>
  ```json Email flow (201) theme={null}
  {
    "session_id": "a5f8da3c-b47f-40c3-a3e6-d2c9a0f27065",
    "account_auth_id": "SA_XXXXXX",
    "customer_email": "customer@example.com",
    "status": "email_sent",
    "expires_at": "2026-06-24T19:37:01.316686Z",
    "widget_url": null,
    "message": "KYC email dispatched successfully"
  }
  ```

  ```json Redirect flow (201) theme={null}
  {
    "session_id": "1a0f7da5-2abb-47bf-a6c3-eb5cff7feda5",
    "account_auth_id": "SA_XXXXXX",
    "customer_email": null,
    "status": "link_ready",
    "expires_at": "2026-06-24T19:37:01.841263Z",
    "widget_url": "https://kyc.vobiz.ai/verify?token=kst_cb1b3fda...",
    "message": "Redirect your customer to widget_url to begin."
  }
  ```
</CodeGroup>

A `422` is returned when the email flow is missing `customer_email`, or the redirect flow is missing `redirect_url`.


## OpenAPI

````yaml POST /api/v1/sub-accounts/{sub_auth_id}/kyc-sessions
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
  /api/v1/sub-accounts/{sub_auth_id}/kyc-sessions:
    post:
      tags:
        - Sub-Account KYC
      summary: Create a hosted KYC session
      description: |
        Creates a Vobiz-hosted KYC session for the sub-account. With
        `flow_type=email` (default) Vobiz emails the customer a signed link
        (from `kyc@vobiz.ai`, hosted at `kyc.vobiz.ai`) and `customer_email` is
        required. With `flow_type=redirect`, omit `customer_email`, pass a
        `redirect_url`, and the `widget_url` is returned directly for an inline
        redirect.

        This is the sub-account–scoped equivalent of the partner-level
        [KYC Sessions](/partner/api/kyc-sessions) endpoint.
      operationId: create-subaccount-kyc-session
      parameters:
        - $ref: '#/components/parameters/SubAuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - account_auth_id
                - flow_type
              properties:
                account_auth_id:
                  type: string
                  description: >-
                    The sub-account's auth_id (typically equal to the path
                    `sub_auth_id`).
                  example: SA_XXXXXX
                flow_type:
                  type: string
                  enum:
                    - email
                    - redirect
                  default: email
                customer_email:
                  type: string
                  format: email
                  description: Required when `flow_type` is `email`.
                  example: customer@example.com
                redirect_url:
                  type: string
                  format: uri
                  description: >
                    Required when `flow_type` is `redirect`. After verification
                    the customer's

                    browser is sent to this URL.
                  example: https://your-app.example.com/kyc/done
                webhook_url:
                  type: string
                  format: uri
                  description: >-
                    HTTPS endpoint VoBiz POSTs the KYC result to. Omit it and no
                    callbacks are sent.
                  example: https://your-app.example.com/kyc/webhook
                expires_in_days:
                  type: integer
                  default: 7
                  example: 30
            examples:
              email-flow:
                summary: Email flow (Vobiz emails the link)
                value:
                  account_auth_id: SA_XXXXXX
                  flow_type: email
                  customer_email: customer@example.com
                  webhook_url: https://your-app.example.com/kyc/webhook
                  expires_in_days: 30
              redirect-flow:
                summary: Redirect flow (you redirect to widget_url)
                value:
                  account_auth_id: SA_XXXXXX
                  flow_type: redirect
                  redirect_url: https://your-app.example.com/kyc/done
                  webhook_url: https://your-app.example.com/kyc/webhook
                  expires_in_days: 30
      responses:
        '201':
          description: KYC session created
          content:
            application/json:
              examples:
                email-flow:
                  summary: Email-flow response
                  value:
                    session_id: a5f8da3c-b47f-40c3-a3e6-d2c9a0f27065
                    account_auth_id: SA_XXXXXX
                    customer_email: customer@example.com
                    status: email_sent
                    expires_at: '2026-06-24T19:37:01.316686Z'
                    widget_url: null
                    message: KYC email dispatched successfully
                redirect-flow:
                  summary: Redirect-flow response
                  value:
                    session_id: 1a0f7da5-2abb-47bf-a6c3-eb5cff7feda5
                    account_auth_id: SA_XXXXXX
                    customer_email: null
                    status: link_ready
                    expires_at: '2026-06-24T19:37:01.841263Z'
                    widget_url: https://kyc.vobiz.ai/verify?token=kst_cb1b3fda...
                    message: Redirect your customer to widget_url to begin.
        '422':
          description: >-
            Validation error (email flow missing `customer_email`, or redirect
            flow missing `redirect_url`)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  parameters:
    SubAuthId:
      name: sub_auth_id
      in: path
      required: true
      description: The sub-account's Auth ID.
      schema:
        type: string
        example: SA_XXXXXX
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