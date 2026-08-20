> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Start a call with the Bolna CLI

> Use the bolna call start command to place a real outbound call, with a wallet balance check and confirmation before dialing.

Place a real outbound call using the given agent. Spends real account balance. Always shows your wallet balance and requires confirmation before dialing. Maps to the `start_outbound_call` MCP tool.

## Syntax

```bash theme={"system"}
bolna call start <agent-id> --to <number> [flags]
```

## Flags

| Flag            | Description                                                        | Default                   |
| --------------- | ------------------------------------------------------------------ | ------------------------- |
| `-h, --help`    | Show help for the command                                          | –                         |
| `--to string`   | Recipient's number in E.164 format, e.g. `+14155551234` (required) | –                         |
| `--from string` | Caller-ID override                                                 | agent's configured number |
| `--yes`         | Skip the confirmation prompt                                       | Disabled                  |

## Example

```bash theme={"system"}
bolna call start 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 --to +14155551234
```

```
Agent        Front Desk Concierge
Recipient    +14155551234
Balance      $482.19

Place this call now? (y/n) y
✓ Call started — execution b7140255-af33-4608-8e97-04dd944b8e48

Track it with:
  bolna calls view b7140255-af33-4608-8e97-04dd944b8e48
```

```bash theme={"system"}
# Override the caller ID
bolna call start 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 \
  --to +14155551234 --from +14155559999

# Skip confirmation, for scripting
bolna call start 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 \
  --to +14155551234 --yes
```

<Tip>
  Prefer a visual flow? Press `s` from an agent's detail view in the [dashboard](/docs/cli/dashboard/starting-a-call) for the same confirmation, guided through screens.
</Tip>
