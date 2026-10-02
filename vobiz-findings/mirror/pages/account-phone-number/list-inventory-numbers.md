> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List Inventory Numbers

> Browse Vobiz phone numbers available for purchase - search unassigned DIDs, virtual numbers, and toll-free numbers by country, prefix, or voice capability.

This endpoint lists phone numbers in inventory (`auth_id` is null) that are available for purchase. Use the [Purchase from Inventory](/docs/account-phone-number/purchase-from-inventory) endpoint to assign them to your account.

<Info>
  Only numbers with `status='active'` and `auth_id=NULL` are returned. These numbers are ready to be purchased and assigned to your account.
</Info>

## HTTP Request

```http theme={null}
GET /api/v1/Account/{auth_id}/inventory/numbers
```

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Query Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `country` | string | No | Filter by country code (e.g., `US`, `IN`). |
| `search` | string | No | Substring match against the E.164 number. For example, `search=80` matches `+918065...`. |
| `exclude` | string | No | One or more E.164 prefixes to remove from results. **Include the country code** (e.g. `9180` for India +91 80-series, `1415` for US +1 415). A leading `+` is optional (`+9180` also works). Accepts repeated params (`?exclude=9180&exclude=9192`) or a comma-separated list (`?exclude=9180,9192`); both forms can be combined. |
| `page` | integer | No | Page number for pagination. Default: 1. |
| `per_page` | integer | No | Items per page. Default: 25. Maximum: 100. |

<Note>
  **How `exclude` behaves:**

  * The prefix is matched against the number's full E.164 form (`+<countrycode><rest>`), so `exclude=9180` removes every number starting with `+9180`. It works for any country - it is not limited to Indian numbers.
  * **Include the country code.** `exclude=9180` (not `exclude=80`). A bare series like `80` matches `+80*`, which does not exist for Indian inventory, so it has no effect.
  * It is ANDed with every other filter, so it takes priority over `search`. A number that matches `search` but also matches an excluded prefix is still excluded (`?search=80&exclude=9180` returns no `+9180*` numbers).
  * Duplicate values are de-duplicated silently.
  * The `total` in the response reflects the filtered result set.
</Note>

<Note>
  There is no separate `/numbers/search` endpoint. To find numbers available to rent, use this endpoint with the `country` and `search` filters.
</Note>

## Response

Returns a paginated list of phone numbers available in inventory.

```json Response - 200 OK theme={null}
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "e164": "+14155551234",
      "country": "US",
      "region": "CA",
      "status": "active",
      "setup_fee": 0.0,
      "monthly_fee": 1.0,
      "currency": "INR",
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T10:00:00Z"
    }
  ],
  "page": 1,
  "per_page": 25,
  "total": 500
}
```

## Examples

### cURL - List All Inventory Numbers

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/inventory/numbers?page=1&per_page=25" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

### cURL - Filter by Country

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/inventory/numbers?country=US&page=1&per_page=25" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

### cURL - Search by prefix within a country

```bash cURL Request theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/inventory/numbers?country=IN&search=80&page=1&per_page=25" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

### cURL - Exclude one or more series

Remove numbers whose prefix you don't want. Include the country code (`9180`, not `80`); a leading `+` is optional.

```bash cURL Request theme={null}
# Exclude the India 80-series - no +9180* numbers are returned
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/inventory/numbers?exclude=9180&per_page=50" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"

# Exclude multiple prefixes (comma-separated; ?exclude=9180&exclude=9192 is equivalent)
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/inventory/numbers?exclude=9180,9192&per_page=50" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"

# Works for any country - exclude a US prefix (+1 415)
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/inventory/numbers?exclude=1415&per_page=50" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

<Note>
  Each item carries a `capabilities` object (`voice`, `sms`, `mms`, `fax`). Vobiz numbers are voice-first, so `sms`, `mms`, and `fax` are commonly `false`. Inspect `setup_fee` and `monthly_fee` (in the listed `currency`) before purchasing - these are the amounts that will be debited.
</Note>

<Tip>
  **Use Cases:**

  * Browse available numbers before purchasing
  * Check inventory for specific countries or regions
  * View pricing information for available numbers
  * Find numbers with specific capabilities (voice, SMS, MMS)
</Tip>

<Info>
  **Next Step:** Once you find a number you want, use the [Purchase from Inventory](/docs/account-phone-number/purchase-from-inventory) endpoint to assign it to your account.
</Info>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/inventory/numbers
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
  /api/v1/Account/{auth_id}/inventory/numbers:
    get:
      tags:
        - Phone Numbers
      summary: List Inventory Numbers
      description: |
        Browse available phone numbers in inventory that are not assigned to
        any account. Only numbers with `status='active'` and `auth_id=NULL`
        are returned. These numbers are ready to be purchased.
      operationId: list-inventory-numbers
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: country
          in: query
          description: Filter by country code (e.g., "US", "IN").
          schema:
            type: string
            example: IN
        - name: search
          in: query
          description: >-
            Substring match against the E.164 number (e.g., "80" matches
            "+918065...").
          schema:
            type: string
        - name: exclude
          in: query
          description: >
            One or more E.164 prefixes to remove from results. Include the
            country code (e.g. "9180" for India +91 80-series, "1415" for US +1
            415); a leading "+" is optional. Matched against the full E.164
            form, so it works for any country. Accepts a comma-separated list
            ("9180,9192") or repeated params ("exclude=9180&exclude=9192"), and
            the two forms can be combined. It is ANDed with all other filters,
            so it takes priority over `search`; duplicates are de-duplicated
            silently and `total` reflects the filtered result set.
          schema:
            type: string
            example: 9180,9192
        - name: page
          in: query
          schema:
            type: integer
            default: 1
        - name: per_page
          in: query
          schema:
            type: integer
            default: 25
            maximum: 100
      responses:
        '200':
          description: Inventory numbers
          content:
            application/json:
              example:
                items:
                  - id: 550e8400-e29b-41d4-a716-446655440000
                    e164: '+14155551234'
                    country: US
                    region: CA
                    status: active
                    setup_fee: 0
                    monthly_fee: 1
                    currency: INR
                    created_at: '2025-01-15T10:00:00Z'
                    updated_at: '2025-01-15T10:00:00Z'
                page: 1
                per_page: 25
                total: 500
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
                        voice_enabled:
                          type: boolean
                        tags:
                          nullable: true
                        is_blocked:
                          type: boolean
                        created_at:
                          type: string
                        updated_at:
                          type: string
                        is_trial_number:
                          type: boolean
                        minimum_commitment_months:
                          type: integer
                        aadhaar_verification_required:
                          type: boolean
                        aadhaar_verified:
                          type: boolean
                        region:
                          type: string
                      required:
                        - id
                        - account_id
                        - e164
                        - country
                        - capabilities
                        - status
                        - provider
                        - setup_fee
                        - monthly_fee
                        - currency
                        - voice_enabled
                        - tags
                        - is_blocked
                        - created_at
                        - updated_at
                        - is_trial_number
                        - minimum_commitment_months
                        - aadhaar_verification_required
                        - aadhaar_verified
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