> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Usage

> What your agents did, what it cost, and every call you can open and listen to.

**Usage** is the workspace-wide record: how much your agents worked, what that
cost, and a line for every call. It sits in the main sidebar, not under an
agent, because it covers all of them at once.

Analytics answers *how well is my agent doing*. Usage answers *what did it do,
and what am I paying for* — and they are different questions.

## The last thirty days

The chart at the top is activity over time: replies your agents sent and calls
they handled, on the same thirty-day grid so you can see them against each
other. A spike in calls the week you ran a campaign should look like one.

Useful for the thing dashboards rarely tell you: **when** your customers
actually get in touch. If the line rises every evening after six, that is when
somebody should be reachable.

## WhatsApp

WhatsApp is billed per message, and it is broken out here in full — marketing,
utility, authentication and service counted separately, by country, because they
cost very different amounts.

The figure against each line is **what you were charged**, in your own currency,
so it reconciles against your balance and against your own record of what you
sent. Everything the workspace sends is counted the same way, whether it came
from a campaign, a sequence, the Send Message page or the API.

<Note>
  **A message that was not delivered is not charged for.** WhatsApp bills for
  what it delivers. When a failure comes back the charge is credited, so a line
  you see here is a message that arrived.
</Note>

<Note>
  Until 1 October 2026, an open 24-hour window makes two things free: the
  agent's own replies, and any utility template you send while it is open.
  Templates that start a conversation are charged, and so is authentication in
  or out of a window. If a number looks higher than you expected, the split here
  usually shows why — see
  [Windows and what gets charged](/meta/windows-and-pricing).
</Note>

## Calls

Every call the workspace answered or placed, newest first: when, who, which
agent, whether it connected, how long it ran, and what it cost.

Open one to read the transcript. If the call was recorded, the recording is
there too.

**Export** gives you the same list as a file, for a spreadsheet or your
accountant.

<Note>
  A call that shows as **failed** never connected — a wrong number, a line that
  rang out, a caller who hung up before the agent spoke. Failed calls cost
  nothing and are kept so the list is honest about what was attempted.
</Note>

### How a call went

An opened call also shows how it went, in numbers, and whether anything broke:

* **How the call went** — how long the caller waited for each reply (the typical
  wait, the slow end, and the slowest), how many pauses of 10 seconds or more
  there were (or your agent's own "are you still there?" time, if it has one),
  how often the caller spoke over the agent, and how many replies the agent could
  not produce or a backup had to produce. A call that was never measured, such
  as one that never connected, has no figures.
* **Problems on this call** — shown only when something went wrong while the
  call was live: the agent could not answer, your own model key failed, a reply
  took more than 5 seconds to start, or the voice connection failed.

Through the API the numbers are `quality` on
[Get Call](/api-reference/calls/get-call), and every problem is sent as a
`call.problem` [webhook](/api-reference/webhooks#problems-on-a-live-call) while
the call is still going on, so you can alert somebody before it ends.

## Recordings

Recording is off unless you turn it on, per agent, on that agent's **Voice**
page. When it is on, the calls that agent answers or places — on your website,
and by phone on a number you took from us — are recorded and appear here.

<Warning>
  **Recordings are deleted when your plan says** — after 30 days on
  pay-as-you-go, 49 on Pro and 75 on Scale. Download anything you need to keep before
  then. Once it is deleted it is gone and we cannot get it back.
</Warning>

A caller on your website sees *This call is recorded* as the call connects. See
[Recording calls](/channels/voice#recording-calls) for which phone calls can be.

Telling people they are being recorded is your responsibility, not ours. In most
places it has to be said at the start of the call, and the wording that satisfies
your regulator is not something we can write for you. Put it in your agent's
first words.

## What is not here

<Warning>
  * **Per-customer spend.** Usage is per workspace and per channel, not per
    contact.
  * **Live figures to the second.** Costs settle when a call ends and when Meta
    confirms a send, so the most recent minutes can lag slightly.
  * **Your invoice.** This is what you used. What you owe is on
    **Settings → Billing**, and the two are presented differently on purpose.
</Warning>

<Tip>
  **Registered for GST in India? Put your GSTIN in Settings → Billing.** It is
  recorded on every invoice we issue you from the moment you save it, which is
  what makes those invoices usable by your accountant. Only an owner or admin
  can set it, and it takes effect on invoices issued afterwards — so it is worth
  doing before your first payment rather than after.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.