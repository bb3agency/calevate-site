> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Authentication

> Bearer keys, and the one place they must never go.

```
Authorization: Bearer ta_live_…
```

Create a key in **Settings → API keys**. It is shown **once**, at creation, and
stored only as a hash — nothing can retrieve it afterwards, including us.

## This is not your widget key

<Warning>
  Your **public key** (`pk_…`) identifies which agent answers and is meant to be
  visible in your page source.

  Your **API key** (`ta_live_…`) can message any of your customers. It belongs in
  a server's environment. Putting it in your HTML hands anybody the ability to
  message your entire contact list.
</Warning>

## Choose what each key can do

When you create a key, you pick one of three access levels. The level applies
everywhere the key is used — your own code calling the API, and the MCP server.
A key's access cannot be changed later — create a new key and revoke the old one.

| Access level | What the key can do |
| - | - |
| **Full access** | Everything, including messaging your customers and placing calls. Keys created before access levels existed have full access. |
| **Build** | See everything, and set up agents, knowledge, actions, contacts and webhooks. It can also [test-chat](/api-reference/test-chat) an agent, resolve, take over and assign conversations, and pause or cancel campaigns. It **cannot** send messages or codes, place or end calls, reply to a customer, report events, add anyone to a sequence, or resume a campaign. Test chats and adding knowledge still count towards your usage. |
| **Read-only** | See everything. Change nothing. |

If a key tries something its access level does not allow, the request is
refused with `403` and a message saying what kind of key it is:

```json theme={null}
{ "error": "This API key is a build key: it can set up agents, actions, contacts and webhooks, but not message customers, send codes or place calls. Use a full key for that." }
```

<Tip>
  Connecting an AI assistant such as Claude Code or Cursor to the
  [ThinnestAI MCP server](/mcp/overview)? The MCP server can do exactly what its
  key can do, so choose **Build** to let it set things up without being able to
  contact a customer, or **Read-only** if it only needs to report. See
  [Connect your assistant to the MCP server](/mcp/connect).
</Tip>

## Revoking

Immediate. Revoked keys are kept along with their last-used time, because that
is the first thing anybody wants to know after a leak.

## Rate limits

Per organization, per minute.

```http theme={null}
HTTP/1.1 429 Too Many Requests
Retry-After: 60
```

Honour `Retry-After`. The limit exists because a loop in an integration can
spend a month of WhatsApp budget before anybody looks at a dashboard — and
because Meta rate-limits the number afterwards. The damage is money first and
reputation second.

<Note>
  Idempotency protects you from repeating **one** request. It does nothing about
  a thousand different ones. These are separate problems and both are guarded.
</Note>

## Storing the key

<CodeGroup>
  ```bash Environment theme={null}
  THINNEST_API_KEY=ta_live_xxxxxxxxxxxx
  ```

  ```js Node theme={null}
  const res = await fetch("https://app.thinnest.ai/api/v1/messages", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.THINNEST_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  ```

  ```python Python theme={null}
  import os, requests

  res = requests.post(
      "https://app.thinnest.ai/api/v1/messages",
      headers={"Authorization": f"Bearer {os.environ['THINNEST_API_KEY']}"},
      json=payload,
  )
  ```
</CodeGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.