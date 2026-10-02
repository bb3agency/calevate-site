> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz MCP Server

> Connect Claude, Cursor, VS Code, and other AI clients directly to the Vobiz documentation through the Model Context Protocol (MCP). Step-by-step setup with npx and native configs.

Vobiz Docs provides a hosted **Model Context Protocol (MCP)** server. Point any MCP-aware client - Claude Desktop, Claude Code, Cursor, VS Code, or ChatGPT - at it and the assistant can search and read the current Vobiz documentation instead of relying on its training snapshot.

## Install with one command

```bash theme={null}
npx add-mcp https://vobiz.ai/docs/mcp
```

That's it. `add-mcp` scans your machine for installed MCP clients (Claude Desktop, Claude Code, Cursor, VS Code, Windsurf…), shows a checklist of which ones to wire up, writes the right config block to each, and prompts you to restart anything that needs it. The command is idempotent - re‑run it any time you install a new client.

```text Server endpoint theme={null}
https://vobiz.ai/docs/mcp
```

* **Transport:** Streamable HTTP (no auth, public).
* **What it exposes:** Read-only full-text search and page fetch across the Vobiz documentation site, plus a `submit_feedback` tool that creates a documentation feedback report.
* **What it is not:** This is **not** the Vobiz REST or Partner API. It cannot place calls, purchase numbers, or change your Vobiz account. For programmatic call and account access, use the [API Reference](/docs/account).

## Discover the server automatically

MCP clients and registries can use the public discovery metadata:

* **Server card:** [https://vobiz.ai/.well-known/mcp/server-card.json](https://vobiz.ai/.well-known/mcp/server-card.json)
* **Registry name:** `io.github.vobiz-ai/vobiz-docs`

The server card identifies the Streamable HTTP endpoint, supported tools, publisher, and authentication requirements.

### Server identity

| Field | Value | Why it matters |
| - | - | - |
| Registry name | `io.github.vobiz-ai/vobiz-docs` | Stable, globally unique identifier used by MCP registries and clients. |
| Display title | `Vobiz Docs` | Human-readable name shown in MCP catalogs and connection screens. |
| Description | Search Vobiz documentation for voice, SIP, messaging, and AI agent integrations. | Defines the server's retrieval scope for people and agents. |
| Version | `1.0.0` | Version of the published server metadata. |
| Setup guide | `https://vobiz.ai/docs/resources/mcp` | Installation, client configuration, verification, and troubleshooting. |
| Icon | `https://vobiz.ai/favicon.svg` | Public SVG brand asset for supporting catalogs and clients. |
| Transport | `streamable-http` | Remote MCP transport supported by the hosted endpoint. |
| Remote endpoint | `https://vobiz.ai/docs/mcp` | Canonical URL that MCP clients connect to. |
| Authentication | None | Public documentation search does not require Vobiz API credentials. |

<Accordion title="View the MCP Registry manifest">
  ```json server.json theme={null}
  {
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
    "name": "io.github.vobiz-ai/vobiz-docs",
    "title": "Vobiz Docs",
    "description": "Search Vobiz documentation for voice, SIP, messaging, and AI agent integrations.",
    "version": "1.0.0",
    "websiteUrl": "https://vobiz.ai/docs/resources/mcp",
    "icons": [
      {
        "src": "https://vobiz.ai/favicon.svg",
        "mimeType": "image/svg+xml",
        "sizes": ["any"]
      }
    ],
    "remotes": [
      {
        "type": "streamable-http",
        "url": "https://vobiz.ai/docs/mcp"
      }
    ]
  }
  ```
</Accordion>

### Available tools

| Tool | Access | Purpose |
| - | - | - |
| `search_vobiz` | Read-only | Search guides, API references, examples, and integration documentation. |
| `query_docs_filesystem_vobiz` | Read-only | Read full documentation and OpenAPI content after locating the relevant source. |
| `submit_feedback` | Write | Create a documentation feedback report for incorrect, outdated, confusing, or incomplete content. |

The MCP server provides documentation context. It does not expose your Vobiz account, API credentials, calls, phone numbers, trunks, or billing data.

## Prerequisites

* An MCP‑aware client (Claude Desktop, Claude Code, Cursor, VS Code 1.99+, etc.).
* **Node.js 18+** for `npx`. If `node --version` prints `v18` or higher, you're set.
* An internet connection - the server is hosted, nothing runs locally.

## Manual setup per client

If you'd rather wire each client up by hand (or `add-mcp` didn't detect yours), the sections below show the exact config for each.

### Claude Desktop

Claude Desktop currently launches MCP servers over stdio, so you wrap the hosted HTTP endpoint with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote). No global install needed - `npx` fetches it on first run.

<Steps>
  <Step title="Open the config file">
    * **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
    * **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
    * **Linux:** `~/.config/Claude/claude_desktop_config.json`

    If the file doesn't exist yet, create it with `{}` as its content.
  </Step>

  <Step title="Add the Vobiz server">
    Merge this block into your config:

    ```json claude_desktop_config.json theme={null}
    {
      "mcpServers": {
        "vobiz-docs": {
          "command": "npx",
          "args": ["-y", "mcp-remote", "https://vobiz.ai/docs/mcp"]
        }
      }
    }
    ```
  </Step>

  <Step title="Restart Claude Desktop">
    Quit Claude fully (⌘Q on macOS) and reopen it. The new tools surface under the 🔌 / hammer icon in the prompt bar - you should see entries like `search` and `fetch` listed under `vobiz-docs`.
  </Step>

  <Step title="Try it">
    Ask Claude:

    > Using the vobiz-docs MCP server, how do I start an audio stream from XML?

    Claude will call the `search`/`fetch` tools and answer from the live docs.
  </Step>
</Steps>

### Claude Code

Claude Code (the CLI) speaks Streamable HTTP natively - no `mcp-remote` shim required.

<Steps>
  <Step title="Add the server">
    Run from any project directory:

    ```bash theme={null}
    claude mcp add --transport http vobiz-docs https://vobiz.ai/docs/mcp
    ```

    Use `--scope user` to make the server available across every project, or `--scope project` to commit the config alongside the repo:

    ```bash theme={null}
    claude mcp add --transport http --scope user vobiz-docs https://vobiz.ai/docs/mcp
    ```
  </Step>

  <Step title="Verify it loaded">
    ```bash theme={null}
    claude mcp list
    ```

    `vobiz-docs` should appear with a ✓ next to it. Inside a session, type `/mcp` to see live status and the tools the server exposes.
  </Step>

  <Step title="Use it in a session">
    Anywhere in a Claude Code conversation:

    > Look up the `<Stream>` XML attributes in the Vobiz docs and write me a minimal handler.

    Claude Code will call `vobiz-docs__search` / `vobiz-docs__fetch` automatically.
  </Step>
</Steps>

### Cursor

Cursor reads MCP servers from `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per‑project).

<Steps>
  <Step title="Edit the MCP config">
    Open **Cursor → Settings → MCP → Edit Config**, or edit the file directly:

    ```json ~/.cursor/mcp.json theme={null}
    {
      "mcpServers": {
        "vobiz-docs": {
          "command": "npx",
          "args": ["-y", "mcp-remote", "https://vobiz.ai/docs/mcp"]
        }
      }
    }
    ```
  </Step>

  <Step title="Enable & test">
    Back in Settings → MCP, toggle `vobiz-docs` on. The status dot should turn green within a few seconds. Open a new chat and ask a Vobiz‑specific question - Cursor surfaces an "MCP" badge when it pulls from the server.
  </Step>
</Steps>

### VS Code

VS Code 1.99+ has first‑class MCP support behind the **Copilot Chat → Agent** mode.

<Steps>
  <Step title="Create the workspace config">
    Inside your project, create `.vscode/mcp.json`:

    ```json .vscode/mcp.json theme={null}
    {
      "servers": {
        "vobiz-docs": {
          "type": "http",
          "url": "https://vobiz.ai/docs/mcp"
        }
      }
    }
    ```

    Prefer a global setup? Run the **MCP: Add Server** command from the palette (⇧⌘P) and paste the same URL.
  </Step>

  <Step title="Use it in agent mode">
    Open the Copilot Chat panel, switch to **Agent**, and click the 🛠 tools menu - enable `vobiz-docs`. Ask the agent anything about Vobiz and it will fetch from the docs automatically.
  </Step>
</Steps>

### Any other MCP client

The hosted URL works with any client that speaks Streamable HTTP. Two common one‑off invocations:

```bash Run mcp-remote directly theme={null}
npx -y mcp-remote https://vobiz.ai/docs/mcp
```

```bash Probe with the MCP Inspector theme={null}
npx -y @modelcontextprotocol/inspector npx -y mcp-remote https://vobiz.ai/docs/mcp
```

The Inspector launches a small web UI where you can list tools, call `search` with a query, and inspect raw JSON‑RPC traffic - handy when integrating a brand‑new client.

## Verify the connection

A quick sanity check that works in any client:

> Use the Vobiz MCP server to find the page that documents the `playedStream` event, then quote its first paragraph.

If the assistant returns content from [/xml/stream/stream-events](/docs/xml/stream/stream-events), the connection is healthy. If it answers from memory (or gets details wrong), the server isn't actually wired up - re‑check the config file and restart the client.

## Troubleshooting

<Warning>
  Most issues are config‑file syntax or stale processes - not server‑side problems. Use `https://vobiz.ai/docs/mcp` exactly - the shorter `docs.vobiz.ai/mcp` form redirects GETs but rejects the POST requests the MCP transport needs, so it will fail the handshake even though the domain resolves.
</Warning>

* **Claude Desktop shows no tools after editing the config.** Fully quit (⌘Q / right‑click → Quit). A window close alone keeps the process alive and the old config cached.
* **`npx: command not found`.** Install [Node.js 18+](https://nodejs.org). On macOS with Homebrew: `brew install node`.
* **`mcp-remote` errors out on first run.** Clear the npx cache: `rm -rf ~/.npm/_npx` and try again. Corporate proxies sometimes block the npm registry - set `HTTPS_PROXY` accordingly.
* **Claude Code says `Server failed to connect`.** Run `claude mcp list` to see the current entry, remove it with `claude mcp remove vobiz-docs`, then re‑add. The `--transport http` flag is required - without it the CLI assumes stdio.
* **VS Code: tools menu is empty.** You're not in Agent mode. Switch the Copilot Chat dropdown from *Ask* to *Agent*; MCP tools only surface there.

## Related

* [Vobiz developer resources](https://vobiz.ai/developers) - discover the API docs, OpenAPI specification, SDKs, Agent Skills, and developer console.
* [OpenAPI specification](https://vobiz.ai/openapi.json) - generate clients and inspect the full REST API contract.
* [Vobiz Agent Skills](/docs/resources/skills) - install reusable workflows for Claude, Codex, and other coding agents.
* [Vobiz SDKs](https://github.com/vobiz-ai) - official client libraries and example applications.
* [Claude Code docs](https://docs.claude.com/en/docs/claude-code) - official setup and `claude mcp` reference.
* [Model Context Protocol spec](https://modelcontextprotocol.io) - protocol details, transports, and SDKs.
* [Vobiz Partner API](/docs/partner/api) - for programmatic access to accounts, CDRs, and KYC, separate from the docs MCP server.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.