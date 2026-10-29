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

> [!TIP]
>
> Add this to **How Agent should speak** on the Playground if you see it happening:
>
> ```text theme={null}
> Start with the actual answer. Never begin with "yes" or "sure" if what
> follows is a no.
> ```

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

## If callers say it talks too fast

Usually it is the length, not the pace: a forty-word reply heard once, at a
normal speed, feels like a lecture. Shorten the replies first (the section
above), then, if it still feels rushed, move the **Speaking speed** slider a
little below Normal on the Playground, under the voice. It also helps on a poor phone line
and with callers listening in a second language.
[Speaking speed](https://docs.thinnest.ai/channels/voice.md#speaking-speed)

It is worth telling the agent what to do when somebody asks it to slow down, in
its instructions: shorter sentences and simpler words for the rest of the call.

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

**Opening line** (on the Playground, under **What Agent says**) is what the
caller hears the instant they connect. Answer the way your staff answer.

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
Playground, or with `voice` on [Update Agent](https://docs.thinnest.ai/api-reference/agents/update-agent.md), and the
agent keeps your choice. Agents you already have keep the voice they have.

## Pick the voice by listening

The voice list is on the Playground, under **Voice**. Names tell you nothing useful, so press play
and hear one. Then set it, ring the number, listen to a full sentence, and change
it if it grates.

Do it with your actual greeting, not "hello" — the sound of a voice reading your
business name is what your customers will hear a hundred times.

There are two tabs — **Premium** and **Studio** — with the per-minute price on
each. Premium voices are what most lines run on. Studio is the largest
catalogue and the [cloning](https://docs.thinnest.ai/channels/voice-clone.md) tier, at a higher rate, on
the Pro plan and above. Listen before deciding the difference is worth the difference —
on a short, transactional call it often is not, and on a line where the voice
*is* the brand it often is.

The Premium tab now lists over two hundred more voices, each named for who it is
and what it is for: *Ishita · Banking*, *Aayan · Conversational*, *Gokul ·
Narrator*. Hover a voice to read it: its gender, what it is for, and its
**accent** (Hindi, Indian English, Hindi–English mix, Marathi, Tamil, Telugu,
Kannada, Bengali, Gujarati or Punjabi). **Conversational**, **Customer care**,
**Sales**, **Banking** and the like are made for a live call; **Narrator**,
**News**, **Ads** and **Stories** are made for reading aloud and can sound stiff
in a conversation, so start with the first kind. Where one voice exists in two
accents, the accent follows its name. They cost the same as any other Premium
voice. Search by accent or style (type "banking" or "tamil") to find one.

Premium is available on every plan, the free trial included. Studio needs the
Pro plan or above, but one
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

> [!NOTE]
>
> Every model in the voice list is fast enough to hold a conversation. That is
> the filter — a model that pauses to think is not offered here at all, however
> good it is at writing.

## Test it the way it will actually be used

> **From a mobile, outdoors**
>
> Not from a quiet room on speakerphone. Wind, traffic and a poor signal are
> the normal conditions for a customer ringing a business.

> **With an accent the agent will hear**
>
> If your customers speak Marathi-accented English, test in Marathi-accented
> English. Testing in the accent the agent finds easiest tells you nothing.

> **Interrupting deliberately**
>
> Talk over it mid-sentence. It should stop. If it keeps going, callers will
> hang up — being talked over by a recording is the exact thing people hate
> about phone systems.

> **Saying something halfway and stopping**
>
> "I'd like to..." then a three-second pause. See whether it waits or jumps
> in. This is the single most common real-world failure and the easiest to
> miss when you are testing carefully.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.