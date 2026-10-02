> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Templates API

> Submit, manage, and sync WhatsApp Message Templates via the Vobiz API - Meta-approved formats required for all proactive business-initiated outbound messaging.

<Warning>
  **Meta approval required** - Templates must be approved by Meta before they can be sent. Newly created templates start with status `PENDING_REVIEW`; approval typically takes a few minutes to 24 hours.
</Warning>

**Base URL:** `https://api.vobiz.ai/api/v1/messaging`

**Authentication:** Every request requires `X-Auth-ID: MA_XXXXXXXX` and `X-Auth-Token: <token>` headers (a `Bearer` JWT is also accepted). Set `Content-Type: application/json` on requests with a body. Get your credentials from [console.vobiz.ai](https://console.vobiz.ai).

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

<ParamField path="channelId" type="string" required>
  UUID of the channel the templates belong to.
</ParamField>

<Note>
  Template create and list are always scoped to a channel under `/channels/{channelId}/templates`. There is no top-level `/messaging/templates` route.
</Note>

## Template categories

| Category | Use case |
| - | - |
| `UTILITY` | Transactional - orders, receipts, alerts |
| `MARKETING` | Promotional - offers, announcements |
| `AUTHENTICATION` | OTP and security codes only |

## List templates

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/channels/{channelId}/templates
```

Returns the templates for a specific channel. Filter by approval status using the `status` query parameter (e.g. `APPROVED`, `PENDING_REVIEW`, `REJECTED`, `DISABLED`, `PAUSED`). This request takes no request body.

<ParamField query="status" type="string">
  Filter by approval status: `APPROVED`, `PENDING_REVIEW`, `REJECTED`, `DISABLED`, or `PAUSED`.
</ParamField>

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/channels/{channelId}/templates?status=APPROVED" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "9d8f1e2a-4c3b-4a1d-8e7f-1a2b3c4d5e6f",
      "account_id": "MA_XXXXXXXX",
      "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
      "waba_id": "104958372615483",
      "meta_template_id": "1234567890123456",
      "name": "order_confirmation",
      "language": "en_US",
      "category": "UTILITY",
      "status": "APPROVED",
      "components": {
        "components": [
          { "type": "BODY", "text": "Your order {{1}} has been confirmed." }
        ]
      },
      "quality_score": "GREEN",
      "created_at": "2026-03-01T10:00:00Z",
      "updated_at": "2026-03-01T10:05:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20,
  "has_more": false
}
```

## Create template

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/channels/{channelId}/templates
```

Submit a new template to Meta for approval. The request body uses Meta's component format. Use double-brace numbered placeholders like `{{1}}`, `{{2}}` for dynamic content in the `BODY`.

### Request body

| Field | Required | Description |
| - | - | - |
| `name` | Yes | Template name, `lowercase_snake_case` |
| `language` | Yes | Language code (e.g. `en_US`) |
| `category` | Yes | `MARKETING`, `UTILITY`, or `AUTHENTICATION` |
| `components` | Yes | Array of component objects (Meta format) |

Each component object:

| Field | Description |
| - | - |
| `type` | `HEADER`, `BODY`, `FOOTER`, or `BUTTONS` |
| `format` | Optional. `TEXT`, `IMAGE`, `VIDEO`, or `DOCUMENT` (for `HEADER`) |
| `text` | Component text. `BODY` text may use `{{1}}`, `{{2}}` placeholders |
| `buttons` | Array of `{ type, text, url?, phone_number? }`. `type` is `QUICK_REPLY`, `URL`, or `PHONE_NUMBER` |
| `example` | Sample values: `{ "header_handle": [], "body_text": [[]] }` |

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/channels/{channelId}/templates" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "order_confirmation",
    "language": "en_US",
    "category": "UTILITY",
    "components": [
      {
        "type": "BODY",
        "text": "Your order {{1}} has been confirmed. Delivery: {{2}}",
        "example": { "body_text": [["ORD-12345", "March 15"]] }
      },
      {
        "type": "BUTTONS",
        "buttons": [
          { "type": "URL", "text": "Track order", "url": "https://example.com/track" }
        ]
      }
    ]
  }'
```

```json 201 Created theme={null}
{
  "id": "9d8f1e2a-4c3b-4a1d-8e7f-1a2b3c4d5e6f",
  "account_id": "MA_XXXXXXXX",
  "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
  "waba_id": "104958372615483",
  "meta_template_id": "1234567890123456",
  "name": "order_confirmation",
  "language": "en_US",
  "category": "UTILITY",
  "status": "PENDING_REVIEW",
  "components": {
    "components": [
      { "type": "BODY", "text": "Your order {{1}} has been confirmed. Delivery: {{2}}" }
    ]
  },
  "quality_score": "UNKNOWN",
  "created_at": "2026-03-25T14:00:00Z",
  "updated_at": "2026-03-25T14:00:00Z"
}
```

## Sync templates from Meta

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/channels/{channelId}/templates/sync
```

Pulls the latest template list and statuses from Meta and updates your Vobiz account. Call this after creating templates in Meta Business Manager directly, or after status changes (for example, when a template moves from `PENDING_REVIEW` to `APPROVED`). Returns the number of templates synced.

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/channels/{channelId}/templates/sync" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{ "synced": 7 }
```

## Template object

| Field | Type | Description |
| - | - | - |
| `id` | UUID | Vobiz template ID |
| `account_id` | string | Owning account (`MA_XXXXXXXX`) |
| `channel_id` | UUID | Channel the template belongs to |
| `waba_id` | string | Meta WhatsApp Business Account ID |
| `meta_template_id` | string | Meta's template ID |
| `name` | string | Template name (`lowercase_snake_case`) |
| `language` | string | Language code (e.g. `en_US`) |
| `category` | string | `MARKETING`, `UTILITY`, or `AUTHENTICATION` |
| `status` | string | `APPROVED`, `PENDING_REVIEW`, `REJECTED`, `DISABLED`, or `PAUSED` |
| `components` | object | Meta component structure |
| `quality_score` | string | Meta quality rating |
| `created_at` | RFC3339 | Creation timestamp (UTC) |
| `updated_at` | RFC3339 | Last update timestamp (UTC) |

## Sending a template message

Creating a template does not send anything. To send an approved template, use the [Messages API](/docs/whatsapp/api/send-message) with `type: "template"`.

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/messages" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "{channelId}",
    "to": "+919876543210",
    "type": "template",
    "template": {
      "name": "order_confirmation",
      "language": { "code": "en_US" },
      "components": [
        {
          "type": "body",
          "parameters": [
            { "type": "text", "text": "ORD-12345" },
            { "type": "text", "text": "March 15" }
          ]
        }
      ]
    }
  }'
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.