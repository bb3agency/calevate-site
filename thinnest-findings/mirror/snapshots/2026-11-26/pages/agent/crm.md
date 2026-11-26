> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# CRM

> Your agent finds the caller in your HubSpot and writes what it learns into their contact.

Someone rings. The agent looks them up in your CRM by their number, answers from
what you already hold, and writes each new answer into their contact as it
arrives — so a call that ends after two questions still leaves those two answers
behind.

It works on every channel: website chat, WhatsApp, Telegram and phone calls.

Three CRMs can be connected, each its own tile under **Actions → CRM**:
**HubSpot**, **Zoho CRM** and **Zoho Bigin**. This page walks through HubSpot;
the Zoho tiles work the same way, except that you choose a module (usually
Leads or Contacts) and the agent can fill any writable field of it.

> [!NOTE]
>
> This is not the same as **Lead capture**, which stores names and numbers in your
> inbox here. This puts them in **your** CRM, where your team already works. You
> can have both on, and when you do the agent records the details in both places
> rather than choosing between them.

## Connecting HubSpot

Go to **Actions**, find **CRM**, and click **HubSpot**.

**1. Sign in to HubSpot**

You are sent to HubSpot's own page to approve the connection, then brought
back. There is no key to copy.

**2. Choose Contacts**

Click **Find modules** and **Use** Contacts. We read your contact properties
— HubSpot's own and every one you created — and remember them.

**3. Pick the properties the agent fills**

A HubSpot contact has a couple of hundred properties, most of them HubSpot's
own tracking. We start you with the useful ones — name, email, phone,
company, job title, city, lead status and the like — plus every property you
created yourself. Tick or untick, then **Save**. Up to forty.

Read-only and calculated properties are never listed: the agent could not
write them anyway.

**4. Choose what the agent may do**

Everything starts **off**. Connecting HubSpot on its own gives the agent
nothing.

## What the agent may do

| Switch | What happens |
| - | - |
| **Save or update the contact** | Writes what the agent learned into the properties you picked — one contact per conversation, filled in as the call goes |
| **Look someone up** | Finds a contact by phone, email or another picked property, so the agent can answer from what you hold. Reads only |

### Updating the contact you already have

Under **Update an existing record**, pick the property that identifies a person
— usually **Phone Number** or **Email**. When a caller matches it, their answers
go into that contact instead of a new one.

Compare it as a **phone number** and `+91 98018 05137`, `919801805137` and
`9801805137` all count as the same person. On a phone call, the number the call
came from is used when the caller does not say one.

HubSpot keeps one contact per email address. If the agent is about to create a
contact whose email is already in HubSpot, it updates that contact instead.

### When to save

**During the call** writes each answer as it arrives. **After the call** reads
the whole conversation once it ends and writes everything in one go — no pause
mid-call. After-the-call saving is for phone calls; chat and WhatsApp keep
saving as they go, since nothing there ends the way a call does.

### Filling from campaign variables

On a calling campaign the agent may already know things nobody says out loud —
the number it dialled, the lead's name. One per line, `property=variable`, for
example `phone=mobile_no`, fills that property from the campaign.

## Things worth knowing

**Dropdowns take only their own options.** If the caller's answer is not one of
the property's options, the agent is told what the options are rather than
writing something HubSpot would refuse.

**Dates are written as dates.** A date property only takes a real date; an
answer like "next Tuesday" is not saved into it, and the agent is told so.

**Add a property in HubSpot, then find modules again** and use Contacts once
more. Your earlier ticks are kept.

**Disconnecting leaves your contacts alone**, and removes our access to your
HubSpot account.

## If it stops working

The tile says **Last call failed** and the card shows what HubSpot said. Usually
access was removed on HubSpot's side — click **Connect again**. Your properties
and switches are remembered.

## Deliberately not included

The agent works with **contacts only**. It does not create deals, companies,
tickets or tasks, and it cannot delete anything.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.