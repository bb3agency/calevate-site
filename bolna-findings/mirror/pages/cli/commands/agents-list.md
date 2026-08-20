> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List agents with the Bolna CLI

> Use the bolna agents list command to list every agent in the account, with options for pagination and bare-ID output.

List every agent on the account with pagination. Returns name, status, and ID. Maps to the `list_agents` MCP tool.

## Syntax

```bash theme={"system"}
bolna agents list [flags]
```

Alias: `bolna agents ls`

## Flags

| Flag                  | Description                              | Default  |
| --------------------- | ---------------------------------------- | -------- |
| `-h, --help`          | Show help for the command                | –        |
| `--page int`          | Page number to fetch                     | `1`      |
| `--page-size int`     | Results per page                         | `20`     |
| `-q, --quiet`         | Print only the bare agent ID per row     | Disabled |
| `-o, --output string` | Output format: `table`, `json`, or `csv` | `table`  |

<Tip>
  Use `-o json` for machine-readable output, `-o csv` for a spreadsheet. Default `-o table` prints a human-friendly table.
</Tip>

## Example

```bash theme={"system"}
# List agents
bolna agents list

# List with custom page size
bolna agents list --page-size 50

# Page through results
bolna agents list --page 2

# Bare IDs, piped into another command
bolna agents list -q | xargs -I{} bolna agents view {}

# Export to CSV
bolna agents list -o csv > agents.csv
```
