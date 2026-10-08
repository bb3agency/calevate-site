> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# WhatsApp

> The same agent, answering on WhatsApp — plus what Meta's rules mean for you.

WhatsApp is the channel most Indian businesses actually want, and it has rules
that are not ours. This page is mostly about those rules, because they shape
everything you can do.

## Connecting

**Connect WhatsApp**, at the top of the WhatsApp section in the sidebar. Two cards
there, each opening Meta's own signup:

| Card | Choose it when |
| - | - |
| **Apply for a WhatsApp Business Account** | You are new to WhatsApp Business |
| **Connect an account you already have** | You already manage a WhatsApp Business Account in Meta |

You sign in with your Facebook account and choose the number. We never see your
login, and the account stays yours: you can move it to another provider whenever
you want.

### Then add a payment method in Meta

**Your balance here doesn't pay WhatsApp's message fees.** Meta charges those to
the card on your own Meta account; your balance pays only our 10% platform fee
on each message ([how the two bills work](/meta/windows-and-pricing)). Without a
card on your Meta account, WhatsApp won't deliver your templates.

Add one in Meta Business, under **Billing & payments → Payment methods**
([open it](https://business.facebook.com/latest/billing_hub/payment_methods)), in
the business that owns your WhatsApp account. Then tick **I've added it** on
Connect WhatsApp. Step by step, with which cards work:
[Adding a payment method in Meta](/whatsapp/payment-method).

We can't see your Meta payment details, so until you tick it we ask once more
before your first send: on Send, in the inbox's template dialog, and before a
broadcast. Disconnecting and connecting a different account asks again, since
that account needs its own card. If Meta later reports a problem with the card,
the step comes back in red with Meta's own words, even after you've ticked it.

### Finish setting up

After you connect, **Finish setting up WhatsApp** at the top of Connect WhatsApp
lists what's left. Each step is checked against Meta and your workspace, not
just ticked off:

| Step | Done when |
| - | - |
| Add a payment method in Meta | You've added it, and Meta isn't reporting a payment problem |
| Choose an agent to answer | Every number has an agent (not shown if your own software answers) |
| Verify your business with Meta | Meta shows your business as verified |
| Get your display name approved | Meta has approved the name customers see |
| Get a template approved | At least one template is approved |

The list disappears once every step is done.

### Which number to use

**A mobile number with a SIM in it** is the smoothest path. During signup Meta
sends that number a six-digit code by SMS, and you type it into Meta's window
to prove the number is yours — nothing else to do.

**A number from the Phone Numbers page can be verified too, by call rather
than text.** It cannot receive SMS, so that option will never arrive on it —
but Meta's verification call does reach it, including from outside India.

<Warning>
  **Meta's own popup does not reliably honour a Voice/SMS choice** — the two
  options can flash briefly and settle on SMS regardless of which you tapped.
  On a number that cannot take SMS, that leaves you with a number Meta shared
  but never confirmed, showing on **Connect WhatsApp** as **not verified yet**.
</Warning>

That has its own recovery, right there on the row:

<Steps>
  <Step title="Call with the code">
    Bypasses the popup's picker and asks Meta directly for a call — the only
    method that can reach a Phone Numbers page number. **Text the code** sits
    beside it for a number that can take SMS.
  </Step>

  <Step title="Type back what Meta says">
    Type the code into the field beneath the buttons, and the number is
    verified and ready to send and receive.
  </Step>
</Steps>

<Tip>
  **If that same number already has an agent answering calls on it, you may
  not need to type anything.** The agent's own call picks up Meta's
  verification call, reads the code off it, and verifies the number
  automatically — usually within two minutes, with a toast to confirm it. If
  the code cannot be read back reliably, you are told to check the recording
  in your inbox and enter it yourself instead.
</Tip>

Your agent can still answer calls on a Phone Numbers page number while
WhatsApp runs on a separate mobile number, if you would rather keep the two
apart — the two work side by side either way.

Two more things about the number:

* **It cannot already be active on WhatsApp or the WhatsApp Business app.** Delete
  the WhatsApp account on that phone first, or use a different number.
* **Asking for a code again is limited.** After a failed attempt Meta makes you
  wait before requesting another, sometimes an hour. Check the number before you
  start.

### The account is your workspace's; the number belongs to an agent

Your WhatsApp Business Account belongs to your **business**, not to any one
agent — so it is connected once, for the whole workspace, and every agent works
against it.

A **number** is different. It answers for exactly one agent, because a message
arrives at a number and something has to decide which agent replies.

So connecting and assigning are two steps, and the second one is yours to make:

1. Connect your account on **Connect WhatsApp**. The number arrives with no agent.
2. Give it one — from that same page, or from the agent's own **Channels** page.

<Note>
  **A number with no agent still receives.** Messages arrive in your
  [inbox](/workspace/inbox) and wait for a person; nothing answers on its own
  until you have said who should. That is deliberate — an agent replying from a
  number nobody chose it for is worse than a message waiting a few minutes.

  Give the number an agent and **the messages that were waiting become theirs**,
  so nothing from your first day is stranded.
</Note>

<Note>
  Moving a number from one agent to **another** works the other way round: the
  agent that had it loses it, but **conversations already open stay with the
  agent handling them** — nobody mid-conversation is suddenly answered by a
  different agent. New conversations go to the agent that took it.
</Note>

<Tip>
  You can also answer from an unassigned number before you have chosen one: send
  a template from [Send](/whatsapp/send) and pick a **handler**, and that agent
  answers that conversation when the customer writes back.
</Tip>

Several numbers on one account is fine. Connect each one and give each its own
agent.

### Your click-to-chat link

Every connected number has one, on the **Connect WhatsApp** page. It opens a
WhatsApp chat with you, and it needs no integration — put it in an Instagram
bio, behind a button on your site, in an email footer, on a printed sign.

You can set what their message already says. That matters more than it sounds:
an empty chat asks somebody to think of an opening line, which is where most of
them stop. And if you word it differently per place you put the link, the first
thing they send tells you where they came from.

### The same link as a QR code

Underneath the link is a QR code for it, and **Download PNG** saves a
print-quality copy. Point a phone camera at it and it opens the same chat, with
the same message already typed.

It is for the places a link cannot go: a counter card, a menu, a packing slip, a
poster in the window, the back of a business card. The code changes as you edit
the message above it, so download it after you have worded it, not before.

<Tip>
  Give each place its own code with its own opening message — "Table 4",
  "Ordered from the catalogue", "Saw the window poster". The message people send
  you is then also the answer to where they were standing, and you never have to
  ask.
</Tip>

### Disconnecting

**Disconnect** on the Connect WhatsApp page stops a number sending and receiving.
Your WhatsApp Business Account is untouched — it is yours, and disconnecting
here does not close it.

<Note>
  **Your conversations are kept.** Everything that number sent and received stays
  in your inbox and stays searchable. Disconnecting ends the connection, not the
  history.
</Note>

### What customers see when they tap your name

**Business profile** on the Connect WhatsApp page, beside Disconnect. Your picture,
the line under your name, a description, your email, website, address and
business category. It is read from WhatsApp when you open it and written back
when you save, so it is never a stale copy of what your customers actually see.

An empty profile is why some businesses show a blank circle and nothing else.

<Note>
  **Your business NAME is not here.** That is the display name on the number
  itself, WhatsApp reviews it before it appears, and it is set in Meta's
  WhatsApp Manager under *Phone numbers → Display name*. The tagline, picture and
  the rest are yours to change whenever you like.
</Note>

### Your name, and the badge, are two different approvals

Two separate things get conflated because they show up in the same place — the
top of a chat with you.

**Your business name, with no badge**, is the ordinary Display Name above.
Any verified business can have one; it is not gated behind anything else. Once
WhatsApp approves it, it is what every customer sees instead of your number —
most businesses stop there.

**A badge beside the name** — WhatsApp's own equivalent of a "blue tick" — is a
separate, optional step: an **Official Business Account**. WhatsApp grants it at
its own discretion, generally to a business it considers well-known or notable
in its own market, on top of your business already being verified. There is no
published checklist and no guaranteed outcome, and it is applied for from Meta's
WhatsApp Manager on your number's profile — not from here. Most verified
businesses run without one; it changes how your name looks, not whether
messages reach anyone.

### When WhatsApp stops the number sending

WhatsApp can stop an account starting new conversations — most often because the
payment method on your Meta account failed, and sometimes after a run of
complaints. It is quiet when it happens: WhatsApp accepts what you send and
delivers none of it.

The Connect WhatsApp page and the agent's Channels page show the reason in WhatsApp's
own words whenever that is the case, and the workspace is told once when it
starts. Replies inside an open 24-hour window keep working throughout — it is
only conversations you start that stop.

<Note>
  **A failed payment method is fixed in Meta, not here.** Add a working one in
  Meta Business Manager under *Billing & payments*, on the business that owns
  your WhatsApp account. Then open or reload **Connect WhatsApp**: that is when
  we ask Meta for your account's status, and the warning clears there and then.
  Step by step:
  [Adding a payment method in Meta](/whatsapp/payment-method).
</Note>

### Your account at a glance

Beside your numbers, **Connect WhatsApp** lists your WhatsApp account as Meta reports it.
Each row shows its current value; click one to see what it means and what changes it.

* **Messaging limit:** how many people your business can start conversations
  with in any 24 hours, across all your numbers. See [quality and
  limits](/meta/quality-and-limits).
* **Can send messages:** whether WhatsApp is letting the account start
  conversations, with WhatsApp's reason when it isn't.
* **Quality:** your lowest-rated number.
* **Business verification:** whether Meta has verified your business.
* **WhatsApp calling:** whether your account can take WhatsApp calls. That
  needs a limit of 2,000.
* **Marketing Messages API:** whether your account is signed up for it. See
  [Marketing Messages API](#marketing-messages-api) below.

Each number also shows its own display name and whether Meta has approved it,
plus its quality, status and sending speed.

### Two-step verification

Two-step verification protects your number with a 6-digit PIN. Meta asks for it
whenever the number is registered again, and the blue tick needs it on. Click
**Two-step verification** on Connect WhatsApp to see whether it is on and to set a
new PIN. Type it twice. Keep it somewhere safe: ThinnestAI never stores it.

When you put an approved display name live with **Start using**, ThinnestAI has to
set a new PIN and shows it to you once. You can change it here afterwards.

If you get a notice that a security setting changed on your number and nobody at
your business did it, set a new PIN here straight away.

### The blue tick

A blue tick next to your name marks an Official Business Account. Click **Blue tick**
on Connect WhatsApp to see where each number stands. ThinnestAI reads this from Meta
every time the page opens, and shows Meta's five requirements as met or not met:

* the business follows WhatsApp's Business Messaging Policy;
* it has been on the WhatsApp Business Platform for at least 30 days;
* your business is verified with Meta;
* two-step verification is on for the number;
* the number's display name is approved.

If a requirement is missing, the window says which, and from what date if it is
the 30 days. When all are met it shows **Ready to apply**: in WhatsApp Manager open
**Phone numbers**, click your number, then **Profile** → **Official business
account** → **Submit request**. Meta asks for your website, your main country and
language, and up to 5 links to news coverage of your brand. Those links matter most.

Meeting every requirement does not guarantee the tick: Meta reviews each request and
decides. After a refusal you can send another 30 days later.

### Marketing Messages API

Meta's Marketing Messages API is an optional programme that can deliver more of
your marketing templates and report clicks. Once your business is on it,
ThinnestAI sends your marketing templates through it automatically; nothing
about how you send changes.

Click **Marketing Messages API** on Connect WhatsApp to see where you stand:

* **On:** your business has accepted Meta's terms. Nothing to do.
* **Request sent:** Meta has asked your business to accept. An admin accepts it in
  Meta Business Suite, under Settings → Requests.
* **Not set up:** choose **Set up**. Meta opens in a small window, where an admin of
  your business accepts its terms for this programme. The window closes itself and
  the row updates. Only an owner or admin can do this.

If Meta says your business is not in a country where it is offered yet, there is
nothing to do until it is.

### Changing your display name

Click **Display name** on Connect WhatsApp, type the new name, and choose **Send to
Meta for review**. Meta reviews it, usually within a few days. The row shows the
review, and you get a notification when Meta decides.

When Meta approves it, choose **Start using** in the same place. Meta needs this
within 14 days of approving the name, or you send it for review again. Meta allows 10 changes in 30 days, and
[its naming rules](https://www.facebook.com/business/help/757569725593362) decide
what is accepted.

If your number also runs on the WhatsApp Business app, change the name in the app.

## The WhatsApp Dashboard

**Dashboard**, under Connect WhatsApp in the sidebar, shows what your numbers did over
the last **24 hours**, **7 days** or **30 days** — or any days you pick with
**Pick dates**. Choose a first and last day, up to a year apart, then **Apply**.
Days run midnight to midnight in your workspace's time zone, and a single day is
shown hour by hour:

Each figure has a small chart of its trend. When the view is by day, a badge shows
how the last 7 days compare with the 7 before.

* **Messages sent:** sent by your agent or your team. Internal notes are not
  counted.
* **Delivered**, **read** and **not delivered:** each as a share of what was sent.
* **Messages received:** messages your customers sent.
* **Cost:** what WhatsApp messages cost you, the same figure as on **Usage**.
* **A chart of sent and received messages:** by hour for 24 hours, by day
  otherwise, in your workspace's time zone.
* **What you sent, by type:** marketing, utility, one-time codes and
  replies, each with its cost.
* **The most common reasons messages were not delivered:** WhatsApp's words,
  then what they mean.

<Note>
  Delivery receipts are recorded from 30 September 2026. Messages sent before
  then show as **no receipt from WhatsApp**, not as undelivered.
</Note>

## Before a number is connected

Templates, Forms and Send are **read-only** until one is. You can read what is
there, and the pre-built template and form libraries, but nothing can be
written, submitted or sent — all three end at Meta, and until an account is
connected there is nothing to send them to.

## The 24-hour window

This is the single rule to understand. [Meta's rules](/meta/overview) covers it
and the rest in depth.

* When a customer messages you, a **24-hour window** opens. Inside it, the agent
  can reply freely, in its own words.
* Outside it, **nothing but an approved template** reaches that customer.

So the agent handles conversations; [templates](/whatsapp/templates) handle
anything you start.

**You can see the window on the conversation itself.** Open it in the
[inbox](/workspace/inbox): while the window is open, a line above the reply box
counts down what is left — *Free replies and forms open · 14h 22m left*. In the
last hour it turns amber. When it runs out, the reply box is replaced by a note
saying so. A customer who has never written to you has no window at all, and the
thread says that instead.

## What the agent does here

The same knowledge, instructions and tools as your website widget. Cards and
buttons render as native WhatsApp messages rather than degrading to text.

Delivery and read receipts arrive afterwards and show in the inbox — sent,
delivered, read and failed are four different facts, each with Meta's own
reason where one applies.

## Free entry point

When a customer arrives from a **click-to-WhatsApp ad** and you reply within 24
hours, Meta does not charge for that conversation for 72 hours. The platform
tracks this and it shows in your usage.

## Opting out

A customer can turn off "Offers and announcements" in WhatsApp itself, or simply
tell your agent to stop. Either way they are recorded as withdrawn and marketing
templates to them are refused.

Utility and authentication messages still reach them, and must — an order
confirmation is not something anybody opted out of.

## Calls

A customer's WhatsApp call appears in the thread with its outcome and duration.

<Warning>
  **No AI answers the call.** Calls are recorded as events in the conversation,
  nothing more. Anyone telling you this platform answers your phone is
  describing something that does not exist.
</Warning>

## Not built

* **Catalogues.** Inbound order messages parse, but there is no catalogue
  browsing.
* **Publishing a form** before Meta has verified your business. Forms build,
  store and preview now; Meta will not publish a flow for an unverified
  business, and an unpublished form reaches nobody.
* **One-time password templates**, which are behind the same verification gate.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.