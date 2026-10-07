> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Actions

> Letting the agent do things, not only say them — safely.

An agent that can only talk is a search box with manners. Actions let it look up
an order, check stock, or start something in your own systems.

**The tools we wrote arrive on; anything that reaches outside your business
arrives off.** Knowledge search, lead capture and escalation are what people set
an agent up for, so making you go and find three switches would be a checklist
before the thing works at all. Web search, your own API and every connected
service start off, because those are reachable from a public chat by a stranger
who may be trying to talk the model into using them — and that is a decision
worth making one at a time.

## Built-in tools

Switchable per agent. Off means the tool is **removed**, not that the model is
asked not to use it.

* **Knowledge search** — your own material, always searched first. **Two
  switches**: one for chat and WhatsApp, one for calls. Both on.
* **Web search** — runs on the model provider's side, so it is only available on
  models that offer it.
* **Capture lead** — see [Leads](/agent/leads).
* **Escalate** — hand the conversation to a person. See [Escalation](/agent/escalation).
* **End the call** — on calls only. The agent hangs up once the conversation is
  genuinely finished. See [Voice](/channels/voice#ending-the-call).
* **Book a call back** — somebody asks to be called later and the agent books
  it; your number rings them at that time. See
  [Voice](/channels/voice#booking-a-call-back).

## Booking into your own calendar

Different from **Book a call back** above, and worth keeping straight: that has
your number ring the customer, this puts a real meeting in your diary at a time
you were genuinely free.

Connect Cal.com and the agent can read your availability, offer real times, and
book — with Cal.com sending the confirmation. Twelve switches, all starting off.
See [Calendar](/agent/calendar).

## Filling in your own spreadsheet

The agent takes a caller's details and writes them into a row of your spreadsheet
as it goes, and can look somebody up in the same table to answer from what you
already hold. Connect your own Grist account; two switches, both starting off.
See [Spreadsheet](/agent/spreadsheet).

<Note>
  **Your calendar and spreadsheet switches share one budget: eight on at once.**
  An agent given too many tools gets worse at choosing between them, so we stop
  you at eight rather than let it quietly degrade.
</Note>

## Reaching the customer on a different channel

A caller needs a link sent to them. A customer on WhatsApp would rather be
phoned. These are the tools for that, and they have their own block on the
Actions page because they share something the others do not: each one reaches
the customer **outside** the conversation the agent is in.

**All three start off**, and two of them cost money each time. Turning one on is
not quite enough on its own — each also needs something only you can give it, and
the row says so when it is missing.

| Tool | You turn it on, and it needs | What it does |
| - | - | - |
| **Ring the customer now** | a number that can dial out, and the customer inside your calling hours | Rings that customer straight away on a number we are allowed to use, and tells them it is coming |
| **Send the customer a WhatsApp** | an approved **utility** template | Sends that template to the customer, blanks filled — never free text, and never while the agent is already on WhatsApp with them |
| **Reply to the customer by email** | a connected helpdesk that can send — Zendesk today | Replies on that customer's existing email thread. See [Helpdesk](/workspace/helpdesk) |

<Note>
  **"Ring the customer now" is not the same switch as "Book a call back".** One
  is a customer asking to be rung later; the other is the agent ringing them
  while it is already talking to them somewhere else. You can have either, both,
  or neither.
</Note>

<Note>
  **The agent never chooses the destination.** It cannot be told "email this to
  another address" or "call this number instead" — there is no such thing to
  say. The number or address is resolved from your records at the moment of
  sending, from the same evidence that
  [links a person across channels](/concepts#how-two-channels-become-one-person).
  So the worst a visitor can talk the agent into is contacting the right person
  at the wrong moment.
</Note>

A few consequences worth expecting:

* **A WhatsApp template costs money**, the same as any other template send. The
  agent may send **two an hour in one conversation**, so a customer who keeps
  asking — or tries to make it loop — cannot run up your bill.
* **Emails are capped the same way**, at three an hour in one conversation.
  Enough for the invoice and the corrected invoice, not enough to flood an inbox.
* **The agent will refuse in words** when it has no usable number or address —
  it says so and carries on helping, rather than pretending it sent something.

## Call your own API

Point the agent at an HTTPS endpoint of yours, describe what it does and what it
takes, and the agent can call it mid-conversation. **[Full guide, including how
to write the endpoint safely](/agent/custom-api).**

* Credentials are encrypted at rest and are not readable from the dashboard.
* The URL is validated **and DNS-resolved** before we fetch it, so an endpoint
  cannot be used to reach inside our network.
* Your header secret is never shown again after you save it.

## Connect a service (MCP)

21 services with addresses read from the official registry and grouped by what
they do, plus any address you want to paste. A further 1,434 services are listed
in the directory.

Sign-in happens in a popup and tokens are sealed and renewed automatically, so
nobody signs in twice.

<Warning>
  **Asana, Xero and Shopify need a manual step.** Those vendors do not support
  dynamic client registration, so connecting them currently means registering an
  app on their side yourself. It works; it is not one-click, and we would rather
  say so here than have you discover it mid-setup.
</Warning>

## Send what happens somewhere else

Signed outbound webhooks to any HTTPS endpoint. This is the lane that reaches
Google Sheets, Zoho and effectively any CRM through Zapier or Make today. Paste
an address — or an email address, if your helpdesk opens tickets that way — and
pick what it should be told about.

| Event | Fires when |
| - | - |
| A lead was captured | The agent collected a name, email or phone from somebody interested |
| A conversation was escalated | It handed a conversation to a person |
| A conversation was resolved | A teammate marked one done |
| **A call finished** | Any call placed or answered — with the outcome, how long it lasted, and which campaign it belonged to |
| **A call's results are ready** | After a call ends and has been read — its summary, the details it collected, the transcript and a recording link ([shape](/api-reference/get-call)) |
| **A campaign finished** | Everybody on a broadcast or [calling campaign](/channels/voice-campaigns) has been reached or given up on |

A finished call carries whether it was answered, missed or refused, so a missed
call is something your own system can act on rather than something you find out
by opening ours. Want what was *said* as well? Tick **A call's results are
ready** — it arrives a few seconds later, once the summary and details are
written. See [Call leads from your CRM](/guides/leads-from-your-crm).

Every delivery is signed with a secret shown once when you add the endpoint, so
your receiver can prove the request came from us. An endpoint that fails five
times in a row is switched off and says so, rather than retrying into a wall.

<Note>
  **New events do not arrive uninvited.** An endpoint added before an event
  existed keeps receiving exactly what it did before. Tick the new one when you
  are ready for it — a receiver built for leads should not be woken by a phone
  call it has never seen the shape of.
</Note>

## Two limits worth knowing

**Eight tools per agent.** Every tool's schema is re-sent on every turn, and
models get measurably worse at choosing as the list grows. The cap is a quality
decision, not a licensing one.

**Every discovered tool arrives off.** Enabling is one deliberate act per tool.
A newly connected service does not silently gain the agent thirty new
capabilities.

## Name protection

Third-party tools are namespaced, so nothing you connect can register itself as your own knowledge search and quietly take over your own material.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.