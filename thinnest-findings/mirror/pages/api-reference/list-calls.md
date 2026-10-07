> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# List calls

> GET /api/v1/calls — every call your agents made or took, newest first.

```http theme={null}
GET /api/v1/calls?agent=ag_5c4a…&status=completed&since=2026-09-17
Authorization: Bearer ta_live_…
```

```json theme={null}
{
  "items": [
    {
      "id": "out_9f2c1a44-…",
      "callRef": "out_9f2c1a44-…",
      "reference": "LSQ-42",
      "metadata": { "deal_id": "D-19" },
      "attempt": 1,
      "status": "completed",
      "direction": "outbound",
      "phone": "919876543210",
      "agent": { "id": "ag_5c4a…", "name": "Skyline Sales" },
      "scheduledFor": null,
      "startedAt": "2026-09-17T04:30:02Z",
      "answeredAt": "2026-09-17T04:30:09Z",
      "endedAt": "2026-09-17T04:33:11Z",
      "seconds": 182,
      "hangup": "answered",
      "variables": { "lead_name": "Asha" },
      "summary": "Asha is keen on a 2BHK…",
      "fields": { "budget": 8000000 },
      "analysedAt": "2026-09-17T04:33:20Z",
      "error": null
    }
  ],
  "nextCursor": "MjAyNi0wOS0xN1Qw…"
}
```

The same fields as [one call's results](/api-reference/get-call), minus the
transcript, the recording link and `retryScheduledFor` — read the single call
for those.

A call with retries appears **once per try**, each row under the same `id` with
its own `attempt`.

## Query

| Parameter | |
| - | - |
| `agent` | An `ag_…` id |
| `status` | `ringing`, `connected`, `completed`, `missed` or `failed` |
| `reference` | Your own reference, as sent when the call was placed |
| `since`, `until` | A date (`2026-09-17`) or instant (`2026-09-17T10:00:00Z`), on when the call started |
| `limit` | 1–100, default 25 |
| `cursor` | The `nextCursor` of the previous page |

Calls still waiting to ring (`sch_…` ids) are not listed; read them one at a
time until they ring, after which they appear here under the same id.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.