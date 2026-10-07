> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Templates and sequences

> Look up the template names and sequence ids the sending endpoints take.

[Send a message](/api-reference/send-message) takes a template **name**, and
[Enrol in a sequence](/api-reference/enrol-in-sequence) a sequence **id**. These
two lists are where to find them. Both are read-only — templates go through
Meta's review and sequences are composed in the console.

## Templates

```http theme={null}
GET /api/v1/templates?status=approved
Authorization: Bearer ta_live_…
```

```json theme={null}
{
  "items": [
    {
      "name": "order_update",
      "language": "en",
      "category": "utility",
      "status": "approved",
      "agent": "ag_5c4a5f93-…",
      "body": "Hi {{1}}, order {{2}} is on its way.",
      "variableCount": 2,
      "variableLabels": [{ "position": 1, "sample": "Priya" }, { "position": 2, "sample": "#10432" }],
      "buttonVariableCount": 1,
      "headerKind": "image",
      "createdAt": "2026-09-30T11:02:00Z"
    }
  ],
  "nextCursor": null
}
```

<ParamField query="status" type="string">
  `draft`, `pending`, `approved`, `rejected` or `paused`. Only `approved`
  templates can be sent.
</ParamField>

<ParamField query="category" type="string">
  `utility`, `marketing` or `authentication`.
</ParamField>

What a send needs, read from the template itself:

| Field | Means |
| - | - |
| `variableCount` | How many values `variables` must carry, in order — one per `{{n}}` in the body |
| `buttonVariableCount` | How many values `buttonVariables` must carry — one per link button with a blank |
| `headerKind` | `image`, `video` or `document` means pass `headerMediaUrl` |

## Sequences

```http theme={null}
GET /api/v1/sequences
```

```json theme={null}
{
  "items": [
    {
      "id": "3f1c2a90-…",
      "name": "Abandoned cart",
      "status": "active",
      "agent": "ag_5c4a5f93-…",
      "exitOnReply": true,
      "createdAt": "2026-09-12T08:00:00Z"
    }
  ],
  "nextCursor": null
}
```

Archived sequences are left out. Only `active` ones send. The `id` is the
`{sequenceId}` in `POST /sequences/{sequenceId}/enrolments`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.