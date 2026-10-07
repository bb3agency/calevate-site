> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Templates

> The only thing that reaches a customer outside the 24-hour window.

Outside the [24-hour window](/meta/windows-and-pricing) WhatsApp carries nothing
but an **approved template**.
Everything you start — a campaign, an order update, a reminder — is a template.

Once one is approved you can put it in a [broadcast](/whatsapp/broadcasts), fire it
from the [API](/api-reference/messages/send-message), or
[send it to a few numbers by hand](/whatsapp/send).

## The three categories

| Category | For | Charged | Reaches an opted-out customer |
| - | - | - | - |
| **Marketing** | Offers, announcements, re-engagement | Every send | No |
| **Utility** | Order confirmations, delivery updates, receipts | Every send | Yes, and must |
| **Authentication** | One-time passwords | Every send | Yes |

Getting the category wrong is the most expensive mistake here. A marketing
template refused for opted-out contacts is correct behaviour, not a bug.

## Already have templates? Import them

If you were using WhatsApp before you came here, your approved templates are
still on your WhatsApp Business Account — and **Import from Meta**, at the top of
the Templates page, brings them in.

They arrive with their wording, their examples, their buttons and their approval
status intact, ready to send. Pressing it again is safe: a template you already
have is refreshed rather than duplicated, which is also how you pick up a status
Meta has changed since.

<Note>
  Only templates on **your own** account are imported. Nothing from anybody
  else's reaches your workspace.
</Note>

## You need a connected number first

Templates are submitted to **your** WhatsApp Business Account, so until one is
connected there is nothing to submit them to. This page is read-only until then
— you can read what is here and browse the pre-built templates, but writing,
submitting, editing and adding a language all wait.

[Connect WhatsApp](/channels/whatsapp#connecting) is the first thing in the WhatsApp
section of the sidebar, and takes a few minutes.

## Writing one

The editor writes the template and submits it to Meta for approval. Approval
typically takes minutes but is Meta's decision, not ours — see [Template review
and approval](/meta/template-review) for what gets rejected and why.

Placeholders are numbered: `{{1}}`, `{{2}}`. Each one is bound at send time to a
contact field or one fixed string — and a template with a placeholder **cannot
go out with it empty**.

<Warning>
  **The header has to be fixed text.** Meta allows a variable there; we do not,
  because nothing in the product can fill it — and a template Meta approves that
  can never be sent is worse than one refused while you are writing it. Put the
  changing part in the body.
</Warning>

<Warning>
  **Authentication templates are copied, not written for you.** Meta writes and
  localises the wording for one-time passwords itself, and rewording it gets the
  template rejected. The editor copies Meta's text exactly.

  Authentication templates are also gated behind business verification.
</Warning>

## Languages and variants

A template name can exist in several languages. When you send, the
[contact's language](/agent/leads#contact-language) decides which variant they
receive.

A contact with no language set receives your default — so adding languages is
always an improvement and never a prerequisite.

<Tip>
  Competitors generally give you one language per template and leave the
  choosing to you. Per-contact variant selection is the difference between
  "we support Hindi" and "your Hindi-speaking customers get Hindi".
</Tip>

## Buttons

Templates can carry quick replies and link buttons. A link button's blank is
sent separately from the body's blanks — Meta wants it in a different component,
and putting it in the body's list breaks both the words and the link.

A button's label can be up to **25 characters** — WhatsApp's limit. The label
box counts as you type (`12/25`) and stops at 25.

## Carousels

A carousel is a message followed by 2 to 10 swipeable cards, each with its own
picture (or video), text and the same buttons. Two things decide whether Meta
accepts one:

* **Each card's picture must be a direct link to the image itself** — one that
  opens just the picture, usually ending in `.jpg` or `.png`. A Google Drive or
  Dropbox share link opens a web page about the file, not the file, so it is
  refused before anything is sent, and the message names the card.
* **Pick the language the text is written in.** A carousel written in Telugu
  should be a Telugu template; Meta reviews the language you choose against the
  words.
* **It must be a Marketing template.** WhatsApp doesn't allow carousels as
  Utility.
* **It has no footer.** WhatsApp allows nothing above the cards except the
  message itself. A marketing carousel still needs a way out, so end the
  message with a line like "Reply STOP to opt out" (in any language, as long as
  it contains the word STOP in capitals), or give the cards a "Stop promotions"
  quick reply.
* **Its buttons go on the cards.** Leave the Buttons section under the message
  empty; a carousel can't have buttons there.
* **Each card's text is up to 160 characters.** The box counts as you type.

All of these are checked when you save, edit and submit, so you find out here, in
plain words, rather than from Meta.

Each card has **one or two buttons**, and every card has the same ones — a quick
reply, a link or a call. A link button can go somewhere different on each card,
but each card's link is a fixed web address: it can't contain a blank like
`{{1}}`, since nothing fills one in when the carousel is sent.

## Sending one

An approved template's card carries **Send broadcast**. It opens the
[broadcast composer](/whatsapp/broadcasts) with that template already chosen, so
the template you just got approved is one click from reaching somebody.

For a single customer rather than a list, use [Send](/whatsapp/send); from your
own systems, [the messages API](/api-reference/messages/send-message).

## Letting an agent send a template

Your agent can send an approved template **during a call or chat** when a
customer asks for something (a renewal link, your address, a documents list). You
decide which templates it may use.

<Steps>
  <Step title="Open an approved Utility template">
    Only **Utility** templates can be sent by an agent. A customer who asked a
    question hasn't agreed to marketing, and Meta treats the two differently.
  </Step>

  <Step title="Tick “Agents may send this during a call or chat”">
    It applies to every language of that template. Untick it to stop.
  </Step>

  <Step title="Switch the tool on for the agent">
    On the agent's **Actions** page, turn on **Send the customer a WhatsApp**. See
    [Actions](/agent/actions#reaching-the-customer-on-a-different-channel).
  </Step>
</Steps>

Two things keep a template out:

* **A blank in a link button.** A button like `yoursite.com/{{1}}` needs a value
  for the blank, and an agent can't fill one. Use a fixed link, and put anything
  that changes in the message text.
* **Not being Utility.** Marketing and authentication templates can't be ticked.

New templates start unticked. Templates you already had when this was added were
ticked for you, apart from any with a blank in a link button.

Each message the agent sends is charged like any other template you send, and the
agent may send two an hour in one conversation.

## Forms

A template button can open a **form** — an address, a booking, a return. That is
how you collect structured information from somebody who has not messaged you
recently.

Answers come back into the conversation and are stored against it, so they are
readable in the inbox and available afterwards as structured data rather than as
words in a transcript.

<Warning>
  **Forms cannot be published until Meta verifies your business.** They build,
  store and preview now; Meta will not publish a flow for an unverified
  business, and an unpublished form reaches nobody.

  Forms also cannot be filled from your data — no slot picker showing only free
  slots, no dropdown of that customer's orders.
</Warning>

## Deleting one

<Note>
  **Deleting an AGENT does not delete your templates.** They belong to your
  WhatsApp Business Account rather than to one agent, so they move to whichever
  of your agents is oldest — along with your forms and your broadcasts. The
  delete dialog lists what will move before you confirm.
</Note>

<Warning>
  **Deleting removes it from Meta too**, not just from this list. Two
  consequences follow, and both are easier to know beforehand:

  * Anything sending that template — a campaign, a sequence, your own code
    calling the API with its name — **stops working**.
  * Meta will **not let the name be used again for 30 days**. If you are
    replacing a template, give the replacement a different name rather than
    waiting a month for the old one.
</Warning>

A draft that was never submitted has neither consequence: Meta has never seen
it, so nothing is using it and the name stays free.

## Template quality

Meta scores every approved template on how people react to it — green, yellow,
red — and tells us when the score changes. **You are warned at yellow**, on the
template and by notification, while there is still something you can do about
it.

Red is not a warning. Meta pauses a red template, and a paused template sends
nothing, so the yellow is the message that matters.

The usual causes are blocks and "report" taps from people who did not expect to
hear from you: a marketing template sent too often, or to a list that never
really opted in.

<Note>
  Your **number** is scored separately, and that one is worse: a flagged number
  has its messaging limit cut, and left flagged it is restricted outright — at
  which point no template works, however healthy. You are warned about that too.
</Note>

<Warning>
  **Per-template delivery analytics are not available yet** — how many people
  opened a given template, or tapped its button. Meta reports button taps in
  WhatsApp Manager and we do not yet read them. What you can see today is
  per-campaign delivery and replies on the [campaign
  report](/whatsapp/broadcasts), and the quality score above.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.