> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List batches with the Bolna CLI

> Use the bolna batches list command to view batch calling campaigns for one agent, with status and schedule.

List batch calling campaigns for one agent. Returns batch ID, status, scheduled time, and created date. Maps to the `list_batches` MCP tool.

## Syntax

```bash theme={"system"}
bolna batches list <agent-id> [flags]
```

## Flags

| Flag                  | Description                              | Default  |
| --------------------- | ---------------------------------------- | -------- |
| `-h, --help`          | Show help for the command                | –        |
| `-q, --quiet`         | Print only the bare batch ID per row     | Disabled |
| `-o, --output string` | Output format: `table`, `json`, or `csv` | `table`  |

## Example

```bash theme={"system"}
bolna batches list 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02
```

```
BATCH ID                               STATUS      SCHEDULED            CREATED
a91c2e4f-6b3d-4a8e-9f1c-2d5b7e8a3c60   completed   2026-07-15 10:00     2026-07-14 16:22
c4d8e1f2-3a9b-4d5c-8e7f-1a2b3c4d5e60   scheduled   2026-07-22 09:00     2026-07-18 12:10
```

```bash theme={"system"}
# Any batch still running or scheduled
bolna batches list 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 --output json \
  | jq -r '.[] | select(.status == "running" or .status == "scheduled")'
```

<Note>
  Creating, scheduling, and stopping a batch — including the CSV of recipients and per-recipient variables — is currently done through the [Batches API](/docs/api-reference/batches/overview). `bolna batches list` is read-only.
</Note>
