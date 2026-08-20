> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete an agent with the Bolna CLI

> Use the bolna agents delete command to permanently delete an agent, requiring its exact name to confirm.

Permanently delete an agent and its history. Maps to the `delete_agent` MCP tool. This cannot be undone.

## Syntax

```bash theme={"system"}
bolna agents delete <agent-id> [flags]
```

## Flags

| Flag         | Description                  | Default  |
| ------------ | ---------------------------- | -------- |
| `-h, --help` | Show help for the command    | –        |
| `--yes`      | Skip the confirmation prompt | Disabled |

## Example

```bash theme={"system"}
bolna agents delete 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02
```

```
You are about to permanently delete:

  Front Desk Concierge (3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02)

This cannot be undone. Type the agent name to confirm: Front Desk Concierge
✓ Deleted agent 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02
```

```bash theme={"system"}
# Skip the name confirmation, for scripting
bolna agents delete 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 --yes
```

<Warning>
  `--yes` skips the name-confirmation entirely. Only use it in scripts you trust with the exact agent ID — there's no dry-run flag.
</Warning>
