> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Tools

> Every tool the ThinnestAI MCP server offers, and what each one does.

Your assistant sees these tools with full descriptions and argument lists; this
page is the map. Tools marked **†** need your approval — see [Safety](/mcp/safety).

Which tools appear depends on the key: a **Read-only** key sees only the tools
that look; a **Build** key sees everything except sending, calling and the
WhatsApp tools that reach a person (marked **‡** below); a **Full access** key
sees all of them.

Ids are prefixed by what they are: `ag_` agent, `act_` action, `conv_`
conversation, `cust_` contact, `doc_` document, `wh_` webhook; calls are `out_`
(placed) or `sch_` (queued). Lists are newest first and take `limit` (up to 100)
and `cursor`.

## Agents

| Tool | What it does |
| - | - |
| `list_agents` | Your agents, with every setting |
| `get_agent` | One agent's settings |
| `create_agent` | A new agent — only a name is required |
| `update_agent` | Change instructions, greeting, model, language, voice, widget, the details it collects |
| `test_chat` | Talk to the agent as a customer and read its reply and the tools it used — nobody is contacted. See [Test chat](/api-reference/test-chat) |
| `delete_agent` † | Delete an agent and everything under it |

Connecting the agent to WhatsApp, a phone number or your website is still done
in the console.

## Knowledge

| Tool | What it does |
| - | - |
| `list_knowledge` | Documents the agent answers from, with their status |
| `add_knowledge` | Teach it from a web page or pasted text |
| `delete_knowledge` † | Remove a document |

<Note>
  Knowledge is stored with us. For data that must stay in your database, use an
  action instead — see [Keep your data in your database](/mcp/own-database).
</Note>

## Actions — your own API

| Tool | What it does |
| - | - |
| `list_actions` | The API calls this agent can make, and which are on |
| `create_action` | Let the agent call one of your HTTPS endpoints. Created **off** |
| `test_action` † | Call it once, for real, exactly as the agent would |
| `update_action` † | Change its address, arguments or headers |
| `enable_action` † | Switch it on — from then on anybody talking to the agent can trigger it — or off |
| `delete_action` † | Remove it and its saved credential |

## Contacts

| Tool | What it does |
| - | - |
| `list_contacts` | Filter by `tag`, `externalId` or `phone` |
| `get_contact` | One contact, with consent |
| `upsert_contact` | Create, or update the contact on that number |
| `update_contact` | Change a contact by id |
| `delete_contact` † | Erase a contact and their conversations and calls |

## Conversations

| Tool | What it does |
| - | - |
| `list_conversations` | Every channel; filter by `channel`, `status` (e.g. escalated) and `since` |
| `list_messages` | A conversation's messages, without internal team notes |
| `reply_to_conversation` † ‡ | Send one WhatsApp message into a conversation |
| `set_conversation_status` | Resolve, hand back to the agent, or take over |
| `assign_conversation` | Make it a teammate's job, by email — they are notified |
| `list_members` | Your teammates, to assign to |

## WhatsApp

| Tool | What it does |
| - | - |
| `list_templates` | Your templates, and what a send needs: how many values, button values, whether a header picture is required |
| `list_sequences` | Your sequences and their ids |
| `send_whatsapp_template` † ‡ | Send an approved template to one person |
| `send_code` † ‡ | Send a one-time code |
| `record_event` † ‡ | Report that something happened (e.g. `order.shipped`) — can start or stop sequences |
| `enrol_in_sequence` † ‡ | Start a sequence for one contact |

## Calls

| Tool | What it does |
| - | - |
| `place_call` † ‡ | Have an agent ring one person, now or later |
| `place_calls_batch` † ‡ | Queue up to 200 calls |
| `list_calls` | Filter by agent, status, reference, dates |
| `get_call` | Summary, extracted details, full transcript, recording link |
| `cancel_call` † ‡ | Cancel a queued call, or hang up a live one |
| `list_models`, `list_voices`, `list_phone_numbers` | What an agent can be set up with |

## Webhooks

| Tool | What it does |
| - | - |
| `list_webhooks` | Where events go, and whether delivery is healthy |
| `create_webhook` † | Send an agent's events to your endpoint. The signing secret is shown once |
| `update_webhook` † | Change the address or events, or switch it back on |
| `delete_webhook` † | Stop sending |
| `test_webhook` | Send a sample event and say whether it arrived |
| `list_webhook_deliveries` | The last 50 deliveries — what your endpoint answered, and why one failed |

## Campaigns

| Tool | What it does |
| - | - |
| `list_campaigns` | Broadcasts and calling campaigns with their results — sent, delivered, read, replied, failed |
| `get_campaign` | One campaign's results |
| `pause_campaign` | Stop a sending campaign from sending more |
| `resume_campaign` † ‡ | Start a paused campaign sending again |
| `cancel_campaign` † | Stop a campaign for good |

Campaigns are created and started in the console.

## Usage and analytics

| Tool | What it does |
| - | - |
| `get_usage` | Plan, replies this month against your allowance, balance, replies per day |
| `get_agent_analytics` | One agent's conversations, leads, escalations, questions it could not answer, and top questions |
| `get_call_summary` | Call totals — answered, missed, minutes, cost — and a series |
| `get_whatsapp_summary` | WhatsApp sent, delivered, read, failed and received, and what they cost by category, for recent days or a date range |

The same numbers the console shows. All four work with a **Read-only** key. See
[Usage and analytics](/api-reference/usage-and-analytics).

## Guides

`read_guide` gives your assistant two built-in how-tos: `own-database` and
`dashboards`. Ask it to read the relevant one before building an integration.

## Prompts

Ready-made commands your client lists — in Claude Code, type `/` to see them.
Each is a worked plan with the points where you approve written in.

| Prompt | What it does |
| - | - |
| `build_agent` | Create an agent for your business, teach it from your website, and test it |
| `connect_my_database` | Let an agent look things up in your own database through your API |
| `weekly_report` | Usage, calls, WhatsApp and each agent's results for the last 7 days, with what to fix |
| `fix_unanswered_questions` | Find what customers asked that the agent could not answer, and draft knowledge for it |
| `triage_inbox` | Summarise conversations waiting for a person and propose what to do with each |

A **Read-only** key is offered only `weekly_report`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.