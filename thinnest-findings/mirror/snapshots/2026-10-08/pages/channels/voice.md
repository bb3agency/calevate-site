> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Voice

> Your agent answers the phone — with the same memory of each customer it has everywhere else.

Voice is your agent picking up a call and holding a conversation out loud. It
listens, thinks and speaks, and the person on the line can interrupt it.

It is the same agent. The same knowledge, the same instructions, the same memory
of the same customer. Somebody who messaged you on WhatsApp last week and rings
you today is one person with one history.

<Note>
  Voice has its own page in the agent sidebar, under **Deploy** — not a tile on
  the Channels page. Everything about it lives on that one screen.
</Note>

## Turn it on

<Steps>
  <Step title="Open Voice">
    In the agent sidebar, choose **Voice**.
  </Step>

  <Step title="Switch on Answer calls">
    Off means the number does not answer at all. Nothing on the page runs until
    this is on.

    You can set everything up first and turn it on last. The settings are never
    greyed out, because the worst version of this is a real caller reaching a
    half-configured agent.
  </Step>

  <Step title="Choose where it answers">
    Open **Website** and switch on **Answer here**, and your agent answers calls
    from the chat widget straight away — no number needed, on any plan.

    To answer a number people dial, go to **Phone Numbers** in the main sidebar —
    the Voice page links there too.
    Take one from us — that needs a paid plan — or bring one you own with Plivo,
    Vobiz, Twilio or Telnyx, which works on every plan including the free one. A
    Plivo or Twilio number also needs your account's Auth ID and Auth Token before
    it answers, and a Telnyx number your account's API key. Then choose this agent beside the number, and it starts answering.
    See [Phone numbers](/channels/phone-numbers).
  </Step>

  <Step title="Call it">
    Ring the number. You should hear your greeting, then the agent.
  </Step>
</Steps>

## The settings

### Replies use

Which model does the thinking. Leave this on the recommendation unless you have
a reason to change it.

The list here is deliberately shorter than the one for chat. A model is only
offered if it can answer fast enough to hold a conversation — one that pauses to
think reads as a dropped call, not as a careful answer.

<Note>
  Your chat model is not used on calls. Voice is its own choice, because what
  makes a good writer and what makes a good speaker are not the same thing.
</Note>

### Voice

Which voice your customers hear. Press play on any of them to listen — reading
the name tells you very little, and the sample is the whole point.

Voices come in three tiers, on their own tabs:

<CardGroup cols={3}>
  <Card title="Standard" icon="circle">
    The everyday voices, and the cheapest per minute. Natural enough that most
    callers never think about it.
  </Card>

  <Card title="Premium" icon="sparkles">
    Warmer and more expressive, at a higher per-minute rate — and what a new agent
    starts on (Kavya). Worth it on a line
    where the voice is the first thing people judge you by.
  </Card>

  <Card title="Studio" icon="wand-magic-sparkles">
    The largest catalogue we offer — hundreds of voices — plus [your own cloned
    ones](/channels/voice-clone). Highest per-minute rate, on the **Pro
    plan and above**.
  </Card>
</CardGroup>

**The per-minute price sits on each tab**, so you can see what a choice costs
before you make it, and again beside **Voice** once you have chosen. A call is
billed at the rate of the voice answering it.

<Note>
  **Standard and Premium are open on every plan, including the free trial.**
  Try a Premium voice on your first day if you want to — nothing is held back,
  and the only difference is the per-minute rate shown on the tab.
</Note>

The Studio tab is shown on every plan, and one voice on it — a professional
customer-support voice — can be **previewed on any plan** so you can hear what
the tier sounds like. Putting any Studio voice on your agent, including that
one, needs the **Pro plan or above**. Below Pro the tab is visible with an
upgrade button over the rest of it, rather than hidden — you can see what you
would be buying before you buy it.

<Card title="Clone your own voice" icon="microphone" href="/channels/voice-clone">
  On the Pro plan and above, record a short sample and your agent can speak
  in it — a founder's own voice, or someone from your team. Up to 10 on Pro
  and 20 on Scale. Full details on its own page.
</Card>

Every voice speaks every language we support. The tier changes how a voice
*sounds*, never what it can say — which language it uses comes from your agent's
setting, covered below.

Through the API, `PATCH /api/v1/agents/{id}` with `"voice": { "voice": null }`
puts the agent back on the voice a new agent starts with (currently Kavya, a
Premium voice), and `"model": null` puts it back on the default model (Prana
\[Voice]). An empty string is refused: `null` is the way back.

### How it should speak

The rules the agent follows on calls, and only on calls. Your chat and WhatsApp
replies are untouched.

It comes filled in, so you are editing real sentences rather than facing an
empty box. Change what you like; clear the box entirely to go back to the
supplied wording.

<Warning>
  Two of the supplied lines are not style, and are worth keeping.

  **Write titles and abbreviations in full.** Speech is produced one sentence at
  a time, and a full stop inside a name ends a sentence early — an agent that
  writes "Dr. Iyer" can be heard stopping halfway through the name.

  **No brackets or bullet points.** Nothing pronounces a bracket. An aside in
  brackets is either read out as though it were the main sentence or lost.
</Warning>

### First words

Your agent's opening line — the first thing a caller hears, in your agent's own
voice. Leave it blank and it uses the agent's greeting.

Keep it short. It is spoken, and a caller who hears a paragraph before they can
speak will talk over it.

### Earlier conversations

What happens when somebody who has spoken with your agent before calls again,
or is called — whether that was an earlier call from the same number, or a chat
on WhatsApp or your website.

* **Remember quietly** — the default. Your agent knows what was said before and
  uses it, without mentioning it. Nobody has to repeat themselves.
* **Remember and recap** — your agent opens by saying you have spoken before and
  what it was about, then asks whether they would like to carry on or talk about
  something else. On a call you placed, it answers what they say first and
  recaps right after.
* **Start fresh** — every call starts clean. Your agent is given nothing from
  earlier calls or other channels, and never greets anyone as a returning
  caller.

A [call back](#booking-a-call-back) the customer asked for is the exception:
it always carries on from the conversation they booked it in, whichever you
choose, and its opening line already says why it is calling, so it is never
recapped on top.

The recap is in your agent's own words and in the language of the call — there
is nothing to write. It names what you talked about, never what they told you:
no amounts, dates or addresses until they bring them up, because anyone can
pick up a phone. A WhatsApp conversation that is kept hidden until the
caller is confirmed (the **Remembering the customer across channels** setting
on the Actions page, see [how two channels become one person](/concepts#how-two-channels-become-one-person))
stays hidden — your agent only says you have been in touch there.

It only happens when there is something to recap, and only once per call. A
first-time caller is greeted as one.

### Fillers Before Tool Run

On, and worth leaving on. Checking your documents or calling one of your tools
takes a second or two, and this is what the caller hears instead of silence.

Leave **What it says** blank and the agent says it in whichever language it is
speaking — if you have not fixed a language, it works that out from the caller,
so somebody who rings you in Tamil is answered in Tamil from the first word.

Fill it in and it says exactly that, every time, in whatever language you wrote
it. Keep it to a few words: it is covering a pause of a second or two, and
something longer just leaves a new silence after it.

Turn it off if you would rather the line stayed quiet.

#### When it speaks

When your agent decides to look something up or run one of your tools, it says
its line **straight away**, while the lookup runs, rather than going quiet
first. If the answer still has not started a little later, it says one more
line, then waits for the answer. It never says more than that for one question.

With **Fillers Before Tool Run** off, the agent says nothing extra while it
works, however long the lookup takes.

Two boxes under it set the timing. Leave either blank to use the standard.

| Setting | What it controls | Standard | Range |
| - | - | - | - |
| **How long it waits first** | Quiet time before the agent speaks on a slow reply | 900 ms | 200–5,000 ms |
| **How long before it says another** | The gap before a second line, and how long a lookup that is still running waits for it | 2,500 ms | 1,000–10,000 ms |

Set the second one longer if your lines take a while to say, so the second
never lands on top of the first. A value outside the range is pulled back into
it when you save.

## What language it speaks

Voice follows the language on your agent — set it on the **Playground** or
**Settings** page. Set the agent to Marathi and it answers calls in Marathi
**only**, and the speech recogniser listens for Marathi too.

Leave it on **\[Auto] Match the customer** and it works out what they are
speaking and answers in that. The recogniser then has to decide the language
afresh for every sentence, so a short or mixed reply can be heard as the wrong
one. On a line where people open in English, Hindi or a mix of both, this is
usually the right setting; if your callers all use one language, fix it.

An agent has one language. There is no "second language" setting: to serve two,
leave the agent on **Match the customer**.

## Where calls appear

Each call is its own conversation in the inbox, with its transcript, alongside
that customer's chats. One customer record, one memory, one history.

A call is genuinely a different thing from a message thread — it has a start, an
end and a duration — so it reads as its own entry rather than being appended to
a chat.

### The call log

**Usage → Calls** lists every call the workspace has made or taken, newest
first, with the transcript and the recording behind each row. Each one says how
it actually ended rather than just whether it finished:

| Outcome | What happened |
| - | - |
| Answered | A person picked up |
| No answer | It rang out — the commonest by far, and what retries are for |
| Line busy | Engaged. Worth trying later; they are near their phone |
| Declined | They pressed decline. Never called again automatically |
| Not reachable | No such number, barred, or out of service |
| Answering machine | Voicemail took it — see [Hang up on voicemail](#hang-up-on-voicemail) |
| Ended before the agent spoke | Something picked up, but the call ended before your agent started — usually somebody who hung up while the voicemail check was listening, or a caller who put the phone down straight away |

On an outbound call the row also shows **which of your numbers placed it**,
which is the question worth asking once an agent has spare numbers to call from.
Export gives you all of it as a spreadsheet.

<Note>
  A lot of *Not reachable* usually means a stale list. A lot of *Declined*
  usually means the wrong audience or the wrong opening. A lot of *No answer* is
  usually the wrong time of day. That is the whole reason the reason is shown.
</Note>

### Call summaries

Off unless you turn it on, under **Summarise each call** on the Voice page.
With it on, two or three sentences are written once a call ends — what the
customer said and how it finished — and they appear as a **Summary** tab on the
call in **Usage → Calls**, beside the recording and the transcript.

The transcript was always there and always free. What this buys is the time:
forty calls to get through is forty transcripts to open, or forty pairs of
sentences to skim.

It is written from the transcript afterwards by a small model, so it is a
reading of the call rather than a record of it. The transcript is what was
actually said, and it is still there underneath.

<Note>
  **A summary covers one call, not the customer.** Somebody rung three times
  has three calls in the log and three separate summaries. The whole history
  with that person is the conversation in the inbox.
</Note>

If your agent writes into a [spreadsheet](/agent/spreadsheet) and you have made
a column called **Summary** — or Notes, or Remarks — the same switch fills that
too. Nothing is summarised anywhere while it is off, including into that
column: making the column does not start it.

## Your knowledge on calls

Your agent searches your knowledge base on calls, the same as it does in chat.
Both are on by default.

They are **two switches**, on the **Actions** page, because looking something up
costs a little more on a call than on a page — the agent has to find the answer
before it can start speaking, so the caller hears a short pause. It is a pause,
not a wait, and for most businesses being right is worth it.

Turn the calls one off if you want the quickest possible line and your callers
mostly ask things your instructions already cover. Changing one switch does not
change the other.

<Note>
  **The agent says something while it looks.** When it has to check your
  documents — or reach any of your connected tools — it says a short "one
  moment" first rather than going quiet. A caller cannot see an agent thinking,
  and a few seconds of silence on a phone line reads as a dropped call.

  It is on to begin with, and it is yours to change under **Fillers Before Tool
  Run** on the Voice page.
</Note>

## Booking a call back

"Can you call me after five?" — the agent books it, and your number rings them
at that time. It works on calls and in WhatsApp chats, because that is where
people ask.

Say it however you like: *in half an hour*, *after five*, *tomorrow morning*.
The agent repeats back the time it booked, so nobody is left guessing.

**It only promises what it can keep.** If it cannot book one it says so plainly
instead — and there are a few reasons it might:

| Why | What the agent says |
| - | - |
| The agent has no number that can dial out | It cannot arrange a call and offers to help now |
| We have no number for that person | It asks for the best number to reach them on |
| Sooner than five minutes away | Too soon — a redial is not a callback |
| Further ahead than two weeks | Too far ahead to promise |
| Three already booked for them | It confirms the ones already booked instead |

**Outside your calling hours, it moves the time and says so.** "Call me at
eleven tonight" becomes nine tomorrow morning, out loud, on the call — never
silently, because somebody waiting by the phone at eleven is worse than being
told. The hours are checked again when the call is actually placed, so a
callback held up for any reason still cannot ring at a rude hour.

The booking appears on the conversation in your inbox, and when the call
happens it lands in that same thread — the request and the call it produced,
in one place. Everything still waiting is listed together on
[Voice Campaigns](/channels/voice-campaigns), with who, when, and what the agent
said it would call about — cancel one there if it is no longer needed, any time
before it goes out. Somebody who asks you to stop contacting them between booking and
the call is not rung.

<Note>
  Switch it off per agent under [Actions](/agent/actions) if you would rather
  your team called people back themselves. With it off, the agent tells anybody
  who asks that it cannot book one rather than promising a call nobody will
  make.
</Note>

## "Don't call me again"

When a caller asks not to be called again — "don't call me", "remove my
number", in any language — your agent puts their number on your
**do-not-call list** itself, tells them they will not be called again, and may
then say goodbye and end the call. It does not do this for "not now" or "call me
later"; that is a request for another time.

From then on **no outbound call rings that number**: a call placed by the API is
refused, a batch refuses that entry, a calling campaign skips the person and
records why, and a call back already booked is given up. If they ring you, the
agent answers as usual.

The number is the caller's own caller ID, so this works on **phone calls and
WhatsApp calls** where that number is known. On a web call, or when the caller
withholds their number, the agent says honestly that it could not note it here
and tells them to ask the business directly to be removed from its calling
list.

The list is the one on the **Contacts** page under *Do not contact*. An entry the
agent made reads *Asked on a call*, with what the caller said; remove it there
(an admin) or with the API if the person later asks to hear from you again. A
developer can also read, add and remove numbers with the
[do-not-call API](/api-reference/do-not-call/list-do-not-call-numbers), and hear about each
new one through the `contact.opted_out` [webhook event](/api-reference/webhooks).

<Note>
  This works on every voice agent, whatever else is switched on. It is separate
  from WhatsApp marketing consent.
</Note>

## Ending the call

Your agent can hang up. It does so when the conversation is genuinely
finished — after it has said goodbye and there is nothing left to do — and after
it has told somebody with an emergency to hang up and call their local
emergency number.

**The closing line is always spoken first.** The call ends when the agent has
finished talking, not part way through.

It is deliberately reluctant. It will not hang up because somebody went quiet,
because it could not help, or because the caller sounds annoyed — a person
thinking, hunting for an order number, or talking to somebody else in the room
is still on the call. If it cannot help, it says so and offers to have a person
follow up, and stays on the line.

<Note>
  Every voice agent decides this for itself, and the call record shows a short
  note saying why the call ended.
</Note>

### Releasing the line

**Hang up when the conversation ends**, on the Voice page, is on for every
agent and is the setting most people will never touch.

It exists because a finished conversation and a finished *call* are not the
same thing. The agent saying goodbye does not put the phone down — somebody has
to, and if it is not us it is the caller. Most callers do. The ones who set the
handset on a desk and walk away leave a line open, and **you are charged for
every minute of it**.

Turn it off only if you want the caller to be the one who ends every call.

<Warning>
  **On a number you brought yourself, this needs your carrier keys.** Ending a
  call is an instruction to your carrier, and your carrier will only take it
  from an account it recognises. Without those keys your number answers
  perfectly and we cannot hang up — the line stays open until the caller does
  it. Add them under **Bring your own number** and the switch starts working.

  Numbers you rent from us are unaffected. We already hold the account.
</Warning>

### Your own limits

Under **When the call ends** on the Voice page. Leave any of them empty and that
rule is off — none of them is on to begin with.

<AccordionGroup>
  <Accordion title="Longest a call may run">
    The agent starts wrapping up before your limit and ends the call at it, so a
    long call finishes with a sentence rather than a dead line. Calls stop at
    twenty minutes whatever you set.
  </Accordion>

  <Accordion title="If nobody speaks, ask — then end">
    Two settings, and the pair is the point. A twenty-second pause is usually
    somebody finding an order number, so the agent **asks** before it gives up:
    "Are you still there?", up to five times, and only then does the call end.

    Write your own wording or leave it blank, in which case it asks in whichever
    language it is speaking. **The count starts again the moment the caller says
    anything**, so a long call with several natural pauses in it never creeps
    towards hanging up.

    Ten to twenty seconds suits most support lines. Give people longer where
    they are working something out — and remember two or three of those seconds
    are audio still being processed, so five is really nearer eight.

    Leave **End the call after** empty and the call ends once the **last ask
    goes unanswered** — the agent never sits on a silent line after it has
    stopped asking. With neither set, a call where **nobody says anything for
    five minutes** is ended anyway, so a line somebody walked away from does not
    run on to the twenty-minute limit.
  </Accordion>

  <Accordion title="End when the caller says">
    Your own phrases, separated by commas — "bye", "that's all", "thank you
    goodbye". The agent still says its closing line first.

    **Short words match inside longer ones.** "bye" would also end a call on
    "goodbye for now, but first…", so prefer whole phrases.
  </Accordion>
</AccordionGroup>

<Note>
  **The agent can put a caller through to a person — on a phone call.** On the Actions page,
  turn on **Hand over to a person**, choose **Call transfer** and give the number (with its
  country code). When a caller asks for a person, the agent says a line you choose and connects
  them; the number rings for 30 seconds, and if nobody answers the caller is told the team will
  get back to them. It transfers on **phone calls** over a number we rent you, or a Plivo or
  Telnyx number you brought; on web and WhatsApp calls, and on carriers that cannot transfer, it
  hands over as a **chat** transfer (your team is told by email, Slack or webhook and the agent
  says somebody will follow up). Through the API: [`PATCH /agents/{id}/tools`](/api-reference/tools/update-built-in-tools)
  with `handOver` and `tools.escalate_to_human`. Details and billing: [Phone numbers](/channels/phone-numbers).
</Note>

## Recording calls

Off unless you turn it on, under **Record calls** on the Voice page. With it on,
the calls this agent answers or places are recorded — on your website and by
phone — and each recording sits with its call in [Usage](/workspace/usage).

**Website calls** are recorded on every agent that has it on. A caller sees
*This call is recorded* as the call connects, before anybody speaks.

**Phone calls** are recorded on every number — one you took from us, and one
you brought from any phone company. On a number you brought, your agent keeps
the recording itself, so nothing has to be switched on at your carrier — see
[Phone numbers](/channels/phone-numbers#recording-calls-on-a-number-you-brought).

**If a caller asks whether the call is recorded, the agent tells the truth** —
yes when Record calls is on, no when it is off — in the caller's language. Your
call rules cannot change that answer. It says "recorded" only on phone and web
calls with Record calls on, never on a WhatsApp call, which is not recorded.

<Warning>
  **Recordings are deleted when your plan says** — after 30 days on
  pay-as-you-go, 49 on Pro and 75 on Scale. Download anything you need to keep before
  then. Once it is deleted it is gone, and we cannot get it back.
</Warning>

Erasing a contact deletes their recordings along with their calls — the ones we
store, the phone provider's copy on a number you took from us, and any copy made
for model training — and a deletion that cannot finish at that moment is retried
every night. See [Your data: erasure and training](/workspace/data-and-erasure).

**Recordings and transcripts are never used for training on Pro and above.** On
pay-as-you-go they may be, and a workspace can be excluded on request.

Telling people they are being recorded is your responsibility. On a website call
we show the line above for you; on a phone call, in most places it has to be said
at the start of the call, and the wording that satisfies your regulator is not
something we can write for you — put it in your agent's first words.

## Interrupting

A caller can talk over the agent and it stops. This is how people actually use
phones, and an agent that finishes its sentence regardless sounds like a
recording.

### Words needed to cut the agent off

**Three by default.** The noises people make while they are listening — "okay",
"achha", "mm", "right" — are not attempts to interrupt, and an agent that stops
dead at every one of them is exhausting to talk to. Somebody agreeing with you
should not be treated as somebody cutting in.

Raising this never makes the agent slower to answer. The count applies only
while it is speaking; the moment it falls quiet, a single word starts your
caller's turn as it always did.

The trade is worth knowing. At three, a caller who says a single **"no"** or
**"stop"** while the agent is talking is not heard — the agent finishes its
sentence. In practice somebody trying to interrupt keeps going, and "no, stop
there" gets through on the third word. But a one-word command does not.

Lower it to **one** if that matters more to you than backchannels — a line
people ring when something has gone wrong, where the first thing out of their
mouth should stop the agent dead. The cost is that "okay" and "achha" stop it
too. Raise it if callers keep getting cut off mid-thought while the agent talks.

## Background sound

**Off, and most numbers should leave it off.** A clean line is what a support
number sounds like, and silence behind a voice is not a fault to be fixed.

Turned on, the caller hears a room behind the agent — an office, with the
distant keyboards and voices of a working desk. It can make a call feel like it
is happening somewhere rather than nowhere.

It can also do the opposite. The same sound that reads as a busy office to one
caller reads as a bad connection to another, and which one you get depends on
your business, your caller, and the handset they are holding. Ring your own
number and listen before you leave it on.

### How loud it sits

Quiet. Ambience works when nobody notices it and would notice its absence —
if a caller can point at it, it is too loud, and one who has to strain past it
to hear your agent would have been better off with silence.

The default is a good starting point. The slider stops well below your agent's
own volume on purpose: there is no setting here that turns the room into
something a caller has to talk over.

## Calling customers

Your agent can also ring people, from your own systems — a reminder the day
before an appointment, a call when an order is ready, a follow-up after a visit.

There are two ways to start one. For a list of people, use a [calling
campaign](/channels/voice-campaigns) — **Voice Campaigns** in the main sidebar,
where you pick which agent does the calling.

For one call at a time, from your own systems, it is one request to
[the calls API](/api-reference/calls/place-call), which takes the reason for the call
as words the agent speaks first:

```json theme={null}
{
  "to": "919876543210",
  "purpose": "I'm calling from Sunrise Clinic about your appointment with Doctor Iyer tomorrow at four."
}
```

<Warning>
  You can only call people who are **already your contacts** and who have not
  asked you to stop. Those are our rules and they are not the law — automated
  calling is regulated nearly everywhere, and having a lawful basis for each
  call is yours to get right.
</Warning>

### Hang up on voicemail

Off unless you turn it on, under **Hang up on voicemail** on the Voice page. It
applies to the calls your agent places on your behalf — campaigns, the calls API
and test calls — and never to calls somebody makes to you. A call-back a
customer asked for never checks either: they are expecting the call, so the
check could only cut them off.

With it on, the phone company listens to the first few seconds of each call
before your agent speaks, and **if it decides an answering machine picked up,
the call ends right there**. Your agent never starts, and the call is charged
only what the phone network charges for those seconds — not your voice rate.

What that costs you:

* **People who do answer wait up to four seconds** before your agent speaks,
  while the listening happens.
* **The guess is not always right.** It is set to lean towards "a person":
  somebody who picks up and waits for you to speak is not counted as a machine
  for that alone, and a short greeting such as "Hello, haan ji, kaun?" counts as
  a person. Even so, a person will occasionally be dropped. In a campaign with
  retries, a call dropped this way is tried again like one nobody answered, so
  they get another call. So is somebody who hangs up during those seconds of
  silence.

It is worth it on a long list where most calls reach voicemail, and not on a
short one where most people pick up. Try it on your own number first.

A campaign with a **voicemail message** works differently: it waits to hear the
greeting so it can leave the message — see
[If it reaches voicemail](/channels/voice-campaigns#if-it-reaches-voicemail).

<Note>
  Not every phone provider can tell a machine from a person. On a number from
  one that cannot, the switch has no effect and your agent talks to whatever
  answers.
</Note>

## A call button in your chat

When **Website** is switched on, a call button appears beside the message box in your
widget — visitors press it and start talking, without dialling anything.

<Steps>
  <Step title="Tick Website on the Voice page">
    That is the whole of it. The button appears in the widget on every page the
    chat is already on, and disappears again the moment you untick it or switch
    **Answer calls** off.
  </Step>

  <Step title="Try it in the playground">
    The playground shows the same widget your visitors see, so the button is
    there too. Press it and talk — this is the quickest way to hear your agent
    before anybody else does.
  </Step>
</Steps>

<Note>
  The visitor's browser asks for microphone permission the first time. Until they
  allow it nothing is recorded, and if they refuse the button says so rather than
  failing silently.
</Note>

A call from the widget is the same conversation as their chat — same person,
same memory, same inbox thread — so somebody can type a question, call to
discuss it, and the agent knows what they already asked.

## WhatsApp

<CardGroup cols={1}>
  <Card title="WhatsApp calling" icon="whatsapp" href="/whatsapp/calls">
    Customers press call inside the WhatsApp thread and reach the same agent.

    The **WhatsApp** row on this page is on by default. Whether a number takes
    calls is its own **Calls** switch on Connect WhatsApp, which turns this row on
    and off with it.
  </Card>
</CardGroup>

## Texting the caller

During a call the agent can send the caller a WhatsApp or an SMS (a booking link,
your address) when you turn those on in [Actions](/agent/actions#reaching-the-customer-on-a-different-channel).
And when the call ends it can send one more, the same message every time, for
answered calls, missed calls or both. See [After the call](/agent/after-the-call).

## When Answer calls is off

A number you still own should not leave a customer wondering. When **Answer
calls** is off, or the phone is not switched on as a place the agent answers,
what the caller hears depends on the number's provider:

| The number is with | The caller hears |
| - | - |
| Plivo | A spoken sentence, then the call ends: your own message if you wrote one and it is in English, otherwise "Sorry, this number is not taking calls right now. Please try again later." |
| Twilio | The same, and your message can be in English or Hindi. |
| Vobiz | No message of yours. The call is declined as it always was. |
| Telnyx | A busy tone. Telnyx numbers cannot play a message from us. |
| WhatsApp calling | The call is rejected. WhatsApp has no way to speak to the caller. |

**Message when it is off**, on the Voice page under Answer calls, is your
sentence for the Plivo and Twilio rows — up to 300 characters, for example "We are closed
today and open again at 9 am tomorrow." Leave it blank to keep the standard
one. Via the API it is `voice.unavailableMessage` (send `null` to clear it).

* It is read aloud by the phone provider's own voice, not by your agent's, so
  only text that voice can read is spoken. English, or English written in Roman
  letters ("Hum kal subah 9 baje khulenge"), is read in an Indian-English voice
  on Plivo and Twilio numbers. Hindi in Devanagari is read only on Twilio. A
  message in any other script (Tamil, Bengali and so on), or Hindi on a Plivo
  number, plays the standard sentence instead. We keep what you wrote and
  tell you beside the field, and in the API as `voice.unavailableMessageNote`.
* It is only for a line you switched off. A call that cannot be taken for any other
  reason — the plan, the balance, every line busy — always hears the standard
  sentence, so that a caller can never learn anything about your account by
  dialling.
* Line breaks and other control characters become spaces, invisible marks are
  removed (the joiners inside a Hindi conjunct are kept), and a message over
  300 characters is refused instead of cut short.

## Things worth knowing before you go live

<AccordionGroup>
  <Accordion title="It will not answer if you have not told it to">
    Both switches matter. **Answer calls** off, or **Answer calls** on with no
    surface switched on, means the agent does not pick up — you have not told it
    to, or not told it where. What a caller hears then depends on the number's
    provider; see [When Answer calls is off](#when-answer-calls-is-off).
  </Accordion>

  <Accordion title="A long call ends itself">
    Calls have a ceiling. A call that runs unusually long — usually a line left
    open by accident rather than a customer with a lot to say — winds down and
    ends rather than running indefinitely.
  </Accordion>

  <Accordion title="It says when it does not know">
    The same rule as every other channel: an agent that does not know something
    says so and offers to have a person follow up. On a call this matters more,
    because a caller cannot scroll back and check what they were told.
  </Accordion>

  <Accordion title="Test with the hardest question you get">
    Not "what are your hours". Ring your own number and ask the thing your staff
    dread — the awkward one, the one with a condition attached, the one where
    the honest answer is "it depends". That is the answer worth hearing out
    loud before a customer does.
  </Accordion>
</AccordionGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.