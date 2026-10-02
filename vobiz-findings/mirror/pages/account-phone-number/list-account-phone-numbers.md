> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List Account Phone Numbers

> Retrieve all phone numbers purchased and assigned to your Vobiz account - capabilities, billing, status, and application assignments across 130+ countries.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers
```

Returns a list of phone numbers purchased and assigned to your account.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Query Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `page` | integer | No | Page number, starting at `1`. Default: `1`. |
| `per_page` | integer | No | Number of records per page. Default: `25`. |
| `search` | string | No | Filter by phone number. Include the country code. For an E.164 number, URL-encode the leading `+` as `%2B` or use `--data-urlencode`. |

<Note>
  The request and response both use `page` and `per_page`. The `limit` and `offset` parameters do not control pagination for this endpoint.
</Note>

<Info>
  `from_date` and `to_date` are not supported filters for this endpoint. Use `search` to filter by phone number.
</Info>

<Warning>
  **Master Accounts (MA\_):** results from a master account include numbers owned by its sub-accounts (`SA_`). Each item's `account_id` tells you which account owns it.
</Warning>

## Request

```bash cURL theme={null}
curl --get "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers" \
  --data-urlencode "page=1" \
  --data-urlencode "per_page=20" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

### Search owned numbers

Use `--data-urlencode` to preserve the leading `+` in an E.164 number. Writing a raw `+` in a query string can decode as a space.

```bash cURL theme={null}
curl --get "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers" \
  --data-urlencode "page=1" \
  --data-urlencode "per_page=20" \
  --data-urlencode "search=+919876543210" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

## Response Example

```json Success Response (200 OK) theme={null}
{
  "items": [
    {
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
      "monthly_fee": 300,
      "currency": "INR",
      "application_id": "20577609616603585",
      "voice_enabled": true,
      "tags": [],
      "purchased_at": "2026-03-25T06:58:38.796024Z",
      "is_blocked": false,
      "created_at": "2026-03-25T18:30:00Z",
      "updated_at": "2026-03-25T06:58:54.752187Z",
      "is_trial_number": false,
      "last_billing_date": "2026-03-25T06:58:38.796024Z",
      "next_billing_date": "2026-04-25T06:58:38.796024Z",
      "minimum_commitment_months": 0,
      "aadhaar_verification_required": false,
      "aadhaar_verified": false,
      "source": "purchased"
    }
  ],
  "page": 1,
  "per_page": 25,
  "total": 24
}
```

<Info>
  **Response Structure:**

  * **items:** Array of phone number objects purchased by your account
  * **page:** Current page number
  * **per\_page:** Number of items per page
  * **total:** Total count of purchased phone numbers
</Info>

<Warning>
  Only phone numbers owned by an account (with a populated `account_id`) are returned. Numbers still in inventory (`auth_id=NULL`) are not included - browse those with [List Inventory Numbers](/docs/account-phone-number/list-inventory-numbers).
</Warning>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/numbers
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
  /api/v1/Account/{auth_id}/numbers:
    get:
      tags:
        - Phone Numbers
      summary: List phone numbers
      description: List all phone numbers on your account.
      operationId: list-numbers
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: page
          in: query
          description: Page number, starting at 1
          schema:
            type: integer
            default: 1
            minimum: 1
        - name: per_page
          in: query
          description: Number of phone numbers to return per page
          schema:
            type: integer
            default: 25
            minimum: 1
        - name: search
          in: query
          description: >-
            Filter by phone number. Include the country code and URL-encode a
            leading plus sign.
          schema:
            type: string
            example: '+919876543210'
      responses:
        '200':
          description: List of phone numbers
          content:
            application/json:
              example:
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
                    provider: ''
                    setup_fee: 100
                    monthly_fee: 300
                    currency: INR
                    application_id: '20577609616603585'
                    voice_enabled: true
                    tags: []
                    purchased_at: '2026-03-25T06:58:38.796024Z'
                    is_blocked: false
                    created_at: '2026-03-25T18:30:00Z'
                    updated_at: '2026-03-25T06:58:54.752187Z'
                    is_trial_number: false
                    last_billing_date: '2026-03-25T06:58:38.796024Z'
                    next_billing_date: '2026-04-25T06:58:38.796024Z'
                    minimum_commitment_months: 0
                    aadhaar_verification_required: false
                    aadhaar_verified: false
                    source: purchased
                  - id: 11223344-5566-7788-99aa-bbccddeeff00
                    account_id: MA_XXXXXXXX
                    e164: '+912271263984'
                    country: IN
                    region: Mumbai
                    capabilities:
                      voice: true
                      sms: false
                      mms: false
                      fax: false
                    status: active
                    provider: ''
                    setup_fee: 100
                    monthly_fee: 200
                    currency: INR
                    application_id: '31985999331899218'
                    voice_enabled: true
                    tags: []
                    purchased_at: '2026-03-25T10:25:30.672202Z'
                    is_blocked: false
                    created_at: '2026-03-25T09:30:04.541115Z'
                    updated_at: '2026-03-25T10:29:35.330503Z'
                    is_trial_number: false
                    last_billing_date: '2026-03-25T10:25:30.672202Z'
                    next_billing_date: '2026-04-25T10:25:30.672202Z'
                    minimum_commitment_months: 0
                    aadhaar_verification_required: false
                    aadhaar_verified: false
                    source: purchased
                page: 1
                per_page: 25
                total: 24
              schema:
                type: object
                properties:
                  items:
                    type: array
                    items:
                      type: object
                      properties:
                        id:
                          type: string
                        account_id:
                          type: string
                        e164:
                          type: string
                        country:
                          type: string
                        region:
                          type: string
                        capabilities:
                          type: object
                          properties:
                            voice:
                              type: boolean
                            sms:
                              type: boolean
                            mms:
                              type: boolean
                            fax:
                              type: boolean
                          required:
                            - voice
                            - sms
                            - mms
                            - fax
                        status:
                          type: string
                        provider:
                          type: string
                        setup_fee:
                          type: integer
                        monthly_fee:
                          type: integer
                        currency:
                          type: string
                        application_id:
                          type: string
                        voice_enabled:
                          type: boolean
                        tags:
                          type: array
                          items:
                            type: string
                        purchased_at:
                          type: string
                        is_blocked:
                          type: boolean
                        created_at:
                          type: string
                        updated_at:
                          type: string
                        is_trial_number:
                          type: boolean
                        last_billing_date:
                          type: string
                        next_billing_date:
                          type: string
                        minimum_commitment_months:
                          type: integer
                        aadhaar_verification_required:
                          type: boolean
                        aadhaar_verified:
                          type: boolean
                        source:
                          type: string
                        released_at:
                          type: string
                        trunk_group_id:
                          type: string
                      required:
                        - id
                        - account_id
                        - e164
                        - country
                        - region
                        - capabilities
                        - status
                        - provider
                        - setup_fee
                        - monthly_fee
                        - currency
                        - voice_enabled
                        - tags
                        - purchased_at
                        - is_blocked
                        - created_at
                        - updated_at
                        - is_trial_number
                        - minimum_commitment_months
                        - aadhaar_verification_required
                        - aadhaar_verified
                        - source
                  page:
                    type: integer
                  per_page:
                    type: integer
                  total:
                    type: integer
                required:
                  - items
                  - page
                  - per_page
                  - total
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