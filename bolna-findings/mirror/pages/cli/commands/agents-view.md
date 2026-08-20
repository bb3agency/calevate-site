> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# View an agent with the Bolna CLI

> Use the bolna agents view command to fetch an agent's full config, including welcome message and system prompt, by ID.

Retrieve full configuration for a single agent by ID. Returns name, status, welcome message, and system prompt, with the prompt rendered as Markdown. Maps to the `get_agent` MCP tool.

## Syntax

```bash theme={"system"}
bolna agents view <agent-id> [flags]
```

## Flags

| Flag                  | Description                                                                                  | Default  |
| --------------------- | -------------------------------------------------------------------------------------------- | -------- |
| `-h, --help`          | Show help for the command                                                                    | –        |
| `--png`               | Also export the card as a PNG, via the [Freeze](https://github.com/charmbracelet/freeze) CLI | Disabled |
| `-o, --output string` | Output format: `table` or `json`                                                             | `table`  |

## Example

```bash theme={"system"}
# View an agent
bolna agents view 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02

# Export the card as a PNG
bolna agents view 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 --png

# Get raw config for scripting
bolna agents view 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 --output json
```

<Tip>
  Not sure of the agent ID? Run [`bolna agents list`](/docs/cli/commands/agents-list) first, or open the [dashboard](/docs/cli/dashboard/overview) and press `:` to fuzzy-search by name.
</Tip>
