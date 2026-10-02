> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Recent CDRs

> Fetch the most recent Vobiz call detail records without date filters - a quick tail view of your latest voice traffic for real-time debugging and monitoring.

A quick tail view of your latest calls with no date range required. Returns the 20 most recent CDRs by default; pass `limit` to retrieve more.

## Query parameters

| Parameter | Type | Default | Notes |
| - | - | - | - |
| `limit` | integer | `20` | Number of recent CDRs to return. |

<Warning>
  The recent endpoint takes **only** `limit`. The list/search filters (`from_number`, `start_date`, `call_direction`, `page`, `per_page`, etc.) do not apply here. To filter or page, use [List CDRs](/docs/cdr/list-cdrs).
</Warning>

## Response shape

Recent returns a trimmed envelope - `{ account_id, count, data, success }`. There is **no `pagination`, no `summary`, and no `filters` block**. The CDR objects in `data` carry the same 43 fields as the list endpoint.

## Edge cases

* **Empty account:** returns `200` with `data: []` and `count: 0`.
* **No paging:** because there is no `pagination`, you cannot walk past the `limit`. For full history use the list endpoint and loop on `has_next`.

## Example

```bash cURL theme={null}
curl -G "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/recent" \
  --data-urlencode "limit=50" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

See the [CDR overview](/docs/cdr) for the full field glossary.


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/cdr/recent
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
  /api/v1/Account/{auth_id}/cdr/recent:
    get:
      tags:
        - CDR
      summary: Get the most recent CDRs
      description: >
        Returns the most recent CDRs for your account without requiring a date
        range.

        Default 20 records; use `limit` to retrieve more.
      operationId: list-recent-cdrs
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: limit
          in: query
          description: Number of recent CDRs to return.
          schema:
            type: integer
            default: 20
            example: 50
      responses:
        '200':
          description: Recent CDRs
          content:
            application/json:
              schema:
                type: object
                properties:
                  account_id:
                    type: string
                  count:
                    type: integer
                  data:
                    type: array
                    items:
                      type: object
                      properties:
                        account_id:
                          type: string
                        answer_time:
                          type: string
                          nullable: true
                        billsec:
                          type: integer
                        bridge_uuid:
                          type: string
                          nullable: true
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
                          nullable: true
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
                          type: string
                          nullable: true
                        failure_reason:
                          type: string
                          nullable: true
                        hangup_cause:
                          type: string
                          nullable: true
                        hangup_cause_code:
                          type: integer
                          nullable: true
                        hangup_cause_name:
                          type: string
                          nullable: true
                        hangup_disposition:
                          type: string
                          nullable: true
                        hangup_source:
                          type: string
                          nullable: true
                        id:
                          type: integer
                        jitter:
                          type: number
                          nullable: true
                        mos:
                          type: number
                          nullable: true
                        network_addr:
                          type: string
                          nullable: true
                        origination_region:
                          type: string
                        packet_loss:
                          type: number
                          nullable: true
                        progress_time:
                          type: string
                          nullable: true
                        region:
                          type: string
                        ring_time:
                          type: integer
                        sip_call_id:
                          type: string
                        sip_user_agent:
                          type: string
                          nullable: true
                        start_time:
                          type: string
                        streaming_cost:
                          type: number
                        terminated_to:
                          type: string
                          nullable: true
                        total_cost:
                          type: number
                        trunk_id:
                          type: string
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
                  - account_id
                  - count
                  - data
                  - success
              example:
                account_id: MA_XXXXXXXX
                count: 1
                data:
                  - account_id: MA_XXXXXXXX
                    answer_time: '2026-03-25T10:00:01Z'
                    billsec: 42
                    bridge_uuid: 99887766-5544-3322-1100-aabbccddeeff
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
                    id: 18000003
                    jitter: 0.2
                    mos: 4.5
                    network_addr: 10.0.0.1
                    origination_region: mumbai
                    packet_loss: 0.1
                    progress_time: '2026-03-25T10:00:00Z'
                    region: ap-south-1
                    ring_time: 5
                    sip_call_id: 99887766-5544-3322-1100-aabbccddeeff
                    sip_user_agent: Vobiz
                    start_time: '2026-03-25T10:00:00Z'
                    streaming_cost: 0
                    terminated_to: null
                    total_cost: 0.45
                    trunk_id: null
                    updated_at: '2026-03-25T10:00:42Z'
                    uuid: 99887766-5544-3322-1100-aabbccddeeff
                success: true
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