> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Leads and contacts

> Ending the conversation with somebody to call, not just a closed ticket.

A support bot answers a question and the visitor leaves. This one answers the
question **and** leaves you a name and a reason to call.

## How a lead gets captured

When a visitor shows real interest, the agent asks for their details in the flow
of the conversation and records:

* name
* email
* phone
* **a one-line note on what they actually wanted**

That last field is the one that matters. "Priya, kitchen quote, 12ft run,
budget around ₹4L" is a callback worth making. A bare phone number is not.

## Partial details are still a lead

A phone number on its own is recorded. Later turns add to the same record rather
than starting a new one, so a customer who gives their name first and their
number three messages later ends up as one contact.

## Switching it off

Per agent. Off removes the capability entirely — the agent has no way to ask
rather than being asked not to.

Worth turning off for a pure support agent, where asking for contact details
reads as a sales tactic and annoys people.

## Contacts

Everyone who has spoken to an agent, **leads first**, with what they asked for.
One click goes from a contact to the conversation that produced them, so
whoever calls back can read what was actually said.

## Contact language

Each contact can carry a language. Where a WhatsApp template exists in several
languages, the contact's language decides which one they receive.

<Note>
  A contact with no language set gets exactly what they would have got before —
  your default. Setting the field is an improvement, never a prerequisite.
</Note>

## Consent

Contacts carry a marketing consent state, and it is enforced in the database
rather than in the interface. A campaign audience is computed at send time from
consent — never from a list somebody exported last week.

Somebody who opts out stops receiving **marketing**. Utility and authentication
messages still reach them, and must: an order confirmation is not something
anybody opted out of.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.