> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Purchase CPS or concurrency capacity

> Purchase recurring Vobiz CPS or concurrent-call capacity and activate a channel subscription that renews every 30 days.

Purchase additional calls-per-second (CPS) or concurrent-call capacity for a Vobiz account.

```http theme={null}
POST https://api.vobiz.ai/api/v1/accounts/{auth_id}/channel-subscriptions
Content-Type: application/json
```

<Warning>
  A successful request immediately debits the first month's charge from the account balance. [Preview the exact price](/docs/account/channel-pricing-preview) and obtain customer confirmation before purchasing.
</Warning>

## Authentication

Use one of these authentication methods:

| Method | Headers |
| - | - |
| Account access token | `Authorization: Bearer <ACCESS_TOKEN>` |
| Account API credentials | `X-Auth-ID: <AUTH_ID>` and `X-Auth-Token: <AUTH_TOKEN>` |

The authenticated account can purchase capacity only for its own `auth_id`. An administrator may act on behalf of another account.

## Parameters

### Path parameter

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Target account Auth ID, such as `MA_XXXX`. |

### Request body

| Field | Type | Required | Description |
| - | - | - | - |
| `resource_type` | string | Yes | Capacity to purchase. Use `concurrent_calls` or `cps`. |
| `quantity` | integer | Yes | Capacity quantity. Must be from `1` through `10000`; pricing-tier block and quantity rules also apply. |

## Examples

<Tabs>
  <Tab title="Concurrent calls">
    ```bash cURL theme={null}
    curl --request POST \
      "https://api.vobiz.ai/api/v1/accounts/MA_XXXX/channel-subscriptions" \
      --header "X-Auth-ID: MA_XXXX" \
      --header "X-Auth-Token: YOUR_AUTH_TOKEN" \
      --header "Content-Type: application/json" \
      --data '{
        "resource_type": "concurrent_calls",
        "quantity": 30
      }'
    ```
  </Tab>

  <Tab title="CPS">
    ```bash cURL theme={null}
    curl --request POST \
      "https://api.vobiz.ai/api/v1/accounts/MA_XXXX/channel-subscriptions" \
      --header "X-Auth-ID: MA_XXXX" \
      --header "X-Auth-Token: YOUR_AUTH_TOKEN" \
      --header "Content-Type: application/json" \
      --data '{
        "resource_type": "cps",
        "quantity": 10
      }'
    ```
  </Tab>
</Tabs>

## Successful response

The values below are illustrative. The actual monthly cost, currency, and billing dates come from the account and its assigned pricing tier.

```json Subscription activated theme={null}
{
  "id": "5ed57f90-b1f1-4c32-9475-b85aa6739aec",
  "account_id": 123456,
  "resource_type": "concurrent_calls",
  "quantity": 30,
  "monthly_cost": "10470.00",
  "currency": "INR",
  "status": "active",
  "last_billing_date": "2026-07-16T10:00:00Z",
  "next_billing_date": "2026-08-15T10:00:00Z",
  "purchased_at": "2026-07-16T10:00:00Z",
  "cancelled_at": null,
  "cancellation_reason": null,
  "is_active": true,
  "created_at": "2026-07-16T10:00:00Z",
  "updated_at": "2026-07-16T10:00:00Z"
}
```

| Field | Type | Description |
| - | - | - |
| `id` | string | Unique subscription identifier. |
| `account_id` | integer | Internal identifier of the account that owns the subscription. |
| `resource_type` | string | Purchased capacity type. |
| `quantity` | integer | Purchased capacity quantity. |
| `monthly_cost` | string | Recurring monthly charge as a decimal string. |
| `currency` | string | Billing currency from the account's pricing tier. |
| `status` | string | Subscription status. A successful purchase is created as `active`. |
| `last_billing_date` | string | Date and time of the most recent subscription charge. |
| `next_billing_date` | string | Scheduled date and time of the next charge. |
| `purchased_at` | string | Date and time the capacity was purchased. |
| `cancelled_at` | string or null | Date and time the subscription was cancelled, if applicable. |
| `cancellation_reason` | string or null | Recorded cancellation reason, if applicable. |
| `is_active` | boolean | Whether the subscription is currently active. |
| `created_at` | string | Date and time the subscription record was created. |
| `updated_at` | string | Date and time the subscription record was last updated. |

## Billing and validation

* `resource_type` must be `concurrent_calls` or `cps`.
* `quantity` must be an integer from `1` through `10000`.
* Pricing uses the account's assigned pricing tier and applicable pricing brackets.
* The tier's block-size, minimum-quantity, and maximum-quantity rules are enforced.
* A successful purchase immediately debits the first month's charge.
* The subscription is created as active and scheduled to renew every 30 days.
* The purchase fails if the account has no pricing tier, the quantity violates its pricing rules, or the balance debit fails.

<Note>
  Do not automatically retry a timed-out purchase. First [retrieve the account](/docs/account/retrieve-account) and [check its balance](/docs/account/balance) to avoid a duplicate charge.
</Note>


## OpenAPI

````yaml POST /api/v1/accounts/{auth_id}/channel-subscriptions
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
  /api/v1/accounts/{auth_id}/channel-subscriptions:
    post:
      tags:
        - Account
      summary: Purchase CPS or concurrency capacity
      description: >-
        Purchase recurring CPS or concurrent-call capacity. A successful request
        immediately debits the first monthly charge and activates a subscription
        that renews every 30 days.
      operationId: create-channel-subscription
      parameters:
        - name: auth_id
          in: path
          required: true
          description: >-
            Target account Auth ID. An account can purchase only for itself;
            administrators may act for another account.
          schema:
            type: string
            example: MA_XXXX
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ChannelSubscriptionRequest'
            example:
              resource_type: concurrent_calls
              quantity: 30
      responses:
        '201':
          description: Capacity subscription purchased and activated.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ChannelSubscription'
              example:
                id: 5ed57f90-b1f1-4c32-9475-b85aa6739aec
                account_id: 123456
                resource_type: concurrent_calls
                quantity: 30
                monthly_cost: '10470.00'
                currency: INR
                status: active
                last_billing_date: '2026-07-16T10:00:00Z'
                next_billing_date: '2026-08-15T10:00:00Z'
                purchased_at: '2026-07-16T10:00:00Z'
                cancelled_at: null
                cancellation_reason: null
                is_active: true
                created_at: '2026-07-16T10:00:00Z'
                updated_at: '2026-07-16T10:00:00Z'
        '400':
          description: >-
            The purchase could not be completed because validation,
            pricing-tier, or account-balance requirements were not met.
        '401':
          description: Missing or invalid authentication.
        '403':
          description: The authenticated account cannot act on the target account.
      security:
        - BearerAuth: []
        - AuthID: []
          AuthToken: []
components:
  schemas:
    ChannelSubscriptionRequest:
      type: object
      required:
        - resource_type
        - quantity
      properties:
        resource_type:
          $ref: '#/components/schemas/CapacityResourceType'
        quantity:
          type: integer
          minimum: 1
          maximum: 10000
          description: >-
            Capacity quantity to purchase. Pricing-tier block and quantity rules
            also apply.
          example: 30
    ChannelSubscription:
      type: object
      required:
        - id
        - account_id
        - resource_type
        - quantity
        - monthly_cost
        - currency
        - status
        - last_billing_date
        - next_billing_date
        - purchased_at
        - cancelled_at
        - cancellation_reason
        - is_active
        - created_at
        - updated_at
      properties:
        id:
          type: string
          format: uuid
          example: 5ed57f90-b1f1-4c32-9475-b85aa6739aec
        account_id:
          type: integer
          example: 123456
        resource_type:
          $ref: '#/components/schemas/CapacityResourceType'
        quantity:
          type: integer
          minimum: 1
          maximum: 10000
          example: 30
        monthly_cost:
          type: string
          description: Recurring monthly charge as a decimal string.
          example: '10470.00'
        currency:
          type: string
          example: INR
        status:
          type: string
          example: active
        last_billing_date:
          type: string
          format: date-time
          example: '2026-07-16T10:00:00Z'
        next_billing_date:
          type: string
          format: date-time
          example: '2026-08-15T10:00:00Z'
        purchased_at:
          type: string
          format: date-time
          example: '2026-07-16T10:00:00Z'
        cancelled_at:
          type: string
          format: date-time
          nullable: true
          example: null
        cancellation_reason:
          type: string
          nullable: true
          example: null
        is_active:
          type: boolean
          example: true
        created_at:
          type: string
          format: date-time
          example: '2026-07-16T10:00:00Z'
        updated_at:
          type: string
          format: date-time
          example: '2026-07-16T10:00:00Z'
    CapacityResourceType:
      type: string
      description: Account capacity to price or purchase.
      enum:
        - concurrent_calls
        - cps
      example: concurrent_calls
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
    BearerAuth:
      type: http
      scheme: bearer
      description: 'Account access token sent as `Authorization: Bearer <ACCESS_TOKEN>`.'

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.