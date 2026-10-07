> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Build a dashboard

> Have your assistant build a dashboard or an internal tool on your workspace's data.

Ask your MCP-connected assistant something like:

> "Build a Next.js dashboard for our ThinnestAI workspace: today's conversations
> by channel, calls with their outcome and summary, and new leads. Store
> everything in our Postgres and keep it up to date with webhooks."

It can read the `dashboards` guide (`read_guide`) for the rules below, and use
the MCP tools to set up the webhooks it needs.

## Ask for numbers directly

You do not need to build anything to get a figure. With a **Read-only** key,
ask your assistant:

> "How many replies have we used this month, and what is our balance?"

> "Which questions did the support agent fail to answer in the last 30 days?"

> "How many calls did we miss last week, and what did calls cost?"

It answers from `get_usage`, `get_agent_analytics`, `get_call_summary` and
`get_whatsapp_summary` — the same numbers the console shows. Your dashboard's
backend can call the same endpoints: see
[Usage and analytics](/api-reference/usage-and-analytics).

## The rules it should follow

* **Server side only.** The dashboard's backend calls the
  [API](/api-reference/introduction) with a key from its environment. Never put
  the key in browser code — it can message your customers.
* **Webhooks for live data, the API to backfill.** Subscribe to
  `call.analysed`, `lead.captured`, `conversation.escalated` and
  `conversation.resolved`, and write each into your own tables. Page through the
  lists once to fill history.
* **Page with the cursor.** Lists answer `{ "items": [...], "nextCursor": ... }`,
  newest first; pass `cursor` back to continue, `limit` up to 100.
* **Stay under 240 requests a minute.** A `429` says how long to wait.
  Sync incrementally rather than re-reading everything.
* **Store ids as given** — they are prefixed strings (`conv_…`, `cust_…`).

## A schema to mirror into

```sql theme={null}
create table conversations (id text primary key, channel text, status text, contact text, created_at timestamptz);
create table messages      (id text primary key, conversation text, author text, text text, created_at timestamptz);
create table calls         (id text primary key, agent text, status text, seconds int,
                            summary text, fields jsonb, transcript jsonb, started_at timestamptz);
create table leads         (conversation text, name text, email text, phone text, note text, received_at timestamptz);
```

## Useful reads

| For | Call |
| - | - |
| Conversations by channel | `GET /conversations?channel=whatsapp&since=…` |
| A conversation's messages | `GET /conversations/{id}/messages` |
| Calls and their results | `GET /calls?since=…`, then `GET /calls/{id}` for transcript and fields |
| Contacts and tags | `GET /contacts?tag=…` |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.