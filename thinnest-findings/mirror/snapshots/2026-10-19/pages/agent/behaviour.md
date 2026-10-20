> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Behaviour

> Tone, language, opening line, model and when to fetch a human.

## Where to set it

Most of this is on the agent's **Playground**, in four cards: **Language and
model**, **Voice**, **What Agent says** (the opening line and the instructions)
and **Reply length**. Nothing changes until you press **Save changes** at the top
right; after that it applies to the next message, including for real customers,
so the Playground is not a sandbox. **Test a call** and a chat panel sit beside
the cards (above them on a narrower screen), so you can try a change straight away.

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

Instructions can be up to **20,000 characters** — the counter under the box
shows how many you have used, and the same limit applies through the API.
Conversation steps are limited separately (up to 12 steps, each with an
80-character title and a 600-character detail) and don't count toward the
20,000.

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
**Settings**. Either **\[Auto] Match the customer** — the agent replies in
whatever language the customer speaks in — or tick the languages it speaks: one,
or up to four.

Through the API, send `languages` on Create Agent or Update Agent: a list of
language names. `[]` is auto, one name is that language alone, and two to four are
the languages the agent expects, the first being the one it falls back to, for
example `["Telugu", "English"]`. More than four, a repeat, a name the console does
not offer, or `languages` together with `language` is refused with a `400`. Get
Agent returns `languages` too. Sending `language` (one language) still works and
replaces any list.

In chat (website chat, WhatsApp, Telegram, the Playground and test chat), **Match the
customer** reads the script of the customer's latest message. Write in Telugu, Hindi,
Tamil, Kannada, Malayalam, Bengali, Gujarati, Punjabi or Odia script and the agent
replies in that language, even if its opening line was in another. Once a conversation
is under way, a few words in another script do not move it: the agent switches when the
customer's first message is in that script, or when a later message is a real sentence
in it. Some cases are left to the agent's own judgement: a message written in English
letters (including Telugu or Hindi typed in English letters), a message too short to
tell, and one that is mostly English. A customer can always ask for a different
language and the agent follows.

Pick one language and the agent answers **only** in it. On a phone call that
also tells the speech recogniser which language to listen for. **Match the
customer** leaves the recogniser to work it out afresh for every sentence, and a
short or mixed reply can be heard as the wrong language — a name from another
language is enough. If your callers use one language, choose it.

Pick **several** — Hindi and English, say, or Tamil and English — and the agent
answers in whichever of them the customer is speaking, and in the **first** one
you ticked when they use any other. On a phone call the recogniser still works
out the language for itself, but only among yours: a reply it hears as some
other language is listened to again in the language the call is in. That
second listen adds about half a second, and only to those replies. Up to four
languages; the first one you tick is the one the agent falls back to.

37 languages, including all 22 of the Eighth Schedule, searchable, each in its
own script, so there is no "other languages" section to scroll past.

## Speaking speed

In the **Voice** card, under the voice itself: how fast the agent talks on
calls, on a slider from slower to faster. See
[Speaking speed](/channels/voice#speaking-speed).

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
on GPT-OSS 120B. If it brings only its own language model key, your key answers on any model it
offers, and the call is billed like any other call, by the voice. See
[Bring your own keys](/api-reference/bring-your-own-keys).

A model marked **premium** in the picker puts every call on the premium per-minute rate,
even with a standard voice. `GET /api/v1/models` gives the same thing for each model:
`callTier` (`standard` or `premium`) and `callPricePerMinuteMicro`, the price of one call
minute in millionths of `currency` (the currency of the wallet your calls are charged
to). Both cover the model only, with a standard voice: a premium or studio voice can
raise a call's price, and one call is billed at one rate, never a stacked surcharge. If
your workspace brings its own keys, calls bill at the
[BYOK per-minute rate](/api-reference/bring-your-own-keys) whatever the model, so these
prices apply only to an agent you've set to run on our stack. The exception is a workspace
that brings only its own language model: there the voice plan still applies, set by the voice
alone, and the model you run never raises it. Typical response latency
per model isn't published.

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