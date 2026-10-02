> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Conversations API

> Retrieve and paginate WhatsApp conversation threads on Vobiz - build inbox views, sync message history to your CRM, or audit logs with cursor-based pagination.

**Base URL:** `https://api.vobiz.ai/api/v1/messaging`

**Authentication:** every request requires `X-Auth-ID: MA_XXXXXXXX` and `X-Auth-Token: <token>` headers (a `Authorization: Bearer <JWT>` header is also accepted). Send `Content-Type: application/json` on requests with a body. Get your credentials from [console.vobiz.ai](https://console.vobiz.ai).

<Info>
  A **conversation** is a thread between one of your WhatsApp channels and one customer contact. Messages within a conversation are cursor-paginated - pass the `next_cursor` from the previous response to fetch the next page of older messages.
</Info>

## List conversations

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/conversations
```

Returns all WhatsApp conversations for your account across all channels.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/conversations" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "c7a1b2d3-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
      "account_id": "MA_XXXXXXXX",
      "channel_id": "2f8892e1-59b7-40a2-b518-e7a7c31a754d",
      "contact_id": "9b8a7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d",
      "category": "service",
      "is_billable": true,
      "started_at": "2026-03-17T14:00:00Z",
      "expires_at": "2026-03-18T14:00:00Z",
      "status": "open"
    }
  ]
}
```

### Conversation object

<ResponseField name="id" type="string">
  Unique conversation identifier (UUID).
</ResponseField>

<ResponseField name="account_id" type="string">
  Your Vobiz account ID (`MA_XXXXXXXX`).
</ResponseField>

<ResponseField name="channel_id" type="string">
  UUID of the channel the conversation belongs to.
</ResponseField>

<ResponseField name="contact_id" type="string">
  UUID of the contact on the other side of the conversation.
</ResponseField>

<ResponseField name="category" type="string">
  WhatsApp conversation category (e.g. `service`, `marketing`, `utility`, `authentication`).
</ResponseField>

<ResponseField name="is_billable" type="boolean">
  Whether the conversation is billable under WhatsApp pricing.
</ResponseField>

<ResponseField name="started_at" type="string">
  Conversation start timestamp (RFC3339 UTC).
</ResponseField>

<ResponseField name="expires_at" type="string">
  When the conversation window expires (RFC3339 UTC).
</ResponseField>

<ResponseField name="status" type="string">
  Conversation status: `open` or `closed`.
</ResponseField>

## List messages in a conversation

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/conversations/{id}/messages
```

Returns cursor-paginated messages for a specific conversation.

<ParamField query="limit" type="integer" default="50">
  Max messages per page. Default `50`, maximum `100`.
</ParamField>

<ParamField query="cursor" type="string">
  Cursor from the previous response (`next_cursor`) to fetch the next page.
</ParamField>

<CodeGroup>
  ```bash First page theme={null}
  curl -X GET \
    "https://api.vobiz.ai/api/v1/messaging/conversations/c7a1b2d3-4e5f-4a6b-8c9d-0e1f2a3b4c5d/messages?limit=50" \
    -H "X-Auth-ID: MA_XXXXXXXX" \
    -H "X-Auth-Token: {auth_token}"
  ```

  ```bash Next page theme={null}
  curl -X GET \
    "https://api.vobiz.ai/api/v1/messaging/conversations/c7a1b2d3-4e5f-4a6b-8c9d-0e1f2a3b4c5d/messages?limit=50&cursor=eyJpZCI6Im1zZzAwMSJ9" \
    -H "X-Auth-ID: MA_XXXXXXXX" \
    -H "X-Auth-Token: {auth_token}"
  ```
</CodeGroup>

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "e1d2c3b4-a5f6-4789-90ab-cdef01234567",
      "account_id": "MA_XXXXXXXX",
      "channel_id": "2f8892e1-59b7-40a2-b518-e7a7c31a754d",
      "contact_id": "9b8a7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d",
      "conversation_id": "c7a1b2d3-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
      "direction": "outbound",
      "type": "text",
      "status": "read",
      "content": "{\"body\":\"How can I help?\"}",
      "meta_message_id": "wamid.HBgL...",
      "created_at": "2026-03-17T14:20:00Z"
    },
    {
      "id": "f2e3d4c5-b6a7-4890-91bc-def012345678",
      "account_id": "MA_XXXXXXXX",
      "channel_id": "2f8892e1-59b7-40a2-b518-e7a7c31a754d",
      "contact_id": "9b8a7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d",
      "conversation_id": "c7a1b2d3-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
      "direction": "inbound",
      "type": "text",
      "status": "delivered",
      "content": "{\"body\":\"Yes, I'd like to proceed.\"}",
      "meta_message_id": "wamid.HBgM...",
      "created_at": "2026-03-17T14:22:00Z"
    }
  ],
  "has_more": true,
  "next_cursor": "eyJpZCI6Im1zZzAwMSJ9"
}
```

### Message object

<ResponseField name="id" type="string">
  Unique message identifier (UUID).
</ResponseField>

<ResponseField name="account_id" type="string">
  Your Vobiz account ID (`MA_XXXXXXXX`).
</ResponseField>

<ResponseField name="channel_id" type="string">
  UUID of the channel the message was sent or received on.
</ResponseField>

<ResponseField name="contact_id" type="string">
  UUID of the contact the message is with.
</ResponseField>

<ResponseField name="conversation_id" type="string">
  UUID of the parent conversation. May be omitted for messages not yet tied to a conversation.
</ResponseField>

<ResponseField name="direction" type="string">
  Message direction: `inbound` or `outbound`.
</ResponseField>

<ResponseField name="type" type="string">
  Message type, e.g. `text`, `image`, `document`, `template`.
</ResponseField>

<ResponseField name="status" type="string">
  Delivery status: `pending`, `sent`, `delivered`, `read`, or `failed`.
</ResponseField>

<ResponseField name="content" type="string">
  Message payload as a JSON-encoded string (parse it to read the body and media fields).
</ResponseField>

<ResponseField name="meta_message_id" type="string">
  Meta WhatsApp message ID (`wamid…`), when available.
</ResponseField>

<ResponseField name="created_at" type="string">
  Message timestamp (RFC3339 UTC).
</ResponseField>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.