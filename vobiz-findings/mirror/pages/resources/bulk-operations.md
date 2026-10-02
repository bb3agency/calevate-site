> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bulk and batch operations

> Every bulk and batch capability in Vobiz in one place - multi-destination bulk dialing, batch CSV campaigns, bulk CDR and recording exports, batched WhatsApp broadcasts, and bulk contact import.

This page collects every bulk and batch capability Vobiz exposes, so you can pick the right one without reading each product section. Each entry gives the endpoint, how results come back, and the limits stated on its detailed page.

## At a glance

| Capability | Endpoint | Host | Results |
| - | - | - | - |
| Bulk outbound dialing | `POST /api/v1/Account/{auth_id}/Call/` | `api.vobiz.ai` | Synchronous `200`, per-destination UUIDs via callbacks |
| Batch campaign dialing | `POST /api/v1/account/{account_id}/campaigns/{campaign_id}/upload` | `api.vobiz.ai` | Upload summary, then results CSV |
| Bulk CDR export | `GET /api/v1/Account/{auth_id}/cdr/export` | `api.vobiz.ai` | Synchronous `text/csv` download |
| Bulk recording export | `POST /api/v1/Account/{auth_id}/export/recording/` | `api.vobiz.ai` | `202 Accepted`, archive link emailed |
| Batched WhatsApp broadcast | `POST /api/v1/messaging/campaigns` | `api.vobiz.ai` | Per-recipient status endpoint |
| Bulk contact import | `POST /api/v1/messaging/contacts/import` | `api.vobiz.ai` | Synchronous `200` with row counts |

## Bulk outbound dialing

Fan a single request out to many destinations. Separate destinations in the `to` field with `<`, up to 1000 destinations per request. Each destination can be a PSTN number or a SIP URI.

```bash cURL theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "14155551234",
    "to": "14157654321<14153464321<sip:john1234@api.vobiz.ai",
    "answer_url": "https://example.com/answer",
    "answer_method": "POST"
  }'
```

* **Limit:** 1000 destinations per request. A `to` value above that returns `400 Bad Request`.
* **Separator:** use `<`. A comma is treated as part of a single destination.
* **Results:** the `200` response carries one `request_uuid` for the request. Each destination is delivered its own UUID through the `ring_url`, `answer_url`, and `hangup_url` callbacks.
* **Pacing:** `429 Too Many Requests` indicates you exceeded your calls-per-second or concurrent-call limit. Spread bulk dials over time and retry with jitter.

Monitor what is still pending with [Retrieve All Queued Calls](/docs/call/retrieve-all-queued-calls), which returns up to 20 call UUIDs.

See [Make an Outbound Call](/docs/call/make-call) for the full parameter set.

## Batch campaign dialing from a CSV

For list-driven outbound dialing with retries, scheduling, caller-ID rotation, and concurrency control, use the Voice Campaign Manager. It runs on `https://api.vobiz.ai` and authenticates with the same `X-Auth-ID` and `X-Auth-Token` headers as the rest of the API - see [Campaign API authentication](/docs/campaign-manager/authentication).

Upload contacts as `multipart/form-data` with the CSV in a field named `file`.

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/upload" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -F "file=@contacts.csv"
```

* **Size:** there is no hard row limit. Uploads above 500,000 rows produce an advisory warning.
* **Concurrency:** a campaign's `max_concurrent` is at least `1` and no higher than your account concurrency limit.
* **Replacement:** re-uploading on a `ready` campaign replaces every existing contact. Upload returns `409` while a campaign is `running`, `paused`, or `queued`.
* **Results:** `GET /campaigns/{campaign_id}/results` returns a CSV of contact outcomes, and is available while the campaign is still running, so partial exports work.
* **Attempts:** `GET /campaigns/{campaign_id}/calls` pages attempts with `page` and `per_page`, where `per_page` has a maximum of `200`.

The upload response summarises the batch:

```json 200 OK theme={null}
{
  "valid_contacts": 980,
  "invalid_rows": 20,
  "total_rows": 1000,
  "custom_headers_detected": ["CustomerID", "LeadScore"]
}
```

See [Campaign contacts and results](/docs/campaign-manager/contacts/upload-contacts) for the CSV column rules and [Voice Campaign Manager API](/docs/campaign-manager/overview) for the surrounding lifecycle.

## Bulk CDR export

Export every call detail record matching your filters as a single CSV file. This one is synchronous: the response body is the file.

```bash cURL theme={null}
curl -G "https://api.vobiz.ai/api/v1/Account/{auth_id}/cdr/export" \
  --data-urlencode "start_date=2026-03-01" \
  --data-urlencode "end_date=2026-03-17" \
  --data-urlencode "call_direction=outbound" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -o cdrs.csv
```

* **Filters:** the same filters as the list endpoint, minus paging. There is no `page` or `per_page` - the file contains every matching row, so scope it with `start_date` and `end_date`.
* **Content type:** the response is `text/csv`. Do not send `Accept: application/json` on this request.
* **Empty match:** returns `200` with a header-only or empty CSV body.

To pull CDRs as JSON in batches instead, [List CDRs](/docs/cdr/list-cdrs) pages with `per_page` up to `100`.

See [Export CDRs as CSV](/docs/cdr/export-cdrs).

## Bulk recording export

Package historical recordings matching a filter into a downloadable archive. This runs as a background job and returns `202 Accepted` immediately.

```bash cURL theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/export/recording/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "2026-03-01 00:00:00",
    "to": "2026-03-17 23:59:59",
    "recipient": {
      "customer_account": ["admin@example.com"]
    }
  }'
```

* **Delivery:** the archive download link is emailed to every address in `recipient.customer_account`, typically within 15-60 minutes depending on volume. Completion is signalled by that email rather than by a status endpoint, so treat the recipient inbox as the job's completion channel.
* **Concurrency:** one export runs at a time per account. A second request while one is in progress returns `403 Forbidden`.
* **Range limits:** maximum date range is 1 year (366 days). Maximum storage duration range is 30 days.
* **Filters:** the additional filters (`from_number`, `to_number`, `call_uuid`, `conference_name`, `recording_format`, `recording_id`) apply when the date or storage duration range is 30 days or less. For longer ranges, export in smaller batches.

See [Export Historical Recordings](/docs/recording/export-historical-recordings) for the full filter matrix and validation rules.

## Batched WhatsApp broadcast

A WhatsApp campaign sends an approved template to a resolved audience, delivering it in batches. Target the audience with `audience_type: "tags"` plus `audience_tags`, or `audience_type: "contact_ids"` plus `audience_contact_ids`.

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/campaigns" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
    "name": "Welcome Campaign",
    "template_id": "9d8f1e2a-4c3b-4a1d-8e7f-1a2b3c4d5e6f",
    "template_components": [
      { "type": "body", "parameters": [{ "type": "text", "text": "{{1}}" }] }
    ],
    "audience_type": "tags",
    "audience_tags": ["vip"]
  }'
```

* **Batching:** the campaign object reports `batch_size` (recipients per batch) and `batch_delay_ms` (delay between batches).
* **Results:** `GET /api/v1/messaging/campaigns/{id}/recipients` returns per-contact delivery status, filterable with `status` and paged with `page` and `limit`. The campaign object also carries `total_recipients`, `sent_count`, `delivered_count`, `read_count`, `failed_count`, and `skipped_count`.
* **Control:** `POST /campaigns/{id}/pause`, `/resume`, and `/cancel` operate on the whole batch mid-send.
* **Listing:** `GET /api/v1/messaging/campaigns` pages with `limit` up to `100`.

See [Campaigns API](/docs/whatsapp/api/campaigns).

## Bulk contact import

Import a WhatsApp contact list from CSV as `multipart/form-data`, with the file under the form field named `file`. The CSV needs `phone_number` and `name` columns; `tags` (comma-separated) is optional.

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/contacts/import" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -F "file=@/path/to/contacts.csv"
```

The response summarises the batch synchronously, and lists each failed row in `errors`:

```json 200 OK theme={null}
{
  "total": 2,
  "created": 1,
  "updated": 1,
  "failed": 0,
  "errors": []
}
```

See [Contacts API](/docs/whatsapp/api/contacts).

## Bulk control operations

Two endpoints act on every matching resource in one request rather than moving data in bulk.

| Operation | Endpoint | Scope |
| - | - | - |
| Hang up all conferences | `DELETE /api/v1/Account/{auth_id}/Conference/` | Every ongoing conference on the account |
| Stop all audio streams | `DELETE /api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/` | Every active stream on one call |

Both are destructive. Hanging up all conferences disconnects every member across all active conference instances - see [Hang Up All Conferences](/docs/conference/hang-up-all-conferences). Stopping all streams closes each WebSocket and fires an `Event=StopStream` callback per stream that had a `status_callback_url` - see [Stop all Audio Streams](/docs/audio-streams/stop-all-audio-streams).

## Choosing between them

* Dialing a handful of numbers with identical call flow logic: bulk dialing on [Make an Outbound Call](/docs/call/make-call).
* Dialing a list with retries, scheduling, and per-contact data: [batch campaigns](/docs/campaign-manager/contacts/upload-contacts).
* Pulling call data for reconciliation right now: [bulk CDR export](/docs/cdr/export-cdrs).
* Pulling large volumes of recorded audio: [bulk recording export](/docs/recording/export-historical-recordings), which arrives by email.
* Messaging a segment on WhatsApp: [batched campaigns](/docs/whatsapp/api/campaigns), after a [bulk contact import](/docs/whatsapp/api/contacts).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.