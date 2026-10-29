> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Early October 2026

> What changed in ThinnestAI from October 1 to 5, 2026.

These are earlier changes. The newest are on [What's New](https://docs.thinnest.ai/whats-new.md), and the
weeks before this are on [Late September](https://docs.thinnest.ai/whats-new/late-september.md).

**Oct 5, 2026**

The MCP server, Telnyx numbers, WhatsApp carousels

**New**

* **Run your workspace from Claude Code, Cursor or VS Code.** ThinnestAI is now an
  MCP server: an AI assistant can work with your agents, actions, contacts, calls
  and analytics. Anything that would reach a customer waits for your approval, and
  a test chat contacts nobody. There is a new **MCP** tab in these docs.
  [MCP overview](https://docs.thinnest.ai/mcp/overview.md) and [Connect](https://docs.thinnest.ai/mcp/connect.md)
* **Choose what each API key can do.** Full access, Build or Read-only, and the
  same level applies to the MCP server. [Authentication](https://docs.thinnest.ai/api-reference/authentication.md)
* **Run the inbox and campaigns from the API or an assistant.** Resolve,
  hand back, take over and assign conversations, pause or cancel a campaign, see
  WhatsApp cost by category, send a test webhook and read its delivery history.
  [MCP tools](https://docs.thinnest.ai/mcp/tools.md)
* **See what an assistant did.** A list of the latest changes an AI assistant
  made in your workspace, with reads and test chats left out.
  [MCP tools](https://docs.thinnest.ai/mcp/tools.md)
* **Import Telnyx numbers.** Bring a number you already own on Telnyx, and your
  agent can answer it, detect voicemail and transfer calls.
  [Numbers from Telnyx](https://docs.thinnest.ai/channels/phone-numbers.md#numbers-from-telnyx)
* **Finish setting up WhatsApp.** A checklist on Connect WhatsApp shows what is
  left, and the payment step turns red if Meta blocks the account.
  [Finish setting up](https://docs.thinnest.ai/channels/whatsapp#finish-setting-up)

**Improved**

* **WhatsApp carousels are easier to get approved.** End the message with STOP,
  put buttons on the cards, and keep each card to 160 characters. The form checks
  all of it as you type. [Carousels](https://docs.thinnest.ai/whatsapp/templates.md#carousels)
* **A transfer on a line you brought no longer costs you our per-minute charge.**
  [Phone numbers](https://docs.thinnest.ai/channels/phone-numbers.md)
* **Erasing a contact also deletes recordings of their calls** on numbers you
  brought. [Data and erasure](https://docs.thinnest.ai/workspace/data-and-erasure.md)

**Oct 4, 2026**

Several phone companies for one agent, quiet calls end

**New**

* **One agent can call out from numbers with different phone companies.** Each
  call dials, hangs up and transfers through its own number's provider.
  [Spare numbers for calling out](https://docs.thinnest.ai/channels/phone-numbers.md#spare-numbers-for-calling-out)
* **Test calls from the Playground can ring any country,** and the card is laid
  out as **Call from** and **Call to**. [Voice](https://docs.thinnest.ai/channels/voice.md)

**Improved**

* **A call where nobody speaks for five minutes is ended,** instead of holding
  the line open. An agent with no "end after" set now hangs up when its last
  "are you still there?" goes unanswered.
  [Ending the call](https://docs.thinnest.ai/channels/voice.md#ending-the-call)
* **Connecting your own WhatsApp account tells you that Meta bills your card,**
  not the balance here, before the first send.
  [Add a payment method in Meta](https://docs.thinnest.ai/whatsapp/payment-method.md)

**Oct 3, 2026**

Twilio numbers, separate inbound and outbound, better inbox search

**New**

* **Import Twilio numbers.** Connect your Twilio account and we set the number
  up there for you. Importing replaces what the number was set to before, so a
  number that already runs a menu or a forwarding rule loses it, and the page
  tells you before you do it.
  [Using a number you already own](https://docs.thinnest.ai/channels/phone-numbers.md#using-a-number-you-already-own)
* **Inbound and outbound are chosen separately for each number.** They can be
  different agents, and either can be empty. An agent that only calls out needs
  no number of its own.
  [Inbound and outbound are separate](https://docs.thinnest.ai/channels/phone-numbers.md#inbound-and-outbound-are-separate)
* **Export who a broadcast reached.** Download every recipient's status as a CSV.
  [Broadcasts](https://docs.thinnest.ai/whatsapp/broadcasts.md)
* **See who WhatsApp's marketing limit applies to.** Contacts and the Inbox show
  **Marketing paused until** for anyone WhatsApp is holding marketing messages
  for. [Not delivered](https://docs.thinnest.ai/whatsapp/not-delivered.md)

**Improved**

* **Inbox search finds every conversation,** not only the ones already loaded,
  and looks inside every message. Filters also look through all conversations.
  [Finding a conversation](https://docs.thinnest.ai/workspace/inbox.md#finding-a-conversation)
* **Carousel link buttons send,** and button labels can be up to 25 characters.
  [Buttons](https://docs.thinnest.ai/whatsapp/templates.md#buttons)

**Fixed**

* **Calls out from an imported number on another phone company now connect.**
  [Phone numbers](https://docs.thinnest.ai/channels/phone-numbers.md)

**Oct 2, 2026**

WhatsApp Dashboard, blue tick, Marketing Messages

**New**

* **A WhatsApp Dashboard** with a date range and campaign-style tiles, and
  account cards on Connect WhatsApp.
  [The WhatsApp Dashboard](https://docs.thinnest.ai/channels/whatsapp#the-whatsapp-dashboard)
* **See your blue tick status.** Connect WhatsApp shows whether each number is
  eligible, with Meta's five checks.
  [The blue tick](https://docs.thinnest.ai/channels/whatsapp#the-blue-tick)
* **Set up Marketing Messages, two-step verification and display-name changes
  from the platform.** [Marketing Messages API](https://docs.thinnest.ai/channels/whatsapp#marketing-messages-api)
* **Filter Contacts by what became of their last message,** and export the
  filtered list to CSV. [Contacts](https://docs.thinnest.ai/agent/leads.md)

**Improved**

* **The daily limit is explained.** WhatsApp's limit counts different people you
  start conversations with in a rolling 24 hours, across the whole business. The
  Calls window states the real figure.
  [Quality and limits](https://docs.thinnest.ai/meta/quality-and-limits.md)
* **"Connect Your CRM" is now "Connect External Agent/CRM",** so the name says
  what it does. [External agents](https://docs.thinnest.ai/whatsapp/external-agents.md)

**Oct 1, 2026**

WhatsApp calls, one-time codes, delivery reasons

**New**

* **Customers can call you from WhatsApp and your agent answers.** One switch on
  Connect WhatsApp controls it. [WhatsApp calling](https://docs.thinnest.ai/whatsapp/calls.md)
* **Save and submit a one-time-code template in one step,** and open a window
  with the code to paste into your website in cURL, Node.js, Python or PHP.
  [One-time codes](https://docs.thinnest.ai/whatsapp/one-time-codes.md)

**Changed**

* **Your agent's replies inside the 24-hour window are charged from October 1,**
  and so are utility templates sent while a window is open, at the utility rate
  for the country. Messages your customers send you stay free.
  [In-window messages](https://docs.thinnest.ai/meta/windows-and-pricing.md#in-window-messages-become-chargeable-on-1-october-2026)

**Improved**

* **A message that was not delivered says why,** in WhatsApp's words first and
  ours second. [When a message isn't delivered](https://docs.thinnest.ai/whatsapp/not-delivered.md)
* **Marketing broadcasts go through Meta's marketing API,** at the same price,
  with nothing to switch on. [Broadcasts](https://docs.thinnest.ai/whatsapp/broadcasts.md#how-marketing-broadcasts-are-sent)
* **The email test goes to every address** and says "accepted" rather than
  "delivered", because that is all we can know.
  [Notifications](https://docs.thinnest.ai/workspace/notifications.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.