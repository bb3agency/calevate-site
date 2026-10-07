> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Test chat

> Talk to your own agent and read its reply — to check a change works without opening the console.

```http theme={null}
POST /api/v1/agents/{id}/test-chat
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{ "message": "Where is my order 10432?" }
```

```json theme={null}
{
  "session": "vr_4f1c09e2b7a84d55a1e0c3b2d9f86a71",
  "reply": "Your order 10432 shipped on 3 October and should reach you by Friday.",
  "tools": [
    {
      "name": "get_order",
      "input": { "order_id": "10432" },
      "output": "{\"status\":\"shipped\",\"shipped_on\":\"2026-10-03\"}"
    }
  ]
}
```

It is your real agent — the same instructions, model, knowledge and actions a
website visitor talks to, like the console's Playground. Use it after changing
an instruction or an [action](/api-reference/actions) to see what the agent now
does, and which of your systems it called with what.

## Continue a conversation

Send the `session` from the previous answer back with the next message. Leave
it out to start a new conversation.

<ParamField body="message" type="string" required>
  What the customer says. Up to 4,000 characters.
</ParamField>

<ParamField body="session" type="string">
  The `session` a previous test chat answered with.
</ParamField>

## Nobody is contacted

<Note>
  In a test chat, everything that would **phone, message, email or send a code
  to a person**, or **create or change a calendar booking**, is switched off —
  callbacks, calling now, WhatsApp, email replies, verification codes, and
  calendar booking changes. The agent tells you what it would have done
  instead, for example *"I would schedule a callback for +91… at 5pm."*
</Note>

What still runs for real, because it only reaches your own business:

* Your **actions** and connected systems — a `POST` action does its write.
* **Lead capture** — the `lead.captured` webhook is sent.
* **Escalation** to your team.
* Reading your calendar's availability.

Test chats are real website conversations: they appear in your inbox, like
Playground chats, and count towards your message allowance.

## Errors

| Status | When |
| - | - |
| `400` | No `message`, or a `session` that did not come from a test chat |
| `403` | The key is read-only — a test chat runs the model, so it needs a build or full-access key |
| `404` | The agent is not in your workspace |
| `409` | The agent's website chat is switched off |
| `429` | Messages sent faster than a person could type. Wait a few seconds |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.