> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Purchase from Inventory

> Purchase a Vobiz phone number from inventory and assign it to your account - instantly deducts setup and monthly fees and activates the number for voice.

Purchases a number from inventory and assigns it to your account. The operation debits your account balance for the setup fee and monthly fee.

<Warning>
  **Important: Purchase Process**

  1. Verifies number exists in inventory (auth\_id IS NULL)
  2. Determines billing account (parent MA\_ for SA\_ accounts)
  3. Debits balance (setup\_fee + monthly\_fee)
  4. Assigns auth\_id to your account
  5. Sets purchased\_at timestamp
  6. Returns updated number
</Warning>

<Warning>
  **Billing account:** the setup fee and monthly fee are debited from the account that *owns the credentials*. When a sub-account (`SA_`) purchases, the parent master account (`MA_`) is charged - not the sub-account.
</Warning>

<Warning>
  **Insufficient balance:** if the balance debit fails, the purchase is rolled back and the number stays in inventory (still `auth_id=NULL`). Verify [available balance](/docs/account/balance) covers `setup_fee + monthly_fee` before calling. A failed debit currently surfaces as a `500` (see below).
</Warning>

## HTTP Request

```http theme={null}
POST /api/v1/Account/{auth_id}/numbers/purchase-from-inventory
```

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Request Body

| Field | Type | Required | Description |
| - | - | - | - |
| `e164` | string | Yes | Phone number to purchase in E.164 format (e.g., `+919876543210`). Keep the literal `+` - this field is in the JSON body, so no URL-encoding is needed. |
| `currency` | string | No | Currency for the transaction. Defaults to the number's currency, or `USD` if neither is set. |

<Note>
  The number must currently be in inventory (`status='active'` and `auth_id=NULL`). Browse it first with [List Inventory Numbers](/docs/account-phone-number/list-inventory-numbers).
</Note>

## Response

Returns a success message and the updated PhoneNumber object with `auth_id` assigned to your account.

```json Response - 200 OK theme={null}
{
  "message": "Number purchased successfully",
  "number": {
    "id": "aabbccdd-1234-5678-90ab-cdef12345678",
    "account_id": "MA_XXXXXXXX",
    "e164": "+919876543210",
    "country": "IN",
    "region": "Karnataka",
    "capabilities": {
      "voice": true,
      "sms": false,
      "mms": false,
      "fax": false
    },
    "status": "active",
    "provider": "",
    "setup_fee": 100,
    "monthly_fee": 1.0,
    "currency": "INR",
    "voice_enabled": true,
    "tags": [],
    "purchased_at": "2026-03-25T10:00:00Z",
    "is_blocked": false,
    "created_at": "2026-03-25T10:00:00Z",
    "updated_at": "2026-03-25T10:00:00Z",
    "is_trial_number": false,
    "minimum_commitment_months": 0,
    "aadhaar_verification_required": false,
    "aadhaar_verified": false,
    "source": "inventory"
  }
}
```

<Note>
  After purchase the number is owned by your account (`account_id` set, `source: "inventory"`) but not yet routed. [Assign it to a trunk](/docs/trunks/assign-number), attach it to an application, or [hand it to a sub-account](/docs/account-phone-number/assign-subaccount) to start receiving calls.
</Note>

## Examples

### cURL - Purchase Number from Inventory

```bash cURL Request theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/purchase-from-inventory \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "e164": "+919876543210",
    "currency": "USD"
  }'
```

<Info>
  **Error Response (404 Not Found):** the number does not exist in inventory (already owned, released, or never stocked):

  ```json Error Response - 404 Not Found theme={null}
  {
    "error": "not_found",
    "message": "number not found in inventory"
  }
  ```
</Info>

<Warning>
  **Error Response (500 Internal Server Error):** the purchase failed - most commonly because the balance debit (`setup_fee + monthly_fee`) could not be completed. The number remains in inventory.

  ```json Error Response - 500 Internal Server Error theme={null}
  {
    "error": "internal_server_error",
    "message": "failed to purchase number"
  }
  ```
</Warning>

<Tip>
  **Best Practices:**

  * Always check [inventory](/docs/account-phone-number/list-inventory-numbers) first to ensure the number is available
  * Verify you have sufficient balance before purchasing
  * Note that setup\_fee + monthly\_fee will be debited immediately
  * For sub-accounts (SA\_), the parent master account (MA\_) will be charged
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/numbers/purchase-from-inventory
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
  /api/v1/Account/{auth_id}/numbers/purchase-from-inventory:
    post:
      tags:
        - Phone Numbers
      summary: Purchase from Inventory
      description: |
        Purchase a phone number from inventory and assign it to your account.
        Debits your account balance for the setup fee and monthly fee. For
        sub-accounts (SA_), the parent master account (MA_) is charged.
      operationId: purchase-from-inventory
      parameters:
        - $ref: '#/components/parameters/AuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - e164
              properties:
                e164:
                  type: string
                  description: Phone number to purchase in E.164 format.
                  example: '+919876543210'
                currency:
                  type: string
                  description: >-
                    Currency for transaction. Defaults to the number's currency
                    or "USD".
                  example: USD
            example:
              e164: '+919876543210'
              currency: USD
      responses:
        '200':
          description: Number purchased
          content:
            application/json:
              example:
                message: Number purchased successfully
                number:
                  id: aabbccdd-1234-5678-90ab-cdef12345678
                  account_id: MA_XXXXXXXX
                  e164: '+919876543210'
                  country: IN
                  region: Karnataka
                  capabilities:
                    voice: true
                    sms: false
                    mms: false
                    fax: false
                  status: active
                  provider: ''
                  setup_fee: 100
                  monthly_fee: 1
                  currency: INR
                  voice_enabled: true
                  tags: []
                  purchased_at: '2026-03-25T10:00:00Z'
                  is_blocked: false
                  created_at: '2026-03-25T10:00:00Z'
                  updated_at: '2026-03-25T10:00:00Z'
                  is_trial_number: false
                  minimum_commitment_months: 0
                  aadhaar_verification_required: false
                  aadhaar_verified: false
                  source: inventory
                items:
                  - id: aabbccdd-1234-5678-90ab-cdef12345678
                    account_id: MA_XXXXXXXX
                    e164: '+919876543210'
                    country: IN
                    region: Karnataka
                    capabilities:
                      voice: true
                      sms: false
                      mms: false
                      fax: false
                    status: active
                    monthly_fee: 1
                    currency: INR
        '404':
          description: Number not found in inventory
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '500':
          description: Failed to purchase number
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