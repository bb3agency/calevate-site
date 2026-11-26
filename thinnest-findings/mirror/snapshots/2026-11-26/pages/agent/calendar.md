> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Calendar

> Your agent reads your real availability and books meetings into your Cal.com or Calendly.

Someone asks when you are free. The agent reads your actual calendar, offers two
or three real times, takes their name and email, and books it. Your calendar
sends the confirmation itself.

Two calendars are supported: **Cal.com**, connected with an API key, and
**Calendly**, connected by signing in to Calendly. Most of this page is about
Cal.com; [Calendly](#calendly) has its own section below.

It works on every channel — website chat, WhatsApp, Telegram and phone calls.

> [!NOTE]
>
> This is not the same as **Book a call back**. That has your number ring the
> customer at a time they chose. This puts a meeting in your diary at a time you
> were actually free. You can have both on; they do not know about each other.

## Connecting your calendar

You need a Cal.com account. Go to **Actions**, find **Calendar**, and click
**Cal.com**.

**1. Get an API key from Cal.com**

In Cal.com, open **Settings → Developer → API keys** and create one.

It must be a **live** key — one beginning `cal_live_`. Cal.com also issues
test keys, which begin `cal_` and work perfectly against a separate test
world, so a booking made with one never reaches the calendar you are looking
at. We refuse those rather than let you find out from an empty diary.

Leave the expiry off unless you have a reason to set one — a key that
expires will stop your agent booking, and the first sign is usually a
customer who could not get a slot.

**2. Paste it in**

We call Cal.com once to check the key works and to read back which account
it belongs to. If it does not work you are told immediately, rather than
finding out from a missed meeting.

**3. Choose what the agent may do**

Everything starts **off**. Connecting your calendar on its own gives the
agent nothing.

## Choosing what it can do

Twelve things, each its own switch. **Switch on only what the agent needs**: the
fewer it carries, the better it picks the right one.

That eight is shared with anything else the agent connects, so a
[spreadsheet](https://docs.thinnest.ai/agent/spreadsheet.md) switch and a calendar switch come out of the
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

> [!WARNING]
>
> **Leave these off unless the agent only ever talks to your own staff.** A phone
> call has no login, so the agent cannot tell you from a caller who has worked out
> what to say. It is asked to refuse strangers, but the reliable protection is the
> switch being off.

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

> [!WARNING]
>
> **Testing in the Playground books for real.** The Playground runs your actual
> agent, not a simulation — so if you ask it to book you a demo, a real meeting
> appears in your Cal.com and a real confirmation email goes out. Cancel it the
> same way, or leave these switches off until you are ready.

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

## Calendly

Go to **Actions**, find **Calendar**, and click **Calendly**.

**1. Sign in to Calendly**

You are sent to Calendly's own page to approve the connection, then brought
back. There is no key to copy, and we never see your Calendly password.

**2. Pick the meeting types**

Click **Find meeting types**. We read the active meeting types on your
account. Tick the ones the agent may book, then **Save meeting types**.

The agent offers only these, by name. Nothing is attached until at least
one is picked.

**3. Choose what the agent may do**

Everything starts **off**, the same as Cal.com.

| Switch | What happens |
| - | - |
| **Check when you are free** | Reads your real open times for a meeting type you picked, a week at a time, and offers a couple of them |
| **Book the meeting** | Books the time the customer chose straight into your Calendly. Calendly emails the confirmation |
| **Send a booking link** | Makes a one-time link to your booking page for a meeting type, so the customer picks a time themselves |

### Booking directly needs a paid Calendly plan

Calendly only lets other apps book a meeting directly on its paid plans
(Standard and above). On a free plan, **Book the meeting** does not fail — it
makes a one-time booking link for the customer instead, and the agent tells them
the meeting is **not** booked until they use it.

The link is also used, on any plan, when a meeting type needs something only
your booking page can collect: required questions you added in Calendly, or a
location the customer has to type in. The card marks those types when you pick
them.

### Sending the link

In a chat — website, WhatsApp, Telegram — the agent gives the link in its reply.

On a phone call it does not read a link out. If the agent can send WhatsApp or
SMS messages, it sends the link that way; if it cannot, it offers to take the
customer's details instead. Turn on **Send a WhatsApp** or **Send an SMS** under
the agent's built-in tools if you want links to reach callers.

### Things worth knowing about Calendly

**It always asks for an email**, as with Cal.com — Calendly needs one for the
confirmation.

**The agent will not invent a time.** It offers only times Calendly returned. If
the customer picks one that has just been taken, the agent checks again and
offers another.

**Times are read in your Calendly account's timezone**, unless the customer says
where they are.

**Disconnecting leaves your bookings alone**, and also removes our access to
your Calendly account.

If the card says **Needs attention**, access was usually removed on Calendly's
side. Click **Connect again** — your meeting types and switches are remembered.

## Deliberately not included

The agent cannot **create, change or delete your meeting types**, in Cal.com
or Calendly. It can book
into them, and that is all. Nobody phoning your business has a good reason to
reshape what your business offers, and the safest way to guarantee that is not to
give the agent the ability at all.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.