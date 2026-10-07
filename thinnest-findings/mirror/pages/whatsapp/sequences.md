> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Sequences

> A series of messages triggered by something that happened, not by a date.

A campaign is one message to a list. A **sequence** is a series of messages
triggered by an event — somebody abandoned a cart, placed an order, or asked
about a product and never came back.

## How it works

<Steps>
  <Step title="Something happens">
    An event arrives — from your systems via the API, or from something the
    customer did.
  </Step>

  <Step title="A matching contact is enrolled">
    Consent is checked at enrolment, and again at each send.
  </Step>

  <Step title="Steps run on their own delays">
    "Immediately", "after 2 days", "after a week". Each step is an approved
    template.
  </Step>

  <Step title="It completes, or stops early">
    A customer who replies, converts or opts out leaves the sequence.
  </Step>
</Steps>

## Sending events

Events come in through the API. See the [API reference](/api-reference/introduction).

## Variables

Each step's template blanks bind to contact fields or values carried on the
enrolment — so an abandoned-cart message can name the actual product.

## Consent, again

WhatsApp only allows messages to people who opted in, so who can be enrolled
depends on how they arrive:

| How they are enrolled | Who can be |
| - | - |
| Enrolling a list from the console | Only people who opted in |
| A tag that triggers the sequence | Only people who opted in |
| An event or enrolment from your systems, [via the API](/api-reference/report-event) | Anyone you send — the call is you confirming they opted in |

Opting out always wins, on every route: somebody who opted out is never enrolled,
and opting out is re-checked at each send. A customer who opts out on day one of a
seven-day sequence does not receive day three.

## Metering

Sequence sends are metered like any other template send.

Most are charged. A **utility** step is the exception: until 1 October 2026, if
it reaches somebody who is still inside their own 24-hour window — which a drip
step often does, since it goes out to people who replied recently — Meta gives
it away, and so do we.

<Note>
  Sequences run on our side, not from a browser tab — unlike a campaign started
  in the console. Nothing needs to stay open for a sequence to keep sending.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.