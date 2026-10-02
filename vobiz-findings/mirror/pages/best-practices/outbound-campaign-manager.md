> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# How an Outbound Campaign Manager Works (2026 Guide)

> A vendor-neutral guide to outbound campaign managers - the dial lifecycle, carrier reputation, number rotation, daily caps, cooldown, retry policy, and the campaign state machine - plus how Vobiz Campaigns implements each one.

Running outbound calls at scale is not a dialling problem - it is a **reputation problem**. The moment a team moves from tens to thousands of calls per day, the question shifts from *"can we dial this number?"* to *"will anyone actually answer?"*

An **outbound campaign manager** is software that takes a list of phone numbers, dials each one systematically, records what happened, and surfaces the results - all while keeping your numbers from being flagged as spam. The hard parts are not the dialling itself; a SIP trunk and an API call can place a call in milliseconds. The hard parts are **which** number to dial from, **when** to dial, **how fast**, **what to do** when nobody picks up, and how to prevent your entire number pool from getting labelled *Spam Likely* by Tuesday afternoon.

This guide is a vendor-neutral walkthrough of how each of those five decisions works, what the trade-offs are, and how to configure them for a production campaign. Where it helps, it points to the equivalent control in [Vobiz Campaigns](/docs/platform/campaigns/list).

## The lifecycle of a single dial

To understand which configuration knobs matter, it helps to see what actually happens between *"I have a CSV of 10,000 phone numbers"* and *"the phone in someone's pocket rings."*

<Steps>
  <Step title="Upload">
    A contact list (typically a CSV) is parsed and stored. Each row becomes one record with a destination phone number and per-contact metadata.
  </Step>

  <Step title="Schedule">
    The user sets when the campaign should start - immediately, or at a specified future time.
  </Step>

  <Step title="Promote">
    When the campaign becomes active, every contact is enqueued into a job queue.
  </Step>

  <Step title="Pace">
    A worker pulls one contact at a time and decides whether to dial it **right now** or wait. This is where the rotation, cap, and cooldown rules apply.
  </Step>

  <Step title="Dial">
    The worker selects a `from` number from the pool, asks the SIP layer to place the call, and records the call UUID.
  </Step>

  <Step title="Hangup">
    When the call ends - answered, unanswered, busy, or failed - a webhook fires back to the campaign manager with the outcome.
  </Step>

  <Step title="Decide what's next">
    Based on the outcome and the campaign's retry policy, the contact is either marked terminal or scheduled for a retry.
  </Step>

  <Step title="Complete">
    When no contacts remain in pending or retry-pending states, the campaign is marked complete.
  </Step>
</Steps>

## The carrier reputation problem

Three companies - **Hiya**, **First Orion**, and **TNS** - operate the analytics platforms that mobile carriers use to decide how your call appears on a recipient's screen. Hiya powers AT\&T's call labelling, First Orion powers T-Mobile's Scam Shield, and TNS powers Verizon's analytics.

These engines never see the content of your call. They infer intent from **patterns**:

| Signal | Why it looks like a robocaller |
| - | - |
| **Calls per number per day** | A single number making 500+ outbound calls in 24 hours matches the statistical signature of a robocaller almost exactly. |
| **Burst patterns within a day** | Fifty calls in sixty seconds from one number is dramatically more suspicious than fifty calls spread over an hour. |
| **Answer-and-hang-up rate** | When recipients reject calls, analytics systems infer the calls were unwanted. |
| **Geographic mismatch** | A number in one area code calling many recipients in a distant area code signals a spoofed-feeling call. |
| **Number age** | Brand-new numbers with no history of normal use appear more suspicious. |

<Warning>
  Once a number earns a *Spam Likely* label, answer rates typically drop **40-70% overnight**. The labelling is sticky, and disputes require convincing three independent, proprietary AI systems - separately - that your traffic is legitimate.
</Warning>

Everything below exists to keep your traffic on the *legitimate* side of those signals.

## Number rotation: the core idea

Instead of dialling all calls from one number, a campaign manager maintains a pool of phone numbers - called **DIDs** - and rotates across them systematically. Three standard rotation policies exist:

| Strategy | How it picks the next number | When to use |
| - | - | - |
| **Round-robin** | Cycles through numbers in order: `1 → 2 → 3 → 1 → 2 → 3`. Produces perfectly even distribution. | The right default for almost every campaign. |
| **Least-used** | Always selects the number used fewest times. Recovers gracefully when the pool changes mid-campaign. | Uneven contact lists, or pools that grow/shrink mid-run. |
| **Random** | Picks uniformly at random. Same average distribution, but can create uneven bursts. | Only for specific adversarial contexts where carriers fingerprint round-robin patterns. |

<Note>
  In Vobiz these are the **Round Robin**, **Least Used**, and **Random** rotation strategies, available when the caller-ID strategy is set to **Pool**. See [Caller ID Strategy](/docs/platform/campaigns/list#3-caller-id-strategy).
</Note>

## The daily cap: the most important reputation knob

Carrier analytics systems specifically watch **24-hour windows**. A number placing 800 calls today and zero yesterday is far more suspicious than one placing 50 calls per day every day for a month.

| Campaign type | Daily cap |
| - | - |
| Compliance-sensitive (financial, healthcare) | 25-40 calls / number / day |
| General B2C outreach | 50-100 calls / number / day |
| Internal notifications, low scrutiny | 200+ calls / number / day |

Two caps work together, and you usually want both:

* **Daily cap** - limits how many times a single number is used within one 24-hour window. Addresses **burst risk**.
* **Lifetime cap** - limits total uses of a number across the whole campaign. Addresses **cumulative wear**.

<Note>
  Vobiz exposes both as **Max calls / day** and **Max calls (lifetime)** per number, applied to every number in the pool. The daily ceiling resets at midnight in the campaign's timezone. See [Limits](/docs/platform/campaigns/list#5-limits-optional-applied-to-every-number-in-the-pool).
</Note>

## Cooldown: preventing burst patterns

A **cooldown** period means: after a number is used for one dial, it cannot be used again for at least *N* seconds. This smooths timing so it looks naturally spaced rather than machine-gunned.

```text Throughput math theme={null}
Effective rate per number  =  (1 / cooldown_seconds) calls/sec
Aggregate throughput       =  (pool_size / cooldown_seconds) calls/sec
```

A 10-second cooldown across a 20-number pool gives **2 calls per second** aggregate throughput - well under any reasonable daily cap, and the timing pattern appears naturally spaced to carrier analytics systems.

<Tip>
  Cooldown and rotation reinforce each other: rotation spreads volume **across** numbers, cooldown spreads it **over time**. Use both. In Vobiz this is the **Cooldown (sec)** field. Pace overall throughput separately with **CPS** and **Max Concurrent** - size them with the [CPS Calculator](/docs/resources/calculator).
</Tip>

## Retry policy: persistence without harassment

Not everyone answers the first time. A retry policy decides how many times - and how far apart - to try again before giving up. Escalating delays plus a hard retry window keep a campaign persistent without hammering unreachable numbers indefinitely.

| Use case | Attempts | Delays | Window |
| - | - | - | - |
| Appointment reminder | 2 | 30 min, 60 min | 1 day |
| Sales outreach | 3 | 60 min, 240 min, 1440 min | 7 days |
| Emergency notification | 4 | 5 min, 15 min, 30 min, 60 min | 1 day |
| Soft renewal reminder | 1 | 1440 min | 3 days |

<Note>
  Vobiz **Retry Attempts** accepts `0-5` (default `2`) and uses an exponential-backoff schedule for contacts that didn't answer - busy, no-answer, or network error. See [Retry Attempts](/docs/platform/campaigns/list#8-retry-attempts).
</Note>

## The campaign state machine

A campaign is a long-lived object that moves through well-defined states. A good manager makes the current state - and the *reason* for it - explicit at all times.

| State | Meaning |
| - | - |
| **Draft** | Created; no contacts uploaded yet. |
| **Ready** | Contacts uploaded, waiting for start. |
| **Running** | Actively dialling. Sub-states: `active`, `idle`, `stalled`. |
| **Paused** | Temporarily stopped - the reason must be exposed: manual, window closed, pool exhausted, failures. |
| **Cancelled** | Terminal stop. Data preserved permanently. |
| **Completed** | Every contact reached a terminal state. |
| **Archived** | Hidden from default list views. Data fully preserved. |

In the Vobiz Console, the live controls map onto these transitions:

* **⏸ Pause** - stop placing new attempts; calls already in flight finish normally.
* **▶ Resume** - restart from where the pause left off.
* **⏹ Abort** - cancel remaining attempts permanently; completed attempts stay in the logs.

<Warning>
  Campaigns are **never hard-deleted**. Every call placed carries the campaign ID - hard-deleting orphans historical reports, audit trails, and billing reconciliation. Vobiz preserves completed attempts in [Campaign Call Logs](/docs/platform/campaigns/call-logs) even after a campaign is aborted.
</Warning>

## A worked example

A **5,000-contact retention campaign** for a SaaS business. Goal: complete within a standard work week without burning numbers.

| Setting | Value |
| - | - |
| **Pool** | 25 numbers, Round Robin rotation |
| **Caps** | Lifetime 500 / number; daily 100 / number |
| **Cooldown** | 30 seconds |
| **Window** | 9am-6pm recipient timezone |
| **Concurrency** | 8 simultaneous calls |
| **Retries** | 2 attempts, 120 min and 480 min delays, 5-day window |

This delivers **2,500 calls per day** - the 5,000-contact list completes in **2 working days**. Each number averages 100 calls per day, well under spam thresholds, and nothing rings outside business hours.

## How Vobiz handles all of this

Building this from scratch is a multi-month engineering project with a long tail of edge cases that only surface in production. [Vobiz Campaigns](/docs/platform/campaigns/list) ships with all of it built in:

<CardGroup cols={2}>
  <Card title="Three rotation strategies" icon="arrows-rotate">
    Round Robin, Least Used, and Random across a pool of your DIDs - plus Single and Sticky caller-ID modes.
  </Card>

  <Card title="Per-number caps" icon="gauge-high">
    Max calls per day and lifetime ceilings, applied to every number in the pool.
  </Card>

  <Card title="Timezone-aware windows" icon="clock">
    Restrict dialling to compliant hours in the recipient's local timezone.
  </Card>

  <Card title="Configurable retries" icon="rotate-right">
    0-5 attempts with exponential backoff for unanswered contacts.
  </Card>

  <Card title="Cooldown + concurrency gating" icon="sliders">
    Per-number cooldown plus account-wide CPS and Max Concurrent pacing.
  </Card>

  <Card title="Full state machine" icon="diagram-project">
    Pause / Resume / Abort with explicit reasons and permanent CDR preservation.
  </Card>
</CardGroup>

With \~80 ms media latency, outbound reach across 130+ countries, and native integrations with [Vapi](/docs/integrations/vapi-dashboard), [Retell AI](/docs/integrations/retellai-dashboard), [ElevenLabs](/docs/integrations/elevenlabs-dashboard), [Pipecat](/docs/integrations/pipecat), and more.

<Card title="Start building on Vobiz" icon="rocket" href="/docs/platform/campaigns/list">
  Create your first outbound campaign - pool rotation, caps, cooldown, windows, and retries in one form.
</Card>

## Related reading

<CardGroup cols={3}>
  <Card title="Campaigns (Console)" icon="bullhorn" href="/docs/platform/campaigns/list">
    The full field-by-field walkthrough of launching a campaign.
  </Card>

  <Card title="Number Utilization" icon="star" href="/docs/best-practices/number-utilization">
    Number-series selection, daily volume limits, and spam reduction.
  </Card>

  <Card title="CPS Calculator" icon="calculator" href="/docs/resources/calculator">
    Size CPS, concurrency, and daily volume before launching.
  </Card>
</CardGroup>

## FAQs

<AccordionGroup>
  <Accordion title="What is an outbound campaign manager?">
    Software that takes a list of contacts, dials each one systematically, and manages the full lifecycle - including which number to dial from, when to dial, how to handle unanswered calls, and how to prevent phone numbers from being flagged as spam.
  </Accordion>

  <Accordion title="Why do outbound call numbers get labelled Spam Likely?">
    Carrier analytics engines (Hiya, First Orion, TNS) score outbound numbers based on calls per number per day, burst density, answer rates, and geographic patterns. When a number makes too many calls too quickly, it earns a spam label that suppresses answer rates by 40-70%.
  </Accordion>

  <Accordion title="What is the difference between a daily cap and a lifetime cap?">
    A daily cap limits how many times a single number can be used within one 24-hour window. A lifetime cap limits how many total times a number is used across an entire campaign. Both are necessary - daily caps address burst risk, lifetime caps address cumulative wear.
  </Accordion>

  <Accordion title="How many retries should an outbound campaign attempt?">
    For most use cases, 2-3 retry attempts with escalating delays (60 minutes, 240 minutes, 1440 minutes). A retry window prevents retries from running indefinitely on unreachable numbers.
  </Accordion>

  <Accordion title="Can Vobiz support outbound campaigns in multiple countries?">
    Yes. Vobiz provides DID numbers and outbound calling reach across 130+ countries. Timezone-aware daily windows ensure calls only fire within compliant hours in the recipient's local timezone.
  </Accordion>
</AccordionGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.