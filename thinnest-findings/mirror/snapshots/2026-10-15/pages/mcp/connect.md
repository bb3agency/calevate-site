> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Connect your assistant

> Add the ThinnestAI MCP server to Claude Code, Cursor, VS Code or Claude Desktop with an API key.

You need a **server key** — create one in **Settings → API keys**. The same page
shows these snippets ready to copy, under **Connect an AI assistant**.

## Pick what the assistant may do

The key's access decides which tools your assistant even sees:

| Key | The assistant can |
| - | - |
| **Build** (recommended) | Build agents, connect your API, manage contacts and webhooks, read everything, test-chat the agent — but not message anyone or place calls |
| **Read-only** | Read conversations, calls, contacts and settings — for reports and dashboards |
| **Full access** | Everything above, plus sending, calling and code sends — each still asking for your approval |

Start with **Build**. Create a separate full-access key only when you want the
assistant to send or call, and revoke it when you are done.

<Warning>
  The key can message your customers and place calls. Keep it in your
  assistant's config on your own machine — never in a repository, a shared
  document or a web page. If it leaks, revoke it in **Settings → API keys**;
  that takes effect immediately.
</Warning>

<Tabs>
  <Tab title="Claude Code">
    Run in a terminal:

    ```bash theme={null}
    claude mcp add --transport http thinnestai https://app.thinnest.ai/api/v1/mcp \
      --header "Authorization: Bearer ta_live_YOUR_KEY"
    ```

    Check it with `claude mcp list`, or `/mcp` inside a session.
  </Tab>

  <Tab title="Cursor">
    Add to `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project):

    ```json theme={null}
    {
      "mcpServers": {
        "thinnestai": {
          "url": "https://app.thinnest.ai/api/v1/mcp",
          "headers": { "Authorization": "Bearer ta_live_YOUR_KEY" }
        }
      }
    }
    ```
  </Tab>

  <Tab title="VS Code">
    Add to `.vscode/mcp.json`:

    ```json theme={null}
    {
      "servers": {
        "thinnestai": {
          "type": "http",
          "url": "https://app.thinnest.ai/api/v1/mcp",
          "headers": { "Authorization": "Bearer ta_live_YOUR_KEY" }
        }
      }
    }
    ```
  </Tab>

  <Tab title="Claude Desktop and others">
    Clients that only run local servers connect through `mcp-remote`, which
    needs [Node.js](https://nodejs.org). In Claude Desktop: **Settings →
    Developer → Edit config**:

    ```json theme={null}
    {
      "mcpServers": {
        "thinnestai": {
          "command": "npx",
          "args": ["-y", "mcp-remote", "https://app.thinnest.ai/api/v1/mcp",
                   "--header", "Authorization:${AUTH}"],
          "env": { "AUTH": "Bearer ta_live_YOUR_KEY" }
        }
      }
    }
    ```

    The key is passed through `env` deliberately: some clients split arguments
    on spaces, which breaks `Bearer ta_live_…` written inline.
  </Tab>
</Tabs>

## Check it works

Ask your assistant: **"List my ThinnestAI agents."** It should call
`list_agents` and show them.

## If it does not connect

| You see | Why | Fix |
| - | - | - |
| `401 Unauthorized` | The key is missing, mistyped or revoked | Copy the full key, including `ta_live_`; create a new one if it was revoked |
| `405` | Something opened the address with `GET` | Use the `http` / Streamable HTTP transport — the server is POST-only and keeps no session |
| A tool answers `429` | Over 240 requests a minute for the workspace, or a send/call limit | Wait the number of seconds it gives and retry |
| Tools refuse with "Not run" | Working as designed — the action needs your approval | Approve it, and the assistant runs it again. See [Safety](/mcp/safety) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.