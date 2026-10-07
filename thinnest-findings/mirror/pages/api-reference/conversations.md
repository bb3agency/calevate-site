> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Conversations

> GET /api/v1/conversations and /conversations/{id}/messages — read threads and catch up on anything your webhook missed.

```http theme={null}
GET /api/v1/conversations?channel=whatsapp&since=2026-09-21T10:00:00Z
Authorization: Bearer ta_live_…
```

```json theme={null}
{
  "items": [
    {
      "id": "conv_e0829641-…",
      "channel": "whatsapp",
      "customer": { "id": "cust_6f4a9fb9-…", "phone": "919876543210" },
      "status": "active",
      "lastInboundAt": "2026-09-21T10:15:01Z",
      "createdAt": "2026-09-18T08:02:44Z"
    }
  ],
  "nextCursor": null
}
```

```http theme={null}
GET /api/v1/conversations/conv_e0829641-…/messages?since=2026-09-21T10:00:00Z
Authorization: Bearer ta_live_…
```

```json theme={null}
{
  "items": [
    {
      "id": "msg_91c2…",
      "author": "customer",
      "parts": [
        { "type": "text", "text": "Here is the damaged box" },
        { "type": "image", "url": "https://…signed…", "alt": "" }
      ],
      "createdAt": "2026-09-21T10:15:01Z"
    }
  ],
  "nextCursor": null
}
```

## Catching up after a missed webhook

A [webhook](/api-reference/webhooks) delivery is attempted once. If your
endpoint was down, read back what you missed:

1. Take the `receivedAt` of the last event you handled and go back **five
   minutes** — messages that arrive together can be delivered out of order.
2. `GET /api/v1/conversations?since=<that time>` — every conversation a
   customer has written in since then, including brand-new ones.
3. For each, `GET /api/v1/conversations/{id}/messages?since=<same time>`.
4. Skip any message whose `id` matches a `messageId` you already handled.

Poll this every few minutes as a safety net and a missed message never goes
unanswered for long.

## `GET /conversations`

Newest first.

<ParamField query="channel" type="string">
  `whatsapp`, `web`, `telegram`, `voice` or `email`.
</ParamField>

<ParamField query="since" type="string">
  ISO 8601. Keeps conversations where the customer last wrote at or after this.
</ParamField>

<ParamField query="status" type="string">
  `active`, `escalated`, `human_handling` or `resolved`. `escalated` and
  `human_handling` are the conversations waiting on your team.
</ParamField>

<ParamField query="limit" type="number">
  Up to 100. Default 25. Follow `nextCursor` with `?cursor=` for the next page.
</ParamField>

## `GET /conversations/{id}/messages`

Newest first. The customer's messages, your agent's replies, and replies a
teammate sent from the inbox (`author: "teammate"`). Your team's internal notes
are not included.

<ParamField query="since" type="string">
  ISO 8601. Keeps messages written after this.
</ParamField>

<ParamField query="limit" type="number">
  Up to 100. Default 25. Follow `nextCursor` with `?cursor=`.
</ParamField>

**Photos, voice notes, videos and documents** a customer sent come back as
links that stay valid for **eight hours**. Download what you need to keep.

## Resolve, hand back or take over

```http theme={null}
POST /api/v1/conversations/{id}/status
```

```json theme={null}
{ "status": "resolved" }
```

```json theme={null}
{ "status": "resolved", "changed": true }
```

| `status` | What it does |
| - | - |
| `resolved` | Marks it done. The `conversation.resolved` webhook fires |
| `active` | Hands it back to the agent |
| `human_handling` | Takes it over — the agent stays quiet until it is handed back |

The same moves as the inbox. An internal note records which API key made the
change; the customer never sees it. `changed: false` means it was already in
that state, and nothing was written or announced. The shared inbox is a
paid-plan feature, so on the Free plan this answers `403`.

## Assign

```http theme={null}
POST /api/v1/conversations/{id}/assign
```

```json theme={null}
{ "assignee": "priya@yourcompany.com" }
```

Make a conversation a teammate's job, by their email — or `null` to put it
back in the pool. They are notified. Assigning does **not** silence the agent;
taking over does. `GET /api/v1/members` lists your teammates:

```json theme={null}
{ "items": [{ "id": "6f2…", "name": "Priya", "email": "priya@yourcompany.com" }] }
```

## Errors

| Status | Why |
| - | - |
| `400` | `since`, `channel`, `limit` or `cursor` is not valid |
| `404` | The conversation is not in your workspace |
| `429` | Too many requests. Wait and retry |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.