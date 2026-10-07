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
[broadcasts](/whatsapp/broadcasts) instead.

## Base URL

```
https://app.thinnest.ai/api/v1
```

## Endpoints

| Method | Path | What |
| - | - | - |
| `POST` | `/messages` | [Send a template to one customer](/api-reference/send-message) |
| `POST` | `/codes` | [Send a one-time code](/api-reference/send-a-code) |
| `POST` | `/calls` | [Ring one customer](/api-reference/place-call), and get the results back |
| `GET` | `/calls/{id}` | [A call's results](/api-reference/get-call) — summary, fields, transcript, recording |
| `DELETE` | `/calls/{id}` | [Cancel a waiting call, or end a live one](/api-reference/get-call#cancelling-or-ending-a-call) |
| `POST` | `/calls/batch` | [Ring up to 200 people](/api-reference/batch-calls) |
| `GET` | `/calls` | [List calls](/api-reference/list-calls) |
| `…` | `/agents`, `/agents/{id}` | [Agents](/api-reference/agents) — create, read, update, delete |
| `…` | `/agents/{id}/knowledge` | [What an agent knows](/api-reference/knowledge) |
| `…` | `/agents/{id}/actions` | [Actions](/api-reference/actions) — let the agent call your own API |
| `POST` | `/agents/{id}/test-chat` | [Talk to your own agent](/api-reference/test-chat) and read its reply |
| `GET` | `/templates`, `/sequences` | [The template names and sequence ids](/api-reference/templates-and-sequences) the sending endpoints take |
| `…` | `/campaigns`, `/campaigns/{id}` | [Campaigns](/api-reference/campaigns) — results, and pause, resume, cancel |
| `…` | `/conversations/{id}/status`, `/assign`, `/members` | [Resolve, hand back, take over and assign](/api-reference/conversations#resolve-hand-back-or-take-over) |
| `GET` | `/usage`, `/agents/{id}/analytics`, `/calls/summary`, `/whatsapp/summary` | [Usage and analytics](/api-reference/usage-and-analytics) — the numbers to build a dashboard on |
| `GET` | `/voices`, `/models`, `/phone-numbers` | [The lists an agent is configured from](/api-reference/voices-and-models) |
| `…` | `/contacts`, `/contacts/{id}` | [Contacts](/api-reference/contacts) |
| `…` | `/webhooks`, `/webhooks/{id}` | [Webhook endpoints](/api-reference/webhooks) |
| `POST` | `/events` | Report an event, which can enrol a contact in a [sequence](/whatsapp/sequences) |
| `POST` | `/sequences/{sequenceId}/enrolments` | Enrol a contact directly |

Every id is prefixed by what it is — `ag_`, `act_`, `cmp_`, `cust_`, `doc_`, `wh_` — and every list
takes `limit` (up to 100) and `cursor`, answering `{ "items": […],
"nextCursor": "…" | null }`. Resource endpoints share a limit of 240 requests a
minute per workspace.

## What it will not do

<Warning>
  * **Send an unapproved template.** Meta refuses it, so we refuse it earlier and
    with a clearer message.
  * **Send marketing to somebody who opted out.** Refused with `409`. Utility and
    authentication still reach them, and must.
  * **Send free-form text.** Outside the 24-hour window WhatsApp carries only
    approved templates. Inside it, the conversation belongs to the agent and the
    inbox.
</Warning>

## Start here

<CardGroup cols={2}>
  <Card title="Authentication" icon="key" href="/api-reference/authentication">
    Creating a key, and where it must not go.
  </Card>

  <Card title="Send a message" icon="paper-plane" href="/api-reference/send-message">
    The one endpoint most integrations need.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.