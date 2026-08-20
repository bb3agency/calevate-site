> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create an agent with the Bolna CLI

> Use the bolna agents create command to create a new agent interactively or from a JSON config file.

Create a new agent. On a real terminal with no `--file` flag, this walks you through an interactive wizard; pass `--file` to create from a raw JSON config instead. Maps to the `create_agent` MCP tool.

## Syntax

```bash theme={"system"}
bolna agents create [flags]
```

## Flags

| Flag                  | Description                                                                                                                                    | Default |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h, --help`          | Show help for the command                                                                                                                      | –       |
| `--file string`       | Path to a JSON file with a full `agent_config` + `agent_prompts` payload, matching the [Create Agent](/docs/api-reference/agent/v2/create) API body | –       |
| `-o, --output string` | Output format: `table` or `json`                                                                                                               | `table` |

<Note>
  `--file` is required in a non-interactive context (a script or CI pipe) — there's no wizard to fall back to without a terminal.
</Note>

## Example

```bash theme={"system"}
# Interactive wizard
bolna agents create

# Create from a JSON config file
bolna agents create --file config.json
```

```json config.json theme={"system"}
{
  "agent_config": {
    "agent_name": "Front Desk Concierge",
    "agent_welcome_message": "Hi, thanks for calling Acme — how can I help?",
    "tasks": [
      {
        "tools_config": {
          "llm_agent": { "provider": "openai", "model": "gpt-4o-mini" },
          "synthesizer": { "provider": "sarvam", "voice": "Maya" }
        }
      }
    ]
  },
  "agent_prompts": {
    "task_1": { "system_prompt": "## Role\nYou are a front-desk concierge for Acme Corp..." }
  }
}
```
