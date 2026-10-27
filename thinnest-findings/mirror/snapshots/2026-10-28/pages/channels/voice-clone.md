> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Voice Clone

> Record a short sample and your agent can speak in that voice — a founder's own, or someone from your team.

Fifteen seconds of somebody reading a line becomes a voice your agent can
answer calls in. It is a Studio voice like any other on the [Voice
page](https://docs.thinnest.ai/channels/voice.md) — same per-minute rate, same tab — except this one is
yours rather than picked from a catalogue.

> [!NOTE]
>
> **Voice Clone** has its own page in the main sidebar, under the same group as
> Phone Numbers and Voice Campaigns. It lists every voice this workspace has
> made, not one agent's.

> [!WARNING]
>
> **This is on the Pro plan and above.** Free and pay-as-you-go see the offer
> over a blurred page rather than the recorder — cloning somebody's voice and
> then telling them they cannot use it would be worse than not offering it.

## Clone a voice

**1. Open Voice Clone**

In the main sidebar, choose **Voice Clone**.

**2. Agree to the two things this actually asks**

Before anything records, you confirm two separate promises — not one
checkbox that quietly covers both:

* The recording is your own voice, or you hold the rights and permission to
  clone the voice in it.
* You will not use it to impersonate anyone, or for anything illegal,
  harmful or misleading.

Both are recorded against the voice, with who agreed and when — this is
what makes the clone lawful to hold, not a formality on top of it.

**3. Read the line out loud**

Record straight from the page, or upload a file — WAV, MP3, M4A or WebM.

Fifteen seconds is the sweet spot: five is the least the engine will accept,
and thirty is the most it wants — read your longest sentence twice if you
are short, rather than pausing partway through and starting again.

Read normally, in one take, without music or anyone else talking over you.
A treated room helps, but is not required — noise removal is on by default
and can be turned off if it flattens a voice recorded somewhere already
quiet.

**4. Name it and set its language**

Give it a name your team will recognise in the voice list later — "Rohan"
or "Founder voice", not "Recording 3". Pick the language it will be
registered under, and an accent within it where the language has more than
one — Indian English and American English are not interchangeable for a
voice, even though the words are the same.

Description and tags are optional and are yours alone — a note for your own
team about when to use this voice, not something a caller ever sees or
hears.

**5. Listen to it**

The moment it is made, it says your line back to you in its own voice — the
same sentence you read, spoken by the clone. That is the one time it is
synthesized for free; every play after this comes from that same recording,
never a fresh one.

## Using it

A cloned voice appears on the **Studio** tab of the voice list, under **Voice** on the agent's Playground,
above the shared catalogue, marked as yours. Choose it like any other voice and
save — nothing else changes about the agent.

> [!NOTE]
>
> It answers calls at the **same per-minute rate as every other Studio voice**.
> Cloning costs nothing; what it speaks on a call is billed the same as Anjali,
> Rakesh Khanna or any of the hundreds of others on that tab.

## Languages

You can clone in any language on the list. If your business is billed outside India, a clone in a language outside
the fifteen the Studio catalogue speaks best (listed under [Voices for more
languages](https://docs.thinnest.ai/channels/voice.md#voices-for-more-languages)) is made with the second set of voices, so it speaks that
language properly on calls. Bosnian and Sundanese are offered only there. Everything else is the same: the same
steps, the same per-minute rate, the same limit, and deleting it removes it everywhere.

If a language shows "Voice cloning in this language is full right now", tell us and we will make room.

## The limit

**Up to 10 cloned voices on Pro, and 20 on Scale.** Enterprise is agreed per
contract. Delete one to make another once you reach it.

If your workspace genuinely needs more, ask us — a higher limit can be set for
your workspace alone. We keep the default modest on purpose: every clone is a
recording of a real person, and a growing pile of them is a growing
responsibility.

## Removing one

Delete a voice from the **Voice Clone** page and it is gone everywhere — the
recording, the preview, and the voice itself at the engine that spoke it. This
cannot be undone.

> [!WARNING]
>
> **An agent already speaking with it is moved to a Premium voice automatically**,
> so a deleted voice never leaves an agent silently billing the Studio rate for
> a voice that no longer exists. Check the agent's Playground afterwards if you
> want to pick something else.

## Your customers can use your voices

If you are a developer building for [customers](https://docs.thinnest.ai/api-reference/customers.md), **every
voice you clone can be used by all your customer workspaces**, automatically.
It shows on their **Studio** tab, and in
[`GET /voices`](https://docs.thinnest.ai/api-reference/voices/list-voices) with `"sharedFromDeveloper": true`,
and their agents speak with it like any other Studio voice. Its `id` there is your
own voice's `id`, unchanged. Their calls are billed to them as usual.

It stays yours: a customer cannot rename or delete it, and it counts against **your**
clone limit, not theirs. A customer's own clones stay theirs alone — you and your other
customers do not see them. If you delete one of your voices, every agent speaking
with it, yours and your customers', is moved to a Premium voice.

## Who can do this

**Admins only**, for cloning and for deleting. A cloned voice is somebody's
actual voice held under a consent record naming who agreed — the same weight
as the do-not-contact list or a KYC document, both of which are admin-only for
the same reason. Any member can still choose an already-cloned voice for an
agent, the same as choosing any other voice.

## What we keep, and for how long

The recording, the one stored preview, and the consent record stay for as long
as the voice exists. Deleting the voice deletes all three. There is nothing
else to configure — this follows the same erasure rule as [call
recordings](https://docs.thinnest.ai/channels/voice.md#recording-calls): once it is gone, it is gone, and
we cannot get it back.

> [!NOTE]
>
> Whether you had the right to clone a particular voice, and what you may say
> in it, is yours to get right — the two promises above are what we ask you to
> confirm, not a guarantee we can make on your behalf.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.