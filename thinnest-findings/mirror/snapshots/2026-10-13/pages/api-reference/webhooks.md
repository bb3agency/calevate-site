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
  | `contact.opted_out` | During a call, somebody asked not to be called again and the agent put their number on your [do-not-call list](/channels/voice#dont-call-me-again) — `data.phone`, `data.callId`, `data.source` (always `"call"`), `data.optedOutAt`, `data.reason` (their words, or `null`) |
  | `call.problem` | During a call that is [still going on](#problems-on-a-live-call): the agent could not answer, your own model key failed, a reply was very slow, or the voice connection failed. At most once per kind per call |
</ParamField>

<ParamField body="enabled" type="boolean">
  Switching an endpoint back on forgives its past failures.
</ParamField>

<Note>
  `call.started` is not a webhook event you subscribe to. It is the request your own system receives
  from an agent's [Who-is-calling lookup](/channels/voice#who-is-calling-lookup), signed the same
  way, which you answer with values for the agent to use.
</Note>

## Problems on a live call

`call.problem` is sent **while the call is still going on**, so you can alert
somebody or flag the call before it ends. Each kind is sent at most once per
call, and a burst across many calls is held to about 20 events a minute per
agent. An event held back by that limit is not queued: it is sent if that kind
happens again on the same call once the agent is back under the limit, and
otherwise it is not sent at all. The same problems are also on the call itself,
under **Problems on this call** in [Usage](/workspace/usage#how-a-call-went).

```json theme={null}
{
  "id": "evt_4d8b2f6a-…",
  "event": "call.problem",
  "sentAt": "2026-10-06T04:31:02.715Z",
  "data": {
    "callId": "out_9f2c1a44-…",
    "agentId": "ag_5c4a5f93-…",
    "kind": "slow_reply",
    "detail": "A reply took 6.2 seconds to start.",
    "at": "2026-10-06T04:31:02.702Z"
  }
}
```

| `kind` | What happened |
| - | - |
| `no_answer_from_model` | The agent could not get an answer — even from its backup — and apologised to the caller |
| `byok_failed` | Your [own model key](/api-reference/bring-your-own-keys) failed, so the agent apologised instead of answering |
| `slow_reply` | A reply took more than 5 seconds to start |
| `voice_failed` | The call's voice connection failed — the caller may have heard silence or been cut off. It also rings the workspace's notification bell |

`callId` is the id [Get Call](/api-reference/calls/get-call) takes. `detail` is
a sentence you can show a person.

## Call quality

Every call the agent ran carries `quality`, written once when the call ends —
on [Get Call](/api-reference/calls/get-call) and in `data.quality` on
`call.completed` and `call.analysed`:

```json theme={null}
"quality": {
  "turns": 14,
  "responseMs": { "median": 1180, "p90": 1920, "max": 3410 },
  "firstTokenMs": { "median": 610, "p90": 940, "max": 1730 },
  "longSilences": 1,
  "longSilenceSeconds": 10,
  "longestSilenceSeconds": 12.4,
  "interruptions": 2,
  "modelErrors": 0,
  "rescues": 1
}
```

| Field | What it is |
| - | - |
| `turns` | Caller turns the agent answered — noises that got no reply, such as an echo of the agent's own voice, are not counted |
| `responseMs` | How long the caller waited: from when they stopped speaking to the agent's first audio — median, 90th percentile and slowest, in milliseconds |
| `firstTokenMs` | Our side of that wait: from the turn reaching the model to its first word |
| `longSilences` | Silences on either side at least `longSilenceSeconds` long — the agent's "are you still there?" time, or 10 seconds if it has none |
| `longestSilenceSeconds` | The longest stretch where nobody spoke |
| `interruptions` | Times the caller started speaking while the agent was talking |
| `modelErrors` | Turns the agent apologised for because it could not get an answer. `null` when the count was not available for the call |
| `rescues` | Turns where the agent's first choice failed and a backup answered, so the caller still got a reply. `null` when the count was not available for the call |

`quality` is `null` for a call that was not measured (a call from before these
figures were recorded, or one that never connected), and a figure inside it is
`null` when it could not be measured on that call. On `call.completed` it can
also be `null` when the call ended before its figures were ready;
`call.analysed` and Get Call have them by then. In the console the same
figures are under **How the call went** when you open the call in
[Usage](/workspace/usage#how-a-call-went).

## Calls handed to another agent

When an agent passes a live call to another of your agents
([how](/channels/voice)), `call.analysed` and Get Call list it in `handedTo`,
oldest first — empty when the call stayed with `agent`, which is always the
agent the call was placed or answered as:

```json theme={null}
"handedTo": [
  {
    "agent": { "id": "ag_7b1d4e90-2c3a-4f6e-8d15-9a0b3c2e4f71", "name": "Support" },
    "from": { "id": "ag_3f6a9c21-7d4e-4b58-9a1f-0c2e8b7d5a34", "name": "Sales" },
    "at": "2026-10-09T10:04:12Z"
  }
]
```

A hand-off to another agent is not a hand-over to a person, so it does not
send `conversation.escalated`.

**Which agent an event names.** The call-level events — `call.completed`,
`call.analysed` and `call.problem` — stay with the agent the call started
with, which is also the one the call is billed and summarised under. Events
the agents themselves raise mid-call — `lead.captured`,
`conversation.escalated` — name the agent that ran the tool in `data.agentId`
and carry `data.callId`, so on a handed call you can join them to the call
report and to `handedTo`.

**Webhooks belong to an agent.** An event raised by the agent a call was handed
to goes to *that* agent's webhooks, not to the agent that took the call first.
If you only subscribe the first agent, you will get `call.completed` and
`call.analysed` for the whole call but miss any `lead.captured` or
`conversation.escalated` the second agent raises. Add the same endpoint to every
agent a call can be handed to.

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

## Event payloads

Every delivery is the same envelope. What changes is `data`, shown here in full for each event.
Ids in `data` are the same prefixed ids the API returns and takes: `conv_…` for a conversation
(pass it to [List Conversation Messages](/api-reference/conversations/list-conversation-messages)), `cmp_…` for a
campaign, and `out_…`, `sch_…` or the call reference for a call (pass it to
[Get Call](/api-reference/calls/get-call)). `conversationId` and `campaignId`
always carry their `conv_` and `cmp_` prefix, so a value from a webhook can be
passed straight to the API. If your receiver stored these ids as bare
identifiers before, store the prefixed value from now on.

An endpoint created with `includeCustomers: true` also gets `data.workspaceId` (`org_…`), the
customer the event is about.

### `lead.captured`

The agent collected contact details. `name`, `email` and `phone` are each `null` when not given; `note` is what the customer wants, written for whoever follows up. `agentId` is the agent that captured it and `callId` the call it was on (the id [Get Call](/api-reference/calls/get-call) takes; `null` off a call).

```json theme={null}
{
  "id": "evt_9d1c4b2a-7e3f-4a6b-8c1d-2e5f7a9b0c13",
  "event": "lead.captured",
  "sentAt": "2026-10-06T04:31:55.204Z",
  "data": {
    "conversationId": "conv_3f6b2d1e-8a4c-4f7b-9e21-6c0d5a7b8e94",
    "agentId": "ag_3f6a9c21-7d4e-4b58-9a1f-0c2e8b7d5a34",
    "callId": "out_6d1c2e84-3b7a-4f95-8e10-5a9b7c3d2f41",
    "name": "Asha Rao",
    "email": "asha@example.com",
    "phone": "+919876543210",
    "note": "Wants a 2 BHK at Sky Towers, budget around 80 lakh, and a site visit on Saturday."
  }
}
```

### `conversation.escalated`

The agent handed the conversation to a person. `reason` is the agent's own words. `agentId` is the agent that handed over and `callId` the call it was on (`null` off a call).

```json theme={null}
{
  "id": "evt_1a7f3c9e-5b2d-4e8a-9f6c-0d3b7e1a4c25",
  "event": "conversation.escalated",
  "sentAt": "2026-10-06T04:32:12.880Z",
  "data": {
    "conversationId": "conv_3f6b2d1e-8a4c-4f7b-9e21-6c0d5a7b8e94",
    "agentId": "ag_3f6a9c21-7d4e-4b58-9a1f-0c2e8b7d5a34",
    "callId": null,
    "reason": "The customer asked to speak to someone about a refund."
  }
}
```

### `conversation.resolved`

A teammate marked the conversation done. Sent once, when the status actually changes.

```json theme={null}
{
  "id": "evt_6e2b8d4f-1c7a-4f3e-a9b5-8d0c2e6f1a37",
  "event": "conversation.resolved",
  "sentAt": "2026-10-06T05:10:03.551Z",
  "data": {
    "conversationId": "conv_3f6b2d1e-8a4c-4f7b-9e21-6c0d5a7b8e94"
  }
}
```

### `call.completed`

The moment a call ends, before it has been read. `outcome` is `completed`, `missed` or `failed`; `hangup` is `answered`, `no_answer`, `busy`, `rejected`, `unreachable`, `cancelled`, `voicemail`, `before_agent` or `failed`; `phone` is null on a web call. `campaignId` is present only for a campaign's call, and `id`, `reference` and `metadata` only for a call placed through the API.

```json theme={null}
{
  "id": "evt_3c9a5e1b-7d4f-4b2a-8e6c-1f0d9a3b5c49",
  "event": "call.completed",
  "sentAt": "2026-10-06T04:33:12.020Z",
  "data": {
    "callRef": "out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60",
    "conversationId": "conv_3f6b2d1e-8a4c-4f7b-9e21-6c0d5a7b8e94",
    "outcome": "completed",
    "hangup": "answered",
    "seconds": 182,
    "direction": "outbound",
    "surface": "phone",
    "phone": "919876543210",
    "campaignId": "cmp_7a1e9c3b-2d4f-4b8a-a6e0-1f5c8d2b9e47",
    "id": "out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60",
    "reference": "LSQ-42",
    "metadata": {
      "deal_id": "D-19",
      "owner": "Ravi"
    },
    "quality": {
      "turns": 14,
      "responseMs": { "median": 1180, "p90": 1920, "max": 3410 },
      "firstTokenMs": { "median": 610, "p90": 940, "max": 1730 },
      "longSilences": 1,
      "longSilenceSeconds": 10,
      "longestSilenceSeconds": 12.4,
      "interruptions": 2,
      "modelErrors": 0,
      "rescues": 1
    },
    "endedAt": "2026-10-06T04:33:11.902Z"
  }
}
```

`quality` is how the call went in numbers (see [Call quality](#call-quality)); it
can be `null` when the call ended before its figures were ready. `forwardedTo`
appears only on a call your number forwarded to a phone, and is that phone's
number; it is left out of every other call.

### `call.analysed`

The call once it has been read: exactly the object [Get Call](/api-reference/calls/get-call) returns. `quality` can be `null` (see [Call quality](#call-quality)), `handedTo` is empty unless the call was [handed to another agent](#calls-handed-to-another-agent), and `forwardedTo` is `null` unless the call was forwarded to a phone.

```json theme={null}
{
  "id": "evt_8f4d2a6c-3e9b-4c1f-b7a5-6d2e0f8c4a51",
  "event": "call.analysed",
  "sentAt": "2026-10-06T04:33:20.402Z",
  "data": {
    "id": "out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60",
    "callRef": "out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60",
    "reference": "LSQ-42",
    "metadata": {
      "deal_id": "D-19",
      "owner": "Ravi"
    },
    "attempt": 1,
    "status": "completed",
    "direction": "outbound",
    "phone": "919876543210",
    "from": "918045678901",
    "agent": {
      "id": "ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71",
      "name": "Skyline Sales"
    },
    "scheduledFor": null,
    "startedAt": "2026-10-06T04:30:02.118Z",
    "answeredAt": "2026-10-06T04:30:09.540Z",
    "endedAt": "2026-10-06T04:33:11.902Z",
    "seconds": 182,
    "hangup": "answered",
    "variables": {
      "lead_name": "Asha",
      "project": "Sky Towers"
    },
    "summary": "Asha is keen on a 2 BHK at Sky Towers with a budget around 80 lakh. She asked to visit the site on Saturday.",
    "fields": {
      "budget": 8000000,
      "interest": "Hot",
      "site_visit": true
    },
    "transcript": [
      {
        "speaker": "agent",
        "text": "Hello Asha, I'm calling from Skyline Homes about your enquiry for Sky Towers.",
        "at": "2026-10-06T04:30:10.204Z"
      },
      {
        "speaker": "customer",
        "text": "Haan, boliye. I wanted a 2 BHK.",
        "at": "2026-10-06T04:30:16.880Z"
      }
    ],
    "recording": {
      "url": "https://app.thinnest.ai/api/v1/recordings/3b7e1c90-5a2d-4e8f-9c61-0d4b7a2e8f13?expires=1762403402&sig=8c1f0e7a92b4d3c6e5f1a0b9c8d7e6f5a4b3c2d1",
      "expiresAt": "2026-11-05T04:30:02.118Z",
      "ready": true
    },
    "analysedAt": "2026-10-06T04:33:20.311Z",
    "retryScheduledFor": null,
    "costMicro": 6370000,
    "currency": "INR",
    "quality": {
      "turns": 14,
      "responseMs": { "median": 1180, "p90": 1920, "max": 3410 },
      "firstTokenMs": { "median": 610, "p90": 940, "max": 1730 },
      "longSilences": 1,
      "longSilenceSeconds": 10,
      "longestSilenceSeconds": 12.4,
      "interruptions": 2,
      "modelErrors": 0,
      "rescues": 1
    },
    "handedTo": [
      {
        "agent": { "id": "ag_7b1d4e90-2c3a-4f6e-8d15-9a0b3c2e4f71", "name": "Site Visits" },
        "from": { "id": "ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71", "name": "Skyline Sales" },
        "at": "2026-10-06T04:31:40.000Z"
      }
    ],
    "forwardedTo": null,
    "error": null
  }
}
```

### `campaign.finished`

Everyone on a broadcast (`kind: "whatsapp"`) or a calling campaign (`kind: "voice"`) has been reached or given up on. `skipped` is people who withdrew consent before their turn.

```json theme={null}
{
  "id": "evt_2b6e0c8a-9f3d-4a7e-8c4b-5e1f3d7a9b63",
  "event": "campaign.finished",
  "sentAt": "2026-10-06T13:02:44.311Z",
  "data": {
    "campaignId": "cmp_7a1e9c3b-2d4f-4b8a-a6e0-1f5c8d2b9e47",
    "name": "Diwali site visits",
    "kind": "voice",
    "recipients": 120,
    "sent": 104,
    "failed": 9,
    "skipped": 7,
    "finishedAt": "2026-10-06T13:02:44.180Z"
  }
}
```

### `contact.opted_out`

During a call, somebody asked not to be called again and their number went on the do-not-call list. `callId` is the call's id; `source` is always `"call"`; `reason` is what the caller said, as recorded (up to 160 characters, in the language they spoke), or `null` when the agent did not record their words.

```json theme={null}
{
  "id": "evt_5a3f7d1e-2c8b-4e6a-9d0f-7b4c1e5a3d75",
  "event": "contact.opted_out",
  "sentAt": "2026-10-06T04:32:40.640Z",
  "data": {
    "phone": "+919876543210",
    "callId": "out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60",
    "source": "call",
    "optedOutAt": "2026-10-06T04:32:40.511Z",
    "reason": "please don't call me again"
  }
}
```

### `call.problem`

Something went wrong while a call was live. `kind` is `no_answer_from_model`, `byok_failed`, `slow_reply` or `voice_failed`; `detail` says what happened in a sentence; `callId` is the id [Get Call](/api-reference/calls/get-call) takes. Sent at most once per kind per call.

```json theme={null}
{
  "id": "evt_4d8b2f6a-1e3c-4a9d-b5f7-0c6e2a8d4b87",
  "event": "call.problem",
  "sentAt": "2026-10-06T04:31:02.715Z",
  "data": {
    "callId": "out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60",
    "agentId": "ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71",
    "kind": "slow_reply",
    "detail": "A reply took 6.2 seconds to start.",
    "at": "2026-10-06T04:31:02.702Z"
  }
}
```

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