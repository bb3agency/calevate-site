> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Single CDR

> Retrieve the full call detail record for a specific call by its call_id - duration, disposition, caller ID, timestamps, and billing data for a single voice session.

Retrieve the full CDR for one completed call. Unlike the list endpoints, the response is `{ data, success }` where `data` is a **single object** (not an array) - and there is no `pagination`, `summary`, or `filters` block.

<Warning>
  **Pass the call's `uuid`, not the numeric `id`.** The path parameter is *named* `call_id`, but the value it expects is the call's `uuid` (the value you see in `data[].uuid` from a list/search response, or the `CallUUID` delivered to your webhooks). Feeding back the numeric `data[].id` returns `404`.
</Warning>

## Path parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your master account ID, e.g. `MA_XXXXXXXX`. |
| `call_id` | string | Yes | The call's `uuid`, e.g. `aabbccdd-1234-5678-90ab-cdef12345678`. |

## Edge cases

* **Unknown or wrong-format ID:** returns `404` (no `data`). Re-check that you passed the `uuid` and not the numeric `id`.
* **Call not yet complete:** a CDR exists only after the call ends, so an in-progress call's `uuid` will not resolve here. Use [Live Calls](/docs/call) for active calls.
* **Casing:** `Account` is capitalized, `cdr` is lowercase.

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/aabbccdd-1234-5678-90ab-cdef12345678" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

See the [CDR overview](/docs/cdr) for the full field glossary and [Hangup Causes](/docs/concepts/hangup-causes) to decode the hangup fields.


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/cdr/{call_id}
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
  /api/v1/Account/{auth_id}/cdr/{call_id}:
    get:
      tags:
        - CDR
      summary: Retrieve a CDR by call ID
      description: >
        Retrieve the CDR for a specific completed call using its `call_id`.

        Useful when you have a `call_id` from a callback or previous API
        response.
      operationId: get-cdr
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: call_id
          in: path
          required: true
          description: The unique call ID of the completed call.
          schema:
            type: string
            example: abc123-def456-ghi789
      responses:
        '200':
          description: CDR details
          content:
            application/json:
              schema:
                type: object
                properties:
                  data:
                    type: object
                    properties:
                      account_id:
                        type: string
                      answer_time:
                        type: string
                      billsec:
                        type: integer
                      bridge_uuid:
                        type: string
                      call_direction:
                        type: string
                      caller_id_name:
                        type: string
                      caller_id_number:
                        type: string
                      campaign_id:
                        nullable: true
                      carrier_ip:
                        nullable: true
                      codec:
                        type: string
                      context:
                        type: string
                      cost:
                        type: number
                      created_at:
                        type: string
                      currency:
                        type: string
                      customer_endpoint:
                        nullable: true
                      destination_number:
                        type: string
                      duration:
                        type: integer
                      end_time:
                        type: string
                      failure_code:
                        nullable: true
                      failure_reason:
                        nullable: true
                      hangup_cause:
                        type: string
                      hangup_cause_code:
                        type: integer
                      hangup_cause_name:
                        type: string
                      hangup_disposition:
                        type: string
                      hangup_source:
                        type: string
                      id:
                        type: integer
                      jitter:
                        type: number
                      mos:
                        type: number
                      network_addr:
                        type: string
                      origination_region:
                        type: string
                      packet_loss:
                        type: integer
                      progress_time:
                        type: string
                      region:
                        type: string
                      ring_time:
                        type: integer
                      sip_call_id:
                        type: string
                      sip_user_agent:
                        type: string
                      start_time:
                        type: string
                      streaming_cost:
                        type: integer
                      terminated_to:
                        nullable: true
                      total_cost:
                        type: number
                      trunk_id:
                        nullable: true
                      updated_at:
                        type: string
                      uuid:
                        type: string
                    required:
                      - account_id
                      - answer_time
                      - billsec
                      - bridge_uuid
                      - call_direction
                      - caller_id_name
                      - caller_id_number
                      - campaign_id
                      - carrier_ip
                      - codec
                      - context
                      - cost
                      - created_at
                      - currency
                      - customer_endpoint
                      - destination_number
                      - duration
                      - end_time
                      - failure_code
                      - failure_reason
                      - hangup_cause
                      - hangup_cause_code
                      - hangup_cause_name
                      - hangup_disposition
                      - hangup_source
                      - id
                      - jitter
                      - mos
                      - network_addr
                      - origination_region
                      - packet_loss
                      - progress_time
                      - region
                      - ring_time
                      - sip_call_id
                      - sip_user_agent
                      - start_time
                      - streaming_cost
                      - terminated_to
                      - total_cost
                      - trunk_id
                      - updated_at
                      - uuid
                  success:
                    type: boolean
                required:
                  - data
                  - success
              example:
                data:
                  account_id: MA_XXXXXXXX
                  answer_time: '2026-03-25T10:00:01Z'
                  billsec: 42
                  bridge_uuid: 11223344-5566-7788-99aa-bbccddeeff00
                  call_direction: outbound
                  caller_id_name: John Doe
                  caller_id_number: '+919876543210'
                  campaign_id: null
                  carrier_ip: 10.0.0.1
                  codec: PCMU
                  context: voice-api
                  cost: 0.45
                  created_at: '2026-03-25T10:00:42Z'
                  currency: INR
                  customer_endpoint: null
                  destination_number: '+918012345678'
                  duration: 47
                  end_time: '2026-03-25T10:00:42Z'
                  failure_code: null
                  failure_reason: null
                  hangup_cause: NORMAL_CLEARING
                  hangup_cause_code: 4000
                  hangup_cause_name: Normal Hangup
                  hangup_disposition: send_bye
                  hangup_source: Caller
                  id: 18000004
                  jitter: 0
                  mos: 4.5
                  network_addr: 10.0.0.1
                  origination_region: mumbai
                  packet_loss: 0
                  progress_time: '2026-03-25T10:00:00Z'
                  region: ap-south-1
                  ring_time: 5
                  sip_call_id: 11223344-5566-7788-99aa-bbccddeeff00
                  sip_user_agent: Vobiz
                  start_time: '2026-03-25T10:00:00Z'
                  streaming_cost: 0
                  terminated_to: null
                  total_cost: 0.45
                  trunk_id: null
                  updated_at: '2026-03-25T10:00:42Z'
                  uuid: aabbccdd-1234-5678-90ab-cdef12345678
                success: true
        '404':
          description: CDR not found
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