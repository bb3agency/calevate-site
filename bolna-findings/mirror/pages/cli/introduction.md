> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# CLI Overview

> Overview of the Bolna CLI for managing agents, calls, phone numbers, and batches from your terminal, and the full-screen dashboard it opens with no arguments.

<Warning>
  `bolna-cli` is in **beta** — commands and flags may still change before a stable 1.0 release.
</Warning>

The **Bolna CLI** (`bolna`) is a single Go binary that lets you manage agents, calls, phone numbers, and batches directly from your terminal — no dashboard tab required. Every command maps 1:1 to a tool in the [Bolna MCP server](/docs/build-with-ai/mcp)'s tool list, so anything an AI assistant can do to your account over MCP, you can run yourself with a direct command.

Run it with no arguments on a real terminal and instead of a help message, it opens a full-screen dashboard — a live, navigable view of your account built on the [Charm](https://charm.sh) TUI stack. Run any command in a script or CI pipe and it behaves like a normal CLI: plain, non-interactive, colorless output.

***

## Benefits of using the Bolna CLI

Developers reach for a CLI because it's **fast, scriptable, and doesn't need a browser**. Instead of clicking through the dashboard, you run one command and move on.

By using the CLI, you can:

* **Script call operations** – Start calls, poll execution status, and pull transcripts from a shell script or CI job.
* **Debug without leaving the terminal** – Pull an agent's config or a call's full transcript with one command instead of navigating the dashboard.
* **Pipe into other tools** – Every list command supports `--json` or `--csv` output, so results feed straight into `jq`, `xargs`, or a spreadsheet.
* **Monitor visually when you want to** – Run `bolna` with no arguments for a full-screen dashboard with a live wallet balance and a guided call-start flow.

***

## What you can do with the Bolna CLI

* **Manage agents** – List, view, create, update, and delete agents.
* **Place and track calls** – Start an outbound call, list call history, and pull a full transcript.
* **Inspect account resources** – List phone numbers and batch campaigns linked to an agent.
* **Check account health** – Confirm authentication, keychain access, and API reachability with `bolna doctor`.
* **Look up the docs without a browser** – Search and read Bolna's documentation with [`docs search`](/docs/cli/commands/docs-search) and [`docs fetch`](/docs/cli/commands/docs-fetch) — no login required.

***

## Available commands

### Agents

Manage [agents](/docs/agent-setup/overview): list, view, create, update, and delete. Also see the [Agent API](/docs/api-reference/agent/v2/overview).

| Command                                        | Description                                                      |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| [`agents list`](/docs/cli/commands/agents-list)     | List agents in the account                                       |
| [`agents view`](/docs/cli/commands/agents-view)     | Get an agent's full config, including prompt and welcome message |
| [`agents create`](/docs/cli/commands/agents-create) | Create a new agent, interactively or from a JSON file            |
| [`agents update`](/docs/cli/commands/agents-update) | Update an agent's name, prompt, welcome message, or webhook      |
| [`agents delete`](/docs/cli/commands/agents-delete) | Permanently delete an agent                                      |

### Calls

Manage [calls](/docs/guides/outbound/making-outgoing-calls): start, list history, and view transcripts. Also see the [Calls API](/docs/api-reference/calls/overview).

| Command                                  | Description                                 |
| ---------------------------------------- | ------------------------------------------- |
| [`call start`](/docs/cli/commands/call-start) | Place a real outbound call                  |
| [`calls list`](/docs/cli/commands/calls-list) | List call history for an agent              |
| [`calls view`](/docs/cli/commands/calls-view) | Get full detail and transcript for one call |

### Resources

| Command                                      | Description                       |
| -------------------------------------------- | --------------------------------- |
| [`numbers list`](/docs/cli/commands/numbers-list) | List phone numbers on the account |
| [`batches list`](/docs/cli/commands/batches-list) | List batch campaigns for an agent |

### Account

| Command                          | Description                                         |
| -------------------------------- | --------------------------------------------------- |
| [`login`](/docs/cli/commands/login)   | Authenticate and store an API key                   |
| [`logout`](/docs/cli/commands/logout) | Remove the stored API key                           |
| [`whoami`](/docs/cli/commands/whoami) | Show the authenticated account, balance, and limits |

### Utility

Unlike every other group above, these commands don't manage account data and don't need `bolna login` or an API key — they help you learn the CLI and Bolna itself directly from the terminal.

| Command                                    | Description                                                  |
| ------------------------------------------ | ------------------------------------------------------------ |
| [`doctor`](/docs/cli/commands/doctor)           | Check config, keychain, and API health                       |
| [`docs search`](/docs/cli/commands/docs-search) | Search Bolna's documentation index for a query               |
| [`docs fetch`](/docs/cli/commands/docs-fetch)   | Fetch a documentation page as Markdown in your terminal      |
| `version`                                  | Print the installed CLI version, commit hash, and build date |

## Next

<CardGroup cols={2}>
  <Card title="Quickstart" icon="bolt" href="/docs/cli/quickstart">
    Install, log in, and run your first command in under a minute
  </Card>

  <Card title="Changelog" icon="clock-rotate-left" href="/docs/cli/changelog">
    Browse CLI releases and updates
  </Card>
</CardGroup>
