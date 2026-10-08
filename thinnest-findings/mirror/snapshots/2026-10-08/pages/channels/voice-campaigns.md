> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Calling campaigns

> Your agent rings a list and has the conversation itself.

A calling campaign is your agent ringing people one after another and talking to
them — the same audience rules and the same consent as a
[broadcast](/whatsapp/broadcasts), on the phone instead.

## Where to find it

**Voice Campaigns** is in the main sidebar, just under Contacts — under it
because a calling campaign is made *of* a contact list. Every campaign in the
workspace is on that one page, whichever agent places the calls.

## Which agent does the calling

You choose, when you build the campaign. It matters more than it sounds: a call
goes out from **that agent's number**, opens with **that agent's first words**,
and is priced by **that agent's voice**.

If you only have one agent that can call, there is nothing to choose and you are
not asked. If you have several, the builder asks first — before the audience,
because the answer changes what the rest of the campaign is — and the list shows
which agent each campaign belongs to.

An agent can only be picked if it can actually place calls: it needs a number
pointed at it on [Phone Numbers](/channels/phone-numbers), and it has to be set
to answer on the phone rather than only on the web. The builder says which of
the two is missing rather than making you guess.

<Note>
  Calling campaigns used to live on each agent's own page. They moved to the
  main sidebar so one workspace has one list — with three calling agents you
  had three lists that could not see each other, and finding a campaign meant
  remembering which agent you made it on. Old links still work.
</Note>

## Who gets called

Two answers, and they are alternatives rather than a pair.

**People already in Contacts.** The same four lists a
[broadcast](/whatsapp/broadcasts) offers, each showing its count before you
commit, and the same tags to narrow within one.

**Upload a list.** A CSV, mapped and rung. This is the one most people want:
the spreadsheet already exists, and nobody wants to import it, tag it, and then
come back here.

<Warning>
  **Numbers you must never call** belong on the do-not-contact list, on the
  **Contacts** page under *Do not contact*. Paste them or upload a file — from a
  regulator, a complaint, or a lawyer's letter — and no campaign will ever reach
  them, on any channel.

  It is not the same as somebody opting out. Opting out is about a customer you
  already have; this is about numbers, most of which are not in your contacts at
  all, and an import cannot undo it. It is checked at the moment each call is
  placed, so a list you upload at eleven stops a campaign that is already running
  by the time it reaches three.

  Somebody who tells your agent on a call not to be called again goes on this
  list by themselves — see ["Don't call me again"](/channels/voice#dont-call-me-again).
  A campaign skips them and shows why.
</Warning>

### Uploading a list

Drop a CSV with a header row. We guess which column is the phone number, the
name and the email — "Phone", "Mobile", "WhatsApp Number" and "Contact" all
land on the same guess — and you can change any of them. Any other column can be
pointed at something your agent says: see
[saying something different to each person](#saying-something-different-to-each-person). The panel shows the
numbers **as we will actually dial them**, not as the file wrote them, because
that is where spreadsheet damage shows up.

Pick the country for numbers with no country code. A number starting `+` or
`00` keeps its own.

<Warning>
  **Excel eats long numbers.** A phone number in a General cell can be saved as
  `9.19E+11`, and those digits are genuinely gone — we refuse the row rather
  than invent a number that reaches a stranger. Format the column as text and
  export again.
</Warning>

Rows we cannot read are listed with their line numbers and the reason. Leaving
them out is a tick you have to make: a list of a thousand that quietly calls
nine hundred is worse than one that stops and tells you.

Repeats within the file are dropped and counted. The same customer twice in an
export is ordinary; ringing them twice is not.

### What an upload does to your contacts

**The people on the file become contacts.** They are in Contacts afterwards,
and the campaign is aimed at exactly them — a label we put on those rows is
what keeps this campaign to this list.

There is a tick saying these people agreed to be called. It is a claim you are
making, recorded with the date, and it decides which *later* campaigns reach
them:

| The tick | Who reaches them afterwards |
| - | - |
| Left alone | Campaigns aimed at everybody, or at imported contacts |
| Ticked | Those, plus campaigns aimed at people who opted in |

<Warning>
  Uploading a spreadsheet is not consent, and a phone call is not a message
  somebody deletes. Calling a number on India's DND register without consent is
  an offence under TCCCPR, and the complaint lands on the number you called
  from.
</Warning>

Anybody who has asked you to stop is left out of the list even when they are in
the file. That is decided in the database rather than by the screen, so it
holds however the campaign was built.

The label stays on those contacts afterwards, so you can aim a second campaign
at the same people without uploading the file again.

## What it says

There is no message to write. A calling campaign opens with **the agent's own
first words** — the greeting on its Voice settings, the same one somebody hears
when they ring in — and talks from there.

> Hello, this is Meera from Sunrise Dental.

That is deliberate, and it is the one place a calling campaign is simpler than a
broadcast. A box here would have been a second version of what your agent
already says, and then nobody could answer the only question that matters: which
one does a customer actually hear? The builder shows the opening before you
launch, beside everything else, and links to where it is changed.

<Note>
  Worth reading it before a campaign goes out. A greeting written for people who
  rang **you** — "Thank you for calling Sunrise Dental" — is the wrong sentence
  coming from somebody who rang **them**.
</Note>

It is a real conversation, not a recording. People interrupt, ask something
unrelated, and the agent answers from your knowledge like it does on any other
call — then the whole thing lands in the inbox with its transcript.

Calls go out a few at a time rather than all at once. A hundred people are not
all rung in the same minute, which is deliberate: it is what a phone line can
actually carry, and what does not look like a machine.

<Warning>
  **Promotional calling in India needs a 140-series number.** An ordinary
  business number is licensed for service and transactional calls, and using it
  to promote something can get it blocked.

  You mark each call campaign as **service** or **promotional**, and we refuse a
  promotional one from a number that is not licensed for it — with a reason, not
  a silent failure. Marking a promotional campaign as service to get past this
  is the thing that gets numbers blocked.
</Warning>

## Saying something different to each person

Put `{{first_name}}` — or any name you like in double braces — into your
agent's greeting or its instructions, and every call fills it in from the row
that person came in on.

> Hello {{first_name}}, calling from Sunrise Dental about your appointment on
> {{appointment_day}}.

When you upload a list, the campaign shows you what your agent asked for and you
point each one at a column. Nothing to declare anywhere: we read the braces out
of your agent's own words, so the list is always what it actually says.

### What fills what

| Written in the agent | Filled from |
| - | - |
| `{{first_name}}`, `{{name}}`, `{{phone}}`, `{{email}}` | the contact, unless your file says otherwise |
| anything else | the column you mapped it to |

Your file wins where the two disagree — a column of preferred names beats the
name we have stored — but a **blank cell does not**. An empty column leaves the
contact's own details alone rather than wiping them for that one call.

`{{first_name}}` follows whichever name won, so a list that carries names for
people you have never spoken to still greets them properly. Map a `first_name`
column of your own if you want to control exactly what they are called — "Dr
Menon" rather than the first word of a full name.

<Note>
  **Keep values short.** These are words your agent says out loud, so anything
  past about 150 characters is trimmed. A date, an order number, a name or a
  short phrase is what belongs here; a notes column mapped by accident is not.
</Note>

### What happens when it is not filled

Nothing is said. "Your order {{order_id}} is ready" with no order mapped becomes
"Your order is ready" — a sentence, spoken normally, with the stray space and
the double space cleaned up.

<Warning>
  **Nobody ever hears the braces.** That is the one rule this feature is built
  around: an unmapped, unknown or misspelled variable is left out rather than
  read aloud. A cell that itself contains `{{something}}` is stripped too — you
  cannot smuggle a placeholder in through a spreadsheet.
</Warning>

### Careful with instructions

A variable in your agent's **greeting** only affects calls it makes.

A variable in its **instructions** is part of every conversation that agent ever
has — someone ringing your number, a website chat, a WhatsApp message. None of
those came from a list, so there is nothing to fill from and it resolves to
nothing for them. The upload screen says so when it spots one, and it is worth
reading: an instruction written for one campaign quietly applies to everybody.

## Looking someone up before you call them

Your list is fixed when you build the campaign. The facts about the people on it
are not — an order that was "packed" on Monday is out for delivery by Tuesday,
and an agent that opens with Monday's answer is worse than one that never
mentioned the order at all. The customer knows which is true.

**Pull Details/Data from API**, step 4 of a new campaign, closes that gap. Moments
before each person is called, we ask your own system about them and use what
comes back in what the agent says.

### What you need first

An **action** on the Actions page: your endpoint, its method, and any keys it
needs, saved once. The campaign picks one from a list — it never asks you to
paste a URL or a key a second time, and changing the action later changes it
everywhere it is used.

The action needs somewhere to put the number. If it declares exactly one field
we choose it for you; if it declares several, say which one is the phone number.

### Try it before you launch

Type one real number and press **Try it**. You will see exactly what the agent
would know about that person, written the way you would use it:

```
{{order_id}}       A-8841
{{status}}         out for delivery
{{eta_minutes}}    20
```

Those are the placeholders you put in your opening line. This really calls your
endpoint; it places no phone call and changes nothing about the campaign.

<Tip>
  Use it. Two dropdowns cannot tell you your endpoint expects `msisdn` where the
  campaign is sending `phone` — but one press of **Try it** does, before a
  single call goes out.
</Tip>

### What we can use from the answer

Plain values at the top level of your JSON. `"status": "out for delivery"` and
`"eta_minutes": 20` both work; a number, a word, or true/false.

Anything nested is skipped rather than read out. An agent saying "your order
\[object Object] is ready" is worse than one that never mentions the order, so we
leave it out and tell you which fields were ignored when you press **Try it**.

Whatever your system says wins over the same column in your uploaded file — that
is the entire point — except when it comes back empty, which does not erase what
you uploaded.

### If the lookup fails for someone

Your choice, and the default is the careful one.

**Don't call them, try again in a few minutes.** Nobody is rung until their
details come back, so a sentence built around `{{order_id}}` is never spoken
with a hole in it. They stay in the queue and are tried again shortly. If the
lookup fails for *everyone*, the campaign pauses and tells you why rather than
working through your list saying nothing useful.

**Call them anyway, without that data.** The call goes out using what you
uploaded, and anything the lookup would have added is simply missing from what
the agent says. Choose this when the extra detail is nice to have and reaching
people on time matters more.

<Warning>
  Every person on the list is one request to your endpoint, sent shortly before
  their call. A campaign of ten thousand people is ten thousand requests, paced
  by the campaign's own speed limit. If your system is rate-limited, set **At
  most, per hour** to something it can live with.
</Warning>

## When it calls, and when it stops

A campaign carries its own clock. Everything below is read in it, and it starts
as your workspace's — change it if you are setting this up from somewhere else,
and what you type is what the campaign does.

| Setting | What it means |
| - | - |
| **It starts** | Now, or at a time you pick |
| **Hours it may call** | The same stretch of every day the campaign runs |
| **Stop after** | Anything still unanswered by then is left uncalled |

Calls outside the hours **wait** rather than being dropped. A campaign started
at midnight begins in the morning, and its row says so rather than looking
stalled.

<Note>
  Indian rules restrict commercial calling to daytime, and 9am to 9pm is the
  window every campaign keeps unless you narrow it. Narrowing is normal — a
  clinic ringing about appointments and a shop ringing about an offer do not
  want the same hours.
</Note>

**The hours are read where each person is.** If your list has numbers in more
than one country, "9am to 6pm" means nine in the morning *to them* — a London
number is rung at 9am London time, not at 9am yours. That is what the rules say
and what anybody being rung would expect. Nothing to set: it comes from the
number.

Two consequences worth knowing:

* A campaign spanning countries is never all callable at once, so it works
  through the list in waves as each country's morning comes round. The row says
  it is waiting rather than looking stalled.
* For a country that spans several time zones — the United States, Canada,
  Australia, Russia, Brazil — a phone number does not say which one. We stay
  inside your hours at **both ends** of the country rather than guessing, which
  makes the callable stretch shorter but never rings anybody at six in the
  morning. If your hours are very narrow, a list like that may not be callable at
  all; the campaign says so instead of trying for ever.

## Calling from more than one number

A big campaign from a single number is the fastest way to get that number marked
as a nuisance line — and once it is, everything it does afterwards suffers,
including customers ringing you back.

If you hold spare numbers, give them to the agent under **Outbound** on
[Phone Numbers](/channels/phone-numbers) and the campaign spreads its calls
across them. Nothing changes in the builder and there is nothing to switch on.

An agent that has **no number of its own** can run a campaign too, from a number
you give it under **Outbound** — the builder offers it like any other agent.

The numbers can be on **different phone companies** — a ThinnestAI number and one
you imported from Twilio, for instance — and each call goes out through its own
number's company. If the campaign leaves a voicemail and only some of its numbers
can (ThinnestAI, Plivo and Telnyx numbers can), it still runs: calls on the others talk to the
answering machine instead, and the builder tells you how many numbers that is
when you create the campaign. If none of them can, it asks you to remove the
message.

Three things are worth knowing, because they are what makes it safe:

* **Whoever we ring keeps the same number.** A second attempt comes from the
  number that rang them the first time.
* **Somebody ringing back reaches whoever answers that number**, which is the
  agent under **Inbound** — not necessarily the one that rang them, and nobody at
  all if **Inbound** is empty. Decide that on the Phone Numbers page before a
  large campaign.
* **Each number has a daily limit** of 200 calls. A campaign that uses up every
  number pauses with a line saying so and carries on the next morning.

## Which days, and how fast

Two things worth setting on any list longer than a few hundred.

**Days it may call.** By default a campaign calls every day it is running,
Sunday included. Pick the days in the builder and it waits for the next allowed
one. The day is read where each person is, the same as the hours.

**At most, per hour.** By default a campaign uses every line your plan gives it,
which is the fastest it can go. That is the wrong setting when somebody has to
answer the calls that connect — a team of two cannot hold thirty conversations,
and the rest of your customers hear a hold tone. A cap only ever slows a
campaign down; your plan's lines are still the ceiling.

<Note>
  The cap is a rolling hour, not a clock hour. "Thirty an hour" means thirty in
  any sixty minutes — not thirty at 10:59 and thirty more at 11:01.
</Note>

### Trying again the next day, at a time you choose

Pick **The next day** as the wait and a time appears beside it. Leave it empty
and the retry goes out 24 hours after the call it missed — so an evening call
is tried the next evening, and later again each round. Set it to 9:00 and
everyone who did not answer is queued for nine the next morning instead.

A busy line is not affected: that is someone holding their phone right now, so
it keeps its own short wait in minutes.

Your calling hours still apply. The time says when somebody becomes due, not
that the call ignores your window.

### When your balance runs low

Two things stop, and not at the same point.

**Trying somebody again stops first.** Once your balance is down to about ten
calls, anyone who did not answer is left where they are and the campaign keeps
ringing numbers it has never tried — the last of a balance is better spent on
somebody who might pick up. The campaign says so on its page.

**Calling stops when there is not enough for one call.** Nothing is lost:
everybody still waiting keeps their place and their turn.

Top up and both resume by themselves within a minute or two. Nobody is dialled
twice for it, and no attempt is used up while calls are held.

## If it reaches voicemail

Most people do not pick up. There are two ways to handle a machine:

* **Leave a message.** Write one in the builder and, when an answering machine
  takes the call, your agent leaves it — in its own voice — and then hangs up.
* **Just hang up.** With no message and the agent's
  [Hang up on voicemail](/channels/voice#hang-up-on-voicemail) switch on, the
  call ends the moment a machine is detected, before your agent says a word, and
  is charged only the phone network's fee for those seconds.

With neither, nothing listens for a machine and your agent talks to it like any
other call.

<Note>
  Writing a message is enough — you do not have to turn anything else on. It is
  not available on every phone provider, and if yours is one of those you are
  told when you write the message rather than after the campaign has run.
</Note>

### How we tell a machine from a person

The phone company listens to the first few seconds of every call and guesses
whether a machine answered. **That guess is often wrong**, and more so on Indian
mobile numbers: on one campaign it called 18 real conversations "machine" out of
32 — people saying "Hello" or "हां" and then talking to the agent for minutes.
What it is used for depends on which of the two you chose.

**Just hang up: the guess decides.** The listening happens before your agent
speaks, so people who answer wait up to four seconds. It is set to lean towards
"a person" — silence when somebody picks up is not counted as a machine on its
own, and a short "Hello, haan ji, kaun?" counts as a person — but somebody who
answered will occasionally be dropped. If the campaign has retries, a call
dropped this way is tried again, so they get another call — and so is somebody
who hangs up during those seconds of silence.

**Leave a message: the guess alone never cuts anybody off.** It only makes us
listen more carefully to the first thing said on the line:

* **A voicemail greeting** — "please leave a message after the beep", "बीप के बाद
  अपना संदेश छोड़ें", "the number you have dialled is switched off" — gets your
  message, then the call ends.
* **Anything else** — "Hello", "हां", "बोलिए", a question — is treated as a person,
  and the conversation carries on as normal, whatever the guess was.

<Warning>
  With a message, we would rather miss a machine than hang up on a person: a
  greeting worded in a way we do not recognise is treated as a person, so
  occasionally your agent will talk to a voicemail box for a few seconds. Just
  hanging up makes the opposite trade — cheaper on voicemail, and now and then a
  person dropped. Test either on your own number first.
</Warning>

Calls that reached a machine are counted separately from calls somebody
answered — and a call where the customer said anything counts as answered, even
if the phone company first guessed otherwise. A recording is not a conversation,
and a person is not a recording.

## Testing two openings

Most of why somebody stays on a call or hangs up happens in the first few
seconds, so the opening is the thing worth testing.

Fill in **Test a second opening** and the campaign is created as two: "(A)" and
"(B)", each calling half the list, each with its own progress and its own
numbers. Nobody is called twice — the halves never overlap — and you compare
them by opening the two rows.

## How it went

A calling campaign shows more than how many calls went out:

| Number | What it means |
| - | - |
| **Called** | The people whose phones rang, with the total number of dials — somebody who was retried counts once here and once per dial in that total |
| **Answered** | People who picked up on their last call, as a percentage of the people called |
| **Average call** | How long the answered ones lasted |
| **Reached voicemail** | The phone company reported an answering machine and the person never spoke. If they did speak, the call counts as answered instead |

Beside them, **Minutes and cost** adds up every dial the campaign made —
retries and calls an answering machine took included, because each was charged
(a machine the call hung up on is charged only the phone network's fee):
the time on calls, how much of it was conversation, what was charged to your
wallet, and what that comes to per answered call and per minute. A call that never left for the phone network is not counted. Each call's own
charge is in Usage → Calls, and the two add up.

Underneath, **How the rest ended** breaks down everything that did not connect —
no answer, line busy, declined, not reachable, ended before the agent spoke —
and each person in the list shows how their own call ended rather than just
"Called", plus how many times they were dialled when it was more than once.

**Click anybody in the list to open their call** — the summary, the transcript and
the recording, in the same panel as Usage → Calls. The list shows each person's
most recent call; every earlier attempt is in Usage → Calls too. It shows 25
people a page — use the page numbers underneath, or search by name or number.

That breakdown is what tells you which problem you have. A lot of "Not reachable"
is a stale list. A lot of "Declined" is the wrong audience or the wrong opening.
A lot of "No answer" is usually the wrong time of day.

<Note>
  Declined and unreachable numbers are never called again. Busy, no-answer and
  answering machines the call hung up on are what retries are for — and anybody
  who rings your number back in the meantime is not called again either.
</Note>

## Ringing again

A person who does not pick up is not called again unless you say so. Whether a
second attempt is reasonable depends on why you rang, so it is a choice on the
campaign rather than a default.

Choose **how many times** to try again and **how long to wait** between tries.
Two retries half an hour apart means three calls at most, and the wait starts
when a call goes unanswered rather than when the campaign started — so somebody
rung late in a long run still gets the gap you asked for.

**A busy line gets its own, shorter wait.** The two are not the same thing and it
is worth setting them apart:

* **Engaged** means they are holding their phone right now. That is the most
  reachable anybody ever is, so the default is five minutes.
* **No answer** means they are away from it. Ringing back five minutes later is
  pestering, so the default there is half an hour.

Leave the busy wait alone and it does what it always did — the same wait for
both.

Anyone who answers is never called again, and retries keep to the calling hours
like every other call.

**And anyone who declined is never called again either.** We read what the
carrier says about how the call ended, so a retry means what you would want it
to mean:

| How it ended | Tried again |
| - | - |
| No answer | Yes — this is what retries are for |
| Line busy | Yes |
| Answering machine, and the call hung up on it | Yes, after the no-answer wait — they were not reached, and the guess may have been wrong |
| Answering machine, and your agent left the message | No — the message was delivered |
| Picked up, but ended before your agent spoke | Yes, after the no-answer wait — usually somebody who hung up while the voicemail check was listening |
| They declined | **No.** Pressing decline is an answer |
| Number does not exist, or is barred | No |

You see the same words on the call in your inbox — "Declined" rather than
"Missed call" — so the reason a number was or was not tried again is on the
record rather than something to work out.

<Warning>
  A phone ringing twice from a number somebody did not recognise the first time
  is the complaint that costs a number. Space the attempts out, and keep them
  few.
</Warning>

## Being told it started

A campaign set for nine in the morning starts with nobody watching — which is
the point of scheduling it, and also why "did it actually go?" is the question
it creates.

Pick anybody in your workspace under **email when it goes live** and they get an
email and a notification the moment it starts, with how many people it is
calling. Nobody is picked by default: a campaign that emails four people every
time it starts is a campaign whose emails get filtered.

## Cost

Calls are charged in half-minute steps, rounded up, and only for calls that
actually connect — a number that rings out costs nothing. The per-minute rate is
your agent's voice rate; the campaign builder shows it before you commit.

An answering machine the call hung up on never reached your agent, so it is
charged only what the phone network charges for those seconds, not your voice
rate. Once a person picks up, the call is your agent's and is charged at the
voice rate, however short. So is a machine your agent leaves a message on,
because your agent spoke.

See [Voice](/channels/voice) for the rest of what an agent does on the phone.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.