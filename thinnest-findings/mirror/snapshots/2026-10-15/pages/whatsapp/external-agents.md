> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Connect External Agent/CRM

> Answer WhatsApp customers from your own CRM or agent platform. ThinnestAI runs the WhatsApp side — the number, the inbox, templates and opt-outs.

**Connect WhatsApp → your number → Connect External Agent/CRM.**

You already have a CRM or an agent platform of your own — your own prompts, your
own voice and chat stack — and you want it on WhatsApp without building a
WhatsApp integration. Switch on
**Connect External Agent/CRM** for a number and ThinnestAI stops answering it. Every
message a customer sends is passed to your external agent, and its replies go back to the
customer through us.

What stays with ThinnestAI: the connected number, the shared
[inbox](/workspace/inbox) where your team sees every thread and can take one
over, [templates](/whatsapp/templates), [forms](/whatsapp/templates#forms), opt-outs
("STOP") and Meta's 24-hour rule.

## How a message travels

1. A customer writes to your WhatsApp number.
2. We store it in the inbox and post it to your platform's address as `message.received`.
3. Your agent decides what to say.
4. Your platform calls `POST /api/v1/conversations/{conversationId}/reply`.
5. We send it on WhatsApp and add it to the thread as the agent's reply.

Your agent can take as long as it needs — nothing waits on it. A reply sent
after the customer's [24-hour window](/meta/windows-and-pricing) has closed
must be an approved template.

## Only want the WhatsApp API?

If nothing of ours should answer — your own software does all of it — pick
**WhatsApp API** when you sign up, under *What will you use it for?*
You land on **WhatsApp** instead of Agents, and **every number you connect
starts with Connect External Agent/CRM already on**. There is no agent to set up and no
toggle to find; follow the steps under the number. Changed your mind — want voice or
our AI agent too? Pick another use case from the dropdown in the top bar; your
connected numbers keep answering through your software until you change them.

* **Start a conversation** with an approved template:
  [`POST /api/v1/messages`](/api-reference/messages/send-message). WhatsApp only lets a
  business message someone first with a template.
* **Reply** once they write back, with text, media, a form or a template:
  [`POST /api/v1/conversations/{id}/reply`](/api-reference/conversations/reply-to-conversation).
* **Read** threads and catch up on anything missed:
  [conversations](/api-reference/conversations/list-conversations).

You pay Meta's fee to Meta and 10% of it to us, per message. Nothing for AI —
no agent of ours runs. On the **Free plan**, your first **200 messages**
(one time) carry none of our charges; after that, switch to Pay as you go (no
monthly fee) to keep sending.

## Set it up

<Steps>
  <Step title="Connect your WhatsApp number">
    On **WhatsApp**, connect your own WhatsApp Business Account — a new one or
    one you already have.
  </Step>

  <Step title="Switch on Connect External Agent/CRM">
    Under the number, switch on **Connect External Agent/CRM**. Our agent picker
    moves to **Not assigned** and locks — nothing of ours answers this number.
    The number then shows these same steps. Only admins can change it; switching
    it off hands the number back, and you choose one of our agents again.
  </Step>

  <Step title="Create an API key">
    **Settings → API keys.** Send it on every call as
    `Authorization: Bearer ta_live_…`. See [authentication](/api-reference/authentication).
  </Step>

  <Step title="Give us your external agent's address">
    Under the number, paste the HTTPS address customer messages should be posted
    to and press **Save**. The **signing secret** is shown once — keep it. Saving
    again mints a new one.
  </Step>

  <Step title="Reply">
    Call [`POST /api/v1/conversations/{id}/reply`](/api-reference/conversations/reply-to-conversation)
    with the `conversationId` from the event.
  </Step>
</Steps>

<Warning>
  Until you save an address, customer messages go nowhere and nobody answers
  them. The WhatsApp page shows a red warning under the number when that is the
  case, and again if your platform starts refusing deliveries.
</Warning>

## What your webhook receives

```json theme={null}
{
  "event": "message.received",
  "sentAt": "2026-09-21T10:15:02Z",
  "data": {
    "conversationId": "conv_e0829641-…",
    "messageId": "msg_91c2…",
    "channel": "whatsapp",
    "from": "919876543210",
    "name": "Priya",
    "text": "Has my order shipped?",
    "media": null,
    "form": null,
    "receivedAt": "2026-09-21T10:15:01Z"
  }
}
```

* **`media`** — when the customer sent a photo, voice note, video or document:
  `{ "kind": "image" | "audio" | "video" | "file", "mimeType", "filename" }`.
  The file itself is not in the event — read the conversation's
  [messages](/api-reference/conversations/list-conversations) for a download link.
* **`form`** — when the customer submitted a WhatsApp form: `{ "answers": { "field": "value" } }`.
* **`text`** — the message, or a media message's caption.
* **`messageId`** — the same id the [messages API](/api-reference/conversations/list-conversations)
  returns, so you can tell a message you already handled from a new one.

Every delivery carries `x-thinnest-signature: sha256=…`, an HMAC-SHA256 of the
raw body under your signing secret. Check it before trusting the body.

Every message is sent, not just the last one in a burst. If a customer sends
three messages quickly, your platform gets three events.

## What your agent can send

| Send | When | Body |
| - | - | - |
| Text | Window open | `{ "text": "…" }` |
| A photo, video, audio or document | Window open | `{ "media": { "type": "image", "url": "https://…", "caption": "…" } }` |
| A WhatsApp form | Window open | `{ "form": "Delivery address" }` — its name on the Forms page |
| An approved template | Any time | `{ "template": { "name": "…", "variables": ["…"] } }` |

One kind per call. The full reference, with every refusal, is on
[Reply to a conversation](/api-reference/conversations/reply-to-conversation).

## When a person takes over

If a teammate takes a conversation over in the inbox, your agent's replies to
it are refused, and its new messages are not sent to your webhook, until the
conversation is handed back. That way the customer never has two voices
answering at once. The teammate's exchange can be read through the
[conversations API](/api-reference/conversations/list-conversations).

"STOP" and other opt-outs are handled before anything reaches you. The
customer is unsubscribed from marketing whatever your agent does.

## Pricing

Meta bills your WhatsApp Business Account directly for its fee on each message,
at [Meta's rates](/meta/windows-and-pricing). ThinnestAI charges **10% of Meta's
rate** per message, from your wallet — pay as you go, with no monthly
subscription. A message Meta does not charge for costs nothing from us either.
Replies your teammates send from the inbox or a connected helpdesk on these
numbers are charged the same way.

There is no AI usage to pay for on these numbers, because your agent does the
answering.

## If your endpoint misses a message

Each message is sent once. One your endpoint does not accept is not retried, and
the WhatsApp page shows the last failure under the number. Nothing is lost:
[read back what you missed](/api-reference/conversations/list-conversations)
with the conversations API.

## Not available yet

* **No typing indicator or read receipts** from your agent.
* **WhatsApp only.** Website chat, Telegram and voice are answered by
  ThinnestAI agents.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.