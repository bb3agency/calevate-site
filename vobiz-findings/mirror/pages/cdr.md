> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Call Detail Records (CDR) API – Call Logs & Billing Analytics

> Query, filter, and export Vobiz CDRs with per-call billing data, MOS scores, jitter, hangup attribution, and CSV export - for reconciliation, fraud detection, and TRAI compliance reporting.

Retrieve detailed call logs, billing data, and per-call telemetry for your account. Vobiz CDRs include caller/callee identifiers, timing, billing, hangup attribution, and quality metrics (MOS, jitter, packet loss). Use them for billing reconciliation, traffic analysis, fraud detection, and compliance reporting.

<Info>
  **Authentication:** All CDR endpoints use API key authentication. Pass `X-Auth-ID` and `X-Auth-Token` in your request headers.
</Info>

## Endpoints Overview

| Method | Endpoint | Description |
| - | - | - |
| GET | `/api/v1/Account/{auth_id}/cdr` | List CDRs with filters + pagination + summary |
| GET | `/api/v1/Account/{auth_id}/cdr/{call_id}` | Fetch a single CDR by call ID |
| GET | `/api/v1/Account/{auth_id}/cdr/search` | Same as list, also echoes active filters in `filters` |
| GET | `/api/v1/Account/{auth_id}/cdr/recent` | Get the most recent CDRs (last 20 by default) |
| GET | `/api/v1/Account/{auth_id}/cdr/export` | Export CDRs as a CSV file |

## List CDRs

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr
```

Returns CDRs for your account. Supports filtering by phone numbers, date range, call direction, duration, and pagination. Response includes a `summary` block with aggregate metrics across the filtered set.

<CodeGroup>
  ```bash cURL theme={null}
  curl -X GET \
    "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr?start_date=2026-03-01&end_date=2026-03-17" \
    --header 'X-Auth-ID: {auth_id}' \
    --header 'X-Auth-Token: {auth_token}' \
    --header 'Accept: application/json'
  ```

  ```javascript Node theme={null}
  const r = await fetch(
    'https://api.vobiz.ai/api/v1/Account/AUTH_ID/cdr?start_date=2026-03-01&end_date=2026-03-17',
    { headers: { 'X-Auth-ID': 'AUTH_ID', 'X-Auth-Token': 'AUTH_TOKEN' } }
  );
  console.log(await r.json());
  ```

  ```python Python theme={null}
  import requests
  r = requests.get(
      "https://api.vobiz.ai/api/v1/Account/AUTH_ID/cdr",
      params={"start_date": "2026-03-01", "end_date": "2026-03-17"},
      headers={"X-Auth-ID": "AUTH_ID", "X-Auth-Token": "AUTH_TOKEN"},
  )
  print(r.json())
  ```
</CodeGroup>

## Get Single CDR

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/{call_id}
```

Retrieve full detail for a specific call by its `call_id`. Useful when you have a `call_id` from a webhook callback or previous list response.

```bash cURL theme={null}
curl --location 'https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/{call_id}' \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}' \
  --header 'Accept: application/json'
```

## Search CDRs

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/search
```

Identical filters to the list endpoint, but the response also includes a `filters` object echoing the active filters applied. Useful when building search UIs that need to display current filter state.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/search?call_direction=outbound&page=1&per_page=50" \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}' \
  --header 'Accept: application/json'
```

## Recent CDRs

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/recent
```

Returns the most recent CDRs for your account without requiring a date range. Returns 20 records by default. Use `limit` to retrieve more. **Note:** the recent endpoint does not return `pagination` or `summary` blocks - just `data`.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/recent?limit=50" \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}' \
  --header 'Accept: application/json'
```

## Export as CSV

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/export
```

Returns CDR data as a downloadable CSV file. Supports the same filters as the list endpoint. Use the `-o` flag in curl to save directly to a file.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/export?start_date=2026-03-01&end_date=2026-03-17" \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}' \
  -o cdrs.csv
```

<Warning>
  The export endpoint returns `text/csv` content. Do **not** send `Accept: application/json` on this request.
</Warning>

## Query Parameters

### Filter Parameters (list, search, export)

| Parameter | Type | Description |
| - | - | - |
| `from_number` | string | Filter by the originating phone number (caller). |
| `to_number` | string | Filter by the destination phone number (callee). |
| `start_date` | string (YYYY-MM-DD) | Beginning of the search period. Required when using `end_date`. |
| `end_date` | string (YYYY-MM-DD) | End of the search period. Required when using `start_date`. |
| `call_direction` | string | `inbound` or `outbound`. |
| `min_duration` | integer | Minimum call duration in seconds. |
| `page` | integer | Page number for paginated results. Default: 1. *(list, search only)* |
| `per_page` | integer | Records per page. Default: 20. Max: 100. *(list, search only)* |
| `limit` | integer | Number of records to return. Default: 20. *(recent only)* |

## Response Structure

A successful list/search request returns:

```json 200 OK - Response theme={null}
{
  "account_id": "MA_ZRTEMCF7",
  "count": 20,
  "data": [
    {
      "id": 18623590,
      "uuid": "bcd1c45d-3f27-41ea-bea1-aa5d4e06dca4",
      "account_id": "MA_ZRTEMCF7",
      "call_direction": "outbound",
      "caller_id_name": "919148227303",
      "caller_id_number": "+918065480214",
      "destination_number": "+919876543210",
      "duration": 6,
      "billsec": 1,
      "ring_time": 5,
      "answer_time": "2026-05-11T06:59:31Z",
      "start_time": "2026-05-11T06:59:26Z",
      "end_time": "2026-05-11T06:59:32Z",
      "progress_time": "2026-05-11T06:59:26Z",
      "created_at": "2026-05-11T06:59:32Z",
      "updated_at": "2026-05-11T06:59:32Z",
      "cost": 0.3,
      "total_cost": 0.3,
      "streaming_cost": 0,
      "currency": "INR",
      "hangup_cause": "NORMAL_CLEARING",
      "hangup_cause_code": 4000,
      "hangup_cause_name": "Normal Hangup",
      "hangup_disposition": "send_bye",
      "hangup_source": "Caller",
      "failure_code": null,
      "failure_reason": null,
      "bridge_uuid": "9e9c108c-6e88-4aad-ad62-cee335b8752c",
      "sip_call_id": "15ad2006-1986-451b-87da-43676cfd8266",
      "sip_user_agent": "Vobiz",
      "codec": "PCMU",
      "mos": 4.5,
      "jitter": 0,
      "packet_loss": 0,
      "network_addr": "3.110.99.6",
      "carrier_ip": null,
      "context": "voice-api",
      "region": "ap-south-1",
      "origination_region": "mumbai",
      "campaign_id": null,
      "customer_endpoint": null,
      "trunk_id": null,
      "terminated_to": null
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 4500,
    "pages": 225,
    "has_next": true,
    "has_prev": false
  },
  "summary": {
    "totalCalls": 4500,
    "answeredCalls": 2171,
    "answerRate": 48.2,
    "avgCallDuration": "28s",
    "total_duration_seconds": 118234,
    "total_billable_seconds": 61211,
    "total_cost": 1564.51,
    "last_call_at": "2026-05-11T06:59:26Z"
  },
  "success": true
}
```

### Top-level fields

| Field | Type | Description |
| - | - | - |
| `account_id` | string | Echo of the account this CDR set belongs to. |
| `count` | integer | Number of records in `data`. |
| `data` | array | Array of CDR objects (see below). |
| `pagination` | object | Pagination metadata. Present on `list` and `search`; absent on `recent`. |
| `summary` | object | Aggregate metrics across the filtered set. Present on `list` and `search`. |
| `filters` | object | *(search only)* Echo of the active filter values applied to this request. |
| `success` | boolean | `true` on a successful response. |

### Pagination object

| Field | Type | Description |
| - | - | - |
| `page` | integer | Current page. |
| `per_page` | integer | Records per page. |
| `total` | integer | Total matching records across all pages. |
| `pages` | integer | Total number of pages. |
| `has_next` | boolean | `true` if a next page exists. |
| `has_prev` | boolean | `true` if a previous page exists. |

### Summary object

| Field | Type | Description |
| - | - | - |
| `totalCalls` | integer | Total calls in the filtered set. |
| `answeredCalls` | integer | Calls that were answered (billsec > 0). |
| `answerRate` | number | Percentage of calls answered. |
| `avgCallDuration` | string | Average duration as a human-readable string (e.g. `"28s"`). |
| `total_duration_seconds` | integer | Sum of all `duration` values. |
| `total_billable_seconds` | integer | Sum of all `billsec` values. |
| `total_cost` | number | Sum of all `total_cost` values in `currency`. |
| `last_call_at` | string (ISO 8601) | Timestamp of the most recent call in the set. |

### CDR object - every field

| Field | Type | Description |
| - | - | - |
| `id` | integer | Internal numeric identifier for the call. |
| `uuid` | string (UUID) | Globally unique identifier for the call. |
| `account_id` | string | Account that owns this call. |
| `call_direction` | string | `inbound` or `outbound`. |
| `caller_id_name` | string | Caller ID display name. |
| `caller_id_number` | string | Originating phone number (E.164 format). |
| `destination_number` | string | Destination phone number or destination identifier. |
| `duration` | integer | Total call duration in seconds (ring + talk). |
| `billsec` | integer | Billable seconds (talk time only). |
| `ring_time` | integer | Time the call rang before answer or hangup, in seconds. |
| `answer_time` | string (ISO 8601) \| null | When the call was answered. `null` if not answered. |
| `start_time` | string (ISO 8601) | When the call was initiated. |
| `end_time` | string (ISO 8601) | When the call ended. |
| `progress_time` | string (ISO 8601) | When the call entered the progress state. |
| `created_at` | string (ISO 8601) | CDR record creation timestamp. |
| `updated_at` | string (ISO 8601) | CDR record last-updated timestamp. |
| `cost` | number | Per-leg cost in `currency`. |
| `total_cost` | number | Total cost including streaming, in `currency`. |
| `streaming_cost` | number | Cost of audio streaming for this call (if used). |
| `currency` | string | ISO currency code, e.g. `INR`. |
| `hangup_cause` | string | High-level hangup reason (e.g. `NORMAL_CLEARING`). See the full list below. |
| `hangup_cause_code` | integer | Numeric hangup code. |
| `hangup_cause_name` | string | Human-readable hangup name. |
| `hangup_disposition` | string | SIP hangup disposition (e.g. `send_bye`, `recv_bye`). |
| `hangup_source` | string | Which party initiated the hangup (`Caller`, `Callee`, etc.). **Not reliable on conference legs** - see the warning below. |

<Warning>
  **`hangup_source` cannot distinguish a platform teardown from a participant
  hangup on conference legs.**

  A leg removed by another member's `endConferenceOnExit` receives no hangup
  attribution, so it falls through to the default and reports as
  `NORMAL_CLEARING` / `4000` / `Callee` - identical to the participant having hung
  up themselves.

  If you reconcile disconnections from `hangup_source`, correlate against
  `ConferenceExit` callbacks rather than trusting the CDR field alone. See
  [Conference attributes](/docs/xml/conference/attributes).
</Warning>

\| `failure_code` | string | null | Failure code if the call did not connect. |
\| `failure_reason` | string | null | Human-readable failure reason. |
\| `bridge_uuid` | string (UUID) | null | UUID of the call bridge. |
\| `sip_call_id` | string | SIP-level Call-ID header value. |
\| `sip_user_agent` | string | SIP User-Agent header value of the originating leg. |
\| `codec` | string | null | Audio codec negotiated (e.g. `PCMU`, `PCMA`, `opus`). |
\| `mos` | number | Mean Opinion Score (call audio quality, 1.0–5.0). |
\| `jitter` | number | Jitter in milliseconds. |
\| `packet_loss` | number | Packet loss percentage. |
\| `network_addr` | string | Network address of the call leg. |
\| `carrier_ip` | string | null | Carrier IP address. |
\| `context` | string | Internal call context (e.g. `voice-api`). |
\| `region` | string | Vobiz infrastructure region (e.g. `ap-south-1`). |
\| `origination_region` | string | Region the call originated from. |
\| `campaign_id` | string | null | Campaign ID if the call is part of a campaign. |
\| `customer_endpoint` | string | null | Customer endpoint identifier. |
\| `trunk_id` | string | null | SIP trunk ID used for this call. |
\| `terminated_to` | string | null | Termination target if forwarded. |

## Hangup Causes

The table below describes common SIP/B2BUA `hangup_cause` values you may encounter in your call logs.

| `hangup_cause` | Description |
| - | - |
| `NORMAL_CLEARING` | One of the parties hung up normally. |
| `USER_BUSY` | The called party is busy (e.g., already on another call or declined). |
| `NO_ANSWER` | The called party did not answer within the timeout period. |
| `ORIGINATOR_CANCEL` | The caller cancelled the call before it was answered. |
| `CALL_REJECTED` | The destination explicitly rejected the call. |
| `REJECTED` | General rejection - the SIP endpoint refused the INVITE. |
| `INVALID_NUMBER` | The dialed number format is invalid. |
| `UNALLOCATED_NUMBER` | The dialed number is valid but not allocated to any subscriber. |
| `SERVICE_UNAVAILABLE` | The destination service is temporarily unavailable (SIP 503). |
| `SERVER_ERROR` | An internal server error occurred during call setup. |
| `MEDIA_TIMEOUT` | No RTP media packets received - likely a firewall or network issue. |
| `PROTOCOL_ERROR` | A SIP protocol violation or malformed message. |
| `NETWORK_OUT_OF_ORDER` | A severe network failure prevented routing. |
| `DESTINATION_OUT_OF_ORDER` | The destination endpoint cannot accept the call. |
| `NORMAL_TEMPORARY_FAILURE` | Generic temporary failure; retrying may succeed. |
| `SWITCH_CONGESTION` | The SIP switch is at capacity. |
| `UNKNOWN` | An error not mapped to a standard cause code. |

## Examples

### Filter by date range

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr?start_date=2026-03-01&end_date=2026-03-17" \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}'
```

### Outbound calls only, minimum 10 seconds

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr?call_direction=outbound&min_duration=10&page=1&per_page=20" \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}'
```

### Last 50 recent calls

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/recent?limit=50" \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}'
```

### Export filtered CDRs to CSV

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/export?start_date=2026-03-01&end_date=2026-03-17" \
  --header 'X-Auth-ID: {auth_id}' \
  --header 'X-Auth-Token: {auth_token}' \
  -o cdrs.csv
```

## What to do next

* [Call recordings](/docs/recording) - Access audio recordings for completed calls
* [Trunk webhooks](/docs/trunks/webhook) - Receive real-time call events instead of polling CDRs
* [Error handling](/docs/errors) - Map `hangup_cause` and SIP response codes to specific failure reasons
* [Audio streaming](/docs/audio-streams) - Stream live call audio to your server in real time

## Diagnose a hangup\_cause with an AI agent

<Prompt description="Paste a CDR or a hangup_cause code - get a plain-English diagnosis and remediation steps." icon="stethoscope" actions={["copy", "cursor"]}>
  Using the Vobiz MCP at `https://vobiz.ai/docs/mcp`:

  1. Read the `vobiz-cdr` skill from `mintlify://skills/cdr`.
  2. Use `query_docs_filesystem_vobiz` to `head -300 /cdr.mdx` and find the hangup\_cause table.
  3. Ask me to paste a single CDR JSON object (or just a `hangup_cause` value like `"USER_BUSY"` plus optional `hangup_cause_code` and `failure_reason`).
  4. Output a structured diagnosis:
     * **What it means**: 1-sentence plain English explanation of that hangup\_cause.
     * **Who hung up**: was it the caller, callee, or carrier? (Use `hangup_source` if present, but see the conference caveat below.)
     * **Likely root cause**: based on `hangup_cause_code`, `failure_code`, `failure_reason`, `mos`, `jitter`, `packet_loss`, `codec`.
     * **What to check next**: concrete remediation steps (DLT registration, DND scrubbing, carrier IP whitelist, MOS thresholds, etc.).
     * **Related fields to inspect** in the same CDR.
  5. If MOS \< 3.5 or jitter > 30ms or packet\_loss > 1%, flag a quality issue separately from the hangup cause.
</Prompt>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.