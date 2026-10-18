> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Helpdesk

> Escalations as tickets in Zendesk or Salesforce, with replies coming back.

If your team already lives in a helpdesk, escalations can arrive there as
tickets — and replies typed there reach the customer on the channel they wrote
from.

## Two-way, on WhatsApp

Connect Zendesk or Salesforce and an escalated conversation opens a ticket with
the transcript. When an agent replies in the helpdesk, that reply is delivered
to the customer on WhatsApp.

The customer never learns your helpdesk exists. They asked on WhatsApp; they get
an answer on WhatsApp.

## Connecting

On the agent's **Channels** page, open **Reply from your helpdesk** and connect
the vendor. Credentials are sealed and are not readable from the dashboard.

## Which vendors

| Vendor | Tickets | Replies come back |
| - | - | - |
| **Zendesk** | Yes | Yes |
| **Salesforce** | Yes | Yes |

<Note>
  Ticket numbering differs by vendor and can repeat across accounts, so tickets
  are keyed by connection as well as by number. Two workspaces with the same
  ticket number never cross.
</Note>

## Salesforce specifics

Salesforce caps a comment at 4,000 **bytes**, not characters — so a long
transcript in a non-Latin script is trimmed on a byte boundary rather than
rejected outright.

## What reaches the ticket

The conversation transcript at the point of escalation, plus a tag identifying
the conversation so replies route back to the right thread.

Internal notes are not included: those are your team's, and a helpdesk ticket is
a different audience.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.