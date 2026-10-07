> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Escalation

> How the agent hands a conversation to a person — including when an action fails.

The counterpart to knowledge search: one finds an answer, this one admits there
isn't one.

Without it the agent's only options are to guess or to apologise into the void,
and you never learn it happened.

## The two triggers

Each switchable, per agent.

| Trigger | Fires when |
| - | - |
| **When the material does not cover it** | A knowledge search found nothing and guessing would be worse than waiting |
| **When the customer asks** | They ask for a person, or are clearly upset |

Turning one off **removes the capability**, rather than asking the model to
refrain. A model that has a tool will eventually use it; a model without one
cannot.

<Warning>
  **A business with nobody watching the inbox should turn escalation off
  entirely.** An escalation nobody answers is worse than a straight "I don't
  know", because the customer waits for something that is not coming.
</Warning>

## What happens when it fires

<Steps>
  <Step title="The conversation is flagged">
    Status changes to **escalated** and it surfaces in the inbox.
  </Step>

  <Step title="A note is written for whoever picks it up">
    One sentence on what the customer wants and what the agent could not find —
    written for a colleague, not for a log.
  </Step>

  <Step title="Your integrations fire">
    Outbound webhooks are delivered, and if you have connected one, a
    [helpdesk ticket](/workspace/helpdesk) opens in Zendesk or Salesforce with
    the transcript.
  </Step>

  <Step title="The customer is told">
    The agent says a person will follow up. It does not go quiet.
  </Step>
</Steps>

## Escalation from a failed action

The case worth planning for.

When a [custom action](/agent/custom-api) times out, returns a 500, or cannot be
reached, the agent is told the lookup failed. It does **not** invent an answer
and it does not pretend the tool succeeded.

What it does next depends on whether escalation is available:

| Escalation | What the customer gets |
| - | - |
| **On** | "I can't reach our order system right now — I've passed this to the team and someone will come back to you." |
| **Off** | "I can't check that at the moment. Please try again shortly." |

<Tip>
  **Switch escalation on wherever you have custom actions.** The failure mode of
  "I could not check that" is far better when there is somebody to pass it to —
  and your API will be down at some point, whatever your uptime target says.
</Tip>

The same applies when a customer hits the [per-conversation action
limit](/agent/custom-api#security): the agent stops calling and hands over
rather than continuing without the information.

## Once a person takes over

The agent **stops replying to that thread entirely**. Two voices answering the
same customer, contradicting each other, is worse than a slower answer.

When a teammate replies, the agent later reads that reply as its own prior turn
— so if the conversation returns to it, it does not re-answer something a person
just handled.

## It escalates once

The agent is told to call it once per conversation. Calling it again does not
make anybody arrive sooner, and a thread that escalates four times is four
notifications about one problem.

## If flagging fails

If the escalation cannot be recorded for some reason, the agent still tells the
customer a person will follow up — because the conversation is in the inbox
either way, and promising nothing is worse than promising something you will
honour by reading it.

## Related

<CardGroup cols={2}>
  <Card title="Inbox" icon="inbox" href="/workspace/inbox">
    Where escalations land, and how taking over works.
  </Card>

  <Card title="Helpdesk" icon="life-ring" href="/workspace/helpdesk">
    Escalations as Zendesk or Salesforce tickets, with replies routed back.
  </Card>

  <Card title="Custom API" icon="plug" href="/agent/custom-api">
    The actions whose failures escalation catches.
  </Card>

  <Card title="Analytics" icon="chart-line" href="/workspace/analytics">
    "Needed a person" over time — not a failure metric, a working one.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.