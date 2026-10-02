> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Search CDRs

> Search Vobiz call detail records with active filter combinations - find specific calls by number, status, or duration for dispute resolution and quality review.

Search behaves exactly like [List CDRs](/docs/cdr/list-cdrs) - same filters, same `data`, `pagination`, and `summary` - but the response adds a `filters` object echoing the active filter values. Use it to power search UIs that need to display the current filter state, or to confirm which filters the server actually applied.

## Filters

Identical to the list endpoint: `from_number`, `to_number`, `start_date` + `end_date` (paired, `YYYY-MM-DD`), `call_direction` (`inbound`/`outbound`), `min_duration` (seconds), `sip_call_id`, `bridge_uuid`, `hangup_cause`, `hangup_disposition`, `context`, `campaign_id`, `search` (free-text), `page` (default `1`), `per_page` (default `20`, max `100`). See [List CDRs](/docs/cdr/list-cdrs#filters) for the full table.

## The `filters` echo

The response includes:

```json theme={null}
"filters": {
  "call_direction": "outbound",
  "from_number": "+919876543210",
  "hangup_cause": "",
  "to_number": ""
}
```

| Field | Notes |
| - | - |
| `call_direction` | Echoes the applied direction, or `""` if none. |
| `from_number` | Echoes the caller filter, or `""`. |
| `to_number` | Echoes the callee filter, or `""`. |
| `hangup_cause` | Present in the echo even though it is not a list/search query param - returns `""` here. |

<Note>
  Unset filters echo back as empty strings (`""`), not as missing keys or `null`. The `filters` object always carries all four keys.
</Note>

## Example

```bash cURL theme={null}
curl -G "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/search" \
  --data-urlencode "call_direction=outbound" \
  --data-urlencode "from_number=919876543210" \
  --data-urlencode "page=1" --data-urlencode "per_page=50" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

See the [CDR overview](/docs/cdr) for the field glossary and [Hangup Causes](/docs/concepts/hangup-causes) for hangup decoding.


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/cdr/search
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
  /api/v1/Account/{auth_id}/cdr/search:
    get:
      tags:
        - CDR
      summary: Search CDRs with filter summary
      description: |
        Identical filters to the list endpoint, but the response also includes a
        `filter_summary` object describing the active filters applied.
      operationId: search-cdrs
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - $ref: '#/components/parameters/CdrFromNumber'
        - $ref: '#/components/parameters/CdrToNumber'
        - $ref: '#/components/parameters/CdrStartDate'
        - $ref: '#/components/parameters/CdrEndDate'
        - $ref: '#/components/parameters/CdrCallDirection'
        - $ref: '#/components/parameters/CdrMinDuration'
        - $ref: '#/components/parameters/CdrSipCallId'
        - $ref: '#/components/parameters/CdrBridgeUuid'
        - $ref: '#/components/parameters/CdrHangupCause'
        - $ref: '#/components/parameters/CdrHangupDisposition'
        - $ref: '#/components/parameters/CdrContext'
        - $ref: '#/components/parameters/CdrCampaignId'
        - $ref: '#/components/parameters/CdrSearch'
        - $ref: '#/components/parameters/CdrPage'
        - $ref: '#/components/parameters/CdrPerPage'
      responses:
        '200':
          description: CDR list with active filter summary
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
                  filters:
                    type: object
                    properties:
                      call_direction:
                        type: string
                      from_number:
                        type: string
                      hangup_cause:
                        type: string
                      to_number:
                        type: string
                    required:
                      - call_direction
                      - from_number
                      - hangup_cause
                      - to_number
                  pagination:
                    type: object
                    properties:
                      page:
                        type: integer
                      per_page:
                        type: integer
                      total:
                        type: integer
                      pages:
                        type: integer
                      has_next:
                        type: boolean
                      has_prev:
                        type: boolean
                    required:
                      - page
                      - per_page
                      - total
                      - pages
                      - has_next
                      - has_prev
                  success:
                    type: boolean
                  summary:
                    type: object
                    properties:
                      answerRate:
                        type: number
                      answeredCalls:
                        type: integer
                      avgCallDuration:
                        type: string
                      last_call_at:
                        type: string
                      totalCalls:
                        type: integer
                      total_billable_seconds:
                        type: integer
                      total_cost:
                        type: number
                      total_duration_seconds:
                        type: integer
                    required:
                      - answerRate
                      - answeredCalls
                      - avgCallDuration
                      - last_call_at
                      - totalCalls
                      - total_billable_seconds
                      - total_cost
                      - total_duration_seconds
                required:
                  - account_id
                  - count
                  - data
                  - filters
                  - pagination
                  - success
                  - summary
              example:
                account_id: MA_XXXXXXXX
                count: 1
                data:
                  - account_id: MA_XXXXXXXX
                    answer_time: '2026-03-25T10:00:01Z'
                    billsec: 42
                    bridge_uuid: 55667788-1122-3344-5566-77889900aabb
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
                    id: 18000002
                    jitter: 0.2
                    mos: 4.5
                    network_addr: 10.0.0.1
                    origination_region: mumbai
                    packet_loss: 0.1
                    progress_time: '2026-03-25T10:00:00Z'
                    region: ap-south-1
                    ring_time: 5
                    sip_call_id: 55667788-1122-3344-5566-77889900aabb
                    sip_user_agent: Vobiz
                    start_time: '2026-03-25T10:00:00Z'
                    streaming_cost: 0
                    terminated_to: null
                    total_cost: 0.45
                    trunk_id: null
                    updated_at: '2026-03-25T10:00:42Z'
                    uuid: 55667788-1122-3344-5566-77889900aabb
                filters:
                  call_direction: outbound
                  from_number: '+919876543210'
                  hangup_cause: ''
                  to_number: ''
                pagination:
                  page: 1
                  per_page: 20
                  total: 1
                  pages: 1
                  has_next: false
                  has_prev: false
                success: true
                summary:
                  answerRate: 100
                  answeredCalls: 1
                  avgCallDuration: 47s
                  last_call_at: '2026-03-25T10:00:00Z'
                  totalCalls: 1
                  total_billable_seconds: 42
                  total_cost: 0.45
                  total_duration_seconds: 47
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
    CdrFromNumber:
      name: from_number
      in: query
      description: Filter by the originating phone number (caller).
      schema:
        type: string
        example: '9876543210'
    CdrToNumber:
      name: to_number
      in: query
      description: Filter by the destination phone number (callee).
      schema:
        type: string
        example: '1234567890'
    CdrStartDate:
      name: start_date
      in: query
      description: >-
        Beginning of the search period (YYYY-MM-DD). Required when using
        `end_date`.
      schema:
        type: string
        format: date
        example: '2026-03-01'
    CdrEndDate:
      name: end_date
      in: query
      description: End of the search period (YYYY-MM-DD). Required when using `start_date`.
      schema:
        type: string
        format: date
        example: '2026-03-17'
    CdrCallDirection:
      name: call_direction
      in: query
      description: Filter by direction.
      schema:
        type: string
        enum:
          - inbound
          - outbound
    CdrMinDuration:
      name: min_duration
      in: query
      description: >-
        Minimum call duration in seconds. Excludes calls shorter than this
        value.
      schema:
        type: integer
        example: 10
    CdrSipCallId:
      name: sip_call_id
      in: query
      description: >-
        Filter by the SIP Call-ID of the call (matches the cdr's sip_call_id
        field).
      schema:
        type: string
        example: dD1qwu5VZ5iK3ed5u3uspjY5RKL
    CdrBridgeUuid:
      name: bridge_uuid
      in: query
      description: >-
        Filter by the UUID of the bridged leg (matches the cdr's bridge_uuid
        field).
      schema:
        type: string
        example: 4b7ae653-f40d-42f1-b582-6b05dfcd0c0a
    CdrHangupCause:
      name: hangup_cause
      in: query
      description: Filter by telephony hangup cause, e.g. NORMAL_CLEARING.
      schema:
        type: string
        example: NORMAL_CLEARING
    CdrHangupDisposition:
      name: hangup_disposition
      in: query
      description: Filter by how the leg was released, e.g. send_refuse.
      schema:
        type: string
        example: send_refuse
    CdrContext:
      name: context
      in: query
      description: Filter by the call context, e.g. sip-trunking.
      schema:
        type: string
        example: sip-trunking
    CdrCampaignId:
      name: campaign_id
      in: query
      description: Filter by the campaign identifier associated with the call.
      schema:
        type: string
    CdrSearch:
      name: search
      in: query
      description: Free-text search across CDR fields (numbers, IDs, etc.).
      schema:
        type: string
    CdrPage:
      name: page
      in: query
      description: Page number for paginated results.
      schema:
        type: integer
        default: 1
    CdrPerPage:
      name: per_page
      in: query
      description: 'Number of records per page. Max: 100.'
      schema:
        type: integer
        default: 20
        maximum: 100
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