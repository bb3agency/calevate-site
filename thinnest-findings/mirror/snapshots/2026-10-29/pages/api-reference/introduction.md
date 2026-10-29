> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# API reference

> The transactional API — the messages your systems send, not the ones your marketing does.

This API exists for the messages a **system** sends: an order confirmation, a
delivery update, a one-time password. One customer, one event, right now.

It is not the campaigns API, and the difference is not cosmetic.

| | Broadcasts | This API |
| - | - | - |
| Triggered by | A person, in the console | Your code, on an event |
| Audience | A list computed from consent | One customer |
| Typical category | Marketing | Utility or authentication |
| Reaches an opted-out contact | No | Yes, for utility and authentication |

If you find yourself looping this endpoint over a list of customers, you want
[broadcasts](https://docs.thinnest.ai/whatsapp/broadcasts.md) instead.

## Base URL

```
https://app.thinnest.ai/api/v1
```

## Endpoints

| Method | Path | What |
| - | - | - |
| `POST` | `/messages` | [Send a template to one customer](https://docs.thinnest.ai/api-reference/messages/send-message.md) |
| `POST` | `/codes` | [Send a one-time code](https://docs.thinnest.ai/api-reference/one-time-codes/send-one-time-code.md) |
| `POST` | `/calls` | [Ring one customer](https://docs.thinnest.ai/api-reference/calls/place-call.md), and get the results back |
| `GET` | `/calls/{id}` | [A call's results](https://docs.thinnest.ai/api-reference/calls/get-call.md) — summary, fields, transcript, recording |
| `DELETE` | `/calls/{id}` | [Cancel a waiting call, or end a live one](https://docs.thinnest.ai/api-reference/calls/get-call.md) |
| `POST` | `/calls/batch` | [Ring up to 200 people](https://docs.thinnest.ai/api-reference/calls/place-batch-calls.md) |
| `GET` | `/calls` | [List calls](https://docs.thinnest.ai/api-reference/calls/list-calls.md) |
| `…` | `/agents`, `/agents/{id}` | [Agents](https://docs.thinnest.ai/api-reference/agents/create-agent.md) — create, read, update, delete |
| `…` | `/agents/{id}/knowledge` | [What an agent knows](https://docs.thinnest.ai/api-reference/knowledge/add-knowledge-document.md) |
| `…` | `/agents/{id}/actions` | [Actions](https://docs.thinnest.ai/api-reference/actions/create-action.md) — let the agent call your own API |
| `POST` | `/agents/{id}/test-chat` | [Talk to your own agent](https://docs.thinnest.ai/api-reference/agents/test-chat.md) and read its reply |
| `GET` | `/templates`, `/sequences` | [The template names and sequence ids](https://docs.thinnest.ai/api-reference/templates/list-templates.md) the sending endpoints take |
| `…` | `/campaigns`, `/campaigns/{id}` | [Campaigns](https://docs.thinnest.ai/api-reference/campaigns/create-campaign.md) — results, and pause, resume, cancel |
| `…` | `/conversations/{id}/status`, `/assign`, `/members` | [Resolve, hand back, take over and assign](https://docs.thinnest.ai/api-reference/conversations/list-conversations.md) |
| `GET` | `/usage`, `/agents/{id}/analytics`, `/calls/summary`, `/whatsapp/summary` | [Usage and analytics](https://docs.thinnest.ai/api-reference/usage/get-usage.md) — the numbers to build a dashboard on |
| `GET` | `/voices`, `/models`, `/phone-numbers` | [The lists an agent is configured from](https://docs.thinnest.ai/api-reference/voices/list-voices.md) |
| `…` | `/contacts`, `/contacts/{id}` | [Contacts](https://docs.thinnest.ai/api-reference/contacts/create-contact.md) |
| `…` | `/webhooks`, `/webhooks/{id}` | [Webhook endpoints](https://docs.thinnest.ai/api-reference/webhooks.md) |
| `POST` | `/events` | Report an event, which can enrol a contact in a [sequence](https://docs.thinnest.ai/whatsapp/sequences.md) |
| `POST` | `/sequences/{sequenceId}/enrolments` | Enrol a contact directly |

Every id is prefixed by what it is — `ag_`, `act_`, `cmp_`, `cust_`, `doc_`, `wh_` — and every list
takes `limit` (up to 100) and `cursor`, answering `{ "items": […],
"nextCursor": "…" | null }`. Resource endpoints share a limit of 240 requests a
minute per workspace.

## What it will not do

> [!WARNING]
>
> * **Send an unapproved template.** Meta refuses it, so we refuse it earlier and
>   with a clearer message.
> * **Send marketing to somebody who opted out.** Refused with `409`. Utility and
>   authentication still reach them, and must.
> * **Send free-form text.** Outside the 24-hour window WhatsApp carries only
>   approved templates. Inside it, the conversation belongs to the agent and the
>   inbox.

## Start here

> **[Authentication](https://docs.thinnest.ai/api-reference/authentication.md)**
>
> Creating a key, and where it must not go.

> **[Send a message](https://docs.thinnest.ai/api-reference/messages/send-message.md)**
>
> The one endpoint most integrations need.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.