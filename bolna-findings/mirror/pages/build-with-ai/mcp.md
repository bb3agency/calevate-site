> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# MCP Server

> Connect Claude, Cursor, Windsurf, or any MCP client to your Bolna account with the Bolna MCP server.

The Bolna MCP server connects your AI assistant directly to your Bolna account over the [Model Context Protocol](https://modelcontextprotocol.io). Once connected, you can list and inspect agents, pull call transcripts, run batch campaigns, manage dispositions, knowledgebases, phone numbers, SIP trunks, and sub-accounts, check your wallet balance, create or update agents, and place real outbound calls — all from a chat window, no dashboard tab required.

It's hosted at **[mcp.bolna.ai](https://mcp.bolna.ai)** — there's nothing to install or run locally. Point your client at the URL with your API key and you're connected.

<Card title="Quickstart" icon="plug" href="/docs/build-with-ai/mcp-quickstart">
  Connect Claude, Cursor, Windsurf, Codex, Zed, or any other MCP client in under a minute
</Card>

## What you can do

<AccordionGroup>
  <Accordion title="Check on your account" icon="magnifying-glass">
    "List my agents", "what's my wallet balance?", "show me the numbers on my account" — quick lookups without opening the dashboard.
  </Accordion>

  <Accordion title="Debug a call" icon="bug">
    "Get the last 5 executions for agent X and show me the transcript for any that failed" — the assistant chains the lookups for you.
  </Accordion>

  <Accordion title="Build and change agents" icon="robot">
    "Create a Hindi lead-qualification agent using Sarvam and GPT-4o mini", "update agent X's welcome message" — describe the change, the assistant makes the API call.
  </Accordion>

  <Accordion title="Run batches and set up dispositions" icon="layer-group">
    "Create a batch from this CSV and schedule it for 9am", "add a disposition that captures appointment\_time from the call" — campaign and post-call setup without leaving the chat.
  </Accordion>

  <Accordion title="Manage phone numbers, SIP trunks, and sub-accounts" icon="phone">
    "Buy me a US number and route it to my support agent", "add this number to my Twilio trunk", "what did the Acme sub-account spend this month?" — the enterprise and telephony surface, not just agents.
  </Accordion>

  <Accordion title="Add a knowledgebase" icon="book-open">
    "Create a knowledgebase from our pricing page and check when it's done processing" — give an agent RAG over a URL without leaving the chat.
  </Accordion>

  <Accordion title="Review flagged calls" icon="triangle-exclamation">
    "List any pending violations on my account" — see calls flagged for content policy, regulatory, or fraud review.
  </Accordion>

  <Accordion title="Look up the docs" icon="book">
    "How do I set up a webhook?", "show me the MCP tool list page" — the assistant searches Bolna's documentation and reads back the actual page content, instead of guessing from training data.
  </Accordion>
</AccordionGroup>

## How it works

Your client sends your Bolna API key as a Bearer token to `https://mcp.bolna.ai/api/mcp`. For the 55 account tools, the server checks the key, calls the matching [Bolna REST API](/docs/api-reference/introduction) endpoint, and hands back trimmed JSON your assistant can reason about. `search_docs` and `get_doc` skip the account API entirely — they read Bolna's public documentation (`llms.txt` and its doc pages) instead.

### Switching accounts mid-conversation

Every tool also accepts an optional `api_key` argument that overrides the connected account's credential for just that one call. This is built for [sub-accounts](/docs/api-reference/sub-accounts/overview): ask the assistant to `list_sub_accounts`, grab the key (`sa-...`) for the one you want, then pass it as `api_key` on any later tool call to act as that sub-account — no reconnecting required. A sub-account key also works as the primary connection credential from the start, exactly like a main account's `bn-...` key.

```
Your client (Claude, Cursor, Windsurf...)
        │  Bearer <BOLNA_API_KEY>
        ▼
https://mcp.bolna.ai/api/mcp
        │
        ▼
https://api.bolna.ai  (agents · calls · batches · dispositions · knowledgebases · phone numbers · SIP trunks · sub-accounts · voice · violations · account)
```

<Frame caption="How the Bolna MCP server connects your AI assistant to your account">
  <img src="https://mintcdn.com/bolna-54a2d4fe/TzYhw_uvJhz-N-Qn/images/changelog/mcp-diagram.svg?fit=max&auto=format&n=TzYhw_uvJhz-N-Qn&q=85&s=a957a5398c33cc73d4b4207c906fc589" alt="Diagram showing an MCP client connecting via Bearer token to mcp.bolna.ai, which calls api.bolna.ai for agents, calls, batches, dispositions, knowledgebases, phone numbers, SIP trunks, sub-accounts, voice, violations, and account" width="880" height="560" data-path="images/changelog/mcp-diagram.svg" />
</Frame>

No key is stored server-side — it travels with each request. The server is open source; see the [GitHub repo](https://github.com/bolna-ai/mcp) for the implementation.

## Confirm before it acts

12 tools are flagged as destructive in their tool definitions — irreversible deletes, or a real-world effect like spending balance or breaking something still in use. Most clients ask you to confirm before running them: `update_agent`, `delete_agent`, `start_outbound_call`, `schedule_batch`, `delete_batch`, `delete_disposition`, `buy_phone_number`, `delete_phone_number`, `delete_sip_trunk`, `delete_sub_account`, `remove_provider`, and `delete_knowledgebase` — see the [Tool List](/docs/build-with-ai/mcp-tool-list) for what makes each one destructive.

## Reference

<CardGroup cols={2}>
  <Card title="Tool List" icon="table-list" href="/docs/build-with-ai/mcp-tool-list">
    Every tool the server exposes, grouped by agents, calls, batches, dispositions, knowledgebases, phone numbers, SIP trunks, sub-accounts, voice, violations, and account
  </Card>

  <Card title="Prompt Cheatsheet" icon="clipboard-list" href="/docs/build-with-ai/mcp-prompts">
    Copy-paste prompts for common tasks — works in any client, chat-only included
  </Card>
</CardGroup>

## For coding agents

<CardGroup cols={2}>
  <Card title="Example: Monitoring Dashboard" icon="gauge" href="/docs/build-with-ai/mcp-example-app">
    Requires Claude Code, Cursor, Windsurf, or another agent that can write and run files — use the MCP server to explore your data, then have it build a small dashboard around it
  </Card>

  <Card title="Bolna Skills" icon="wand-magic-sparkles" href="/docs/build-with-ai/skills">
    A code-native alternative — teaches the same operations to Claude Code, Cursor, and Codex directly, no MCP connection needed
  </Card>
</CardGroup>
