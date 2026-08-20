> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List calls with the Bolna CLI

> Use the bolna calls list command to view call history for one agent, with options to filter by date range.

List call history for one agent with pagination. Returns status, duration, recipient, and created date. Defaults to the last 7 days. Maps to the `list_agent_executions` MCP tool.

## Syntax

```bash theme={"system"}
bolna calls list <agent-id> [flags]
```

## Flags

| Flag                  | Description                              | Default    |
| --------------------- | ---------------------------------------- | ---------- |
| `-h, --help`          | Show help for the command                | –          |
| `--from string`       | Start of the date range, ISO 8601        | 7 days ago |
| `--to string`         | End of the date range, ISO 8601          | today      |
| `--page int`          | Page number to fetch                     | `1`        |
| `--page-size int`     | Results per page                         | `20`       |
| `-q, --quiet`         | Print only the bare execution ID per row | Disabled   |
| `-o, --output string` | Output format: `table`, `json`, or `csv` | `table`    |

## Example

```bash theme={"system"}
# Last 7 days, default view
bolna calls list 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02

# A specific date range
bolna calls list 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 \
  --from 2026-07-01 --to 2026-07-19

# Export to CSV
bolna calls list 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 -o csv > july-calls.csv

# View the transcript of every call in the window
bolna calls list 3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02 -q \
  | xargs -I{} bolna calls view {}
```
