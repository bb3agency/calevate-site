> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Keep your data in your database

> Use your own database and ThinnestAI's agents — the agent looks your data up live instead of us holding a copy.

You do not need to upload your customer list, orders or catalogue for the agent
to use them. Keep them in your own database, put a small API in front of it,
and the agent calls that API live, mid-conversation, on every channel —
website, WhatsApp, Telegram and phone calls.

With an MCP-connected assistant you can build the whole thing in one session:
the API in your app, the actions that connect it, and the webhooks that bring
results back.

## What stays where

Be precise about this when you explain it to your own customers.

| | Where it lives |
| - | - |
| Your records — customers, orders, stock, CSVs | **Your database.** The agent asks your API for one answer at a time |
| What your API returns for one question | Read by the agent to answer, then the conversation moves on |
| The conversation itself | Passes through ThinnestAI and the AI model while the agent answers. **We keep the conversation history** — the agent re-reads it to continue a conversation — and the contact it belongs to |
| What each action was called with | Kept by us as an audit trail of what the agent asked your system |
| Leads, escalations, call results | Sent to your webhook as they happen |

<Warning>
  **Not available yet:** automatic deletion of our copy of conversations after a
  window you choose, and a full-transcript event for chat and WhatsApp (calls
  already have one). Do not promise either to your customers until they ship.
</Warning>

## 1. Build the endpoints

Small and single-purpose — each one becomes one thing the agent can do.

```
GET  https://api.yourapp.com/orders/{{order_id}}
POST https://api.yourapp.com/appointments    {"name": "{{name}}", "slot": "{{slot}}"}
```

* **https only.** Addresses inside private networks are refused.
* **Authenticate** with a header you choose, e.g. `Authorization: Bearer <secret>`.
  We store it sealed and never show it again.
* **Answer within 10 seconds** — callers on the phone are waiting.
* **Return only what the agent needs.** It reads about 4,000 characters of the
  answer; an order's status, not the order history.
* **Treat every argument as untrusted** — it came from a stranger's message.
  Use parameterised queries and never let an argument pick a table or a URL.

## 2. Connect them

Ask your assistant, or do it step by step:

1. `create_action` — name (`get_order`), a description of **when** to call it
   (the agent decides from this sentence alone), the URL with placeholders, one
   parameter per placeholder, and your auth header.
2. `test_action` with sample arguments — a real call, through the same path the
   agent uses. Fix errors now, not when a customer is waiting.
3. `enable_action` — after your approval it goes live for everyone talking to
   the agent.
4. `update_agent` — tell the agent about it in its instructions: *"Look up the
   order with get\_order before answering anything about delivery."*

The same is available over the API: [Actions](/api-reference/actions/create-action).

## 3. Receive what happens

`create_webhook` with your endpoint and the events you want. The answer contains
a **signing secret, once** — store it in your receiver's environment.

Every delivery is a `POST` of `{ "event", "sentAt", "data" }` with the header
`x-thinnest-signature: sha256=<HMAC-SHA256 of the raw body>`. Verify the raw
bytes before parsing:

```ts theme={null}
import { createHmac, timingSafeEqual } from "node:crypto";

export function verify(rawBody: string, header: string, secret: string): boolean {
  const expected = Buffer.from("sha256=" + createHmac("sha256", secret).update(rawBody).digest("hex"));
  const actual = Buffer.from(header ?? "");
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}
```

| Event | Carries |
| - | - |
| `lead.captured` | Name, email, phone, note |
| `conversation.escalated` | The conversation, and why |
| `conversation.resolved` | The conversation a teammate marked done |
| `call.completed` | How a call ended, and how long it lasted |
| `call.analysed` | Summary, extracted details, full transcript, recording link |
| `campaign.finished` | Counts for a finished broadcast or call list |

To keep chat transcripts in your database today, fetch the messages
(`list_messages`) when `conversation.resolved` or `conversation.escalated`
arrives.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.