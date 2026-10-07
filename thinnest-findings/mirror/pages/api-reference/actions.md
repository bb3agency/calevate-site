> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Actions

> Let an agent call your own API — create, test, switch on, change and remove its actions.

An action is an HTTPS endpoint of yours that the agent may call
mid-conversation, with arguments it fills from what the customer said. It is how
an agent uses data that stays in your own database. The console's version is
[Call your own API](/agent/custom-api).

```http theme={null}
POST /api/v1/agents/{id}/actions
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{
  "name": "get_order",
  "description": "Look up an order's status by its number before answering anything about delivery.",
  "method": "GET",
  "url": "https://api.yourapp.com/orders/{{order_id}}",
  "parameters": [
    { "name": "order_id", "description": "The order number, e.g. 10432", "required": true }
  ],
  "headers": { "Authorization": "Bearer your-secret" }
}
```

```json theme={null}
{
  "id": "act_9b2f…",
  "agent": "ag_5c4a5f93-…",
  "name": "get_order",
  "description": "Look up an order's status by its number before answering anything about delivery.",
  "method": "GET",
  "url": "https://api.yourapp.com/orders/{{order_id}}",
  "parameters": [{ "name": "order_id", "description": "The order number, e.g. 10432", "required": true }],
  "bodyTemplate": null,
  "headerNames": ["Authorization"],
  "speakBefore": null,
  "speakAfter": null,
  "enabled": false,
  "createdAt": "2026-10-05T09:41:00Z",
  "updatedAt": "2026-10-05T09:41:00Z"
}
```

<Warning>
  **A new action is off.** Test it, then switch it on with
  `PATCH { "enabled": true }` — from that moment anybody talking to the agent can
  cause this call. Sending `enabled` when creating is refused.
</Warning>

## Endpoints

| Method | Path | What |
| - | - | - |
| `GET` | `/agents/{id}/actions` | List, newest first |
| `POST` | `/agents/{id}/actions` | Create one, switched off |
| `GET` | `/agents/{id}/actions/{actionId}` | One action |
| `PATCH` | `/agents/{id}/actions/{actionId}` | Change any field, or `enabled` |
| `DELETE` | `/agents/{id}/actions/{actionId}` | Remove it and its credential |
| `POST` | `/agents/{id}/actions/{actionId}/test` | Call it once, for real |

## Fields

<ParamField body="name" type="string" required>
  The tool name the agent sees: 3–40 characters, lowercase letters, numbers and
  underscores, starting with a letter. Cannot be one of the agent's built-in
  tools.
</ParamField>

<ParamField body="description" type="string" required>
  When the agent should call it. The model decides from this sentence alone —
  see [the description is the whole thing](/agent/custom-api#the-description-is-the-whole-thing).
</ParamField>

<ParamField body="url" type="string" required>
  `https://` only, with `{{placeholders}}` for parameters. Addresses inside
  private networks are refused when called.
</ParamField>

<ParamField body="method" type="string" default="GET">
  `GET`, `POST`, `PUT`, `PATCH` or `DELETE`.
</ParamField>

<ParamField body="parameters" type="object[]">
  Up to 20 `{ name, description, required }`. Every placeholder in `url` and
  `bodyTemplate` needs one, and the agent fills them from the conversation.
</ParamField>

<ParamField body="bodyTemplate" type="string">
  JSON with **quoted** placeholders — `{"id": "{{order_id}}"}`. It must still be
  valid JSON once the blanks are filled.
</ParamField>

<ParamField body="headers" type="object">
  Up to 10, e.g. `Authorization`. **Write-only:** stored sealed; only the names
  come back, as `headerNames`. On `PATCH`, leave it out to keep the saved ones —
  sending any **replaces the whole set**, so include every header the call needs.
</ParamField>

<ParamField body="speakBefore" type="string">
  On phone calls, what the agent says while the call to your API runs. Up to 200
  characters.
</ParamField>

<ParamField body="speakAfter" type="string">
  On phone calls, what it says while it turns your answer into a reply.
</ParamField>

<ParamField body="enabled" type="boolean">
  `PATCH` only. `true` puts the action within reach of every conversation.
</ParamField>

A `PATCH` is checked against the action as it will be saved — a new URL is
checked against the parameters already there.

## Test an action

```http theme={null}
POST /api/v1/agents/{id}/actions/{actionId}/test
```

```json theme={null}
{ "arguments": { "order_id": "10432" } }
```

```json theme={null}
{ "ok": true, "status": 200, "result": "Order 10432 shipped on 3 October…" }
```

The call is made for real, through exactly the address checks and credentials
the agent uses, and works while the action is off. `result` is what the agent
would have read — about 4,000 characters at most. On a `POST` action the test
**does** the write.

## Errors

| Status | When |
| - | - |
| `400` | A rule above is broken — the message says which |
| `404` | The agent or action is not in your workspace |
| `409` | The agent already has an action with that name |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.