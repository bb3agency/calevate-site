> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Keybindings

> Every keybinding in the bolna-cli dashboard, plus the fuzzy-searchable command palette.

## Global keybindings

These work from anywhere in the dashboard:

| Key            | Action                                |
| -------------- | ------------------------------------- |
| `:`            | Open the command palette              |
| `1`            | Jump to the Agents screen             |
| `2`            | Jump to the Numbers screen            |
| `3`            | Jump to the Account screen            |
| `enter`        | Drill into the selected row           |
| `esc`          | Go back one screen                    |
| `r`            | Refresh the current screen            |
| `t`            | Cycle color theme (persisted to disk) |
| `q` / `ctrl+c` | Quit                                  |

## From an agent's detail view

Once you've drilled into a specific agent, three more keys become available:

| Key | Action                                                                               |
| --- | ------------------------------------------------------------------------------------ |
| `c` | View this agent's calls                                                              |
| `b` | View this agent's batches                                                            |
| `s` | Start a call with this agent — see [Starting a Call](/docs/cli/dashboard/starting-a-call) |

## Command palette

Press `:` from anywhere to open a fuzzy-searchable jump list covering **every agent and every section** at once — not just the current screen. Type a few letters of an agent's name or a section like "batches", hit `enter`, and you land directly there. No need to back out to the top level and navigate down through menus first.

```
┌─ Jump to… ─────────────────────────────────────────┐
│ > front                                             │
│                                                      │
│   Front Desk Concierge          Agent                │
│   Front Desk Concierge → Calls   Section              │
│   Front Desk Concierge → Batches Section              │
└──────────────────────────────────────────────────────┘
```

This is the fastest way to move around once you have more than a handful of agents — faster than paging through the Agents table looking for a name.

## Themes

Press `t` to cycle through the dashboard's color themes. Your choice is written to disk and reused the next time you open `bolna` — you set it once, not every session.

## See also

<CardGroup cols={2}>
  <Card title="Dashboard Overview" icon="gauge" href="/docs/cli/dashboard/overview">
    Layout, screens, and the header/footer bars
  </Card>

  <Card title="Starting a Call" icon="phone-arrow-up-right" href="/docs/cli/dashboard/starting-a-call">
    The `s` keybinding, in full
  </Card>
</CardGroup>
