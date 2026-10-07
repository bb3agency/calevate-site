> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Campaigns

> Read your WhatsApp broadcasts' and calling campaigns' results, and pause, resume or cancel them.

Your broadcasts and calling campaigns, with their results, and the three
controls you need while one is running. Campaigns are **created and started in
the console** — the API does not launch them.

```http theme={null}
GET /api/v1/campaigns?status=sending
Authorization: Bearer ta_live_…
```

```json theme={null}
{
  "items": [
    {
      "id": "cmp_7a1c…",
      "agent": "ag_5c4a5f93-…",
      "name": "Diwali offer",
      "kind": "whatsapp",
      "status": "sending",
      "template": "diwali_offer_v2",
      "purpose": null,
      "counts": { "recipients": 1200, "sent": 640, "delivered": 610, "read": 402, "replied": 37, "failed": 9, "skipped": 14 },
      "scheduledAt": null,
      "startedAt": "2026-10-05T09:00:00Z",
      "finishedAt": null,
      "createdAt": "2026-10-04T16:20:00Z",
      "lastError": null
    }
  ],
  "nextCursor": null
}
```

## Endpoints

| Method | Path | What |
| - | - | - |
| `GET` | `/campaigns` | Newest first. `status` filters: `draft`, `sending`, `paused`, `sent`, `failed`, `cancelled` |
| `GET` | `/campaigns/{id}` | One campaign and its results |
| `POST` | `/campaigns/{id}/pause` | A sending campaign stops sending |
| `POST` | `/campaigns/{id}/resume` | A paused campaign sends again |
| `POST` | `/campaigns/{id}/cancel` | A draft, sending or paused campaign stops for good |

`kind` is `whatsapp` for a broadcast or `voice` for a calling campaign;
`purpose` is a calling campaign's reason for calling.

## Pausing, resuming and cancelling

Each answers the campaign as it now is. A campaign in a state the move does not
apply to is refused with `409` and says which state it is in — cancelling a
campaign that already finished does not pretend it worked.

* **Pause** stops further sends. Messages already handed to WhatsApp, and calls
  already placed, still complete.
* **Resume** sends again to everyone not yet reached, charged as usual — so it
  needs a **full-access** key.
* **Cancel** cannot be undone. Duplicate the campaign in the console to run it
  again.

A **Build** key can pause and cancel, since both only stop sending; it cannot
resume. See [Choose what each key can do](/api-reference/authentication#choose-what-each-key-can-do).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.