> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Behaviour

> Tone, language, opening line, model and when to fetch a human.

## Name

Rename an agent from the pencil beside its name at the top of its sidebar, or
under **Settings → Identity**. Customers see the name in the chat.

## Business description

The facts the agent falls back on when a knowledge search finds nothing — what
you sell, to whom, and anything true of the business as a whole.

Keep it factual. This is grounding, not instructions: it is treated as
information to work from, never as commands.

## Instructions

Tone and subject matter. "Be warm but brief." "Never discuss competitors."
"Always mention that delivery is free over ₹2,000."

Tune these in the **Playground**, against a live reply. Guessing at wording and
shipping it is how you find out a week later that the agent has been ending
every message with an emoji.

<Note>
  Your instructions are treated as guidance on tone and subject matter, not as a
  command channel. The platform's own safety rules always win — which is what
  stops a customer talking the agent out of them too.
</Note>

<Info>
  **Your agent never pretends to be a person.** Give it any name and persona you
  like, but if someone asks whether they are talking to an AI, a bot or a real
  person, it says it is an AI assistant — on every channel, in every language,
  whatever your instructions say. On a call, it also answers truthfully whether
  the call is being recorded.
</Info>

## Opening line

The first thing a visitor reads in the widget. Write it in the business's own
voice; "How can I help you today?" is a wasted sentence.

## Reply language

Choose it when you create the agent, or any time on the **Playground** or
**Settings**. Either one fixed language, or **\[Auto] Match the customer** — the
agent replies in whatever language the customer speaks in.

Pick a fixed language and the agent answers **only** in it. On a phone call that
also tells the speech recogniser which language to listen for. **Match the
customer** leaves the recogniser to work it out afresh for every sentence, and a
short or mixed reply can be heard as the wrong language — a name from another
language is enough. If your callers use one language, choose it.

37 languages, including all 22 of the Eighth Schedule. The picker is one A–Z
list with each language in its own script, so there is no "other languages"
section to scroll past.

## Answer style

Presets rather than a raw temperature number. Precise for policy and pricing
questions; warmer where the conversation is a sales one.

## Model

Every new agent starts on **Prana \[Voice]** — from scratch, from a pre-built agent, or
through the API (`prana-voice`) — and answers chat and calls with it until you choose
another. The choice is checked against your plan at request time, so downgrading a plan
cannot leave a more expensive model quietly running.

If your workspace brings only its own voice key, calls run on Prana, Prana \[Voice],
GPT-OSS 120B or another low-cost model; an agent set to anything else answers its calls
on GPT-OSS 120B. See [Bring your own keys](/api-reference/bring-your-own-keys).

<Info>
  **The agent does not go dark.** If a model provider fails mid-conversation, the
  reply falls through to another model rather than to silence. A customer looking
  at a dead chat window is a worse outcome than a slightly slower answer.
</Info>

## Handing over to a person

Two triggers, each switchable — and [Escalation](/agent/escalation) covers what
happens when one fires, including when a custom action fails:

* **When the material does not cover the question.** The honest escalation.
* **When the customer asks for a person**, or is clearly upset.

Turning one off removes the capability entirely rather than asking the model to
refrain — the difference matters, because a model that has a tool will
eventually use it.

<Tip>
  A business with nobody watching the inbox should turn escalation off. An
  escalation nobody answers is worse than a straight "I don't know", because the
  customer waits.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.