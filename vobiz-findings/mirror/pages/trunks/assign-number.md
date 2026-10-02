> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Assign Number to Trunk

> Assign a phone number to a Vobiz SIP trunk so all inbound calls to that DID route through the designated trunk - supports global and India DID numbers.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/{phone_number}/assign
```

Use this endpoint to assign a phone number to a specific SIP trunk. Once assigned, all inbound calls to that phone number are routed through the designated trunk according to your trunk's configuration.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Important:** The phone number must already be in your account inventory. You can purchase numbers using the [Purchase Number](/docs/account-phone-number/purchase-from-inventory) endpoint before assigning them to a trunk.
</Info>

<Warning>
  **URL Encoding Notice:** Always encode the phone number in the URL. Use `%2B` instead of the `+` symbol. For example: `%2B912271264217` (not +912271264217). Failure to encode properly may result in a 404 error.
</Warning>

## URL Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your unique Vobiz account identifier (e.g., `MA_BN2MZ1VV`). Must match your `X-Auth-ID` header. |
| `PHONE_NUMBER` | string | Yes | Phone number to assign, URL-encoded. Use `%2B` instead of `+` (e.g., `%2B912271264217`). |

## Request Body

| Field | Type | Required | Description |
| - | - | - | - |
| `trunk_group_id` | string (UUID) | Yes | UUID of the trunk to assign this phone number to (e.g., `e3e55a78-1234-5678-90ab-cdef12345678`). |

```json Request Body Example theme={null}
{
  "trunk_group_id": "aabbccdd-1234-5678-90ab-cdef12345678"
}
```

## Examples

<CodeGroup>
  ```bash cURL - Assign Number to Trunk theme={null}
  curl -X POST "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/%2B1234567890/assign" \
    -H "X-Auth-ID: {auth_id}" \
    -H "X-Auth-Token: {auth_token}" \
    -H "Content-Type: application/json" \
    -d '{
      "trunk_group_id": "{trunk_id}"
    }'
  ```

  ```bash cURL Template theme={null}
  curl -X POST "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/{phone_number}/assign" \
    -H "X-Auth-ID: {auth_id}" \
    -H "X-Auth-Token: {auth_token}" \
    -H "Content-Type: application/json" \
    -d '{
      "trunk_group_id": "{trunk_id}"
    }'
  ```
</CodeGroup>

## Response

On successful assignment, the API returns `204 No Content` with no response body. Verify the assignment by retrieving the trunk or listing your numbers.

```http Success Response - 204 No Content theme={null}
HTTP/1.1 204 No Content
```

### Error Responses

```json Error Response - 404 Not Found (Number not in inventory) theme={null}
{
  "error": "Number not found",
  "message": "The phone number could not be found. Ensure it is in your inventory and URL-encoded correctly."
}
```

```json Error Response - 400 Bad Request (Number already assigned) theme={null}
{
  "error": "invalid request",
  "message": "This number is already assigned to a trunk."
}
```

<Note>
  **Reassigning a number.** If a number is already assigned to a trunk, the assign call returns `400`. Unassign it first with [Unassign Number](/docs/trunks/unassign-number), then assign it to the new trunk.
</Note>

<Tip>
  **Quick Tips:**

  * **Success Code:** Look for `204 No Content` (empty body) - the call succeeded.
  * **URL Encoding:** Always use `%2B` instead of `+` in the phone number.
  * **Body field:** The trunk UUID goes in `trunk_group_id`, not `trunk_id`.
  * **Number Format:** Use E.164 with country code (e.g., `+1234567890`), URL-encoded.
</Tip>

<Info>
  **Next Steps:**

  * Verify the assignment by retrieving your trunk details
  * Configure your trunk's inbound routing rules
  * Test inbound calls to the assigned number
  * To remove the assignment, use the [Unassign Number](/docs/trunks/unassign-number) endpoint
</Info>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/numbers/{phone_number}/assign
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
  /api/v1/Account/{auth_id}/numbers/{phone_number}/assign:
    post:
      tags:
        - Phone Numbers
      summary: Assign Number to Trunk
      description: |
        Assign a phone number to a specific SIP trunk. Once assigned, all
        inbound calls to that phone number will be routed through the
        designated trunk. The phone number must be URL-encoded; use `%2B`
        instead of `+` (e.g., `%2B912271264217`).
      operationId: assign-number-to-trunk
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: phone_number
          in: path
          required: true
          description: The phone number to assign, URL-encoded (use %2B instead of +).
          schema:
            type: string
            example: '%2B912271264217'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - trunk_group_id
              properties:
                trunk_group_id:
                  type: string
                  format: uuid
                  description: The UUID of the trunk to assign this number to.
                  example: e3e55a78-1234-5678-90ab-cdef12345678
            example:
              trunk_group_id: e3e55a78-1234-5678-90ab-cdef12345678
      responses:
        '204':
          description: Number assigned to trunk
        '400':
          description: Invalid request (e.g., already assigned)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '404':
          description: Number not found
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