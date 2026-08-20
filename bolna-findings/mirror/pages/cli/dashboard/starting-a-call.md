> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Starting a Call

> The one write action built into the dashboard — a guided call flow with a live, polling status view.

The dashboard is deliberately [read-mostly](/docs/cli/dashboard/overview#read-mostly-by-design) — with exactly one exception. Press `s` from an agent's detail view to place a real call, guided through a few screens instead of a single command.

This is the dashboard's equivalent of [`bolna call start`](/docs/cli/commands/call-start) — same confirmation, same balance check, same real money spent — just walked through visually instead of typed as flags.

## The flow

<Steps>
  <Step title="Enter a recipient">
    A prompt asks for the number to call, validated as [E.164](https://en.wikipedia.org/wiki/E.164) format (`+14155551234`) before you can continue. An invalid format is rejected right there, before anything is sent anywhere.
  </Step>

  <Step title="Confirm">
    A confirmation screen shows the agent, the recipient, and your account's **real current wallet balance** — pulled fresh, not cached. Nothing dials until you explicitly answer `y`.

    ```
    Start a call?

      Agent        Front Desk Concierge
      Recipient    +14155551234
      Balance      $482.19

    (y/n)
    ```

    This never fires automatically. There's no "skip confirmation" option inside the dashboard flow — for that, use [`bolna call start --yes`](/docs/cli/commands/call-start) from a script instead.
  </Step>

  <Step title="Watch it live">
    Once confirmed, the screen switches to a live view with an animated waveform, polling the call's status every 1.5 seconds until it reaches a final state (`completed`, `no-answer`, `failed`, etc.).
  </Step>

  <Step title="Read the transcript">
    When the call ends, the same screen shows the full transcript — no separate lookup needed, no need to copy an execution ID into another command.
  </Step>
</Steps>

## See also

<CardGroup cols={2}>
  <Card title="bolna call start" icon="terminal" href="/docs/cli/commands/call-start">
    The same flow, scriptable from the command line
  </Card>

  <Card title="Dashboard Overview" icon="gauge" href="/docs/cli/dashboard/overview" />
</CardGroup>
