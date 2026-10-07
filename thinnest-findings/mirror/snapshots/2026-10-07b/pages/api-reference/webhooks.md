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
  body under this secret, and `x-thinnest-signature-v2`, which also signs the
  delivery time — see [Delivery](#delivery).
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
| `GET` | `/webhooks/{id}/deliveries` | Recent deliveries, newest first, with attempts and the next retry |
| `POST` | `/webhooks/{id}/redeliver` | Send one delivery again, or everything that failed since a time |

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
  | `call.analysed` | A call's [results are ready](/api-reference/calls/get-call) — summary, fields, transcript, recording link, and what the call cost (`costMicro` in millionths of `currency`; your reseller's price if you are a white-label client; `costMicro` is `null` if the call has not settled yet — read [Get Call](/api-reference/calls/get-call) later) |
  | `campaign.finished` | A broadcast or calling campaign finished |
  | `contact.opted_out` | During a call, somebody asked not to be called again and the agent put their number on your [do-not-call list](/channels/voice#dont-call-me-again) — `data.phone`, `data.callId`, `data.source` (always `"call"`), `data.optedOutAt` |
</ParamField>

<ParamField body="enabled" type="boolean">
  Switching an endpoint back on forgives its past failures.
</ParamField>

## Delivery

Each event is a `POST` of JSON:

```json theme={null}
{ "id": "evt_9d1c…", "event": "lead.captured", "sentAt": "2026-10-07T09:12:03.551Z", "data": { … } }
```

with these headers on every attempt (an email destination gets the ticket email only, without them):

| Header | What it is |
| - | - |
| `x-thinnest-signature` | `sha256=` + hex HMAC-SHA256 of the raw body under your signing secret |
| `x-thinnest-signature-v2` | `sha256=` + hex HMAC-SHA256 of `<x-thinnest-delivered-at>.<raw body>` — the delivery time, signed |
| `x-thinnest-delivered-at` | When this attempt left (ISO 8601) |
| `x-thinnest-event-id` | `evt_…`, the same as the body's `id` — the same on every retry and re-send |
| `x-thinnest-attempt` | `1`, then `2`, `3`, … |

### Retries

Anything other than a 2xx answer — an error, a timeout after 10 seconds, an
address we cannot reach — is tried again after **1 minute, 5 minutes, 30
minutes, 2 hours and 6 hours**: six attempts over about 8½ hours. Every attempt
sends the **same bytes**, so `sentAt` is when the event happened, not when the
attempt left. Payloads are kept for **7 days**, so anything that still did not
arrive can be [sent again](#re-send-what-failed) within that week.

Re-sending a delivery starts its retry schedule afresh. Retries and re-sends
go to the endpoint's **current** address — change the URL and pending retries
follow it. A Slack or helpdesk destination that accepted a post but answered
after the 10-second timeout can receive it twice, since neither can dedupe on
the event id.

### What your receiver should do

1. **Verify** `x-thinnest-signature-v2` (or `x-thinnest-signature`) with a
   constant-time compare.
2. **Check freshness on `x-thinnest-delivered-at`** — reject one more than five
   minutes from your clock. Not on `sentAt`: a retry's `sentAt` is hours old by
   design. The delivery time is covered by the v2 signature, so it cannot be
   moved without breaking it.
3. **Dedupe on `x-thinnest-event-id`.** A retry after a timeout can reach you
   after you already handled the first attempt.
4. **Answer 2xx quickly**, then do the work.

```js theme={null}
import { createHmac, timingSafeEqual } from "node:crypto";

function verify(secret, rawBody, headers) {
  const at = headers["x-thinnest-delivered-at"];
  const expected = "sha256=" + createHmac("sha256", secret).update(`${at}.${rawBody}`).digest("hex");
  const given = headers["x-thinnest-signature-v2"] ?? "";
  const fresh = Math.abs(Date.now() - Date.parse(at)) < 5 * 60_000;
  return fresh && given.length === expected.length && timingSafeEqual(Buffer.from(given), Buffer.from(expected));
}
```

### Switched off

An endpoint is switched off — `enabled: false`, `delivery.lastError` says why —
after **five events in a row that each failed every attempt**. A failed attempt
that a retry then delivers does not count. Events that happen while it is off
are recorded as not sent; fix the endpoint, `PATCH { "enabled": true }`, and
re-send them — nothing within the last 7 days is lost.

## Re-send what failed

```http theme={null}
POST /api/v1/webhooks/{id}/redeliver
```

One delivery, now — the answer says whether it arrived:

```json theme={null}
{ "deliveryId": "whd_2b6f…" }
```

```json theme={null}
{ "delivered": true, "status": 200, "error": null, "attempts": 4 }
```

Or everything that has not succeeded since a time, at most 7 days back — queued
and sent within a minute:

```json theme={null}
{ "since": "2026-10-06T00:00:00Z" }
```

```json theme={null}
{ "queued": 12 }
```

The same body, event id and `sentAt` as the first attempt, with
`x-thinnest-attempt` one higher. The endpoint must be switched on. The console's
**Re-send failed** button on the endpoint does the same for the last 7 days. A
build key may do this.

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
    {
      "id": "whd_2b6f…", "eventId": "evt_9d1c…", "event": "call.analysed",
      "status": 500, "delivered": false, "error": "Internal Server Error",
      "attempts": 2, "nextRetryAt": "2026-10-05T09:18:04Z",
      "at": "2026-10-05T09:12:03Z", "lastAttemptAt": "2026-10-05T09:13:04Z"
    },
    {
      "id": "whd_7c3e…", "eventId": null, "event": "test",
      "status": 200, "delivered": true, "error": null,
      "attempts": 1, "nextRetryAt": null,
      "at": "2026-10-05T08:58:41Z", "lastAttemptAt": "2026-10-05T08:58:41Z"
    }
  ]
}
```

One row per event, however many attempts it took, newest first — the last 7
days (or the last 50, whichever is more). The answer to "why did leads stop
reaching our CRM on Tuesday?". `status` and `error` are from the latest
attempt; `0` means we could not reach it. `nextRetryAt` is when the next
automatic attempt is due — null once it arrived or ran out of retries. The
payloads themselves are not returned: they carry your customers' details.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.