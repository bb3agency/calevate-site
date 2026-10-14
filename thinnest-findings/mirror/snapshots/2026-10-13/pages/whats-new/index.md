> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# What's New

> The latest changes to ThinnestAI, newest first: October 6 to 13, 2026.

This is what changed in ThinnestAI, in plain words, with a link to the page that
explains each thing. Earlier changes are on [Early October](/whats-new/early-october)
and [Late September](/whats-new/late-september).

<Update label="Oct 13, 2026" description="Warm and cold hand-offs; Actions, Voice and Playground, redesigned" tags={["New", "Improved", "Fixed"]}>
  **New**

  * **Bring your own language model and voice together.** A new set for bring your own
    keys: your LLM account answers and your voice account speaks, while we keep the
    speech recogniser. A call is a flat ₹1 a minute, as with all three keys, on any
    model your key offers. Choose **My voice and my language model** in **Settings →
    Your keys**, or `scope: "llm_voice"` on the API.
    [Bring your own keys](/api-reference/bring-your-own-keys)
  * **Each agent chooses how it uses your keys.** The scope you pick for the
    workspace is the default; an agent can follow it, be switched off your keys, or
    use a different set your saved keys allow, so one agent can run on your language
    model while another uses your language model and your voice. In the console it
    is **How Agent uses your keys** on the agent's pages; in the API, the agent's
    `byok` is `null` (follow the workspace), `"off"`, or a scope, and a scope your
    keys cannot serve is refused with the missing key named.
    [Bring your own keys](/api-reference/bring-your-own-keys)
  * **Tokens used on every call.** Get Call and the `call.analysed` webhook now carry
    `usage`: the `inputTokens`, `outputTokens` and `cachedInputTokens` the call's
    replies used, including on your own model key, each null when not recorded.
    [Get Call](/api-reference/calls/get-call)
  * **Warm or cold, when a call is handed on.** Each agent a call can be handed to
    is **warm** (it gets a short summary and the conversation, and opens by saying
    who it is and why the caller is there) or **cold** (it starts fresh and greets
    the caller as on a new call). [Voice](/channels/voice#handing-a-call-on)
  * **Warm transfers to a person.** With **Call transfer**, the person who answers
    can first hear a short spoken summary of the call before the caller is
    connected, and with **Press 1 to accept** the caller is connected only once
    they press 1, so a voicemail never takes the call. Cold, as before, stays the
    default. [Escalation](/agent/escalation#on-a-phone-call-putting-the-caller-through)
  * **In the API**, `handOver.transferMode`, `handOver.acceptKey` and each hand-off
    agent's `mode`; `handedTo` on calls now says each hand-off's `mode` and `summary`.
    [Update Built-in Tools](/api-reference/tools/update-built-in-tools)

  **Improved**

  * **The Actions page is in three tabs.** **Built in**, **On calls** and **Connect a
    service**, with the open tab kept in the address. A line under the title shows
    how many tools are on, how many services are connected and how many agents calls
    can be handed to, and a tool that is on but missing something it needs shows an
    amber **Not in use yet**. [Actions](/agent/actions)
  * **The Voice page is in seven sections.** Calls, How Agent speaks, Listening, Sound
    and recording, Ending calls, Memory, and Call length and silence, with links
    along the top, **Save changes** always in view, and **Test a call** staying
    in view beside the settings on a wide screen (first, above them, on a narrower one). [Voice](/channels/voice)
  * **The Playground is in four cards.** Language and model, Voice, What Agent says,
    and Reply length. The page used to say changes save immediately; they apply
    once you press **Save changes**. [Behaviour](/agent/behaviour)
  * **More room inside an agent.** The workspace sidebar shrinks to icons while you
    are inside an agent, next to the agent's own menu. Open it any time with the
    toggle; the sidebar on every other page stays as you left it.
  * **Zoho CRM and Zoho Bigin sit side by side** under a **CRM** heading, like
    Calendar and Spreadsheet, instead of stretching across the page.
  * **Labels name the agent** where they said "it": **How Agent should speak**,
    **What Agent says**, **Message when Agent is off**.

  **Fixed**

  * **The "How Agent should speak" box on the Voice page scrolls** once it is tall,
    as it was always meant to. It had grown to show every rule at once.
</Update>

<Update label="Oct 12, 2026" description="Calls that read better, an own-voice tuning panel, safer do-not-call" tags={["New", "Improved", "Fixed"]}>
  **New**

  * **Bring only your own language model.** Use your own LLM account, such as Gemini
    or OpenAI, while we keep the speech recogniser and the voice. Calls stay on the
    same per-minute voice plan as any other call (Standard, Premium or Studio), whatever
    model your key runs, and chat replies cost ₹0.02. Choose it in **Settings → Your
    keys**, or with `scope: "llm"` on the API.
    [Bring your own keys](/api-reference/bring-your-own-keys)
  * **Tune your own Cartesia voice for each agent.** Speed, volume, emotion, the
    Sonic model (including `sonic-3.6`) and a pronunciation dictionary can be set
    per agent in the console, through the API and in MCP, and heard in the console
    and the API before you save. [Tune a Cartesia voice](/api-reference/bring-your-own-keys)
  * **The who-is-calling lookup moved to the Actions page.** It is now a card of its
    own there, no longer on the Voice page; nothing about how it works changed.
    [Who-is-calling lookup](/channels/voice#who-is-calling-lookup)
  * **Choose how the agent decides the caller has finished speaking.** `voice.turnDetection`
    (Smart, Timer or Ear) is now on the API next to the silence setting.
    [Voice](/channels/voice)
  * **Switch off the do-not-call tool for an agent.** `voice.recordDoNotCall` and a
    switch on the Voice page. The `contact.opted_out` webhook now carries the words
    the caller used, so you can see why a number was added.
    [Voice](/channels/voice) and [Webhooks](/api-reference/webhooks)
  * **A reply in your customer's language in chat.** With **Match the customer**,
    website chat, WhatsApp, Telegram, the Playground and test chat now answer in the
    language of a message written in an Indian script. Messages typed in English
    letters are left to the agent's judgement. [Reply language](/agent/behaviour#reply-language)

  **Improved**

  * **The agent asks before adding someone to the do-not-call list.** "That's all,
    you can hang up" no longer counts as "do not call me again", and the agent
    quotes the caller's words when it does add a number.
  * **What was never heard is no longer treated as said.** When a caller talks over
    the agent, the agent now knows which part was cut off and the transcript is
    corrected to the part the caller heard where it can be.
    [Voice](/channels/voice)
  * **Stage directions are not read aloud.** Text such as `[pause]` or
    "(waiting for your response)", and a model's visible "thinking", is removed
    before the agent speaks and before it is saved, while ordinary brackets such as
    "(Monday to Friday)" and "\[1]" stay.
  * **Goodbyes in more languages.** Telugu, Tamil, Kannada, Malayalam, Bengali and
    Marathi closings now end a call properly. The short fixed lines the agent
    falls back on ("I am having trouble", a goodbye) are also written in Hindi and
    Telugu; if you hear a wording you would change, tell us.
  * **Gemini on your own key** is asked to think less on a call, for the models
    where Google allows it.
    [Bring your own keys](/api-reference/bring-your-own-keys)

  **Fixed**

  * **A reply that was retried on a backup model no longer runs together.** The same
    sentence could be said, and stored, twice with no space between the pieces.
  * **"I'll take care of that" no longer ends a call** as if it were a goodbye.
</Update>

<Update label="Oct 10-11, 2026" description="Every Voice page setting on the API, a test-chat marker, model call prices" tags={["New", "Improved", "Fixed"]}>
  **New**

  * **Every setting on the Voice page can now be read and changed through the API
    and the MCP server.** Fillers and their timing, how long a pause ends the
    caller's turn, how many words cut the agent off, never interrupt, the
    background sound and its volume, hanging up when the conversation ends,
    asking "are you still there?", ending a call on silence or on a phrase, and
    the call instructions. A read returns every value with its default filled in,
    and a number outside its range is refused with a message instead of being
    moved. [Voice](/channels/voice#the-settings) and
    [Update Agent](/api-reference/agents/update-agent)
  * **Choose where an agent answers calls.** `voice.surfaces` sets phone, your
    website's call button and WhatsApp calls. Adding the phone to an agent that
    answers calls but has no number is refused with the code
    `phone_number_required`. [Where it answers](/channels/voice#turn-it-on) and
    [Errors](/api-reference/errors)
  * **Your endpoint can tell a test chat from a real customer.** Every action
    request made during an API test chat carries an `X-Test-Chat: true` header, and
    `{{test.chat}}` fills as `true`, so you can answer without writing anything to
    your system. [During a test chat](/agent/custom-api#during-a-test-chat)
  * **Each model shows what a call on it costs.** `GET /models` now returns
    `callTier`, `callPricePerMinuteMicro` and `currency` (the currency of the
    wallet your calls are charged to). A model marked premium puts every call on the
    premium rate. A workspace using its own keys is billed the BYOK rate whatever
    the model. [Model](/agent/behaviour#model)
  * **Your own cloned voices on Cartesia.** The voice list starts with the voices
    you cloned and then reads the whole library, and a clone can be set on an
    agent. [Choose an agent's voice](/api-reference/bring-your-own-keys#choose-an-agents-voice)

  **Improved**

  * **Agent instructions can be 20,000 characters in the console too.** The box
    used to stop at 8,000 while the API accepted more. Conversation steps are limited
    separately. [Instructions](/agent/behaviour#instructions)

  * **A forwarded call on a number with no agent** appears in Usage, Get Call and
    the call list with no agent, and does not create an inbox conversation or a
    webhook. [Forwarding a whole line](/channels/phone-numbers#forwarding-a-whole-line)
    **Fixed**

  * **Studio voices need the Pro plan or above,** not Scale as one guide said.
    [How your agent sounds](/guides/how-your-agent-sounds)

  * **A cloned Cartesia voice that was missing from the list,** and so was refused
    when you set it on an agent, is listed and accepted.
    [Choose an agent's voice](/api-reference/bring-your-own-keys#choose-an-agents-voice)

  * **The background sound's volume now shows what callers actually hear.** The
    Voice page slider and the API report 15% (0.15) when you have not set one; the
    page used to show 18%. [Background sound](/channels/voice#background-sound)
</Update>

<Update label="Oct 9, 2026" description="Callers by name, call hand-offs, forwarding, contact groups" tags={["New", "Improved", "Fixed"]}>
  **New**

  * **Your agent knows who is calling.** When someone rings from a number saved in
    your Contacts, the agent is told their name and can greet them with it. It is
    also told to confirm who it is talking to before discussing an account, because
    a caller's number can be faked. [Who is calling](/channels/voice#who-is-calling)
  * **Look the caller up in your own system.** Give an agent a web address and we
    ask your system who is calling before the agent answers, so it can open with
    their last order or their plan. You have two seconds to reply, and the request
    is signed so you know it came from us.
    [Who-is-calling lookup](/channels/voice#who-is-calling-lookup)
  * **Hand a call to another of your agents.** Sales can pass a caller to support
    in the middle of a call. It is the same line and the same conversation, and the
    other agent sees everything said so far.
    [Handing a call on](/channels/voice#handing-a-call-on)
  * **Forward a whole phone line.** Choose **Forward calls** in a number's menu
    and every call to it rings a phone of your choice, with no agent speaking. It
    works whether or not an agent answers the number, so use it as a fallback while
    you fix or switch off an agent.
    [Forwarding a whole line](/channels/phone-numbers#forwarding-a-whole-line)
  * **Set how long outbound calls ring.** Between 10 and 60 seconds, for an agent
    on the Voice page or for one call through the API. Calls now stop ringing
    after 30 seconds unless you set it; on some carriers they used to ring longer.
    [How long it rings](/channels/voice#how-long-it-rings)
  * **Move a number between your customers.** If you build on the developer API, a
    number can move between your workspace and your customers' workspaces and keep
    its digits, from the number's menu or the API.
    [Moving a number](/channels/phone-numbers#moving-a-number-to-another-workspace)
  * **See how each call went.** Open a call in Usage to see who it was handed to
    or forwarded to, how long the caller waited for each reply, long silences,
    interruptions and any replies that needed a backup. A new `call.problem` webhook tells you the moment something
    goes wrong on a live call.
    [How a call went](/workspace/usage#how-a-call-went)
  * **Contact groups.** Build named lists of contacts, such as "Wholesale buyers",
    and aim a broadcast or a voice campaign at exactly those people.
    [Groups](/agent/leads#groups)

  **Improved**

  * **Every webhook event has a documented example,** and the ids in webhooks
    always carry their `conv_` or `cmp_` prefix, so a value from a webhook can go
    straight into the API. [Event payloads](/api-reference/webhooks#event-payloads)
  * **An agent that is on a live call cannot be deleted,** so a call is never cut
    off by a clean-up. The API says why in a clear error.
    [Errors](/api-reference/errors)
  * **The Buy tab on Phone Numbers stays visible on a plan that cannot buy,** and
    tells you why, instead of disappearing.
    [Getting a number from us](/channels/phone-numbers#getting-a-number-from-us)

  **Fixed**

  * **A call from your website that never connects now gives up after 45
    seconds** and frees the line, instead of showing "Connecting" forever.
    Reloading the page ends a live call, and the "line busy" message names the
    limit. [A call button in your chat](/channels/voice#a-call-button-in-your-chat)
</Update>

<Update label="Oct 8, 2026" description="One language per agent, per-agent keys, erasure and error codes" tags={["New", "Improved", "Fixed"]}>
  **New**

  * **Pick a language for each agent.** An agent has one language: choose it when
    you create the agent, on the Playground or in Settings, or leave it on **Match
    the customer**. The old "second language" setting is retired. You can also
    rename an agent from the sidebar. [Reply language](/agent/behaviour#reply-language)
  * **Keep one agent off your own keys.** If your workspace brings its own provider
    keys, an individual agent can choose to stay on ours.
    [Bring your own keys](/api-reference/bring-your-own-keys)
  * **Erase a contact, and their recordings go too.** Erasing a contact now also
    removes the recordings of their calls on numbers you brought. On pay-as-you-go,
    you can ask us to exclude your workspace from model training.
    [Data and erasure](/workspace/data-and-erasure)
  * **Say what a switched-off line tells the caller.** When Answer calls is off,
    the caller hears a sentence you wrote, where the phone provider allows it.
    [When Answer calls is off](/channels/voice#when-answer-calls-is-off)
  * **Every API refusal carries a code you can act on.** Branch on `code` rather
    than on the wording of the message. [Errors](/api-reference/errors)
  * **Business details (KYC) for rented Indian numbers, by API.** Submit and
    follow the business details an Indian number needs, without the console.
    [India needs your business verified first](/channels/phone-numbers#india-needs-your-business-verified-first)

  **Improved**

  * **A WhatsApp template you sent looks the same in the inbox as it did to the
    customer,** with its picture, cards and buttons.
    [Inbox](/workspace/inbox)
  * **The agent speaks sooner while it looks something up,** with its own wording
    or a short one of ours, and it no longer says a generic "I see" just before the
    answer. A new setting sets the gap before a second line.
    [Fillers before tool run](/channels/voice#fillers-before-tool-run)
  * **A shorter wait before the agent's first answer on a call.**
    [Voice](/channels/voice)

  **Fixed**

  * **The agent no longer answers its own echo** on calls where the speech
    recogniser used to hear the agent's own voice as the caller.
  * **A caller repeating the agent's words is no longer ignored.** Someone who
    answers "I would like to see the pediatrician" in the agent's own words now
    gets a reply. [Interrupting](/channels/voice#interrupting)
</Update>

<Update label="Oct 7, 2026" description="A full API reference, SDKs, texting the caller, new default voice" tags={["New", "Improved"]}>
  **New**

  * **An API reference with a page for every endpoint.** About 180 operations,
    each with typed fields, cURL, JavaScript and Python examples, a **Try it**
    panel and sample responses. [API reference](/api-reference/introduction)
  * **TypeScript and Python SDKs.** Every operation is a typed method, with
    retries and pagination built in. [SDKs](/api-reference/sdks)
  * **Text the caller.** Your agent can send an SMS during a call, and a WhatsApp
    message or SMS after it ends, through your own SMS provider and sender ID.
    [SMS](/channels/sms), [After the call](/agent/after-the-call) and
    [a worked guide](/guides/text-the-caller)
  * **The MCP server covers the whole console.** An AI assistant such as Claude
    Code or Cursor can now do almost anything you can do in the console, with your
    approval for anything that reaches a customer, including drafting and
    launching campaigns. [MCP tools](/mcp/tools)
  * **Bring only your own voice.** Use your own voice account while we supply
    speech recognition, the model and the phone line, at ₹1.50 a minute. Calls run
    on low-cost models in this mode.
    [Bring your own keys](/api-reference/bring-your-own-keys)
  * **Webhooks are signed with their delivery time** and carry an `evt_` id that
    stays the same across retries. [Delivery](/api-reference/webhooks#delivery)
  * **Failed webhooks are retried, and you can send them again** yourself.
    [Retries](/api-reference/webhooks#retries)

  **Improved**

  * **New agents start on the Premium voice Kavya,** because the standard voices
    sounded robotic on a first call. Change it any time from the voice picker. Calls
    on a new agent are billed at the Premium rate until you do.
    [Voice](/channels/voice#voice)
  * **New agents start on the Prana \[Voice] model.**
    [Model](/agent/behaviour#model)
  * **Replies start sooner after a caller stops speaking,** and the agent is better
    at telling a finished sentence from a pause.
    [Voice](/channels/voice)
  * **The call's cost is on its result in the API.**
    [Get Call](/api-reference/calls/get-call)
</Update>

<Update label="Oct 6, 2026" description="Build on the API, white label on every paid plan" tags={["New", "Improved"]}>
  **New**

  * **Build your own product on ThinnestAI.** Create a workspace for each of your
    customers, reach all of them with one key and a `Thinnest-Workspace` header, and
    receive one webhook for every customer.
    [Customers](/api-reference/customers) and
    [Build a platform](/guides/build-a-platform)
  * **White label on every paid plan.** Resell the console under your own brand and
    domain: 3 clients on Pay As You Go, 20 on Pro and 100 on Scale. Each client has
    its own plan and call lines, and starts on a free trial that you set and pay for.
    A reseller with no domain yet gets a free preview address.
    [White label](/white-label/overview), [Clients](/white-label/clients),
    [Brand and domains](/white-label/brand-and-domains) and
    [Your prices](/white-label/prices)
  * **Each agent picks its own model from your keys,** and a single call can name
    one of your voices. Speechmatics is back among the providers.
    [Bring your own keys](/api-reference/bring-your-own-keys)
</Update>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.