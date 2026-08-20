> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# bolna whoami

> Use the bolna whoami command to show the authenticated account's name, email, wallet balance, and concurrency limits.

Show who you're authenticated as, current wallet balance, and concurrency limits. Maps to the `get_user_info` MCP tool.

## Syntax

```bash theme={"system"}
bolna whoami [flags]
```

## Flags

| Flag                  | Description                              | Default |
| --------------------- | ---------------------------------------- | ------- |
| `-h, --help`          | Show help for the command                | –       |
| `-o, --output string` | Output format: `table`, `json`, or `csv` | `table` |

## Example

```bash theme={"system"}
bolna whoami
```

```
Account       Acme Corp
Email         ops@acme.com
Balance       $482.19
Concurrency   3 / 10 calls
```

```bash theme={"system"}
# Pre-flight balance check before a batch run
balance=$(bolna whoami --json | jq -r '.balance_usd')

# Check a specific profile
bolna whoami --profile client-acme
```
