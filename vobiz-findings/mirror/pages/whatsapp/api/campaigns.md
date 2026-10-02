> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Campaigns API

> Create and manage WhatsApp broadcast campaigns on Vobiz - send bulk outbound messages via Meta-approved templates to segmented contact audiences at scale.

<Info>
  **Prerequisites:** Campaigns require an approved template (you pass its `template_id`) and either contact tags or explicit contact IDs as the audience. See [Templates API](/docs/whatsapp/api/templates) and [Contacts API](/docs/whatsapp/api/contacts).
</Info>

**Base URL:** `https://api.vobiz.ai/api/v1/messaging`

**Authentication:** Every request requires `X-Auth-ID: MA_XXXXXXXX` and `X-Auth-Token: <token>` headers (a `Bearer` JWT is also accepted). Set `Content-Type: application/json` on requests with a body. Get your credentials from [console.vobiz.ai](https://console.vobiz.ai).

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

## Campaign lifecycle

`draft` → `scheduled` → `sending` → `paused` → `completed` / `cancelled` / `failed`

## List campaigns

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/campaigns
```

Returns a paginated list of campaigns with status, delivery counts, and scheduling details. Filter with the `status` query parameter.

| Query param | Default | Description |
| - | - | - |
| `status` | - | Filter by campaign status |
| `page` | `1` | Page number |
| `limit` | `20` | Page size (max `100`) |

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/campaigns?status=completed&page=1&limit=20" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "7c2e9a4d-1b3f-4e6a-8c9d-0f1a2b3c4d5e",
      "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
      "name": "Welcome Campaign",
      "template_id": "9d8f1e2a-4c3b-4a1d-8e7f-1a2b3c4d5e6f",
      "template_name": "welcome_message",
      "template_lang": "en_US",
      "status": "completed",
      "total_recipients": 142,
      "sent_count": 142,
      "delivered_count": 138,
      "read_count": 95,
      "failed_count": 4,
      "skipped_count": 0,
      "created_at": "2026-03-25T09:55:00Z",
      "updated_at": "2026-03-25T10:30:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20,
  "has_more": false
}
```

## Create campaign

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/campaigns
```

Create a new campaign. Reference an approved template by its `template_id` (a UUID, not a template name). Choose the audience with `audience_type`: use `tags` plus `audience_tags`, or `contact_ids` plus `audience_contact_ids`. Set `scheduled_at` for a future send, or omit it to send immediately.

### Request body

| Field | Required | Description |
| - | - | - |
| `channel_id` | Yes | Channel (UUID) to send from |
| `name` | Yes | Campaign display name |
| `template_id` | Yes | UUID of an approved template |
| `template_components` | Yes | Meta component structure for the template |
| `audience_type` | Yes | `tags` or `contact_ids` |
| `audience_tags` | Conditional | Array of contact tags. Required when `audience_type` is `tags` |
| `audience_contact_ids` | Conditional | Array of contact IDs. Required when `audience_type` is `contact_ids` |
| `variable_mappings` | No | Object mapping template variables to contact fields |
| `recipient_variables` | No | Object: `{ "<contact_id>": { "<key>": "<value>" } }` per-recipient values |
| `scheduled_at` | No | RFC3339 datetime (UTC) for a scheduled send |

<ParamField body="channel_id" type="string" required>
  Channel (UUID) to send from.
</ParamField>

<ParamField body="name" type="string" required>
  Campaign display name.
</ParamField>

<ParamField body="template_id" type="string" required>
  UUID of an approved template.
</ParamField>

<ParamField body="template_components" type="object[]" required>
  Meta component structure for the template.
</ParamField>

<ParamField body="audience_type" type="string" required>
  Either `tags` or `contact_ids`.
</ParamField>

<ParamField body="audience_tags" type="string[]">
  Array of contact tags. Required when `audience_type` is `tags`.
</ParamField>

<ParamField body="audience_contact_ids" type="string[]">
  Array of contact IDs. Required when `audience_type` is `contact_ids`.
</ParamField>

<ParamField body="variable_mappings" type="object">
  Object mapping template variables to contact fields.
</ParamField>

<ParamField body="recipient_variables" type="object">
  Per-recipient values, shaped as `{ "<contact_id>": { "<key>": "<value>" } }`.
</ParamField>

<ParamField body="scheduled_at" type="string">
  RFC3339 datetime (UTC) for a scheduled send.
</ParamField>

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
    "audience_tags": ["vip"],
    "recipient_variables": {
      "1f2e3d4c-5b6a-7980-a1b2-c3d4e5f60718": { "1": "Asha" }
    },
    "scheduled_at": "2026-03-25T10:00:00Z"
  }'
```

```json 201 Created theme={null}
{
  "id": "7c2e9a4d-1b3f-4e6a-8c9d-0f1a2b3c4d5e",
  "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
  "name": "Welcome Campaign",
  "template_id": "9d8f1e2a-4c3b-4a1d-8e7f-1a2b3c4d5e6f",
  "template_name": "welcome_message",
  "template_lang": "en_US",
  "status": "scheduled",
  "total_recipients": 0,
  "sent_count": 0,
  "delivered_count": 0,
  "read_count": 0,
  "failed_count": 0,
  "skipped_count": 0,
  "scheduled_at": "2026-03-25T10:00:00Z",
  "created_at": "2026-03-25T09:55:00Z",
  "updated_at": "2026-03-25T09:55:00Z"
}
```

## Get campaign

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/campaigns/{id}
```

Returns full details and delivery statistics for a specific campaign.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/campaigns/{id}" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

## Campaign actions

Control campaign execution. All three use `POST` with no request body and return the updated `Campaign`.

| Endpoint | Description |
| - | - |
| `POST /campaigns/{id}/pause` | Pause a sending campaign. Sending stops immediately. |
| `POST /campaigns/{id}/resume` | Resume a paused campaign. |
| `POST /campaigns/{id}/cancel` | Permanently cancel. Cannot be undone. |

```bash cURL - pause theme={null}
curl -X POST "https://api.vobiz.ai/api/v1/messaging/campaigns/{id}/pause" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

## Delete campaign

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/messaging/campaigns/{id}
```

Permanently delete a campaign. Returns `204 No Content`.

```bash cURL theme={null}
curl -X DELETE "https://api.vobiz.ai/api/v1/messaging/campaigns/{id}" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```text 204 No Content theme={null}
// Empty body on success
```

## List campaign recipients

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/campaigns/{id}/recipients
```

Returns a paginated, per-contact delivery status. Use it to audit delivery rates or identify failed recipients. Filter with `status` and page with `page` / `limit`.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/campaigns/{id}/recipients?status=failed&page=1&limit=50" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "a1b2c3d4-e5f6-4071-8293-a4b5c6d7e8f9",
      "campaign_id": "7c2e9a4d-1b3f-4e6a-8c9d-0f1a2b3c4d5e",
      "contact_id": "1f2e3d4c-5b6a-7980-a1b2-c3d4e5f60718",
      "phone_number": "+919876543210",
      "status": "read",
      "meta_message_id": "wamid.HBgM...",
      "sent_at": "2026-03-25T10:00:05Z",
      "delivered_at": "2026-03-25T10:00:07Z",
      "read_at": "2026-03-25T10:15:00Z",
      "created_at": "2026-03-25T09:55:00Z",
      "updated_at": "2026-03-25T10:15:00Z"
    }
  ],
  "total": 142,
  "page": 1,
  "limit": 50,
  "has_more": true
}
```

## Campaign object

| Field | Type | Description |
| - | - | - |
| `id` | UUID | Campaign ID |
| `channel_id` | UUID | Channel the campaign sends from |
| `name` | string | Campaign display name |
| `template_id` | UUID | Approved template used |
| `template_name` | string | Resolved template name |
| `template_lang` | string | Template language code |
| `status` | string | `draft`, `scheduled`, `sending`, `paused`, `completed`, `cancelled`, or `failed` |
| `total_recipients` | int | Total recipients resolved for the audience |
| `sent_count` | int | Messages sent |
| `delivered_count` | int | Messages delivered |
| `read_count` | int | Messages read |
| `failed_count` | int | Messages failed |
| `skipped_count` | int | Recipients skipped |
| `batch_size` | int | Recipients per batch |
| `batch_delay_ms` | int | Delay between batches (ms) |
| `pause_reason` | string | Reason if paused |
| `scheduled_at` | RFC3339 | Scheduled send time (UTC) |
| `started_at` | RFC3339 | When sending started (UTC) |
| `completed_at` | RFC3339 | When sending completed (UTC) |
| `created_at` | RFC3339 | Creation timestamp (UTC) |
| `updated_at` | RFC3339 | Last update timestamp (UTC) |

## Campaign recipient object

| Field | Type | Description |
| - | - | - |
| `id` | UUID | Recipient row ID |
| `campaign_id` | UUID | Parent campaign |
| `contact_id` | UUID | Contact targeted |
| `phone_number` | string | Recipient phone (E.164) |
| `variables` | object | Per-recipient template variables |
| `status` | string | `queued`, `sent`, `delivered`, `read`, `failed`, or `skipped` |
| `meta_message_id` | string | Meta message ID (when sent) |
| `error_code` | string | Meta error code (on failure) |
| `error_desc` | string | Meta error description (on failure) |
| `sent_at` | RFC3339 | Sent timestamp (UTC) |
| `delivered_at` | RFC3339 | Delivered timestamp (UTC) |
| `read_at` | RFC3339 | Read timestamp (UTC) |
| `created_at` | RFC3339 | Creation timestamp (UTC) |
| `updated_at` | RFC3339 | Last update timestamp (UTC) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.