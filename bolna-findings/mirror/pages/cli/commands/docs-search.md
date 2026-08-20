> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# bolna docs search

> Use the bolna docs search command to search Bolna's documentation index (llms.txt) by title, description, and path, ranked best-match-first.

Search every page title, description, and path in [Bolna's `llms.txt` index](https://www.bolna.ai/docs/llms.txt) for a query, and print matching pages ranked best-match-first — title matches are weighted higher than description or path matches.

This is a **utility** command, not an account-management one: it reads Bolna's own public documentation index, not your account data, so it works without `bolna login` or an API key. Maps to the `search_docs` MCP tool.

## Syntax

```bash theme={"system"}
bolna docs search <query> [flags]
```

## Flags

| Flag                  | Description                                                  | Default  |
| --------------------- | ------------------------------------------------------------ | -------- |
| `-h, --help`          | Show help for the command                                    | –        |
| `-q, --quiet`         | Print only the matched doc paths, one per line, nothing else | Disabled |
| `-o, --output string` | Output format: `table`, `json`, or `csv`                     | `table`  |

<Tip>
  Use `-q` to pipe a match straight into [`bolna docs fetch`](/docs/cli/commands/docs-fetch):

  ```bash theme={"system"}
  bolna docs search webhook -q | head -1 | xargs bolna docs fetch
  ```
</Tip>

## Example

```bash theme={"system"}
bolna docs search webhook
```

```
TITLE                                                    PATH                                                       DESCRIPTION
Create Bolna Webhook connection with Make.com            tutorials/make-com/create-bolna-webhook-connection         Step-by-step tutorial on integrating Bolna Voice AI agents with Make...
Set Up Webhooks and Post-Call Extractions                agent-setup/analytics-tab                                  Configure webhooks, call summarization, and data extraction for Bolna...
Receive Bolna Voice AI call updates                      guides/post-call/polling-call-status-webhooks               Receive real-time call status updates from Bolna Voice AI using webho...
```

```bash theme={"system"}
# Quoted, multi-word query
bolna docs search "mcp tool list"

# JSON output — full result set with Title, Path, Description per entry
bolna docs search webhook -o json
```

If nothing matches, table mode prints `No matching docs. Try different keywords.` (`json`/`csv` return an empty list instead).

<Card title="bolna docs fetch" icon="file-lines" href="/docs/cli/commands/docs-fetch">
  Fetch the full Markdown content of a page found here
</Card>
