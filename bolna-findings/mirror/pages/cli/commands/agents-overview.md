> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna agents CLI commands and flags

> Reference for the bolna agents CLI commands and flags used to list, view, create, update, and delete agents from your terminal.

Manage [agents](/docs/agent-setup/overview). Subcommands let you list, view full config, create, update, and delete agents in your account. Each command maps to a tool in the [Bolna MCP server](/docs/build-with-ai/mcp)'s tool list.

## Syntax

```bash theme={"system"}
bolna agents [command]
```

## Commands

| Command                                        | Description                                                 |
| ---------------------------------------------- | ----------------------------------------------------------- |
| [`agents list`](/docs/cli/commands/agents-list)     | List agents in the account                                  |
| [`agents view`](/docs/cli/commands/agents-view)     | Get an agent's full config                                  |
| [`agents create`](/docs/cli/commands/agents-create) | Create a new agent                                          |
| [`agents update`](/docs/cli/commands/agents-update) | Update an agent's name, prompt, welcome message, or webhook |
| [`agents delete`](/docs/cli/commands/agents-delete) | Permanently delete an agent                                 |

***

## Inherited Global Flags

This command also supports [Global Flags](/docs/cli/global-flags), such as:

* `-o, --output` – Output format: `table`, `json`, or `csv`
* `--profile` – Credential profile to use
* `-v, --verbose` – Verbose logging
* `-n, --no-color` – Disable color output
