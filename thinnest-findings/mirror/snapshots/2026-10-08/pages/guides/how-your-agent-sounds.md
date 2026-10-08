> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Make your agent sound right on the phone

> Why a reply that reads well can sound wrong, and the handful of changes that fix it.

An agent that writes well does not automatically speak well. The same sentence
that is clear on a screen can be confusing out loud, and almost every problem
comes from the same cause: **the caller hears it once, in order, and cannot go
back.**

These are the changes worth making, roughly in the order they matter.

## Never lead with the wrong word

This is the big one.

> **Yes, you can see the dentist on Monday morning.** Doctor Iyer is available
> on Tuesday and Thursday.

Read on a page, that corrects itself. Heard on a phone, the caller stopped
listening after "yes" and is already reaching for their diary.

Put the answer first:

> Monday is not possible — the dentist is here Tuesday and Thursday.

<Tip>
  Add this to **How it should speak** on the Voice page if you see it happening:

  ```text theme={null}
  Start with the actual answer. Never begin with "yes" or "sure" if what
  follows is a no.
  ```
</Tip>

## Say it the way you would say it

Written shorthand does not survive being read aloud.

| Written | Spoken as |
| - | - |
| Dr. Iyer | "Doctor" — or a stop halfway through the name |
| 4pm–8pm | anything from "four pee em to eight pee em" to a mumble |
| ₹1,200 | inconsistent, and often wrong |
| (subject to availability) | read out flat, or lost entirely |
| • three bullet points | read as one run-on sentence |

The supplied instructions already cover titles and brackets. If you are quoting
prices or times a lot, add:

```text theme={null}
Say numbers, prices and times the way a person would say them out loud.
Four p.m., not 4pm. Twelve hundred rupees, not Rs 1200.
```

## Keep replies short, then shorter

Two sentences is plenty. A caller cannot skim, and a long answer means either
they interrupt you or they stop listening — usually both.

The supplied instructions ask for one or two sentences. If yours are still long,
the cause is normally your **agent instructions** telling it to be thorough,
which is good advice for a website and bad advice for a phone.

## Do not describe things nobody can see

No lists, no links, no buttons, no "as shown below", no "click here". This is in
the supplied instructions, and it is the first thing to re-add if you rewrite
them from scratch.

If you need to send somebody a link, the agent should offer to have it sent by
message rather than reading a URL aloud. Nobody has ever successfully written
down a URL from a phone call.

## Let people finish

People pause mid-sentence on the phone. They are checking a calendar, or
thinking, or looking for their card. An agent that treats the first half-second
of silence as their turn will talk over them.

If callers are being cut off, say so plainly:

```text theme={null}
When they pause, let them finish. People hesitate when they are thinking or
looking something up. Silence is them thinking, not them finishing.
```

## Give it a first line that sounds like your business

**First words** on the Voice page is what the caller hears the instant they
connect. Answer the way your staff answer.

| Instead of | Try |
| - | - |
| "Hello, welcome to our automated assistant." | "Sunrise Clinic, how can I help you?" |
| "Thank you for calling. Please hold." | "Ravi Kitchens, good morning." |

Short, names the business, invites them to speak. Anything longer and they will
talk over it — which is not a failure, but it does mean nobody heard it.

## Where a new agent starts

Every new agent — from scratch, from a pre-built agent, during sign-up or through the API —
starts with the **Premium** voice **Kavya**, because the first call is the impression your
customers get. Premium calls are billed at the Premium per-minute price — that includes an agent you create
through the API without choosing a `voice`. Change the voice on the
Voice page, or with `voice` on [Update Agent](/api-reference/agents/update-agent), and the
agent keeps your choice. Agents you already have keep the voice they have.

## Pick the voice by listening

The voice list is on the Voice page. Names tell you nothing useful, so press play
and hear one. Then set it, ring the number, listen to a full sentence, and change
it if it grates.

Do it with your actual greeting, not "hello" — the sound of a voice reading your
business name is what your customers will hear a hundred times.

There are three tabs — **Standard**, **Premium** and **Studio** — with the
per-minute price on each. Premium voices are warmer and cost more per minute;
standard voices are what most lines run on and nobody complains. Studio is the
largest catalogue and the [cloning](/channels/voice-clone) tier, on the Scale
plan and above. Listen before deciding the difference is worth the difference —
on a short, transactional call it often is not, and on a line where the voice
*is* the brand it often is.

Standard and Premium are available on every plan, the free trial included. Try
the more expensive one early — it is easier to decide it is not worth the money
once you have heard it than to wonder. Studio is gated below Scale, but one
voice on it previews free on every plan, so you can hear the tier before
deciding whether to upgrade for it.

Ignore the language a voice is listed under when you are judging it. Every voice
speaks every language we support; that label is the accent it carries, not a
limit on what it can say.

## When to change the model

Rarely. The recommended one is chosen for how quickly it starts speaking, which
matters more on a call than almost anything else.

Change it if the agent is following your instructions loosely — ignoring a rule
you have stated plainly, or inventing details. Some models hold a long
instruction better than others. Change it back if replies get slower; a thoughtful
answer that arrives late sounds like a bad line, not a careful assistant.

<Note>
  Every model in the voice list is fast enough to hold a conversation. That is
  the filter — a model that pauses to think is not offered here at all, however
  good it is at writing.
</Note>

## Test it the way it will actually be used

<AccordionGroup>
  <Accordion title="From a mobile, outdoors">
    Not from a quiet room on speakerphone. Wind, traffic and a poor signal are
    the normal conditions for a customer ringing a business.
  </Accordion>

  <Accordion title="With an accent the agent will hear">
    If your customers speak Marathi-accented English, test in Marathi-accented
    English. Testing in the accent the agent finds easiest tells you nothing.
  </Accordion>

  <Accordion title="Interrupting deliberately">
    Talk over it mid-sentence. It should stop. If it keeps going, callers will
    hang up — being talked over by a recording is the exact thing people hate
    about phone systems.
  </Accordion>

  <Accordion title="Saying something halfway and stopping">
    "I'd like to..." then a three-second pause. See whether it waits or jumps
    in. This is the single most common real-world failure and the easiest to
    miss when you are testing carefully.
  </Accordion>
</AccordionGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.