> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Leads and contacts

> Ending the conversation with somebody to call, not just a closed ticket.

A support bot answers a question and the visitor leaves. This one answers the
question **and** leaves you a name and a reason to call.

> [!NOTE]
>
> **Leads** has two tabs. **Inbound leads** is this page: people who came to your
> agents. **Find leads** goes the other way — your agent finds
> businesses you want to reach. See [Find leads](https://docs.thinnest.ai/agent/find-leads.md).

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

## Groups

A group is a named list of contacts you put together yourself — "Wholesale
buyers", "Pune walk-ins" — so you can send a broadcast or run a voice campaign to
exactly those people.

**1. Create the group**

On **Contacts**, choose **New group** and name it. Names are unique in your
workspace, whatever the capitals.

**2. Add people**

Tick contacts in the list (the box at the top ticks everyone on the page),
then **Add to group** and pick the group. Somebody already in it is left as
they are. A contact can be in any number of groups.

**3. Open it**

Each group is a chip above the list with how many people are in it. Open one
to see only its members; tick people there and **Remove from** the group to
take them out.

The **⋯** beside an open group renames or deletes it. Deleting a group never
deletes its contacts.

A group decides *who you are aiming at*, never *who agreed*. Consent still
applies to everybody in it — see
[narrowing by group](https://docs.thinnest.ai/whatsapp/broadcasts.md#narrowing-by-tag-or-group).

## Contact language

Each contact can carry a language. Where a WhatsApp template exists in several
languages, the contact's language decides which one they receive.

> [!NOTE]
>
> A contact with no language set gets exactly what they would have got before —
> your default. Setting the field is an improvement, never a prerequisite.

## Consent

Contacts carry a marketing consent state, and it is enforced in the database
rather than in the interface. A campaign audience is computed at send time from
consent — never from a list somebody exported last week.

Businesses you found with [Find leads](https://docs.thinnest.ai/agent/find-leads.md) have not opted in, and
saving them asks you to confirm that contacting them is your responsibility. They
are the one exception to the opt-in rule for WhatsApp broadcasts; calls and
everything else here still apply, and anyone who says stop is never contacted again.

Somebody who opts out stops receiving **marketing**. Utility and authentication
messages still reach them, and must: an order confirmation is not something
anybody opted out of.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.