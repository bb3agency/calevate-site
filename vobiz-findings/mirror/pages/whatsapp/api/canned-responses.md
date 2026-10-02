> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Canned responses API

> Create and manage WhatsApp canned responses on Vobiz - reusable reply snippets that agents trigger with a /shortcut command directly inside the inbox.

<Info>
  **How agents use them:** In the inbox, an agent types `/greeting` and the pre-saved content is automatically inserted into the reply box.
</Info>

**Base URL:** `https://api.vobiz.ai/api/v1/messaging`

**Authentication:** Every request requires `X-Auth-ID: MA_XXXXXXXX` and `X-Auth-Token: <token>` headers (a `Bearer` JWT is also accepted). Set `Content-Type: application/json` on requests with a body. Get your credentials from [console.vobiz.ai](https://console.vobiz.ai).

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

## Endpoints overview

| Method | Endpoint | Description |
| - | - | - |
| `GET` | `/api/v1/messaging/canned-responses` | List all canned responses |
| `POST` | `/api/v1/messaging/canned-responses` | Create a canned response |
| `DELETE` | `/api/v1/messaging/canned-responses/{id}` | Delete a canned response |

## List canned responses

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/canned-responses
```

Returns a paginated list of canned responses for your account. This request takes no path parameters and no request body.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/canned-responses" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "b3c4d5e6-f708-4192-a3b4-c5d6e7f80910",
      "shortcut": "/greeting",
      "content": "Hello! Thank you for reaching out. How can I help you today?",
      "created_at": "2026-03-01T10:00:00Z"
    },
    {
      "id": "c4d5e6f7-0819-42a3-b4c5-d6e7f8091021",
      "shortcut": "/hours",
      "content": "Our support hours are Monday-Friday, 9am-6pm IST.",
      "created_at": "2026-03-02T11:00:00Z"
    }
  ],
  "total": 2,
  "page": 1,
  "limit": 20,
  "has_more": false
}
```

## Create canned response

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/canned-responses
```

Create a new canned response. The `shortcut` is the trigger agents type in the inbox. The `content` is the full text inserted.

| Field | Required | Description |
| - | - | - |
| `shortcut` | Yes | Trigger keyword (e.g. `/greeting`) |
| `content` | Yes | Full text of the canned reply |

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/canned-responses" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{"shortcut":"/greeting","content":"Hello! Thank you for reaching out. How can I help you today?"}'
```

```json 201 Created theme={null}
{
  "id": "b3c4d5e6-f708-4192-a3b4-c5d6e7f80910",
  "shortcut": "/greeting",
  "content": "Hello! Thank you for reaching out. How can I help you today?",
  "created_at": "2026-03-01T10:00:00Z"
}
```

## Delete canned response

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/messaging/canned-responses/{id}
```

Permanently delete a canned response. Agents will no longer be able to trigger it via shortcut. Returns `204 No Content`.

```bash cURL theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/messaging/canned-responses/{id}" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```text 204 No Content theme={null}
// Empty body on success
```

## Canned response object

| Field | Type | Description |
| - | - | - |
| `id` | UUID | Canned response ID |
| `shortcut` | string | Trigger keyword (e.g. `/greeting`) |
| `content` | string | Full text inserted into the reply box |
| `created_at` | RFC3339 | Creation timestamp (UTC) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.