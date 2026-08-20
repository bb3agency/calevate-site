> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dashboard Overview

> The full-screen bolna-cli dashboard — a read-mostly mission control view of your agents, calls, and account.

Run `bolna` with no arguments on a real terminal, and instead of a help message you get a full-screen dashboard — a live, navigable view of every agent, call, phone number, and batch on your account, built entirely on the [Charm](https://charm.sh) TUI stack.

```bash theme={"system"}
bolna
```

## The splash screen

Before the dashboard appears, a "BOLNA" ASCII wordmark animates into place using spring physics (via [Harmonica](https://github.com/charmbracelet/harmonica)) — it settles, then transitions into the dashboard automatically, or immediately on any keypress if you don't want to wait.

## Layout

The whole dashboard sits inside a bordered "mission control" frame — a rounded border in Bolna's brand blue gradient, matching the wordmark color scheme at [mcp.bolna.ai](https://mcp.bolna.ai).

```
┌─ bolna ─────────────────────────────────────── Agents ─────  $482.19 ─┐
│                                                                        │
│   NAME                    STATUS    ID                                │
│  ▸ Front Desk Concierge   active    3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9…  │
│    Collections Reminder   active    7b2e4f10-8a3c-4d9e-b1f2-5c9a0e…   │
│    Lead Qualifier (v2)    draft     e91c3a5f-2d4b-4a8e-9f0c-1d5b7e…   │
│                                                                        │
├────────────────────────────────────────────────────────────────────  │
│  : palette   1/2/3 jump   enter view   r refresh   q quit             │
└────────────────────────────────────────────────────────────────────  ┘
```

* **Header bar** — a `bolna` badge, a breadcrumb for the current screen, and your account's real-time wallet balance in the top-right corner.
* **Footer bar** — context-sensitive keybinding hints for whatever screen is active, a loading spinner during data fetches, or an error message if something failed.

## Screens

| Screen       | What it shows                                                                     |
| ------------ | --------------------------------------------------------------------------------- |
| Agents       | Table of every agent — name, status, ID                                           |
| Agent Detail | Full card: welcome message and system prompt, rendered as Markdown                |
| Calls        | Call history table, scoped to one agent                                           |
| Call Detail  | Full transcript for one call                                                      |
| Numbers      | Every phone number on the account                                                 |
| Batches      | Batch campaigns for one agent                                                     |
| Account      | Your profile card — balance and concurrency limits                                |
| Call Start   | The one guided write flow — see [Starting a Call](/docs/cli/dashboard/starting-a-call) |

Jump between them with the [command palette](/docs/cli/dashboard/keybindings#command-palette) or the number keys — full keybinding reference on the [Keybindings](/docs/cli/dashboard/keybindings) page.

## Read-mostly, on purpose

Everything in the dashboard is read-only, with one exception: starting a call. Creating, editing, or deleting an agent always routes to the dedicated CLI commands — [`create`](/docs/cli/commands/agents-create), [`update`](/docs/cli/commands/agents-update), [`delete`](/docs/cli/commands/agents-delete) — which have their own wizards and confirmations.

## Non-blocking by design

Every screen's data loads independently. A slow fetch on one screen never freezes another. The footer shows a spinner while loading, or an error if something failed.

## See also

<CardGroup cols={2}>
  <Card title="Keybindings" icon="keyboard" href="/docs/cli/dashboard/keybindings">
    Full reference: navigation, the command palette, and themes
  </Card>

  <Card title="Starting a Call" icon="phone-arrow-up-right" href="/docs/cli/dashboard/starting-a-call">
    The one write action built into the dashboard
  </Card>
</CardGroup>
