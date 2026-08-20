> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Quickstart

> Connect the Bolna MCP server to Claude, Cursor, Windsurf, or any other MCP client.

Every client needs the same two things — there's nothing to install, the server is hosted at `mcp.bolna.ai`:

```
URL:     https://mcp.bolna.ai/api/mcp
Header:  Authorization: Bearer <your BOLNA_API_KEY>
```

<Steps>
  <Step title="Get your API key">
    Grab it from the [Bolna Dashboard → Developers](https://platform.bolna.ai). Keep it secret — anyone with the key can read your account data and place calls that spend your balance.

    A [sub-account](/docs/api-reference/sub-accounts/overview) key (`sa-...`) works here too, exactly like a main account's `bn-...` key — connect with it directly, or switch per-call later with the `api_key` argument described in the [Tool List](/docs/build-with-ai/mcp-tool-list#calling-tools-with-a-different-account).
  </Step>

  <Step title="Add the MCP server">
    <Tabs>
      <Tab title="Claude Code">
        ```bash theme={"system"}
        claude mcp add --transport http bolna https://mcp.bolna.ai/api/mcp \
          --header "Authorization: Bearer <your BOLNA_API_KEY>" \
          --scope user
        ```
      </Tab>

      <Tab title="Claude Desktop">
        Desktop only launches local (stdio) servers, so reaching this remote HTTP server needs the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge. Add to `claude_desktop_config.json`:

        ```json theme={"system"}
        {
          "mcpServers": {
            "bolna": {
              "command": "npx",
              "args": [
                "-y", "mcp-remote",
                "https://mcp.bolna.ai/api/mcp",
                "--header", "Authorization: Bearer <your BOLNA_API_KEY>"
              ]
            }
          }
        }
        ```

        Restart Claude Desktop after saving.
      </Tab>

      <Tab title="Cursor">
        Add to `.cursor/mcp.json`:

        ```json theme={"system"}
        {
          "mcpServers": {
            "bolna": {
              "url": "https://mcp.bolna.ai/api/mcp",
              "headers": { "Authorization": "Bearer <your BOLNA_API_KEY>" }
            }
          }
        }
        ```
      </Tab>

      <Tab title="Windsurf">
        Add to `~/.codeium/windsurf/mcp_config.json`:

        ```json theme={"system"}
        {
          "mcpServers": {
            "bolna": {
              "serverUrl": "https://mcp.bolna.ai/api/mcp",
              "headers": { "Authorization": "Bearer <your BOLNA_API_KEY>" }
            }
          }
        }
        ```
      </Tab>

      <Tab title="Codex CLI">
        Reads the key from an environment variable:

        ```bash theme={"system"}
        export BOLNA_API_KEY="<your BOLNA_API_KEY>"

        codex mcp add bolna \
          --url https://mcp.bolna.ai/api/mcp \
          --bearer-token-env-var BOLNA_API_KEY
        ```
      </Tab>

      <Tab title="Zed">
        Add to `settings.json`. Zed doesn't support environment-variable interpolation in headers yet, so the key goes in directly:

        ```json theme={"system"}
        {
          "context_servers": {
            "bolna": {
              "url": "https://mcp.bolna.ai/api/mcp",
              "headers": { "Authorization": "Bearer <your BOLNA_API_KEY>" }
            }
          }
        }
        ```
      </Tab>

      <Tab title="Any other client">
        Point it at the URL and header above. If it only launches local (stdio) servers, bridge it with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

        ```bash theme={"system"}
        npx -y mcp-remote https://mcp.bolna.ai/api/mcp \
          --header "Authorization: Bearer <your BOLNA_API_KEY>"
        ```
      </Tab>
    </Tabs>
  </Step>

  <Step title="Verify the connection">
    Start a new conversation and ask:

    ```
    List my Bolna agents
    ```

    A real list back means you're connected.
  </Step>
</Steps>

<Note>
  claude.ai (web/mobile) isn't supported yet — its custom-connector UI has no field for a personal Bearer token. The options above are the only self-serve paths until OAuth support ships.
</Note>

## Troubleshooting

<AccordionGroup>
  <Accordion title="Tools return an auth error" icon="triangle-exclamation">
    Check the header reads exactly `Authorization: Bearer <key>` — a missing space after `Bearer`, or quotes baked in from copy-paste, will break it. An invalid key surfaces as a `403` from the underlying Bolna API.
  </Accordion>

  <Accordion title="Client can't reach a remote HTTP server" icon="plug-circle-xmark">
    Some clients (Claude Desktop is the common one) only support locally-run stdio servers — use the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge shown above.
  </Accordion>

  <Accordion title="Not sure the server is even reachable" icon="stethoscope">
    Test it directly with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

    ```bash theme={"system"}
    npx @modelcontextprotocol/inspector
    ```

    Connect with transport **Streamable HTTP**, URL `https://mcp.bolna.ai/api/mcp`, header `Authorization: Bearer <your BOLNA_API_KEY>`, and check all 57 tools appear under "List Tools".
  </Accordion>
</AccordionGroup>

<CardGroup cols={2}>
  <Card title="Tool List" icon="table-list" href="/docs/build-with-ai/mcp-tool-list">
    Every tool the server exposes
  </Card>

  <Card title="Prompt Cheatsheet" icon="clipboard-list" href="/docs/build-with-ai/mcp-prompts">
    Copy-paste prompts for common tasks
  </Card>
</CardGroup>
