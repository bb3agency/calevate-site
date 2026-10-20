> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Calendar

> Your agent reads your real availability and books meetings into your Cal.com.

Someone asks when you are free. The agent reads your actual calendar, offers two
or three real times, takes their name and email, and books it. Cal.com sends the
confirmation itself.

It works on every channel — website chat, WhatsApp, Telegram and phone calls.

<Note>
  This is not the same as **Book a call back**. That has your number ring the
  customer at a time they chose. This puts a meeting in your diary at a time you
  were actually free. You can have both on; they do not know about each other.
</Note>

## Connecting your calendar

You need a Cal.com account. Go to **Actions**, find **Calendar**, and click
**Cal.com**.

<Steps>
  <Step title="Get an API key from Cal.com">
    In Cal.com, open **Settings → Developer → API keys** and create one.

    It must be a **live** key — one beginning `cal_live_`. Cal.com also issues
    test keys, which begin `cal_` and work perfectly against a separate test
    world, so a booking made with one never reaches the calendar you are looking
    at. We refuse those rather than let you find out from an empty diary.

    Leave the expiry off unless you have a reason to set one — a key that
    expires will stop your agent booking, and the first sign is usually a
    customer who could not get a slot.
  </Step>

  <Step title="Paste it in">
    We call Cal.com once to check the key works and to read back which account
    it belongs to. If it does not work you are told immediately, rather than
    finding out from a missed meeting.
  </Step>

  <Step title="Choose what the agent may do">
    Everything starts **off**. Connecting your calendar on its own gives the
    agent nothing.
  </Step>
</Steps>

## Choosing what it can do

Twelve things, each its own switch. **An agent can have eight on at once** —
past that it gets worse at picking the right one, so we stop you rather than let
it quietly degrade.

That eight is shared with anything else the agent connects, so a
[spreadsheet](/agent/spreadsheet) switch and a calendar switch come out of the
same budget.

### What a customer can ask for

| Switch | What happens |
| - | - |
| **See what can be booked** | Reads your meeting types — a 15-minute intro, a demo — so the agent offers real ones instead of inventing them |
| **Check when you are free** | Reads your genuinely open slots and offers a couple of them |
| **Hold a slot while you talk** | Reserves the time for a few minutes so nobody else takes it while the customer is still spelling their email |
| **Book the meeting** | Puts a real booking in your Cal.com. Cal.com emails the confirmation |
| **Find their existing booking** | Looks up what this customer already has, by their email |
| **Move a booking** | Reschedules to a time they picked |
| **Cancel a booking** | Cancels it, with the reason they gave |

Most people want the first four. Add **Find** before **Move** or **Cancel** —
those two need it, because it is where the agent gets the booking to act on.

### Acting as you

Five more decide something on your behalf: accepting or declining a booking that
is waiting on you, marking a no-show, and reading your working hours or time off.

**Three of these need Find their existing booking turned on as well** —
accepting, declining and marking a no-show all act on a specific booking, and
Find is the only thing that can identify one.

Marking a no-show needs one more thing: the person's email address. Cal.com
identifies an attendee by email and by nothing else, so without one the agent
cannot say who failed to turn up.

<Warning>
  **Leave these off unless the agent only ever talks to your own staff.** A phone
  call has no login, so the agent cannot tell you from a caller who has worked out
  what to say. It is asked to refuse strangers, but the reliable protection is the
  switch being off.
</Warning>

## What your customer experiences

> **Them:** Can I get a demo this week?
> **Agent:** Let me check the diary. I have Tuesday at 11, or Thursday at 3.
> **Them:** Thursday.
> **Agent:** Can I take your name and email?

Then a Cal.com confirmation lands in their inbox, exactly as if they had used
your booking page.

The agent will **not** invent a time. If nothing is free it says so and offers to
look at another week, rather than promising a slot you do not have.

## Things worth knowing

**It always asks for an email.** Cal.com will accept a booking without one; we
will not. A booking with no email gets no confirmation and cannot be found again
if the customer rings back to change it.

<Warning>
  **Testing in the Playground books for real.** The Playground runs your actual
  agent, not a simulation — so if you ask it to book you a demo, a real meeting
  appears in your Cal.com and a real confirmation email goes out. Cancel it the
  same way, or leave these switches off until you are ready.
</Warning>

**Times are read in your calendar's timezone**, unless the customer says where
they are — then it converts.

**Hidden meeting types are never offered.** If you took something off your public
booking page, the agent will not offer it either.

**Disconnecting leaves your bookings alone.** They are your customers'
appointments, not ours to cancel.

## If it stops working

The card says **Needs attention** and shows what Cal.com said.

Almost always the key expired or was revoked. Create a new one in Cal.com and use
**Replace key** — your switches are remembered, so you do not have to set them up
again.

## Deliberately not included

The agent cannot **create, change or delete your meeting types**. It can book
into them, and that is all. Nobody phoning your business has a good reason to
reshape what your business offers, and the safest way to guarantee that is not to
give the agent the ability at all.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.