> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Export CDRs as CSV

> Export Vobiz call detail records as a CSV file for billing reconciliation, compliance auditing, and traffic analysis - returns text/csv content directly.

<Warning>
  The export endpoint returns `text/csv` content. Do **not** send `Accept: application/json` on this request - pipe the response directly to a file with `curl -o cdrs.csv`.
</Warning>

Export streams the matching CDRs as a CSV file - one row per call - for billing reconciliation, compliance auditing, and offline analysis.

## Filters

Export accepts the **same filters as the list endpoint, minus paging**. There is no `page` or `per_page`; the file contains every matching row.

| Parameter | Type | Notes |
| - | - | - |
| `from_number` | string | Originating (caller) number. Substring or full E.164. |
| `to_number` | string | Destination (callee) number. |
| `start_date` | string `YYYY-MM-DD` | Required together with `end_date`. |
| `end_date` | string `YYYY-MM-DD` | Required together with `start_date`. |
| `call_direction` | enum | `inbound` or `outbound`. |
| `min_duration` | integer | Seconds; excludes shorter calls. |

<Tip>
  Because there is no paging, always scope the export with `start_date`/`end_date` (and any other filter) to keep the file size manageable for high-volume accounts.
</Tip>

## Response

* Content type is `text/csv`. The columns mirror the CDR object fields (see the [field glossary](/docs/cdr)).
* An empty match still returns `200` with a header-only (or empty) CSV body - not a `404`.

## Example

```bash cURL theme={null}
curl -G "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/export" \
  --data-urlencode "start_date=2026-03-01" \
  --data-urlencode "end_date=2026-03-17" \
  --data-urlencode "call_direction=outbound" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -o cdrs.csv
```

<Note>
  To receive a large recordings archive by email instead of a synchronous CSV, see [Export Historical Recordings](/docs/recording/export-historical-recordings). For per-call JSON, use [List CDRs](/docs/cdr/list-cdrs).
</Note>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/cdr/export
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
  /api/v1/Account/{auth_id}/cdr/export:
    get:
      tags:
        - CDR
      summary: Export CDRs as CSV
      description: >
        Returns CDR data as a downloadable CSV file. Same filters as the list
        endpoint.


        **Note:** Do NOT send `Accept: application/json` on this endpoint - the
        response is `text/csv`.
      operationId: export-cdrs
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
      responses:
        '200':
          description: CSV file containing CDR rows
          content:
            text/csv:
              schema:
                type: string
                format: binary
            application/json:
              schema:
                type: string
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