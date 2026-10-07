> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Knowledge

> What an agent knows — list, add a page or text, remove.

```http theme={null}
POST /api/v1/agents/{id}/knowledge
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{ "url": "https://skylinehomes.example/sky-towers/prices" }
```

or

```json theme={null}
{ "title": "Sky Towers prices", "text": "A 2BHK starts at 80 lakh. A 3BHK starts at 1.1 crore…" }
```

```json theme={null}
{
  "id": "doc_f741…",
  "title": "Sky Towers prices",
  "type": "text",
  "source": "pasted",
  "status": "ready",
  "error": null,
  "createdAt": "2026-09-17T09:42:00Z",
  "passages": 3
}
```

## Endpoints

| Method | Path | What |
| - | - | - |
| `GET` | `/agents/{id}/knowledge` | The documents, newest first |
| `POST` | `/agents/{id}/knowledge` | Add a `url`, or `text` with an optional `title` |
| `DELETE` | `/agents/{id}/knowledge/{documentId}` | The document and every passage from it |

A URL is fetched and indexed **before the request answers**, exactly as the
console does it — so a slow site is a slow request, and `passages` says how
much was indexed. `status` is `ready` when the agent can cite it and `failed`
with `error` when the page could not be read ("requires JavaScript", "returned
403"), which are different problems with different fixes.

`text` is capped at 200,000 characters. Files are uploaded in the console.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.