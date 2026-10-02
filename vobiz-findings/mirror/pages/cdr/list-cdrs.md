> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List CDRs

> Retrieve paginated Vobiz call detail records with filters for date range, number, direction, and duration - the primary endpoint for call analytics and billing review.

This is the primary endpoint for call analytics and billing review. It returns CDRs newest-first, with a `pagination` block for paging and a `summary` block of aggregate metrics across the filtered set. A CDR is written only after a call completes, so very recent calls may take a few seconds to appear.

## Filters

All filters are optional and combine with AND. Apply them as query-string parameters.

| Parameter | Type | Default | Notes |
| - | - | - | - |
| `from_number` | string | - | Originating (caller) number. Substring or full E.164, e.g. `9876543210`. |
| `to_number` | string | - | Destination (callee) number. Substring or full E.164. |
| `start_date` | string `YYYY-MM-DD` | - | Beginning of the period. **Required together with** `end_date`. |
| `end_date` | string `YYYY-MM-DD` | - | End of the period. **Required together with** `start_date`. |
| `call_direction` | enum | - | `inbound` or `outbound` only. |
| `min_duration` | integer | - | Seconds. Excludes calls shorter than this value. |
| `sip_call_id` | string | - | The SIP `Call-ID` of the call, e.g. `dD1qwu5VZ5iK3ed5u3uspjY5RKL`. Matches the `sip_call_id` field on the CDR. |
| `bridge_uuid` | string | - | UUID of the bridged leg, e.g. `4b7ae653-f40d-42f1-b582-6b05dfcd0c0a`. Matches the `bridge_uuid` field on the CDR. |
| `hangup_cause` | string | - | Telephony hangup cause, e.g. `NORMAL_CLEARING`. See [Hangup Causes](/docs/concepts/hangup-causes). |
| `hangup_disposition` | string | - | How the leg was released, e.g. `send_refuse`. |
| `context` | string | - | Call context, e.g. `sip-trunking`. |
| `campaign_id` | string | - | Campaign identifier associated with the call. |
| `search` | string | - | Free-text search across CDR fields (numbers, IDs, etc.). |
| `page` | integer | `1` | Page number. |
| `per_page` | integer | `20` | Records per page. Max `100`. |

<Note>
  The `from_number` / `to_number` filters map to the `caller_id_number` / `destination_number` fields on the returned CDR object - filter on the former, read the latter. The other filters (`sip_call_id`, `bridge_uuid`, `hangup_cause`, `hangup_disposition`, `context`, `campaign_id`) match the same-named CDR fields directly.
</Note>

## Pagination

The `pagination` object is `{ page, per_page, total, pages, has_next, has_prev }` - not `current_page` / `total_records`. `total` is the count across all pages and `pages = ceil(total / per_page)`. Loop while `has_next` is `true`, incrementing `page`.

## Reading the summary

`summary` is computed over the **filtered** set, not your whole account:

* `totalCalls`, `answeredCalls`, `answerRate` (percent)
* `avgCallDuration` is a **string** like `"28s"` - parse it, don't do arithmetic on it. For numeric work use `total_duration_seconds` and `total_billable_seconds`.
* `total_cost` is in the account `currency`; `last_call_at` is ISO 8601.

## Edge cases

* **No matches:** a valid request that matches nothing returns `200` with `data: []`, `count: 0`, and a zeroed `summary` - not a `404`.
* **Quality metrics on unanswered calls:** `mos`, `jitter`, and `packet_loss` are often `0` (or `null`) for calls that never carried media. Treat `mos: 0` as "no media", not "worst quality".
* **Unanswered calls** have `answer_time: null` and `billsec: 0`.
* **Casing:** `Account` is capitalized and `cdr` is lowercase in the path.

## Example

```bash Filter by date range theme={null}
curl -G "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr" \
  --data-urlencode "start_date=2026-03-01" \
  --data-urlencode "end_date=2026-03-17" \
  --data-urlencode "call_direction=outbound" \
  --data-urlencode "min_duration=10" \
  --data-urlencode "page=1" --data-urlencode "per_page=50" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

```bash Filter by bridge / SIP call id theme={null}
# Find the CDR(s) for a specific bridged leg or SIP Call-ID
curl -sS "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr?bridge_uuid=4b7ae653-f40d-42f1-b582-6b05dfcd0c0a" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"

curl -sS "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr?sip_call_id=dD1qwu5VZ5iK3ed5u3uspjY5RKL" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

See the [CDR overview](/docs/cdr) for the complete 43-field glossary and the [Hangup Causes](/docs/concepts/hangup-causes) reference for decoding `hangup_cause` / `hangup_cause_code`.


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/cdr
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
  /api/v1/Account/{auth_id}/cdr:
    get:
      tags:
        - CDR
      summary: List call records
      description: |
        Returns all CDRs for your account. Supports filtering by phone numbers,
        date range, call direction, duration, and pagination.
      operationId: list-cdrs
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
          description: Paginated list of CDRs
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
                  - pagination
                  - success
                  - summary
              example:
                account_id: MA_XXXXXXXX
                count: 2
                data:
                  - account_id: MA_XXXXXXXX
                    answer_time: '2026-03-25T10:00:01Z'
                    billsec: 42
                    bridge_uuid: aabbccdd-1234-5678-90ab-cdef12345678
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
                    id: 18000000
                    jitter: 0.2
                    mos: 4.5
                    network_addr: 10.0.0.1
                    origination_region: mumbai
                    packet_loss: 0.1
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
                  - account_id: MA_XXXXXXXX
                    answer_time: null
                    billsec: 0
                    bridge_uuid: null
                    call_direction: inbound
                    caller_id_name: ''
                    caller_id_number: '+919876543210'
                    campaign_id: null
                    carrier_ip: null
                    codec: PCMU
                    context: voice-api
                    cost: 0
                    created_at: '2026-03-25T09:30:12Z'
                    currency: INR
                    customer_endpoint: null
                    destination_number: '+918012345678'
                    duration: 12
                    end_time: '2026-03-25T09:30:12Z'
                    failure_code: '16'
                    failure_reason: NO_ANSWER
                    hangup_cause: NO_ANSWER
                    hangup_cause_code: 4100
                    hangup_cause_name: No Answer
                    hangup_disposition: send_cancel
                    hangup_source: Callee
                    id: 18000001
                    jitter: 0
                    mos: 0
                    network_addr: 10.0.0.1
                    origination_region: mumbai
                    packet_loss: 0
                    progress_time: '2026-03-25T09:30:00Z'
                    region: ap-south-1
                    ring_time: 12
                    sip_call_id: 99887766-5544-3322-1100-aabbccddeeff
                    sip_user_agent: Vobiz
                    start_time: '2026-03-25T09:30:00Z'
                    streaming_cost: 0
                    terminated_to: null
                    total_cost: 0
                    trunk_id: null
                    updated_at: '2026-03-25T09:30:12Z'
                    uuid: 11223344-5566-7788-99aa-bbccddeeff00
                pagination:
                  page: 1
                  per_page: 20
                  total: 4500
                  pages: 225
                  has_next: true
                  has_prev: false
                success: true
                summary:
                  answerRate: 48.2
                  answeredCalls: 2171
                  avgCallDuration: 28s
                  last_call_at: '2026-03-25T10:00:00Z'
                  totalCalls: 4500
                  total_billable_seconds: 61211
                  total_cost: 1564.51
                  total_duration_seconds: 118234
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