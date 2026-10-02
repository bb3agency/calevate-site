> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Send Message API

> Send WhatsApp messages via the Vobiz REST API - text, images, video, audio, documents, stickers, and Meta-approved templates over a single endpoint.

**Authentication:** `X-Auth-ID: MA_…`, `X-Auth-Token`, `Content-Type: application/json`

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

<Note>
  This endpoint sends these WhatsApp message types: `text`, `image`, `audio`, `video`, `document`, `sticker`, and `template`. Set the `type` field to one of these and include the matching object (`text`, `media`, or `template`).
</Note>

<Note>
  **Inbound-only types.** WhatsApp also defines `interactive` (buttons, list pickers), `location`, and `contacts` message types. You **receive** these on inbound messages (see the [Webhook Events Reference](/docs/whatsapp/webhooks/events)), and you can offer buttons/URLs/quick replies on **outbound template** messages (see [Templates](/docs/whatsapp/messaging/templates)). To send a structured prompt outside the 24-hour window, use an approved template with buttons rather than a free-form interactive message.
</Note>

## Endpoint

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/messages
```

## Request Body

| Property | Type | Required | Description |
| - | - | - | - |
| `channel_id` | string (UUID) | Required | The WhatsApp channel to send from |
| `waba_id` | string | Required | The WhatsApp Business Account ID for the channel |
| `to` | string | Required | Recipient phone number in E.164 format (e.g. `+919876543210`) |
| `type` | string | Required | One of `text`, `template`, `image`, `audio`, `video`, `document`, `sticker` |
| `text` | object | When `type=text` | Text message body |
| `media` | object | For media types | Shared media object for `image`, `audio`, `video`, `document`, `sticker` |
| `template` | object | When `type=template` | Template message payload |

<ParamField body="channel_id" type="string" required>
  The WhatsApp channel (UUID) to send from.
</ParamField>

<ParamField body="waba_id" type="string" required>
  The WhatsApp Business Account ID for the channel.
</ParamField>

<ParamField body="to" type="string" required>
  Recipient phone number in E.164 format, for example `+919876543210`.
</ParamField>

<ParamField body="type" type="string" required>
  One of `text`, `template`, `image`, `audio`, `video`, `document`, or `sticker`.
</ParamField>

<ParamField body="text" type="object">
  Text message body. Required when `type` is `text`. Contains a `body` string.
</ParamField>

<ParamField body="media" type="object">
  Shared media object for `image`, `audio`, `video`, `document`, and `sticker`. Contains `link` or `id`, plus optional `caption` and `filename`.
</ParamField>

<ParamField body="template" type="object">
  Template message payload. Required when `type` is `template`. Contains `name`, `language`, and optional `category` and `components`.
</ParamField>

## Sending Text Messages

Send plain text messages to your customers. Provide the `text` object with a `body` field.

| Property | Type | Description |
| - | - | - |
| `text.body` | string | Message content |

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/messages" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <your-auth-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "0a8f3feb-9598-47f2-8a6c-df1aeb306ae1",
    "waba_id": "123456789012345",
    "to": "+919876543210",
    "type": "text",
    "text": { "body": "Hello from Vobiz!" }
  }'
```

## Sending Media Messages

Send images, audio, video, documents, or stickers. All media types share a single `media` object. Supply either a public `link` (HTTPS URL) or a Meta media `id`.

### Media Object Properties

| Property | Type | Description |
| - | - | - |
| `link` | string | Public HTTPS URL of the media file |
| `id` | string | A previously uploaded Meta media ID (alternative to `link`) |
| `caption` | string | Optional caption (for `image`, `video`, `document`) |
| `filename` | string | Optional filename (for `document`) |

```bash cURL - image example theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/messages" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <your-auth-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "0a8f3feb-9598-47f2-8a6c-df1aeb306ae1",
    "waba_id": "123456789012345",
    "to": "+919876543210",
    "type": "image",
    "media": {
      "link": "https://example.com/photo.jpg",
      "caption": "Check this out!"
    }
  }'
```

```bash cURL - document example theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/messages" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <your-auth-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "0a8f3feb-9598-47f2-8a6c-df1aeb306ae1",
    "waba_id": "123456789012345",
    "to": "+919876543210",
    "type": "document",
    "media": {
      "link": "https://example.com/invoice.pdf",
      "filename": "invoice.pdf",
      "caption": "Your invoice"
    }
  }'
```

## Sending Template Messages

Send pre-approved template messages for marketing, authentication, or utility purposes.

### Template Object Properties

| Property | Type | Description |
| - | - | - |
| `name` | string | Template name from Meta Business Manager |
| `language` | object | Language object with a `code` field (e.g. `{ "code": "en_US" }`) |
| `category` | string | Optional template category |
| `components` | array | Optional array of component objects for template variables |

<Note>
  Templates must be created and approved in Meta Business Manager before you can use them. See our [Templates Guide](/docs/whatsapp/messaging/templates) for details.
</Note>

```bash cURL - template example theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/messages" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <your-auth-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "0a8f3feb-9598-47f2-8a6c-df1aeb306ae1",
    "waba_id": "123456789012345",
    "to": "+919876543210",
    "type": "template",
    "template": {
      "name": "order_confirmation",
      "language": { "code": "en_US" },
      "components": [{
        "type": "body",
        "parameters": [
          { "type": "text", "text": "ORD-12345" },
          { "type": "text", "text": "March 15" }
        ]
      }]
    }
  }'
```

## Response

### Success Response (201 Created)

Returns the created `Message` object.

```json theme={null}
{
  "id": "9b2e1c40-8a3d-4f5e-9c1a-7d6b2e8f4a01",
  "account_id": "MA_XXXXXXXX",
  "channel_id": "0a8f3feb-9598-47f2-8a6c-df1aeb306ae1",
  "contact_id": "4f9c2a18-3e6b-4d2f-8b1a-9e7c5d3f1a02",
  "conversation_id": "c7d1e9a3-2b4f-4a6c-8d5e-1f3a9b7c2e04",
  "direction": "outbound",
  "type": "text",
  "status": "pending",
  "content": "{\"body\":\"Hello from Vobiz!\"}",
  "meta_message_id": null,
  "created_at": "2026-06-15T10:30:00Z"
}
```

### Message Object Fields

| Field | Type | Description |
| - | - | - |
| `id` | string (UUID) | Unique message ID |
| `account_id` | string | Your account ID (`MA_…`) |
| `channel_id` | string (UUID) | Channel the message was sent from |
| `contact_id` | string (UUID) | Contact the message was sent to |
| `conversation_id` | string (UUID) or `null` | Conversation the message belongs to |
| `direction` | string | `outbound` for sent messages |
| `type` | string | The message type (`text`, `image`, etc.) |
| `status` | string | One of `pending`, `sent`, `delivered`, `read`, `failed` |
| `content` | string | JSON-encoded string of the message content |
| `meta_message_id` | string or `null` | The Meta WhatsApp message ID (`wamid`) once accepted by Meta |
| `created_at` | string (RFC3339 UTC) | When the message was created |

### Common Errors

* **`400 Bad Request`** - Missing or invalid fields (e.g. missing `channel_id`, `waba_id`, `to`, or `type`), or a malformed `type`-specific object.
* **`401 Unauthorized`** - Missing or invalid authentication credentials.
* **`403 Forbidden`** - Valid credentials but insufficient permissions for the channel.

A `2xx` from Vobiz means the message was **accepted**, not delivered. A message can still end as `failed` later - watch the [`message.status`](/docs/whatsapp/webhooks/events#message-status) webhook for the final state and any error reason from Meta.

## The 24-hour window (most common real-world failure)

WhatsApp only lets you send **free-form** messages (`text` and media) within **24 hours of the customer's last inbound message**. Outside that window - including the **first** message to a contact who has never replied - you can send **only an approved template**.

* **Inside the window**: any `type` works. Each new inbound message from the customer resets the 24h timer.
* **Outside the window**: send `type: "template"`. A free-form send is rejected by WhatsApp; the rejection surfaces as a `failed` status on the `message.status` webhook.
* **Open a new window**: sending a template (re)opens a fresh 24-hour service window once the customer replies.

<Warning>
  If you are unsure whether the window is open, send an approved **template**. Templates are always allowed; free-form messages are not.
</Warning>

## Idempotency and correlation

* The response `id` is the **Vobiz** message UUID. The **Meta** id (`wamid`) arrives as `meta_message_id` once Meta accepts the message - it is `null` in the initial `201` response.
* Correlate later [`message.status`](/docs/whatsapp/webhooks/events#message-status) webhooks back to the send using the `wamid` (the `statuses[].id` in the webhook equals `meta_message_id`).

## Related Topics

* [API Authentication →](/docs/whatsapp/api/authentication)
* [Message Templates →](/docs/whatsapp/messaging/templates)
* [Webhook Events →](/docs/whatsapp/webhooks/events)
* [Channels API →](/docs/whatsapp/api/channels)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.