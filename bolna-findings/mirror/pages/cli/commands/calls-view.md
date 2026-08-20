> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# View a call with the Bolna CLI

> Use the bolna calls view command to fetch full call detail, including status, cost, and the complete transcript.

Retrieve full detail for one call by execution ID. Returns status (color-coded by outcome), duration, cost, and the complete transcript rendered as Markdown. Maps to the `get_execution` MCP tool.

## Syntax

```bash theme={"system"}
bolna calls view <execution-id> [flags]
```

## Flags

| Flag                  | Description                      | Default |
| --------------------- | -------------------------------- | ------- |
| `-h, --help`          | Show help for the command        | –       |
| `-o, --output string` | Output format: `table` or `json` | `table` |

## Example

```bash theme={"system"}
bolna calls view b7140255-af33-4608-8e97-04dd944b8e48
```

```
Status      completed
Duration    2m 14s
Cost        $0.38
Recipient   +14155551234

Transcript
  Agent:  Hi, thanks for calling Acme — how can I help?
  User:   I wanted to check on my order status.
  ...
```

```bash theme={"system"}
# Raw execution data, e.g. for extracted_data or webhook reconciliation
bolna calls view b7140255-af33-4608-8e97-04dd944b8e48 --output json
```

<Tip>
  [`bolna call start`](/docs/cli/commands/call-start) prints the exact `bolna calls view` command to run, execution ID already filled in.
</Tip>
