> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# What's New

> The latest changes to ThinnestAI, newest first: October 6 to 27, 2026.

This is what changed in ThinnestAI, in plain words, with a link to the page that
explains each thing. Earlier changes are on [Early October](https://docs.thinnest.ai/whats-new/early-october.md)
and [Late September](https://docs.thinnest.ai/whats-new/late-september.md).

**Oct 27, 2026**

Voices for more languages outside India; the call settings move to the Playground, with one Save for everything; help text in (i) tooltips across the agent pages; several WhatsApp and SMS messages after a call; where the time went in each turn of a call

**New**

* **Voices for more languages.** If your business is billed outside India, the Studio catalogue speaks fifteen
  languages best. For the others, a call now answers in a voice of the same gender from a second set made for them,
  and **Browse voices** lists that set under each of those languages. These voices have no sample to play.
  [Voices for more languages](https://docs.thinnest.ai/channels/voice.md#voices-for-more-languages)
* **Clone a voice in more languages.** Bosnian and Sundanese join the list outside India, and a clone in any language
  outside those fifteen is made with the second set, at the same rate. [Languages](https://docs.thinnest.ai/channels/voice-clone.md#languages)
* **API.** [`GET /voices`](https://docs.thinnest.ai/api-reference/voices/list-voices) lists the second set with `languages`, the languages each is
  offered for, and an empty `accent`.
* **Several messages after a call.** The **After the call** card on an agent's Actions page now sends up to 3 WhatsApp
  templates and up to 3 SMS templates when a call ends, in the order you tick them, each with its own blanks. They go
  out as one set: once per call, never to your do-not-contact list, at most once a day to the same number.
  [After the call](https://docs.thinnest.ai/agent/after-the-call.md)
* **Choose what Agent may send during a call.** A **During the call** card on the Actions page's **On calls** tab holds
  the WhatsApp and SMS switches, with a list to tick the templates Agent may pick from while it talks to a customer.
* **API.** [Update Post-call Settings](https://docs.thinnest.ai/api-reference/post-call/update-post-call-settings.md) takes `followUp.whatsappTemplates`
  and `followUp.smsTemplates`, lists of up to 3. `whatsapp` and `sms` still work and mean the first of the list.
* **Where the time went in each turn.** Open a call in Usage and, under **How the call went**, open **Where the time went
  in each turn**. For every turn it shows when the first word of the actual answer was heard, when the first sound of any
  kind was (a thinking line or an acknowledgement that plays first no longer passes for the answer), how long the turn took
  to be decided, Ear's check, the model's first sentence and the voice. It is recorded for calls made from now on, and not
  for speech-to-speech calls; an older call says nothing was recorded. [Usage](https://docs.thinnest.ai/workspace/usage.md#how-a-call-went)
* **The time to the answer, in the API.** [Get Call](https://docs.thinnest.ai/api-reference/calls/get-call.md) and the `call.completed` and
  `call.analysed` webhooks carry `quality.answerMs`, the wait to the first word of the actual answer (`responseMs` still
  stops at the first sound of any kind), and `quality.knowledgeTurns`, the turns that looked something up in the agent's
  knowledge. [Get Call Timeline](https://docs.thinnest.ai/api-reference/calls/get-call-timeline.md) returns every turn's timing.
* **Knowledge on calls from the API.** [Update Built-in Tools](https://docs.thinnest.ai/api-reference/tools/update-built-in-tools.md) takes
  `knowledgeOnCalls` to switch the agent's knowledge search on or off during calls; chat is not affected.

**Changed**

* **Call settings are on the Playground.** How the agent speaks, listening and turn detection, sound and recording, ending calls, memory, and call length and silence are now cards on the agent's Playground, under the model, voice and instructions. One **Save changes** saves the whole page, and **Test a call** saves any unsaved change before it dials. The **Voice** page keeps whether the agent answers and where. [Where the call settings are](https://docs.thinnest.ai/channels/voice.md#where-the-call-settings-are)
* **Help text in (i) tooltips.** On the agent pages, the grey line that explained a card or a field is now an (i) beside its title. Hover it, tab to it, or tap it on a phone. Warnings, live counts and empty states stay on the page.
* **Send after** on the After the call card is a list you tick: calls somebody answered, missed calls, or both.
* **Save appears only when there is something to save** on the After the call and Hand calls to another agent cards.

**Oct 26, 2026**

One app for every country: sign up at app.thinnest.ai and pick the country your business is billed in

**Changed**

* **One app, one address.** ThinnestAI is now a single app at `app.thinnest.ai` for every country. The sign-up page asks which country your business is billed in: India is billed in rupees, everywhere else in US dollars. The API is at `https://app.thinnest.ai/api/v1` for every workspace. `dashboard.thinnest.ai` now sends you to `app.thinnest.ai`, and its API address keeps working. [Where you are billed](https://docs.thinnest.ai/workspace/regions.md)

**Oct 24, 2026**

Every phone number carries its country code, with a country list in the console; the API refuses a number without one; an international site; resellers paid through their own Dodo Payments account

**Changed**

* **The API refuses a phone number without its country code.** Send every number with its code, like
  `+44 7700 900123` or `+91 98765 43210` (full international digits without the `+` work too). A
  number like `9876543210` used to be read as Indian; it is now refused with a message saying how to
  write it. This covers placing calls, batch calls, contacts, the do-not-call list, WhatsApp messages
  and one-time codes, and importing a phone number. [Phone numbers](https://docs.thinnest.ai/channels/phone-numbers.md#country-codes)
* **A country list beside every number box in the console.** Importing a number, adding or importing
  contacts, the do-not-contact list, a calling campaign's list, sending a WhatsApp message and the
  Playground's test call each have a country list with flags, starting on your workspace's country.
  A number typed without a code takes the country picked there.
  [Phone numbers](https://docs.thinnest.ai/channels/phone-numbers.md#country-codes)

**New**

* **An international site** at `dashboard.thinnest.ai`, with billing in US dollars,
  ten British voices, and WhatsApp priced from Meta's own published rates for every country. Buying a number there is coming soon; bring one you already own. The sign-up and
  log-in pages name the region you are on, with a link to the other. [Regions](https://docs.thinnest.ai/workspace/regions.md)
* **Resellers on the international site are paid through their own Dodo Payments account**, under
  their own business name. A reseller with no payment account has its clients' usage charged to its
  own balance, so a client is never stopped for its own balance. [Your prices](https://docs.thinnest.ai/white-label/prices.md#paid-through-dodo-international)

**Oct 23, 2026**

Speech-to-speech calls with OpenAI GPT-Realtime Mini; speech-to-speech on the Enterprise plan only for now; unused Pro and Scale credit rolls over for up to 3 months; standard voices retired

**New**

* **Speech-to-speech calls with OpenAI GPT-Realtime Mini.** A second model that hears and speaks,
  at a lower rate a minute than GPT-Live-1, with the phone line included (per second on web,
  30-second blocks on phone), on the Enterprise plan. It takes turns: callers can cut in, but it does not
  listen while it speaks. It answers simple things itself and uses your agent's knowledge and
  actions for the rest, and never states a fact your agent has not given it.
  Its ten voices speak every language. Its own call settings, **Realtime session** on the
  Playground, set its noise reduction, how it knows the caller has finished, an idle timeout,
  interruptions, the caller transcript, reply length, speaking speed and what a long call keeps;
  on this model they replace the Voice page's fillers and listening settings.
  Through the API: the model `openai-gpt-realtime-mini`, `voice.realtimeVoice` and
  `voice.realtimeSession`. [Voice](https://docs.thinnest.ai/channels/voice.md#speech-to-speech-openai-gpt-realtime-mini)

**Changed**

* **Speech-to-speech models are on the Enterprise plan only, for now.** OpenAI GPT-Live-1 and
  OpenAI GPT-Realtime Mini have left the Model picker and List Models while they are tested
  further; we set them up on Enterprise agents. An agent already on one keeps it, and its calls
  run and bill as before. Through the API, a realtime model is refused as a new choice with
  "… is not available yet." [Voice](https://docs.thinnest.ai/channels/voice.md#speech-to-speech-openai-gpt-live-1)

* **Unused plan credit rolls over.** The usage credit that Pro and Scale give each period
  used to expire at the end of that period. Now unused credit rolls over for up to 3 months
  while your paid subscription remains active, and each period's credit expires at the end of
  its own 3-month window. A renewal adds the new credit on top of what is left, the oldest
  credit is spent first, and money you topped up is never touched. If you cancel, what is left
  lasts until the end of the period you have paid for. Through the API, `creditExpiresAt` on
  [Get Usage](https://docs.thinnest.ai/api-reference/usage/get-usage.md) is the earliest date any of your credit
  expires. [Usage](https://docs.thinnest.ai/workspace/usage.md#plan-credit)

* **Standard voices are retired.** Every voice call is now billed at the Premium or the Studio
  rate — see Pricing. An agent that spoke with a standard voice has been moved to a similar Premium
  voice automatically. The model no longer changes a call's rate: only a Studio voice (one of ours
  or your own clone) makes a call Studio. The Scale plan pays the same voice rates as every other
  plan. Through the API, [List Models](https://docs.thinnest.ai/api-reference/models/list-models.md) returns `callTier` as
  `premium` for every model, with the Premium price, and
  [List Voices](https://docs.thinnest.ai/api-reference/voices/list-voices.md) lists only `premium` and `studio` voices; `tier`
  is never `standard`. [Voice](https://docs.thinnest.ai/channels/voice.md#voice)

**Oct 22, 2026**

Speech-to-speech calls with OpenAI GPT-Live-1; early answers can be switched off; no limit on the Playground's instructions

**New**

* **Speech-to-speech calls with OpenAI GPT-Live-1.** An agent can answer
  calls with one model that hears and speaks, listens while it talks, and still uses your
  agent's instructions, knowledge and actions. It speaks in its own voices, Indian voices
  first, and is billed at one flat rate a minute with the phone line included (per second on web,
  30-second blocks on phone). On the Enterprise plan only for now (see Oct 23). Fillers, speaking
  speed, Ear mode, early answers, digit hold, the interruption and silence settings and end phrases
  are shown greyed out on it, with the reason.
  Through the API: the model `openai-gpt-live-1`, `voice.realtimeVoice`, and `billing.billedOn`
  and `billing.chargedMicro` on a call. [Voice](https://docs.thinnest.ai/channels/voice.md#speech-to-speech-openai-gpt-live-1)
* **Early answers, on or off.** The agent starts its reply on what it has heard so far and
  throws it away if the caller goes on; the tokens of a thrown-away reply are billed to your
  own model key on an agent that uses one, and are not in the call's `usage`. Switch **Early
  answers** off on the Voice page, or send `voice.earlyAnswers: false`, to start a reply only
  once the caller has finished. On by default. [Voice](https://docs.thinnest.ai/channels/voice.md#early-answers)
* **What each call was about, in the export.** The call export from Usage (and
  `GET /v1/usage/calls?format=csv`) now ends with the call's summary and a column for each
  detail the agent collected, such as the caller's name or the reason they called. The
  columns before them are unchanged. [Usage](https://docs.thinnest.ai/workspace/usage.md)
* **Billing details in Settings.** A billing name, so invoices can carry your company's
  legal name rather than the workspace name, and your GST number, both in Settings →
  General before the billing address. [Usage](https://docs.thinnest.ai/workspace/usage.md)
* **No character limit on the Playground's instructions.** Saving from the agent page no longer
  refuses long instructions, and the box shows only the count. The API still accepts up to
  20,000 characters. [Behaviour](https://docs.thinnest.ai/agent/behaviour.md)

**Oct 21, 2026**

Your own lead and hand-over rules, Test Chat as a call, the number a caller rang

**New**

* **`ownRules`: leave our lead and hand-over sentences out.** If you write those rules
  yourself, set `ownRules: true` on Create Agent or Update Agent and the agent is no
  longer told to refuse names and numbers, to never promise a follow-up or when to hand
  over. The boundary, the AI disclosure, the reply language and the date stay. Off by
  default. [Behaviour](https://docs.thinnest.ai/agent/behaviour.md#writing-your-own-lead-and-hand-over-rules)
* **Test Chat as a call.** `mode: "call"` runs a test turn with the agent's call prompt
  and the thinking level a call uses, so you can try wording the way a caller will get
  it. [Test chat](https://docs.thinnest.ai/agent/custom-api.md#during-a-test-chat)
* **The number a caller rang.** Get Call and List Calls now carry `to`: your number a
  call came in on, so a workspace with several numbers can tell which line it was.
  Calls from before today have it empty.

**Improved**

* **A forward under your own keys** is billed at the flat price of those keys, not the
  agent's voice plan. [Forwarding a whole line](https://docs.thinnest.ai/channels/phone-numbers.md#forwarding-a-whole-line)

**Oct 19, 2026**

Webhooks, forwarded calls and Test Chat

**Fixed**

* **Choosing `contact.erased` or `byok.changed` on a webhook.** Create Webhook and Update
  Webhook answered `500` when an endpoint named either event. Both are saved now.
  [Webhooks](https://docs.thinnest.ai/api-reference/webhooks.md)

**Improved**

* **What a forwarded call costs is spelled out.** A call forwarded to a phone on a number
  we rent is billed for every connected second at the voice plan of the agent attached to
  the number, or the Standard plan when none is (the flat own-key price where your own
  keys apply); it is not the carrier-only charge, and it is not recorded. [Forwarding a whole line](https://docs.thinnest.ai/channels/phone-numbers.md#forwarding-a-whole-line)
* **Rent Phone Number takes an `Idempotency-Key`,** so a retry returns the first answer
  instead of renting a second number.
* **A shared voice clone keeps your own voice `id`** inside every customer.
  [Voice cloning](https://docs.thinnest.ai/channels/voice-clone.md#your-customers-can-use-your-voices)
* **Lending a number to a second agent ends no call.** A call waiting to be placed that
  named that number fails with a clear message. [Numbers](https://docs.thinnest.ai/channels/phone-numbers.md)
* **Test Chat** says that it runs the agent as saved, and what a reply costs on your own
  model key.

**Oct 17, 2026**

Languages and re-ask on the API, clearer billing notes

**New**

* **Reply languages on the API.** `languages` on Create Agent and Update Agent sets the
  console's "one, or up to four": `[]` for auto, one name for that language, two to
  four for the languages the agent expects, the first being its fallback. Get Agent
  returns it. [Behaviour](https://docs.thinnest.ai/agent/behaviour.md#reply-language)
* **`billing` on List Calls.** Every call in the list now carries what it was billed as
  (the key choice, the voice plan, the per-minute rate, the billed seconds and the
  currency), the same object as Get Call, so reconciling a page of calls needs no
  call per row.
* **`voice.reaskAfterSeconds` is in the API reference.** It could already be set; it was
  missing from the schema. [Voice](https://docs.thinnest.ai/channels/voice.md)

**Improved**

* **What a call was billed as is clearer.** A call that ended before the agent spoke is
  charged the carrier's fee only, in 30-second blocks. A free trial call is one paid
  from a free-plan workspace's trial minutes.

**Fixed**

* **Update Agent's own-model response.** The `409` for the agent's own model said the
  workspace was "not using its own voice key". It now says the language-model key
  is the one that is missing.

**Oct 15, 2026**

Find leads: describe the businesses you want and your agent finds them

**New**

* **Find leads.** Describe the businesses you want to reach — "real-estate
  developers in Pune" — and an agent finds them and brings back their phone numbers
  and emails, with a link to where each came from. Save them to Contacts and a group, then call them with an agent
  or send them a WhatsApp broadcast. The first 50 are free in your first month;
  after that ₹1 a lead, and you only pay for leads that have a phone number or
  email. [Find leads](https://docs.thinnest.ai/agent/find-leads.md)
* **Save a search and run it again.** Name a search to keep it on the start screen;
  running it again charges only for businesses you do not already have.
  [Find leads](https://docs.thinnest.ai/agent/find-leads.md#save-a-search-run-it-again)

**Improved**

* **Leads has two tabs.** **Find leads** is first; the people who came to your
  agents are on **Inbound leads**. [Leads and contacts](https://docs.thinnest.ai/agent/leads.md)

**Oct 15, 2026**

What each call was billed as; delete one call's content; shorter retention; developers' voices for their customers; two new webhooks

**New**

* **What each call was billed as.** Get Call and the `call.analysed` webhook now
  carry `billing`: whose keys the call ran on (`keys`: `off` for ours, or `all`,
  `voice`, `llm`, `llm_voice`), the voice plan it was priced on (`voicePlan`;
  null on the flat own-key prices), its per-minute rate fixed when it started
  (`ratePerMinuteMicro`) and the seconds it was charged for (`billedSeconds`).
  [Get Call](https://docs.thinnest.ai/api-reference/calls/get-call.md)
* **Characters sent to the voice, per call.** `usage.ttsCharacters` counts the
  text sent to the voice to be spoken — replies, the greeting and fixed lines —
  on your own voice key too. It includes sentences sent before the caller
  interrupted, which is what voice providers charge for.
  [Get Call](https://docs.thinnest.ai/api-reference/calls/get-call.md)
* **Estimated token counts are marked.** `usage.inputTokensEstimated` is `true`
  when part of a call's input token count was estimated because the model's
  provider reported none. [Get Call](https://docs.thinnest.ai/api-reference/calls/get-call.md)
* **`contact.erased` webhook.** Sent once a contact you deleted is gone
  completely, recordings included — straight away, or after the nightly retry
  when a recording could not be deleted at once. Only the contact's id and when.
  [Webhooks](https://docs.thinnest.ai/api-reference/webhooks.md#workspace-events)
* **`byok.changed` webhook.** Sent when one of your own keys is added, replaced,
  removed or refused by its provider, and when your own keys are switched on or
  off or set to cover different jobs. Never carries a key.
  [Webhooks](https://docs.thinnest.ai/api-reference/webhooks.md#workspace-events)
* **Delete one call's recording and transcript.** `DELETE /calls/{id}/content`
  removes a call's recording, its turns, its summary and the details collected
  from it, and keeps the call's billing record. Get Call then shows
  `contentDeleted: true`. [Your data](https://docs.thinnest.ai/workspace/data-and-erasure.md#deleting-one-calls-recording-and-transcript)
* **Keep calls for less time.** Set `callRetentionDays` on your workspace to
  delete calls' recordings and transcripts sooner than your plan does, from
  1 day up to your plan's limit. [How long calls are kept](https://docs.thinnest.ai/workspace/data-and-erasure.md#how-long-calls-are-kept)
* **Your customers can use your cloned voices.** Every voice a developer clones
  can now be used by all its customer workspaces, marked
  `sharedFromDeveloper` in `GET /voices`. Only the developer can rename or
  delete it. [Voice Clone](https://docs.thinnest.ai/channels/voice-clone.md#your-customers-can-use-your-voices)
* **Your own voices are marked.** Each voice in `GET /byok/voices` now says
  `own`: `true` for a voice you cloned or designed on your provider account
  (Cartesia, ElevenLabs, Soniox), `false` for the provider's library.
  [Bring your own keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md#voices)

**Oct 14, 2026**

Speaking speed; the agent stops sooner, and at once, when a caller talks over it

**New**

* **Over two hundred more Premium voices.** Named for the voice and its style, with the accent (Hindi, Indian English,
  Hindi–English mix and seven more Indian languages) in the hover text beside what it is for: conversational, customer
  care, sales, banking, narrator, news and more. Search the Premium tab by accent or style. Voices you already use are unchanged.
  [Voices](https://docs.thinnest.ai/guides/how-your-agent-sounds.md#pick-the-voice-by-listening)
* **A question with no answer is asked again.** When the agent asks something
  on a call and hears nothing, it asks the same question again after 2.5
  seconds, once — instead of waiting in silence for your "Are you still there?".
  Change the wait, or turn it off, on the Voice page. Through the API,
  `voice.reaskAfterSeconds`. [Voice](https://docs.thinnest.ai/channels/voice.md#your-own-limits)
* **An agent can speak a few languages.** The language picker on the Playground
  and Settings now takes up to four. The agent answers in whichever of them the
  customer speaks, and falls back to the first; on a call the speech recogniser
  listens only for those, so a short reply is no longer written down in a
  language nobody on the call speaks. [Reply language](https://docs.thinnest.ai/agent/behaviour.md#reply-language)
* **Speaking speed.** Set how fast your agent talks on calls with a slider, from
  slower to faster, on the Playground, right under the voice. Most Standard and
  Premium voices follow it. Through the API,
  `voice.speakingSpeed`. [Voice](https://docs.thinnest.ai/channels/voice.md#speaking-speed)

**Improved**

* **"Are you still there?" in the call's language.** On a call where the caller
  had not yet said anything the agent could read the language from, it used to
  ask in English; it now asks in the language of its own opening line.
  [Voice](https://docs.thinnest.ai/channels/voice.md#your-own-limits)
* **The agent stops while a website caller is still talking over it.** It used to
  finish its sentence and stop only once the caller had finished theirs. Now it
  stops once they have talked over it for about as long as your **Words needed to
  cut the agent off** — a hum or a quick "okay" still changes nothing — and if it
  was stopped by something that was not words, it asks the caller to go on.
  [Interrupting](https://docs.thinnest.ai/channels/voice.md#interrupting)
* **Ear mode listens in real time, and phone callers can stop the agent
  mid-sentence too.** An agent set to **Ear** under **How agent knows the caller
  has finished** stops as soon as it has heard enough of the caller's words, or a
  "wait", usually a second or two in, instead of once they have finished. It
  ignores its own voice coming back down the line, lets a listener's "haan ji,
  bilkul" pass without stopping, and waits through a pause mid-thought instead of
  answering half a sentence — saying a short "haan ji" while it waits. Ear is
  billed at the rate of the voice, like any other call. Both behaviours have a switch and a box for your own words —
  **Backchannel detection** with **Caller backchannel words**, and **Agent speaks
  backchannel / acknowledgement while the caller explains** with **Agent
  backchannel phrases** — and API fields to match.
  [Ear: real-time speech recognition](https://docs.thinnest.ai/channels/voice.md#ear-real-time-speech-recognition)
* **The agent goes quiet the instant it is interrupted.** On some voices it used
  to carry on for up to half a second before stopping.
* **The agent's "haan ji" now comes while the caller is still talking.** With
  **Agent speaks backchannel / acknowledgement while the caller explains** on, it
  used to wait for a long pause that someone explaining something rarely makes,
  so it almost never spoke. On website calls it now says its word in the short
  gaps between a caller's sentences, once they have been talking for a few
  seconds, at most twice in a turn; it does not count as the caller being
  interrupted. On a phone call it still waits for a longer pause.
  [Ear: real-time speech recognition](https://docs.thinnest.ai/channels/voice.md#ear-real-time-speech-recognition)
* **Replies start sooner.** The agent now starts working on its answer the
  moment it has heard what the caller said, while it is still making sure they
  have finished, so the first words come a fifth of a second or so earlier on
  every turn, whichever model your agent uses. If the caller was not finished,
  that early answer is dropped and never spoken or recorded. The short silence
  some voices put in front of each reply is no longer played, which saves up to
  most of a second on those voices.

**Oct 13, 2026**

Warm and cold hand-offs; Actions, Voice and Playground, redesigned

**New**

* **Bring your own language model and voice together.** A new set for bring your own
  keys: your LLM account answers and your voice account speaks, while we keep the
  speech recogniser. A call is a flat ₹1 a minute, as with all three keys, on any
  model your key offers. Choose **My voice and my language model** in **Settings →
  Your keys**, or `scope: "llm_voice"` on the API.
  [Bring your own keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md)
* **Each agent chooses how it uses your keys.** The scope you pick for the
  workspace is the default; an agent can follow it, be switched off your keys, or
  use a different set your saved keys allow, so one agent can run on your language
  model while another uses your language model and your voice. In the console it
  is **How Agent uses your keys** on the agent's pages; in the API, the agent's
  `byok` is `null` (follow the workspace), `"off"`, or a scope, and a scope your
  keys cannot serve is refused with the missing key named.
  [Bring your own keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md)
* **Tokens used on every call.** Get Call and the `call.analysed` webhook now carry
  `usage`: the `inputTokens`, `outputTokens` and `cachedInputTokens` the call's
  replies used, including on your own model key, each null when not recorded.
  [Get Call](https://docs.thinnest.ai/api-reference/calls/get-call.md)
* **Warm or cold, when a call is handed on.** Each agent a call can be handed to
  is **warm** (it gets a short summary and the conversation, and opens by saying
  who it is and why the caller is there) or **cold** (it starts fresh and greets
  the caller as on a new call). [Voice](https://docs.thinnest.ai/channels/voice.md#handing-a-call-on)
* **Warm transfers to a person.** With **Call transfer**, the person who answers
  can first hear a short spoken summary of the call before the caller is
  connected, and with **Press 1 to accept** the caller is connected only once
  they press 1, so a voicemail never takes the call. Cold, as before, stays the
  default. [Escalation](https://docs.thinnest.ai/agent/escalation.md#on-a-phone-call-putting-the-caller-through)
* **In the API**, `handOver.transferMode`, `handOver.acceptKey` and each hand-off
  agent's `mode`; `handedTo` on calls now says each hand-off's `mode` and `summary`.
  [Update Built-in Tools](https://docs.thinnest.ai/api-reference/tools/update-built-in-tools.md)

**Improved**

* **The Actions page is in three tabs.** **Built in**, **On calls** and **Connect a
  service**, with the open tab kept in the address. A line under the title shows
  how many tools are on, how many services are connected and how many agents calls
  can be handed to, and a tool that is on but missing something it needs shows an
  amber **Not in use yet**. [Actions](https://docs.thinnest.ai/agent/actions.md)
* **The Voice page is in seven sections.** Calls, How Agent speaks, Listening, Sound
  and recording, Ending calls, Memory, and Call length and silence, with links
  along the top, **Save changes** always in view, and **Test a call** staying
  in view beside the settings on a wide screen (first, above them, on a narrower one). [Voice](https://docs.thinnest.ai/channels/voice.md)
* **The Playground is in four cards.** Language and model, Voice, What Agent says,
  and Reply length. The page used to say changes save immediately; they apply
  once you press **Save changes**. [Behaviour](https://docs.thinnest.ai/agent/behaviour.md)
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

**Oct 12, 2026**

Calls that read better, an own-voice tuning panel, safer do-not-call

**New**

* **Bring only your own language model.** Use your own LLM account, such as Gemini
  or OpenAI, while we keep the speech recogniser and the voice. Calls stay on the
  same per-minute voice plan as any other call (Standard, Premium or Studio), whatever
  model your key runs, and chat replies cost ₹0.02. Choose it in **Settings → Your
  keys**, or with `scope: "llm"` on the API.
  [Bring your own keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md)
* **Tune your own Cartesia voice for each agent.** Speed, volume, emotion, the
  Sonic model (including `sonic-3.6`) and a pronunciation dictionary can be set
  per agent in the console, through the API and in MCP, and heard in the console
  and the API before you save. [Tune a Cartesia voice](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md)
* **The who-is-calling lookup moved to the Actions page.** It is now a card of its
  own there, no longer on the Voice page; nothing about how it works changed.
  [Who-is-calling lookup](https://docs.thinnest.ai/channels/voice.md#who-is-calling-lookup)
* **Choose how the agent decides the caller has finished speaking.** `voice.turnDetection`
  (Smart, Timer or Ear) is now on the API next to the silence setting.
  [Voice](https://docs.thinnest.ai/channels/voice.md)
* **Switch off the do-not-call tool for an agent.** `voice.recordDoNotCall` and a
  switch on the Voice page. The `contact.opted_out` webhook now carries the words
  the caller used, so you can see why a number was added.
  [Voice](https://docs.thinnest.ai/channels/voice.md) and [Webhooks](https://docs.thinnest.ai/api-reference/webhooks.md)
* **A reply in your customer's language in chat.** With **Match the customer**,
  website chat, WhatsApp, Telegram, the Playground and test chat now answer in the
  language of a message written in an Indian script. Messages typed in English
  letters are left to the agent's judgement. [Reply language](https://docs.thinnest.ai/agent/behaviour.md#reply-language)

**Improved**

* **The agent asks before adding someone to the do-not-call list.** "That's all,
  you can hang up" no longer counts as "do not call me again", and the agent
  quotes the caller's words when it does add a number.
* **What was never heard is no longer treated as said.** When a caller talks over
  the agent, the agent now knows which part was cut off and the transcript is
  corrected to the part the caller heard where it can be.
  [Voice](https://docs.thinnest.ai/channels/voice.md)
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
  [Bring your own keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md)

**Fixed**

* **A reply that was retried on a backup model no longer runs together.** The same
  sentence could be said, and stored, twice with no space between the pieces.
* **"I'll take care of that" no longer ends a call** as if it were a goodbye.

**Oct 10-11, 2026**

Every Voice page setting on the API, a test-chat marker, model call prices

**New**

* **Every setting on the Voice page can now be read and changed through the API
  and the MCP server.** Fillers and their timing, how long a pause ends the
  caller's turn, how many words cut the agent off, never interrupt, the
  background sound and its volume, hanging up when the conversation ends,
  asking "are you still there?", ending a call on silence or on a phrase, and
  the call instructions. A read returns every value with its default filled in,
  and a number outside its range is refused with a message instead of being
  moved. [Voice](https://docs.thinnest.ai/channels/voice.md#the-settings) and
  [Update Agent](https://docs.thinnest.ai/api-reference/agents/update-agent.md)
* **Choose where an agent answers calls.** `voice.surfaces` sets phone, your
  website's call button and WhatsApp calls. Adding the phone to an agent that
  answers calls but has no number is refused with the code
  `phone_number_required`. [Where it answers](https://docs.thinnest.ai/channels/voice.md#turn-it-on) and
  [Errors](https://docs.thinnest.ai/api-reference/errors.md)
* **Your endpoint can tell a test chat from a real customer.** Every action
  request made during an API test chat carries an `X-Test-Chat: true` header, and
  `{{test.chat}}` fills as `true`, so you can answer without writing anything to
  your system. [During a test chat](https://docs.thinnest.ai/agent/custom-api.md#during-a-test-chat)
* **Each model shows what a call on it costs.** `GET /models` now returns
  `callTier`, `callPricePerMinuteMicro` and `currency` (the currency of the
  wallet your calls are charged to). A model marked premium puts every call on the
  premium rate. A workspace using its own keys is billed the BYOK rate whatever
  the model. [Model](https://docs.thinnest.ai/agent/behaviour.md#model)
* **Your own cloned voices on Cartesia.** The voice list starts with the voices
  you cloned and then reads the whole library, and a clone can be set on an
  agent. [Choose an agent's voice](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md#choose-an-agents-voice)

**Improved**

* **Agent instructions can be 20,000 characters in the console too.** The box
  used to stop at 8,000 while the API accepted more. Conversation steps are limited
  separately. [Instructions](https://docs.thinnest.ai/agent/behaviour.md#instructions)

* **A forwarded call on a number with no agent** appears in Usage, Get Call and
  the call list with no agent, and does not create an inbox conversation or a
  webhook. [Forwarding a whole line](https://docs.thinnest.ai/channels/phone-numbers.md#forwarding-a-whole-line)
  **Fixed**

* **Studio voices need the Pro plan or above,** not Scale as one guide said.
  [How your agent sounds](https://docs.thinnest.ai/guides/how-your-agent-sounds.md)

* **A cloned Cartesia voice that was missing from the list,** and so was refused
  when you set it on an agent, is listed and accepted.
  [Choose an agent's voice](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md#choose-an-agents-voice)

* **The background sound's volume now shows what callers actually hear.** The
  Voice page slider and the API report 15% (0.15) when you have not set one; the
  page used to show 18%. [Background sound](https://docs.thinnest.ai/channels/voice.md#background-sound)

**Oct 9, 2026**

Callers by name, call hand-offs, forwarding, contact groups

**New**

* **Your agent knows who is calling.** When someone rings from a number saved in
  your Contacts, the agent is told their name and can greet them with it. It is
  also told to confirm who it is talking to before discussing an account, because
  a caller's number can be faked. [Who is calling](https://docs.thinnest.ai/channels/voice.md#who-is-calling)
* **Look the caller up in your own system.** Give an agent a web address and we
  ask your system who is calling before the agent answers, so it can open with
  their last order or their plan. You have two seconds to reply, and the request
  is signed so you know it came from us.
  [Who-is-calling lookup](https://docs.thinnest.ai/channels/voice.md#who-is-calling-lookup)
* **Hand a call to another of your agents.** Sales can pass a caller to support
  in the middle of a call. It is the same line and the same conversation, and the
  other agent sees everything said so far.
  [Handing a call on](https://docs.thinnest.ai/channels/voice.md#handing-a-call-on)
* **Forward a whole phone line.** Choose **Forward calls** in a number's menu
  and every call to it rings a phone of your choice, with no agent speaking. It
  works whether or not an agent answers the number, so use it as a fallback while
  you fix or switch off an agent.
  [Forwarding a whole line](https://docs.thinnest.ai/channels/phone-numbers.md#forwarding-a-whole-line)
* **Set how long outbound calls ring.** Between 10 and 60 seconds, for an agent
  on the Voice page or for one call through the API. Calls now stop ringing
  after 30 seconds unless you set it; on some carriers they used to ring longer.
  [How long it rings](https://docs.thinnest.ai/channels/voice.md#how-long-it-rings)
* **Move a number between your customers.** If you build on the developer API, a
  number can move between your workspace and your customers' workspaces and keep
  its digits, from the number's menu or the API.
  [Moving a number](https://docs.thinnest.ai/channels/phone-numbers.md#moving-a-number-to-another-workspace)
* **See how each call went.** Open a call in Usage to see who it was handed to
  or forwarded to, how long the caller waited for each reply, long silences,
  interruptions and any replies that needed a backup. A new `call.problem` webhook tells you the moment something
  goes wrong on a live call.
  [How a call went](https://docs.thinnest.ai/workspace/usage.md#how-a-call-went)
* **Contact groups.** Build named lists of contacts, such as "Wholesale buyers",
  and aim a broadcast or a voice campaign at exactly those people.
  [Groups](https://docs.thinnest.ai/agent/leads.md#groups)

**Improved**

* **Every webhook event has a documented example,** and the ids in webhooks
  always carry their `conv_` or `cmp_` prefix, so a value from a webhook can go
  straight into the API. [Event payloads](https://docs.thinnest.ai/api-reference/webhooks.md#event-payloads)
* **An agent that is on a live call cannot be deleted,** so a call is never cut
  off by a clean-up. The API says why in a clear error.
  [Errors](https://docs.thinnest.ai/api-reference/errors.md)
* **The Buy tab on Phone Numbers stays visible on a plan that cannot buy,** and
  tells you why, instead of disappearing.
  [Getting a number from us](https://docs.thinnest.ai/channels/phone-numbers.md#getting-a-number-from-us)

**Fixed**

* **A call from your website that never connects now gives up after 45
  seconds** and frees the line, instead of showing "Connecting" forever.
  Reloading the page ends a live call, and the "line busy" message names the
  limit. [A call button in your chat](https://docs.thinnest.ai/channels/voice.md#a-call-button-in-your-chat)

**Oct 8, 2026**

One language per agent, per-agent keys, erasure and error codes

**New**

* **Pick a language for each agent.** An agent has one language: choose it when
  you create the agent, on the Playground or in Settings, or leave it on **Match
  the customer**. The old "second language" setting is retired. You can also
  rename an agent from the sidebar. [Reply language](https://docs.thinnest.ai/agent/behaviour.md#reply-language)
* **Keep one agent off your own keys.** If your workspace brings its own provider
  keys, an individual agent can choose to stay on ours.
  [Bring your own keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md)
* **Erase a contact, and their recordings go too.** Erasing a contact now also
  removes the recordings of their calls on numbers you brought. On pay-as-you-go,
  you can ask us to exclude your workspace from model training.
  [Data and erasure](https://docs.thinnest.ai/workspace/data-and-erasure.md)
* **Say what a switched-off line tells the caller.** When Answer calls is off,
  the caller hears a sentence you wrote, where the phone provider allows it.
  [When Answer calls is off](https://docs.thinnest.ai/channels/voice.md#when-answer-calls-is-off)
* **Every API refusal carries a code you can act on.** Branch on `code` rather
  than on the wording of the message. [Errors](https://docs.thinnest.ai/api-reference/errors.md)
* **Business details (KYC) for rented Indian numbers, by API.** Submit and
  follow the business details an Indian number needs, without the console.
  [India needs your business verified first](https://docs.thinnest.ai/channels/phone-numbers.md#india-needs-your-business-verified-first)

**Improved**

* **A WhatsApp template you sent looks the same in the inbox as it did to the
  customer,** with its picture, cards and buttons.
  [Inbox](https://docs.thinnest.ai/workspace/inbox.md)
* **The agent speaks sooner while it looks something up,** with its own wording
  or a short one of ours, and it no longer says a generic "I see" just before the
  answer. A new setting sets the gap before a second line.
  [Fillers before tool run](https://docs.thinnest.ai/channels/voice.md#fillers-before-tool-run)
* **A shorter wait before the agent's first answer on a call.**
  [Voice](https://docs.thinnest.ai/channels/voice.md)

**Fixed**

* **The agent no longer answers its own echo** on calls where the speech
  recogniser used to hear the agent's own voice as the caller.
* **A caller repeating the agent's words is no longer ignored.** Someone who
  answers "I would like to see the pediatrician" in the agent's own words now
  gets a reply. [Interrupting](https://docs.thinnest.ai/channels/voice.md#interrupting)

**Oct 7, 2026**

A full API reference, SDKs, texting the caller, new default voice

**New**

* **An API reference with a page for every endpoint.** About 180 operations,
  each with typed fields, cURL, JavaScript and Python examples, a **Try it**
  panel and sample responses. [API reference](https://docs.thinnest.ai/api-reference/introduction.md)
* **TypeScript and Python SDKs.** Every operation is a typed method, with
  retries and pagination built in. [SDKs](https://docs.thinnest.ai/api-reference/sdks.md)
* **Text the caller.** Your agent can send an SMS during a call, and a WhatsApp
  message or SMS after it ends, through your own SMS provider and sender ID.
  [SMS](https://docs.thinnest.ai/channels/sms.md), [After the call](https://docs.thinnest.ai/agent/after-the-call.md) and
  [a worked guide](https://docs.thinnest.ai/guides/text-the-caller.md)
* **The MCP server covers the whole console.** An AI assistant such as Claude
  Code or Cursor can now do almost anything you can do in the console, with your
  approval for anything that reaches a customer, including drafting and
  launching campaigns. [MCP tools](https://docs.thinnest.ai/mcp/tools.md)
* **Bring only your own voice.** Use your own voice account while we supply
  speech recognition, the model and the phone line, at ₹1.50 a minute. Calls run
  on low-cost models in this mode.
  [Bring your own keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md)
* **Webhooks are signed with their delivery time** and carry an `evt_` id that
  stays the same across retries. [Delivery](https://docs.thinnest.ai/api-reference/webhooks.md#delivery)
* **Failed webhooks are retried, and you can send them again** yourself.
  [Retries](https://docs.thinnest.ai/api-reference/webhooks.md#retries)

**Improved**

* **New agents start on the Premium voice Kavya,** because the standard voices
  sounded robotic on a first call. Change it any time from the voice picker. Calls
  on a new agent are billed at the Premium rate until you do.
  [Voice](https://docs.thinnest.ai/channels/voice.md#voice)
* **New agents start on the Prana \[Voice] model.**
  [Model](https://docs.thinnest.ai/agent/behaviour.md#model)
* **Replies start sooner after a caller stops speaking,** and the agent is better
  at telling a finished sentence from a pause.
  [Voice](https://docs.thinnest.ai/channels/voice.md)
* **The call's cost is on its result in the API.**
  [Get Call](https://docs.thinnest.ai/api-reference/calls/get-call.md)

**Oct 6, 2026**

Build on the API, white label on every paid plan

**New**

* **Build your own product on ThinnestAI.** Create a workspace for each of your
  customers, reach all of them with one key and a `Thinnest-Workspace` header, and
  receive one webhook for every customer.
  [Customers](https://docs.thinnest.ai/api-reference/customers.md) and
  [Build a platform](https://docs.thinnest.ai/guides/build-a-platform.md)
* **White label on every paid plan.** Resell the console under your own brand and
  domain: 3 clients on Pay As You Go, 20 on Pro and 100 on Scale. Each client has
  its own plan and call lines, and starts on a free trial that you set and pay for.
  A reseller with no domain yet gets a free preview address.
  [White label](https://docs.thinnest.ai/white-label/overview.md), [Clients](https://docs.thinnest.ai/white-label/clients.md),
  [Brand and domains](https://docs.thinnest.ai/white-label/brand-and-domains.md) and
  [Your prices](https://docs.thinnest.ai/white-label/prices.md)
* **Each agent picks its own model from your keys,** and a single call can name
  one of your voices. Speechmatics is back among the providers.
  [Bring your own keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.