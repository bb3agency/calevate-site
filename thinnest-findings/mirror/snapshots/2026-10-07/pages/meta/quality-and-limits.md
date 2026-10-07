> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Quality ratings and messaging limits

> How many people you can reach, how to reach more, and how to lose the ability.

Two separate things, and people confuse them constantly:

* **Messaging limit** — how many unique customers you may message in 24 hours.
* **Quality rating** — how customers are reacting, which decides whether your
  limit rises or your templates get paused.

Both belong to Meta. Neither is something we set.

## Messaging tiers

| Tier | Unique customers per 24 hours |
| - | - |
| Starting | **250** |
| Tier 1 | 2,000 |
| Tier 2 | 10,000 |
| Tier 3 | 100,000 |
| Tier 4 | Unlimited |

<Note>
  The limit counts **unique customers you start conversations with**, not
  messages. Replying inside the 24-hour window to somebody who wrote to you does
  not consume it.
</Note>

Limits apply at the business portfolio level, shared across all your phone
numbers — a second number does not double your reach.

## Where to see yours

* **In the console:** Connect WhatsApp → **Calls** on the number. The window states
  your business's daily limit, the one WhatsApp uses to decide calling.
* **In Meta's WhatsApp Manager:** the messaging limit shown for your business.

<Warning>
  **You may see two different numbers.** WhatsApp Manager can still show an older
  **per-number** figure — often 250 — beside the business-wide limit. Meta moved
  limits to the business portfolio, and the business-wide figure is the one that
  counts, for messaging and for calling. A number showing "250" can belong to a
  business whose limit is already 2,000.
</Warning>

## Climbing

**Starting → 2,000.** Either [verify your business](/meta/verification), or send
2,000 delivered messages outside customer service windows to unique customers
within a rolling 30 days, using templates with a **high** quality rating.

Verification is the faster path, and it unlocks other things you will want
anyway.

**2,000 and above** happens automatically when you meet two conditions at once:

1. You are sending high-quality messages consistently, **and**
2. You use at least half your current limit within 7 days.

<Warning>
  **Condition 2 catches people out.** A business sitting at 2,000 and sending
  400 a day will never be promoted, however good its quality. Meta does not
  raise a limit you are not using.
</Warning>

If a tier increase is denied, Meta notifies you with a reason — usually identity
verification or delivery patterns.

## Quality rating

Scored per template and per number, from what customers do:

| Rating | Means |
| - | - |
| **High** | Minimal negative feedback |
| **Medium** | Negative feedback from several customers, or poor read rates. Still sendable |
| **Low** | Significant negative feedback or low engagement. At risk of suspension |

The signals are **blocks**, **reports** and **read rates**. Note the third: a
message nobody opens hurts you even if nobody complains.

## Pauses and disabling

A template with recurring negative feedback or low read rates enters **paused**
— it cannot be sent while paused. Repeat it and the template is **disabled**
permanently.

<Warning>
  A paused template is a warning about that message, but the underlying quality
  signal attaches to your **number**. Enough paused templates and the number
  itself is restricted, which costs you every template rather than one.
</Warning>

## Staying high quality

The failure mode is almost always the same: sending more than the audience
wanted.

<AccordionGroup>
  <Accordion title="Send to people who opted in, and only them">
    A bought list is the fastest route to a restricted number. Consent is
    enforced where it cannot be bypassed for exactly this reason.
  </Accordion>

  <Accordion title="Segment rather than blast">
    Start with the [narrowest audience](/whatsapp/broadcasts#choosing-an-audience).
    A campaign to 200 engaged customers outperforms one to 4,000 indifferent
    ones on every metric that matters — including the one Meta scores.
  </Accordion>

  <Accordion title="Frequency is the usual culprit">
    Two marketing messages a month is a business people tolerate. Two a week is
    one they block. Read rate falls first, then reports rise.
  </Accordion>

  <Accordion title="Make the first line worth reading">
    Read rate is a quality signal. A message whose first line is "Dear valued
    customer" is a message nobody opens.
  </Accordion>

  <Accordion title="Honour opt-outs immediately">
    Handled for you — a customer who turns off "Offers and announcements" or
    asks the agent to stop is recorded as withdrawn, and marketing to them is
    refused. Do not try to route around it.
  </Accordion>
</AccordionGroup>

## What to watch

Check quality before a big send, not after:

* **Delivered but not read** — a timing or subject problem. Change the hour
  before you change the audience.
* **A rising refusal count for consent** — correct behaviour, but it means your
  list is going stale.
* **A dropping read rate across campaigns** — the earliest warning you get. Act
  on it while the rating is still high.

## Restrictions

If Meta restricts your account, sends are refused. The console shows the reason
and when it lifts.

<Warning>
  **Do not retry into a restriction.** Every refused request is a signal that
  the business has not noticed, and a retry loop extends the restriction rather
  than getting through it.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.