> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Call many people

> POST /api/v1/calls/batch — up to 200 calls in one request, paced by us.

```http theme={null}
POST /api/v1/calls/batch
Authorization: Bearer ta_live_…
Content-Type: application/json
Idempotency-Key: open-house-invites-17-sep
```

```json theme={null}
{
  "purpose": "I'm calling from Skyline Homes about Saturday's open house at Sky Towers.",
  "callingHours": { "start": "10:00", "end": "19:00" },
  "extract": [{ "name": "attending", "type": "boolean" }, { "name": "guests", "type": "integer" }],
  "summary": true,
  "variables": { "project": "Sky Towers" },
  "calls": [
    { "to": "919876543210", "name": "Asha Rao", "reference": "LSQ-42", "variables": { "lead_name": "Asha" } },
    { "to": "919876543211", "name": "Ravi Menon", "reference": "LSQ-43", "variables": { "lead_name": "Ravi" } }
  ]
}
```

```json theme={null}
{
  "accepted": [
    { "id": "sch_…", "to": "919876543210", "reference": "LSQ-42", "from": null, "status": "scheduled", "scheduledFor": "2026-09-17T04:30:00Z" },
    { "id": "sch_…", "to": "919876543211", "reference": "LSQ-43", "from": null, "status": "scheduled", "scheduledFor": "2026-09-17T04:30:00Z" }
  ],
  "refused": [],
  "limit": 200
}
```

Everything [a single call](/api-reference/place-call) accepts — `callingHours`,
`extract`, `summary`, `variables`, `metadata`, `scheduledAt`, `retry`, `from`,
`overrides` — can be set once for the batch and again on an entry. The entry's value replaces the
batch's, except `variables`, which merge with the entry's on top.

## How it runs

* **Every entry is queued**, never dialled while you wait. Each is placed from
  its `scheduledFor` onward — now, or when its hours open — at the pace your
  plan's lines and balance allow. `status` is `scheduled` for all of them.
* **Each entry is checked on its own**: the do-not-contact rules, the hours, one
  waiting call per person, and that its `from` and `overrides` are ones the
  agent can use. A bad number lands in `refused` with a reason and
  does not stop the others.
* **Each reports like a single call**: `call.analysed` when it ends, and
  [`GET /api/v1/calls/{id}`](/api-reference/get-call) any time, under its own
  `sch_…` id.
* **Send an `Idempotency-Key`.** A retried request queues nobody twice.

## Limits

200 entries per request. The same number twice in one batch is refused the
second time. A person who already has a call waiting on this agent is refused
with that call's id.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.