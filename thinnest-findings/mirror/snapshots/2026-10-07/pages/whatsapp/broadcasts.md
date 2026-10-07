> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Broadcasts

> One approved template, to everybody who agreed to hear from you.

**Broadcasts** in the sidebar sends an approved
[template](/whatsapp/templates) to an audience computed **at send time from
consent** — never from a list somebody exported last week.

<Note>
  The WhatsApp Business App calls this a broadcast too, and caps it at 256
  contacts, reaches only people who saved your number, and gives you no
  scheduling, no personalisation and no delivery reports. This is the same job
  without any of that: no cap beyond [Meta's own messaging
  tier](/meta/overview), no requirement that anybody saved you, and you can see
  what arrived.
</Note>

## It belongs to the workspace, not to an agent

A broadcast is sent from your WhatsApp number, using a template that belongs to
your WhatsApp Business Account, to your workspace's contacts. None of those is
one agent's, so neither is the list: **every broadcast appears here**, whichever
agent answers it.

<Note>
  **Looking for calling campaigns?** They are **Voice Campaigns** in the main
  sidebar, listed the same way this page lists broadcasts. The difference is
  what you choose when you build one: a call goes out from a particular agent's
  number and is opened in its own words, so the builder asks which agent does
  the calling. See [Calling campaigns](/channels/voice-campaigns).
</Note>

## Before you can send

In this order: WhatsApp connected, an approved template, and contacts who have
consented. Each screen in the chain says what the next one needs, and the
**Send broadcast** button says which one is missing before you start rather than
after you have filled the form in.

## How marketing broadcasts are sent

A broadcast on a **marketing** template goes out through Meta's **Marketing
Messages API**, which Meta optimises for delivery. Meta reports up to 9% more
marketing messages delivered in India than the standard API, for messages people
engage with. There's nothing to switch on: if your account isn't eligible yet,
Meta sends it the standard way instead. The price is the same.

WhatsApp still limits how many marketing messages each person receives, on
every platform. If some aren't delivered, see
[When a message isn't delivered](/whatsapp/not-delivered).

## Writing one

**New broadcast** opens a page, not a dialog — five decisions with a live
preview of what arrives between them:

<Steps>
  <Step title="Name it">
    For you, not the customer. Nobody receiving it sees this.
  </Step>

  <Step title="Choose who it goes to">
    See below — the lists overlap, and the page says which one it settles on.
  </Step>

  <Step title="Pick an approved template">
    Only approved ones appear. Meta refuses anything else at the moment of
    sending, so an unapproved template is not an option you can pick and regret.
  </Step>

  <Step title="Fill the blanks">
    Each one takes a contact field or a fixed value. The preview updates as you
    type, so you read the message a real recipient gets rather than a row of
    braces.
  </Step>

  <Step title="Say when">
    Now, or a time. Scheduling needs nothing left open — see **Sending** below.
  </Step>
</Steps>

The page does not scroll. The two side columns do, and the preview between them
stays put, because it is the thing you are checking the other two against.

<Tip>
  **From a template you just got approved**, press **Send broadcast** on its card
  on the [Templates](/whatsapp/templates) page. It opens this page with that
  template already chosen.
</Tip>

## Who answers the replies

A broadcast produces conversations — people reply to it. **Who answers the
replies** on the send form picks the agent that handles them, and defaults to
the one your number already answers on.

It is a real choice rather than a formality: you may want a different agent on a
sale than on a delivery notice. Replies land in your [inbox](/workspace/inbox)
whichever you pick, so nothing is lost if you change your mind afterwards — only
who drafts the first answer.

## Choosing an audience

<Warning>
  **A broadcast only reaches people who opted in.** That is WhatsApp's rule, not
  ours: Meta allows a business to message someone only if they gave you their
  number **and** agreed to hear from you. Contacts who never opted in are left
  out of every broadcast, whichever list you choose.
</Warning>

Three lists, each showing its count **before** you commit:

| Audience | Who |
| - | - |
| Imported contacts | Contacts from a spreadsheet you uploaded, whose opt-in you confirmed when uploading |
| Opted in on WhatsApp | Opted in, and reached you via WhatsApp |
| Everyone who opted in | Everyone who opted in, however they arrived |

You can tick more than one. The lists overlap — everybody who opted in on
WhatsApp is also in *Everyone who opted in* — so ticking two sends to *Everyone
who opted in*, and the page says so and shows that count as soon as you pick a
second list.

## Getting people opted in

Consent is collected out in the world — on your website, a form, at your counter,
in a shop, over the phone — as long as what they agreed to names your business
and says you will message them on WhatsApp. What the console does is **record**
it. There are four ways, and they all write the same thing: the answer, the date,
and where it came from.

| | How |
| - | - |
| **A customer agrees in the conversation** | Automatic. Your agent records it when somebody says yes, in their own words, and records the opposite when they say stop. |
| **Importing a spreadsheet** | Tick *These people agreed to hear from us* on the import. Only tick it if they did. |
| **People already in your contacts** | The **Contacts** page says how many have not been asked, with a **Record consent** button beside it. |
| **From your own system** | Our [Contacts API](/api-reference/contacts/create-contact) takes a consent status and source with each contact, so a CRM or billing system can keep it in step. |

<Warning>
  **If your contacts show as not asked, broadcasts reach nobody.** Importing a
  spreadsheet without ticking the box is the usual reason: the contacts save
  fine, and every broadcast and sequence then leaves them out, because WhatsApp
  only allows marketing to people who agreed. The banner on **Contacts** is
  there to say so before you build an audience and find it empty.
</Warning>

### Recording it for people already in your contacts

An admin can record consent for everyone nobody has asked yet, in one go. You
confirm that they agreed and say how — in writing, in person or by phone, or on
your website — and that answer is stored beside each contact with today's date.
It is what you would show WhatsApp if they ever ask, so it is worth being
accurate about.

It never touches anybody who opted out. Somebody who replied STOP stays opted
out, and no bulk action can undo that.

<Note>
  Contacts with no phone number are left alone too — a WhatsApp consent needs a
  WhatsApp number to apply to — and so are the people your agent spoke to, who
  live on [Leads](/agent/leads) and arrived by a different promise.
</Note>

Consent is enforced in the database. There is exactly one way an audience gets
built, and it is not the interface — so a bug in a screen cannot message
somebody who did not opt in, or who opted out.

### The do-not-contact list

Separate from consent, and it applies to broadcasts as well as calls.

Consent is about a customer you already have: they replied STOP, or they never
opted in. The **do-not-contact list** is a list of *numbers* — the file you get
from a regulator, a complaint, a lawyer's letter, or the CRM you used before.
Most of those numbers are not in your contacts at all, so there is nothing to
set a consent flag on.

Add them on the **Contacts** page, with the **Do not contact** button at the top — paste them or upload
a file. Nothing on that list is ever messaged or called again, on any channel.

**Finding the numbers to add.** Filter your contacts by what happened to their last
WhatsApp message (for example *Failed* or *Not delivered*), then choose **Export
CSV**. You get exactly the people that filter shows, every page of them, with a
**Do not contact** column saying who is on the list already. The file opens in
Excel and Google Sheets, including names written in Telugu, Hindi or any other
script. Only owners and admins can export.

<Note>
  It is checked **at the moment each message is sent**, not when the audience was
  built. So a list you upload at eleven stops a broadcast that is already part
  way through. It also survives an import: bringing in a spreadsheet that happens
  to contain one of those numbers updates the contact, but it does not take the
  number off the list. Only removing it does that, and that needs an admin.
</Note>

### Narrowing by tag

Tags filter *within* the list you chose — they never reach past it. Picking two
tags means **either**, not both.

The exact number after tagging is worked out when the broadcast sends, against
consent as it stands then, so the summary shows the list's own size and says the
tags will narrow it. That is deliberate: somebody who withdraws consent between
your writing it and its going out is not messaged.

## Variables

Each blank binds to a contact field or one fixed string. A template with a
placeholder cannot go out with it empty.

<Note>
  **You cannot edit the message here**, and that is not an omission. Meta
  approved a specific wording; changing it means submitting a new template and
  waiting for review. What is yours per-send is what goes in the blanks, which
  is what this asks for.
</Note>

## Retargeting and split tests

Both optional, both at the foot of the form.

<ParamField path="Only people from an earlier broadcast" type="broadcast + outcome">
  Sends only to people who did something — or nothing — with a broadcast that
  has already gone out. *Did not reply* is the usual one and usually the one
  worth sending.

  Both halves or neither: an earlier broadcast **and** what those people did.
  Half-filled, it would quietly mean everybody, so the page refuses it.
</ParamField>

<ParamField path="Test a second template against it" type="template">
  Splits the audience in half by a hash of the contact, so the two sides never
  overlap and nobody gets both. It makes **two broadcasts**, named (A) and (B),
  which you compare on the list.

  Press **Send broadcast** and both go out. Press **Save as draft** and you get
  two drafts to start when you are ready.
</ParamField>

## Sending

<Warning>
  **A send started from the console runs from your browser, so that tab must stay
  open to finish.** It is the same client-driven loop the site crawl uses.

  A **scheduled** send has no tab and does not need one — it runs on our side.
  It also picks up any broadcast a closed tab left half-sent.
</Warning>

Sends are resumable. Each recipient is its own row, so a crash or a closed tab
**pauses** rather than loses, and nobody is messaged twice.

## Watching it

The broadcast's own page shows the message as sent, every recipient with their
state, the refusal reasons grouped, and a timeline.

**On the Contacts page**, every contact shows what became of their last WhatsApp
campaign message, and the menu above the list filters by it — the same states,
plus *Never messaged*. The filter stays in the address, so a page, a reload or a
shared link keeps it.

**On a broadcast's own page, filter its list by what happened** — the menu above
it, beside the search:
Delivered, Read, Replied, Not delivered, Failed, Not contacted, Sent with no
receipt yet, and Waiting, each with how many are in it. "Delivered" includes the
people who went on to read or reply. It combines with the search, so you can
look for one person among the undelivered.

**Export CSV**, beside the search, downloads exactly the people that filter
shows, every page of them. Each row has the name, the number, the status, the
reason where there is one, and when the message was sent, delivered, read and
replied to, on your workspace's clock. A calling campaign also gets how each
call ended, the talk time and the number of dials. The file opens in Excel and
Google Sheets, including names written in Telugu, Hindi or any other script.
Only owners and admins can export.

**Sent, delivered, read and refused are four different facts**, each carrying
Meta's own reason where one applies. "Sent" means WhatsApp accepted it — not
that it arrived.

## Cost

The summary beside the form shows the per-message rate and what the audience
would cost at it, **before** you send. It is an estimate and it lands high
rather than low: Meta charges per *delivered* message, so anything that does not
deliver is not charged.

See [Windows and what gets charged](/meta/windows-and-pricing).
Marketing templates are charged by Meta on **every** send, unlike replies inside
the 24-hour window.

A **utility** broadcast is different: any recipient who is still inside their
own 24-hour window receives it free. So the same broadcast can cost less than
its estimate, and the [usage](/workspace/usage) breakdown is what tells you
which sends were actually charged.

Calling campaigns are priced separately — see [Calling
campaigns](/channels/voice-campaigns).

Both appear line by line in [Usage](/workspace/usage), where you can also open
any call from a calling campaign and read what was said.

## What is not built

<Warning>
  * **Broadcasting on any other channel.** A broadcast is WhatsApp. Instagram and
    Messenger cannot carry marketing outside the 24-hour window at all — Meta
    forbids promotional content there explicitly — Telegram does not send one yet,
    and website chat never will: a broadcast reaches somebody who is not there.
  * **Sending to people who never opted in.** Not a missing feature — buying a
    list and messaging it is the fastest way to lose a WhatsApp number.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.