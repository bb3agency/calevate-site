> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Preview CPS and concurrency pricing

> Calculate the monthly price for additional Vobiz CPS or concurrent-call capacity without purchasing capacity or debiting the account.

Preview the monthly price for additional calls-per-second (CPS) or concurrent-call capacity. This endpoint calculates the charge from the account's assigned pricing tier without creating a subscription or debiting the account.

```http theme={null}
GET https://api.vobiz.ai/api/v1/accounts/{auth_id}/channel-pricing-preview
```

## Authentication

Use one of these authentication methods:

| Method | Headers |
| - | - |
| Account access token | `Authorization: Bearer <ACCESS_TOKEN>` |
| Account API credentials | `X-Auth-ID: <AUTH_ID>` and `X-Auth-Token: <AUTH_TOKEN>` |

The authenticated account can preview pricing only for its own `auth_id`. An administrator may act on behalf of another account.

## Parameters

### Path parameter

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Target account Auth ID, such as `MA_XXXX`. |

### Query parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `resource_type` | string | Yes | Capacity to price. Use `concurrent_calls` or `cps`. |
| `quantity` | integer | Yes | Capacity quantity. Must be from `1` through `10000`; pricing-tier block and quantity rules also apply. |

## Examples

<Tabs>
  <Tab title="Concurrent calls">
    ```bash cURL theme={null}
    curl --request GET \
      "https://api.vobiz.ai/api/v1/accounts/MA_XXXX/channel-pricing-preview?resource_type=concurrent_calls&quantity=30" \
      --header "X-Auth-ID: MA_XXXX" \
      --header "X-Auth-Token: YOUR_AUTH_TOKEN"
    ```
  </Tab>

  <Tab title="CPS">
    ```bash cURL theme={null}
    curl --request GET \
      "https://api.vobiz.ai/api/v1/accounts/MA_XXXX/channel-pricing-preview?resource_type=cps&quantity=10" \
      --header "X-Auth-ID: MA_XXXX" \
      --header "X-Auth-Token: YOUR_AUTH_TOKEN"
    ```
  </Tab>
</Tabs>

## Response

The values below are illustrative. The actual monthly cost and currency come from the target account's assigned pricing tier.

```json Preview response theme={null}
{
  "resource_type": "concurrent_calls",
  "quantity": 30,
  "monthly_cost": "10470.00",
  "currency": "INR",
  "breakdown": []
}
```

| Field | Type | Description |
| - | - | - |
| `resource_type` | string | Capacity type that was priced. |
| `quantity` | integer | Capacity quantity included in the calculation. |
| `monthly_cost` | string | Calculated recurring monthly charge as a decimal string. |
| `currency` | string | Currency assigned by the account's pricing tier. |
| `breakdown` | array | Pricing-bracket calculation details when supplied by the tier. |

<Tip>
  Show this response to the customer before submitting a purchase so they can confirm the exact recurring charge.
</Tip>

## Pricing rules

* `resource_type` must be `concurrent_calls` or `cps`.
* `quantity` must be an integer from `1` through `10000`.
* Pricing uses the account's assigned pricing tier and applicable pricing brackets.
* The tier's block-size, minimum-quantity, and maximum-quantity rules are enforced.
* The request fails if the account has no pricing tier or the quantity violates its tier rules.

When the customer confirms the previewed amount, use [Purchase CPS or concurrency capacity](/docs/account/channel-subscriptions).


## OpenAPI

````yaml GET /api/v1/accounts/{auth_id}/channel-pricing-preview
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
  /api/v1/accounts/{auth_id}/channel-pricing-preview:
    get:
      tags:
        - Account
      summary: Preview CPS or concurrency pricing
      description: >-
        Calculate the monthly price for CPS or concurrent-call capacity without
        purchasing capacity or debiting the account.
      operationId: preview-channel-pricing
      parameters:
        - name: auth_id
          in: path
          required: true
          description: >-
            Target account Auth ID. An account can preview only its own pricing;
            administrators may act for another account.
          schema:
            type: string
            example: MA_XXXX
        - name: resource_type
          in: query
          required: true
          description: Capacity type to price.
          schema:
            $ref: '#/components/schemas/CapacityResourceType'
        - name: quantity
          in: query
          required: true
          description: >-
            Capacity quantity to price. Pricing-tier block and quantity rules
            also apply.
          schema:
            type: integer
            minimum: 1
            maximum: 10000
            example: 30
      responses:
        '200':
          description: Calculated monthly capacity price. No balance is debited.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ChannelPricingPreview'
              example:
                resource_type: concurrent_calls
                quantity: 30
                monthly_cost: '10470.00'
                currency: INR
                breakdown: []
        '400':
          description: >-
            Invalid resource type or quantity, pricing-tier rules were not met,
            or no pricing tier is assigned.
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
    CapacityResourceType:
      type: string
      description: Account capacity to price or purchase.
      enum:
        - concurrent_calls
        - cps
      example: concurrent_calls
    ChannelPricingPreview:
      type: object
      required:
        - resource_type
        - quantity
        - monthly_cost
        - currency
        - breakdown
      properties:
        resource_type:
          $ref: '#/components/schemas/CapacityResourceType'
        quantity:
          type: integer
          minimum: 1
          maximum: 10000
          example: 30
        monthly_cost:
          type: string
          description: Calculated monthly charge as a decimal string.
          example: '10470.00'
        currency:
          type: string
          description: Currency assigned by the account's pricing tier.
          example: INR
        breakdown:
          type: array
          description: >-
            Pricing-bracket calculation details when supplied by the pricing
            tier.
          items:
            type: object
            additionalProperties: true
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