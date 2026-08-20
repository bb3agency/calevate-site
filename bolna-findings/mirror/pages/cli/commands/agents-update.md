> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update an agent with the Bolna CLI

> Use the bolna agents update command to change an agent's name, prompt, welcome message, or webhook, with a before/after diff and confirmation.

Update one or more fields on an existing agent. Shows a before/after diff and requires confirmation before applying. Maps to the `update_agent` MCP tool.

## Syntax

```bash theme={"system"}
bolna agents update <agent-id> [flags]
```

Pass at least one flag to update directly, or run with none on a real terminal for an interactive wizard.

## Flags

| Flag               | Description                                               | Default  |
| ------------------ | --------------------------------------------------------- | -------- |
| `-h, --help`       | Show help for the command                                 | –        |
| `--name string`    | New agent name                                            | –        |
| `--welcome string` | New welcome message                                       | –        |
| `--prompt string`  | New system prompt. Pass `@file.md` to read it from a file | –        |
| `--webhook string` | New webhook URL for call status/execution updates         | –        |
| `--yes`            | Skip the confirmation prompt                              | Disabled |

## Example

```bash theme={"system"}
# Update the welcome message
bolna agents update 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 \
  --welcome "Thanks for calling Acme Support — how can I help today?"
```

```
Agent: Front Desk Concierge (3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02)

  Welcome message
  - Hi, thanks for calling Acme — how can I help?
  + Thanks for calling Acme Support — how can I help today?

Apply this change? (y/n) y
✓ Updated agent 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02
```

```bash theme={"system"}
# Update the system prompt from a file
bolna agents update 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 --prompt @new-prompt.md

# Skip confirmation, for CI
bolna agents update 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 \
  --welcome "Thanks for calling Acme — one moment." --yes
```
