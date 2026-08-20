> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# bolna docs fetch

> Use the bolna docs fetch command to fetch a Bolna documentation page as rendered Markdown directly in your terminal, given a path or URL.

Fetch one documentation page and render it as formatted Markdown directly in the terminal, using the same renderer the CLI already uses for call transcripts and agent system prompts.

This is a **utility** command, not an account-management one: it reads a public Bolna doc page, not your account data, so it works without `bolna login` or an API key. Maps to the `get_doc` MCP tool.

## Syntax

```bash theme={"system"}
bolna docs fetch <page> [flags]
```

`<page>` accepts three equivalent forms, all normalized to the same request:

* A bare path — `bolna docs fetch agent-setup/analytics-tab`
* A path with `.md` — `bolna docs fetch agent-setup/analytics-tab.md`
* A full URL, exactly as printed by [`docs search`](/docs/cli/commands/docs-search) — `bolna docs fetch https://www.bolna.ai/docs/agent-setup/analytics-tab.md`

Only `www.bolna.ai/docs/*.md` URLs are ever fetched — a non-Bolna URL is rejected rather than requested, so this command can't be used as an open URL proxy.

## Flags

| Flag                | Description                                                                                               | Default |
| ------------------- | --------------------------------------------------------------------------------------------------------- | ------- |
| `-h, --help`        | Show help for the command                                                                                 | –       |
| `-o, --output json` | Return `{"path": "...", "content": "..."}` with the raw Markdown, instead of the rendered terminal output | –       |

## Example

```bash theme={"system"}
bolna docs fetch agent-setup/analytics-tab
```

```
# Set Up Webhooks and Post-Call Extractions

Configure webhooks, call summarization, and data extraction for Bolna Voice AI...

## What is the Extractions Tab?

The Extractions Tab is where you configure webhooks for real-time data and
post-call processing tasks...
```

```bash theme={"system"}
# Raw Markdown, for piping or saving to a file
bolna docs fetch agent-setup/analytics-tab -o json | jq -r '.content' > analytics-tab.md
```

## Errors

An invalid or nonexistent page returns a clear error instead of a partial render:

```
fetching doc page "this/does/not/exist": HTTP 404 from https://www.bolna.ai/docs/this/does/not/exist.md
```

## Workflow

```bash theme={"system"}
bolna docs search "outbound call"     # find the right page
bolna docs search "outbound call" -q  # just get its path
bolna docs fetch <path-from-above>    # read the full page, right in the terminal
```

<Card title="bolna docs search" icon="magnifying-glass" href="/docs/cli/commands/docs-search">
  Find the page path to pass here
</Card>
