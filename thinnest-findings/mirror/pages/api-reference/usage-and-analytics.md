> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Usage and analytics

> Read your usage, balance, agent analytics, call totals and WhatsApp totals — the numbers to build a dashboard on.

Four read-only endpoints for building your own dashboard. Every number is the
same one the console shows — the Usage page, the dashboard, and each agent's
Analytics page — so your dashboard and the console always agree.

A **Read-only** key is enough for all of them. See
[Choose what each key can do](/api-reference/authentication#choose-what-each-key-can-do).

| Method | Path | What |
| - | - | - |
| `GET` | `/usage` | Plan, replies this month, allowance, balance, replies per day |
| `GET` | `/agents/{id}/analytics` | One agent's conversations, leads, escalations, unanswered questions |
| `GET` | `/calls/summary` | Call totals and a series |
| `GET` | `/whatsapp/summary` | WhatsApp sent, delivered, read, failed, received |

<Note>
  **Money is in micro-units** of `currency`: `1000000` is one rupee (INR) or one
  dollar (USD). Divide by 1,000,000 to show it.
</Note>

## Usage and balance

```http theme={null}
GET /api/v1/usage?days=30
```

```json theme={null}
{
  "plan": "payg",
  "currency": "INR",
  "period": { "start": "2026-10-01T00:00:00.000Z", "end": "2026-11-01T00:00:00.000Z" },
  "replies": { "used": 1240, "included": null, "metered": true, "stopped": false },
  "wallet": {
    "balanceMicro": 1850000000,
    "availableMicro": 1350000000,
    "heldMicro": 500000000,
    "creditMicro": 0,
    "creditExpiresAt": null
  },
  "daily": [{ "day": "2026-10-04", "replies": 52 }, { "day": "2026-10-05", "replies": 61 }]
}
```

| Field | Means |
| - | - |
| `period` | This calendar month, in UTC — what `replies.used` counts |
| `replies.metered` | `true`: every reply is paid from your balance. `false`: an allowance of `included` replies this period, and `stopped` once it is used up |
| `wallet.balanceMicro` | Your balance, as on the billing page |
| `wallet.availableMicro` | What can be spent now — the balance less money held for phone-number rent renewing soon |
| `wallet.creditMicro` | Plan credit included in the balance, and when it expires |
| `wallet` | `null` on the Free plan, which has no balance |
| `daily` | Replies per UTC day for the last `days` (1–90, default 30) |

## Agent analytics

```http theme={null}
GET /api/v1/agents/{id}/analytics?days=30&rows=20
```

```json theme={null}
{
  "days": 30,
  "totals": {
    "conversations": 412, "customers": 368, "messages": 3104, "agent_replies": 1530,
    "leads": 57, "escalated": 12, "resolved": 140, "human_handled": 9,
    "searches": 820, "unanswered": 64
  },
  "daily": [{ "day": "2026-10-05", "conversations": 18, "replies": 71, "leads": 3 }],
  "hourly": [{ "hour": 9, "conversations": 41 }],
  "channels": [{ "kind": "whatsapp", "conversations": 260 }, { "kind": "web", "conversations": 152 }],
  "knowledgeGaps": [{ "query": "do you deliver on sunday", "asked": 7, "last_asked": "2026-10-05T08:12:00Z", "best_similarity": 0.41 }],
  "topQuestions": [{ "query": "where is my order", "asked": 96, "answered": 94, "last_asked": "2026-10-05T10:02:00Z" }],
  "derived": { "neededAPerson": 21, "answerRate": 0.92 }
}
```

* `days` is a rolling window, 1–90 (default 30). `rows` caps the two question
  lists, 1–100 (default 20).
* `resolved` and `escalated` count conversations by their **current** status.
* `knowledgeGaps` are questions the agent searched its knowledge for and found
  nothing — the list to write new knowledge from.
* `derived.neededAPerson` is escalated plus handled by a person;
  `derived.answerRate` is the share of knowledge searches that found an answer
  (`null` when there were none).
* Days and hours are in UTC.

## Call totals

```http theme={null}
GET /api/v1/calls/summary?days=7
```

```json theme={null}
{
  "days": 7,
  "timezone": "Asia/Kolkata",
  "grain": "day",
  "calls": 230, "inbound": 140, "outbound": 90,
  "answered": 198, "missed": 26, "failed": 6,
  "seconds": 41820,
  "debitMicro": 1394000000,
  "surfaces": { "phone": 210, "web": 14, "whatsapp": 6 },
  "series": [{ "bucket": "2026-10-05", "inbound": 22, "outbound": 15, "answered": 33, "missed": 4, "minutes": 118 }]
}
```

`days` is 1–90 (default 7). With `days=1` the series is by hour. Buckets are in
your workspace's time zone. `debitMicro` is what the calls cost you.

## WhatsApp totals

```http theme={null}
GET /api/v1/whatsapp/summary?days=7
GET /api/v1/whatsapp/summary?from=2026-09-01&to=2026-09-30
```

```json theme={null}
{
  "from": "2026-09-01",
  "to": "2026-09-30",
  "timezone": "Asia/Kolkata",
  "grain": "day",
  "sent": 1820, "delivered": 410, "read": 1290, "failed": 34, "noReceipt": 86,
  "received": 2210,
  "series": [{ "bucket": "2026-09-30", "sent": 61, "received": 70 }],
  "errors": [{ "error": "131049", "n": 21 }],
  "cost": {
    "currency": "INR",
    "totalMicro": 214350000,
    "complete": true,
    "byCategory": [
      { "category": "marketing", "messages": 1200, "costMicro": 191400000 },
      { "category": "utility", "messages": 620, "costMicro": 22950000 }
    ]
  }
}
```

`cost` is what the WhatsApp messages in the window cost you, priced exactly as
the WhatsApp dashboard prices them, by Meta category for the messages you sent.
`complete: false` means some messages are not priced yet — Meta has not
reported them, or there is no rate card for that country — so `totalMicro` is
what is known so far.

Either a rolling `days` (1–90, default 7) or a `from`/`to` range (inclusive, up
to 366 days), in your workspace's time zone. `errors` counts failures by
WhatsApp error code — see [Not delivered](/whatsapp/not-delivered).

## Errors

| Status | When |
| - | - |
| `400` | `days`, `rows` or a date range out of bounds |
| `404` | The agent is not in your workspace |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.