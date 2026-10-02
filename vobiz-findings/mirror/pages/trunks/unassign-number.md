> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Unassign Number from Trunk

> Remove a phone number's trunk assignment on Vobiz - the DID returns to your account inventory and inbound routing via the trunk stops immediately.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/{phone_number}/assign
```

Use this endpoint to remove the assignment between a phone number and a SIP trunk. After unassignment, the number remains in your account inventory but no longer routes calls through the previously assigned trunk.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Warning:** Unassigning a number from a trunk immediately stops routing inbound calls to that number. Ensure you have an alternative routing configuration, or reassign the number to a different trunk if you want to continue receiving calls.
</Warning>

<Warning>
  **URL Encoding Notice:** Always encode the phone number in the URL. Use `%2B` instead of the `+` symbol. For example: `%2B912271264217` (not +912271264217). Failure to encode properly may result in a 404 error.
</Warning>

<Info>
  **Note:** This endpoint uses the `DELETE` HTTP method on the same URL path as the assignment endpoint. No request body is required.
</Info>

## URL Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your unique Vobiz account identifier (e.g., `MA_XXXXXXXX`). Must match your `X-Auth-ID` header. |
| `PHONE_NUMBER` | string | Yes | Phone number to unassign, URL-encoded. Use `%2B` instead of `+` (e.g., `%2B912271264217`). |

<Note>
  **No Request Body Required:** The DELETE method does not require a request body. The phone number specified in the URL will be unassigned from its currently associated trunk.
</Note>

## Examples

<CodeGroup>
  ```bash cURL - Unassign Number from Trunk theme={null}
  curl -X DELETE "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/%2B1234567890/assign" \
    -H "X-Auth-ID: {auth_id}" \
    -H "X-Auth-Token: {auth_token}" \
    -H "Content-Type: application/json"
  ```

  ```bash cURL Template theme={null}
  curl -X DELETE "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/{phone_number}/assign" \
    -H "X-Auth-ID: {auth_id}" \
    -H "X-Auth-Token: {auth_token}" \
    -H "Content-Type: application/json"
  ```
</CodeGroup>

## Response

On successful unassignment, the API returns `204 No Content` with no response body.

```http Success Response - 204 No Content theme={null}
HTTP/1.1 204 No Content
Date: Thu, 23 Jan 2026 07:07:24 GMT
Server: Vobiz API Gateway
```

### Verifying the Unassignment

After unassignment, you can confirm the change by listing numbers (the `trunk_group_id` will be absent) and by retrieving the trunk to confirm it no longer references this number.

```json Number after unassign (from list-numbers) theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345680",
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
  "voice_enabled": true,
  "tags": [],
  "purchased_at": "2026-05-01T06:58:38.796024Z",
  "is_blocked": false,
  "created_at": "2026-03-31T18:30:00Z",
  "updated_at": "2026-05-12T07:07:24.000000Z",
  "is_trial_number": false,
  "last_billing_date": "2026-05-01T06:58:38.796024Z",
  "next_billing_date": "2026-06-01T06:58:38.796024Z",
  "minimum_commitment_months": 0,
  "aadhaar_verification_required": false,
  "aadhaar_verified": false,
  "source": "purchased"
}
```

```json Trunk after unassign (from retrieve-trunk) theme={null}
{
  "trunk_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "name": "Acme Production Trunk",
  "trunk_domain": "aabbccdd-1234-5678-90ab-cdef12345678.sip.vobiz.ai",
  "trunk_status": "active",
  "secure": false,
  "trunk_direction": "inbound",
  "concurrent_calls_limit": 10,
  "cps_limit": 2,
  "primary_uri_uuid": "aabbccdd-1234-5678-90ab-cdef12345681",
  "description": "",
  "inbound_destination": "aabbccdd-1234-5678-90ab-cdef12345681",
  "transport": "udp",
  "recording": true,
  "enable_transcription": true,
  "pii_redaction": false,
  "webhook_method": "POST",
  "recording_webhook_enabled": false,
  "created_at": "2026-04-17T10:28:06.112095Z",
  "updated_at": "2026-05-12T07:07:24.000000Z"
}
```

### Error Responses

```json Error Response - 404 Not Found (Invalid Phone Number) theme={null}
{
  "error": "Number not found",
  "message": "The phone number could not be found or is not assigned to any trunk."
}
```

```json Error Response - 400 Bad Request (Invalid Format) theme={null}
{
  "error": "invalid request",
  "message": "The phone number format is invalid. Ensure it is URL-encoded correctly."
}
```

<Tip>
  **Quick Tips:**

  * **Success Code:** Look for `204 No Content` response
  * **URL Encoding:** Always use `%2B` instead of `+` in the phone number
  * **No Request Body:** DELETE requests do not require a request body
  * **Number Format:** Use E.164 format with country code (e.g., +1234567890)
</Tip>

<Warning>
  **Important Considerations:**

  * **Immediate Effect:** Unassignment takes effect immediately; inbound calls will no longer route
  * **Number Retention:** The number remains in your account inventory after unassignment
  * **Reassignment:** You can reassign the number to a different trunk or the same trunk later
  * **Billing:** Number rental charges continue until you release the number using the [Unrent Number](/docs/account-phone-number/unrent-number) endpoint
</Warning>

<Info>
  **Next Steps:**

  * Reassign to a different trunk using the [Assign Number](/docs/trunks/assign-number) endpoint
  * Or, release the number entirely using the [Unrent Number](/docs/account-phone-number/unrent-number) endpoint
  * Verify the unassignment by listing your trunk details
  * Update your application logic to handle the routing change
</Info>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/numbers/{phone_number}/assign
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
    delete:
      tags:
        - Phone Numbers
      summary: Unassign Number from Trunk
      description: |
        Remove the assignment between a phone number and a SIP trunk. After
        unassignment, the number remains in your account inventory but will
        no longer route inbound calls through the previously assigned trunk.
        URL-encode the phone number (use `%2B` instead of `+`).
      operationId: unassign-number-from-trunk
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: phone_number
          in: path
          required: true
          description: The phone number to unassign, URL-encoded (use %2B instead of +).
          schema:
            type: string
            example: '%2B912271264217'
      responses:
        '204':
          description: Number unassigned
        '400':
          description: Invalid request
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