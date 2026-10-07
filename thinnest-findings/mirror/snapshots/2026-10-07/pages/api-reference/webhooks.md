> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Webhooks

> Add, list, change and remove the endpoints an agent's events are sent to.

```http theme={null}
POST /api/v1/webhooks
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{
  "agent": "ag_5c4a5f93-…",
  "url": "https://crm.example.com/hooks/thinnest",
  "events": ["call.analysed", "call.completed"]
}
```

```json theme={null}
{
  "id": "wh_e1c5…",
  "agent": "ag_5c4a5f93-…",
  "url": "https://crm.example.com/hooks/thinnest",
  "events": ["call.analysed", "call.completed"],
  "enabled": true,
  "delivery": { "failuresInARow": 0, "lastStatus": null, "lastError": null, "lastSentAt": null },
  "createdAt": "2026-09-17T09:41:00Z",
  "signingSecret": "s3cr3t…"
}
```

<Warning>
  **`signingSecret` is in the create response and nowhere else.** Store it.
  Every delivery carries `x-thinnest-signature: sha256=…`, an HMAC of the raw
  body under this secret.
</Warning>

## Endpoints

| Method | Path | What |
| - | - | - |
| `GET` | `/webhooks` | List, newest first. `agent` filters |
| `POST` | `/webhooks` | Add one. `url`, and `agent` — or `includeCustomers: true` |
| `GET` | `/webhooks/{id}` | One endpoint, with its delivery state |
| `PATCH` | `/webhooks/{id}` | `url`, `events`, `enabled` |
| `DELETE` | `/webhooks/{id}` | Remove it |
| `POST` | `/webhooks/{id}/test` | Send a sample event and say whether it arrived |
| `GET` | `/webhooks/{id}/deliveries` | The last 50 deliveries, newest first |

## Fields

<ParamField body="agent" type="string" required>
  Whose events. Required on create — unless `includeCustomers` is `true`.
</ParamField>

<ParamField body="includeCustomers" type="boolean">
  For a workspace with [customers](/api-reference/customers): one endpoint for the events of every
  agent in every one of your customers. It has no `agent` (send one or the other, not both). Each
  delivery's `data` carries `workspaceId` — the customer it is about — inside the signed body.
</ParamField>

<ParamField body="url" type="string" required>
  An `https://` address, or an email address — a helpdesk that opens tickets by
  mail gets one email per event. Addresses inside our own network are refused.
</ParamField>

<ParamField body="events" type="string[]">
  Which events to send. Leave it out for every event, now and as new ones are
  added; the response then reads `["*"]`.

  | Event | When |
  | - | - |
  | `lead.captured` | The agent collected a name, email or phone from somebody interested |
  | `conversation.escalated` | It handed a conversation to a person |
  | `conversation.resolved` | A teammate marked one done |
  | `call.completed` | A call ended — outcome and duration, the moment it ends |
  | `call.analysed` | A call's [results are ready](/api-reference/calls/get-call) — summary, fields, transcript, recording link |
  | `campaign.finished` | A broadcast or calling campaign finished |
</ParamField>

<ParamField body="enabled" type="boolean">
  Switching an endpoint back on forgives its past failures.
</ParamField>

## Delivery

One attempt per event. An endpoint that fails five times in a row is switched
off — `enabled: false`, `delivery.lastError` says why — rather than retried
into a wall. Read [`GET /api/v1/calls/{id}`](/api-reference/calls/get-call) for
anything a dead endpoint missed, then `PATCH { "enabled": true }`.

## Test an endpoint

```http theme={null}
POST /api/v1/webhooks/{id}/test
```

```json theme={null}
{ "delivered": true, "status": 200, "error": null }
```

Sends one sample `lead.captured` — marked `"test": true`, with obviously fake
details — the same way a real event goes: signed JSON, Slack's own format for
a Slack URL, or a ticket email for an email address. A failed test counts
towards the five failures that switch an endpoint off.

## Delivery history

```http theme={null}
GET /api/v1/webhooks/{id}/deliveries
```

```json theme={null}
{
  "items": [
    { "event": "call.analysed", "status": 500, "delivered": false, "error": "Internal Server Error", "at": "2026-10-05T09:12:03Z" },
    { "event": "test", "status": 200, "delivered": true, "error": null, "at": "2026-10-05T08:58:41Z" }
  ]
}
```

The last 50 deliveries, newest first — the answer to "why did leads stop
reaching our CRM on Tuesday?". `status` is what your endpoint answered; `0`
means we could not reach it, and `error` says why. The event payloads are not
kept, because they carry your customers' details.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.