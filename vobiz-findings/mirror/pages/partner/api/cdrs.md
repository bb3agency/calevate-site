> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# CDRs (Call History)

> Fetch full call detail records for every voice session across your Vobiz partner ecosystem - filter by date, direction, or hangup cause for billing and quality review.

[← Partner API Reference](/docs/partner/api)

Full call detail records for every voice session across your partner ecosystem. Filter by date range, direction, hangup cause, number, and more. Essential for billing reconciliation, call quality troubleshooting, and traffic monitoring.

<Info>
  All Partner API requests use `X-Auth-ID` and `X-Auth-Token` headers. See [Authentication](/docs/partner/api/authentication) for details.
</Info>

## Overview

The CDR API gives you read access to call logs for all customers under your partner account. Three endpoints cover different scopes:

* **Customer CDRs** - Filtered CDR log for one customer. Most common - use for per-customer billing and support tickets.
* **Single CDR by UUID** - Deep forensic detail for one specific call by its UUID. Use for troubleshooting a specific incident.
* **All CDRs (Global)** - Global traffic log across all accounts. Use for platform-wide quality monitoring and aggregate reporting.

## Customer CDRs

Returns a paginated CDR log for one specific customer. All filter parameters are optional - omit all to get the most recent calls paginated by default.

### Available Filters

| Parameter | Type | Example | Description |
| - | - | - | - |
| `page` | integer | `1` | Page number (1-indexed) |
| `per_page` | integer | `20` | Items per page (max `100`) |
| `start_date` | string | `2026-03-01` | Start of date range, `YYYY-MM-DD` |
| `end_date` | string | `2026-03-31` | End of date range, `YYYY-MM-DD` |
| `call_direction` | string | `inbound` | `inbound` or `outbound` |
| `status` | string | `answered` | `answered`, `failed`, `busy`, `no_answer` |
| `hangup_cause` | string | `NO_ANSWER` | SIP/Q.850 hangup cause, e.g. `NORMAL_CLEARING`, `NO_ANSWER`, `USER_BUSY` |
| `min_duration` | integer | `10` | Minimum call duration in seconds |

<Note>
  The date filters here are **`start_date`** / **`end_date`** (CDRs), not `from_date` / `to_date` as used by the [Transactions](/docs/partner/api/transactions) endpoint. Status values are underscored: `no_answer`, not `no-answer`.
</Note>

### Examples

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/cdrs?page=1&per_page=20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/cdrs?start_date=2026-03-01&end_date=2026-03-31&per_page=100" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/cdrs?call_direction=inbound&status=answered&min_duration=10&start_date=2026-03-01&end_date=2026-03-31" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/cdrs?status=failed&hangup_cause=NO_ANSWER&start_date=2026-03-20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

### Response

```json theme={null}
{
  "success": true,
  "account_id": "MA_XXXXXXXX",
  "account_auth_id": "MA_XXXXXXXX",
  "count": 2,
  "data": [
    {
      "account_id": "MA_XXXXXXXX",
      "answer_time": "2026-03-25T10:00:08Z",
      "billsec": 177,
      "bridge_uuid": "aabbccdd-1234-5678-90ab-cdef12345678",
      "call_direction": "outbound",
      "caller_id_name": "John Doe",
      "caller_id_number": "+919876543210",
      "campaign_id": null,
      "carrier_ip": "10.0.0.1",
      "codec": "PCMU",
      "context": "voice-api",
      "cost": 0.45,
      "created_at": "2026-03-25T10:03:05Z",
      "currency": "INR",
      "customer_endpoint": null,
      "destination_number": "+918012345678",
      "duration": 185,
      "end_time": "2026-03-25T10:03:05Z",
      "failure_code": null,
      "failure_reason": null,
      "hangup_cause": "NORMAL_CLEARING",
      "hangup_cause_code": 4000,
      "hangup_cause_name": "Normal Hangup",
      "hangup_disposition": "send_bye",
      "hangup_source": "Caller",
      "id": 18000000,
      "jitter": 2,
      "mos": 4.5,
      "network_addr": "10.0.0.2",
      "origination_region": "mumbai",
      "packet_loss": 0,
      "progress_time": "2026-03-25T10:00:00Z",
      "region": "ap-south-1",
      "ring_time": 8,
      "sip_call_id": "aabbccdd-1234-5678-90ab-cdef12345678",
      "sip_user_agent": "Vobiz",
      "start_time": "2026-03-25T10:00:00Z",
      "streaming_cost": 0,
      "terminated_to": null,
      "total_cost": 0.45,
      "trunk_id": null,
      "updated_at": "2026-03-25T10:03:05Z",
      "uuid": "aabbccdd-1234-5678-90ab-cdef12345678"
    },
    {
      "account_id": "MA_XXXXXXXX",
      "answer_time": "2026-03-25T11:15:04Z",
      "billsec": 42,
      "bridge_uuid": "11223344-5566-7788-99aa-bbccddeeff00",
      "call_direction": "outbound",
      "caller_id_name": "",
      "caller_id_number": "+919876543210",
      "campaign_id": null,
      "carrier_ip": "10.0.0.1",
      "codec": "PCMU",
      "context": "voice-api",
      "cost": 0.12,
      "created_at": "2026-03-25T11:15:46Z",
      "currency": "INR",
      "customer_endpoint": null,
      "destination_number": "+918012345678",
      "duration": 46,
      "end_time": "2026-03-25T11:15:46Z",
      "failure_code": null,
      "failure_reason": null,
      "hangup_cause": "NORMAL_CLEARING",
      "hangup_cause_code": 4000,
      "hangup_cause_name": "Normal Hangup",
      "hangup_disposition": "send_bye",
      "hangup_source": "Callee",
      "id": 18000001,
      "jitter": 1,
      "mos": 4.4,
      "network_addr": "10.0.0.2",
      "origination_region": "mumbai",
      "packet_loss": 0,
      "progress_time": "2026-03-25T11:15:00Z",
      "region": "ap-south-1",
      "ring_time": 4,
      "sip_call_id": "11223344-5566-7788-99aa-bbccddeeff00",
      "sip_user_agent": "Vobiz",
      "start_time": "2026-03-25T11:15:00Z",
      "streaming_cost": 0,
      "terminated_to": null,
      "total_cost": 0.12,
      "trunk_id": null,
      "updated_at": "2026-03-25T11:15:46Z",
      "uuid": "11223344-5566-7788-99aa-bbccddeeff00"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 1284,
    "pages": 65,
    "has_next": true,
    "has_prev": false
  },
  "summary": {
    "answerRate": 48.2,
    "answeredCalls": 619,
    "avgCallDuration": "28s",
    "last_call_at": "2026-03-25T11:15:00Z",
    "totalCalls": 1284,
    "total_billable_seconds": 17428,
    "total_cost": 312.85,
    "total_duration_seconds": 35952
  }
}
```

## Get Specific CDR by UUID

Returns complete detail for a single call identified by its UUID. Use this when a customer reports a specific call issue - pass the call UUID from their system or from a previous CDR list query. This endpoint exposes the full call metadata, including SIP response codes and media quality indicators where available.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/cdrs/abc123-def456-ghi789" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```json theme={null}
{
  "account_id": "MA_XXXXXXXX",
  "answer_time": "2026-03-25T10:00:08Z",
  "billsec": 177,
  "bridge_uuid": "aabbccdd-1234-5678-90ab-cdef12345678",
  "call_direction": "outbound",
  "caller_id_name": "John Doe",
  "caller_id_number": "+919876543210",
  "campaign_id": null,
  "carrier_ip": "10.0.0.1",
  "codec": "PCMU",
  "context": "voice-api",
  "cost": 0.45,
  "created_at": "2026-03-25T10:03:05Z",
  "currency": "INR",
  "customer_endpoint": null,
  "destination_number": "+918012345678",
  "duration": 185,
  "end_time": "2026-03-25T10:03:05Z",
  "failure_code": null,
  "failure_reason": null,
  "hangup_cause": "NORMAL_CLEARING",
  "hangup_cause_code": 4000,
  "hangup_cause_name": "Normal Hangup",
  "hangup_disposition": "send_bye",
  "hangup_source": "Caller",
  "id": 18000000,
  "jitter": 2,
  "mos": 4.5,
  "network_addr": "10.0.0.2",
  "origination_region": "mumbai",
  "packet_loss": 0,
  "progress_time": "2026-03-25T10:00:00Z",
  "region": "ap-south-1",
  "ring_time": 8,
  "sip_call_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "sip_user_agent": "Vobiz",
  "start_time": "2026-03-25T10:00:00Z",
  "streaming_cost": 0,
  "terminated_to": null,
  "total_cost": 0.45,
  "trunk_id": null,
  "updated_at": "2026-03-25T10:03:05Z",
  "uuid": "aabbccdd-1234-5678-90ab-cdef12345678"
}
```

## All CDRs (Global)

Global CDR log across all customer accounts under your partner umbrella, returned as a single paginated response. Supports all the same filter parameters as the per-customer endpoint. Use for platform-wide traffic monitoring and identifying customers with unusual call patterns.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/cdrs?page=1&per_page=50" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/cdrs?status=failed&start_date=2026-03-25&per_page=100" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

## Response shape

The list response wraps the records in a fixed envelope:

| Field | Notes |
| - | - |
| `success` | Always `true` on a `200`. |
| `account_id` / `account_auth_id` | The customer the CDRs belong to. |
| `count` | Number of records in this page's `data` array. |
| `data[]` | The CDR rows. Key per-row fields: `uuid`, `call_direction`, `caller_id_number`, `destination_number`, `duration` (total seconds), `billsec` (billable seconds), `cost` / `total_cost`, `hangup_cause`, `mos` (call quality), `start_time` / `answer_time` / `end_time`. |
| `pagination` | `page`, `per_page`, `total`, `pages`, `has_next`, `has_prev`. |
| `summary` | Window aggregates: `totalCalls`, `answeredCalls`, `answerRate`, `avgCallDuration`, `total_billable_seconds`, `total_duration_seconds`, `total_cost`, `last_call_at`. |

<Note>
  For billing, multiply each row's **`billsec`** (billable seconds), not raw `duration`, by your per-minute rate - or simply read `summary.total_cost`, which Vobiz has already computed at the customer's pricing tier.
</Note>

## Use Cases

* **Per-customer billing** - Pull CDRs for a customer for the billing period. Use `summary.total_cost` for the period total, or sum `billsec` across rows if you apply your own markup.
* **Call quality troubleshooting** - When a customer reports poor call quality, pull the specific CDR by UUID. Check `hangup_cause`, `mos`, `jitter`, and `packet_loss` for the root cause.
* **No-answer rate monitoring** - Filter by `status=no_answer` over the past 7 days. High no-answer rates indicate number configuration issues or customer routing problems.
* **Fraud detection** - Watch for abnormal call volumes or unusual call durations in the global CDR feed. Spikes in short-duration outbound calls can indicate robocalling abuse.


## OpenAPI

````yaml GET /api/v1/partner/accounts/{customer_auth_id}/cdrs
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
  /api/v1/partner/accounts/{customer_auth_id}/cdrs:
    get:
      tags:
        - Partner API
      summary: List customer CDRs
      description: |
        Look up any customer's call history. Same filter set as the
        customer-side CDR endpoint.
      operationId: list-customer-cdrs
      parameters:
        - name: customer_auth_id
          in: path
          required: true
          schema:
            type: string
        - name: start_date
          in: query
          schema:
            type: string
            format: date
        - name: end_date
          in: query
          schema:
            type: string
            format: date
        - name: call_direction
          in: query
          schema:
            type: string
            enum:
              - inbound
              - outbound
        - name: status
          in: query
          schema:
            type: string
            enum:
              - answered
              - failed
              - busy
              - no_answer
        - name: min_duration
          in: query
          schema:
            type: integer
        - name: hangup_cause
          in: query
          schema:
            type: string
            example: NO_ANSWER
        - name: per_page
          in: query
          schema:
            type: integer
            default: 20
      responses:
        '200':
          description: Customer CDRs
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
                        type: integer
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
                        type: integer
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
                  account_auth_id:
                    type: string
                required:
                  - account_id
                  - count
                  - data
                  - pagination
                  - success
                  - summary
                  - account_auth_id
              example:
                success: true
                account_id: MA_XXXXXXXX
                account_auth_id: MA_XXXXXXXX
                count: 2
                data:
                  - account_id: MA_XXXXXXXX
                    answer_time: '2026-03-25T06:59:31Z'
                    billsec: 1
                    bridge_uuid: aabbccdd-1234-5678-90ab-cdef12345678
                    call_direction: outbound
                    caller_id_name: Acme Corp
                    caller_id_number: '+918012345678'
                    campaign_id: null
                    carrier_ip: null
                    codec: PCMU
                    context: voice-api
                    cost: 0.3
                    created_at: '2026-03-25T06:59:32Z'
                    currency: INR
                    customer_endpoint: null
                    destination_number: '+919876543210'
                    duration: 6
                    end_time: '2026-03-25T06:59:32Z'
                    failure_code: null
                    failure_reason: null
                    hangup_cause: NORMAL_CLEARING
                    hangup_cause_code: 4000
                    hangup_cause_name: Normal Hangup
                    hangup_disposition: send_bye
                    hangup_source: Caller
                    id: 18600001
                    jitter: 0
                    mos: 4.5
                    network_addr: 3.110.99.6
                    origination_region: mumbai
                    packet_loss: 0
                    progress_time: '2026-03-25T06:59:26Z'
                    region: ap-south-1
                    ring_time: 5
                    sip_call_id: 11223344-1234-5678-90ab-cdef12345678
                    sip_user_agent: Vobiz
                    start_time: '2026-03-25T06:59:26Z'
                    streaming_cost: 0
                    terminated_to: null
                    total_cost: 0.3
                    trunk_id: null
                    updated_at: '2026-03-25T06:59:32Z'
                    uuid: 55667788-1234-5678-90ab-cdef12345678
                  - account_id: MA_XXXXXXXX
                    answer_time: '2026-03-25T07:10:11Z'
                    billsec: 4
                    bridge_uuid: 99887766-1234-5678-90ab-cdef12345678
                    call_direction: inbound
                    caller_id_name: '+919876543210'
                    caller_id_number: '+919876543210'
                    campaign_id: null
                    carrier_ip: null
                    codec: PCMU
                    context: voice-api
                    cost: 0.45
                    created_at: '2026-03-25T07:10:15Z'
                    currency: INR
                    customer_endpoint: null
                    destination_number: '+918012345678'
                    duration: 9
                    end_time: '2026-03-25T07:10:15Z'
                    failure_code: null
                    failure_reason: null
                    hangup_cause: NORMAL_CLEARING
                    hangup_cause_code: 4010
                    hangup_cause_name: End Of XML Instructions
                    hangup_disposition: send_bye
                    hangup_source: Vobiz
                    id: 18600002
                    jitter: 0
                    mos: 4.5
                    network_addr: 13.203.7.132
                    origination_region: mumbai
                    packet_loss: 0
                    progress_time: '2026-03-25T07:10:06Z'
                    region: ap-south-1
                    ring_time: 5
                    sip_call_id: aabbccdd-1234-5678-90ab-cdef12345678
                    sip_user_agent: Vobiz
                    start_time: '2026-03-25T07:10:06Z'
                    streaming_cost: 0
                    terminated_to: null
                    total_cost: 0.45
                    trunk_id: null
                    updated_at: '2026-03-25T07:10:15Z'
                    uuid: aabbccdd-9999-5678-90ab-cdef12345678
                pagination:
                  page: 1
                  per_page: 20
                  total: 2
                  pages: 1
                  has_next: false
                  has_prev: false
                summary:
                  answerRate: 100
                  answeredCalls: 2
                  avgCallDuration: 7s
                  last_call_at: '2026-03-25T07:10:15Z'
                  totalCalls: 2
                  total_billable_seconds: 15
                  total_cost: 1
                  total_duration_seconds: 15
components:
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