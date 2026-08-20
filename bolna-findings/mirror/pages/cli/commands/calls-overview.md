> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna calls CLI commands and flags

> Reference for the bolna call/calls CLI commands and flags used to start calls, list history, and view transcripts from your terminal.

Manage [calls](/docs/guides/outbound/making-outgoing-calls). Subcommands let you start an outbound call, list call history for an agent, and view a single call's full detail and transcript. Each command maps to a tool in the [Bolna MCP server](/docs/build-with-ai/mcp)'s tool list.

## Syntax

```bash theme={"system"}
bolna call start <agent-id> [flags]
bolna calls [command]
```

## Commands

| Command                                  | Description                                 |
| ---------------------------------------- | ------------------------------------------- |
| [`call start`](/docs/cli/commands/call-start) | Place a real outbound call                  |
| [`calls list`](/docs/cli/commands/calls-list) | List call history for an agent              |
| [`calls view`](/docs/cli/commands/calls-view) | Get full detail and transcript for one call |

***

## Inherited Global Flags

This command also supports [Global Flags](/docs/cli/global-flags), such as:

* `-o, --output` – Output format: `table`, `json`, or `csv`
* `--profile` – Credential profile to use
* `-v, --verbose` – Verbose logging
* `-n, --no-color` – Disable color output
