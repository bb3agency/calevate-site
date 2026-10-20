> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# MCP server

> Run your workspace from Claude Code, Cursor or VS Code — build agents, connect your systems, read conversations, build dashboards.

ThinnestAI is an **MCP server**. Connect an AI coding assistant to it with one of
your API keys, and you can run the workspace by asking:

> "Create a support agent for our clinic that answers in Hindi and English, and
> connect it to our appointments API."

> "Which customers asked about refunds this week? Draft a reply for each."

> "Build me a dashboard of yesterday's calls — outcome, duration and what each
> caller wanted."

The assistant does the work through the same API your own code would use, so it
can do exactly what your key can do — no more.

```
https://app.thinnest.ai/api/v1/mcp
```

## What you can do with it

<CardGroup cols={2}>
  <Card title="Build and tune agents" icon="robot">
    Create agents, write their instructions, teach them from pages and text —
    then talk to the agent to check the change worked, with nobody contacted.
  </Card>

  <Card title="Connect your own systems" icon="plug">
    Point an agent at your API so it looks things up live — your data stays in
    your database. See [Keep your data in your database](/mcp/own-database).
  </Card>

  <Card title="Work the conversations" icon="comments">
    Read conversations and call transcripts, find patterns, reply on WhatsApp.
  </Card>

  <Card title="Reach out" icon="phone">
    Place calls, queue call lists, send templates — each one only after you
    approve it.
  </Card>

  <Card title="Build dashboards and apps" icon="chart-line">
    Have your assistant write a dashboard or an internal tool on the API.
    See [Build a dashboard](/mcp/dashboards).
  </Card>

  <Card title="Receive what happens" icon="bolt">
    Set up webhooks so leads, escalations and call results land in your systems.
  </Card>
</CardGroup>

## Nothing reaches a customer without your yes

Anything that messages a customer, places a call, spends money, deletes
something, or decides where your customers' data is sent **asks for your
approval first** — and refuses to run if your assistant tries to skip asking.
See [Safety](/mcp/safety).

## What works today

| Client | Works |
| - | - |
| Claude Code | Yes |
| Cursor | Yes |
| VS Code (Copilot agent mode) | Yes |
| Claude Desktop, Windsurf and other local-only clients | Yes, through a small bridge that needs Node.js |
| claude.ai and ChatGPT connectors | **Not yet** — they sign in with OAuth, which is not available yet |

[Connect your assistant →](/mcp/connect)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.