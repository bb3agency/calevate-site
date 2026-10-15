> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Early October 2026

> What changed in ThinnestAI from October 1 to 5, 2026.

These are earlier changes. The newest are on [What's New](/whats-new), and the
weeks before this are on [Late September](/whats-new/late-september).

<Update label="Oct 5, 2026" description="The MCP server, Telnyx numbers, WhatsApp carousels" tags={["New", "Improved"]}>
  **New**

  * **Run your workspace from Claude Code, Cursor or VS Code.** ThinnestAI is now an
    MCP server: an AI assistant can work with your agents, actions, contacts, calls
    and analytics. Anything that would reach a customer waits for your approval, and
    a test chat contacts nobody. There is a new **MCP** tab in these docs.
    [MCP overview](/mcp/overview) and [Connect](/mcp/connect)
  * **Choose what each API key can do.** Full access, Build or Read-only, and the
    same level applies to the MCP server. [Authentication](/api-reference/authentication)
  * **Run the inbox and campaigns from the API or an assistant.** Resolve,
    hand back, take over and assign conversations, pause or cancel a campaign, see
    WhatsApp cost by category, send a test webhook and read its delivery history.
    [MCP tools](/mcp/tools)
  * **See what an assistant did.** A list of the latest changes an AI assistant
    made in your workspace, with reads and test chats left out.
    [MCP tools](/mcp/tools)
  * **Import Telnyx numbers.** Bring a number you already own on Telnyx, and your
    agent can answer it, detect voicemail and transfer calls.
    [Numbers from Telnyx](/channels/phone-numbers#numbers-from-telnyx)
  * **Finish setting up WhatsApp.** A checklist on Connect WhatsApp shows what is
    left, and the payment step turns red if Meta blocks the account.
    [Finish setting up](/channels/whatsapp#finish-setting-up)

  **Improved**

  * **WhatsApp carousels are easier to get approved.** End the message with STOP,
    put buttons on the cards, and keep each card to 160 characters. The form checks
    all of it as you type. [Carousels](/whatsapp/templates#carousels)
  * **A transfer on a line you brought no longer costs you our per-minute charge.**
    [Phone numbers](/channels/phone-numbers)
  * **Erasing a contact also deletes recordings of their calls** on numbers you
    brought. [Data and erasure](/workspace/data-and-erasure)
</Update>

<Update label="Oct 4, 2026" description="Several phone companies for one agent, quiet calls end" tags={["New", "Improved"]}>
  **New**

  * **One agent can call out from numbers with different phone companies.** Each
    call dials, hangs up and transfers through its own number's provider.
    [Spare numbers for calling out](/channels/phone-numbers#spare-numbers-for-calling-out)
  * **Test calls from the Playground can ring any country,** and the card is laid
    out as **Call from** and **Call to**. [Voice](/channels/voice)

  **Improved**

  * **A call where nobody speaks for five minutes is ended,** instead of holding
    the line open. An agent with no "end after" set now hangs up when its last
    "are you still there?" goes unanswered.
    [Ending the call](/channels/voice#ending-the-call)
  * **Connecting your own WhatsApp account tells you that Meta bills your card,**
    not the balance here, before the first send.
    [Add a payment method in Meta](/whatsapp/payment-method)
</Update>

<Update label="Oct 3, 2026" description="Twilio numbers, separate inbound and outbound, better inbox search" tags={["New", "Improved", "Fixed"]}>
  **New**

  * **Import Twilio numbers.** Connect your Twilio account and we set the number
    up there for you. Importing replaces what the number was set to before, so a
    number that already runs a menu or a forwarding rule loses it, and the page
    tells you before you do it.
    [Using a number you already own](/channels/phone-numbers#using-a-number-you-already-own)
  * **Inbound and outbound are chosen separately for each number.** They can be
    different agents, and either can be empty. An agent that only calls out needs
    no number of its own.
    [Inbound and outbound are separate](/channels/phone-numbers#inbound-and-outbound-are-separate)
  * **Export who a broadcast reached.** Download every recipient's status as a CSV.
    [Broadcasts](/whatsapp/broadcasts)
  * **See who WhatsApp's marketing limit applies to.** Contacts and the Inbox show
    **Marketing paused until** for anyone WhatsApp is holding marketing messages
    for. [Not delivered](/whatsapp/not-delivered)

  **Improved**

  * **Inbox search finds every conversation,** not only the ones already loaded,
    and looks inside every message. Filters also look through all conversations.
    [Finding a conversation](/workspace/inbox#finding-a-conversation)
  * **Carousel link buttons send,** and button labels can be up to 25 characters.
    [Buttons](/whatsapp/templates#buttons)

  **Fixed**

  * **Calls out from an imported number on another phone company now connect.**
    [Phone numbers](/channels/phone-numbers)
</Update>

<Update label="Oct 2, 2026" description="WhatsApp Dashboard, blue tick, Marketing Messages" tags={["New", "Improved"]}>
  **New**

  * **A WhatsApp Dashboard** with a date range and campaign-style tiles, and
    account cards on Connect WhatsApp.
    [The WhatsApp Dashboard](/channels/whatsapp#the-whatsapp-dashboard)
  * **See your blue tick status.** Connect WhatsApp shows whether each number is
    eligible, with Meta's five checks.
    [The blue tick](/channels/whatsapp#the-blue-tick)
  * **Set up Marketing Messages, two-step verification and display-name changes
    from the platform.** [Marketing Messages API](/channels/whatsapp#marketing-messages-api)
  * **Filter Contacts by what became of their last message,** and export the
    filtered list to CSV. [Contacts](/agent/leads)

  **Improved**

  * **The daily limit is explained.** WhatsApp's limit counts different people you
    start conversations with in a rolling 24 hours, across the whole business. The
    Calls window states the real figure.
    [Quality and limits](/meta/quality-and-limits)
  * **"Connect Your CRM" is now "Connect External Agent/CRM",** so the name says
    what it does. [External agents](/whatsapp/external-agents)
</Update>

<Update label="Oct 1, 2026" description="WhatsApp calls, one-time codes, delivery reasons" tags={["New", "Improved"]}>
  **New**

  * **Customers can call you from WhatsApp and your agent answers.** One switch on
    Connect WhatsApp controls it. [WhatsApp calling](/whatsapp/calls)
  * **Save and submit a one-time-code template in one step,** and open a window
    with the code to paste into your website in cURL, Node.js, Python or PHP.
    [One-time codes](/whatsapp/one-time-codes)

  **Changed**

  * **Your agent's replies inside the 24-hour window are charged from October 1,**
    and so are utility templates sent while a window is open, at the utility rate
    for the country. Messages your customers send you stay free.
    [In-window messages](/meta/windows-and-pricing#in-window-messages-become-chargeable-on-1-october-2026)

  **Improved**

  * **A message that was not delivered says why,** in WhatsApp's words first and
    ours second. [When a message isn't delivered](/whatsapp/not-delivered)
  * **Marketing broadcasts go through Meta's marketing API,** at the same price,
    with nothing to switch on. [Broadcasts](/whatsapp/broadcasts#how-marketing-broadcasts-are-sent)
  * **The email test goes to every address** and says "accepted" rather than
    "delivered", because that is all we can know.
    [Notifications](/workspace/notifications)
</Update>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.